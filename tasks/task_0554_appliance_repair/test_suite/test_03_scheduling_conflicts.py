"""Technician-timeline and zone-capacity conflicts, plus validation-pipeline ordering."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_appointment_payload,
    setup_scheduling_conflict_base, book_conflict_appointment,
    setup_diagnosed_request, set_technician_off_duty, get_service_request,
    TEST_USERS,
)

ADMIN = TEST_USERS["service_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Difficulty: technician_buffered_double_book ───────────────────────────
def test_booking_within_30min_buffer_conflicts(api):
    """PRD §3.2: "A proposed window conflicts with an existing one when the proposed
    `window_start` is earlier than the existing `window_end` plus a half-hour travel buffer
    of 30 minutes, and simultaneously the existing `window_start` is earlier than the proposed
    `window_end` plus that same 30-minute buffer. Any such conflict rejects the booking with
    `ERR_TECH_DOUBLE_BOOKED`; because the buffer is added on both sides, two appointments that
    abut within 30 minutes of each other still conflict."

    Design: Difficulty/resource_temporal_overlap/technician_buffered_double_book
    """
    scaffold = setup_scheduling_conflict_base(num_techs=1, zone_capacity=5)
    book_conflict_appointment(scaffold, "sr1_id", 0, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    res = api.create_appointment(
        scaffold["sr2_id"],
        create_appointment_payload(scaffold["tech_ids"][0], scaffold["zone_id"],
                                   "2026-06-10T10:15:00Z", "2026-06-10T11:00:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_TECH_DOUBLE_BOOKED)


def test_buffered_conflict_leaves_second_request_unscheduled(api):
    """PRD §3.2: "Any such conflict rejects the booking with `ERR_TECH_DOUBLE_BOOKED`;
    because the buffer is added on both sides, two appointments that abut within 30 minutes
    of each other still conflict."

    Design: Difficulty/resource_temporal_overlap/technician_buffered_double_book
    """
    scaffold = setup_scheduling_conflict_base(num_techs=1, zone_capacity=5)
    book_conflict_appointment(scaffold, "sr1_id", 0, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    res = api.create_appointment(
        scaffold["sr2_id"],
        create_appointment_payload(scaffold["tech_ids"][0], scaffold["zone_id"],
                                   "2026-06-10T10:15:00Z", "2026-06-10T11:00:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_TECH_DOUBLE_BOOKED)
    sr2 = validate_success(api.get_service_request(scaffold["sr2_id"], ADMIN), 200)
    assert sr2["status"] == "INTAKE"


# ─── Difficulty: zone_aggregate_capacity_overlap ───────────────────────────
def test_zone_capacity_exceeded_two_technicians(api):
    """PRD §3.2: "If that overlap count plus the one new appointment would exceed the zone's
    `max_concurrent_appointments`, the booking is rejected with `ERR_ZONE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/zone_aggregate_capacity_overlap
    """
    scaffold = setup_scheduling_conflict_base(num_techs=2, zone_capacity=1)
    book_conflict_appointment(scaffold, "sr1_id", 0, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    res = api.create_appointment(
        scaffold["sr2_id"],
        create_appointment_payload(scaffold["tech_ids"][1], scaffold["zone_id"],
                                   "2026-06-10T09:30:00Z", "2026-06-10T10:30:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)


def test_zone_capacity_conflict_leaves_second_request_unscheduled(api):
    """PRD §3.2: "If that overlap count plus the one new appointment would exceed the zone's
    `max_concurrent_appointments`, the booking is rejected with `ERR_ZONE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/zone_aggregate_capacity_overlap
    """
    scaffold = setup_scheduling_conflict_base(num_techs=2, zone_capacity=1)
    book_conflict_appointment(scaffold, "sr1_id", 0, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    res = api.create_appointment(
        scaffold["sr2_id"],
        create_appointment_payload(scaffold["tech_ids"][1], scaffold["zone_id"],
                                   "2026-06-10T09:30:00Z", "2026-06-10T10:30:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)
    sr2 = validate_success(api.get_service_request(scaffold["sr2_id"], ADMIN), 200)
    assert sr2["status"] == "INTAKE"


# ─── Difficulty: temporal_beats_constraint_on_schedule ─────────────────────
def test_timeline_conflict_reported_before_zone_capacity(api):
    """PRD §2.1: "Requests are evaluated through a fixed validation pipeline, and the earliest
    failing stage determines the error returned."
    PRD §2.1: "(10) the technician being free of a timeline conflict (`ERR_TECH_DOUBLE_BOOKED`);
    (11) the zone not exceeding its concurrent-window capacity (`ERR_ZONE_CAPACITY_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_schedule
    """
    # Same technician (double-booked) AND zone at capacity 1 (full): timeline check (10) wins over (11).
    scaffold = setup_scheduling_conflict_base(num_techs=1, zone_capacity=1)
    book_conflict_appointment(scaffold, "sr1_id", 0, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    res = api.create_appointment(
        scaffold["sr2_id"],
        create_appointment_payload(scaffold["tech_ids"][0], scaffold["zone_id"],
                                   "2026-06-10T09:30:00Z", "2026-06-10T10:30:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_TECH_DOUBLE_BOOKED)


def test_timeline_conflict_precedence_no_appointment_created(api):
    """PRD §2.1: "the earliest failing stage determines the error returned."
    PRD §2.1: "(10) the technician being free of a timeline conflict (`ERR_TECH_DOUBLE_BOOKED`);
    (11) the zone not exceeding its concurrent-window capacity (`ERR_ZONE_CAPACITY_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_schedule
    """
    scaffold = setup_scheduling_conflict_base(num_techs=1, zone_capacity=1)
    book_conflict_appointment(scaffold, "sr1_id", 0, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    res = api.create_appointment(
        scaffold["sr2_id"],
        create_appointment_payload(scaffold["tech_ids"][0], scaffold["zone_id"],
                                   "2026-06-10T09:30:00Z", "2026-06-10T10:30:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_TECH_DOUBLE_BOOKED)
    sr2 = validate_success(api.get_service_request(scaffold["sr2_id"], ADMIN), 200)
    assert sr2["status"] == "INTAKE"


# ─── Difficulty: state_beats_referential_on_schedule ───────────────────────
def test_state_check_precedes_off_duty_check_on_booking(api):
    """PRD §2.1: "the earliest failing stage determines the error returned."
    PRD §2.1: "(4) the target resource being in a state that permits the transition
    (`ERR_INVALID_STATE`); ... (8) the assigned technician being on duty
    (`ERR_TECHNICIAN_OFF_DUTY`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_schedule
    """
    # Request is DIAGNOSED (not bookable) AND the technician is OFF_DUTY: state check (4) wins over (8).
    ctx = setup_diagnosed_request(model="M900")
    set_technician_off_duty(ctx)
    res = api.create_appointment(
        ctx["sr_id"],
        create_appointment_payload(ctx["tech_id"], ctx["zone_id"],
                                   "2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_state_beats_referential_leaves_request_diagnosed(api):
    """PRD §2.1: "(4) the target resource being in a state that permits the transition
    (`ERR_INVALID_STATE`)".
    PRD §2.1: "the earliest failing stage determines the error returned."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_schedule
    """
    ctx = setup_diagnosed_request(model="M901")
    set_technician_off_duty(ctx)
    res = api.create_appointment(
        ctx["sr_id"],
        create_appointment_payload(ctx["tech_id"], ctx["zone_id"],
                                   "2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    sr = get_service_request(ctx)
    assert sr["status"] == "DIAGNOSED"
