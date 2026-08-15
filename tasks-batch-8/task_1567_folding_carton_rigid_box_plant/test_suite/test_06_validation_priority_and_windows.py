"""Validation-pipeline ordering between error categories, and press booking
half-open window arithmetic (touching endpoints allowed, overlap rejected)."""
from test_helpers import (
    ApiErrorId,
    create_booked_press_window,
    create_customer,
    create_job,
    create_kit_order,
    setup_finished_job,
    setup_press_ready_job,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, KITTER, OPERATOR
from test_helpers.api_client import api_client
from test_helpers.factories import create_press_booking_payload


class TestBookingStateTrumpsWindowConflict:
    def _fixture(self, api, brand_code):
        """JobA PRESS_READY with booking [10:00,12:00) on press P; JobB QUOTED."""
        ctx = setup_press_ready_job(customer_name="Kappa", brand_code=brand_code)
        create_booked_press_window(
            ctx, planned_sheets=130,
            start_utc="2026-08-10T10:00:00Z", end_utc="2026-08-10T12:00:00Z",
        )
        job_b = create_job(ctx["customer"]["id"], quantity_ordered=3000)
        ctx["job_b"] = job_b
        return ctx

    def test_state_error_wins_over_window_conflict(self, api):
        """PRD §2.6: "Every request is screened against a fixed, ordered validation pipeline, and a request that violates several rules surfaces the earliest failure in this order rather than an arbitrary one."
        PRD §3.5: "The job must be `PRESS_READY` or `IN_PRODUCTION`; in any other state the booking is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/priority_pair_validation_conflict/booking_state_trumps_window_conflict
        """
        ctx = self._fixture(api, "KPA")
        # JobB is QUOTED (state violation) AND the window collides with the
        # existing booking on the same press (temporal violation).
        res = api.create_press_booking(
            create_press_booking_payload(
                ctx["job_b"]["id"], ctx["press"]["id"], planned_sheets=100,
                start_utc="2026-08-10T11:00:00Z", end_utc="2026-08-10T13:00:00Z",
            ),
            OPERATOR,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION,
                       expected_status=409)

    def test_state_gate_also_fires_without_any_window_conflict(self, api):
        """PRD §3.5: "The job must be `PRESS_READY` or `IN_PRODUCTION`; in any other state the booking is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/priority_pair_validation_conflict/booking_state_trumps_window_conflict
        """
        ctx = self._fixture(api, "KPB")
        # Control: a non-colliding window proves the state check, not the
        # window screen, is what rejects the QUOTED job's booking.
        res = api.create_press_booking(
            create_press_booking_payload(
                ctx["job_b"]["id"], ctx["press"]["id"], planned_sheets=100,
                start_utc="2026-08-12T11:00:00Z", end_utc="2026-08-12T13:00:00Z",
            ),
            OPERATOR,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION,
                       expected_status=409)


class TestJobCompleteGatePriority:
    def test_rrp_safety_gate_trumps_open_kit_referential_gate(self, api):
        """PRD §2.6: "Every request is screened against a fixed, ordered validation pipeline, and a request that violates several rules surfaces the earliest failure in this order rather than an arbitrary one."
        PRD §3.7: "If the job's `requires_retail_compliance` is true, a `CERTIFIED` retail-ready audit must exist for the job, or completion is rejected with `ERR_RRP_NOT_CERTIFIED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/job_complete_rrp_safety_trumps_open_kit_referential
        """
        ctx = setup_finished_job(customer_name="Lambda", brand_code="LMD",
                                 requires_retail_compliance=True)
        kit = create_kit_order(ctx["job"]["id"], kits_planned=5,
                               components=[{"description": "carton",
                                            "units_per_kit": 2}])
        validate_success(api.start_kit_order(kit["id"], KITTER), 200)

        # No CERTIFIED audit exists AND a kit order is IN_PROGRESS.
        res = api.complete_job(ctx["job"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_RRP_NOT_CERTIFIED, expected_status=409)

        job_after = validate_success(api.get_job(ctx["job"]["id"], ADMIN), 200)
        assert job_after["status"] == "FINISHED"
        kit_after = validate_success(api.get_kit_order(kit["id"], ADMIN), 200)
        assert kit_after["status"] == "IN_PROGRESS"

    def test_open_kit_gate_fires_when_retail_requirement_absent(self, api):
        """PRD §3.7: "And no kit order of the job may still be `PLANNED` or `IN_PROGRESS`, or completion is rejected with `ERR_OPEN_KIT_ORDERS` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/job_complete_rrp_safety_trumps_open_kit_referential
        """
        ctx = setup_finished_job(customer_name="Lambda", brand_code="LMB",
                                 requires_retail_compliance=False)
        kit = create_kit_order(ctx["job"]["id"], kits_planned=5,
                               components=[{"description": "carton",
                                            "units_per_kit": 2}])
        validate_success(api.start_kit_order(kit["id"], KITTER), 200)

        res = api.complete_job(ctx["job"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_OPEN_KIT_ORDERS, expected_status=409)


class TestPressBookingHalfOpenAdjacency:
    def _fixture(self, api, brand_code):
        """PRESS_READY job with booking B1 [10:00,12:00) on press P."""
        ctx = setup_press_ready_job(customer_name="Pi", brand_code=brand_code)
        create_booked_press_window(
            ctx, planned_sheets=60,
            start_utc="2026-08-10T10:00:00Z", end_utc="2026-08-10T12:00:00Z",
        )
        return ctx

    def test_touching_window_accepted(self, api):
        """PRD §2.9: "Press bookings occupy half-open windows: the interval includes `start_utc` and excludes `end_utc`."
        PRD §2.9: "Because window ends are exclusive, windows that merely touch, one ending at the exact instant the other begins, do not conflict."

        Design: Difficulty/resource_temporal_overlap/press_booking_half_open_adjacency
        """
        ctx = self._fixture(api, "PII")
        res = api.create_press_booking(
            create_press_booking_payload(
                ctx["job"]["id"], ctx["press"]["id"], planned_sheets=60,
                start_utc="2026-08-10T12:00:00Z", end_utc="2026-08-10T14:00:00Z",
            ),
            OPERATOR,
        )
        booking = validate_success(res, 201)
        assert booking["status"] == "SCHEDULED"

    def test_overlapping_window_rejected(self, api):
        """PRD §2.9: "A new press booking conflicts with any non-`CANCELLED` booking on the same press when the two windows intersect — that is, when the new window's start is strictly earlier than the existing window's end and the existing window's start is strictly earlier than the new window's end — and the rejection carries `ERR_PRESS_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/press_booking_half_open_adjacency
        """
        ctx = self._fixture(api, "PIB")
        res = api.create_press_booking(
            create_press_booking_payload(
                ctx["job"]["id"], ctx["press"]["id"], planned_sheets=60,
                start_utc="2026-08-10T11:00:00Z", end_utc="2026-08-10T13:00:00Z",
            ),
            OPERATOR,
        )
        validate_error(res, ApiErrorId.ERR_PRESS_WINDOW_CONFLICT,
                       expected_status=409)
