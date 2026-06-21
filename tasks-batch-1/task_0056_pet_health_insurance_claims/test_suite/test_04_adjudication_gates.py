"""Adjudication preconditions: waiting period, pre-existing exclusion, open
policy-year coverage, validation precedence, and boundary precision.

Difficulty queue: priority_pair_validation_conflict, boundary_precision_check
(waiting-period day boundary), resource_temporal_overlap.
Corner queue: validations (pre-existing alone, waiting-period alone), errors stubs
owned here.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, create_account, create_policy, activate_policy, create_condition,
    build_claim_in_review, get_year_zero_version,
    make_claims_adjuster_headers, make_underwriter_headers,
    ApiErrorId,
)


def _adj():
    return make_claims_adjuster_headers()


def _uw():
    return make_underwriter_headers()


def _setup_in_review(email, *, incident_date, condition_first_diagnosed,
                     waiting_period_days=14, claim_type="ILLNESS", clock="2026-06-01T00:00:00Z"):
    set_clock(clock)
    acct = create_account(email=email)
    pol = create_policy(acct["id"], annual_deductible_cents=25000, reimbursement_rate_bps=8000,
                        annual_cap_cents=500000, waiting_period_days=waiting_period_days,
                        effective_date="2026-01-01T00:00:00Z")
    activate_policy(acct["id"], pol["id"])
    cond = create_condition(acct["id"], pol["id"], name="c", first_diagnosed_date=condition_first_diagnosed)
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"],
                                  claim_overrides={"claim_type": claim_type, "incident_date": incident_date},
                                  billed_amount_cents=40000)
    return acct, pol, cond, claim


def _adjudicate_approve_resp(api, acct, pol, claim):
    version = get_year_zero_version(acct["id"], pol["id"])
    return api.adjudicate(claim["id"], {"decision": "APPROVE", "expected_policy_year_version": version}, _adj())


def test_waiting_period_beats_pre_existing_when_both_fail(api):
    """PRD 3.7: "These checks evaluate in priority order ... then the waiting-period
    check, then the pre-existing-exclusion check ... The relative ordering matters: a
    claim outside the waiting period surfaces ERR_WITHIN_WAITING_PERIOD before the
    pre-existing check would fire."

    Claim incident 2026-01-10 (inside waiting period, coverage start 2026-01-15) on a
    PRE_EXISTING condition (diagnosed 2026-01-05) -> ERR_WITHIN_WAITING_PERIOD wins.

    Design: Difficulty/priority_pair_validation_conflict/waiting_period_beats_pre_existing_temporal_vs_safety
    """
    acct, pol, _, claim = _setup_in_review(
        "pp1@x.com", incident_date="2026-01-10T00:00:00Z",
        condition_first_diagnosed="2026-01-05T00:00:00Z", waiting_period_days=14)

    resp = _adjudicate_approve_resp(api, acct, pol, claim)
    validate_error(resp, ApiErrorId.ERR_WITHIN_WAITING_PERIOD.value)

    unchanged = validate_success(api.get_claim(claim["id"], _adj()))
    assert unchanged["status"] == "IN_REVIEW", f"claim should stay IN_REVIEW, got {unchanged['status']}"


def test_waiting_period_winner_leaves_claim_unadjudicated(api):
    """PRD 3.7: "an incident inside the waiting period is rejected with
    ERR_WITHIN_WAITING_PERIOD."

    The temporal-vs-safety conflict that surfaces ERR_WITHIN_WAITING_PERIOD must not
    advance the claim out of IN_REVIEW (no DENIED/APPROVED side effect from a rejected
    adjudicate).

    Design: Difficulty/priority_pair_validation_conflict/waiting_period_beats_pre_existing_temporal_vs_safety
    """
    acct, pol, _, claim = _setup_in_review(
        "pp1b@x.com", incident_date="2026-01-10T00:00:00Z",
        condition_first_diagnosed="2026-01-05T00:00:00Z", waiting_period_days=14)

    resp = _adjudicate_approve_resp(api, acct, pol, claim)
    validate_error(resp, ApiErrorId.ERR_WITHIN_WAITING_PERIOD.value)
    after = validate_success(api.get_claim(claim["id"], _adj()))
    assert after["status"] == "IN_REVIEW"
    assert after["reimbursed_cents"] == 0


def test_not_found_for_missing_policy_in_nested_path(api):
    """PRD 2.5: "path identifiers are validated strictly left to right — account first,
    then policy, then claim, then invoice or line. The request is rejected with
    ERR_NOT_FOUND at the first path segment that does not resolve to an existing
    resource, before any deeper segment or any business rule is evaluated."

    Activating a non-existent policy under a real account returns ERR_NOT_FOUND rather
    than any state-machine error.

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_existence_vs_state
    """
    acct = create_account(email="pp2b@x.com")
    resp = api.activate_policy(acct["id"], "00000000-0000-4000-8000-000000000000", {}, _uw())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_not_found_beats_invalid_state_for_missing_claim(api):
    """PRD 2.5: "The request is rejected with ERR_NOT_FOUND at the first path segment
    that does not resolve to an existing resource, before any deeper segment or any
    business rule is evaluated."

    Submitting a non-existent claim id returns ERR_NOT_FOUND, never an ERR_INVALID_STATE
    about its (absent) status.

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_existence_vs_state
    """
    from test_helpers import make_policy_holder_headers
    acct = create_account(email="pp2@x.com")
    resp = api.submit_claim("00000000-0000-4000-8000-000000000000", make_policy_holder_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_waiting_period_exact_day_boundary_is_payable(api):
    """PRD 3.7: "For a non-wellness claim, the incident_date must be on or after the
    policy's effective_date advanced by waiting_period_days days; an incident inside the
    waiting period is rejected with ERR_WITHIN_WAITING_PERIOD."

    Incident exactly at coverage start (2026-01-15, effective 2026-01-01 + 14d) is on or
    after the threshold and approves: eligible 40000, deductible 25000 -> reimbursed 12000.

    Design: Difficulty/boundary_precision_check/waiting_period_exact_day_boundary_on_adjudicate
    """
    acct, pol, _, claim = _setup_in_review(
        "bp1@x.com", incident_date="2026-01-15T00:00:00Z",
        condition_first_diagnosed="2026-01-20T00:00:00Z", waiting_period_days=14)

    approved = validate_success(_adjudicate_approve_resp(api, acct, pol, claim))
    assert approved["status"] == "APPROVED"
    assert approved["deductible_applied_cents"] == 25000, f"deductible: {approved['deductible_applied_cents']}"
    assert approved["reimbursed_cents"] == 12000, f"reimbursed: {approved['reimbursed_cents']}"


def test_waiting_period_one_day_before_boundary_rejected(api):
    """PRD 3.7: "the incident_date must be on or after the policy's effective_date
    advanced by waiting_period_days days; an incident inside the waiting period is
    rejected with ERR_WITHIN_WAITING_PERIOD."

    The day below the exact boundary (2026-01-14, coverage start 2026-01-15) is rejected,
    confirming the X-1 side of the threshold.

    Design: Difficulty/boundary_precision_check/waiting_period_exact_day_boundary_on_adjudicate
    """
    acct, pol, _, claim = _setup_in_review(
        "bp1b@x.com", incident_date="2026-01-14T00:00:00Z",
        condition_first_diagnosed="2026-01-20T00:00:00Z", waiting_period_days=14)

    resp = _adjudicate_approve_resp(api, acct, pol, claim)
    validate_error(resp, ApiErrorId.ERR_WITHIN_WAITING_PERIOD.value)


def test_incident_before_year_leaves_claim_in_review(api):
    """PRD 3.7: "a PolicyYear whose half-open window from period_start (inclusive) to
    period_end (exclusive) contains the incident_date must exist and be OPEN; if no such
    open year is found the approval is rejected with ERR_POLICY_YEAR_CLOSED."

    The rejected out-of-window adjudicate does not advance the claim past IN_REVIEW.

    Incident 2027-01-01 falls past PolicyYear 0 = [2026-01-01, 2027-01-01) (period_end
    exclusive); waiting period (0) is satisfied and the condition is COVERED, so the
    open-policy-year check is the one that fires.

    Design: Difficulty/resource_temporal_overlap/incident_date_outside_any_open_policy_year
    """
    acct, pol, _, claim = _setup_in_review(
        "rt1b@x.com", incident_date="2027-01-01T00:00:00Z",
        condition_first_diagnosed="2026-01-01T00:00:00Z", waiting_period_days=0)

    resp = _adjudicate_approve_resp(api, acct, pol, claim)
    validate_error(resp, ApiErrorId.ERR_POLICY_YEAR_CLOSED.value)
    after = validate_success(api.get_claim(claim["id"], _adj()))
    assert after["status"] == "IN_REVIEW"


def test_clock_advance_closes_year_then_blocks_approval(api):
    """PRD 3.2: "any policy year whose period_end is at or before the new clock instant
    transitions to CLOSED."
    PRD 2.8: "claims may only be approved into an OPEN year."

    Advancing the clock past period_end flips PolicyYear 0 to CLOSED; the subsequent
    adjudicate of an in-window incident is rejected ERR_POLICY_YEAR_CLOSED.

    Design: Difficulty/resource_temporal_overlap/incident_date_in_closed_year_after_clock_advance
    """
    acct, pol, _, claim = _setup_in_review(
        "rt2b@x.com", incident_date="2026-06-01T00:00:00Z",
        condition_first_diagnosed="2026-02-01T00:00:00Z", waiting_period_days=0,
        clock="2026-06-15T00:00:00Z")
    version = get_year_zero_version(acct["id"], pol["id"])
    set_clock("2027-02-01T00:00:00Z")

    years, _ = validate_paginated(api.list_policy_years(acct["id"], pol["id"], _adj()))
    assert years[0]["status"] == "CLOSED", f"year should be CLOSED after clock advance, got {years[0]['status']}"

    resp = api.adjudicate(claim["id"], {"decision": "APPROVE", "expected_policy_year_version": version}, _adj())
    validate_error(resp, ApiErrorId.ERR_POLICY_YEAR_CLOSED.value)


def test_waiting_period_alone_blocks_approval(api):
    """PRD 3.7: "For a non-wellness claim, the incident_date must be on or after the
    policy's effective_date advanced by waiting_period_days days; an incident inside the
    waiting period is rejected with ERR_WITHIN_WAITING_PERIOD."

    Incident 2026-01-14 (one day before coverage start 2026-01-15) on a COVERED condition
    is rejected ERR_WITHIN_WAITING_PERIOD.

    Design: Corner/validations/waiting_period_alone_blocks_approval
    """
    acct, pol, _, claim = _setup_in_review(
        "v22@x.com", incident_date="2026-01-14T00:00:00Z",
        condition_first_diagnosed="2026-01-20T00:00:00Z", waiting_period_days=14)

    resp = _adjudicate_approve_resp(api, acct, pol, claim)
    validate_error(resp, ApiErrorId.ERR_WITHIN_WAITING_PERIOD.value)


def test_pre_existing_condition_alone_blocks_approval(api):
    """PRD 3.7: "For a non-wellness claim, the referenced MedicalCondition must have
    exclusion_status of COVERED; a PRE_EXISTING condition is rejected with
    ERR_PRE_EXISTING_EXCLUDED."

    Incident 2026-03-01 (past waiting period) but the condition was diagnosed 2026-01-05
    (PRE_EXISTING) -> ERR_PRE_EXISTING_EXCLUDED.

    Design: Corner/validations/pre_existing_condition_alone_blocks_approval
    """
    acct, pol, _, claim = _setup_in_review(
        "v21@x.com", incident_date="2026-03-01T00:00:00Z",
        condition_first_diagnosed="2026-01-05T00:00:00Z", waiting_period_days=14)

    resp = _adjudicate_approve_resp(api, acct, pol, claim)
    validate_error(resp, ApiErrorId.ERR_PRE_EXISTING_EXCLUDED.value)


def test_incident_before_any_policy_year_rejected_closed(api):
    """PRD 3.7: "a PolicyYear whose half-open window from period_start (inclusive) to
    period_end (exclusive) contains the incident_date must exist and be OPEN; if no such
    open year is found the approval is rejected with ERR_POLICY_YEAR_CLOSED."

    Incident 2027-01-01 falls past PolicyYear 0 = [2026-01-01, 2027-01-01) (period_end is
    exclusive); no covering open year -> ERR_POLICY_YEAR_CLOSED. Waiting period (0) is
    satisfied and the condition is COVERED, so neither higher-priority check pre-empts.

    Design: Difficulty/resource_temporal_overlap/incident_date_outside_any_open_policy_year
    """
    acct, pol, _, claim = _setup_in_review(
        "rt1@x.com", incident_date="2027-01-01T00:00:00Z",
        condition_first_diagnosed="2026-01-01T00:00:00Z", waiting_period_days=0)

    resp = _adjudicate_approve_resp(api, acct, pol, claim)
    validate_error(resp, ApiErrorId.ERR_POLICY_YEAR_CLOSED.value)


def test_incident_in_year_closed_by_clock_advance_rejected(api):
    """PRD 2.8: "A coverage year is OPEN while its accumulators may still change and
    CLOSED once the logical clock has advanced to or past its end; claims may only be
    approved into an OPEN year."
    PRD 3.7: "if no such open year is found the approval is rejected with
    ERR_POLICY_YEAR_CLOSED."

    Incident 2026-06-01 sits inside PolicyYear 0, but advancing the clock to 2027-02-01
    closes the year, so adjudication is rejected ERR_POLICY_YEAR_CLOSED.

    Design: Difficulty/resource_temporal_overlap/incident_date_in_closed_year_after_clock_advance
    """
    acct, pol, _, claim = _setup_in_review(
        "rt2@x.com", incident_date="2026-06-01T00:00:00Z",
        condition_first_diagnosed="2026-02-01T00:00:00Z", waiting_period_days=0,
        clock="2026-06-15T00:00:00Z")
    version = get_year_zero_version(acct["id"], pol["id"])
    set_clock("2027-02-01T00:00:00Z")

    resp = api.adjudicate(claim["id"], {"decision": "APPROVE", "expected_policy_year_version": version}, _adj())
    validate_error(resp, ApiErrorId.ERR_POLICY_YEAR_CLOSED.value)
