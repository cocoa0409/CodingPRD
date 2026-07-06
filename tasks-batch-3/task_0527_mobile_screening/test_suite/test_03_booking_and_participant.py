"""Booking guards, capacity boundaries, participant no-show/block lifecycle."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    fixtures,
)

PM = TEST_USERS["program_manager_headers"]
CS = TEST_USERS["clinical_staff_headers"]


# ---------------------------------------------------------------------------
# Corner: validations — slot outside window
# ---------------------------------------------------------------------------
def test_slot_outside_window_returns_422(api):
    """PRD §3.4: "The slot's half-open interval must lie fully within the event's window —
    that is, from `window_start_min` up to `window_end_min` — and a slot falling outside is
    rejected with `ERR_SLOT_OUTSIDE_WINDOW`."

    Design: Corner/validations/slot_outside_window_returns_422
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL",
                                                           window_start_min=540, window_end_min=720)
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    # [700,730) exceeds window end 720
    resp = api.create_appointment(
        {"event_id": event["id"], "participant_id": participant["id"],
         "slot_start_min": 700, "slot_duration_min": 30}, PM
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OUTSIDE_WINDOW.value)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check — event full at booked == capacity
# ---------------------------------------------------------------------------
def test_event_full_at_capacity_boundary_rejects_second_booking(api):
    """PRD §3.4: "The event's `booked_count` must be strictly less than the mobile unit's
    `daily_capacity` at booking time; a count already at or above capacity is rejected with
    `ERR_EVENT_FULL`."

    Design: Difficulty/boundary_precision_check/event_full_boundary_booked_equals_capacity
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL", daily_capacity=1)
    p1 = fixtures.register_participant(pay_type="SELF_PAY", full_name="P1")
    p2 = fixtures.register_participant(pay_type="SELF_PAY", full_name="P2", date_of_birth="1981-01-01")
    fixtures.book_appointment(event["id"], p1["id"], slot_start_min=540)  # booked_count 0 < 1 succeeds
    resp = api.create_appointment(
        {"event_id": event["id"], "participant_id": p2["id"],
         "slot_start_min": 600, "slot_duration_min": 30}, PM
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL.value)


def test_first_booking_under_capacity_succeeds(api):
    """PRD §3.4: "The event's `booked_count` must be strictly less than the mobile unit's
    `daily_capacity` at booking time; a count already at or above capacity is rejected with
    `ERR_EVENT_FULL`."

    Design: Difficulty/boundary_precision_check/event_full_boundary_booked_equals_capacity
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL", daily_capacity=1)
    p1 = fixtures.register_participant(pay_type="SELF_PAY", full_name="P1")
    resp = api.create_appointment(
        {"event_id": event["id"], "participant_id": p1["id"],
         "slot_start_min": 540, "slot_duration_min": 30}, PM
    )
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair — blocked participant pre-empts event-full
# ---------------------------------------------------------------------------
def test_blocked_participant_pre_empts_event_full(api):
    """PRD §3.4: "Read the ordering as: request well-formedness, then existence, then the
    blocked-participant check, then slot-within-window, then slot-overlap, then event
    capacity, then grant depletion."
    PRD §3.4: "A participant whose `status` is `BLOCKED` cannot be booked and is rejected
    with `ERR_PARTICIPANT_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_blocked_vs_constraint_full_on_booking
    """
    # A capacity-1 event already full, and a BLOCKED participant attempting to book it.
    unit = fixtures.create_unit(modality="BLOOD_PANEL", daily_capacity=1)
    sponsor = fixtures.create_sponsor()
    full_event = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL",
                                       event_date="2026-06-20", site_label="Full")
    full_event = fixtures.publish_event(full_event)
    filler = fixtures.register_participant(pay_type="SELF_PAY", full_name="Filler")
    fixtures.book_appointment(full_event["id"], filler["id"], slot_start_min=540)

    blocked, _, _ = fixtures.create_blocked_participant(unit_id=unit["id"], sponsor_id=sponsor["id"],
                                                        num_no_shows=3)
    assert blocked["status"] == "BLOCKED", f"setup: expected BLOCKED, got {blocked['status']}"

    resp = api.create_appointment(
        {"event_id": full_event["id"], "participant_id": blocked["id"],
         "slot_start_min": 570, "slot_duration_min": 30}, PM
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_BLOCKED.value)


def test_blocked_participant_cannot_book_open_event(api):
    """PRD §3.4: "A participant whose `status` is `BLOCKED` cannot be booked and is rejected
    with `ERR_PARTICIPANT_BLOCKED`."
    PRD §3.3: "A `BLOCKED` participant cannot be booked."

    Design: Difficulty/priority_pair_validation_conflict/safety_blocked_vs_constraint_full_on_booking
    """
    # A roomy (capacity 10) fresh event and a BLOCKED participant: the blocked check fires
    # regardless of capacity headroom.
    unit = fixtures.create_unit(modality="BLOOD_PANEL", daily_capacity=10)
    sponsor = fixtures.create_sponsor()
    blocked, _, _ = fixtures.create_blocked_participant(unit_id=unit["id"], sponsor_id=sponsor["id"],
                                                        num_no_shows=3)
    assert blocked["status"] == "BLOCKED", f"setup: expected BLOCKED, got {blocked['status']}"
    open_event = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL",
                                       event_date="2026-06-25", site_label="Open")
    open_event = fixtures.publish_event(open_event)
    resp = api.create_appointment(
        {"event_id": open_event["id"], "participant_id": blocked["id"],
         "slot_start_min": 540, "slot_duration_min": 30}, PM
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_BLOCKED.value)


# ---------------------------------------------------------------------------
# Corner: validations — grant depleted booking
# ---------------------------------------------------------------------------
def test_grant_depleted_booking_rejected(api):
    """PRD §3.4: "Finally, for a `GRANT`-pay participant, the referenced grant must not be
    depleted — its `is_depleted` must be false — or the booking is rejected with
    `ERR_GRANT_DEPLETED`."

    Design: Corner/validations/grant_depleted_booking_rejected
    """
    # First GRANT participant screened on an 8000-budget grant fully commits it.
    ctx = fixtures.create_screened_appointment(pay_type="GRANT", modality="BLOOD_PANEL",
                                              grant_total_budget_cents=8000, event_date="2026-06-11")
    grant = ctx["grant"]
    depleted = validate_success(api.get_grant(grant["id"], PM))
    assert depleted["is_depleted"] is True, f"setup: grant should be depleted, got {depleted}"

    # Second GRANT participant on the same grant attempts to book a fresh event.
    e2 = fixtures.create_event(ctx["sponsor"]["id"], ctx["unit"]["id"], modality="BLOOD_PANEL",
                              event_date="2026-06-12", site_label="L2")
    e2 = fixtures.publish_event(e2)
    p2 = fixtures.register_participant(pay_type="GRANT", grant_id=grant["id"], full_name="Pat G2",
                                       date_of_birth="1976-01-01")
    resp = api.create_appointment(
        {"event_id": e2["id"], "participant_id": p2["id"],
         "slot_start_min": 560, "slot_duration_min": 30}, PM
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_DEPLETED.value)


# ---------------------------------------------------------------------------
# Corner: state_machines — consent required, no-show gating
# ---------------------------------------------------------------------------
def test_checkin_without_consent_returns_consent_required(api):
    """PRD §3.5: "Check-in requires the appointment to be `SCHEDULED` (otherwise
    `ERR_INVALID_STATE`), the parent event to be `PUBLISHED` (otherwise
    `ERR_EVENT_NOT_PUBLISHED`), and the appointment's `consent_signed` to be true (otherwise
    `ERR_CONSENT_REQUIRED`)."

    Design: Corner/state_machines/checkin_without_consent_returns_consent_required
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    resp = api.checkin_appointment(appt["id"], CS)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value)
    reread = validate_success(api.get_appointment(appt["id"], CS))
    assert reread["status"] == "SCHEDULED"


def test_no_show_before_event_closed_returns_error(api):
    """PRD §3.5: "Marking a no-show moves a scheduled appointment to `NO_SHOW` (it must be
    `SCHEDULED`, otherwise `ERR_INVALID_STATE`) but only after the parent event is `CLOSED`
    (otherwise `ERR_EVENT_NOT_CLOSED`)."

    Design: Corner/state_machines/no_show_before_event_closed_returns_error
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    resp = api.mark_no_show(appt["id"], PM)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_CLOSED.value)
    reread = validate_success(api.get_appointment(appt["id"], PM))
    assert reread["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade — no-show reaching strike limit blocks participant
# ---------------------------------------------------------------------------
def test_third_no_show_blocks_participant(api):
    """PRD §3.5: "Marking a no-show cascades in three hops: the participant's
    `no_show_strikes` increases by one; if that count reaches the strike limit of three
    while the participant is `ACTIVE`, the participant flips to `BLOCKED`; and every
    `PENDING` reminder for the appointment transitions to `CANCELLED`."

    Design: Difficulty/transitive_cascade/no_show_cascade_depth2_blocks_participant
    """
    participant, third_appt_id = fixtures.create_participant_with_two_strikes()
    assert participant["no_show_strikes"] == 2, f"setup: expected 2 strikes, got {participant['no_show_strikes']}"
    validate_success(api.mark_no_show(third_appt_id, PM))
    reread = validate_success(api.get_participant(participant["id"], PM))
    assert reread["no_show_strikes"] == 3, f"expected 3 strikes, got {reread['no_show_strikes']}"
    assert reread["status"] == "BLOCKED", f"expected BLOCKED, got {reread['status']}"


def test_no_show_increments_strike(api):
    """PRD §3.3: "Whenever an appointment is marked no-show, the participant's
    `no_show_strikes` count increases by one, and if that count reaches the strike limit of
    three while the participant is still `ACTIVE`, the participant automatically flips to
    `BLOCKED`."

    Design: Difficulty/transitive_cascade/no_show_cascade_depth2_blocks_participant
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL", event_date="2026-06-05")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    validate_success(api.close_event(event["id"], PM))
    validate_success(api.mark_no_show(appt["id"], PM))
    reread = validate_success(api.get_participant(participant["id"], PM))
    assert reread["no_show_strikes"] == 1, f"expected 1 strike, got {reread['no_show_strikes']}"
    assert reread["status"] == "ACTIVE", f"expected still ACTIVE at 1 strike, got {reread['status']}"


# ---------------------------------------------------------------------------
# Corner: consistency_model — reinstate resets strikes immediately
# ---------------------------------------------------------------------------
def test_participant_reinstate_resets_strikes_immediately(api):
    """PRD §3.3: "A `ProgramManager` may reinstate a blocked participant, moving `status`
    from `BLOCKED` back to `ACTIVE` (the participant must be `BLOCKED`, otherwise
    `ERR_INVALID_STATE`); reinstatement resets `no_show_strikes` to 0 and bumps the
    participant's `version`."

    Design: Corner/consistency_model/participant_reinstate_resets_strikes_immediately
    """
    blocked, _, _ = fixtures.create_blocked_participant(num_no_shows=3)
    assert blocked["status"] == "BLOCKED", f"setup: expected BLOCKED, got {blocked['status']}"
    data = validate_success(api.reinstate_participant(blocked["id"], PM))
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["no_show_strikes"] == 0, f"expected 0 strikes, got {data['no_show_strikes']}"
