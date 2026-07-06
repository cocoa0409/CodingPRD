"""Calendar slots, appointment booking/confirm/reschedule cycle, slot capacity
invariants, buffer-aware overlap, availability-window adjacency, and slot OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fixtures as fx, factories as f,
    make_platform_admin_headers, make_account_owner_headers, make_receptionist_headers,
)

ADMIN = make_platform_admin_headers()


# =============================================================================
# Difficulty / non_linear_state_machine / appointment_reschedule_cycle_back_to_confirmed
# =============================================================================
def test_reschedule_moves_confirmed_to_reschedule_requested(api):
    """PRD §3.12: "A confirmed appointment may be rescheduled by an AccountOwner to
    a new start_at and end_at, moving it from CONFIRMED to RESCHEDULE_REQUESTED ...
    On reschedule, start_at and end_at are updated to the new interval and
    reschedule_count increments by one."

    A CONFIRMED appointment rescheduled once becomes RESCHEDULE_REQUESTED with
    reschedule_count 1.

    Design: Difficulty/non_linear_state_machine/appointment_reschedule_cycle_back_to_confirmed
    """
    s = fx.setup_slot_with_confirmed_appointment(capacity=2, buffer_minutes=0)
    appt_id = s["appointment"]["id"]
    owner = s["owner_headers"]

    resched = validate_success(api.reschedule_appointment(
        appt_id, f.reschedule_payload("2026-03-02T11:00:00Z", "2026-03-02T11:30:00Z"), owner))
    assert resched["status"] == "RESCHEDULE_REQUESTED", (
        f"status {resched['status']} != RESCHEDULE_REQUESTED")
    assert resched["reschedule_count"] == 1, (
        f"reschedule_count {resched['reschedule_count']} != 1")


def test_reconfirm_cycles_back_to_confirmed(api):
    """PRD §3.12: "Re-confirming moves the appointment from RESCHEDULE_REQUESTED
    back to CONFIRMED (requiring the account to be ACTIVE or DELINQUENT), closing
    the loop".

    After reschedule (RESCHEDULE_REQUESTED), re-confirming returns the appointment
    to CONFIRMED — the same state it left, a cycle.

    Design: Difficulty/non_linear_state_machine/appointment_reschedule_cycle_back_to_confirmed
    """
    s = fx.setup_slot_with_confirmed_appointment(capacity=2, buffer_minutes=0)
    appt_id = s["appointment"]["id"]
    owner = s["owner_headers"]

    validate_success(api.reschedule_appointment(
        appt_id, f.reschedule_payload("2026-03-02T11:00:00Z", "2026-03-02T11:30:00Z"), owner))
    reconfirmed = validate_success(api.confirm_appointment(appt_id, owner))
    assert reconfirmed["status"] == "CONFIRMED", (
        f"status {reconfirmed['status']} != CONFIRMED after re-confirm (cycle back)")


# =============================================================================
# Difficulty / cross_entity_state_dependency / confirm_blocked_when_slot_closed
# =============================================================================
def test_confirm_blocked_when_slot_closed(api):
    """PRD §3.12: "An AccountOwner confirms a REQUESTED appointment, moving it to
    CONFIRMED; confirmation requires the account to be ACTIVE or DELINQUENT and
    the slot to be OPEN."
    PRD §2.7: "that the target resource is in a state from which the requested
    transition is defined (ERR_INVALID_STATE)".

    With the slot CLOSED, the cross-entity precondition (slot OPEN) fails and the
    confirm is rejected with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_slot_closed
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=1, buffer_minutes=0)
    appt = fx.book_appointment(account["id"], slot["id"], slot["version"])
    closed = validate_success(api.close_calendar_slot(slot["id"], owner))
    assert closed["status"] == "CLOSED"

    resp = api.confirm_appointment(appt["id"], owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_succeeds_when_slot_open(api):
    """PRD §3.12: "An AccountOwner confirms a REQUESTED appointment, moving it to
    CONFIRMED; confirmation requires the account to be ACTIVE or DELINQUENT and the
    slot to be OPEN."

    The cross-entity precondition is satisfied when the slot is OPEN: a REQUESTED
    appointment on an OPEN slot confirms to CONFIRMED. This pins that it is the slot
    state (not some other factor) that gates the confirm.

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_slot_closed
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=1, buffer_minutes=0)
    appt = fx.book_appointment(account["id"], slot["id"], slot["version"])
    confirmed = validate_success(api.confirm_appointment(appt["id"], owner))
    assert confirmed["status"] == "CONFIRMED", (
        f"status {confirmed['status']} != CONFIRMED when slot is OPEN")


# =============================================================================
# Difficulty / resource_temporal_overlap / appointment_buffer_aware_overlap_on_slot
# =============================================================================
def test_buffer_aware_overlap_rejects_zero_gap_booking(api):
    """PRD §3.12: "the new interval must not overlap any other non-cancelled
    appointment in the slot once buffer_minutes of clear gap is honored (else
    ERR_SLOT_OVERLAP)."

    With buffer_minutes=15 and a CONFIRMED 10:00-10:30 appointment, a 10:30-11:00
    booking leaves a 0-minute gap — less than the required 15 — and is rejected
    with ERR_SLOT_OVERLAP. The rejected booking does not consume capacity.

    Design: Difficulty/resource_temporal_overlap/appointment_buffer_aware_overlap_on_slot
    """
    s = fx.setup_slot_with_confirmed_appointment(capacity=2, buffer_minutes=15)
    account_id = s["account"]["id"]
    owner = s["owner_headers"]
    slot = validate_success(api.get_calendar_slot(s["slot"]["id"], owner))

    resp = api.create_appointment(
        f.create_appointment_payload(
            account_id, slot["id"], slot["version"],
            start_at="2026-03-02T10:30:00Z", end_at="2026-03-02T11:00:00Z"), owner)
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)

    slot_after = validate_success(api.get_calendar_slot(slot["id"], owner))
    assert slot_after["booked_count"] == 1, (
        f"booked_count {slot_after['booked_count']} != 1 (rejected booking must not consume)")


def test_buffer_aware_overlap_allows_gap_meeting_buffer(api):
    """PRD §3.12: "the new interval must not overlap any other non-cancelled
    appointment in the slot once buffer_minutes of clear gap is honored (else
    ERR_SLOT_OVERLAP)."

    With buffer_minutes=15 and a CONFIRMED 10:00-10:30 appointment, a booking that
    starts at 10:45 (a clear 15-minute gap) honors the buffer and succeeds.

    Design: Difficulty/resource_temporal_overlap/appointment_buffer_aware_overlap_on_slot
    """
    s = fx.setup_slot_with_confirmed_appointment(capacity=2, buffer_minutes=15)
    account_id = s["account"]["id"]
    owner = s["owner_headers"]
    slot = validate_success(api.get_calendar_slot(s["slot"]["id"], owner))

    ok = validate_success(api.create_appointment(
        f.create_appointment_payload(
            account_id, slot["id"], slot["version"],
            start_at="2026-03-02T10:45:00Z", end_at="2026-03-02T11:15:00Z"), owner),
        expected_status=201)
    assert ok["status"] == "REQUESTED"


# =============================================================================
# Difficulty / resource_temporal_overlap / availability_window_closed_interval_adjacency_ok
# =============================================================================
def test_adjacent_availability_window_allowed(api):
    """PRD §3.3: "A new window must not overlap an existing ACTIVE window for the
    same receptionist, where touching endpoints are permitted — one window may end
    at exactly the minute another begins — but any genuine overlap is rejected with
    ERR_WINDOW_OVERLAP."

    Given an ACTIVE window [540,600], an adjacent [600,660] (touching endpoint) is
    accepted as ACTIVE.

    Design: Difficulty/resource_temporal_overlap/availability_window_closed_interval_adjacency_ok
    """
    rec = get_success_data(api.create_receptionist(
        f.create_receptionist_payload(languages=["EN"], max_concurrent_calls=1), ADMIN))
    rec_headers = make_receptionist_headers(rec["id"])
    get_success_data(api.create_availability_window(
        rec["id"], {"start_minute": 540, "end_minute": 600}, rec_headers))

    adjacent = validate_success(api.create_availability_window(
        rec["id"], {"start_minute": 600, "end_minute": 660}, rec_headers),
        expected_status=201)
    assert adjacent["status"] == "ACTIVE", (
        f"adjacent window status {adjacent['status']} != ACTIVE")


def test_overlapping_availability_window_rejected(api):
    """PRD §3.3: "but any genuine overlap is rejected with ERR_WINDOW_OVERLAP."

    Given an ACTIVE window [540,600], a [599,660] window genuinely overlaps
    (599 < 600) and is rejected with ERR_WINDOW_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/availability_window_closed_interval_adjacency_ok
    """
    rec = get_success_data(api.create_receptionist(
        f.create_receptionist_payload(languages=["EN"], max_concurrent_calls=1), ADMIN))
    rec_headers = make_receptionist_headers(rec["id"])
    get_success_data(api.create_availability_window(
        rec["id"], {"start_minute": 540, "end_minute": 600}, rec_headers))

    resp = api.create_availability_window(
        rec["id"], {"start_minute": 599, "end_minute": 660}, rec_headers)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)


# =============================================================================
# Difficulty / compensating_invariant / cancel_restores_slot_capacity_invariant
# =============================================================================
def test_cancel_restores_slot_capacity(api):
    """PRD §3.12: "a computed available_count equal to capacity minus booked_count,
    never falling below zero."
    PRD §3.12: "An appointment may be cancelled by an AccountOwner from REQUESTED,
    CONFIRMED, or RESCHEDULE_REQUESTED, moving it to CANCELLED; each cancellation
    decrements the slot's booked_count and recomputes its available_count as
    capacity minus booked_count."

    Booking + confirming takes booked_count 0->1 (available 1 on a capacity-2
    slot); cancelling restores booked_count to 0 and available_count to the full
    capacity 2 — the invariant available_count == capacity - booked_count holds.

    Design: Difficulty/compensating_invariant/cancel_restores_slot_capacity_invariant
    """
    s = fx.setup_slot_with_confirmed_appointment(capacity=2, buffer_minutes=0)
    owner = s["owner_headers"]
    slot_id = s["slot"]["id"]
    appt_id = s["appointment"]["id"]

    before = validate_success(api.get_calendar_slot(slot_id, owner))
    assert before["booked_count"] == 1 and before["available_count"] == 1

    validate_success(api.cancel_appointment(appt_id, owner))
    after = validate_success(api.get_calendar_slot(slot_id, owner))
    assert after["booked_count"] == 0, f"booked_count {after['booked_count']} != 0 after cancel"
    assert after["available_count"] == 2, (
        f"available_count {after['available_count']} != 2 (== capacity - booked_count)")


def test_booking_consumes_exactly_one_capacity_unit(api):
    """PRD §3.12: "a computed available_count equal to capacity minus booked_count,
    never falling below zero."
    PRD §3.12: "On a successful booking the slot's booked_count increments, its
    available_count is recomputed".

    The forward half of the conservation law: booking + confirming on a capacity-2
    slot consumes exactly one unit (booked_count 1, available_count 1), so the
    invariant available_count == capacity - booked_count holds before any cancel.

    Design: Difficulty/compensating_invariant/cancel_restores_slot_capacity_invariant
    """
    s = fx.setup_slot_with_confirmed_appointment(capacity=2, buffer_minutes=0)
    owner = s["owner_headers"]
    slot = validate_success(api.get_calendar_slot(s["slot"]["id"], owner))
    assert slot["booked_count"] == 1, f"booked_count {slot['booked_count']} != 1"
    assert slot["available_count"] == slot["capacity"] - slot["booked_count"], (
        "available_count must equal capacity - booked_count after booking")
    assert slot["available_count"] == 1


# =============================================================================
# Corner / state_machines / new_appointment_starts_requested
# =============================================================================
def test_new_appointment_starts_requested(api):
    """PRD §3.12: "A new appointment starts in REQUESTED."
    PRD §3.12: "On a successful booking the slot's booked_count increments".

    A freshly booked appointment is REQUESTED and the slot's booked_count is 1.

    Design: Corner/state_machines/new_appointment_starts_requested
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=1)
    appt = validate_success(api.create_appointment(
        f.create_appointment_payload(account["id"], slot["id"], slot["version"]), owner),
        expected_status=201)
    assert appt["status"] == "REQUESTED"
    slot_after = validate_success(api.get_calendar_slot(slot["id"], owner))
    assert slot_after["booked_count"] == 1


# =============================================================================
# Corner / state_machines / confirm_cancelled_appointment_invalid_state
# =============================================================================
def test_confirm_cancelled_appointment_rejected(api):
    """PRD §3.12: "An appointment's status is one of REQUESTED, CONFIRMED,
    RESCHEDULE_REQUESTED, COMPLETED, CANCELLED, or NO_SHOW, with COMPLETED,
    CANCELLED, and NO_SHOW terminal."
    PRD §2.7: "that the target resource is in a state from which the requested
    transition is defined (ERR_INVALID_STATE)".

    Confirming a terminal CANCELLED appointment has no defined transition and is
    rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/confirm_cancelled_appointment_invalid_state
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=1)
    appt = fx.book_appointment(account["id"], slot["id"], slot["version"])
    cancelled = validate_success(api.cancel_appointment(appt["id"], owner))
    assert cancelled["status"] == "CANCELLED"

    resp = api.confirm_appointment(appt["id"], owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# Corner / state_machines / reschedule_after_three_loops_hits_limit
# =============================================================================
def test_fourth_reschedule_hits_limit(api):
    """PRD §3.12: "rescheduling requires that reschedule_count is below 3 (else
    ERR_RESCHEDULE_LIMIT) ... the cycle between CONFIRMED and RESCHEDULE_REQUESTED
    is bounded by the rule that reschedule_count stays below 3."

    After three reschedule+reconfirm laps (reschedule_count == 3) a fourth
    reschedule is rejected with ERR_RESCHEDULE_LIMIT.

    Design: Corner/state_machines/reschedule_after_three_loops_hits_limit
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=1, buffer_minutes=0,
                          window_start="2026-03-02T08:00:00Z",
                          window_end="2026-03-02T20:00:00Z")
    appt = fx.book_appointment(account["id"], slot["id"], slot["version"])
    appt_id = appt["id"]
    validate_success(api.confirm_appointment(appt_id, owner))

    times = [("11:00", "11:30"), ("12:00", "12:30"), ("13:00", "13:30")]
    for start, end in times:
        validate_success(api.reschedule_appointment(
            appt_id, f.reschedule_payload(f"2026-03-02T{start}:00Z", f"2026-03-02T{end}:00Z"),
            owner))
        validate_success(api.confirm_appointment(appt_id, owner))

    current = validate_success(api.get_appointment(appt_id, owner))
    assert current["reschedule_count"] == 3, (
        f"reschedule_count {current['reschedule_count']} != 3 before the fourth")

    resp = api.reschedule_appointment(
        appt_id, f.reschedule_payload("2026-03-02T14:00:00Z", "2026-03-02T14:30:00Z"), owner)
    validate_error(resp, ApiErrorId.ERR_RESCHEDULE_LIMIT.value)


# =============================================================================
# Corner / validations / booking_succeeds_with_room_and_no_overlap
# =============================================================================
def test_booking_succeeds_with_room_and_no_overlap(api):
    """PRD §3.12: "the slot must be OPEN with available_count greater than zero
    (else ERR_SLOT_FULL); and the new interval must not overlap any other
    non-cancelled appointment in the slot once buffer_minutes of clear gap is
    honored (else ERR_SLOT_OVERLAP). On a successful booking the slot's
    booked_count increments".

    A non-overlapping booking into an OPEN capacity-2 slot succeeds with 201 and
    REQUESTED, booked_count 1.

    Design: Corner/validations/booking_succeeds_with_room_and_no_overlap
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=2, buffer_minutes=0)
    appt = validate_success(api.create_appointment(
        f.create_appointment_payload(account["id"], slot["id"], slot["version"]), owner),
        expected_status=201)
    assert appt["status"] == "REQUESTED"
    slot_after = validate_success(api.get_calendar_slot(slot["id"], owner))
    assert slot_after["booked_count"] == 1 and slot_after["available_count"] == 1


# =============================================================================
# Corner / cross_cutting_complexity_layers / occ_book_stale_slot_version_rejected
# =============================================================================
def test_booking_with_stale_slot_version_rejected(api):
    """PRD §2.6: "Booking a new appointment must carry expected_slot_version
    matching the target CalendarSlot's current version. The slot's version
    advances whenever a booking consumes one of its capacity units, so a booking
    carrying an earlier value has a stale picture of remaining capacity and is
    rejected with ERR_STALE_SLOT_VERSION (HTTP 412)."

    After a first booking bumps the slot version, a second booking that still
    carries the pre-bump version is rejected with ERR_STALE_SLOT_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_book_stale_slot_version_rejected
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=3, buffer_minutes=0)
    v0 = slot["version"]
    fx.book_appointment(account["id"], slot["id"], v0,
                        start_at="2026-03-02T10:00:00Z", end_at="2026-03-02T10:30:00Z")

    resp = api.create_appointment(
        f.create_appointment_payload(
            account["id"], slot["id"], v0,
            start_at="2026-03-02T11:00:00Z", end_at="2026-03-02T11:30:00Z"), owner)
    validate_error(resp, ApiErrorId.ERR_STALE_SLOT_VERSION.value)


# =============================================================================
# Corner / cross_cutting_complexity_layers / appointment_version_increments_on_reschedule
# =============================================================================
def test_appointment_version_increments_each_mutation(api):
    """PRD §2.4: "an integer version that begins at its initial value and
    increments by one on every mutation that changes the resource."
    PRD §2.5: "Whenever a computed field changes as a side effect of an operation,
    the owning resource is mutated: its updated_at is refreshed and its version
    increments."

    An appointment's version starts at 1 on create and increments by 1 on confirm
    and again on reschedule (1 -> 2 -> 3).

    Design: Corner/cross_cutting_complexity_layers/appointment_version_increments_on_reschedule
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=1, buffer_minutes=0,
                          window_start="2026-03-02T08:00:00Z",
                          window_end="2026-03-02T20:00:00Z")
    appt = validate_success(api.create_appointment(
        f.create_appointment_payload(account["id"], slot["id"], slot["version"]), owner),
        expected_status=201)
    assert appt["version"] == 1, f"version on create {appt['version']} != 1"

    confirmed = validate_success(api.confirm_appointment(appt["id"], owner))
    assert confirmed["version"] == 2, f"version after confirm {confirmed['version']} != 2"

    resched = validate_success(api.reschedule_appointment(
        appt["id"], f.reschedule_payload("2026-03-02T11:00:00Z", "2026-03-02T11:30:00Z"), owner))
    assert resched["version"] == 3, f"version after reschedule {resched['version']} != 3"


# =============================================================================
# Corner / consistency_model / immediate_slot_counts_visible_after_booking
# =============================================================================
def test_slot_counts_visible_immediately_after_booking(api):
    """PRD §2.5: "Whenever a computed field changes as a side effect of an
    operation, the owning resource is mutated".
    PRD §3.12: "On a successful booking the slot's booked_count increments, its
    available_count is recomputed".

    Immediately after a booking, GET on the slot reflects booked_count 1 and
    available_count capacity-1 with no lag.

    Design: Corner/consistency_model/immediate_slot_counts_visible_after_booking
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = fx.create_slot(account["id"], capacity=2, buffer_minutes=0)
    fx.book_appointment(account["id"], slot["id"], slot["version"])

    fetched = validate_success(api.get_calendar_slot(slot["id"], owner))
    assert fetched["booked_count"] == 1, (
        f"booked_count {fetched['booked_count']} != 1 (must be visible immediately)")
    assert fetched["available_count"] == 1


# =============================================================================
# Corner / entities / calendar_slot_computed_available_count
# =============================================================================
def test_calendar_slot_computed_counts_on_create(api):
    """PRD §3.12: "The slot exposes a computed booked_count ... and a computed
    available_count equal to capacity minus booked_count, never falling below
    zero. A slot's status is OPEN or CLOSED, defaulting to OPEN".

    On create, booked_count is 0, available_count equals capacity, and status is
    OPEN.

    Design: Corner/entities/calendar_slot_computed_available_count
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    slot = validate_success(api.create_calendar_slot(
        f.create_calendar_slot_payload(account["id"], capacity=3), owner),
        expected_status=201)
    assert slot["booked_count"] == 0
    assert slot["available_count"] == 3, (
        f"available_count {slot['available_count']} != capacity 3")
    assert slot["status"] == "OPEN"


# =============================================================================
# Corner / entities / calendar_slot_window_end_must_exceed_start
# =============================================================================
def test_calendar_slot_window_end_before_start_rejected(api):
    """PRD §3.12: "with window_start (ISO 8601 UTC, inclusive) and window_end (ISO
    8601 UTC, exclusive, strictly after window_start)."
    PRD §2.7: "Required-field presence and enum/range validity (ERR_INVALID_REQUEST)
    is the lowest-priority check".

    A slot whose window_end is not strictly after window_start is rejected with
    ERR_INVALID_REQUEST.

    Design: Corner/entities/calendar_slot_window_end_must_exceed_start
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    resp = api.create_calendar_slot(
        f.create_calendar_slot_payload(
            account["id"], window_start="2026-03-02T17:00:00Z",
            window_end="2026-03-02T09:00:00Z", capacity=1), owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
