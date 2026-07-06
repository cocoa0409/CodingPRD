"""Call intake, screening, routing, the parallel handling/billing axes, the live
segment side effects, and lifecycle reconciliation of counters."""
from test_helpers import (
    validate_success, get_success_data,
    fixtures as fx, factories as f,
    make_platform_admin_headers, make_account_owner_headers, make_receptionist_headers,
)

ADMIN = make_platform_admin_headers()


# =============================================================================
# Difficulty / dual_variant_calc / spam_score_final_drops_after_human_engagement
# =============================================================================
def test_provisional_spam_score_uses_only_static_signals(api):
    """PRD §3.4: "Starting from zero, the score adds the matched ACTIVE rule's
    anonymous_penalty when the caller_id is the empty string, and adds 50 points
    when the caller's area code appears in the rule's blocked_area_codes; the
    result is then capped at a ceiling of 100."

    An anonymous call (caller_id absent) with anonymous_penalty=40 scores a
    provisional 40 at intake and, being below the threshold of 70, stays RINGING.

    Design: Difficulty/dual_variant_calc/spam_score_final_drops_after_human_engagement
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    get_success_data(api.create_spam_rule(
        f.create_spam_rule_payload(account["id"], blocked_area_codes=[],
                                   spam_score_threshold=70, anonymous_penalty=40), owner))
    fx.create_published_script(account["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)

    call = fx.intake_call(account["id"], rec["id"], requested_language="EN")
    assert call["spam_score"] == 40, f"provisional spam_score {call['spam_score']} != 40"
    assert call["handling_status"] == "RINGING", (
        f"handling_status {call['handling_status']} != RINGING (40 < 70)")


def test_final_spam_score_subtracts_thirty_after_human_engagement(api):
    """PRD §3.6: "the final score is computed exactly like the provisional score
    (zero, plus anonymous_penalty if caller_id is empty, plus 50 if the area code
    is blocked, capped at 100) but, if the call ever reached IN_PROGRESS —
    evidence that a human engaged and the call was legitimate — 30 points are
    subtracted with a floor of zero."

    An anonymous call (provisional 40) answered, started (IN_PROGRESS), then
    wrapped finalizes to max(0, 40-30) = 10.

    Design: Difficulty/dual_variant_calc/spam_score_final_drops_after_human_engagement
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    get_success_data(api.create_spam_rule(
        f.create_spam_rule_payload(account["id"], blocked_area_codes=[],
                                   spam_score_threshold=70, anonymous_penalty=40), owner))
    fx.create_published_script(account["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    call = fx.intake_call(account["id"], rec["id"], requested_language="EN")
    fx.answer_call(call["id"], rec["id"])
    get_success_data(api.start_call(call["id"], rec_headers))
    wrapped = get_success_data(api.wrap_call(call["id"], rec_headers))
    assert wrapped["spam_score"] == 10, (
        f"final spam_score {wrapped['spam_score']} != 10 (40 - 30 human engagement)")


# =============================================================================
# Difficulty / non_linear_state_machine / call_parallel_handling_and_billing_axes
# =============================================================================
def test_dispute_moves_billing_axis_while_handling_axis_stays_completed(api):
    """PRD §3.10: "A completed call's billing_status is BILLED. An AccountOwner may
    dispute a billed call, moving its billing_status from BILLED to DISPUTED; this
    is permitted only while the call's BillingPeriod is OPEN, and it makes no
    ledger change yet."
    PRD §1 (Introduction): "a call advances along two independent state axes at
    once".

    After completion handling_status is COMPLETED and billing_status BILLED;
    disputing flips billing_status to DISPUTED while handling_status stays
    COMPLETED — the two axes move independently.

    Design: Difficulty/non_linear_state_machine/call_parallel_handling_and_billing_axes
    """
    env = fx.setup_answer_environment(plan_kind="PER_CALL", clock="2026-03-01T09:00:00Z")
    call = fx.create_completed_call(env, "2026-03-01T09:00:00Z", "2026-03-01T09:01:00Z")
    assert call["handling_status"] == "COMPLETED"
    assert call["billing_status"] == "BILLED"

    owner = env["owner_headers"]
    disputed = validate_success(api.dispute_call(call["id"], owner))
    assert disputed["billing_status"] == "DISPUTED", (
        f"billing_status {disputed['billing_status']} != DISPUTED")
    assert disputed["handling_status"] == "COMPLETED", (
        f"handling_status {disputed['handling_status']} != COMPLETED (unchanged by dispute)")


def test_completed_call_has_terminal_handling_and_billed_billing(api):
    """PRD §3.6: "Completing the call moves it from WRAP_UP to COMPLETED and is the
    moment billing occurs ... the call's billing_status flips from UNBILLED to
    BILLED, freezing charge_cents and billed_units onto the call".
    PRD §3.4: "its terminal handling states are COMPLETED, SCREENED_OUT, and
    ABANDONED."

    A completed call sits at terminal handling COMPLETED on the handling axis and
    BILLED on the independent billing axis.

    Design: Difficulty/non_linear_state_machine/call_parallel_handling_and_billing_axes
    """
    env = fx.setup_answer_environment(plan_kind="PER_CALL", clock="2026-03-01T09:00:00Z")
    call = fx.create_completed_call(env, "2026-03-01T09:00:00Z", "2026-03-01T09:01:00Z")
    assert call["handling_status"] == "COMPLETED"
    assert call["billing_status"] == "BILLED"


# =============================================================================
# Difficulty / transitive_cascade /
#   start_call_drives_receptionist_busy_and_account_lifetime
# =============================================================================
def test_start_drives_receptionist_busy_at_capacity(api):
    """PRD §3.6: "On start, start_second is stamped from the logical clock's
    epoch-seconds, the answering receptionist's active_call_count increments by
    one (and the agent moves to BUSY if that brings active_call_count up to
    max_concurrent_calls), and the account's lifetime_calls_answered increments by
    one."

    With max_concurrent_calls=1, starting one call drives active_call_count to 1
    and flips the receptionist AVAILABLE -> BUSY.

    Design: Difficulty/transitive_cascade/start_call_drives_receptionist_busy_and_account_lifetime
    """
    fx.set_clock("2026-03-01T09:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=1)
    rec_headers = make_receptionist_headers(rec["id"])

    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    fx.answer_call(call["id"], rec["id"])
    started = get_success_data(api.start_call(call["id"], rec_headers))
    assert started["handling_status"] == "IN_PROGRESS"

    rec_after = validate_success(api.get_receptionist(rec["id"], rec_headers))
    assert rec_after["active_call_count"] == 1, (
        f"active_call_count {rec_after['active_call_count']} != 1")
    assert rec_after["status"] == "BUSY", (
        f"receptionist status {rec_after['status']} != BUSY (reached max_concurrent_calls 1)")


def test_start_increments_account_lifetime_calls_answered(api):
    """PRD §3.6: "On start ... the account's lifetime_calls_answered increments by
    one."
    PRD §3.1: "lifetime_calls_answered, the cumulative count of the account's
    calls that ever reached the IN_PROGRESS handling stage."

    Starting one call drives the account's lifetime_calls_answered to 1.

    Design: Difficulty/transitive_cascade/start_call_drives_receptionist_busy_and_account_lifetime
    """
    fx.set_clock("2026-03-01T09:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=1)
    rec_headers = make_receptionist_headers(rec["id"])

    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    fx.answer_call(call["id"], rec["id"])
    get_success_data(api.start_call(call["id"], rec_headers))

    acct = validate_success(api.get_account(account["id"], ADMIN))
    assert acct["lifetime_calls_answered"] == 1, (
        f"lifetime_calls_answered {acct['lifetime_calls_answered']} != 1")


# =============================================================================
# Difficulty / boundary_precision_check / empty_receptionist_pool_routes_to_overflow
# =============================================================================
def test_empty_candidate_pool_routes_business_hours_call_to_overflow(api):
    """PRD §3.5: "During business hours, if the candidate set is empty, the call is
    not rejected; instead it transitions to OVERFLOW, leaving
    answered_by_receptionist_id null and the call still open".

    With the only receptionist OFFLINE (no AVAILABLE candidate), answering a
    business-hours call returns 200 and the call moves to OVERFLOW with
    answered_by_receptionist_id null.

    Design: Difficulty/boundary_precision_check/empty_receptionist_pool_routes_to_overflow
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"], overflow_action="QUEUE")
    # Receptionist exists but is deliberately left OFFLINE -> empty candidate set.
    rec = get_success_data(api.create_receptionist(
        f.create_receptionist_payload(languages=["EN"], max_concurrent_calls=5), ADMIN))
    rec_id = rec["id"]

    call = fx.intake_call(account["id"], rec_id, caller_id="5550001", requested_language="EN")
    assert call["handling_status"] == "RINGING"
    answered = validate_success(api.answer_call(call["id"], make_receptionist_headers(rec_id)))
    assert answered["handling_status"] == "OVERFLOW", (
        f"handling_status {answered['handling_status']} != OVERFLOW on empty pool")
    assert not answered["answered_by_receptionist_id"], (
        "answered_by_receptionist_id must be null/empty after OVERFLOW")


def test_overflow_answer_returns_success_status(api):
    """PRD §3.5: "During business hours, if the candidate set is empty, the call is
    not rejected; instead it transitions to OVERFLOW".

    The empty-pool fallback is a non-error path: the answer call returns a 2xx
    status rather than an error.

    Design: Difficulty/boundary_precision_check/empty_receptionist_pool_routes_to_overflow
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"], overflow_action="QUEUE")
    rec = get_success_data(api.create_receptionist(
        f.create_receptionist_payload(languages=["EN"], max_concurrent_calls=5), ADMIN))
    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    resp = api.answer_call(call["id"], make_receptionist_headers(rec["id"]))
    data = validate_success(resp)  # asserts a 2xx envelope (no error)
    assert data["handling_status"] == "OVERFLOW"


# =============================================================================
# Corner / state_machines / intake_blocked_area_code_screens_out
# =============================================================================
def test_blocked_area_code_screens_out_at_intake(api):
    """PRD §3.4: "If an ACTIVE SpamRule exists for the account and either the
    caller's area code is among the blocked codes or the provisional score is at or
    above the rule's spam_score_threshold, the call is screened out: its
    handling_status is set directly to SCREENED_OUT, a terminal state, no
    receptionist is consumed, and its billing_status stays UNBILLED so the call is
    never charged. A screened-out call does not increment the account's
    open_call_count."

    A caller whose area code (900) is in blocked_area_codes is SCREENED_OUT,
    stays UNBILLED, and does not raise open_call_count.

    Design: Corner/state_machines/intake_blocked_area_code_screens_out
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    get_success_data(api.create_spam_rule(
        f.create_spam_rule_payload(account["id"], blocked_area_codes=["900"],
                                   spam_score_threshold=70, anonymous_penalty=40), owner))
    fx.create_published_script(account["id"])

    call = validate_success(api.create_call(
        f.create_call_payload(account["id"], caller_id="9005551234",
                              requested_language="EN"), ADMIN), expected_status=201)
    assert call["handling_status"] == "SCREENED_OUT"
    assert call["billing_status"] == "UNBILLED"

    acct = validate_success(api.get_account(account["id"], ADMIN))
    assert acct["open_call_count"] == 0, (
        f"open_call_count {acct['open_call_count']} != 0 (screened call does not open)")


# =============================================================================
# Corner / state_machines / ringing_call_abandoned_decrements_open_count
# =============================================================================
def test_abandon_ringing_call_decrements_open_count(api):
    """PRD §3.5: "A RINGING call that the caller drops can be marked abandoned by a
    Receptionist or PlatformAdmin, moving it from RINGING to ABANDONED and
    decrementing the account's open_call_count."

    A fresh RINGING call (open_call_count 1) that is abandoned reaches ABANDONED
    and open_call_count returns to 0.

    Design: Corner/state_machines/ringing_call_abandoned_decrements_open_count
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    call = validate_success(api.create_call(
        f.create_call_payload(account["id"], caller_id="5550001"), ADMIN),
        expected_status=201)

    abandoned = validate_success(api.abandon_call(call["id"], ADMIN))
    assert abandoned["handling_status"] == "ABANDONED"
    acct = validate_success(api.get_account(account["id"], ADMIN))
    assert acct["open_call_count"] == 0, (
        f"open_call_count {acct['open_call_count']} != 0 after abandon")


# =============================================================================
# Corner / state_machines / abandon_already_abandoned_call_invalid_state
# =============================================================================
def test_abandon_already_abandoned_call_rejected(api):
    """PRD §3.4: "its terminal handling states are COMPLETED, SCREENED_OUT, and
    ABANDONED."
    PRD §2.7: "that the target resource is in a state from which the requested
    transition is defined (ERR_INVALID_STATE)".

    Abandoning an already-ABANDONED (terminal) call has no defined transition and
    is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/abandon_already_abandoned_call_invalid_state
    """
    from test_helpers import validate_error, ApiErrorId
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    call = validate_success(api.create_call(
        f.create_call_payload(account["id"], caller_id="5550001"), ADMIN),
        expected_status=201)
    validate_success(api.abandon_call(call["id"], ADMIN))

    resp = api.abandon_call(call["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# Corner / calculations / spam_provisional_at_threshold_screens_out
# =============================================================================
def test_spam_provisional_at_threshold_screens_out(api):
    """PRD §3.4: "spam_score_threshold, the provisional spam score at or above
    which a call is screened out before it is ever answered".
    PRD §3.4: "If an ACTIVE SpamRule exists for the account and either the caller's
    area code is among the blocked codes or the provisional score is at or above the
    rule's spam_score_threshold, the call is screened out: its handling_status is set
    directly to SCREENED_OUT, a terminal state, no receptionist is consumed, and its
    billing_status stays UNBILLED so the call is never charged."

    With anonymous_penalty=90 and threshold=90, an anonymous call scores exactly
    90 — at the >= boundary — and is SCREENED_OUT.

    Design: Corner/calculations/spam_provisional_at_threshold_screens_out
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    owner = make_account_owner_headers(account["id"])
    get_success_data(api.create_spam_rule(
        f.create_spam_rule_payload(account["id"], blocked_area_codes=[],
                                   spam_score_threshold=90, anonymous_penalty=90), owner))
    fx.create_published_script(account["id"])

    call = validate_success(api.create_call(
        f.create_call_payload(account["id"], requested_language="EN"), ADMIN),
        expected_status=201)
    assert call["spam_score"] == 90, f"spam_score {call['spam_score']} != 90"
    assert call["handling_status"] == "SCREENED_OUT", (
        f"handling_status {call['handling_status']} != SCREENED_OUT at the >= boundary")


# =============================================================================
# Corner / calculations / routing_tiebreak_prefers_more_headroom
# =============================================================================
def test_routing_tiebreak_prefers_higher_max_concurrent_calls(api):
    """PRD §3.5: "Candidates are ranked deterministically: primarily by
    active_call_count ascending (the least-loaded agent first); ties broken by
    max_concurrent_calls descending (more headroom first); and any remaining ties
    broken by created_at ascending (the oldest receptionist first)."

    Two AVAILABLE EN agents, both 0 active. The one with the higher
    max_concurrent_calls is selected by the first tie-break.

    Design: Corner/calculations/routing_tiebreak_prefers_more_headroom
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    r_lo = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=1)
    r_hi = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=3)

    call = fx.intake_call(account["id"], r_lo["id"], caller_id="5550001", requested_language="EN")
    answered = validate_success(api.answer_call(call["id"], make_receptionist_headers(r_lo["id"])))
    assert answered["answered_by_receptionist_id"] == r_hi["id"], (
        f"selected {answered['answered_by_receptionist_id']} != r_hi {r_hi['id']} "
        "(higher max_concurrent_calls wins the tie)")
    assert answered["handling_status"] == "ANSWERED"


# =============================================================================
# Corner / cross_cutting_complexity_layers / open_call_count_reconciles_through_lifecycle
# =============================================================================
def test_open_call_count_reconciles_to_zero_on_completion(api):
    """PRD §3.1: "open_call_count, the number of the account's own calls whose
    handling is not yet terminal (that is, not in COMPLETED, ABANDONED, or
    SCREENED_OUT)".
    PRD §3.6: "and the account's open_call_count decrements." [on completion]

    open_call_count is 1 while a call is in flight (RINGING..WRAP_UP) and
    reconciles to 0 once the call reaches terminal COMPLETED.

    Design: Corner/cross_cutting_complexity_layers/open_call_count_reconciles_through_lifecycle
    """
    fx.set_clock("2026-03-01T12:00:00Z")
    plan, account = fx.create_account_on_per_call_plan()
    fx.create_published_script(account["id"])
    rec = fx.create_online_receptionist(languages=["EN"], max_concurrent_calls=5)
    rec_headers = make_receptionist_headers(rec["id"])

    call = fx.intake_call(account["id"], rec["id"], caller_id="5550001")
    acct_after_intake = validate_success(api.get_account(account["id"], ADMIN))
    assert acct_after_intake["open_call_count"] == 1, (
        f"open_call_count {acct_after_intake['open_call_count']} != 1 after intake")

    fx.answer_call(call["id"], rec["id"])
    get_success_data(api.start_call(call["id"], rec_headers))
    fx.set_clock("2026-03-01T12:01:00Z")
    get_success_data(api.wrap_call(call["id"], rec_headers))
    get_success_data(api.complete_call(call["id"], rec_headers))

    acct_after_complete = validate_success(api.get_account(account["id"], ADMIN))
    assert acct_after_complete["open_call_count"] == 0, (
        f"open_call_count {acct_after_complete['open_call_count']} != 0 after COMPLETED")
