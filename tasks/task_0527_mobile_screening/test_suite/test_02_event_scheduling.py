"""Event lifecycle, publish guards, unit-day exclusivity, and booking geometry."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    fixtures,
)

PM = TEST_USERS["program_manager_headers"]
CS = TEST_USERS["clinical_staff_headers"]


# ---------------------------------------------------------------------------
# Corner: state_machines — event transitions
# ---------------------------------------------------------------------------
def test_publish_already_published_event_returns_invalid_state(api):
    """PRD §3.2: "Publishing an event advances it from `DRAFT` to `PUBLISHED` and carries
    the required `expected_event_version`; the event must be in `DRAFT` (otherwise
    `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/publish_already_published_event_returns_invalid_state
    """
    unit = fixtures.create_unit(modality="BLOOD_PANEL")
    sponsor = fixtures.create_sponsor()
    event = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL")
    published = fixtures.publish_event(event)
    resp = api.publish_event(published["id"], {"expected_event_version": published["version"]}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_event(published["id"], PM))
    assert reread["status"] == "PUBLISHED"


def test_close_event_with_open_appointments_returns_error(api):
    """PRD §3.2: "Closing an event advances it from `PUBLISHED` to `CLOSED`. The event must
    be `PUBLISHED` (otherwise `ERR_INVALID_STATE`), and no appointment on the event may be
    in an in-progress state of `CHECKED_IN`, `SCREENED`, or `RESULT_READY` (otherwise
    `ERR_OPEN_APPOINTMENTS_EXIST`)."

    Design: Corner/state_machines/close_event_with_open_appointments_returns_error
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    validate_success(api.consent_appointment(appt["id"], CS))
    validate_success(api.checkin_appointment(appt["id"], CS))
    resp = api.close_event(event["id"], PM)
    validate_error(resp, ApiErrorId.ERR_OPEN_APPOINTMENTS_EXIST.value)
    reread = validate_success(api.get_event(event["id"], PM))
    assert reread["status"] == "PUBLISHED"


def test_cancel_terminal_event_returns_invalid_state(api):
    """PRD §3.2: "Cancelling an event moves it to `CANCELLED` and is permitted while the
    event is in either `DRAFT` or `PUBLISHED` (otherwise `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_terminal_event_returns_invalid_state
    """
    unit = fixtures.create_unit(modality="BLOOD_PANEL")
    sponsor = fixtures.create_sponsor()
    event = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL")
    validate_success(api.cancel_event(event["id"], PM))
    resp = api.cancel_event(event["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_event(event["id"], PM))
    assert reread["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Corner: validations — publish guards
# ---------------------------------------------------------------------------
def test_publish_modality_mismatch_returns_error(api):
    """PRD §3.2: "the event's `modality` must equal the unit's `modality` (otherwise
    `ERR_MODALITY_MISMATCH`)"

    Design: Corner/validations/publish_modality_mismatch_returns_error
    """
    unit = fixtures.create_unit(modality="BLOOD_PANEL")
    sponsor = fixtures.create_sponsor()
    event = fixtures.create_event(sponsor["id"], unit["id"], modality="SKIN")
    resp = api.publish_event(event["id"], {"expected_event_version": event["version"]}, PM)
    validate_error(resp, ApiErrorId.ERR_MODALITY_MISMATCH.value)
    reread = validate_success(api.get_event(event["id"], PM))
    assert reread["status"] == "DRAFT"


def test_publish_retired_unit_returns_unavailable(api):
    """PRD §3.2: "the assigned mobile unit must be `AVAILABLE` (otherwise
    `ERR_UNIT_UNAVAILABLE`)"

    Design: Corner/validations/publish_retired_unit_returns_unavailable
    """
    unit = fixtures.create_unit(modality="BLOOD_PANEL")
    sponsor = fixtures.create_sponsor()
    event = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL")
    validate_success(api.retire_mobile_unit(unit["id"], PM))
    resp = api.publish_event(event["id"], {"expected_event_version": event["version"]}, PM)
    validate_error(resp, ApiErrorId.ERR_UNIT_UNAVAILABLE.value)
    reread = validate_success(api.get_event(event["id"], PM))
    assert reread["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_mobile_unit_whole_day_exclusive_conflict_at_publish(api):
    """PRD §3.2: "no other event already in `PUBLISHED` or `CLOSED` may share this
    `mobile_unit_id` and `event_date` (otherwise `ERR_UNIT_DAY_CONFLICT`) — a unit
    occupies a whole calendar day exclusively."

    Design: Difficulty/resource_temporal_overlap/mobile_unit_whole_day_exclusive_conflict_at_publish
    """
    unit = fixtures.create_unit(modality="BLOOD_PANEL")
    sponsor = fixtures.create_sponsor()
    e1 = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL",
                              event_date="2026-06-11", site_label="AM",
                              window_start_min=540, window_end_min=660)
    fixtures.publish_event(e1)
    e2 = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL",
                              event_date="2026-06-11", site_label="PM",
                              window_start_min=660, window_end_min=780)
    resp = api.publish_event(e2["id"], {"expected_event_version": e2["version"]}, PM)
    validate_error(resp, ApiErrorId.ERR_UNIT_DAY_CONFLICT.value)
    reread = validate_success(api.get_event(e2["id"], PM))
    assert reread["status"] == "DRAFT"


def test_unit_day_conflict_second_publish_blocked(api):
    """PRD §3.2: "no other event already in `PUBLISHED` or `CLOSED` may share this
    `mobile_unit_id` and `event_date` (otherwise `ERR_UNIT_DAY_CONFLICT`) — a unit
    occupies a whole calendar day exclusively."

    Design: Difficulty/resource_temporal_overlap/mobile_unit_whole_day_exclusive_conflict_at_publish
    """
    unit = fixtures.create_unit(modality="MAMMOGRAPHY")
    sponsor = fixtures.create_sponsor()
    e1 = fixtures.create_event(sponsor["id"], unit["id"], modality="MAMMOGRAPHY",
                              event_date="2026-07-01", site_label="One")
    fixtures.publish_event(e1)
    e2 = fixtures.create_event(sponsor["id"], unit["id"], modality="MAMMOGRAPHY",
                              event_date="2026-07-01", site_label="Two")
    resp = api.publish_event(e2["id"], {"expected_event_version": e2["version"]}, PM)
    validate_error(resp, ApiErrorId.ERR_UNIT_DAY_CONFLICT.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap — appointment slot half-open overlap
# ---------------------------------------------------------------------------
def test_appointment_slot_interior_overlap_rejected(api):
    """PRD §3.4: "The slot's half-open interval must not overlap the interval of any existing
    non-cancelled appointment on the same event; two intervals that merely touch at a single
    point do not conflict, but any shared interior minute does, and an overlap is rejected
    with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appointment_slot_halfopen_overlap_within_event
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    p1 = fixtures.register_participant(pay_type="SELF_PAY", full_name="P1")
    p2 = fixtures.register_participant(pay_type="SELF_PAY", full_name="P2", date_of_birth="1981-01-01")
    fixtures.book_appointment(event["id"], p1["id"], slot_start_min=560, slot_duration_min=30)
    # [580,610) shares interior minutes with [560,590)
    resp = api.create_appointment(
        {"event_id": event["id"], "participant_id": p2["id"], "slot_start_min": 580, "slot_duration_min": 30}, PM
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_appointment_slot_touching_at_point_allowed(api):
    """PRD §3.4: "two intervals that merely touch at a single point do not conflict, but any
    shared interior minute does, and an overlap is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appointment_slot_halfopen_overlap_within_event
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    p1 = fixtures.register_participant(pay_type="SELF_PAY", full_name="P1")
    p2 = fixtures.register_participant(pay_type="SELF_PAY", full_name="P2", date_of_birth="1981-01-01")
    fixtures.book_appointment(event["id"], p1["id"], slot_start_min=560, slot_duration_min=30)
    # [590,620) touches [560,590) only at point 590 — allowed
    resp = api.create_appointment(
        {"event_id": event["id"], "participant_id": p2["id"], "slot_start_min": 590, "slot_duration_min": 30}, PM
    )
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency — check-in requires event PUBLISHED
# ---------------------------------------------------------------------------
def test_checkin_after_event_closed_returns_event_not_published(api):
    """PRD §3.5: "Check-in requires the appointment to be `SCHEDULED` (otherwise
    `ERR_INVALID_STATE`), the parent event to be `PUBLISHED` (otherwise
    `ERR_EVENT_NOT_PUBLISHED`), and the appointment's `consent_signed` to be true
    (otherwise `ERR_CONSENT_REQUIRED`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_published
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    validate_success(api.consent_appointment(appt["id"], CS))
    # SCHEDULED appointments do not block closure
    validate_success(api.close_event(event["id"], PM))
    resp = api.checkin_appointment(appt["id"], CS)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PUBLISHED.value)
    reread = validate_success(api.get_appointment(appt["id"], CS))
    assert reread["status"] == "SCHEDULED"


def test_checkin_on_published_event_succeeds(api):
    """PRD §3.5: "`ClinicalStaff` check a participant in, advancing the appointment from
    `SCHEDULED` to `CHECKED_IN`. Check-in requires the appointment to be `SCHEDULED`
    (otherwise `ERR_INVALID_STATE`), the parent event to be `PUBLISHED` (otherwise
    `ERR_EVENT_NOT_PUBLISHED`), and the appointment's `consent_signed` to be true
    (otherwise `ERR_CONSENT_REQUIRED`)."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_event_published
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    validate_success(api.consent_appointment(appt["id"], CS))
    data = validate_success(api.checkin_appointment(appt["id"], CS))
    assert data["status"] == "CHECKED_IN"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant — booked_count conservation on cancel
# ---------------------------------------------------------------------------
def test_booked_count_restored_on_appointment_cancel(api):
    """PRD §3.4: "Booking recomputes the event's `booked_count`."
    PRD §3.2: "An event also exposes `booked_count`, a computed count of the appointments
    on it that are in the non-cancelled states `SCHEDULED`, `CHECKED_IN`, `SCREENED`,
    `RESULT_READY`, or `CLOSED`."
    PRD §3.5: "Cancelling a scheduled appointment moves it to `CANCELLED` (it must be
    `SCHEDULED`, otherwise `ERR_INVALID_STATE`)"

    Design: Difficulty/compensating_invariant/event_booked_count_conservation_on_appointment_cancel
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL", daily_capacity=10)
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    before = validate_success(api.get_event(event["id"], PM))
    assert before["booked_count"] == 1, f"expected booked_count 1, got {before['booked_count']}"
    validate_success(api.cancel_appointment(appt["id"], PM))
    after = validate_success(api.get_event(event["id"], PM))
    assert after["booked_count"] == 0, f"expected booked_count 0 after cancel, got {after['booked_count']}"
    reread = validate_success(api.get_appointment(appt["id"], PM))
    assert reread["status"] == "CANCELLED"


def test_booked_count_reflects_single_booking(api):
    """PRD §3.2: "An event also exposes `booked_count`, a computed count of the appointments
    on it that are in the non-cancelled states `SCHEDULED`, `CHECKED_IN`, `SCREENED`,
    `RESULT_READY`, or `CLOSED`."

    Design: Difficulty/compensating_invariant/event_booked_count_conservation_on_appointment_cancel
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL", daily_capacity=10)
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    data = validate_success(api.get_event(event["id"], PM))
    assert data["booked_count"] == 1, f"expected booked_count 1, got {data['booked_count']}"
