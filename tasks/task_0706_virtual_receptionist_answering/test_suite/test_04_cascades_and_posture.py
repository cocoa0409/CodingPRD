"""Hard-cap suspension cascade, account-posture transitions, suspended-account
blocking, validation-priority conflict, and the adjust ledger invariant."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fixtures as fx, factories as f,
    make_platform_admin_headers, make_account_owner_headers, make_receptionist_headers,
)

ADMIN = make_platform_admin_headers()


# =============================================================================
# Difficulty / transitive_cascade /
#   complete_call_suspends_account_cancels_appointments
# =============================================================================
def test_completion_suspends_account_and_cancels_appointments(api):
    """PRD §3.9: "From either ACTIVE or DELINQUENT, the account moves to SUSPENDED
    when the open period's overage_charge_cents reaches or exceeds the hard cap.
    Suspension is the protective posture: it cascades to cancel every one of the
    account's appointments that is in REQUESTED, CONFIRMED, or RESCHEDULE_REQUESTED,
    and each such cancellation decrements its CalendarSlot's booked_count and
    recomputes that slot's available_count."

    A 121s call (3 billed minutes) on an included=0, R1=100, hard_cap=300 plan
    drives overage_charge to 300 (>= cap), suspending the account. The cascade
    cancels the CONFIRMED appointment and frees its slot.

    Design: Difficulty/transitive_cascade/complete_call_suspends_account_cancels_appointments
    """
    fx.set_clock("2026-03-01T09:00:00Z")
    plan = fx.create_per_minute_plan(
        included_minutes=0, overage_rate_cents=100, overage_tier2_rate_cents=100,
        hard_cap_overage_cents=300, overage_tier2_threshold=100)
    account = fx.create_account(plan["id"])
    acct_id = account["id"]
    account = get_success_data(api.get_account(acct_id, ADMIN))
    period_id = account["current_period_id"]
    owner = make_account_owner_headers(acct_id)

    fx.create_published_script(acct_id)
    slot = fx.create_slot(acct_id, capacity=1, buffer_minutes=0)
    appt = fx.book_appointment(acct_id, slot["id"], slot["version"])
    fx.confirm_appointment(acct_id, appt["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)

    call = fx.intake_call(acct_id, rec["id"], caller_id="5550001")
    completed = fx.answer_start_wrap_complete(
        call["id"], acct_id, rec["id"], "2026-03-01T09:05:00Z", "2026-03-01T09:07:01Z")
    assert completed["billed_units"] == 3

    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["overage_charge_cents"] == 300

    acct = validate_success(api.get_account(acct_id, ADMIN))
    assert acct["status"] == "SUSPENDED", f"account status {acct['status']} != SUSPENDED"

    appt_after = validate_success(api.get_appointment(appt["id"], owner))
    assert appt_after["status"] == "CANCELLED", (
        f"appointment status {appt_after['status']} != CANCELLED (suspend cascade)")

    slot_after = validate_success(api.get_calendar_slot(slot["id"], owner))
    assert slot_after["booked_count"] == 0, (
        f"slot booked_count {slot_after['booked_count']} != 0 after cascade cancel")
    assert slot_after["available_count"] == 1


def test_suspend_cascade_frees_slot_capacity(api):
    """PRD §3.9: "each such cancellation decrements its CalendarSlot's booked_count
    and recomputes that slot's available_count."

    The suspend cascade's cancellation of the appointment restores the slot to its
    full capacity (available_count == capacity).

    Design: Difficulty/transitive_cascade/complete_call_suspends_account_cancels_appointments
    """
    fx.set_clock("2026-03-01T09:00:00Z")
    plan = fx.create_per_minute_plan(
        included_minutes=0, overage_rate_cents=100, overage_tier2_rate_cents=100,
        hard_cap_overage_cents=300, overage_tier2_threshold=100)
    account = fx.create_account(plan["id"])
    acct_id = account["id"]
    owner = make_account_owner_headers(acct_id)
    fx.create_published_script(acct_id)
    slot = fx.create_slot(acct_id, capacity=1, buffer_minutes=0)
    appt = fx.book_appointment(acct_id, slot["id"], slot["version"])
    fx.confirm_appointment(acct_id, appt["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)

    call = fx.intake_call(acct_id, rec["id"], caller_id="5550001")
    fx.answer_start_wrap_complete(
        call["id"], acct_id, rec["id"], "2026-03-01T09:05:00Z", "2026-03-01T09:07:01Z")

    slot_after = validate_success(api.get_calendar_slot(slot["id"], owner))
    assert slot_after["available_count"] == slot_after["capacity"], (
        "slot available_count must equal capacity after the cascade freed it")


# =============================================================================
# Difficulty / boundary_precision_check / hard_cap_suspend_at_exact_threshold
# =============================================================================
def test_hard_cap_suspends_at_exact_threshold(api):
    """PRD §3.9: "if the period's overage_charge_cents is at or above
    hard_cap_overage_cents, the account is suspended".

    With hard_cap=300, a 121s call producing overage_charge exactly 300 hits the
    >= boundary and suspends the account.

    Design: Difficulty/boundary_precision_check/hard_cap_suspend_at_exact_threshold
    """
    fx.set_clock("2026-03-01T09:00:00Z")
    plan = fx.create_per_minute_plan(
        included_minutes=0, overage_rate_cents=100, overage_tier2_rate_cents=100,
        hard_cap_overage_cents=300, overage_tier2_threshold=100)
    account = fx.create_account(plan["id"])
    acct_id = account["id"]
    account = get_success_data(api.get_account(acct_id, ADMIN))
    period_id = account["current_period_id"]
    fx.create_published_script(acct_id)
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)

    call = fx.intake_call(acct_id, rec["id"], caller_id="5550001")
    fx.answer_start_wrap_complete(
        call["id"], acct_id, rec["id"], "2026-03-01T09:05:00Z", "2026-03-01T09:07:01Z")

    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["overage_charge_cents"] == 300, (
        f"overage_charge_cents {period['overage_charge_cents']} != 300 (exactly == hard_cap)")
    acct = validate_success(api.get_account(acct_id, ADMIN))
    assert acct["status"] == "SUSPENDED", (
        f"account status {acct['status']} != SUSPENDED at the >= boundary")


def test_overage_just_below_cap_does_not_suspend(api):
    """PRD §3.9: "From ACTIVE, the account moves to DELINQUENT when the open
    period's overage_units is greater than zero while its overage_charge_cents is
    still below the hard cap".

    With hard_cap=300, a 61s call (2 billed minutes -> charge 200) leaves charge
    below the cap, so the account becomes DELINQUENT, not SUSPENDED — confirming
    the boundary is strict (200 < 300 does not suspend).

    Design: Difficulty/boundary_precision_check/hard_cap_suspend_at_exact_threshold
    """
    fx.set_clock("2026-03-01T09:00:00Z")
    plan = fx.create_per_minute_plan(
        included_minutes=0, overage_rate_cents=100, overage_tier2_rate_cents=100,
        hard_cap_overage_cents=300, overage_tier2_threshold=100)
    account = fx.create_account(plan["id"])
    acct_id = account["id"]
    account = get_success_data(api.get_account(acct_id, ADMIN))
    period_id = account["current_period_id"]
    fx.create_published_script(acct_id)
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)

    call = fx.intake_call(acct_id, rec["id"], caller_id="5550001")
    fx.answer_start_wrap_complete(
        call["id"], acct_id, rec["id"], "2026-03-01T09:05:00Z", "2026-03-01T09:06:01Z")  # 61s

    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["overage_charge_cents"] == 200
    acct = validate_success(api.get_account(acct_id, ADMIN))
    assert acct["status"] == "DELINQUENT", (
        f"account status {acct['status']} != DELINQUENT (charge 200 below hard cap 300)")


# =============================================================================
# Difficulty / priority_pair_validation_conflict / suspended_beats_after_hours_on_answer
# =============================================================================
def test_suspended_account_error_precedes_after_hours_on_answer(api):
    """PRD §2.7: "the first failing check determines the error returned. The order
    is: ... (7) that the acting account is not suspended for answer, booking, and
    confirm operations (ERR_ACCOUNT_SUSPENDED); and then the domain-specific
    business checks described throughout §3."
    PRD §3.5: "An attempt to answer when the account is SUSPENDED is rejected with
    ERR_ACCOUNT_SUSPENDED. An attempt to answer an after-hours call that the script
    does not make routable is rejected with ERR_AFTER_HOURS_BLOCKED."

    A single answer request that violates BOTH the suspended check (priority 7) and
    the after-hours check (priority 8) returns the lower-priority error
    ERR_ACCOUNT_SUSPENDED.

    Design: Difficulty/priority_pair_validation_conflict/suspended_beats_after_hours_on_answer
    """
    fx.set_clock("2026-03-01T10:00:00Z")
    plan = fx.create_per_minute_plan(
        included_minutes=0, overage_rate_cents=100, overage_tier2_rate_cents=100,
        hard_cap_overage_cents=300, overage_tier2_threshold=100)
    account = fx.create_account(plan["id"])
    acct_id = account["id"]
    # business hours [09:00,17:00), after_hours_action VOICEMAIL (not routable).
    fx.create_published_script(acct_id, business_open_minute=540, business_close_minute=1020,
                               after_hours_action="VOICEMAIL")
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    # Drive a billed call (in business hours) to suspend the account.
    biller = fx.intake_call(acct_id, rec["id"], caller_id="5550001")
    fx.answer_call(biller["id"], rec["id"])
    get_success_data(api.start_call(biller["id"], rec_headers))
    fx.set_clock("2026-03-01T10:02:01Z")
    get_success_data(api.wrap_call(biller["id"], rec_headers))
    get_success_data(api.complete_call(biller["id"], rec_headers))
    assert validate_success(api.get_account(acct_id, ADMIN))["status"] == "SUSPENDED"

    # Intake the call-under-test at after-hours (18:00).
    fx.set_clock("2026-03-01T18:00:00Z")
    target = fx.intake_call(acct_id, rec["id"], caller_id="5559999")
    assert target["is_after_hours"] is True, "target call must be after-hours at 18:00"

    resp = api.answer_call(target["id"], rec_headers)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)


def test_suspended_after_hours_answer_does_not_transition_call(api):
    """PRD §2.7: "the first failing check determines the error returned. The order
    is: ... (7) that the acting account is not suspended for answer, booking, and
    confirm operations (ERR_ACCOUNT_SUSPENDED)".
    PRD §3.5: "On success the call moves from RINGING to ANSWERED and its
    answered_by_receptionist_id is set to the selected agent".

    When the priority-7 suspended check rejects the answer, no transition occurs:
    the after-hours target call's handling_status is not ANSWERED and its
    answered_by_receptionist_id stays null.

    Design: Difficulty/priority_pair_validation_conflict/suspended_beats_after_hours_on_answer
    """
    fx.set_clock("2026-03-01T10:00:00Z")
    plan = fx.create_per_minute_plan(
        included_minutes=0, overage_rate_cents=100, overage_tier2_rate_cents=100,
        hard_cap_overage_cents=300, overage_tier2_threshold=100)
    account = fx.create_account(plan["id"])
    acct_id = account["id"]
    fx.create_published_script(acct_id, business_open_minute=540, business_close_minute=1020,
                               after_hours_action="VOICEMAIL")
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    biller = fx.intake_call(acct_id, rec["id"], caller_id="5550001")
    fx.answer_call(biller["id"], rec["id"])
    get_success_data(api.start_call(biller["id"], rec_headers))
    fx.set_clock("2026-03-01T10:02:01Z")
    get_success_data(api.wrap_call(biller["id"], rec_headers))
    get_success_data(api.complete_call(biller["id"], rec_headers))
    assert validate_success(api.get_account(acct_id, ADMIN))["status"] == "SUSPENDED"

    fx.set_clock("2026-03-01T18:00:00Z")
    target = fx.intake_call(acct_id, rec["id"], caller_id="5559999")
    api.answer_call(target["id"], rec_headers)  # rejected
    after = validate_success(api.get_call(target["id"], rec_headers))
    assert after["handling_status"] != "ANSWERED", (
        f"handling_status {after['handling_status']} must not be ANSWERED after rejection")
    assert not after["answered_by_receptionist_id"], (
        "answered_by_receptionist_id must stay null after a rejected answer")


# =============================================================================
# Difficulty / cross_entity_state_dependency / answer_blocked_when_account_suspended
# =============================================================================
def test_answer_blocked_when_account_suspended(api):
    """PRD §3.5: "An attempt to answer when the account is SUSPENDED is rejected
    with ERR_ACCOUNT_SUSPENDED."

    The Call RINGING -> ANSWERED transition depends on the ClientAccount's status:
    a fresh business-hours RINGING call on a SUSPENDED account cannot be answered.

    Design: Difficulty/cross_entity_state_dependency/answer_blocked_when_account_suspended
    """
    fx.set_clock("2026-03-01T10:00:00Z")
    plan = fx.create_per_minute_plan(
        included_minutes=0, overage_rate_cents=100, overage_tier2_rate_cents=100,
        hard_cap_overage_cents=300, overage_tier2_threshold=100)
    account = fx.create_account(plan["id"])
    acct_id = account["id"]
    fx.create_published_script(acct_id)  # 24h business hours
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    biller = fx.intake_call(acct_id, rec["id"], caller_id="5550001")
    fx.answer_call(biller["id"], rec["id"])
    get_success_data(api.start_call(biller["id"], rec_headers))
    fx.set_clock("2026-03-01T10:02:01Z")
    get_success_data(api.wrap_call(biller["id"], rec_headers))
    get_success_data(api.complete_call(biller["id"], rec_headers))
    assert validate_success(api.get_account(acct_id, ADMIN))["status"] == "SUSPENDED"

    target = fx.intake_call(acct_id, rec["id"], caller_id="5559999")
    resp = api.answer_call(target["id"], rec_headers)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)


def test_answer_overflow_call_blocked_when_account_suspended(api):
    """PRD §3.5: "A call already sitting in OVERFLOW can still be answered later:
    answering an OVERFLOW call runs the same eligibility requirements (account
    ACTIVE, a selected agent that is AVAILABLE with capacity and speaks the
    requested_language) and, on success, moves it from OVERFLOW to ANSWERED".
    PRD §3.5: "An attempt to answer when the account is SUSPENDED is rejected with
    ERR_ACCOUNT_SUSPENDED."

    Answering an OVERFLOW call also depends on the account's status: on a SUSPENDED
    account the OVERFLOW-call answer is rejected with ERR_ACCOUNT_SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/answer_blocked_when_account_suspended
    """
    fx.set_clock("2026-03-01T10:00:00Z")
    plan = fx.create_per_minute_plan(
        included_minutes=0, overage_rate_cents=100, overage_tier2_rate_cents=100,
        hard_cap_overage_cents=300, overage_tier2_threshold=100)
    account = fx.create_account(plan["id"])
    acct_id = account["id"]
    # after_hours_action OVERFLOW so a call intaken after-hours lands in OVERFLOW.
    fx.create_published_script(acct_id, business_open_minute=540, business_close_minute=1020,
                               after_hours_action="OVERFLOW")
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    # Intake an OVERFLOW call at after-hours BEFORE suspension (business open 09:00).
    fx.set_clock("2026-03-01T18:00:00Z")
    overflow_call = fx.intake_call(acct_id, rec["id"], caller_id="5557777")
    assert overflow_call["handling_status"] == "OVERFLOW"

    # Now drive a billed call during business hours to suspend the account.
    fx.set_clock("2026-03-01T10:00:00Z")
    biller = fx.intake_call(acct_id, rec["id"], caller_id="5550001")
    fx.answer_call(biller["id"], rec["id"])
    get_success_data(api.start_call(biller["id"], rec_headers))
    fx.set_clock("2026-03-01T10:02:01Z")
    get_success_data(api.wrap_call(biller["id"], rec_headers))
    get_success_data(api.complete_call(biller["id"], rec_headers))
    assert validate_success(api.get_account(acct_id, ADMIN))["status"] == "SUSPENDED"

    # Answer the OVERFLOW call during business hours on the SUSPENDED account.
    resp = api.answer_call(overflow_call["id"], rec_headers)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)


# =============================================================================
# Difficulty / compensating_invariant / adjust_preserves_consumed_units_ledger_invariant
# =============================================================================
def test_adjust_preserves_consumed_units_ledger_invariant(api):
    """PRD §3.10: "On adjust, the call's billed_units is set to adjusted_units and
    its charge_cents is recomputed at the adjusted unit count ... The period's
    ledger is then compensated so its minutes-ledger invariant holds: consumed_units
    is reduced by the difference between the old billed_units and the adjusted_units,
    and overage_units and overage_charge_cents are recomputed under the final
    variant."

    A 121s call completes at billed_units 3 (consumed 3). Disputing then adjusting
    to 1 unit sets billed_units to 1 and reduces consumed_units to 1 — the ledger
    invariant (consumed_units == sum of BILLED/ADJUSTED billed_units) holds with no
    drift.

    Design: Difficulty/compensating_invariant/adjust_preserves_consumed_units_ledger_invariant
    """
    env = fx.setup_disputed_call(
        plan_overrides={"included_minutes": 100, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 100, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100})
    call = env["call"]  # disputed; carries current version
    period_id = env["period_id"]
    assert call["billed_units"] == 3, f"billed_units after complete {call['billed_units']} != 3"

    adjusted = validate_success(api.adjust_call(
        call["id"], f.adjust_payload(1, call["version"]), ADMIN))
    assert adjusted["billed_units"] == 1, (
        f"billed_units after adjust {adjusted['billed_units']} != 1")

    period = validate_success(api.get_billing_period(period_id, ADMIN))
    assert period["consumed_units"] == 1, (
        f"consumed_units {period['consumed_units']} != 1 after adjust (invariant, no drift)")


def test_adjust_recomputes_charge_at_adjusted_units(api):
    """PRD §3.10: "On adjust, the call's billed_units is set to adjusted_units and
    its charge_cents is recomputed at the adjusted unit count; the call's version
    increments by one."

    Adjusting the disputed call to 1 unit also bumps the call's version (the adjust
    mutated the call), confirming the per-call recompute side effect occurred.

    Design: Difficulty/compensating_invariant/adjust_preserves_consumed_units_ledger_invariant
    """
    env = fx.setup_disputed_call(
        plan_overrides={"included_minutes": 100, "overage_rate_cents": 100,
                        "overage_tier2_rate_cents": 100, "hard_cap_overage_cents": 100_000,
                        "overage_tier2_threshold": 100})
    call = env["call"]
    pre_version = call["version"]
    adjusted = validate_success(api.adjust_call(
        call["id"], f.adjust_payload(1, pre_version), ADMIN))
    assert adjusted["billed_units"] == 1
    assert adjusted["version"] == pre_version + 1, (
        f"call version {adjusted['version']} != {pre_version + 1} (must increment on adjust)")
