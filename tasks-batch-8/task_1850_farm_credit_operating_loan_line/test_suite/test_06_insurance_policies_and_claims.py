"""Crop insurance: half-open coverage windows, policy-number uniqueness,
assignment gates, claim creation gates, and the adjust-appeal loop (PRD 3.5).
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, add_assigned_policy,
    adjuster_report_payload, create_approved_loan, create_association,
    create_borrower, create_claim_payload, create_loan_payload,
    create_policy_payload, get_success_data, setup_active_loan,
    setup_active_loan_with_reported_claim, validate_error, validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["loan_officer_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


def _policy(api, borrower_id, **overrides):
    return api.create_insurance_policy(
        create_policy_payload(borrower_id=borrower_id, **overrides), OFFICER)


# ---------------------------------------------------------------------------
# Half-open coverage windows
# ---------------------------------------------------------------------------

def test_policy_windows_adjacency_allowed_overlap_rejected(api):
    """PRD section 3.5: "Coverage windows for the same borrower, crop type, and
    county must not overlap; adjacency — one window's `coverage_start` landing
    exactly on another's `coverage_end` — is allowed, and an overlapping
    submission is rejected with `ERR_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_windows_half_open_adjacency_allowed_overlap_rejected
    """
    assoc = create_association()
    bor = create_borrower(assoc["id"])
    p1 = validate_success(_policy(api, bor["id"]), 201)

    adjacent = _policy(api, bor["id"], policy_number="POL-ADJ",
                       coverage_start="2027-03-01T00:00:00Z",
                       coverage_end="2028-03-01T00:00:00Z",
                       coverage_amount_cents=30_000_000)
    data = validate_success(adjacent, 201)
    assert data["id"] and data["status"] == "ACTIVE", \
        "coverage_start landing exactly on coverage_end touches without overlapping"

    overlapping = _policy(api, bor["id"], policy_number="POL-OVR",
                          coverage_start="2026-06-01T00:00:00Z",
                          coverage_end="2027-06-01T00:00:00Z",
                          coverage_amount_cents=30_000_000)
    validate_error(overlapping, ApiErrorId.ERR_COVERAGE_OVERLAP)


def test_policy_windows_distinct_crop_or_county_do_not_overlap(api):
    """PRD section 3.5: "Coverage windows for the same borrower, crop type, and
    county must not overlap; adjacency — one window's `coverage_start` landing
    exactly on another's `coverage_end` — is allowed, and an overlapping
    submission is rejected with `ERR_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_windows_half_open_adjacency_allowed_overlap_rejected
    """
    assoc = create_association()
    bor = create_borrower(assoc["id"])
    validate_success(_policy(api, bor["id"]), 201)  # CORN / BLACKHAWK

    other_crop = _policy(api, bor["id"], policy_number="POL-SOY",
                         crop_type="SOYBEAN")  # identical window, other crop
    assert validate_success(other_crop, 201)["status"] == "ACTIVE", \
        "a different crop_type is a different coverage key"

    other_county = _policy(api, bor["id"], policy_number="POL-PRA",
                           county="PRAIRIE")  # identical window, other county
    assert validate_success(other_county, 201)["status"] == "ACTIVE", \
        "a different county is a different coverage key"


# ---------------------------------------------------------------------------
# Claim creation gates
# ---------------------------------------------------------------------------

def test_claim_create_requires_policy_assigned_to_that_loan(api):
    """PRD section 3.5: "The claim's `loan_account_id` must equal the policy's
    `assigned_loan_id` and the policy must stand `ASSIGNED`, else the report is
    rejected with `ERR_POLICY_NOT_ASSIGNED_TO_LOAN`".

    Design: Difficulty/cross_entity_state_dependency/claim_create_requires_policy_assigned_to_that_loan
    """
    ctx = setup_active_loan_with_reported_claim()  # POL-001 ASSIGNED, one claim REPORTED
    pol2 = validate_success(_policy(api, ctx["bor"]["id"], policy_number="POL-002",
                                    crop_type="SOYBEAN", coverage_amount_cents=20_000_000),
                            201)
    assert pol2["assignment_status"] == "UNASSIGNED"

    resp = api.create_insurance_claim(
        create_claim_payload(policy_id=pol2["id"], loan_account_id=ctx["loan"]["id"],
                             claimed_loss_cents=500_000), OFFICER)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ASSIGNED_TO_LOAN)

    get_success_data(api.assign_insurance_policy(
        pol2["id"], {"loan_account_id": ctx["loan"]["id"]}, OFFICER))
    data = validate_success(api.create_insurance_claim(
        create_claim_payload(policy_id=pol2["id"], loan_account_id=ctx["loan"]["id"],
                             claimed_loss_cents=500_000), OFFICER), 201)
    assert data["status"] == "REPORTED"


def test_claim_naming_a_different_loan_rejected(api):
    """PRD section 3.5: "The claim's `loan_account_id` must equal the policy's
    `assigned_loan_id` and the policy must stand `ASSIGNED`, else the report is
    rejected with `ERR_POLICY_NOT_ASSIGNED_TO_LOAN`".

    Design: Difficulty/cross_entity_state_dependency/claim_create_requires_policy_assigned_to_that_loan
    """
    ctx = create_approved_loan()
    pol = add_assigned_policy(ctx)  # ASSIGNED to the first loan
    other_loan = validate_success(api.create_loan(
        create_loan_payload(borrower_id=ctx["bor"]["id"]), OFFICER), 201)

    resp = api.create_insurance_claim(
        create_claim_payload(policy_id=pol["id"], loan_account_id=other_loan["id"],
                             claimed_loss_cents=500_000), OFFICER)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ASSIGNED_TO_LOAN)
    claims, meta = validate_paginated(
        api.list_insurance_claims(OFFICER, {"loan_account_id": other_loan["id"]}))
    assert meta["total_count"] == 0, "the rejected report created no claim row"

    data = validate_success(api.create_insurance_claim(
        create_claim_payload(policy_id=pol["id"], loan_account_id=ctx["loan"]["id"],
                             claimed_loss_cents=500_000), OFFICER), 201)
    assert data["status"] == "REPORTED", "naming the assigned loan reports cleanly"


# ---------------------------------------------------------------------------
# The adjust-appeal loop
# ---------------------------------------------------------------------------

def test_insurance_claim_appeal_cycle_overwrites_amount(api):
    """PRD section 3.5: "The adjuster's report sets the indemnity amount: from
    `REPORTED` → `ADJUSTED`, and again from `UNDER_APPEAL` → `ADJUSTED` when an
    appeal sends it back, in which case the new figure overwrites the old." PRD
    section 3.5: "The borrower or an officer who disputes an approved amount
    appeals it, moving `APPROVED` → `UNDER_APPEAL` and reopening the adjuster's
    report."

    Design: Difficulty/non_linear_state_machine/insurance_claim_appeal_cycle
    """
    ctx = setup_active_loan_with_reported_claim(claimed_loss_cents=3_000_000)
    clm = ctx["clm"]["id"]

    s1 = validate_success(api.adjuster_report_claim(
        clm, adjuster_report_payload(adjuster_approved_cents=2_000_000), ADJUSTER), 200)
    assert s1["status"] == "ADJUSTED"
    s2 = validate_success(api.approve_claim(clm, ADJUSTER), 200)
    assert s2["status"] == "APPROVED"
    s3 = validate_success(api.appeal_claim(clm, OFFICER), 200)
    assert s3["status"] == "UNDER_APPEAL"
    s4 = validate_success(api.adjuster_report_claim(
        clm, adjuster_report_payload(adjuster_approved_cents=2_500_000), ADJUSTER), 200)
    assert s4["status"] == "ADJUSTED"
    assert s4["adjuster_approved_cents"] == 2_500_000, \
        "the second report overwrites 2,000,000 rather than accumulating"
    s5 = validate_success(api.approve_claim(clm, ADJUSTER), 200)
    assert s5["status"] == "APPROVED"


def test_claim_deny_from_under_appeal_is_terminal(api):
    """PRD section 3.5: "The adjuster approves an `ADJUSTED` claim to `APPROVED`,
    or denies a claim from any of `REPORTED`, `ADJUSTED`, or `UNDER_APPEAL` to
    `DENIED` (terminal)." PRD section 2.7: "7. **Generic state preconditions.** The
    requested transition is listed for the entity's current state, and terminal
    states accept no transitions — `ERR_INVALID_STATE_TRANSITION`."

    Design: Difficulty/non_linear_state_machine/insurance_claim_appeal_cycle
    """
    ctx = setup_active_loan_with_reported_claim(claimed_loss_cents=3_000_000)
    clm = ctx["clm"]["id"]
    get_success_data(api.adjuster_report_claim(
        clm, adjuster_report_payload(adjuster_approved_cents=2_000_000), ADJUSTER))
    get_success_data(api.approve_claim(clm, ADJUSTER))
    get_success_data(api.appeal_claim(clm, OFFICER))
    data = validate_success(api.deny_claim(clm, ADJUSTER), 200)
    assert data["status"] == "DENIED"

    resp = api.pay_claim(clm, OFFICER)  # pay is listed only from APPROVED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


# ---------------------------------------------------------------------------
# Policy uniqueness and assignment gates; coverage ceiling on reports
# ---------------------------------------------------------------------------

def test_policy_number_taken_rejected(api):
    """PRD section 3.5: "A policy enters the books when a `Borrower` or a
    `LoanOfficer` records it with the owning `borrower_id`, a `policy_number`
    unique per borrower — duplicates are rejected with `ERR_POLICY_NUMBER_TAKEN`".

    Design: Corner/validations/policy_number_taken_rejected
    """
    assoc = create_association()
    bor = create_borrower(assoc["id"])
    validate_success(_policy(api, bor["id"]), 201)  # POL-001 CORN BLACKHAWK
    resp = _policy(api, bor["id"], policy_number="POL-001", crop_type="SOYBEAN",
                   coverage_start="2027-03-01T00:00:00Z",
                   coverage_end="2028-03-01T00:00:00Z",
                   coverage_amount_cents=10_000_000)
    validate_error(resp, ApiErrorId.ERR_POLICY_NUMBER_TAKEN)


def test_policy_assign_cancelled_policy_rejected(api):
    """PRD section 3.5: "A `LoanOfficer` assigns a policy by naming the
    `loan_account_id`, and four checks guard the act: the policy must be `ACTIVE`,
    else `ERR_POLICY_NOT_ACTIVE`".

    Design: Corner/validations/policy_assign_cancelled_policy_rejected
    """
    ctx = create_approved_loan()
    pol = validate_success(_policy(api, ctx["bor"]["id"]), 201)
    get_success_data(api.cancel_insurance_policy(pol["id"], OFFICER))
    resp = api.assign_insurance_policy(
        pol["id"], {"loan_account_id": ctx["loan"]["id"]}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
    assert validate_success(api.get_insurance_policy(pol["id"], OFFICER), 200)[
        "assignment_status"] == "UNASSIGNED"


def test_policy_reassign_already_assigned_rejected(api):
    """PRD section 3.5: "it must not already be `ASSIGNED`, else
    `ERR_POLICY_ALREADY_ASSIGNED`".

    Design: Corner/validations/policy_reassign_already_assigned_rejected
    """
    ctx = create_approved_loan()
    pol = validate_success(_policy(api, ctx["bor"]["id"]), 201)
    get_success_data(api.assign_insurance_policy(
        pol["id"], {"loan_account_id": ctx["loan"]["id"]}, OFFICER))
    resp = api.assign_insurance_policy(
        pol["id"], {"loan_account_id": ctx["loan"]["id"]}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_POLICY_ALREADY_ASSIGNED)


def test_claim_adjuster_report_over_coverage_rejected(api):
    """PRD section 3.5: "Either way, `adjuster_approved_cents` may not exceed the
    policy's remaining coverage — the `coverage_amount_cents` less the sum of
    `indemnity_to_lender_cents` over this policy's claims already in `PAID` status
    — and an excessive report is rejected with `ERR_CLAIM_EXCEEDS_COVERAGE`."

    Design: Corner/validations/claim_adjuster_report_over_coverage_rejected
    """
    ctx = setup_active_loan_with_reported_claim(claimed_loss_cents=45_000_000)
    clm = ctx["clm"]["id"]  # policy coverage_amount_cents 40,000,000; nothing paid yet
    resp = api.adjuster_report_claim(
        clm, adjuster_report_payload(adjuster_approved_cents=40_000_001), ADJUSTER)
    validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_COVERAGE)
    data = validate_success(api.adjuster_report_claim(
        clm, adjuster_report_payload(adjuster_approved_cents=40_000_000), ADJUSTER), 200)
    assert data["status"] == "ADJUSTED", "exactly the remaining coverage passes (<=)"


def test_cross_association_policy_assign_returns_422(api):
    """PRD section 3.5: "the loan and the policy must belong to the same
    association, else `ERR_CROSS_ASSOCIATION_REFERENCE`".

    Design: Corner/validations/cross_association_policy_assign_returns_422
    """
    assoc_a = create_association("Blackhawk FCS", "CH-1850")
    assoc_b = create_association("Prairie FCS", "CH-1851")
    bor_a = create_borrower(assoc_a["id"])
    bor_b = create_borrower(assoc_b["id"], legal_name="Other Farms LLC",
                            tax_id="41-0000002", county="PRAIRIE")
    loan_b = validate_success(api.create_loan(
        create_loan_payload(borrower_id=bor_b["id"]), OFFICER), 201)
    pol_a = validate_success(_policy(api, bor_a["id"]), 201)

    resp = api.assign_insurance_policy(
        pol_a["id"], {"loan_account_id": loan_b["id"]}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_CROSS_ASSOCIATION_REFERENCE)
    assert validate_success(api.get_insurance_policy(pol_a["id"], OFFICER), 200)[
        "assignment_status"] == "UNASSIGNED"
