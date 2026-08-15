"""Flock planning, placement, feed, and mortality rules (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_flock,
    assert_placement,
    create_contract_payload,
    create_feed_delivery_payload,
    create_flock_payload,
    create_grower_payload,
    create_house_payload,
    create_mortality_report_payload,
    create_placement_payload,
    create_settlement_group_payload,
    get_success_data,
    plan_flock,
    record_audit,
    schedule_placement,
    set_logical_clock,
    setup_growing_flock,
    setup_harvested_flock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
LIVEHAUL = TEST_USERS["livehaul_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestFlockPlanning:
    def test_flock_computed_fields_initialize(self, api, admin_headers):
        """PRD §3.3: "A planned flock starts in `PLANNED` status with
        `placed_head` zero, all derived counters at zero, `adj_fcr`,
        `livability_pct`, and `performance_score` null, and `condemnation_pct`
        at zero."

        Design: Corner/entities/flock_computed_fields_ignore_client_input
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-CF",
                                                    full_name="Computed Fields"),
                              admin_headers))
        house = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=5000),
                             admin_headers))
        contract = get_success_data(
            api.create_contract(create_contract_payload(grower["id"],
                                                        contract_no="C-CF"),
                                admin_headers))
        get_success_data(api.activate_contract(contract["id"], admin_headers))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-CF",
                                                week_ending_date="2026-12-31"),
                ANALYST))

        data = validate_success(
            api.create_flock(create_flock_payload(house["id"], contract["id"],
                                                  group["id"], flock_no="F-CF"),
                             admin_headers),
            expected_status=201)
        assert_flock(data)
        assert data["status"] == "PLANNED"
        assert data["placed_head"] == 0
        assert data["feed_delivered_lbs"] == 0
        assert data["live_weight_lbs"] == 0
        assert data["mortality_head"] == 0
        assert data["condemnation_head"] == 0
        assert data["adj_fcr"] is None
        assert data["livability_pct"] is None
        assert data["performance_score"] is None
        assert data["condemnation_pct"] == 0


class TestPlacements:
    def test_placement_initial_state_scheduled(self, api, admin_headers):
        """PRD §3.3: "A placement starts `SCHEDULED` and may be cancelled
        (`SCHEDULED` → `CANCELLED`) or confirmed by an `IntegratorAdmin`."
        PRD §3.3: "Confirming a placement moves it `SCHEDULED` → `CONFIRMED`,
        stamps its `confirmed_date` with the current logical date".

        Design: Corner/state_machines/placement_initial_state_scheduled
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-S2",
                                                    full_name="State Two"),
                              admin_headers))
        house = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=5000),
                             admin_headers))
        contract = get_success_data(
            api.create_contract(create_contract_payload(grower["id"],
                                                        contract_no="C-S2"),
                                admin_headers))
        get_success_data(api.activate_contract(contract["id"], admin_headers))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-S2",
                                                week_ending_date="2026-12-31"),
                ANALYST))
        flock = plan_flock(house["id"], contract["id"], group["id"], "F-S2")

        placement = validate_success(
            api.schedule_placement(flock["id"], create_placement_payload(
                scheduled_date="2026-08-01", head_count=4000), admin_headers),
            expected_status=201)
        assert_placement(placement)
        assert placement["status"] == "SCHEDULED"
        assert placement["confirmed_date"] is None

    def test_placement_confirm_cascades_flock_and_house(self, api, admin_headers):
        """PRD §3.3: "On confirmation, three cascades fire together: the flock
        transitions `PLANNED` → `PLACED` with `placed_head` set from the
        placement's `head_count` and `placed_date` set from the placement's
        `confirmed_date`, and the flock's `livability_pct` is computed for the
        first time; the house transitions `ACTIVE` → `PLACED`, which recomputes
        the grower's `house_count`".

        Design: Corner/state_machines/placement_confirm_cascades_flock_and_house
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-S4",
                                                    full_name="State Four"),
                              admin_headers))
        house = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=9000),
                             admin_headers))
        contract = get_success_data(
            api.create_contract(create_contract_payload(grower["id"],
                                                        contract_no="C-S4"),
                                admin_headers))
        get_success_data(api.activate_contract(contract["id"], admin_headers))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-S4",
                                                week_ending_date="2026-12-31"),
                ANALYST))
        flock = plan_flock(house["id"], contract["id"], group["id"], "F-S4")
        placement = schedule_placement(flock["id"], "2026-08-01", 7000)

        confirmed = validate_success(
            api.confirm_placement(placement["id"], admin_headers))
        assert confirmed["status"] == "CONFIRMED"

        flock_data = validate_success(api.get_flock(flock["id"], admin_headers))
        assert flock_data["status"] == "PLACED"
        assert flock_data["placed_head"] == 7000
        assert flock_data["placed_date"] == confirmed["confirmed_date"]

        house_data = validate_success(api.get_house(house["id"], admin_headers))
        assert house_data["house_status"] == "PLACED"

    def test_placement_head_count_over_capacity_rejected(self, api,
                                                         admin_headers):
        """PRD §3.3: "An `IntegratorAdmin` schedules a placement against a
        planned flock with a `scheduled_date` and a `head_count` — the number
        of chicks to be delivered, which must be greater than zero and no more
        than the target house's `capacity_birds`."
        PRD §2.8: "11. Quantity sanity — positive weights and head counts,
        capacity limits, cumulative mortality bounds (`ERR_QUANTITY_INVALID`)."

        Design: Corner/validations/placement_head_count_over_capacity_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-V1",
                                                    full_name="Valid One"),
                              admin_headers))
        house = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=5000),
                             admin_headers))
        contract = get_success_data(
            api.create_contract(create_contract_payload(grower["id"],
                                                        contract_no="C-V1"),
                                admin_headers))
        get_success_data(api.activate_contract(contract["id"], admin_headers))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-V1",
                                                week_ending_date="2026-12-31"),
                ANALYST))
        flock = plan_flock(house["id"], contract["id"], group["id"], "F-V1")

        resp = api.schedule_placement(flock["id"], create_placement_payload(
            scheduled_date="2026-08-01", head_count=5001), admin_headers)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_INVALID)


class TestFeedDelivery:
    def test_first_delivery_flips_placed_to_growing_and_accumulates(
            self, api, admin_headers):
        """PRD §3.3: "Every accepted delivery adds its `feed_lbs` into the
        flock's `feed_delivered_lbs`. The very first delivery for a flock also
        flips it `PLACED` → `GROWING`; subsequent deliveries accumulate without
        further status change."

        Design: Corner/state_machines/feed_delivery_first_flips_placed_to_growing
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-S5",
                                                    full_name="State Five"),
                              admin_headers))
        house = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=9000),
                             admin_headers))
        contract = get_success_data(
            api.create_contract(create_contract_payload(grower["id"],
                                                        contract_no="C-S5"),
                                admin_headers))
        get_success_data(api.activate_contract(contract["id"], admin_headers))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-S5",
                                                week_ending_date="2026-12-31"),
                ANALYST))
        flock = plan_flock(house["id"], contract["id"], group["id"], "F-S5")
        placement = schedule_placement(flock["id"], "2026-08-01", 7000)
        get_success_data(api.confirm_placement(placement["id"], admin_headers))

        get_success_data(
            api.record_feed_delivery(
                flock["id"],
                create_feed_delivery_payload(delivered_date="2026-08-05",
                                             feed_lbs=3000, feed_type="STARTER",
                                             ticket_no="FT-S5a"),
                admin_headers))
        mid = validate_success(api.get_flock(flock["id"], admin_headers))
        assert mid["status"] == "GROWING", "first delivery flips PLACED -> GROWING"
        assert mid["feed_delivered_lbs"] == 3000

        get_success_data(
            api.record_feed_delivery(
                flock["id"],
                create_feed_delivery_payload(delivered_date="2026-08-06",
                                             feed_lbs=2500, feed_type="GROWER",
                                             ticket_no="FT-S5b"),
                admin_headers))
        after = validate_success(api.get_flock(flock["id"], admin_headers))
        assert after["feed_delivered_lbs"] == 5500
        assert after["status"] == "GROWING", \
            "second delivery accumulates without further status change"

    def test_duplicate_feed_ticket_rejected(self, api, admin_headers):
        """PRD §3.3: "An `IntegratorAdmin` records each `FeedDelivery` against
        a flock with its `delivered_date`, the `feed_lbs` delivered (must be
        positive), the ration phase `feed_type` — one of `STARTER`, `GROWER`,
        `FINISHER`, or `WITHDRAWAL` — and a unique feed-mill `ticket_no`."
        PRD §2.8: "12. Uniqueness — no duplicate of a unique identifier
        (`ERR_DUPLICATE`)."

        Design: Corner/errors/error_duplicate_feed_ticket
        """
        ctx = setup_growing_flock(grower_code="G-ER1", full_name="Error One",
                                  contract_no="C-ER1", group_code="WK-ER1",
                                  flock_no="F-ER1", placed_head=1000,
                                  feed_lbs=1000, ticket_no="FT-DUP",
                                  set_clock_to="2026-08-01T00:00:00Z")
        flock_id = ctx["flock"]["id"]

        resp = api.record_feed_delivery(
            flock_id,
            create_feed_delivery_payload(delivered_date="2026-08-06",
                                         feed_lbs=500, feed_type="GROWER",
                                         ticket_no="FT-DUP"),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

        data = validate_success(api.get_flock(flock_id, admin_headers))
        assert data["feed_delivered_lbs"] == 1000, \
            "the rejected duplicate delivery must not accumulate"


class TestMortalityReporting:
    def test_cumulative_mortality_exceeding_placed_rejected(self, api,
                                                            admin_headers):
        """PRD §3.3: "Quantity sanity is enforced at intake with
        `ERR_QUANTITY_INVALID` (HTTP 422): the cumulative mortality plus
        condemnation across all of a flock's reports must never exceed its
        `placed_head`."

        Design: Corner/validations/cumulative_mortality_exceeding_placed_rejected
        """
        ctx = setup_growing_flock(
            grower_code="G-V2", full_name="Valid Two", contract_no="C-V2",
            group_code="WK-V2", flock_no="F-V2", placed_head=1000,
            feed_lbs=1000, set_clock_to="2026-08-01T00:00:00Z",
            mortality=(600, 0), mortality_date="2026-08-10")
        flock_id = ctx["flock"]["id"]

        resp = api.record_mortality_report(
            flock_id,
            create_mortality_report_payload(report_date="2026-08-11",
                                            dead_head=401, condemned_head=0),
            ctx["grower_headers"])
        validate_error(resp, ApiErrorId.ERR_QUANTITY_INVALID)

    def test_derived_fields_reconcile_on_mortality_post(self, api,
                                                        admin_headers):
        """PRD §3.3: "Each report adds its `dead_head` into the flock's
        `mortality_head` and its `condemned_head` into the flock's
        `condemnation_head`, then recomputes the flock's `livability_pct` —
        placed head minus mortality head, divided by placed head — and its
        `condemnation_pct` — condemnation head divided by the larger of one and
        (placed head minus mortality head)."
        PRD §2.6: "Rate and ratio quantities that feed the tournament scoring —
        `adj_fcr`, `livability_pct`, `condemnation_pct`, `performance_score`,
        `performance_rating`, and the three group averages — are computed and
        stored to exactly 4 decimal places using round-half-up."

        Design: Corner/cross_cutting_complexity_layers/derived_fields_reconcile_on_mortality_post
        """
        ctx = setup_growing_flock(
            grower_code="G-DF", full_name="Derived Fields", contract_no="C-DF",
            group_code="WK-DF", flock_no="F-DF", placed_head=10000,
            feed_lbs=1000, capacity_birds=20000,
            set_clock_to="2026-08-01T00:00:00Z")
        flock_id = ctx["flock"]["id"]

        get_success_data(
            api.record_mortality_report(
                flock_id,
                create_mortality_report_payload(report_date="2026-08-10",
                                                dead_head=300, condemned_head=40),
                ctx["grower_headers"]))

        data = validate_success(api.get_flock(flock_id, admin_headers))
        assert data["mortality_head"] == 300
        assert data["condemnation_head"] == 40
        assert data["livability_pct"] == pytest.approx(0.97, abs=1e-9), \
            "livability = (10000 - 300) / 10000"
        # 40/9700 stored to exactly 4 decimal places per PRD §2.6.
        assert data["condemnation_pct"] == pytest.approx(0.0041, abs=1e-9)


class TestBodyForeignKeyResolution:
    def test_flock_with_nonexistent_contract_reference_rejected(
            self, api, admin_headers):
        """PRD §2.5: "Separately, identifiers that arrive in the request body —
        the `contract_id`, `settlement_group_id`, or `crew_id` supplied when
        planning a flock or scheduling a catch, and analogous foreign keys such
        as `grower_id` or `house_id` on creation payloads — are validated after
        the path resolves; a body reference that does not resolve is rejected
        with `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/body_fk_reference_not_found
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        grower = get_success_data(
            api.create_grower(create_grower_payload(grower_code="G-V5",
                                                    full_name="Valid Five"),
                              admin_headers))
        house = get_success_data(
            api.create_house(create_house_payload(grower["id"], house_no="H1",
                                                  capacity_birds=5000),
                             admin_headers))
        group = get_success_data(
            api.create_settlement_group(
                create_settlement_group_payload(group_code="WK-V5",
                                                week_ending_date="2026-12-31"),
                ANALYST))

        resp = api.create_flock(
            create_flock_payload(house["id"], NON_EXISTENT_UUID, group["id"],
                                 flock_no="F-V5"),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


class TestPlacementSafety:
    def _setup_house_in_downtime_with_new_flock(self, api):
        """House harvested on 2026-09-10 (DOWNTIME until 2026-09-24) with a
        second flock planned on the same house."""
        ctx = setup_harvested_flock(
            grower_code="G-T1", full_name="Temporal Grower", contract_no="C-T1",
            group_code="WK-44", week_ending_date="2026-12-05",
            flock_no="F-T1A", set_clock_to="2026-08-01T00:00:00Z")
        house = validate_success(api.get_house(ctx["house"]["id"], ADMIN))
        assert house["house_status"] == "DOWNTIME"
        assert house["downtime_until"] == "2026-09-24"
        flock2 = plan_flock(ctx["house"]["id"], ctx["contract"]["id"],
                            ctx["group"]["id"], "F-T1B")
        return ctx, flock2

    def test_placement_on_downtime_until_date_rejected(self, api,
                                                       admin_headers):
        """PRD §3.3: "Placement creation is guarded by house safety: if the
        flock's house is `QUARANTINED`, or its `downtime_until` covers the
        scheduled date, the request is rejected with `ERR_HOUSE_IN_DOWNTIME`
        (HTTP 409)."
        PRD §3.1: "A house's `downtime_until` field — an ISO date until which
        the house is barred from placement — starts null and is set by harvest
        completion and biosecurity failures, as later subsections describe."

        Design: Difficulty/resource_temporal_overlap/house_downtime_half_open_placement_boundary
        """
        _ctx, flock2 = self._setup_house_in_downtime_with_new_flock(api)

        resp = api.schedule_placement(flock2["id"], create_placement_payload(
            scheduled_date="2026-09-24", head_count=5000), admin_headers)
        validate_error(resp, ApiErrorId.ERR_HOUSE_IN_DOWNTIME)

    def test_placement_day_after_downtime_until_allowed(self, api,
                                                        admin_headers):
        """PRD §3.4: "Releasing downtime moves a house `DOWNTIME` → `ACTIVE`;
        it requires the current logical date to be after `downtime_until`" —
        the downtime window is barred through `downtime_until` itself, so the
        first placeable date is the day after.
        PRD §3.3: "Placement creation is guarded by house safety: if the
        flock's house is `QUARANTINED`, or its `downtime_until` covers the
        scheduled date, the request is rejected with `ERR_HOUSE_IN_DOWNTIME`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/house_downtime_half_open_placement_boundary
        """
        _ctx, flock2 = self._setup_house_in_downtime_with_new_flock(api)

        placement = validate_success(
            api.schedule_placement(flock2["id"], create_placement_payload(
                scheduled_date="2026-09-25", head_count=5000), admin_headers),
            expected_status=201)
        assert_placement(placement)
        assert placement["status"] == "SCHEDULED"


class TestPlacementStateBeforeSafety:
    def _setup_cancelled_placement_in_quarantined_house(self, api):
        """Flock F-P1 harvested (house DOWNTIME); flock F-P1B planned with a
        placement scheduled 2026-09-30; FAIL audit quarantines the house; the
        placement is then cancelled."""
        ctx = setup_harvested_flock(
            grower_code="G-P1", full_name="Priority Grower", contract_no="C-P1",
            group_code="WK-39", week_ending_date="2026-10-31",
            flock_no="F-P1", set_clock_to="2026-08-01T00:00:00Z")
        flock2 = plan_flock(ctx["house"]["id"], ctx["contract"]["id"],
                            ctx["group"]["id"], "F-P1B")
        placement2 = schedule_placement(flock2["id"], "2026-09-30", 5000)
        record_audit(ctx["house"]["id"], "2026-09-15", "FAIL", 21)
        house = validate_success(api.get_house(ctx["house"]["id"], ADMIN))
        assert house["house_status"] == "QUARANTINED"
        get_success_data(api.cancel_placement(placement2["id"], ADMIN))
        return ctx, flock2, placement2

    def test_confirm_cancelled_placement_surfaces_invalid_state(
            self, api, admin_headers):
        """PRD §2.8: "When multiple validation rules could reject the same
        request, they are evaluated in a fixed priority order so that the
        surfaced error is deterministic:"
        PRD §2.8: "5. Transition legality — the target entity is in a
        from-state of the requested transition (`ERR_INVALID_STATE`)."
        PRD §2.8: "7. House placement safety — the house is not quarantined
        and the scheduled placement date clears any downtime
        (`ERR_HOUSE_IN_DOWNTIME`)."

        Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_placement_into_placed_house
        """
        _ctx, _flock2, placement2 = (
            self._setup_cancelled_placement_in_quarantined_house(api))

        resp = api.confirm_placement(placement2["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_confirm_leaves_placement_cancelled(self, api,
                                                         admin_headers):
        """PRD §3.3: "A placement starts `SCHEDULED` and may be cancelled
        (`SCHEDULED` → `CANCELLED`) or confirmed by an `IntegratorAdmin`."
        PRD §2.8: "5. Transition legality — the target entity is in a
        from-state of the requested transition (`ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_placement_into_placed_house
        """
        ctx, flock2, placement2 = (
            self._setup_cancelled_placement_in_quarantined_house(api))

        resp = api.confirm_placement(placement2["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        placements = validate_success(
            api.list_placements(flock2["id"], admin_headers))
        by_id = {p["id"]: p for p in placements}
        assert by_id[placement2["id"]]["status"] == "CANCELLED", \
            "the rejected confirmation must not move the placement"

        house = validate_success(api.get_house(ctx["house"]["id"], admin_headers))
        assert house["house_status"] == "QUARANTINED", \
            "the rejected confirmation must not touch the house"
