"""Request state machine: invalid transitions, terminal lockdown, correction loop,
supporting-search freshness, and the thirty-day refile window."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_attempt,
    approve_preparation,
    create_attempt_payload,
    create_draft_attempt,
    create_filing_request,
    create_ready_request,
    create_ucc3_request,
    get_client_account,
    get_filing,
    get_request,
    make_filing_reviewer_headers,
    make_filing_specialist_headers,
    order_completed_pre_filing_search,
    reject_attempt,
    set_clock_to,
    setup_active_initial_filing,
    setup_client_world,
    submit_attempt,
    submit_intake,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_record_acceptance_from_draft_rejected(api):
    """PRD §3.5: "The attempt must be `SUBMITTED` (otherwise `ERR_FILING_INVALID_STATE`)".

    Design: Corner/state_machines/record_acceptance_from_draft_rejected
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    resp = api.record_acceptance(
        attempt["id"],
        {"filing_number": "CA-2026-0001", "filed_at": "2026-08-01T00:00:00Z"},
        OFFICER,
    )
    validate_error(resp, ApiErrorId.ERR_FILING_INVALID_STATE)
    filing = get_filing(attempt["id"])
    assert filing["effectiveness_status"] == "DRAFT"
    assert filing.get("filing_number") is None, (
        "a failed acceptance assigns no filing number"
    )


def test_withdraw_submitted_attempt_rejected(api):
    """PRD §3.5: "Finally, a `DRAFT` attempt may be withdrawn by a `FilingSpecialist`,
    moving it `DRAFT` → `WITHDRAWN` with a `WITHDRAWN` event; from any other state
    withdrawal is rejected with `ERR_FILING_INVALID_STATE`."

    Design: Corner/state_machines/withdraw_submitted_attempt_rejected
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    resp = api.withdraw_filing(attempt["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_FILING_INVALID_STATE)
    assert get_filing(attempt["id"])["effectiveness_status"] == "SUBMITTED"


def test_cancel_in_process_request_rejected(api):
    """PRD §3.6: "A `FilingSpecialist` may cancel a request in `DRAFT_INTAKE`,
    `IN_REVIEW`, `READY`, or `CORRECTION_REQUIRED`; attempting to cancel one that is
    `IN_PROCESS` is rejected with `ERR_REQUEST_IN_PROCESS`."

    Design: Corner/state_machines/cancel_in_process_request_rejected
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    resp = api.cancel_filing_request(request["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_REQUEST_IN_PROCESS)
    assert get_request(request["id"])["status"] == "IN_PROCESS"


def test_terminal_lockdown_fulfilled_request_submit_intake(api):
    """PRD §3.6: "Both `FULFILLED` and `CANCELLED` are terminal states for a request".
    PRD §2.9: "the request is in a valid from-state for the requested transition
    (`ERR_REQUEST_INVALID_STATE`, or `ERR_REQUEST_IN_PROCESS` for cancellation during
    processing)".

    Design: Corner/state_machines/terminal_lockdown_fulfilled_request_submit_intake
    """
    ctx = setup_active_initial_filing()
    resp = api.submit_intake(ctx["request"]["id"], make_filing_specialist_headers("spec-1"))
    validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
    assert get_request(ctx["request"]["id"])["status"] == "FULFILLED"


def test_continuation_intake_on_terminated_target_rejected(api):
    """PRD §3.2: "For the UCC-3 kinds the target filing must be `ACTIVE`, failing with
    `ERR_TARGET_FILING_NOT_ACTIVE` otherwise."

    Design: Corner/state_machines/continuation_intake_on_terminated_target_rejected
    """
    ctx = setup_active_initial_filing()
    root = ctx["filing"]
    # Fully terminate the root filing.
    termination = create_ucc3_request(
        "TERMINATION", ctx["client"], ctx["debtor"], ctx["secured_party"], root["id"])
    submit_intake(termination["id"], user_id="spec-1")
    approve_preparation(termination["id"])
    term_attempt = create_draft_attempt(
        termination["id"], debtor_name_on_filing="Acme Manufacturing, Inc.",
        collateral_text=None)
    submit_attempt(term_attempt["id"])
    accept_attempt(term_attempt["id"], filing_number="CA-2026-0009",
                   filed_at="2026-08-01T00:00:00Z")
    assert get_filing(root["id"])["effectiveness_status"] == "TERMINATED"
    # Creation of a CONTINUATION request is OCC-guarded only; the ACTIVE gate fires at intake.
    continuation = create_ucc3_request(
        "CONTINUATION", ctx["client"], ctx["debtor"], ctx["secured_party"], root["id"])
    resp = api.submit_intake(continuation["id"], make_filing_specialist_headers("spec-1"))
    validate_error(resp, ApiErrorId.ERR_TARGET_FILING_NOT_ACTIVE)
    assert get_request(continuation["id"])["status"] == "DRAFT_INTAKE"
    assert get_filing(root["id"])["effectiveness_status"] == "TERMINATED"


def test_search_stale_boundary_ninety_days(api):
    """PRD §3.3: "When the request carries a `supporting_search_id`, that search must
    be a completed pre-filing diligence search — its status must be `COMPLETED` — and
    its `through_date` must be no more than ninety days before the current instant; a
    search whose certified-through date is exactly ninety days old is still fresh, and
    an older one fails approval with `ERR_SEARCH_STALE`."

    Design: Corner/validations/search_stale_boundary_ninety_days
    """
    world = setup_client_world()
    # Exactly 90 days old at the 2026-08-01 default clock: fresh.
    fresh_search = order_completed_pre_filing_search(
        world["client"], world["debtor"], "2026-05-03T00:00:00Z")
    # 91 days old: stale.
    stale_search = order_completed_pre_filing_search(
        world["client"], world["debtor"], "2026-05-02T00:00:00Z")
    req_fresh = create_filing_request(world["client"], world["debtor"],
                                      world["secured_party"],
                                      supporting_search_id=fresh_search["id"])
    submit_intake(req_fresh["id"], user_id="spec-1")
    req_stale = create_filing_request(world["client"], world["debtor"],
                                      world["secured_party"],
                                      supporting_search_id=stale_search["id"])
    submit_intake(req_stale["id"], user_id="spec-1")
    approved = validate_success(
        api.approve_preparation(req_fresh["id"], make_filing_reviewer_headers("rev-1")),
        expected_status=200)
    assert approved["status"] == "READY", "a search exactly ninety days old is still fresh"
    resp = api.approve_preparation(req_stale["id"], make_filing_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_SEARCH_STALE)
    assert get_request(req_stale["id"])["status"] == "IN_REVIEW"


def test_refile_window_inclusive_then_expired(api):
    """PRD §3.4: "On a refile — an attempt created after a rejection —
    `supersedes_attempt_id` points at the latest `REJECTED` attempt under the same
    request, and creation is permitted only while the current instant is no later than
    thirty days after that attempt's `rejected_at`; the boundary is inclusive, so
    creation exactly thirty days after the rejection is allowed and anything later
    fails with `ERR_REFILE_WINDOW_EXPIRED`."

    Design: Corner/validations/refile_window_inclusive_then_expired
    """
    world = setup_client_world()
    # Two requests each with an attempt rejected at 2026-08-01, each re-approved.
    req1 = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    att1 = create_draft_attempt(req1["id"])
    submit_attempt(att1["id"])
    reject_attempt(att1["id"], reason="MISSING_SIGNATURE")
    approve_preparation(req1["id"])
    req2 = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    att2 = create_draft_attempt(req2["id"])
    submit_attempt(att2["id"])
    reject_attempt(att2["id"], reason="FEE_INCORRECT")
    approve_preparation(req2["id"])
    # Exactly thirty days after rejection: the boundary is inclusive.
    set_clock_to("2026-08-31T00:00:00Z")
    refile = validate_success(
        api.create_attempt(req1["id"], create_attempt_payload(), SPECIALIST),
        expected_status=201)
    assert refile["effectiveness_status"] == "DRAFT"
    assert refile["supersedes_attempt_id"] == att1["id"], (
        "the refile must link the latest REJECTED attempt"
    )
    # One day later the window has closed.
    set_clock_to("2026-09-01T00:00:00Z")
    resp = api.create_attempt(req2["id"], create_attempt_payload(), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_REFILE_WINDOW_EXPIRED)


def test_correction_cycle_refile_links_superseded_attempt(api):
    """PRD §3.4: "On a refile — an attempt created after a rejection —
    `supersedes_attempt_id` points at the latest `REJECTED` attempt under the same
    request".
    PRD §3.5: "- **`INITIAL`.** The attempt's `expiration_at` is set to exactly sixty
    calendar months after `filed_at`, preserving the day of month."

    Design: Difficulty/non_linear_state_machine/request_correction_cycle_rejection_refile_loop
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    first = create_draft_attempt(request["id"], secured_amount_cents=500000)
    submit_attempt(first["id"])
    reject_attempt(first["id"], reason="NAME_MISMATCH")
    approve_preparation(request["id"])  # CORRECTION_REQUIRED -> READY
    second = validate_success(
        api.create_attempt(request["id"], create_attempt_payload(
            secured_amount_cents=500000), SPECIALIST),
        expected_status=201)
    assert second["supersedes_attempt_id"] == first["id"], (
        "the refiled attempt must link the REJECTED attempt, proving the loop"
    )
    submit_attempt(second["id"])
    filing = accept_attempt(second["id"], filing_number="CA-2026-0002",
                            filed_at="2026-08-01T00:00:00Z")
    assert get_filing(first["id"])["effectiveness_status"] == "REJECTED"
    assert filing["effectiveness_status"] == "ACTIVE"
    assert filing["expiration_at"] == "2031-08-01T00:00:00Z"
    assert get_request(request["id"])["status"] == "FULFILLED"


def test_correction_cycle_rejection_moves_request_to_correction_required(api):
    """PRD §3.5: "The rejection stores the code, the note, and `rejected_at`; credits
    the client's `fees_refunded_total_cents` by the attempt's `charged_fee_cents`;
    moves the attempt `SUBMITTED` → `REJECTED`; moves the parent request `IN_PROCESS`
    → `CORRECTION_REQUIRED`; and appends a `REJECTED` event."
    PRD §3.3: "Approval is performed by a `FilingReviewer` and moves the request to
    `READY` — from `IN_REVIEW` on the first pass, or from `CORRECTION_REQUIRED` inside
    the correction loop."

    Design: Difficulty/non_linear_state_machine/request_correction_cycle_rejection_refile_loop
    """
    world = setup_client_world()
    request = create_ready_request(world["client"], world["debtor"], world["secured_party"])
    attempt = create_draft_attempt(request["id"])
    submit_attempt(attempt["id"])
    reject_attempt(attempt["id"], reason="NAME_MISMATCH")
    mid = get_request(request["id"])
    assert mid["status"] == "CORRECTION_REQUIRED", (
        f"rejection must open the correction loop, got {mid['status']}"
    )
    client_mid = get_client_account(world["client"]["id"])
    assert client_mid["fees_refunded_total_cents"] == 10000, (
        "rejection credits the charged fee back to the client ledger"
    )
    reapproved = approve_preparation(request["id"])
    assert reapproved["status"] == "READY", (
        "re-approval inside the correction loop moves the request back to READY"
    )


def test_state_error_wins_over_temporal_on_approve(api):
    """PRD §2.9: "Incoming requests are checked in a fixed order, and the first failing
    check determines the error returned."
    PRD §2.9 item 7: "the request is in a valid from-state for the requested transition
    (`ERR_REQUEST_INVALID_STATE`, or `ERR_REQUEST_IN_PROCESS` for cancellation during
    processing)".
    PRD §2.9 item 9: "`filed_at` bracketing (`ERR_INVALID_FILED_AT`), the
    continuation window (`ERR_CONTINUATION_OUTSIDE_WINDOW`), the thirty-day refile
    window (`ERR_REFILE_WINDOW_EXPIRED`), supporting-search freshness
    (`ERR_SEARCH_STALE`), and verification through-date coverage
    (`ERR_SEARCH_THROUGH_DATE_TOO_EARLY`)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_approve_preparation
    """
    world = setup_client_world()
    stale_search = order_completed_pre_filing_search(
        world["client"], world["debtor"], "2026-04-15T00:00:00Z")
    # Never submit intake: the request stays in DRAFT_INTAKE (a state violation) AND
    # the supporting search is stale (a temporal violation) at approval time.
    request = create_filing_request(world["client"], world["debtor"],
                                    world["secured_party"],
                                    supporting_search_id=stale_search["id"])
    resp = api.approve_preparation(request["id"], make_filing_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
    assert get_request(request["id"])["status"] == "DRAFT_INTAKE"


def test_stale_search_rejected_on_approve_when_state_valid(api):
    """PRD §3.3: "When the request carries a `supporting_search_id`, that search must
    be a completed pre-filing diligence search — its status must be `COMPLETED` — and
    its `through_date` must be no more than ninety days before the current instant; a
    search whose certified-through date is exactly ninety days old is still fresh, and
    an older one fails approval with `ERR_SEARCH_STALE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_approve_preparation
    """
    world = setup_client_world()
    stale_search = order_completed_pre_filing_search(
        world["client"], world["debtor"], "2026-04-15T00:00:00Z")
    request = create_filing_request(world["client"], world["debtor"],
                                    world["secured_party"],
                                    supporting_search_id=stale_search["id"])
    submit_intake(request["id"], user_id="spec-1")
    resp = api.approve_preparation(request["id"], make_filing_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_SEARCH_STALE)
    assert get_request(request["id"])["status"] == "IN_REVIEW"
