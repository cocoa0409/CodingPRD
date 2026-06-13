"""Accrual gating (proof currency, residual report requirement), temporal-overlap
semantics (closed offset windows vs half-open coverage months), offset finalize
state guard, and benefit-period void idempotency + ledger restoration.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_benefit_period,
    create_claim_payload, create_disability_proof_payload,
    TEST_USERS, make_policyholder_headers,
    setup_active_policy, setup_approved_claim,
    setup_approved_total_with_periods,
    setup_total_claim_with_period_and_estimated_offset,
    file_claim, add_offset_award, accrue_benefit_period,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]


# ─── Difficulty / resource_temporal_overlap ───────────

def test_offset_window_closed_interval_touching_collides(api):
    """PRD §3.11: "the new window may not overlap any existing non-VOID offset
    award of the same offset_source on the claim, and because the interval is
    closed and carries a one-month no-touch buffer, two windows that merely touch
    (the end of one equal to the start of the other) collide and are rejected with
    ERR_OFFSET_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/offset_window_closed_interval_touching_collides
    """
    book = setup_approved_total_with_periods([], clock_months=5)
    cid = book["claim"]["id"]
    add_offset_award(cid, "SSDI", 120000, 3, 5)
    resp = api.create_offset_award(
        cid, {"offset_source": "SSDI", "monthly_offset_cents": 90000,
              "start_month": 5, "end_month": 7}, ADJ,
    )  # [5,7] touches existing [3,5] at month 5
    validate_error(resp, "ERR_OFFSET_WINDOW_OVERLAP")


def test_benefit_period_half_open_consecutive_months_allowed(api):
    """PRD §3.9: "each benefit period covers a half-open one-month interval running
    from its coverage month up to but not including the following month, so
    consecutive months touch but never overlap."
    PRD §3.9: "No other ACCRUED benefit period on the claim may already cover this
    coverage month; a duplicate is rejected with ERR_COVERAGE_MONTH_OCCUPIED."

    Design: Difficulty/resource_temporal_overlap/benefit_period_half_open_consecutive_months_allowed
    """
    book = setup_approved_total_with_periods([3], clock_months=6)
    cid = book["claim"]["id"]
    bp4 = validate_success(api.create_benefit_period(cid, {"coverage_month": 4}, ADJ), 201)
    assert bp4["coverage_month"] == 4
    assert bp4["status"] == "ACCRUED"
    dup = api.create_benefit_period(cid, {"coverage_month": 3}, ADJ)
    validate_error(dup, "ERR_COVERAGE_MONTH_OCCUPIED")


# ─── Corner / validations ─────────────────────────────

def test_submit_residual_without_income_report_rejected(api):
    """PRD §3.5: "if the claim's type is RESIDUAL there must be at least one income
    report on it (otherwise ERR_RESIDUAL_INCOME_REPORT_REQUIRED, a 422)."

    Design: Corner/validations/submit_residual_without_income_report_rejected
    """
    book = setup_active_policy(occ_overrides={"own_occ_window_months_cap": 0})
    claim = file_claim(book["insurer"]["id"], book["policy"]["id"],
                       book["policyholder"]["id"], claimed_disability_type="RESIDUAL")
    resp = api.submit_claim(claim["id"], make_policyholder_headers(book["policyholder"]["id"]))
    validate_error(resp, "ERR_RESIDUAL_INCOME_REPORT_REQUIRED")


def test_accrual_coverage_month_before_elimination_rejected(api):
    """PRD §3.9: "it must be at least the claim's elimination_satisfied_month and no
    greater than the claim's next_proof_due_month ... a coverage month before
    elimination satisfaction or beyond the proof-due horizon is rejected with
    ERR_PROOF_NOT_CURRENT (a 422)."

    Design: Corner/validations/accrual_coverage_month_before_elimination_rejected
    """
    book = setup_approved_total_with_periods([], clock_months=5)
    resp = api.create_benefit_period(book["claim"]["id"], {"coverage_month": 2}, ADJ)
    validate_error(resp, "ERR_PROOF_NOT_CURRENT")  # 2 < elim_sat 3


def test_accrual_beyond_proof_due_without_new_proof_rejected(api):
    """PRD §3.9: "a coverage month before elimination satisfaction or beyond the
    proof-due horizon is rejected with ERR_PROOF_NOT_CURRENT (a 422)."

    Design: Corner/validations/accrual_beyond_proof_due_without_new_proof_rejected
    """
    book = setup_approved_total_with_periods([], clock_months=8)
    # next_proof_due_month = elim_sat 3 + PROOF_INTERVAL 3 = 6 ; coverage 7 > 6.
    resp = api.create_benefit_period(book["claim"]["id"], {"coverage_month": 7}, ADJ)
    validate_error(resp, "ERR_PROOF_NOT_CURRENT")


def test_disability_proof_acceptance_advances_proof_due_month(api):
    """PRD §3.6: "a proof is accepted when still_disabled is true and its
    attestation_month is no greater than the claim's next_proof_due_month at the
    moment of submission. When a proof is accepted, the claim's next_proof_due_month
    advances by the three-month proof interval and the claim version increments."

    Design: Corner/validations/disability_proof_acceptance_advances_proof_due_month
    """
    book = setup_approved_total_with_periods([], clock_months=8)
    cid = book["claim"]["id"]
    proof = validate_success(api.create_disability_proof(
        cid, create_disability_proof_payload(6, True),
        make_policyholder_headers(book["policyholder"]["id"]),
    ), 201)
    assert proof["accepted"] is True  # attestation 6 <= prior due 6
    # next_proof_due advanced 6 -> 9, so coverage_month 7 now accrues.
    bp = validate_success(api.create_benefit_period(cid, {"coverage_month": 7}, ADJ), 201)
    assert bp["status"] == "ACCRUED"


# ─── Corner / errors ──────────────────────────────────

def test_finalize_already_finalized_offset_rejected(api):
    """PRD §3.11: "Finalizing an offset award reconciles the estimate against the
    actual third-party determination. It requires the award to be ESTIMATED
    (otherwise ERR_OFFSET_NOT_ESTIMATED) and the parent claim to be APPROVED
    (otherwise ERR_CLAIM_NOT_APPROVED)."

    Design: Corner/errors/finalize_already_finalized_offset_rejected
    """
    book = setup_total_claim_with_period_and_estimated_offset(
        offset_source="SSDI", monthly_offset_cents=120000, offset_window=(3, 5),
        coverage_month=3, clock_months=5,
    )
    oa_id = book["offset_award"]["id"]
    get_success_data(api.finalize_offset_award(oa_id, {}, ADJ))
    resp = api.finalize_offset_award(oa_id, {}, ADJ)
    validate_error(resp, "ERR_OFFSET_NOT_ESTIMATED")


# ─── Corner / state_machines (benefit-period void) ────

def test_void_benefit_period_already_reversed_rejected(api):
    """PRD §3.12: "the period must be ACCRUED (otherwise
    ERR_BENEFIT_PERIOD_NOT_ACCRUED) and the parent claim must be in either APPROVED
    or SUSPENDED status (otherwise ERR_CLAIM_NOT_PAYABLE)."

    Design: Corner/state_machines/void_benefit_period_already_reversed_returns_invalid_state
    """
    book = setup_approved_total_with_periods([3], clock_months=5)
    bp_id = book["benefit_periods"][0]["id"]
    get_success_data(api.void_benefit_period(bp_id, ADJ))
    resp = api.void_benefit_period(bp_id, ADJ)
    validate_error(resp, "ERR_BENEFIT_PERIOD_NOT_ACCRUED")


def test_void_benefit_period_restores_consumed_and_ledger(api):
    """PRD §3.12: "Voiding increments the benefit period version, recomputes the
    claim ledger totals, and decreases the policy's benefit_months_consumed by that
    period's benefit_fraction, again preserving the conservation invariant that
    consumed months equal the sum over active periods."
    PRD §3.12: "Its total_gross_paid_cents is the sum of gross_benefit_cents over
    the claim's ACCRUED benefit periods".

    Design: Corner/state_machines/void_benefit_period_restores_consumed_and_ledger
    """
    book = setup_approved_total_with_periods([3, 4], clock_months=6)
    cid = book["claim"]["id"]
    pid = book["policy"]["id"]
    bp3_id = book["benefit_periods"][0]["id"]
    get_success_data(api.void_benefit_period(bp3_id, ADJ))
    policy_after = validate_success(api.get_policy(pid, UW), 200)
    assert policy_after["benefit_months_consumed"] == 1.0
    ledger, _ = validate_paginated(api.get_claim_ledger(cid, ADJ))
    assert ledger[0]["total_gross_paid_cents"] == 500000  # only month-4 remains ACCRUED
