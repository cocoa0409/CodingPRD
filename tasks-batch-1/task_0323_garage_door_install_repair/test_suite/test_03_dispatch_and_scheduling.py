"""Dispatch: scheduling eligibility, temporal overlap, equipment capacity, the
state-vs-temporal precedence, and booked-minutes conservation on cancel.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    # fixtures
    create_customer,
    create_technician,
    create_door_model,
    create_equipment_unit,
    create_sent_quote,
    accept_quote_get_job,
    schedule_job,
    setup_scheduled_job,
    get_technician,
    get_job,
)

SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Difficulty / cross_entity_state_dependency / cesd_job_schedule_requires_tech_available
# ===========================================================================
class TestScheduleRequiresAvailableTechnician:
    def _setup_on_leave_tech_and_job(self):
        customer = create_customer()
        technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
        get_success_data(
            api_client.set_technician_leave(technician["id"], {"status": "ON_LEAVE"}, SM)
        )
        quote = create_sent_quote(
            customer["id"], [{"item_kind": "LABOR", "qty": 30}],
            quote_type="SERVICE_CALL", service_call_fee_cents=5000,
        )
        job = accept_quote_get_job(quote["id"], customer["id"])
        return technician, job

    def test_schedule_to_on_leave_technician_rejected(self, api):
        """PRD §3.5: "The chosen technician's `status` must be `AVAILABLE`, and
        if the originating quote's `quote_type` is `INSTALL` the technician's
        `certified_for_install` must be true; a technician who is on leave or
        not install-certified for an install job triggers `ERR_TECH_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/cesd_job_schedule_requires_tech_available
        """
        technician, job = self._setup_on_leave_tech_and_job()
        resp = api.schedule_job(
            job["id"],
            {"technician_id": technician["id"],
             "scheduled_start": "2026-07-01T17:00:00Z",
             "scheduled_end": "2026-07-01T18:00:00Z"},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_TECH_NOT_ELIGIBLE.value, 409)

    def test_set_leave_then_status_reflects_on_leave(self, api):
        """PRD §3.2: "A `ServiceManager` may toggle a technician between
        `AVAILABLE` and `ON_LEAVE` by supplying the desired `status`."

        Design: Difficulty/cross_entity_state_dependency/cesd_job_schedule_requires_tech_available
        """
        technician, _ = self._setup_on_leave_tech_and_job()
        fetched = get_technician(technician["id"])
        assert fetched["status"] == "ON_LEAVE", (
            f"Expected status ON_LEAVE after set-leave, got {fetched['status']}"
        )


# ===========================================================================
# Corner / validations / install_job_to_uncertified_tech_rejected
# ===========================================================================
def test_install_job_to_uncertified_technician_rejected(api):
    """PRD §3.5: "The chosen technician's `status` must be `AVAILABLE`, and if
    the originating quote's `quote_type` is `INSTALL` the technician's
    `certified_for_install` must be true; a technician who is on leave or not
    install-certified for an install job triggers `ERR_TECH_NOT_ELIGIBLE`."

    Design: Corner/validations/install_job_to_uncertified_tech_rejected
    """
    customer = create_customer()
    technician = create_technician(skill_level="APPRENTICE", certified_for_install=False)
    door = create_door_model(install_labor_minutes=120, requires_lift=False, list_price_cents=90000)
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "DOOR", "qty": 1}],
        quote_type="INSTALL", door_model_id=door["id"],
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    resp = api.schedule_job(
        job["id"],
        {"technician_id": technician["id"],
         "scheduled_start": "2026-07-01T17:00:00Z",
         "scheduled_end": "2026-07-01T19:00:00Z"},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_TECH_NOT_ELIGIBLE.value, 409)


# ===========================================================================
# Difficulty / resource_temporal_overlap / rto_technician_window_buffer_overlap
# ===========================================================================
def test_technician_window_overlap_within_travel_buffer_rejected(api):
    """PRD §3.5: "The window must not overlap any of the technician's other
    non-cancelled jobs once a 30-minute travel buffer is added to each side;
    treating intervals as half-open and buffered, an overlap is rejected with
    `ERR_TECH_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_technician_window_buffer_overlap
    """
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
    # Job A scheduled 17:00-18:00Z.
    quote_a = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job_a = accept_quote_get_job(quote_a["id"], customer["id"])
    schedule_job(job_a["id"], technician["id"],
                 start="2026-07-01T17:00:00Z", end="2026-07-01T18:00:00Z")
    # Job B 18:20-19:20Z: only a 20-min gap < 30-min travel buffer -> conflict.
    quote_b = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job_b = accept_quote_get_job(quote_b["id"], customer["id"])
    resp = api.schedule_job(
        job_b["id"],
        {"technician_id": technician["id"],
         "scheduled_start": "2026-07-01T18:20:00Z",
         "scheduled_end": "2026-07-01T19:20:00Z"},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_TECH_SCHEDULE_CONFLICT.value, 409)


def test_technician_window_outside_travel_buffer_succeeds(api):
    """PRD §3.5: "The window must not overlap any of the technician's other
    non-cancelled jobs once a 30-minute travel buffer is added to each side;
    treating intervals as half-open and buffered, an overlap is rejected with
    `ERR_TECH_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_technician_window_buffer_overlap
    """
    # Job A 17:00-18:00Z. Job B at 20:00-21:00Z leaves a 120-minute gap — far
    # beyond the 30-minute travel buffer on either side — so it does not overlap.
    customer = create_customer()
    technician = create_technician(skill_level="CERTIFIED", certified_for_install=True)
    quote_a = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job_a = accept_quote_get_job(quote_a["id"], customer["id"])
    schedule_job(job_a["id"], technician["id"],
                 start="2026-07-01T17:00:00Z", end="2026-07-01T18:00:00Z")
    quote_b = create_sent_quote(
        customer["id"], [{"item_kind": "LABOR", "qty": 30}],
        quote_type="SERVICE_CALL", service_call_fee_cents=5000,
    )
    job_b = accept_quote_get_job(quote_b["id"], customer["id"])
    scheduled_b = validate_success(api.schedule_job(
        job_b["id"],
        {"technician_id": technician["id"],
         "scheduled_start": "2026-07-01T20:00:00Z",
         "scheduled_end": "2026-07-01T21:00:00Z"},
        DISPATCHER,
    ))
    assert scheduled_b["dispatch_status"] == "SCHEDULED", (
        f"Expected SCHEDULED for non-overlapping window, got {scheduled_b['dispatch_status']}"
    )


# ===========================================================================
# Difficulty / resource_temporal_overlap / rto_equipment_capacity_overlap
# ===========================================================================
def test_equipment_capacity_overlap_rejected(api):
    """PRD §3.5: "If the door on this job requires a lift, an `equipment_unit_id`
    must be supplied, and the number of existing bookings on that equipment unit
    whose intervals overlap the requested window (intervals treated as closed for
    aggregate-capacity counting) must be strictly below the unit's
    `concurrent_capacity`; otherwise — including the case where a lift is required
    but no unit is supplied — the request is rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/rto_equipment_capacity_overlap
    """
    customer = create_customer()
    t1 = create_technician(skill_level="MASTER", certified_for_install=True)
    t2 = create_technician(skill_level="MASTER", certified_for_install=True)
    unit = create_equipment_unit(concurrent_capacity=1)
    door = create_door_model(install_labor_minutes=240, requires_lift=True,
                             width_in=192, height_in=96, list_price_cents=200000)
    # Job A occupies the unit 17:00-20:00Z.
    quote_a = create_sent_quote(
        customer["id"], [{"item_kind": "DOOR", "qty": 1}],
        quote_type="INSTALL", door_model_id=door["id"],
    )
    job_a = accept_quote_get_job(quote_a["id"], customer["id"])
    schedule_job(job_a["id"], t1["id"],
                 start="2026-07-01T17:00:00Z", end="2026-07-01T20:00:00Z",
                 equipment_unit_id=unit["id"])
    # Job B 18:00-21:00Z overlaps; capacity 1 already booked -> unavailable.
    quote_b = create_sent_quote(
        customer["id"], [{"item_kind": "DOOR", "qty": 1}],
        quote_type="INSTALL", door_model_id=door["id"],
    )
    job_b = accept_quote_get_job(quote_b["id"], customer["id"])
    resp = api.schedule_job(
        job_b["id"],
        {"technician_id": t2["id"],
         "scheduled_start": "2026-07-01T18:00:00Z",
         "scheduled_end": "2026-07-01T21:00:00Z",
         "equipment_unit_id": unit["id"]},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value, 409)


def test_equipment_non_overlapping_booking_succeeds(api):
    """PRD §3.5: "the number of existing bookings on that equipment unit whose
    intervals overlap the requested window (intervals treated as closed for
    aggregate-capacity counting) must be strictly below the unit's
    `concurrent_capacity`"

    Design: Difficulty/resource_temporal_overlap/rto_equipment_capacity_overlap
    """
    # Unit capacity 1; Job A 17:00-19:00Z. Job B 21:00-23:00Z is wholly disjoint
    # (no overlap under closed intervals), so the single capacity slot is free.
    customer = create_customer()
    t1 = create_technician(skill_level="MASTER", certified_for_install=True)
    t2 = create_technician(skill_level="MASTER", certified_for_install=True)
    unit = create_equipment_unit(concurrent_capacity=1)
    door = create_door_model(install_labor_minutes=240, requires_lift=True,
                             width_in=192, height_in=96, list_price_cents=200000)
    quote_a = create_sent_quote(
        customer["id"], [{"item_kind": "DOOR", "qty": 1}],
        quote_type="INSTALL", door_model_id=door["id"],
    )
    job_a = accept_quote_get_job(quote_a["id"], customer["id"])
    schedule_job(job_a["id"], t1["id"],
                 start="2026-07-01T17:00:00Z", end="2026-07-01T19:00:00Z",
                 equipment_unit_id=unit["id"])
    quote_b = create_sent_quote(
        customer["id"], [{"item_kind": "DOOR", "qty": 1}],
        quote_type="INSTALL", door_model_id=door["id"],
    )
    job_b = accept_quote_get_job(quote_b["id"], customer["id"])
    scheduled_b = validate_success(api.schedule_job(
        job_b["id"],
        {"technician_id": t2["id"],
         "scheduled_start": "2026-07-01T21:00:00Z",
         "scheduled_end": "2026-07-01T23:00:00Z",
         "equipment_unit_id": unit["id"]},
        DISPATCHER,
    ))
    assert scheduled_b["dispatch_status"] == "SCHEDULED", (
        f"Expected SCHEDULED for non-overlapping equipment booking, got {scheduled_b['dispatch_status']}"
    )


# ===========================================================================
# Corner / errors / equipment_unavailable_when_lift_required_but_missing
# ===========================================================================
def test_lift_required_but_no_equipment_supplied_rejected(api):
    """PRD §3.5: "If the door on this job requires a lift, an `equipment_unit_id`
    must be supplied ... otherwise — including the case where a lift is required
    but no unit is supplied — the request is rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Corner/errors/equipment_unavailable_when_lift_required_but_missing
    """
    customer = create_customer()
    technician = create_technician(skill_level="MASTER", certified_for_install=True)
    door = create_door_model(install_labor_minutes=240, requires_lift=True,
                             width_in=192, height_in=96, list_price_cents=220000)
    quote = create_sent_quote(
        customer["id"], [{"item_kind": "DOOR", "qty": 1}],
        quote_type="INSTALL", door_model_id=door["id"],
    )
    job = accept_quote_get_job(quote["id"], customer["id"])
    resp = api.schedule_job(
        job["id"],
        {"technician_id": technician["id"],
         "scheduled_start": "2026-07-01T17:00:00Z",
         "scheduled_end": "2026-07-01T21:00:00Z"},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value, 409)


# ===========================================================================
# Difficulty / priority_pair_validation_conflict / ppvc_state_beats_temporal_on_schedule
# ===========================================================================
def test_reschedule_already_scheduled_job_returns_invalid_state_not_conflict(api):
    """PRD §2.8: "(5) that the target resource is in a state from which the
    requested transition is allowed (`ERR_INVALID_STATE`); and then the
    domain-specific business checks."
    PRD §3.5: "A `Dispatcher` schedules an unscheduled job, moving its dispatch
    status from `UNSCHEDULED` to `SCHEDULED`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_temporal_on_schedule
    """
    # Job already SCHEDULED; a second /schedule with an overlapping window must
    # fail the state check (priority 5) before the temporal check (priority 10).
    ctx = setup_scheduled_job(start="2026-07-01T17:00:00Z", end="2026-07-01T18:00:00Z")
    resp = api.schedule_job(
        ctx["job"]["id"],
        {"technician_id": ctx["technician"]["id"],
         "scheduled_start": "2026-07-01T17:00:00Z",
         "scheduled_end": "2026-07-01T18:00:00Z"},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_rejected_reschedule_leaves_job_scheduled(api):
    """PRD §3.5: "A `Dispatcher` schedules an unscheduled job, moving its dispatch
    status from `UNSCHEDULED` to `SCHEDULED`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_temporal_on_schedule
    """
    # The state-rejected second schedule must not mutate the already-SCHEDULED job.
    ctx = setup_scheduled_job(start="2026-07-01T17:00:00Z", end="2026-07-01T18:00:00Z")
    api.schedule_job(
        ctx["job"]["id"],
        {"technician_id": ctx["technician"]["id"],
         "scheduled_start": "2026-07-01T17:00:00Z",
         "scheduled_end": "2026-07-01T18:00:00Z"},
        DISPATCHER,
    )
    fetched = get_success_data(api.get_job(ctx["job"]["id"], SM))
    assert fetched["dispatch_status"] == "SCHEDULED", (
        f"Expected job to remain SCHEDULED after rejected reschedule, got {fetched['dispatch_status']}"
    )


# ===========================================================================
# Difficulty / compensating_invariant / ci_technician_booked_minutes_conservation_on_cancel
# ===========================================================================
class TestBookedMinutesConservation:
    def test_schedule_adds_booked_minutes(self, api):
        """PRD §3.5: "A successful schedule assigns the `technician_id` (and the
        `equipment_unit_id` when required) and increases the technician's
        `booked_minutes` by the window length in minutes."

        Design: Difficulty/compensating_invariant/ci_technician_booked_minutes_conservation_on_cancel
        """
        ctx = setup_scheduled_job(start="2026-07-01T17:00:00Z", end="2026-07-01T18:00:00Z")
        tech = get_technician(ctx["technician"]["id"])
        assert tech["booked_minutes"] == 60, (
            f"Expected booked_minutes 60 after scheduling a 60-min window, got {tech['booked_minutes']}"
        )

    def test_cancel_restores_booked_minutes_to_zero(self, api):
        """PRD §3.5: "and if a technician had been assigned, the technician's
        `booked_minutes` is decreased by that job's window length, restoring the
        conserved booked-time total."

        Design: Difficulty/compensating_invariant/ci_technician_booked_minutes_conservation_on_cancel
        """
        ctx = setup_scheduled_job(start="2026-07-01T17:00:00Z", end="2026-07-01T18:00:00Z")
        get_success_data(api.cancel_job(ctx["job"]["id"], DISPATCHER))
        tech = get_technician(ctx["technician"]["id"])
        assert tech["booked_minutes"] == 0, (
            f"Expected booked_minutes 0 after cancel, got {tech['booked_minutes']}"
        )
