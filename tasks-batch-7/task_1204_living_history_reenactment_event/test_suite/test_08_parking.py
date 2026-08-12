"""Parking: explicit-lot capacity boundary, unit conservation across
issue/void, the deterministic server-side lot selector, and void gating."""
from test_helpers import (
    TEST_USERS,
    api_client,
    ApiErrorId,
    issue_parking_pass_payload,
    ticket_line,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_signed_agreement,
    create_event,
    create_site_area,
    issue_parking_pass,
    open_registration,
    publish_event,
    set_clock,
    setup_paid_order,
    setup_published_event,
)
from test_helpers.test_users import make_spectator_headers

ORG = TEST_USERS["organizer_headers"]


def _published_event_with_paid_order(lot_capacity=5, buyer="spec-1"):
    """Published event, one PARKING lot of the given capacity, one PAID order
    (single ADULT_DAY line). Returns (event, lot, order)."""
    event = create_event()
    lot = create_site_area(event["id"], area_kind="PARKING",
                           capacity_units=lot_capacity, area_name="Lot B")
    add_signed_agreement(event["id"], "LANDOWNER_USE")
    add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
    open_registration(event["id"])
    publish_event(event["id"])
    order = setup_paid_order(event["id"], buyer=buyer,
                             lines=[ticket_line("ADULT_DAY", 1)])
    return event, lot, order


def _lot_units(lot_id):
    return validate_success(api_client.get_site_area(lot_id, ORG), 200)["allocated_units"]


class TestParkingCapacityBoundary:
    def test_parking_capacity_inclusive_boundary(self, api):
        """PRD §3.7: "the lot's `allocated_units` plus the needed units must not
        exceed `capacity_units`, inclusive (`ERR_PARKING_CAPACITY_EXCEEDED`)"
        PRD §3.7: "Each pass occupies computed `units_used`: one unit for
        `STANDARD`, two for `OVERSIZE`."

        Design: Difficulty/boundary_precision_check/parking_capacity_inclusive_boundary
        """
        event, lot, order = _published_event_with_paid_order(lot_capacity=5)

        p1 = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="RV-001",
                                vehicle_class="OVERSIZE", site_area_id=lot["id"])
        p2 = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="RV-002",
                                vehicle_class="OVERSIZE", site_area_id=lot["id"])
        p3 = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="CAR-03",
                                vehicle_class="STANDARD", site_area_id=lot["id"])
        assert _lot_units(lot["id"]) == 5, "2 + 2 + 1 fills the lot to exactly capacity"

        fourth = api_client.issue_parking_pass(
            order["id"],
            issue_parking_pass_payload(vehicle_plate="CAR-04", vehicle_class="STANDARD",
                                       site_area_id=lot["id"]),
            make_spectator_headers("spec-1"),
        )
        validate_error(fourth, ApiErrorId.ERR_PARKING_CAPACITY_EXCEEDED, 409)
        assert _lot_units(lot["id"]) == 5, "the rejected pass consumes nothing"

    def test_parking_capacity_exact_fill_with_oversize(self, api):
        """PRD §3.7: "the lot's `allocated_units` plus the needed units must not
        exceed `capacity_units`, inclusive (`ERR_PARKING_CAPACITY_EXCEEDED`)"

        Design: Difficulty/boundary_precision_check/parking_capacity_inclusive_boundary
        """
        event, lot, order = _published_event_with_paid_order(lot_capacity=4)
        issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="RV-001",
                           vehicle_class="OVERSIZE", site_area_id=lot["id"])
        second = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="RV-002",
                                    vehicle_class="OVERSIZE", site_area_id=lot["id"])
        assert second["status"] == "ACTIVE", "the second oversize pass exactly fills the lot"
        assert _lot_units(lot["id"]) == 4

        over = api_client.issue_parking_pass(
            order["id"],
            issue_parking_pass_payload(vehicle_plate="CAR-03", vehicle_class="STANDARD",
                                       site_area_id=lot["id"]),
            make_spectator_headers("spec-1"),
        )
        validate_error(over, ApiErrorId.ERR_PARKING_CAPACITY_EXCEEDED, 409)
        assert _lot_units(lot["id"]) == 4


class TestIssueVoidConservation:
    def test_parking_units_issue_void_conservation(self, api):
        """PRD §3.7: "for a `PARKING` area, the sum of `units_used` over its
        `ACTIVE` parking passes" (§3.5 exposes the computed `allocated_units`)
        PRD §3.7: "voiding it — by the owning spectator or an organizer, valid
        only from `ACTIVE` (`ERR_INVALID_PASS_STATUS`) — moves it to `VOIDED` and
        decrements the lot's `allocated_units` by `units_used`."

        Design: Difficulty/compensating_invariant/parking_units_issue_void_conservation
        """
        event, lot, order = _published_event_with_paid_order(lot_capacity=10)

        oversize = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="RV-001",
                                      vehicle_class="OVERSIZE", site_area_id=lot["id"])
        assert _lot_units(lot["id"]) == 2, "oversize pass moves the lot by 2 units"
        standard = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="CAR-02",
                                      vehicle_class="STANDARD", site_area_id=lot["id"])
        assert _lot_units(lot["id"]) == 3

        voided = validate_success(
            api_client.void_parking_pass(oversize["id"], make_spectator_headers("spec-1")), 200
        )
        assert voided["status"] == "VOIDED"
        assert _lot_units(lot["id"]) == 1, (
            "the compensating void restores exactly the forward delta"
        )

        third = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="CAR-03",
                                   vehicle_class="STANDARD", site_area_id=lot["id"])
        assert _lot_units(lot["id"]) == 2, (
            "allocated_units always equals the sum over ACTIVE passes"
        )
        passes = validate_success(
            api_client.list_order_parking_passes(order["id"], make_spectator_headers("spec-1")),
            200,
        )
        by_id = {p["id"]: p for p in passes}
        assert by_id[oversize["id"]]["status"] == "VOIDED"
        assert by_id[standard["id"]]["status"] == "ACTIVE"
        assert by_id[third["id"]]["status"] == "ACTIVE"

    def test_parking_units_conservation_void_all(self, api):
        """PRD §3.7: "`VOIDED` passes never count toward lot occupancy."
        PRD §3.7: "voiding it — by the owning spectator or an organizer, valid
        only from `ACTIVE` (`ERR_INVALID_PASS_STATUS`) — moves it to `VOIDED` and
        decrements the lot's `allocated_units` by `units_used`."

        Design: Difficulty/compensating_invariant/parking_units_issue_void_conservation
        """
        event, lot, order = _published_event_with_paid_order(lot_capacity=10)
        p1 = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="RV-001",
                                vehicle_class="OVERSIZE", site_area_id=lot["id"])
        p2 = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="RV-002",
                                vehicle_class="OVERSIZE", site_area_id=lot["id"])
        assert _lot_units(lot["id"]) == 4

        api_client.void_parking_pass(p1["id"], make_spectator_headers("spec-1"))
        assert _lot_units(lot["id"]) == 2
        api_client.void_parking_pass(p2["id"], ORG)
        assert _lot_units(lot["id"]) == 0, "voiding every pass returns the lot to empty"

        fresh = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="RV-003",
                                   vehicle_class="OVERSIZE", site_area_id=lot["id"])
        assert fresh["status"] == "ACTIVE"
        assert _lot_units(lot["id"]) == 2


class TestVoidGate:
    def test_void_already_voided_pass_rejected(self, api):
        """PRD §3.7: "voiding it — by the owning spectator or an organizer, valid
        only from `ACTIVE` (`ERR_INVALID_PASS_STATUS`) — moves it to `VOIDED` and
        decrements the lot's `allocated_units` by `units_used`."

        Design: Corner/state_machines/void_already_voided_pass_rejected
        """
        event, lot, order = _published_event_with_paid_order(lot_capacity=10)
        parking = issue_parking_pass(order["id"], buyer="spec-1", vehicle_plate="CAR-01",
                                     vehicle_class="STANDARD", site_area_id=lot["id"])
        first = validate_success(
            api_client.void_parking_pass(parking["id"], make_spectator_headers("spec-1")), 200
        )
        assert first["status"] == "VOIDED"
        assert _lot_units(lot["id"]) == 0

        second = api_client.void_parking_pass(parking["id"], make_spectator_headers("spec-1"))
        validate_error(second, ApiErrorId.ERR_INVALID_PASS_STATUS, 409)
        assert _lot_units(lot["id"]) == 0, "a rejected void never decrements twice"


class TestAutoLotSelector:
    def test_auto_lot_selector_empty_pool_rejected(self, api):
        """PRD §3.7: "When the lot is omitted, the server selects it
        deterministically: eligibility is every `PARKING` area of the event that
        is `ACTIVE` and whose remaining capacity — `capacity_units` minus
        `allocated_units` — is at least the needed units; ranking is by remaining
        capacity descending; ties break by earliest `created_at`, never by `id`;
        and an empty pool is rejected with `ERR_NO_PARKING_AVAILABLE`."

        Design: Corner/validations/auto_lot_selector_empty_pool_rejected
        """
        event = setup_published_event()  # no site areas at all
        order = setup_paid_order(event["id"], buyer="spec-1",
                                 lines=[ticket_line("ADULT_DAY", 1)])
        resp = api_client.issue_parking_pass(
            order["id"],
            issue_parking_pass_payload(vehicle_plate="CAR-01", vehicle_class="STANDARD"),
            make_spectator_headers("spec-1"),
        )
        validate_error(resp, ApiErrorId.ERR_NO_PARKING_AVAILABLE, 409)

    def test_auto_lot_selector_ranking_and_tiebreak(self, api):
        """PRD §3.7: "ranking is by remaining capacity descending; ties break by
        earliest `created_at`, never by `id`"
        PRD §3.7: "The chosen lot is echoed back in the pass's `site_area_id`"

        Design: Corner/endpoints/auto_lot_selector_ranking_and_tiebreak
        """
        event = create_event()
        # Distinct created_at values make the tie-break deterministic.
        set_clock("2026-05-01T00:00:00Z")
        lot_t1 = create_site_area(event["id"], area_kind="PARKING", capacity_units=10,
                                  area_name="Lot T1")
        set_clock("2026-05-02T00:00:00Z")
        lot_t2 = create_site_area(event["id"], area_kind="PARKING", capacity_units=10,
                                  area_name="Lot T2")
        add_signed_agreement(event["id"], "LANDOWNER_USE")
        add_signed_agreement(event["id"], "INSURANCE_LIABILITY")
        open_registration(event["id"])
        publish_event(event["id"])
        order = setup_paid_order(event["id"], buyer="spec-1",
                                 lines=[ticket_line("ADULT_DAY", 1)])

        first = validate_success(
            api_client.issue_parking_pass(
                order["id"],
                issue_parking_pass_payload(vehicle_plate="CAR-01", vehicle_class="STANDARD"),
                make_spectator_headers("spec-1"),
            ),
            201,
        )
        assert first["site_area_id"] == lot_t1["id"], (
            "equal remaining capacity ties break by earliest created_at"
        )
        second = validate_success(
            api_client.issue_parking_pass(
                order["id"],
                issue_parking_pass_payload(vehicle_plate="CAR-02", vehicle_class="STANDARD"),
                make_spectator_headers("spec-1"),
            ),
            201,
        )
        assert second["site_area_id"] == lot_t2["id"], (
            "T2 now has the larger remaining capacity and wins the ranking"
        )
