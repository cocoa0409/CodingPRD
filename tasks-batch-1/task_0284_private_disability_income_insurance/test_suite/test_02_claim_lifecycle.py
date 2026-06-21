"""Claim review cycle, parallel policy state dimensions, invalid transitions,
terminal-state lockdown, activation/termination preconditions and cascades,
premium-state guards, and the OCC-guarded income-report supersede.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    get_success_data,
    assert_claim,
    create_policy_payload, create_claim_payload, create_income_report_payload,
    TEST_USERS, make_policyholder_headers,
    setup_book, setup_active_policy, setup_pending_policy,
    setup_submitted_claim, setup_under_review_claim, setup_approved_claim,
    setup_approved_total_with_periods,
    drive_premium_to_grace, drive_premium_to_default,
    file_claim,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]


# ─── Difficulty / non_linear_state_machine ────────────

def test_claim_revision_loop_reenters_under_review_then_approves(api):
    """PRD §3.5: "resuming review then moves it from PENDING_INFO back to
    UNDER_REVIEW (requiring PENDING_INFO, else ERR_CLAIM_NOT_PENDING_INFO). This
    UNDER_REVIEW → PENDING_INFO → UNDER_REVIEW loop may repeat any number of
    times, and each leg increments the claim version."
    PRD §3.6: "On success the claim moves from UNDER_REVIEW to APPROVED and its
    version increments."

    Design: Difficulty/non_linear_state_machine/claim_revision_loop_under_review_pending_info_cycle
    """
    book = setup_under_review_claim(clock_months=5)
    cid = book["claim"]["id"]
    get_success_data(api.request_info(cid, ADJ))
    resumed = validate_success(api.resume_review(cid, ADJ), 200)
    assert resumed["status"] == "UNDER_REVIEW"
    approved = validate_success(api.approve_claim(cid, ADJ), 200)
    assert approved["status"] == "APPROVED"


def test_claim_revision_loop_increments_version_each_leg(api):
    """PRD §3.5: "This UNDER_REVIEW → PENDING_INFO → UNDER_REVIEW loop may repeat
    any number of times, and each leg increments the claim version."

    Design: Difficulty/non_linear_state_machine/claim_revision_loop_under_review_pending_info_cycle
    """
    book = setup_under_review_claim(clock_months=5)
    cid = book["claim"]["id"]
    v_under_review = book["claim"]["version"]
    after_request = validate_success(api.request_info(cid, ADJ), 200)
    assert after_request["status"] == "PENDING_INFO"
    assert after_request["version"] == v_under_review + 1
    after_resume = validate_success(api.resume_review(cid, ADJ), 200)
    assert after_resume["status"] == "UNDER_REVIEW"
    assert after_resume["version"] == v_under_review + 2


def test_policy_parallel_premium_dimension_independent_of_lifecycle(api):
    """PRD §3.3: "Recording a missed premium on an ACTIVE policy whose
    premium_status is CURRENT advances it to GRACE".
    PRD §3.3: "Paying the premium while in GRACE returns premium_status to CURRENT".

    Design: Difficulty/non_linear_state_machine/policy_parallel_lifecycle_and_premium_dimensions
    """
    book = setup_active_policy()
    pid = book["policy"]["id"]
    after_miss = validate_success(api.premium_miss(pid, UW), 200)
    assert after_miss["premium_status"] == "GRACE"
    assert after_miss["lifecycle_status"] == "ACTIVE"
    after_pay = validate_success(api.premium_pay(pid, UW), 200)
    assert after_pay["premium_status"] == "CURRENT"
    assert after_pay["lifecycle_status"] == "ACTIVE"


def test_policy_parallel_dimensions_version_increments(api):
    """PRD §3.3: "this first leg requires the policy to be ACTIVE (otherwise
    ERR_POLICY_NOT_ACTIVE) and the premium status to be CURRENT (otherwise
    ERR_PREMIUM_NOT_CURRENT), and it increments the policy version."

    Design: Difficulty/non_linear_state_machine/policy_parallel_lifecycle_and_premium_dimensions
    """
    book = setup_active_policy()
    pid = book["policy"]["id"]
    base_v = book["policy"]["version"]
    after_miss = validate_success(api.premium_miss(pid, UW), 200)
    assert after_miss["premium_status"] == "GRACE"
    assert after_miss["version"] == base_v + 1
    after_pay = validate_success(api.premium_pay(pid, UW), 200)
    assert after_pay["premium_status"] == "CURRENT"
    assert after_pay["version"] == base_v + 2


# ─── Corner / state_machines ──────────────────────────

def test_submit_already_submitted_claim_rejected(api):
    """PRD §3.5: "The claim must be in DRAFT (otherwise ERR_CLAIM_NOT_DRAFT)".

    Design: Corner/state_machines/submit_claim_from_already_submitted_returns_invalid_state
    """
    book = setup_submitted_claim(clock_months=0)
    ph = make_policyholder_headers(book["policyholder"]["id"])
    resp = api.submit_claim(book["claim"]["id"], ph)
    validate_error(resp, "ERR_CLAIM_NOT_DRAFT")


def test_approve_from_denied_terminal_rejected(api):
    """PRD §3.5: "Denial moves the claim to the terminal DENIED status (requiring
    UNDER_REVIEW, else ERR_CLAIM_NOT_UNDER_REVIEW) and increments version."
    PRD §3.6: "Approving an UNDER_REVIEW claim ... The claim must be UNDER_REVIEW
    (ERR_CLAIM_NOT_UNDER_REVIEW)."

    Design: Corner/state_machines/approve_claim_from_denied_terminal_returns_invalid_state
    """
    book = setup_under_review_claim(clock_months=5)
    cid = book["claim"]["id"]
    get_success_data(api.deny_claim(cid, ADJ))
    resp = api.approve_claim(cid, ADJ)
    validate_error(resp, "ERR_CLAIM_NOT_UNDER_REVIEW")


def test_activate_declined_occupation_class_policy_rejected(api):
    """PRD §3.2: "The referenced occupation class must not be a DECLINE class —
    activating a policy backed by a declined class is rejected with
    ERR_OCCUPATION_CLASS_DECLINED."

    Design: Corner/state_machines/activate_declined_occupation_class_policy_rejected
    """
    book = setup_pending_policy(occ_overrides={
        "code": "DEC", "risk_tier": "DECLINE", "own_occ_window_months_cap": 0,
    })
    resp = api.activate_policy(book["policy"]["id"], UW)
    validate_error(resp, "ERR_OCCUPATION_CLASS_DECLINED")


def test_terminate_policy_with_open_claim_rejected(api):
    """PRD §3.3: "no claim on the policy may be in UNDER_REVIEW or PENDING_INFO —
    an open claim mid-adjudication blocks termination with ERR_OPEN_CLAIM_EXISTS."

    Design: Corner/state_machines/terminate_policy_with_open_claim_rejected
    """
    book = setup_under_review_claim(clock_months=5)
    resp = api.terminate_policy(book["policy"]["id"], UW)
    validate_error(resp, "ERR_OPEN_CLAIM_EXISTS")


def test_terminate_policy_cascades_approved_claim_to_closed(api):
    """PRD §3.3: "On success the lifecycle becomes TERMINATED, the policy version
    increments, and a closing cascade sweeps every APPROVED or SUSPENDED claim on
    the policy to CLOSED, each such transition incrementing the affected claim's
    version."

    Design: Corner/state_machines/terminate_policy_cascades_approved_claim_to_closed
    """
    book = setup_approved_claim(clock_months=5)
    cid = book["claim"]["id"]
    terminated = validate_success(api.terminate_policy(book["policy"]["id"], UW), 200)
    assert terminated["lifecycle_status"] == "TERMINATED"
    claim_after = validate_success(api.get_claim(cid, ADJ), 200)
    assert claim_after["status"] == "CLOSED"


# ─── Corner / errors (state guards) ───────────────────

def test_reinstate_non_suspended_claim_rejected(api):
    """PRD §3.6: "Reinstating a SUSPENDED claim moves it back to APPROVED
    (requiring SUSPENDED, else ERR_CLAIM_NOT_SUSPENDED, and additionally requiring
    the policy lifecycle to be ACTIVE, else ERR_POLICY_NOT_ACTIVE)."

    Design: Corner/errors/reinstate_non_suspended_claim_rejected
    """
    book = setup_approved_claim(clock_months=5)
    resp = api.reinstate_claim(book["claim"]["id"], ADJ)
    validate_error(resp, "ERR_CLAIM_NOT_SUSPENDED")


def test_premium_pay_when_current_rejected(api):
    """PRD §3.3: "Paying the premium while in GRACE returns premium_status to
    CURRENT; this requires the status to be GRACE (otherwise
    ERR_PREMIUM_NOT_IN_GRACE) and increments version."

    Design: Corner/errors/premium_pay_when_current_rejected
    """
    book = setup_active_policy()
    resp = api.premium_pay(book["policy"]["id"], UW)
    validate_error(resp, "ERR_PREMIUM_NOT_IN_GRACE")


# ─── Corner / cross_cutting_complexity_layers (OCC) ───

def test_income_report_stale_claim_version_rejected(api):
    """PRD §2.7: "The server compares it to the claim's current version: if
    another recertification or status transition has advanced the claim's version
    since the client last read it, the values no longer match and the create is
    rejected with ERR_STALE_CLAIM_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_on_income_report
    """
    book = setup_active_policy(occ_overrides={"own_occ_window_months_cap": 0})
    ph_id = book["policyholder"]["id"]
    claim = file_claim(book["insurer"]["id"], book["policy"]["id"], ph_id,
                       claimed_disability_type="RESIDUAL")
    stale_version = claim["version"]
    ph = make_policyholder_headers(ph_id)
    # First report advances claim.version off of stale_version.
    get_success_data(api.create_income_report(
        claim["id"],
        create_income_report_payload(3, 500000, stale_version), ph,
    ))
    # Second report reuses the now-stale version.
    resp = api.create_income_report(
        claim["id"],
        create_income_report_payload(4, 400000, stale_version), ph,
    )
    validate_error(resp, "ERR_STALE_CLAIM_VERSION")


def test_income_report_fresh_version_supersedes_prior(api):
    """PRD §3.8: "Accepting a new report recertifies the basis: it supersedes any
    prior report on the same claim that has a strictly lesser effective_month by
    setting that prior report's is_superseded flag to true, leaving the newest
    report as the live basis."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_claim_version_income_report_supersedes
    """
    book = setup_active_policy(occ_overrides={"own_occ_window_months_cap": 0})
    ph_id = book["policyholder"]["id"]
    claim = file_claim(book["insurer"]["id"], book["policy"]["id"], ph_id,
                       claimed_disability_type="RESIDUAL")
    ph = make_policyholder_headers(ph_id)
    ir1 = get_success_data(api.create_income_report(
        claim["id"], create_income_report_payload(3, 500000, claim["version"]), ph,
    ))
    claim_after = validate_success(api.get_claim(claim["id"], ph), 200)
    ir2 = validate_success(api.create_income_report(
        claim["id"], create_income_report_payload(5, 400000, claim_after["version"]), ph,
    ), 201)
    assert ir2["effective_month"] == 5
    reports, _ = validate_paginated(api.list_income_reports(claim["id"], ADJ))
    prior = next(r for r in reports if r["id"] == ir1["id"])
    assert prior["is_superseded"] is True
