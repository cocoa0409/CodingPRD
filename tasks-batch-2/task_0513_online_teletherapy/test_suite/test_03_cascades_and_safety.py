"""Transitive cascades (finalize-cancel and crisis resolution) and the safety
suspension loop (PRD §3.7, §3.8).

Covers the transitive_cascade difficulty instances, the subscription
pause/resume cycle, and crisis-escalation corner probes.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, cleared_client, accepting_therapist, propose_match, accept_match,
    active_match, get_match, get_thread, get_client, get_therapist,
    create_client, submit_intake, create_subscription, charge_cycle,
    cancel_scheduled_subscription, get_subscription, get_subscription_version,
    paused_subscription, raise_escalation, acknowledge_escalation,
    api_client, make_client_headers,
)
from test_helpers import TEST_USERS


def _client(cid):
    return make_client_headers(cid)


def _clinical():
    return TEST_USERS["clinical_admin_headers"]


def _billing():
    return TEST_USERS["billing_admin_headers"]


# ==========================================================================
# Difficulty: transitive_cascade — finalize-cancel depth-4
# ==========================================================================
def test_finalize_cancel_cascades_client_match_caseload(api):
    """PRD §3.7: "Reaching `CANCELLED` cascades into closing the client: a client in `ACTIVE` or
    `SUSPENDED` with no other non-terminal subscription moves to `CLOSED`, which in turn ends all
    of the client's `ACTIVE` matches (moving them to `ENDED`), expires all of the client's
    `AVAILABLE` or `RESERVED` credits (moving them to `EXPIRED`), and archives all of the client's
    `OPEN` or `FROZEN` message threads (moving them to `ARCHIVED`)."
    PRD §3.4: "the match becomes `ENDED`, the therapist's `active_caseload` decrements by one
    (again possibly bubbling `FULL` to `ACCEPTING`), and the match's thread is archived."

    Design: Difficulty/transitive_cascade/finalize_cancel_subscription_client_match_caseload_depth4
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    accept_match(proposed["id"], client["id"])
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])
    cancel_scheduled_subscription(client["id"], sub["id"])  # cancel_effective_on = period_start + 7d
    # PRD §2.10: advancing the clock to cancel_effective_on auto-finalizes the
    # CANCEL_SCHEDULED subscription to CANCELLED, firing the close cascade.
    set_clock("2026-06-08T00:00:00Z")
    finalized = get_subscription(sub["id"], client["id"])
    assert finalized["status"] == "CANCELLED", finalized
    after_client = get_client(client["id"])
    assert after_client["status"] == "CLOSED", after_client
    after_match = get_match(proposed["id"])
    assert after_match["status"] == "ENDED", after_match
    after_t = get_therapist(therapist["id"])
    assert after_t["active_caseload"] == 0, after_t


# ==========================================================================
# Difficulty: transitive_cascade — acute resolve depth-3
# ==========================================================================
def test_acute_resolve_restores_client_and_unfreezes_thread(api):
    """PRD §3.8: "If the escalation being resolved was `ACUTE` and the client has no other `OPEN`
    or `ACKNOWLEDGED` `ACUTE` escalation remaining, the client is restored from `SUSPENDED` to
    `ACTIVE`, their `risk_flag` is cleared to `NONE`, and their frozen threads are unfrozen from
    `FROZEN` back to `OPEN` (a thread unfreezes only when its owning match is itself still
    `ACTIVE`)."

    Design: Difficulty/transitive_cascade/acute_resolve_escalation_client_thread_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    match = accept_match(proposed["id"], client["id"])
    thread = get_thread(match["id"], client["id"])
    esc = raise_escalation(client["id"], severity="ACUTE")  # client SUSPENDED, thread FROZEN
    acknowledge_escalation(esc["id"])
    resolved = validate_success(api.resolve_escalation(esc["id"], _clinical()))
    assert resolved["status"] == "RESOLVED", resolved
    after_client = get_client(client["id"])
    assert after_client["status"] == "ACTIVE", after_client
    assert after_client["risk_flag"] == "NONE", after_client
    after_thread = validate_success(api.get_thread(thread["id"], _client(client["id"])))
    assert after_thread["status"] == "OPEN", after_thread


# ==========================================================================
# Difficulty: non_linear_state_machine — subscription pause/resume cycle
# ==========================================================================
def test_subscription_pause_then_resume_clears_pause_field(api):
    """PRD §3.7: "A paused subscription returns to `ACTIVE` either when the client manually
    resumes it or when the logical clock reaches its `pause_resumes_on`. Resuming clears
    `pause_resumes_on` back to null and resets `current_period_start` to the current clock; the
    subscription's `version` increments."

    Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])
    set_clock("2026-06-02T00:00:00Z")
    paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")
    resumed = validate_success(api.resume_subscription(sub["id"], _client(client["id"])))
    assert resumed["status"] == "ACTIVE", resumed
    assert resumed["pause_resumes_on"] is None, resumed


# ==========================================================================
# Corner: crisis ACUTE suspends client and sends safety resources
# ==========================================================================
def test_acute_escalation_suspends_client_and_sends_resources(api):
    """PRD §3.8: "Raising one creates a `CrisisEscalation` in `OPEN` status for the named client,
    records the `raised_by_role` of the raiser, and attaches the standardized safety-resource
    packet so that `safety_resources_sent` is set true on open."
    PRD §3.8: "An `ACUTE` escalation is more consequential: it sets the client's `risk_flag` to
    `ACUTE`, suspends the client by moving them from `ACTIVE` to `SUSPENDED`, and freezes the
    client's message threads from `OPEN` to `FROZEN`."

    Design: Corner/endpoints/crisis_acute_suspends_client_and_sends_resources
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    accept_match(proposed["id"], client["id"])  # client now ACTIVE
    esc = validate_success(api.create_crisis_escalation(
        client["id"], {"severity": "ACUTE"}, _client(client["id"])
    ), 201)
    assert esc["safety_resources_sent"] is True, esc
    after = get_client(client["id"])
    assert after["status"] == "SUSPENDED", after
    assert after["risk_flag"] == "ACUTE", after


# ==========================================================================
# Corner (errors): accept blocked when client risk_flag ACUTE
# ==========================================================================
def test_accept_blocked_when_client_risk_acute(api):
    """PRD §3.3: "An attempt to accept while the client's risk posture is `ACUTE` is rejected with
    `ERR_CLIENT_RISK_BLOCKED` (HTTP 409)."

    Design: Corner/errors/client_risk_blocked_on_accept_when_acute
    """
    set_clock("2026-06-01T00:00:00Z")
    client = cleared_client(state_code="CA")
    therapist = accepting_therapist(state_code="CA")
    proposed = propose_match(client["id"], therapist["id"])
    # ACUTE escalation sets risk_flag ACUTE while the match remains PROPOSED.
    raise_escalation(client["id"], severity="ACUTE", as_clinical=True)
    resp = api.accept_match(proposed["id"], _client(client["id"]))
    validate_error(resp, ApiErrorId.ERR_CLIENT_RISK_BLOCKED.value)
