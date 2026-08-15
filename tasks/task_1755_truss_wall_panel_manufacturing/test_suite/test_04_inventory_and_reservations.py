"""Inventory lots and material reservations: conservation, kind discipline, availability."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_jig,
    make_lumber_lot,
    make_plate_lot,
    make_sealed_design,
    explode_cut_list,
    cut_list_line_payload,
    reserve_lumber,
    reserve_plates,
    setup_exploded_list_with_lot,
    setup_sealed_roof_design,
    lot_fresh,
    reservation_fresh,
    assert_lumber_lot_conservation,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
IM = TEST_USERS["inventory_manager_headers"]


class TestLotBoardFeetConservation:
    def test_reserve_then_consume_shifts_without_leak(self, api):
        """PRD §2.8: "For a lumber lot, the quantities `available_bf`, `reserved_bf`,
        `consumed_bf`, and `scrapped_bf` partition what was received: reserving moves
        board feet from available to reserved, releasing moves them back to available
        exactly (release is the compensating action of reserve), consuming moves them
        from reserved to consumed, and scrapping moves them from consumed to scrapped."

        Design: Difficulty/compensating_invariant/lot_board_feet_conservation
        """
        ns = setup_exploded_list_with_lot()
        r1 = reserve_lumber(ns.lot6["id"], ns.lines["TC-1"]["id"], 126.00)
        lot = lot_fresh(ns.lot6["id"])
        assert lot["available_bf"] == pytest.approx(374.00)
        assert lot["reserved_bf"] == pytest.approx(126.00), "reserve moves available to reserved"
        assert_lumber_lot_conservation(lot)

        validate_success(api.consume_reservation(r1["id"], IM))
        lot = lot_fresh(ns.lot6["id"])
        assert lot["reserved_bf"] == pytest.approx(0)
        assert lot["consumed_bf"] == pytest.approx(126.00), "consume shifts reserved to consumed"
        assert lot["available_bf"] == pytest.approx(374.00)
        assert_lumber_lot_conservation(lot)

    def test_release_is_the_exact_compensating_action_of_reserve(self, api):
        """PRD §3.5: "Release moves it to `RELEASED` and restores availability exactly:
        the lot's reserved quantity decreases by the reservation's amount and its
        available quantity increases by the same amount — the exact compensating
        action of the original reserve"."

        Design: Difficulty/compensating_invariant/lot_board_feet_conservation
        """
        ns = setup_exploded_list_with_lot()
        r1 = reserve_lumber(ns.lot6["id"], ns.lines["TC-1"]["id"], 126.00)
        validate_success(api.consume_reservation(r1["id"], IM))
        r2 = reserve_lumber(ns.lot6["id"], ns.lines["TC-1"]["id"], 100.00)
        validate_success(api.release_reservation(r2["id"], IM))

        lot = lot_fresh(ns.lot6["id"])
        assert lot["available_bf"] == pytest.approx(374.00), \
            "the reserve(100.00)/release round trip leaves availability exactly restored"
        assert lot["reserved_bf"] == pytest.approx(0)
        assert lot["consumed_bf"] == pytest.approx(126.00)
        assert lot["scrapped_bf"] == pytest.approx(0)
        assert_lumber_lot_conservation(lot)
        assert reservation_fresh(r1["id"])["status"] == "CONSUMED"
        assert reservation_fresh(r2["id"])["status"] == "RELEASED"


class TestReservationKindAndAvailability:
    def test_reservation_kind_mismatch_and_insufficient_inventory(self, api):
        """PRD §3.5: "Kind discipline is checked first, before availability: a
        reservation against a lumber lot must carry `cut_list_line_id` naming the line
        it feeds, a `reserved_bf` greater than 0, and `reserved_plates` of exactly 0,
        and the lot's `lumber_dimension` and `lumber_grade` must equal the line's cut
        list's design values; a reservation against a plate lot must instead carry
        `cut_list_id`, a `reserved_plates` greater than 0, and `reserved_bf` of
        exactly 0, and the lot's `plate_class` must equal the design's `plating`. Any
        violation is rejected with `ERR_RESERVATION_KIND_MISMATCH` (HTTP 422). Only
        then is availability checked: `reserved_bf` must not exceed the lot's
        `available_bf` (lumber) or `reserved_plates` its `available_plates` (plate),
        and the lot must be `ACTIVE`, else `ERR_INSUFFICIENT_INVENTORY` (HTTP 422)."

        Design: Corner/validations/reservation_kind_mismatch_and_insufficient_inventory
        """
        ns = setup_sealed_roof_design(job_name="Kind Job", contract=100000)
        ns.jig = make_jig()
        ns.cl1, ns.lines = explode_cut_list(
            ns.dsg1["id"], ns.jig["id"], [cut_list_line_payload("TC-1", "L2X6", 12.0, 10)])
        lot_msr = make_lumber_lot(lumber_dimension="L2X6", lumber_grade="SPF_MSR2400",
                                  received_board_feet=500.0)
        lot_syp = make_lumber_lot(lumber_dimension="L2X6", lumber_grade="SYP_NO1",
                                  received_board_feet=500.0)
        plot = make_plate_lot(received_plates=1000)
        line_id = ns.lines["TC-1"]["id"]

        # Board feet against a PLATE lot violates kind discipline.
        resp1 = api.create_reservation(
            {"lot_id": plot["id"], "expected_lot_version": plot["version"],
             "cut_list_line_id": line_id, "reserved_bf": 10.0}, PP)
        validate_error(resp1, ApiErrorId.ERR_RESERVATION_KIND_MISMATCH)

        # Lot grade differs from the design's lumber grade.
        resp2 = api.create_reservation(
            {"lot_id": lot_syp["id"], "expected_lot_version": lot_syp["version"],
             "cut_list_line_id": line_id, "reserved_bf": 10.0}, PP)
        validate_error(resp2, ApiErrorId.ERR_RESERVATION_KIND_MISMATCH)

        # Correct kind but the amount exceeds availability.
        resp3 = api.create_reservation(
            {"lot_id": lot_msr["id"], "expected_lot_version": lot_msr["version"],
             "cut_list_line_id": line_id, "reserved_bf": 600.0}, PP)
        validate_error(resp3, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

        r1 = reserve_lumber(lot_msr["id"], line_id, 126.00)
        assert r1["status"] == "RESERVED"
        assert lot_fresh(lot_msr["id"])["available_bf"] == pytest.approx(374.00)


class TestLotConditionalSchema:
    def test_create_lumber_lot_missing_dimension_returns_invalid_request(self, api):
        """PRD §2.7: "lumber attributes are required exactly when a lot's `lot_kind`
        is `LUMBER`, plate attributes exactly when it is `PLATE`" and "a plate lot's
        `received_board_feet` must be 0 and a lumber lot's `received_plates` must be 0".

        Design: Corner/entities/create_lumber_lot_missing_dimension_returns_invalid_request
        """
        resp1 = api.create_inventory_lot(
            {"lot_kind": "LUMBER", "lumber_grade": "SPF_MSR2400", "received_board_feet": 500.0},
            IM)
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)
        resp2 = api.create_inventory_lot(
            {"lot_kind": "PLATE", "plate_class": "P20", "received_plates": 100,
             "received_board_feet": 10.0}, IM)
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)


class TestImmediateReadAfterWrite:
    def test_reservation_visible_in_next_read(self, api):
        """PRD §3.5: "A successful create decrements the lot's available quantity,
        increments its reserved quantity, and increments the lot's `version`; the
        reservation is born `RESERVED`." and "The reservation list supports filtering
        by `lot_id`, `cut_list_line_id`, `cut_list_id`, and `status`."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        ns = setup_exploded_list_with_lot(job_name="Cons Job")
        r1 = reserve_lumber(ns.lot6["id"], ns.lines["TC-1"]["id"], 126.00)
        lot = lot_fresh(ns.lot6["id"])
        assert lot["available_bf"] == pytest.approx(374.00)
        assert lot["reserved_bf"] == pytest.approx(126.00)
        data, meta = validate_paginated(
            api.list_reservations(IM, params={"lot_id": ns.lot6["id"]}))
        assert meta["total_count"] == 1 and data[0]["id"] == r1["id"], \
            "the very next read sees the created reservation"
