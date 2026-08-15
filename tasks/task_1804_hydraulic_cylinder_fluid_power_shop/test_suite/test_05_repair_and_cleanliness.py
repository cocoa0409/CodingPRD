"""Repair execution gates: cleanliness code boundaries and assembly preconditions
(PRD §3.6)."""
from test_helpers import (
    ADVISOR,
    ApiErrorId,
    cleanliness_payload,
    complete_assembly,
    consume_all_reservations,
    get_success_data,
    make_technician_headers,
    record_passing_cleanliness,
    setup_in_repair,
    setup_quote_sent,
    start_repair,
    validate_error,
)


class TestCleanlinessCodeBoundary:
    def test_c14_count_8192_maps_to_code_13_and_passes(self, api):
        """PRD §3.6: "Each count maps to an ISO code: the code is zero when the
        count is zero, and otherwise the smallest whole-number code such that the
        count does not exceed two raised to the power of that code — the boundary
        is inclusive, so a count of exactly 8192 maps to code 13 while a count of
        8193 maps to code 14."

        Design: Difficulty/boundary_precision_check/cleanliness_particle_boundary_2pow13
        """
        sc = setup_in_repair()
        wo = get_success_data(
            api.record_cleanliness_check(
                sc.work_order["id"],
                cleanliness_payload(c14_count=8192),
                make_technician_headers(sc.tech["id"]),
            )
        )
        # c4=200000 -> 18, c6=60000 -> 16, c14=8192 -> 13 (2^13 inclusive).
        assert wo["latest_cleanliness_code4"] == 18
        assert wo["latest_cleanliness_code6"] == 16
        assert wo["latest_cleanliness_code14"] == 13
        assert wo["cleanliness_passed"] is True

    def test_c14_count_8193_maps_to_code_14_and_fails(self, api):
        """PRD §3.6: "The sample passes when all three channels meet the shop
        targets: the code of `c4_count` at most `cleanliness_target_code4` (18 by
        default), the code of `c6_count` at most `cleanliness_target_code6` (16
        by default), and the code of `c14_count` at most
        `cleanliness_target_code14` (13 by default)."

        Design: Difficulty/boundary_precision_check/cleanliness_particle_boundary_2pow13
        """
        sc = setup_in_repair()
        wo = get_success_data(
            api.record_cleanliness_check(
                sc.work_order["id"],
                cleanliness_payload(c14_count=8193),
                make_technician_headers(sc.tech["id"]),
            )
        )
        # 8193 > 2^13 -> code 14 > target 13 -> sample fails.
        assert wo["latest_cleanliness_code14"] == 14
        assert wo["cleanliness_passed"] is False


class TestAssemblyGates:
    def test_complete_assembly_without_cleanliness_check_rejected(self, api):
        """PRD §3.6: "The work order's `cleanliness_passed` must be true —
        meaning a sample has been recorded and the latest sample met target on
        all three channels; with no sample on file the flag is false — otherwise
        the completion is rejected with `ERR_CLEANLINESS_CLASS_EXCEEDED`."

        Design: Corner/validations/complete_assembly_without_cleanliness_check_rejected
        """
        sc = setup_in_repair()
        consume_all_reservations(sc.work_order, sc.tech)
        resp = api.complete_assembly(
            sc.work_order["id"], make_technician_headers(sc.tech["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CLEANLINESS_CLASS_EXCEEDED)
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "IN_REPAIR"

    def test_complete_assembly_with_open_reservation_rejected(self, api):
        """PRD §3.6: "Every stock reservation of the work order must be
        `CONSUMED`; any reservation not yet consumed is rejected with
        `ERR_RESERVATION_NOT_OPEN`."

        Design: Corner/validations/complete_assembly_with_open_reservation_rejected
        """
        sc = setup_in_repair()
        record_passing_cleanliness(sc.work_order, sc.tech)
        # The auto-created rod reservation is still OPEN (not consumed).
        resp = api.complete_assembly(
            sc.work_order["id"], make_technician_headers(sc.tech["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_OPEN)
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "IN_REPAIR"

    def test_start_repair_before_approval_rejected(self, api):
        """PRD §3.6: "Once the quote is `APPROVED`, the assigned `Technician`
        starts the physical repair, moving the work order from `APPROVED` to
        `IN_REPAIR`."
        PRD §2.7: "A non-terminal resource addressed from the wrong from-state
        for the requested transition is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/start_repair_before_approval_rejected
        """
        sc = setup_quote_sent(rod_needed=False, honing_passes=0, estimated_labor_hours=1.0)
        resp = api.start_repair(sc.work_order["id"], make_technician_headers(sc.tech["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        wo = get_success_data(api.get_work_order(sc.work_order["id"], ADVISOR))
        assert wo["status"] == "QUOTE_SENT"
