"""Appointment scheduling: reschedule revert cycle, bay temporal-overlap geometry with
turnover buffers, alignment/bay-state guards, and their precedence (PRD §3.5, §3.6).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    create_customer, create_vehicle, create_tire_model, create_fitment_rule,
    create_work_order, create_service_bay, add_tire_line, add_service_line, approve_order,
    authorize_payment, book_appointment, make_customer_headers,
    setup_customer_vehicle_tire, setup_approved_order_with_tire_line,
    setup_scheduled_appointment,
)
import test_helpers.factories as F

ADVISOR = TEST_USERS["service_advisor_headers"]
TECH = TEST_USERS["technician_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ---------------------------------------------------------------------------
# Rule 3 — reschedule revert cycle (different entity than work order)
# ---------------------------------------------------------------------------
class TestRescheduleRevertCycle:
    def _scheduled_pending(self, api):
        customer, vehicle, tire, wo, line, bay, appt = setup_scheduled_appointment(
            scheduled_start="2026-07-01T09:00:00.000Z",
            scheduled_end="2026-07-01T10:00:00.000Z", authorize=True)
        cust_headers = make_customer_headers(customer["id"])
        validate_success(api.request_reschedule(appt["id"], cust_headers))
        return customer, wo, bay, appt

    def test_confirm_reschedule_returns_to_scheduled_with_new_interval(self, api):
        """PRD §3.6: "A `ServiceAdvisor` then confirms the reschedule, which carries a new
        `scheduled_start` and `scheduled_end`, re-runs the very same guards as a fresh booking
        ... and on success moves `status` from `RESCHEDULE_PENDING` back to `SCHEDULED`,
        updating the window so that it once again blocks the bay."

        Design: Difficulty/non_linear_state_machine/install_appointment_reschedule_revert_cycle
        """
        customer, wo, bay, appt = self._scheduled_pending(api)
        data = validate_success(api.confirm_reschedule(
            appt["id"],
            {"scheduled_start": "2026-07-02T13:00:00.000Z",
             "scheduled_end": "2026-07-02T14:00:00.000Z"}, ADVISOR))
        assert data["status"] == "SCHEDULED"
        assert data["scheduled_start"] == "2026-07-02T13:00:00.000Z"

    def test_request_reschedule_moves_to_pending(self, api):
        """PRD §3.6: "A `Customer` may request a reschedule of their own appointment, moving
        its `status` from `SCHEDULED` to `RESCHEDULE_PENDING`; while in `RESCHEDULE_PENDING`
        the appointment's window no longer blocks the bay".

        Design: Difficulty/non_linear_state_machine/install_appointment_reschedule_revert_cycle
        """
        customer, vehicle, tire, wo, line, bay, appt = setup_scheduled_appointment(
            scheduled_start="2026-07-11T09:00:00.000Z",
            scheduled_end="2026-07-11T10:00:00.000Z", authorize=True)
        data = validate_success(api.request_reschedule(appt["id"], make_customer_headers(customer["id"])))
        assert data["status"] == "RESCHEDULE_PENDING"


# ---------------------------------------------------------------------------
# Rule 5 — bay-state error precedence over temporal overlap
# ---------------------------------------------------------------------------
class TestBayStateBeatsOverlap:
    def _closed_bay_with_pending_overlap(self, api):
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 16000, "mileage_warranty_miles": 45000,
                            "original_tread_32nds": 10, "stock_qty": 12})
        bay = create_service_bay(alignment_capable=False, turnover_buffer_min=15)
        # First order + appointment occupying 09:00-10:00
        wo1 = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo1, tire["id"], quantity=4)
        approve_order(wo1)
        book_appointment(wo1, bay, "2026-07-05T09:00:00.000Z", "2026-07-05T10:00:00.000Z")
        # Cancel that order so its appointment cancels, freeing the bay so close precondition holds
        validate_success(api.cancel_work_order(
            wo1["id"], {"expected_work_order_version": wo1["version"]}, ADVISOR))
        closed = validate_success(api.close_service_bay(
            bay["id"], {"expected_service_bay_version": bay["version"]}, INV))
        bay["version"] = closed["version"]
        # Second order ready to book an overlapping slot into the now-closed bay
        wo2 = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo2, tire["id"], quantity=4)
        approve_order(wo2)
        return wo2, bay

    def test_out_of_service_bay_beats_time_conflict(self, api):
        """PRD §3.6: "The chosen bay must be `OPEN`; booking against a bay whose `status` is
        `OUT_OF_SERVICE` is rejected with `ERR_BAY_OUT_OF_SERVICE`. Finally, the requested
        window must not collide with the bay's existing calendar ... and a collision is
        rejected with `ERR_BAY_TIME_CONFLICT`."

        The bay-OPEN check is stated before the "Finally" overlap check, so the state error
        wins. (Overlap would also apply here had the bay been open.)

        Design: Difficulty/priority_pair_validation_conflict/bay_state_beats_temporal_overlap_on_appointment
        """
        wo2, bay = self._closed_bay_with_pending_overlap(api)
        validate_error(api.create_appointment(
            F.create_appointment_payload(
                wo2["id"], bay["id"], "2026-07-05T09:30:00.000Z", "2026-07-05T10:30:00.000Z",
                bay["version"]), ADVISOR),
            ApiErrorId.ERR_BAY_OUT_OF_SERVICE)

    def test_out_of_service_bay_rejects_even_nonoverlapping_slot(self, api):
        """PRD §3.6: "booking against a bay whose `status` is `OUT_OF_SERVICE` is rejected
        with `ERR_BAY_OUT_OF_SERVICE`."
        PRD §2.10: "An `OUT_OF_SERVICE` bay refuses new appointments."

        Confirms the closed-bay rejection is independent of any time conflict.

        Design: Difficulty/priority_pair_validation_conflict/bay_state_beats_temporal_overlap_on_appointment
        """
        wo2, bay = self._closed_bay_with_pending_overlap(api)
        validate_error(api.create_appointment(
            F.create_appointment_payload(
                wo2["id"], bay["id"], "2026-07-05T15:00:00.000Z", "2026-07-05T16:00:00.000Z",
                bay["version"]), ADVISOR),
            ApiErrorId.ERR_BAY_OUT_OF_SERVICE)


# ---------------------------------------------------------------------------
# Rule 8 — resource temporal-overlap conflicts (buffer geometry)
# ---------------------------------------------------------------------------
class TestBayOverlapGeometry:
    def _bay_with_one_appointment(self, api, buffer_min, start, end):
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 15000, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 10, "stock_qty": 20})
        bay = create_service_bay(alignment_capable=False, turnover_buffer_min=buffer_min)
        wo1 = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo1, tire["id"], quantity=4)
        approve_order(wo1)
        book_appointment(wo1, bay, start, end)
        wo2 = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo2, tire["id"], quantity=4)
        approve_order(wo2)
        return wo2, bay

    def test_buffer_makes_adjacent_slot_conflict(self, api):
        """PRD §3.6: "the interval, extended past its end by the bay's `turnover_buffer_min`,
        must not overlap any `SCHEDULED` or `CHECKED_IN` appointment on the same bay, and a
        collision is rejected with `ERR_BAY_TIME_CONFLICT`."

        Existing [09:00,10:00) with buffer 15 extends to [09:00,10:15); new [10:00,11:00)
        overlaps -> ERR_BAY_TIME_CONFLICT.

        Design: Difficulty/resource_temporal_overlap/bay_overlap_with_turnover_buffer_adjacency
        """
        wo2, bay = self._bay_with_one_appointment(
            api, 15, "2026-07-08T09:00:00.000Z", "2026-07-08T10:00:00.000Z")
        validate_error(api.create_appointment(
            F.create_appointment_payload(
                wo2["id"], bay["id"], "2026-07-08T10:00:00.000Z", "2026-07-08T11:00:00.000Z",
                bay["version"]), ADVISOR),
            ApiErrorId.ERR_BAY_TIME_CONFLICT)

    def test_buffer_conflict_independent_of_alignment(self, api):
        """PRD §3.6: "the requested window must not collide with the bay's existing calendar:
        the interval, extended past its end by the bay's `turnover_buffer_min`, must not
        overlap any `SCHEDULED` or `CHECKED_IN` appointment on the same bay".

        Re-verifies the buffered conflict with a later day window.

        Design: Difficulty/resource_temporal_overlap/bay_overlap_with_turnover_buffer_adjacency
        """
        wo2, bay = self._bay_with_one_appointment(
            api, 15, "2026-07-20T09:00:00.000Z", "2026-07-20T10:00:00.000Z")
        validate_error(api.create_appointment(
            F.create_appointment_payload(
                wo2["id"], bay["id"], "2026-07-20T10:10:00.000Z", "2026-07-20T11:00:00.000Z",
                bay["version"]), ADVISOR),
            ApiErrorId.ERR_BAY_TIME_CONFLICT)

    def test_zero_buffer_adjacent_slot_succeeds(self, api):
        """PRD §3.6: "The booked window is treated as a half-open interval: `scheduled_start`
        is included and `scheduled_end` is excluded".
        PRD §3.6: "the interval, extended past its end by the bay's `turnover_buffer_min`,
        must not overlap any `SCHEDULED` or `CHECKED_IN` appointment on the same bay".

        Buffer 0: existing [09:00,10:00), new [10:00,11:00) are exactly adjacent (half-open,
        no overlap) -> booking succeeds (201, SCHEDULED).

        Design: Difficulty/resource_temporal_overlap/bay_half_open_adjacency_no_buffer_succeeds
        """
        wo2, bay = self._bay_with_one_appointment(
            api, 0, "2026-07-09T09:00:00.000Z", "2026-07-09T10:00:00.000Z")
        data = validate_success(api.create_appointment(
            F.create_appointment_payload(
                wo2["id"], bay["id"], "2026-07-09T10:00:00.000Z", "2026-07-09T11:00:00.000Z",
                bay["version"]), ADVISOR), expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_zero_buffer_adjacent_slot_persisted(self, api):
        """PRD §3.6: "A new appointment is born `SCHEDULED`."
        PRD §3.6: "A successful booking bumps the bay's `version` by one."

        Confirms the adjacent-with-zero-buffer booking is durably SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/bay_half_open_adjacency_no_buffer_succeeds
        """
        wo2, bay = self._bay_with_one_appointment(
            api, 0, "2026-07-21T09:00:00.000Z", "2026-07-21T10:00:00.000Z")
        data = validate_success(api.create_appointment(
            F.create_appointment_payload(
                wo2["id"], bay["id"], "2026-07-21T10:00:00.000Z", "2026-07-21T11:00:00.000Z",
                bay["version"]), ADVISOR), expected_status=201)
        fetched = validate_success(api.get_appointment(data["id"], ADVISOR))
        assert fetched["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner — appointment / bay validations
# ---------------------------------------------------------------------------
class TestAppointmentValidations:
    def _approved_order_and_bay(self, api, alignment_capable=False, with_alignment_line=False):
        customer, vehicle, tire = setup_customer_vehicle_tire(
            tire_overrides={"unit_price_cents": 14000, "mileage_warranty_miles": 60000,
                            "original_tread_32nds": 10, "stock_qty": 8})
        bay = create_service_bay(alignment_capable=alignment_capable, turnover_buffer_min=15)
        wo = create_work_order(customer["id"], vehicle["id"])
        add_tire_line(wo, tire["id"], quantity=4)
        if with_alignment_line:
            add_service_line(wo, "ALIGNMENT", quantity=1)
        approve_order(wo)
        return wo, bay

    def test_alignment_order_into_non_alignment_bay_rejected(self, api):
        """PRD §3.6: "a booking is rejected with `ERR_BAY_NOT_ALIGNMENT_CAPABLE` if the order
        requires alignment but the chosen bay is not `alignment_capable`."

        Design: Corner/validations/alignment_order_into_non_alignment_bay_rejected
        """
        wo, bay = self._approved_order_and_bay(api, alignment_capable=False, with_alignment_line=True)
        validate_error(api.create_appointment(
            F.create_appointment_payload(
                wo["id"], bay["id"], "2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z",
                bay["version"]), ADVISOR),
            ApiErrorId.ERR_BAY_NOT_ALIGNMENT_CAPABLE)

    def test_invalid_interval_end_before_start_rejected(self, api):
        """PRD §3.6: "`scheduled_end` must be strictly later than `scheduled_start`, with any
        non-positive interval rejected as `ERR_INVALID_INTERVAL`."

        Design: Corner/validations/appointment_invalid_interval_end_before_start
        """
        wo, bay = self._approved_order_and_bay(api)
        validate_error(api.create_appointment(
            F.create_appointment_payload(
                wo["id"], bay["id"], "2026-08-02T11:00:00.000Z", "2026-08-02T10:00:00.000Z",
                bay["version"]), ADVISOR),
            ApiErrorId.ERR_INVALID_INTERVAL)
