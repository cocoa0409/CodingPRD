"""Scheduling: fitter cleanup-buffer overlap, gait-lab aggregate capacity, their
precedence, and basic appointment lifecycle/validation."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

SM = TEST_USERS["store_manager_headers"]


def _customer_fitter_lab(capacity=1):
    fx.set_clock()
    cust = fx.create_customer(full_name="Sched Cust", date_of_birth="1965-05-05")
    f1 = fx.create_fitter(full_name="F One")
    f2 = fx.create_fitter(full_name="F Two")
    lab = fx.create_gait_lab(name="Lab L", concurrent_capacity=capacity)
    return cust, f1, f2, lab


class TestFitterDoubleBookPrecedesGaitCapacity:
    """A GAIT booking that both collides with the fitter's interval AND fills the lab
    reports the higher-priority fitter error."""

    def test_both_violations_report_fitter_double_booked(self, api):
        """PRD §2.9: "the domain-specific checks in ascending priority: ...
        fitter-double-booked (`ERR_FITTER_DOUBLE_BOOKED`), certification-visit-expired
        (`ERR_CERTIFICATION_VISIT_EXPIRED`), out-of-stock (`ERR_OUT_OF_STOCK`),
        gait-lab-capacity (`ERR_GAIT_LAB_AT_CAPACITY`)."

        Design: Difficulty/priority_pair_validation_conflict/appointment_fitter_double_book_beats_gait_lab_capacity
        """
        cust, f1, _f2, lab = _customer_fitter_lab(capacity=1)
        f1h = fx.make_fitter_headers(f1["id"])
        fx.book_appointment(cust["id"], f1["id"], f1h, appointment_type="GAIT",
                            gait_lab_id=lab["id"], start_time="2026-07-02T10:00:00Z",
                            end_time="2026-07-02T11:00:00Z")
        resp = api.create_appointment(
            {"customer_id": cust["id"], "fitter_id": f1["id"], "gait_lab_id": lab["id"],
             "appointment_type": "GAIT", "start_time": "2026-07-02T10:30:00Z",
             "end_time": "2026-07-02T11:30:00Z"}, f1h)
        validate_error(resp, ApiErrorId.ERR_FITTER_DOUBLE_BOOKED.value)

    def test_gait_capacity_fires_when_fitter_is_free(self, api):
        """PRD §3.3: "the number of `SCHEDULED` or `CHECKED_IN` `GAIT` appointments in the
        same lab whose intervals overlap the requested interval must remain below the
        lab's `concurrent_capacity`; reaching capacity yields `ERR_GAIT_LAB_AT_CAPACITY`."

        Design: Difficulty/priority_pair_validation_conflict/appointment_fitter_double_book_beats_gait_lab_capacity
        """
        cust, f1, f2, lab = _customer_fitter_lab(capacity=1)
        f1h = fx.make_fitter_headers(f1["id"])
        f2h = fx.make_fitter_headers(f2["id"])
        fx.book_appointment(cust["id"], f1["id"], f1h, appointment_type="GAIT",
                            gait_lab_id=lab["id"], start_time="2026-07-02T10:00:00Z",
                            end_time="2026-07-02T11:00:00Z")
        resp = api.create_appointment(
            {"customer_id": cust["id"], "fitter_id": f2["id"], "gait_lab_id": lab["id"],
             "appointment_type": "GAIT", "start_time": "2026-07-02T10:30:00Z",
             "end_time": "2026-07-02T11:30:00Z"}, f2h)
        validate_error(resp, ApiErrorId.ERR_GAIT_LAB_AT_CAPACITY.value)


class TestFitterCleanupBufferOverlap:
    """The fitter's 15-minute trailing buffer blocks a booking 10 minutes after the prior
    appointment's end, though the raw intervals do not overlap."""

    def test_booking_inside_trailing_buffer_rejected(self, api):
        """PRD §3.3: "treating each of the fitter's `SCHEDULED` or `CHECKED_IN`
        appointments as occupying its interval plus a 15-minute trailing cleanup buffer,
        the requested interval may not overlap any such occupied window, or the booking is
        rejected with `ERR_FITTER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/fitter_cleanup_buffer_overlap
        """
        fx.set_clock()
        cust = fx.create_customer(full_name="Pia Pair", date_of_birth="1975-07-07")
        f1 = fx.create_fitter(full_name="Buff Fit")
        f1h = fx.make_fitter_headers(f1["id"])
        fx.book_appointment(cust["id"], f1["id"], f1h, appointment_type="FITTING",
                            start_time="2026-07-02T10:00:00Z", end_time="2026-07-02T10:30:00Z")
        resp = api.create_appointment(
            {"customer_id": cust["id"], "fitter_id": f1["id"], "appointment_type": "FITTING",
             "start_time": "2026-07-02T10:40:00Z", "end_time": "2026-07-02T11:00:00Z"}, f1h)
        validate_error(resp, ApiErrorId.ERR_FITTER_DOUBLE_BOOKED.value)

    def test_booking_clear_of_buffer_succeeds(self, api):
        """PRD §3.3: "treating each of the fitter's `SCHEDULED` or `CHECKED_IN`
        appointments as occupying its interval plus a 15-minute trailing cleanup buffer,
        the requested interval may not overlap any such occupied window, or the booking is
        rejected with `ERR_FITTER_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/fitter_cleanup_buffer_overlap
        """
        fx.set_clock()
        cust = fx.create_customer(full_name="Pia Pair", date_of_birth="1975-07-07")
        f1 = fx.create_fitter(full_name="Buff Fit")
        f1h = fx.make_fitter_headers(f1["id"])
        fx.book_appointment(cust["id"], f1["id"], f1h, appointment_type="FITTING",
                            start_time="2026-07-02T10:00:00Z", end_time="2026-07-02T10:30:00Z")
        # 11:00 start is 30 min after the 10:30 end, well beyond the 15-min buffer (ends 10:45)
        appt2 = validate_success(api.create_appointment(
            {"customer_id": cust["id"], "fitter_id": f1["id"], "appointment_type": "FITTING",
             "start_time": "2026-07-02T11:00:00Z", "end_time": "2026-07-02T11:30:00Z"}, f1h),
            expected_status=201)
        assert appt2["status"] == "SCHEDULED"


class TestGaitLabAggregateCapacity:
    """Lab capacity is an overlap count, independent of the fitter."""

    def test_overlapping_gait_on_different_fitter_hits_capacity(self, api):
        """PRD §3.3: "the number of `SCHEDULED` or `CHECKED_IN` `GAIT` appointments in the
        same lab whose intervals overlap the requested interval must remain below the
        lab's `concurrent_capacity`; reaching capacity yields `ERR_GAIT_LAB_AT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/gait_lab_aggregate_capacity_overlap
        """
        cust, f1, f2, lab = _customer_fitter_lab(capacity=1)
        f1h = fx.make_fitter_headers(f1["id"])
        f2h = fx.make_fitter_headers(f2["id"])
        fx.book_appointment(cust["id"], f1["id"], f1h, appointment_type="GAIT",
                            gait_lab_id=lab["id"], start_time="2026-07-02T10:00:00Z",
                            end_time="2026-07-02T11:00:00Z")
        resp = api.create_appointment(
            {"customer_id": cust["id"], "fitter_id": f2["id"], "gait_lab_id": lab["id"],
             "appointment_type": "GAIT", "start_time": "2026-07-02T10:30:00Z",
             "end_time": "2026-07-02T11:30:00Z"}, f2h)
        validate_error(resp, ApiErrorId.ERR_GAIT_LAB_AT_CAPACITY.value)

    def test_non_overlapping_gait_in_capacity_one_lab_succeeds(self, api):
        """PRD §3.3: "the number of `SCHEDULED` or `CHECKED_IN` `GAIT` appointments in the
        same lab whose intervals overlap the requested interval must remain below the
        lab's `concurrent_capacity`; reaching capacity yields `ERR_GAIT_LAB_AT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/gait_lab_aggregate_capacity_overlap
        """
        cust, f1, f2, lab = _customer_fitter_lab(capacity=1)
        f1h = fx.make_fitter_headers(f1["id"])
        f2h = fx.make_fitter_headers(f2["id"])
        fx.book_appointment(cust["id"], f1["id"], f1h, appointment_type="GAIT",
                            gait_lab_id=lab["id"], start_time="2026-07-02T10:00:00Z",
                            end_time="2026-07-02T11:00:00Z")
        # A later, non-overlapping GAIT interval sees 0 overlapping appointments (< 1)
        appt2 = validate_success(api.create_appointment(
            {"customer_id": cust["id"], "fitter_id": f2["id"], "gait_lab_id": lab["id"],
             "appointment_type": "GAIT", "start_time": "2026-07-02T12:00:00Z",
             "end_time": "2026-07-02T13:00:00Z"}, f2h), expected_status=201)
        assert appt2["status"] == "SCHEDULED"


def test_appointment_starts_scheduled(api):
    """PRD §3.3: "An appointment starts `SCHEDULED`."

    Design: Corner/state_machines/appointment_initial_state_scheduled
    """
    ctx = fx.setup_fitter_and_customer()
    appt = validate_success(api.create_appointment(
        {"customer_id": ctx["customer"]["id"], "fitter_id": ctx["fitter"]["id"],
         "appointment_type": "FITTING", "start_time": "2026-07-04T09:00:00Z",
         "end_time": "2026-07-04T09:30:00Z"}, ctx["fitter_headers"]), expected_status=201)
    assert appt["status"] == "SCHEDULED"


def test_appointment_invalid_time_range_rejected(api):
    """PRD §3.3: "The `end_time` must be strictly after the `start_time`, or the booking
    is rejected with `ERR_INVALID_TIME_RANGE`."

    Design: Corner/state_machines/appointment_invalid_time_range_returns_422
    """
    ctx = fx.setup_fitter_and_customer()
    resp = api.create_appointment(
        {"customer_id": ctx["customer"]["id"], "fitter_id": ctx["fitter"]["id"],
         "appointment_type": "FITTING", "start_time": "2026-07-05T11:00:00Z",
         "end_time": "2026-07-05T10:00:00Z"}, ctx["fitter_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE.value)


def test_check_in_completed_appointment_rejected(api):
    """PRD §3.3: "`COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal; any transition
    attempted from an incompatible state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/appointment_check_in_from_completed_returns_invalid_state
    """
    ctx = fx.setup_fitter_and_customer()
    appt = get_success_data(api.create_appointment(
        {"customer_id": ctx["customer"]["id"], "fitter_id": ctx["fitter"]["id"],
         "appointment_type": "FITTING", "start_time": "2026-07-03T09:00:00Z",
         "end_time": "2026-07-03T09:30:00Z"}, ctx["fitter_headers"]))
    get_success_data(api.complete_appointment(
        appt["id"], {"recommended_mondo_mm": 260}, ctx["fitter_headers"]))
    resp = api.check_in_appointment(appt["id"], ctx["fitter_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
