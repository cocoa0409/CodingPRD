"""Supply allocation, depot accounting, conservation, returns, and stock
capacity (PRD §2.7, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_depot_returnables_conserved,
    brief_event,
    create_adult_waiver,
    create_depot,
    create_event,
    get_depot,
    get_supply,
    issue_supplies,
    make_coordinator_headers,
    make_group_leader_headers,
    setup_active_agreement,
    validate_error,
    validate_success,
)
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

COORD = make_coordinator_headers()


class TestSupplyAllocation:
    def test_supply_allocation_water_surcharge_and_caps(self, api):
        """PRD §3.5: "`vests_issued` is exactly the `expected_volunteers`
        count; `grabbers_issued` is one grabber per two volunteers, rounded up;
        and `bags_issued` starts from the volunteer count multiplied by two
        bags per volunteer per mile and by the segment's `mile_length`, rounded
        up to a whole bag — and when the segment is water-adjacent, that
        rounded quantity is multiplied by one and a quarter and rounded up
        again. For an event expecting 7 volunteers on a 2.0-mile water-adjacent
        reach, issuance is 7 vests, 4 grabbers, and 35 bags; the same event on
        a dry roadside segment yields 7 vests, 4 grabbers, and 28 bags."

        Design: Difficulty/combinatorial_formula/supply_allocation_water_surcharge_and_caps
        """
        depot = create_depot(bags=500, vests=100, grabbers=50)
        g1, s1, ag1 = setup_active_agreement(
            group_name="Riverkeepers", contact_email="gina@riverkeepers.org",
            route_name="River Rd", mile_marker_start=4.0, mile_marker_end=6.0,
            segment_type="RIVERBANK", water_adjacent=True,
        )
        g2, s2, ag2 = setup_active_agreement(
            group_name="Road Rangers", org_type="BUSINESS",
            contact_email="rob@roadrangers.com",
            route_name="Hill Rd", mile_marker_start=10.0, mile_marker_end=12.0,
            segment_type="ROADWAY", water_adjacent=False,
        )
        ew = create_event(ag1["id"], g1["id"], scheduled_date="2026-09-10",
                          expected_volunteers=7)
        er = create_event(ag2["id"], g2["id"], scheduled_date="2026-09-10",
                          expected_volunteers=7)

        w = issue_supplies(ew["id"], g1["id"], depot["id"])
        r = issue_supplies(er["id"], g2["id"], depot["id"])

        assert w["vests_issued"] == 7
        assert w["grabbers_issued"] == 4
        assert w["bags_issued"] == 35

        assert r["vests_issued"] == 7
        assert r["grabbers_issued"] == 4
        assert r["bags_issued"] == 28

        dep = get_depot(depot["id"])
        assert dep["bags_on_hand"] == 437
        assert dep["vests_on_hand"] == 86
        assert dep["grabbers_on_hand"] == 42

    def test_supply_allocation_grabbers_round_up(self, api):
        """PRD §3.5: "`grabbers_issued` is one grabber per two volunteers,
        rounded up"

        Design: Difficulty/combinatorial_formula/supply_allocation_water_surcharge_and_caps
        """
        depot = create_depot(bags=500, vests=100, grabbers=50)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        dist = issue_supplies(event["id"], group["id"], depot["id"])
        assert dist["vests_issued"] == 3
        assert dist["grabbers_issued"] == 2  # ceil(3/2)
        # bags: ceil(3 * 2 * 2.0) = 12; water-adjacent -> ceil(12 * 1.25) = 15
        assert dist["bags_issued"] == 15


class TestDepotPoolCapacity:
    def test_depot_pool_aggregate_capacity_overlap(self, api):
        """PRD §3.5: "The stock gate is evaluated last of all checks: each
        computed line must fit within the depot's on-hand quantity for that
        item, or the entire issuance is refused with
        `ERR_SUPPLY_STOCK_EXCEEDED` — there is no partial issuance."
        PRD §2.7: "For each depot and each returnable item, the server enforces
        an exact conservation invariant after every issue, every return, every
        reconciliation, and every cascade"

        Design: Difficulty/resource_temporal_overlap/depot_pool_aggregate_capacity_overlap
        """
        depot = create_depot(name="North Depot", bags=200, vests=50, grabbers=5)
        group, segment, agreement = setup_active_agreement()
        ea = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-10", expected_volunteers=8)
        da = issue_supplies(ea["id"], group["id"], depot["id"])
        assert da["grabbers_issued"] == 4

        eb = create_event(agreement["id"], group["id"],
                          scheduled_date="2026-09-12", expected_volunteers=4)
        gl = make_group_leader_headers(group["id"])
        # 4 outstanding + 2 new > pool of 5 grabbers.
        resp = api.issue_supplies(eb["id"], {"depot_id": depot["id"]}, gl)
        validate_error(resp, ApiErrorId.ERR_SUPPLY_STOCK_EXCEEDED)

        # Full return frees capacity.
        ret = validate_success(api.return_supplies(
            da["id"], {"returned_vests": 8, "returned_grabbers": 4}, gl), 200)
        assert ret["status"] == "RECONCILED"

        eb_dist = issue_supplies(eb["id"], group["id"], depot["id"])
        assert eb_dist["grabbers_issued"] == 2
        assert eb_dist["bags_issued"] == 20

        dep = get_depot(depot["id"])
        assert dep["grabbers_on_hand"] == 3
        assert dep["vests_on_hand"] == 46
        assert dep["bags_on_hand"] == 140

    def test_no_partial_issuance_on_stock_breach(self, api):
        """PRD §3.5: "the entire issuance is refused with
        `ERR_SUPPLY_STOCK_EXCEEDED` — there is no partial issuance."

        Design: Difficulty/resource_temporal_overlap/depot_pool_aggregate_capacity_overlap
        """
        depot = create_depot(name="North Depot", bags=200, vests=50, grabbers=1)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=4)
        gl = make_group_leader_headers(group["id"])
        resp = api.issue_supplies(event["id"], {"depot_id": depot["id"]}, gl)
        validate_error(resp, ApiErrorId.ERR_SUPPLY_STOCK_EXCEEDED)
        # Depot unchanged: nothing debited.
        dep = get_depot(depot["id"])
        assert dep["bags_on_hand"] == 200
        assert dep["vests_on_hand"] == 50
        assert dep["grabbers_on_hand"] == 1


class TestReturnablesConservation:
    def test_depot_returnables_conserved_on_full_return(self, api):
        """PRD §2.7: "As a compensating pair, an issue followed by a full
        return of the same units leaves the depot's on-hand count identical to
        its pre-issue value."
        PRD §2.7: "bags are consumable and are never returned, so
        `bags_on_hand` only ever decreases through issuance."

        Design: Difficulty/compensating_invariant/depot_returnables_conserved_on_full_return
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=7)
        dist = issue_supplies(event["id"], group["id"], depot["id"])

        pre = get_depot(depot["id"])
        assert pre["vests_on_hand"] == 33
        assert pre["grabbers_on_hand"] == 16
        assert pre["bags_on_hand"] == 65

        gl = make_group_leader_headers(group["id"])
        ret = validate_success(api.return_supplies(
            dist["id"], {"returned_vests": 7, "returned_grabbers": 4}, gl), 200)
        assert ret["status"] == "RECONCILED"

        post = get_depot(depot["id"])
        assert post["vests_on_hand"] == 40
        assert post["grabbers_on_hand"] == 20
        assert post["bags_on_hand"] == 65
        assert post["lost_vests_total"] == 0
        assert post["lost_grabbers_total"] == 0

    def test_conservation_invariant_holds_while_issued(self, api):
        """PRD §2.7: "the depot's on-hand count for the item, plus the
        outstanding quantity across all of that depot's distributions still in
        `ISSUED` or `PARTIALLY_RETURNED`, plus the depot's cumulative lost
        total for the item, must equal the pinned pool total."

        Design: Difficulty/compensating_invariant/depot_returnables_conserved_on_full_return
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=7)
        dist = issue_supplies(event["id"], group["id"], depot["id"])
        dep = get_depot(depot["id"])
        assert_depot_returnables_conserved(dep, [get_supply(dist["id"])])


class TestSupplyReturns:
    def test_supply_return_exceeding_issued_rejected(self, api):
        """PRD §3.5: "any return that would push the cumulative returned count
        for an item above its issued count is rejected with
        `ERR_RETURN_EXCEEDS_ISSUED`."

        Design: Corner/validations/supply_return_exceeding_issued_rejected
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=7)
        dist = issue_supplies(event["id"], group["id"], depot["id"])
        gl = make_group_leader_headers(group["id"])

        resp = api.return_supplies(
            dist["id"], {"returned_vests": 7, "returned_grabbers": 5}, gl)
        validate_error(resp, ApiErrorId.ERR_RETURN_EXCEEDS_ISSUED)

        ok = validate_success(api.return_supplies(
            dist["id"], {"returned_vests": 7, "returned_grabbers": 4}, gl), 200)
        assert ok["status"] == "RECONCILED"

    def test_supply_return_cumulative_exceed_check(self, api):
        """PRD §3.5: "any return that would push the cumulative returned count
        for an item above its issued count is rejected with
        `ERR_RETURN_EXCEEDS_ISSUED`."

        Design: Corner/validations/supply_return_exceeding_issued_rejected
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=7)
        dist = issue_supplies(event["id"], group["id"], depot["id"])
        gl = make_group_leader_headers(group["id"])
        # Two partial returns whose cumulative grabbers exceed 4 issued.
        validate_success(api.return_supplies(
            dist["id"], {"returned_vests": 0, "returned_grabbers": 3}, gl), 200)
        resp = api.return_supplies(
            dist["id"], {"returned_vests": 0, "returned_grabbers": 2}, gl)
        validate_error(resp, ApiErrorId.ERR_RETURN_EXCEEDS_ISSUED)

    def test_second_supply_issue_for_same_event_rejected(self, api):
        """PRD §3.5: "because exactly one distribution may exist per event, a
        second issuance for the same event is refused with
        `ERR_SUPPLY_ALREADY_ISSUED`."

        Design: Corner/validations/second_supply_issue_for_same_event_rejected
        """
        depot = create_depot(bags=500, vests=100, grabbers=50)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        issue_supplies(event["id"], group["id"], depot["id"])
        gl = make_group_leader_headers(group["id"])
        resp = api.issue_supplies(event["id"], {"depot_id": depot["id"]}, gl)
        validate_error(resp, ApiErrorId.ERR_SUPPLY_ALREADY_ISSUED)
        dep = get_depot(depot["id"])
        assert dep["grabbers_on_hand"] == 48  # only the first issue debited 2

    def test_second_supply_issue_does_not_double_debit(self, api):
        """PRD §3.5: "On success the distribution is created `ISSUED` with its
        three issued quantities recorded ... and the depot's on-hand counts are
        debited."

        Design: Corner/validations/second_supply_issue_for_same_event_rejected
        """
        depot = create_depot(bags=500, vests=100, grabbers=50)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        issue_supplies(event["id"], group["id"], depot["id"])
        gl = make_group_leader_headers(group["id"])
        resp = api.issue_supplies(event["id"], {"depot_id": depot["id"]}, gl)
        validate_error(resp, ApiErrorId.ERR_SUPPLY_ALREADY_ISSUED)
        dep = get_depot(depot["id"])
        assert dep["vests_on_hand"] == 97
        assert dep["bags_on_hand"] == 485

    def test_return_after_reconcile_rejected(self, api):
        """PRD §3.5: "A distribution already `RECONCILED` refuses further
        returns with `ERR_SUPPLY_ALREADY_RECONCILED`"

        Design: Corner/validations/return_after_reconcile_rejected
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        dist = issue_supplies(event["id"], group["id"], depot["id"])
        gl = make_group_leader_headers(group["id"])
        validate_success(api.return_supplies(
            dist["id"], {"returned_vests": 3, "returned_grabbers": 2}, gl), 200)
        resp = api.return_supplies(
            dist["id"], {"returned_vests": 0, "returned_grabbers": 0}, gl)
        validate_error(resp, ApiErrorId.ERR_SUPPLY_ALREADY_RECONCILED)

    def test_partial_supply_return_then_completion(self, api):
        """PRD §3.5: "if outstanding units remain and `mark_remaining_lost`
        was not set, the distribution moves from `ISSUED` to
        `PARTIALLY_RETURNED` (or stays `PARTIALLY_RETURNED` across successive
        partial returns); if the return completes the full balance, the
        distribution moves to `RECONCILED`. When `mark_remaining_lost` is set,
        the outstanding balance is written off rather than restocked — the
        distribution's `lost_vests` and `lost_grabbers` are set to the
        outstanding counts, the depot's `lost_vests_total` and
        `lost_grabbers_total` grow by those amounts — and the distribution
        moves straight to `RECONCILED`."

        Design: Corner/endpoints/partial_supply_return_then_completion
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        dist = issue_supplies(event["id"], group["id"], depot["id"])
        gl = make_group_leader_headers(group["id"])

        p = validate_success(api.return_supplies(
            dist["id"], {"returned_vests": 3, "returned_grabbers": 1}, gl), 200)
        assert p["status"] == "PARTIALLY_RETURNED"

        fin = validate_success(api.return_supplies(
            dist["id"],
            {"returned_vests": 0, "returned_grabbers": 0,
             "mark_remaining_lost": True},
            COORD), 200)
        assert fin["status"] == "RECONCILED"
        assert fin["lost_grabbers"] == 1

        dep = get_depot(depot["id"])
        assert dep["grabbers_on_hand"] == 19
        assert dep["lost_grabbers_total"] == 1

    def test_partial_return_stays_partially_returned(self, api):
        """PRD §3.5: "the distribution moves from `ISSUED` to
        `PARTIALLY_RETURNED` (or stays `PARTIALLY_RETURNED` across successive
        partial returns)"

        Design: Corner/endpoints/partial_supply_return_then_completion
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        dist = issue_supplies(event["id"], group["id"], depot["id"])
        gl = make_group_leader_headers(group["id"])
        p1 = validate_success(api.return_supplies(
            dist["id"], {"returned_vests": 1, "returned_grabbers": 0}, gl), 200)
        assert p1["status"] == "PARTIALLY_RETURNED"
        p2 = validate_success(api.return_supplies(
            dist["id"], {"returned_vests": 1, "returned_grabbers": 0}, gl), 200)
        assert p2["status"] == "PARTIALLY_RETURNED"


class TestDepotPools:
    def test_depot_pool_totals_pinned_at_creation(self, api):
        """PRD §2.7: "At creation, the depot's `vests_pool_total` and
        `grabbers_pool_total` are pinned to the initial `vests_on_hand` and
        `grabbers_on_hand` respectively and never change afterward"

        Design: Corner/entities/depot_pool_totals_pinned_at_creation
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        assert depot["vests_pool_total"] == 40
        assert depot["grabbers_pool_total"] == 20

        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=7)
        issue_supplies(event["id"], group["id"], depot["id"])

        dep = get_depot(depot["id"])
        assert dep["vests_pool_total"] == 40
        assert dep["grabbers_pool_total"] == 20
        assert dep["vests_on_hand"] == 33
        assert dep["grabbers_on_hand"] == 16

    def test_pool_totals_do_not_move_on_loss_writeoff(self, api):
        """PRD §2.7: "pinned to the initial `vests_on_hand` and
        `grabbers_on_hand` respectively and never change afterward"

        Design: Corner/entities/depot_pool_totals_pinned_at_creation
        """
        depot = create_depot(name="South Depot", bags=100, vests=40, grabbers=20)
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10", expected_volunteers=3)
        dist = issue_supplies(event["id"], group["id"], depot["id"])
        gl = make_group_leader_headers(group["id"])
        validate_success(api.return_supplies(
            dist["id"],
            {"returned_vests": 0, "returned_grabbers": 0,
             "mark_remaining_lost": True},
            gl), 200)
        dep = get_depot(depot["id"])
        assert dep["vests_pool_total"] == 40
        assert dep["grabbers_pool_total"] == 20


class TestSupplyIssueGuards:
    def test_supply_issue_with_unknown_depot_returns_not_found(self, api):
        """PRD §3.5: "An unresolvable depot reference fails with
        `ERR_DEPOT_NOT_FOUND`"

        Design: Corner/validations/supply_issue_with_unknown_depot_returns_not_found
        """
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        gl = make_group_leader_headers(group["id"])
        resp = api.issue_supplies(
            event["id"], {"depot_id": NON_EXISTENT_UUID}, gl)
        validate_error(resp, ApiErrorId.ERR_DEPOT_NOT_FOUND)

    def test_supply_issue_unknown_depot_http_404(self, api):
        """PRD §3.5: "An unresolvable depot reference fails with
        `ERR_DEPOT_NOT_FOUND`"

        Design: Corner/validations/supply_issue_with_unknown_depot_returns_not_found
        """
        group, segment, agreement = setup_active_agreement()
        event = create_event(agreement["id"], group["id"],
                             scheduled_date="2026-09-10")
        gl = make_group_leader_headers(group["id"])
        resp = api.issue_supplies(
            event["id"], {"depot_id": NON_EXISTENT_UUID}, gl)
        err = validate_error(resp, ApiErrorId.ERR_DEPOT_NOT_FOUND)
        assert resp.status_code == 404
