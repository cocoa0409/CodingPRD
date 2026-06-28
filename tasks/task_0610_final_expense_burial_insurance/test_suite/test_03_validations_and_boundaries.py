"""Validation rejections, numeric boundaries, temporal overlaps, priority pairs,
cross-entity state dependencies, and compensating invariants.

Translates the priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap and
compensating_invariant difficulty rules (queue A) plus the validations corner
section (queue B).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    issue_active_policy,
    issue_active_policy_only,
    issue_vested_policy,
    create_plan,
    create_applicant,
    create_draft_application_with_questionnaire,
    set_clock,
    submit_application,
    issue_policy,
    post_premium,
    claim_under_review,
    disburse_loan,
)
from test_helpers.api_client import api_client

PA = TEST_USERS["policy_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]


# ===========================================================================
# Difficulty / priority_pair_validation_conflict / claim_on_terminated_policy_state_beats_temporal
# ===========================================================================
def test_claim_on_terminated_policy_surfaces_state_not_temporal(api):
    """PRD §3.11: "These two checks are ordered - the in-force coverage check is
    evaluated before the death-before-issue check - so a claim against a
    terminated policy surfaces ERR_POLICY_NOT_IN_FORCE rather than a date error."

    Design: Difficulty/priority_pair_validation_conflict/claim_on_terminated_policy_state_beats_temporal
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_jonah")
    set_clock("2026-06-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2026-06-01T00:00:00Z", manner_of_death="ACCIDENTAL", certified_cause="ACCIDENT", certificate_number="DC-5")
    validate_success(api.approve_claim(reviewed["id"], CE))  # policy now TERMINATED

    # Second claim: date_of_death before issue AND policy not in force.
    resp = api.create_claim({"policy_id": policy["id"], "date_of_death": "2026-01-01T00:00:00Z", "manner_of_death": "NATURAL"}, CE)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_IN_FORCE.value)


def test_claim_on_active_policy_before_issue_surfaces_temporal(api):
    """PRD §3.11: "The date of death may not predate coverage: a date_of_death
    earlier than the policy's issue_date is rejected with ERR_DEATH_BEFORE_ISSUE."

    Design: Difficulty/priority_pair_validation_conflict/claim_on_terminated_policy_state_beats_temporal
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_jonah2")
    set_clock("2026-06-01T00:00:00Z")
    # Policy is ACTIVE (in force), so only the date check should fire.
    resp = api.create_claim({"policy_id": policy["id"], "date_of_death": "2026-01-01T00:00:00Z", "manner_of_death": "NATURAL"}, CE)
    validate_error(resp, ApiErrorId.ERR_DEATH_BEFORE_ISSUE.value)


# ===========================================================================
# Difficulty / priority_pair_validation_conflict / beneficiary_terminal_policy_referential_beats_constraint
# ===========================================================================
def test_beneficiary_on_terminal_policy_surfaces_referential_not_shares(api):
    """PRD §3.8: "both permitted only while the policy's coverage is ACTIVE or
    LAPSED - a write against a terminal-coverage policy is rejected with
    ERR_POLICY_NOT_DESIGNABLE."

    Design: Difficulty/priority_pair_validation_conflict/beneficiary_terminal_policy_referential_beats_constraint
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_kara")
    api.create_beneficiary(policy["id"], {"full_name": "Primary Heir", "relationship": "CHILD", "share_pct": 70}, PA)
    set_clock("2031-02-01T00:00:00Z")
    validate_success(api.surrender_policy(policy["id"], PA))  # now SURRENDERED (terminal)

    # 70 + 50 = 120 > 100 AND policy terminal: referential error must win.
    resp = api.create_beneficiary(policy["id"], {"full_name": "Late Heir", "relationship": "CHILD", "share_pct": 50}, PA)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_DESIGNABLE.value)


def test_beneficiary_on_active_policy_over_100_surfaces_shares(api):
    """PRD §3.8: "after each write, the sum of share_pct across the policy's
    ACTIVE beneficiaries must not exceed 100, and a write that would push the
    running total above 100 is rejected with ERR_SHARES_EXCEED_100."

    Design: Difficulty/priority_pair_validation_conflict/beneficiary_terminal_policy_referential_beats_constraint
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_kara2")
    api.create_beneficiary(policy["id"], {"full_name": "Primary Heir", "relationship": "CHILD", "share_pct": 70}, PA)
    # Policy still ACTIVE: only the shares check can fire.
    resp = api.create_beneficiary(policy["id"], {"full_name": "Late Heir", "relationship": "CHILD", "share_pct": 50}, PA)
    validate_error(resp, ApiErrorId.ERR_SHARES_EXCEED_100.value)


# ===========================================================================
# Difficulty / boundary_precision_check / max_issue_age_boundary_85_vs_86
# ===========================================================================
def test_attained_age_above_max_issue_age_declined(api):
    """PRD §3.3: "If knockout_triggered is true, or the attained age is below the
    plan's min_issue_age or above its max_issue_age ... the application advances
    automatically from SUBMITTED to DECLINED."
    PRD §3.3: "if there is no knockout but the age is out of band, the reason is
    AGE_OUT_OF_BAND"

    Design: Difficulty/boundary_precision_check/max_issue_age_boundary_85_vs_86
    """
    plan = create_plan(simple=False)
    set_clock("2026-02-01T00:00:00Z")
    # DOB 1939-06-15 -> attained age 86 on 2026-02-01 (> max_issue_age 85).
    applicant = create_applicant(full_name="Eld Roan", date_of_birth="1939-06-15", gender="MALE")
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1000000)
    submitted = validate_success(api.submit_application(app["id"], UW))

    assert submitted["attained_age"] == 86, submitted
    assert submitted["status"] == "DECLINED", submitted
    assert submitted["decline_reason"] == "AGE_OUT_OF_BAND", submitted


def test_attained_age_equal_max_issue_age_approved(api):
    """PRD §3.1: "It defines the eligible age range through min_issue_age
    (default 45) and max_issue_age (default 85); an applicant's attained age must
    fall at or above the minimum and at or below the maximum."

    Design: Difficulty/boundary_precision_check/max_issue_age_boundary_85_vs_86
    """
    plan = create_plan(simple=False)
    set_clock("2026-02-01T00:00:00Z")
    # DOB 1940-06-15 -> attained age 85 == max_issue_age (inclusive) -> APPROVED.
    applicant = create_applicant(full_name="Bord Line", date_of_birth="1940-06-15", gender="MALE")
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1000000)
    submitted = validate_success(api.submit_application(app["id"], UW))

    assert submitted["attained_age"] == 85, submitted
    assert submitted["status"] == "APPROVED", submitted


# ===========================================================================
# Difficulty / boundary_precision_check / graded_period_boundary_exact_month_24
# ===========================================================================
def test_graded_period_at_exact_boundary_pays_full_face(api):
    """PRD §3.12: "A death falls within the graded variant when the policy's
    benefit type is graded ... and the months in force are strictly less than the
    plan's graded_period_months and the manner of death is NATURAL."

    Design: Difficulty/boundary_precision_check/graded_period_boundary_exact_month_24
    """
    policy = issue_active_policy_only(simple=False, face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_nell")
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    set_clock("2028-02-01T00:00:00Z")  # exactly 24 months in force
    reviewed = claim_under_review(policy["id"], "2028-02-01T00:00:00Z", manner_of_death="NATURAL", certificate_number="DC-6")

    # 24 months == graded_period_months is NOT strictly less -> outside graded -> FULL_FACE.
    assert reviewed["payout_basis"] == "FULL_FACE", reviewed
    assert reviewed["gross_benefit_cents"] == 1000000, reviewed["gross_benefit_cents"]


def test_graded_period_one_month_inside_pays_graded(api):
    """PRD §3.12: "When the death is within the graded variant, payout_basis is
    GRADED_REFUND and the benefit is a refund of premiums paid plus simple
    interest - not the full face."

    Design: Difficulty/boundary_precision_check/graded_period_boundary_exact_month_24
    """
    policy = issue_active_policy_only(simple=False, face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_nell2")
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    set_clock("2028-01-01T00:00:00Z")  # 23 months in force < 24
    reviewed = claim_under_review(policy["id"], "2028-01-01T00:00:00Z", manner_of_death="NATURAL", certificate_number="DC-6b")

    assert reviewed["payout_basis"] == "GRADED_REFUND", reviewed
    assert reviewed["gross_benefit_cents"] != 1000000, reviewed


# ===========================================================================
# Difficulty / cross_entity_state_dependency / claim_filing_depends_on_policy_coverage_status
# ===========================================================================
def test_claim_filing_on_surrendered_policy_rejected(api):
    """PRD §3.11: "A claim may be filed only when the policy's coverage is in
    force - ACTIVE, or LAPSED still inside its reinstatement window - and never
    when coverage is TERMINATED, SURRENDERED, RESCINDED, or still PENDING; a
    filing against an out-of-force policy is rejected with
    ERR_POLICY_NOT_IN_FORCE."

    Design: Difficulty/cross_entity_state_dependency/claim_filing_depends_on_policy_coverage_status
    """
    policy = issue_vested_policy(simple=False, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_sol")
    validate_success(api.surrender_policy(policy["id"], PA))

    resp = api.create_claim({"policy_id": policy["id"], "date_of_death": "2031-03-01T00:00:00Z", "manner_of_death": "NATURAL"}, CE)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_IN_FORCE.value)


def test_claim_filing_on_active_policy_succeeds(api):
    """PRD §3.11: "A claim may be filed only when the policy's coverage is in
    force - ACTIVE, or LAPSED still inside its reinstatement window"

    Design: Difficulty/cross_entity_state_dependency/claim_filing_depends_on_policy_coverage_status
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_sol2")
    set_clock("2026-05-01T00:00:00Z")
    claim = validate_success(api.create_claim({"policy_id": policy["id"], "date_of_death": "2026-05-01T00:00:00Z", "manner_of_death": "NATURAL"}, CE), expected_status=201)
    assert claim["status"] == "FILED", claim


# ===========================================================================
# Difficulty / cross_entity_state_dependency / loan_disburse_depends_on_policy_vesting
# ===========================================================================
def test_loan_before_vesting_rejected(api):
    """PRD §3.9: "A loan may only be taken once the policy is past its vesting
    threshold; a loan before cash_value_vesting_years whole policy-years have
    elapsed is rejected with ERR_CASH_VALUE_NOT_VESTED."

    Design: Difficulty/cross_entity_state_dependency/loan_disburse_depends_on_policy_vesting
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_tess")
    set_clock("2027-02-01T00:00:00Z")  # only 1 year in force, not vested
    fresh = validate_success(api.get_policy(policy["id"], PA))

    resp = api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": fresh["version"], "principal_cents": 5000}, PA)
    validate_error(resp, ApiErrorId.ERR_CASH_VALUE_NOT_VESTED.value)


def test_loan_after_vesting_succeeds(api):
    """PRD §3.9: "A successful disbursement creates the loan ACTIVE with
    disbursed_date at the current clock and repaid_principal_cents initialized to
    0, increments the policy's version by one"

    Design: Difficulty/cross_entity_state_dependency/loan_disburse_depends_on_policy_vesting
    """
    policy = issue_vested_policy(simple=False, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_tess2")
    loan = validate_success(api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": policy["version"], "principal_cents": 5000}, PA), expected_status=201)
    assert loan["status"] == "ACTIVE", loan


# ===========================================================================
# Difficulty / resource_temporal_overlap / premium_coverage_halfopen_overlap_rejected
# ===========================================================================
def test_premium_coverage_overlap_rejected(api):
    """PRD §3.6: "It is rejected with ERR_COVERAGE_PERIOD_OVERLAP if the new
    interval overlaps the interval of any existing POSTED payment on the same
    policy; pure adjacency, where a prior payment's coverage_end exactly equals
    the new coverage_start, is permitted and is not an overlap."

    Design: Difficulty/resource_temporal_overlap/premium_coverage_halfopen_overlap_rejected
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_una")
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")

    resp = api.create_premium_payment({"policy_id": policy["id"], "amount_cents": 6000, "coverage_start": "2026-02-15T00:00:00Z", "coverage_end": "2026-03-15T00:00:00Z"}, PA)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP.value)


def test_premium_coverage_adjacent_allowed(api):
    """PRD §3.6: "pure adjacency, where a prior payment's coverage_end exactly
    equals the new coverage_start, is permitted and is not an overlap."

    Design: Difficulty/resource_temporal_overlap/premium_coverage_halfopen_overlap_rejected
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_una2")
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")

    payment = validate_success(api.create_premium_payment({"policy_id": policy["id"], "amount_cents": 6000, "coverage_start": "2026-03-01T00:00:00Z", "coverage_end": "2026-04-01T00:00:00Z"}, PA), expected_status=201)
    assert payment["status"] == "POSTED", payment


# ===========================================================================
# Difficulty / resource_temporal_overlap / loan_cooldown_buffer_overlap_rejected
# ===========================================================================
def test_loan_cooldown_buffer_overlap_rejected(api):
    """PRD §3.9: "The loan cooldown requires that a new loan's disbursed_date be
    at or after the prior settled loan's settled_date plus loan_cooldown_days; a
    disbursement inside that cooldown is rejected with ERR_LOAN_COOLDOWN_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/loan_cooldown_buffer_overlap_rejected
    """
    policy = issue_vested_policy(simple=False, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_van")
    loan1 = validate_success(api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": policy["version"], "principal_cents": 5000}, PA), expected_status=201)
    validate_success(api.repay_policy_loan(loan1["id"], {"amount_cents": 5000}, PA))  # settled 2031-02-01
    set_clock("2031-02-15T00:00:00Z")  # 14 days < 30 cooldown
    fresh = validate_success(api.get_policy(policy["id"], PA))

    resp = api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": fresh["version"], "principal_cents": 5000}, PA)
    validate_error(resp, ApiErrorId.ERR_LOAN_COOLDOWN_OVERLAP.value)


def test_loan_after_cooldown_elapsed_succeeds(api):
    """PRD §3.9: "The loan cooldown requires that a new loan's disbursed_date be
    at or after the prior settled loan's settled_date plus loan_cooldown_days"

    Design: Difficulty/resource_temporal_overlap/loan_cooldown_buffer_overlap_rejected
    """
    policy = issue_vested_policy(simple=False, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_van2")
    loan1 = validate_success(api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": policy["version"], "principal_cents": 5000}, PA), expected_status=201)
    validate_success(api.repay_policy_loan(loan1["id"], {"amount_cents": 5000}, PA))  # settled 2031-02-01
    set_clock("2031-04-01T00:00:00Z")  # > 30 days after settlement
    fresh = validate_success(api.get_policy(policy["id"], PA))

    loan2 = validate_success(api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": fresh["version"], "principal_cents": 5000}, PA), expected_status=201)
    assert loan2["status"] == "ACTIVE", loan2


# ===========================================================================
# Difficulty / compensating_invariant / premium_post_then_reverse_conserves_premiums_paid
# ===========================================================================
def test_premium_reverse_conserves_premiums_paid(api):
    """PRD §3.6: "Reversal sets the payment's status to REVERSED and recomputes
    the policy's total_premiums_paid_cents and paid_through_date back to the
    values they held before the post, conserving the premiums-paid invariant"

    Design: Difficulty/compensating_invariant/premium_post_then_reverse_conserves_premiums_paid
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_wynn")
    payment = post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    validate_success(api.reverse_premium_payment(payment["id"], PA))

    fresh = validate_success(api.get_policy(policy["id"], PA))
    assert fresh["total_premiums_paid_cents"] == 0, fresh["total_premiums_paid_cents"]
    assert fresh["paid_through_date"].startswith("2026-02-01"), fresh["paid_through_date"]


def test_premium_reverse_sets_status_reversed(api):
    """PRD §3.6: "A PolicyAdmin may reverse a POSTED premium as a compensating
    action ... Reversal sets the payment's status to REVERSED"
    PRD §3.6: "The conserved invariant is that total_premiums_paid_cents always
    equals the sum of POSTED premium amounts minus those that have been reversed."

    Design: Difficulty/compensating_invariant/premium_post_then_reverse_conserves_premiums_paid
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_wynn2")
    payment = post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    reversed_payment = validate_success(api.reverse_premium_payment(payment["id"], PA))
    assert reversed_payment["status"] == "REVERSED", reversed_payment


# ===========================================================================
# Difficulty / compensating_invariant / loan_disburse_then_repay_conserves_cash_value
# ===========================================================================
def test_loan_repay_restores_cash_value(api):
    """PRD §3.9: "A successful repayment moves the loan to SETTLED, sets its
    settled_date to the current clock, recomputes the policy's net_cash_value_cents
    and outstanding_loan_balance_cents to restore the cash-value invariant"

    Design: Difficulty/compensating_invariant/loan_disburse_then_repay_conserves_cash_value
    """
    policy = issue_vested_policy(simple=False, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_xan")
    loan = disburse_loan(policy["id"], principal_cents=20000)
    set_clock("2031-05-02T00:00:00Z")  # 90 days; balance 20395
    validate_success(api.repay_policy_loan(loan["id"], {"amount_cents": 20395}, PA))

    fresh = validate_success(api.get_policy(policy["id"], PA))
    assert fresh["outstanding_loan_balance_cents"] == 0, fresh["outstanding_loan_balance_cents"]
    assert fresh["net_cash_value_cents"] == 30000, fresh["net_cash_value_cents"]
    assert fresh["gross_cash_value_cents"] == 30000, fresh["gross_cash_value_cents"]


def test_loan_disburse_reduces_net_cash_value(api):
    """PRD §3.9: "net_cash_value_cents is the gross cash value minus the
    outstanding loan balance, floored at zero."
    PRD §3.9: "The outstanding_loan_balance_cents is the sum of principal plus
    accrued interest across all ACTIVE loans"

    Design: Difficulty/compensating_invariant/loan_disburse_then_repay_conserves_cash_value
    """
    policy = issue_vested_policy(simple=False, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_xan2")
    disburse_loan(policy["id"], principal_cents=20000)
    set_clock("2031-05-02T00:00:00Z")  # 90 days; balance 20395

    fresh = validate_success(api.get_policy(policy["id"], PA))
    assert fresh["gross_cash_value_cents"] == 30000, fresh["gross_cash_value_cents"]
    assert fresh["net_cash_value_cents"] == 9605, fresh["net_cash_value_cents"]


# ===========================================================================
# Corner / validations
# ===========================================================================
def test_beneficiary_shares_exceed_100_rejected(api):
    """PRD §3.8: "after each write, the sum of share_pct across the policy's
    ACTIVE beneficiaries must not exceed 100, and a write that would push the
    running total above 100 is rejected with ERR_SHARES_EXCEED_100."

    Design: Corner/validations/beneficiary_shares_exceed_100_rejected
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_sh")
    api.create_beneficiary(policy["id"], {"full_name": "Major Heir", "relationship": "CHILD", "share_pct": 70}, PA)

    resp = api.create_beneficiary(policy["id"], {"full_name": "Partial Heir", "relationship": "CHILD", "share_pct": 50}, PA)
    validate_error(resp, ApiErrorId.ERR_SHARES_EXCEED_100.value)


def test_loan_exceeds_cash_value_rejected(api):
    """PRD §3.9: "The fiscal cap requires that the outstanding balance plus the
    new principal not exceed max_loan_to_cash_value_pct of the policy's net cash
    value, and that the policy be past vesting; a request that breaches the cap
    is rejected with ERR_LOAN_EXCEEDS_CASH_VALUE."

    Design: Corner/validations/loan_exceeds_cash_value_rejected
    """
    policy = issue_vested_policy(simple=True, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_ex")
    # net cash value 30000, max loan = 0.90*30000 = 27000; request 28000 exceeds.
    resp = api.create_policy_loan({"policy_id": policy["id"], "expected_policy_version": policy["version"], "principal_cents": 28000}, PA)
    validate_error(resp, ApiErrorId.ERR_LOAN_EXCEEDS_CASH_VALUE.value)


def test_loan_repay_underpaid_rejected(api):
    """PRD §3.9: "Full repayment requires that the amount be at least the
    outstanding principal (principal minus already-repaid principal) plus the
    accrued interest; an amount short of that is rejected with
    ERR_LOAN_UNDERPAID."

    Design: Corner/validations/loan_repay_underpaid_rejected
    """
    policy = issue_vested_policy(simple=True, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_up")
    loan = disburse_loan(policy["id"], principal_cents=20000)
    set_clock("2031-05-02T00:00:00Z")  # balance 20395

    resp = api.repay_policy_loan(loan["id"], {"amount_cents": 20000}, PA)
    validate_error(resp, ApiErrorId.ERR_LOAN_UNDERPAID.value)


def test_premium_coverage_start_after_end_rejected(api):
    """PRD §3.6: "The request is rejected with ERR_VALIDATION if coverage_start
    is not strictly before coverage_end."

    Design: Corner/validations/premium_coverage_start_after_end_rejected
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_bi")
    resp = api.create_premium_payment({"policy_id": policy["id"], "amount_cents": 6000, "coverage_start": "2026-03-01T00:00:00Z", "coverage_end": "2026-02-01T00:00:00Z"}, PA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_surrender_before_vesting_rejected(api):
    """PRD §3.10: "Surrender requires that coverage is ACTIVE - otherwise
    ERR_INVALID_STATE - that the whole policy-years in force are at least
    cash_value_vesting_years - otherwise ERR_CASH_VALUE_NOT_VESTED"

    Design: Corner/validations/surrender_before_vesting_rejected
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_nv")
    set_clock("2027-02-01T00:00:00Z")  # 1 year < 3 vesting years

    resp = api.surrender_policy(policy["id"], PA)
    validate_error(resp, ApiErrorId.ERR_CASH_VALUE_NOT_VESTED.value)
