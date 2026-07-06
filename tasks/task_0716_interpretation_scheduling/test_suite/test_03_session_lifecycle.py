"""Assignment and session lifecycle: the dispute/reopen cycle, the parallel
lifecycle/billing dimensions, load conservation, and offer-window transitions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    provision_med_phone, create_billed_med_phone_session,
    create_connected_session, create_ended_session, dispatch_accept,
    dispatch_request, create_request, set_clock, open_invoice,
    make_client_headers, make_interpreter_headers, coordinator_headers,
    factories,
)


def test_session_dispute_reopen_end_cycle_rebills(api):
    """PRD 3.8: "They may **reopen** the session, which clears `ended_at` and returns the
    session to `ACTIVE` so additional billable time can accrue; a subsequent end re-runs
    session billing from scratch, so the `ACTIVE → ENDED → DISPUTED → ACTIVE` loop may
    repeat as a revision cycle."

    Design: Difficulty/non_linear_state_machine/session_dispute_reopen_cycle
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    client_h = make_client_headers(env["client"]["id"])
    itp_h = make_interpreter_headers(env["interpreter"]["id"])
    validate_success(api.dispute_session(session["id"], client_h))
    validate_success(api.reopen_session(session["id"], coordinator_headers()))  # back to ACTIVE
    set_clock("2026-03-10T09:50:00Z")
    reended = validate_success(api.end_session(session["id"], itp_h))
    # connected_at stayed 09:00; new end 09:50 -> 3000s -> ceil 50 min -> 50*195 = 9750.
    assert reended["status"] == "ENDED"
    assert reended["billed_units"] == 50, f"expected 50, got {reended['billed_units']}"
    assert reended["billed_amount_cents"] == 9750, (
        f"expected 9750c after re-bill, got {reended['billed_amount_cents']}"
    )


def test_reopened_session_returns_to_active(api):
    """PRD 3.8: "They may **reopen** the session, which clears `ended_at` and returns the
    session to `ACTIVE` so additional billable time can accrue."

    Design: Difficulty/non_linear_state_machine/session_dispute_reopen_cycle
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg, session = create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    validate_success(api.dispute_session(session["id"], make_client_headers(env["client"]["id"])))
    reopened = validate_success(api.reopen_session(session["id"], coordinator_headers()))
    assert reopened["status"] == "ACTIVE", f"expected ACTIVE after reopen, got {reopened['status']}"


def test_assignment_lifecycle_completed_billing_invoiced_independent(api):
    """PRD 2.10: "an assignment evolves along two independent dimensions at once: its
    lifecycle_status (the operational arc) and its billing_status (the money arc); a
    transition on one dimension does not implicitly move the other except where Section 3
    says so explicitly."

    Design: Difficulty/non_linear_state_machine/assignment_parallel_lifecycle_and_billing_dimensions
    """
    env = create_billed_med_phone_session()  # ENDED session, assignment COMPLETED/BILLABLE
    # The invoice sweep flips billing_status to INVOICED while lifecycle stays COMPLETED.
    open_invoice(env["client"]["id"])
    asg = validate_success(api.get_assignment(env["assignment"]["id"], coordinator_headers()))
    assert asg["lifecycle_status"] == "COMPLETED", f"got {asg['lifecycle_status']}"
    assert asg["billing_status"] == "INVOICED", f"got {asg['billing_status']}"


def test_assignment_billable_at_end_before_invoice(api):
    """PRD 3.5: "the assignment moves `lifecycle_status` from `IN_SESSION` to `COMPLETED`
    with `billing_status` set to `BILLABLE`,"

    Design: Difficulty/non_linear_state_machine/assignment_parallel_lifecycle_and_billing_dimensions
    """
    env = create_billed_med_phone_session()  # ended, not yet invoiced
    asg = validate_success(api.get_assignment(env["assignment"]["id"], coordinator_headers()))
    assert asg["lifecycle_status"] == "COMPLETED"
    assert asg["billing_status"] == "BILLABLE", (
        f"billing should be BILLABLE before any invoice sweep, got {asg['billing_status']}"
    )


def test_interpreter_load_returns_to_zero_after_completion(api):
    """PRD 3.5: "the interpreter's `active_load` decrements by 1 (and if the interpreter had
    been `BUSY`, its `status` returns to `AVAILABLE`),"

    Design: Difficulty/compensating_invariant/interpreter_load_accept_complete_conserved
    """
    env = provision_med_phone(max_concurrent_load=2)
    set_clock("2026-03-10T09:00:00Z")
    create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    itp = validate_success(api.get_interpreter(env["interpreter"]["id"], coordinator_headers()))
    assert itp["active_load"] == 0, f"load must return to 0 after completion, got {itp['active_load']}"


def test_interpreter_available_after_completion(api):
    """PRD 3.5: "the interpreter's `active_load` decrements by 1 (and if the interpreter had
    been `BUSY`, its `status` returns to `AVAILABLE`),"

    Design: Difficulty/compensating_invariant/interpreter_load_accept_complete_conserved
    """
    # max_concurrent_load=1 so accept drives status to BUSY; completion must restore AVAILABLE.
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    create_ended_session(
        env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"],
        connect_iso="2026-03-10T09:00:00Z", end_iso="2026-03-10T09:20:00Z",
    )
    itp = validate_success(api.get_interpreter(env["interpreter"]["id"], coordinator_headers()))
    assert itp["status"] == "AVAILABLE", f"expected AVAILABLE, got {itp['status']}"
    assert itp["active_load"] == 0


def test_accept_already_accepted_returns_invalid_state(api):
    """PRD 3.4: "Accepting moves lifecycle_status to ACCEPTED" and PRD 2.6 establishes that
    a transition is permitted only "whether the target is in a state from which the
    requested transition is defined (ERR_INVALID_STATE)."

    Design: Corner/state_machines/accept_already_accepted_returns_invalid_state
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req, asg = dispatch_accept(env["client"]["id"], env["lp"]["id"], env["interpreter"]["id"])
    resp = api.accept_assignment(asg["id"], make_interpreter_headers(env["interpreter"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_decline_offered_assignment_bubbles_request_to_open(api):
    """PRD 3.4: "The interpreter may instead decline the offer, moving `lifecycle_status` to
    `DECLINED`, recomputing `acceptance_pct`, and bubbling the parent request from `ASSIGNED`
    back to `OPEN` so it can be re-dispatched to someone else."

    Design: Corner/state_machines/decline_offered_assignment_bubbles_request_to_open
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(env["client"]["id"], env["lp"]["id"])
    asg = dispatch_request(req["id"], req["version"])
    declined = validate_success(
        api.decline_assignment(asg["id"], make_interpreter_headers(env["interpreter"]["id"]))
    )
    assert declined["lifecycle_status"] == "DECLINED"
    request = validate_success(api.get_request(req["id"], coordinator_headers()))
    assert request["status"] == "OPEN", f"request must bubble to OPEN, got {request['status']}"


def test_accept_after_offer_ttl_returns_offer_expired(api):
    """PRD 3.4: "An accept attempted after the offer's deadline is rejected with
    ERR_OFFER_EXPIRED (HTTP 409)."

    Design: Corner/state_machines/offer_expires_after_ttl_then_observed_expired
    """
    env = provision_med_phone()
    set_clock("2026-03-10T09:00:00Z")
    req = create_request(env["client"]["id"], env["lp"]["id"])
    asg = dispatch_request(req["id"], req["version"])  # offered_at = 09:00
    set_clock("2026-03-10T09:10:00Z")  # 600s, well past the 120s TTL
    resp = api.accept_assignment(asg["id"], make_interpreter_headers(env["interpreter"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)
