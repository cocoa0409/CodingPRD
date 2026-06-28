"""Superbill reimbursement (service-value basis), async messaging, thread
freezing, and scheduled clock-driven actions (PRD §3.4, §3.6, §3.7, §3.9).

Covers the dual_variant_calc superbill instance, the cross-entity
message-vs-thread dependency, and superbill / messaging / scheduled-action
corner probes.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, cleared_client, accepting_therapist, propose_match, accept_match,
    active_match, active_match_with_credits, get_match_version, get_thread,
    schedule_session, subscription_with_paid_cycle, draft_superbill,
    completed_session_in_window, create_client, submit_intake, create_subscription,
    charge_cycle, get_subscription, get_subscription_version, paused_subscription,
    api_client, make_client_headers, make_therapist_headers,
)
from test_helpers import TEST_USERS


def _client(cid):
    return make_client_headers(cid)


def _therapist(tid):
    return make_therapist_headers(tid)


def _clinical():
    return TEST_USERS["clinical_admin_headers"]


def _billing():
    return TEST_USERS["billing_admin_headers"]


# ==========================================================================
# Difficulty: dual_variant_calc — superbill service-value basis
# ==========================================================================
def test_superbill_uses_list_amount_service_value(api):
    """PRD §3.9: "the system finds the `PAID` `BillingCycle` whose own half-open period contains
    the session's `starts_at`, takes the per-session value as the floor of that cycle's
    `list_amount_cents` divided by its `credits_granted` (which is always at least 1), and adds
    that value to a running total. The final `reimbursable_amount_cents` is the exact sum of those
    per-session values with no post-sum rounding."
    PRD §3.9: "Issuing the superbill recomputes those totals and moves it from `DRAFT` to
    `ISSUED`, but issuance is permitted only when at least one completed session falls in the
    window — a `session_count` of at least 1"

    Design: Difficulty/dual_variant_calc/superbill_service_value_basis_on_superbill
    """
    set_clock("2026-06-01T00:00:00Z")
    info = completed_session_in_window(
        state_code="CA", weekly_credit_grant=1,
        session_start="2026-06-02T10:00:00Z", session_end="2026-06-02T11:00:00Z",
    )
    sb = draft_superbill(info["client"]["id"], "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    issued = validate_success(api.issue_superbill(sb["id"], _billing()))
    assert issued["status"] == "ISSUED", issued
    assert issued["session_count"] == 1, issued
    # cycle list 9900, 1 credit -> floor(9900/1) = 9900 (service value, not charged amount).
    assert issued["reimbursable_amount_cents"] == 9900, issued


def test_void_superbill_cannot_be_reissued(api):
    """PRD §3.9: "An issued superbill may later be voided by a `BillingAdmin`, moving it from
    `ISSUED` to the terminal `VOID`."
    PRD §2.11: "the target resource's current state is checked against the requested transition,
    raising `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a state from which the
    transition is legal."

    Design: Corner/state_machines/terminal_state_lockdown_void_superbill_cannot_issue
    """
    set_clock("2026-06-01T00:00:00Z")
    info = completed_session_in_window(
        state_code="CA", weekly_credit_grant=1,
        session_start="2026-06-02T10:00:00Z", session_end="2026-06-02T11:00:00Z",
    )
    sb = draft_superbill(info["client"]["id"], "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
    validate_success(api.issue_superbill(sb["id"], _billing()))
    validate_success(api.void_superbill(sb["id"], _billing()))
    resp = api.issue_superbill(sb["id"], _billing())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Difficulty: cross_entity_state_dependency — message blocked by frozen thread
# ==========================================================================
def test_post_message_blocked_when_thread_frozen(api):
    """PRD §3.4: "Either the client or the therapist may request a switch on an `ACTIVE` match,
    which requires a `switch_reason` to be supplied and moves the match from `ACTIVE` to
    `SWITCH_REQUESTED` while freezing the match's thread from `OPEN` to `FROZEN`"
    PRD §3.4: "Messages may be posted only to a thread that is `OPEN`; posting to a `FROZEN` or
    `ARCHIVED` thread is rejected with `ERR_THREAD_NOT_OPEN` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/message_post_blocked_by_thread_frozen_pair_message_thread
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    match = accept_match(proposed["id"], client["id"])
    thread = get_thread(match["id"], client["id"])
    validate_success(api.request_switch(
        match["id"], {"switch_reason": "FIT"}, _client(client["id"])
    ))  # freezes the thread
    resp = api.post_message(thread["id"], {"body": "hello"}, _client(client["id"]))
    validate_error(resp, ApiErrorId.ERR_THREAD_NOT_OPEN.value)


# ==========================================================================
# Corner: client message to OPEN thread increments unread_for_therapist
# ==========================================================================
def test_client_message_increments_unread_for_therapist(api):
    """PRD §3.4: "the created message records its owning `thread_id` and a `sender_role` derived
    from the acting role (`CLIENT` or `THERAPIST`). When the sender is the client, the thread's
    `unread_for_therapist` increments."

    Design: Corner/endpoints/post_message_increments_unread_for_therapist
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    match = accept_match(proposed["id"], client["id"])
    thread = get_thread(match["id"], client["id"])
    validate_success(api.post_message(
        thread["id"], {"body": "hi there"}, _client(client["id"])
    ), 201)
    after = validate_success(api.get_thread(thread["id"], _client(client["id"])))
    assert after["unread_for_therapist"] == 1, after


# ==========================================================================
# Corner (cross-cutting): scheduled auto-resume at pause_resumes_on
# ==========================================================================
def test_clock_advance_auto_resumes_paused_subscription(api):
    """PRD §2.10: "auto-resumes any `PAUSED` subscription whose `pause_resumes_on` is at or before
    the new instant"
    PRD §3.7: "A paused subscription returns to `ACTIVE` either when the client manually resumes it
    or when the logical clock reaches its `pause_resumes_on`. Resuming clears `pause_resumes_on`
    back to null and resets `current_period_start` to the current clock"

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_auto_resume_at_pause_date
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])
    paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z")  # reaches pause_resumes_on
    after = get_subscription(sub["id"], client["id"])
    assert after["status"] == "ACTIVE", after
    assert after["pause_resumes_on"] is None, after
