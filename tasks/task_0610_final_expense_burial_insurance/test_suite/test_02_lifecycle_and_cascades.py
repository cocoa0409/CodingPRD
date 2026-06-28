"""Policy / application / claim lifecycle transitions and cross-entity cascades.

Translates non_linear_state_machine and transitive_cascade difficulty rules
(queue A), the state_machines corner section, and the cascade/consistency
cross-cutting instances (queue B).
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
    issue_vested_policy_with_loan,
    create_plan,
    create_applicant,
    create_draft_application_with_questionnaire,
    set_clock,
    submit_application,
    issue_policy,
    post_premium,
    file_claim,
    attach_certificate,
    claim_under_review,
    disburse_loan,
)
from test_helpers.api_client import api_client

PA = TEST_USERS["policy_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine / policy_cyclic_active_lapsed_active
# ===========================================================================
def test_policy_cycles_active_lapsed_active_on_reinstate(api):
    """PRD §3.7: "Reinstating a lapsed policy is a PolicyAdmin action that moves
    coverage from LAPSED back to ACTIVE."
    PRD §3.7: "On reinstatement coverage returns to ACTIVE, payment status
    returns to CURRENT, and every CALLED loan transitions from CALLED back to
    ACTIVE."

    Design: Difficulty/non_linear_state_machine/policy_cyclic_active_lapsed_active
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_dora")
    set_clock("2026-04-01T00:00:00Z")  # past due_date 2026-02-01 + 31 grace
    validate_success(api.lapse_policy(policy["id"], PA))
    # Post back premium covering the current cycle before reinstating.
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2026-05-01T00:00:00Z")

    reinstated = validate_success(api.reinstate_policy(policy["id"], PA))
    assert reinstated["coverage_status"] == "ACTIVE", reinstated
    assert reinstated["payment_status"] == "CURRENT", reinstated


def test_lapse_sets_coverage_lapsed_and_payment_delinquent(api):
    """PRD §3.7: "A lapse sets coverage to LAPSED and payment status to
    DELINQUENT, opens a reinstatement window running from the lapse instant to
    the lapse instant plus reinstatement_window_days"

    Design: Difficulty/non_linear_state_machine/policy_cyclic_active_lapsed_active
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_dora2")
    set_clock("2026-04-01T00:00:00Z")
    lapsed = validate_success(api.lapse_policy(policy["id"], PA))

    assert lapsed["coverage_status"] == "LAPSED", lapsed
    assert lapsed["payment_status"] == "DELINQUENT", lapsed


# ===========================================================================
# Difficulty / non_linear_state_machine / claim_branching_under_review_to_contesting
# ===========================================================================
def test_claim_branches_under_review_to_contesting(api):
    """PRD §3.13: "Contesting moves the claim from UNDER_REVIEW to CONTESTING for
    a misrepresentation investigation, but is permitted only when the date of
    death falls within contestability_period_months of the policy's issue_date"

    Design: Difficulty/non_linear_state_machine/claim_branching_under_review_to_contesting
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_glen")
    set_clock("2026-05-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2026-05-01T00:00:00Z", manner_of_death="NATURAL", verified=False, certificate_number="DC-3")

    contested = validate_success(api.contest_claim(reviewed["id"], CE))
    assert contested["status"] == "CONTESTING", contested


def test_deny_from_contesting_sets_misrepresentation_and_rescinds(api):
    """PRD §3.13: "A denial from CONTESTING sets denial_reason to
    MISREPRESENTATION, and if the death falls within the contestability window
    the policy transitions from ACTIVE to the terminal RESCINDED state"

    Design: Difficulty/non_linear_state_machine/claim_branching_under_review_to_contesting
    """
    policy = issue_active_policy_only(simple=False, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_glen2")
    set_clock("2026-05-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2026-05-01T00:00:00Z", manner_of_death="NATURAL", verified=False, certificate_number="DC-3b")
    contested = validate_success(api.contest_claim(reviewed["id"], CE))

    denied = validate_success(api.deny_claim(contested["id"], {}, CE))
    assert denied["status"] == "DENIED", denied
    assert denied["denial_reason"] == "MISREPRESENTATION", denied
    fresh_policy = validate_success(api.get_policy(policy["id"], PA))
    assert fresh_policy["coverage_status"] == "RESCINDED", fresh_policy


# ===========================================================================
# Difficulty / transitive_cascade / claim_approve_terminates_policy_settles_loan_depth3
# ===========================================================================
def test_claim_approve_terminates_policy_and_settles_loan(api):
    """PRD §3.13: "Approval is the first step of a depth-3 cascade: the policy
    transitions from ACTIVE to TERMINATED, which in turn settles each ACTIVE or
    CALLED loan to SETTLED with its balance netted against the death benefit as
    the loan offset."
    PRD §3.13: "sets loan_offset_cents to the policy's
    outstanding_loan_balance_cents, and sets net_payout_cents to the gross
    benefit minus that offset, floored at zero."

    Design: Difficulty/transitive_cascade/claim_approve_terminates_policy_settles_loan_depth3
    """
    policy, loan = issue_vested_policy_with_loan(principal_cents=20000, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_hugh")
    set_clock("2031-03-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2031-03-01T00:00:00Z", manner_of_death="ACCIDENTAL", certified_cause="ACCIDENT", certificate_number="DC-4")

    approved = validate_success(api.approve_claim(reviewed["id"], CE))
    assert approved["status"] == "APPROVED", approved
    assert approved["payout_basis"] == "FULL_FACE", approved
    # loan balance: 20000 principal + round(20000*0.08*28/365)=123 -> offset 20123.
    assert approved["loan_offset_cents"] == 20123, approved["loan_offset_cents"]
    assert approved["net_payout_cents"] == 979877, approved["net_payout_cents"]

    fresh_policy = validate_success(api.get_policy(policy["id"], PA))
    assert fresh_policy["coverage_status"] == "TERMINATED", fresh_policy
    fresh_loan = validate_success(api.get_policy_loan(loan["id"], PA))
    assert fresh_loan["status"] == "SETTLED", fresh_loan


def test_claim_approve_terminates_policy_no_loan(api):
    """PRD §3.13: "the policy transitions from ACTIVE to TERMINATED"
    PRD §3.13: "On approval the system finalizes gross_benefit_cents and
    payout_basis, sets loan_offset_cents to the policy's
    outstanding_loan_balance_cents, and sets net_payout_cents to the gross
    benefit minus that offset, floored at zero."

    Design: Difficulty/transitive_cascade/claim_approve_terminates_policy_settles_loan_depth3
    """
    policy = issue_vested_policy(simple=False, face_cents=1000000, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_hugh2")
    set_clock("2031-03-01T00:00:00Z")
    reviewed = claim_under_review(policy["id"], "2031-03-01T00:00:00Z", manner_of_death="ACCIDENTAL", certified_cause="ACCIDENT", certificate_number="DC-4b")

    approved = validate_success(api.approve_claim(reviewed["id"], CE))
    assert approved["loan_offset_cents"] == 0, approved
    assert approved["net_payout_cents"] == 1000000, approved
    fresh_policy = validate_success(api.get_policy(policy["id"], PA))
    assert fresh_policy["coverage_status"] == "TERMINATED", fresh_policy


# ===========================================================================
# Difficulty / transitive_cascade / issue_creates_policy_depth2
# ===========================================================================
def test_issue_creates_active_policy_with_pinned_fields(api):
    """PRD §3.5: "Issuing advances the application to its terminal ISSUED state
    and, as a depth-2 cascade, creates a Policy."
    PRD §3.5: "The policy is created with coverage status PENDING and payment
    status CURRENT, then immediately auto-advances its coverage from PENDING to
    ACTIVE."

    Design: Difficulty/transitive_cascade/issue_creates_policy_depth2
    """
    plan = create_plan(simple=False)
    applicant = create_applicant(full_name="Ina Reed")
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1000000)
    set_clock("2026-02-01T00:00:00Z")
    submit_application(app["id"])

    policy = validate_success(api.issue_application(app["id"], {"policyholder_user_id": "ph_ina"}, PA), expected_status=201)
    assert policy["coverage_status"] == "ACTIVE", policy
    assert policy["face_amount_cents"] == 1000000, policy
    assert policy["monthly_premium_cents"] == 6000, policy

    fresh_app = validate_success(api.get_application(app["id"], UW))
    assert fresh_app["status"] == "ISSUED", fresh_app


def test_issue_advances_application_to_issued_terminal(api):
    """PRD §3.5: "Issuing advances the application to its terminal ISSUED state
    and, as a depth-2 cascade, creates a Policy. The new policy pins
    face_amount_cents, monthly_premium_cents, benefit_type, applicant_id, and
    product_plan_id from the application and plan"

    Design: Difficulty/transitive_cascade/issue_creates_policy_depth2
    """
    plan = create_plan(simple=False)
    applicant = create_applicant(full_name="Ina Reed 2")
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1000000)
    set_clock("2026-02-01T00:00:00Z")
    submit_application(app["id"])

    policy = validate_success(api.issue_application(app["id"], {"policyholder_user_id": "ph_ina2"}, PA), expected_status=201)
    assert policy["benefit_type"] == "GRADED_BENEFIT", policy
    assert policy["applicant_id"] == applicant["id"], policy
    assert policy["product_plan_id"] == plan["id"], policy


# ===========================================================================
# Corner / state_machines
# ===========================================================================
def test_resubmit_approved_application_invalid_state(api):
    """PRD §3.3: "Submitting an application for adjudication is an Underwriter
    action that advances it from DRAFT to SUBMITTED."
    PRD §5 names ERR_INVALID_STATE for a target resource not in a state
    permitting this transition.

    Design: Corner/state_machines/submit_already_submitted_application_invalid_state
    """
    plan = create_plan(simple=True)
    applicant = create_applicant(full_name="Re Sub")
    app = create_draft_application_with_questionnaire(plan["id"], applicant["id"], face_cents=1000000)
    set_clock("2026-02-01T00:00:00Z")
    submit_application(app["id"])  # auto-APPROVED

    resp = api.submit_application(app["id"], UW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_submit_without_questionnaire_rejected(api):
    """PRD §3.3: "Submission requires that exactly one health questionnaire has
    been attached; with none present the submission is rejected with
    ERR_QUESTIONNAIRE_MISSING."

    Design: Corner/state_machines/submit_without_questionnaire_rejected
    """
    plan = create_plan(simple=True)
    applicant = create_applicant(full_name="No Q")
    app = validate_success(
        api.create_application({"applicant_id": applicant["id"], "product_plan_id": plan["id"], "requested_face_amount_cents": 1000000}, UW),
        expected_status=201,
    )
    set_clock("2026-02-01T00:00:00Z")

    resp = api.submit_application(app["id"], UW)
    validate_error(resp, ApiErrorId.ERR_QUESTIONNAIRE_MISSING.value)


def test_knockout_questionnaire_auto_declines(api):
    """PRD §3.3: "If knockout_triggered is true, or the attained age is below the
    plan's min_issue_age or above its max_issue_age, or the requested face falls
    outside every configured face tier, the application advances automatically
    from SUBMITTED to DECLINED."
    PRD §3.3: "a knockout takes precedence and yields KNOCKOUT_CONDITION"

    Design: Corner/state_machines/knockout_questionnaire_auto_declines
    """
    plan = create_plan(simple=True)
    applicant = create_applicant(full_name="Ko Out")
    app = create_draft_application_with_questionnaire(
        plan["id"], applicant["id"], face_cents=1000000,
        questionnaire_overrides={"terminal_illness": True},
    )
    set_clock("2026-02-01T00:00:00Z")
    submitted = validate_success(api.submit_application(app["id"], UW))

    assert submitted["status"] == "DECLINED", submitted
    assert submitted["decline_reason"] == "KNOCKOUT_CONDITION", submitted


def test_manual_lapse_before_grace_expires_rejected(api):
    """PRD §3.7: "when fired by hand, that the current clock has reached or
    passed the due date plus grace_period_days; lapsing before grace has expired
    is rejected with ERR_GRACE_NOT_EXPIRED."

    Design: Corner/state_machines/manual_lapse_before_grace_expires_rejected
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_grace")
    set_clock("2026-02-10T00:00:00Z")  # only 9 days < 31 grace
    resp = api.lapse_policy(policy["id"], PA)
    validate_error(resp, ApiErrorId.ERR_GRACE_NOT_EXPIRED.value)


def test_reinstate_after_window_closed_rejected(api):
    """PRD §3.7: "that the current clock is at or before the lapse instant plus
    reinstatement_window_days - otherwise ERR_REINSTATEMENT_WINDOW_CLOSED"

    Design: Corner/state_machines/reinstate_after_window_closed_rejected
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_wi")
    set_clock("2026-04-01T00:00:00Z")
    validate_success(api.lapse_policy(policy["id"], PA))
    set_clock("2027-01-01T00:00:00Z")  # > 180 days past lapse
    post_premium(policy["id"], 6000, "2026-02-01T00:00:00Z", "2027-02-01T00:00:00Z")

    resp = api.reinstate_policy(policy["id"], PA)
    validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_WINDOW_CLOSED.value)


def test_surrendered_policy_cannot_surrender_again(api):
    """PRD §3.10: "A Policyholder or PolicyAdmin may surrender an ACTIVE policy
    for its cash value. Surrender requires that coverage is ACTIVE - otherwise
    ERR_INVALID_STATE"

    Design: Corner/state_machines/terminal_state_surrendered_no_further_transition
    """
    policy = issue_vested_policy(simple=True, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_te")
    validate_success(api.surrender_policy(policy["id"], PA))

    resp = api.surrender_policy(policy["id"], PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_start_review_without_certificate_rejected(api):
    """PRD §3.11: "A ClaimsExaminer starts review, advancing the claim from FILED
    to UNDER_REVIEW; this requires that a death certificate exists for the claim,
    otherwise ERR_DEATH_CERTIFICATE_MISSING."

    Design: Corner/state_machines/start_review_without_death_certificate_rejected
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_nc")
    set_clock("2026-05-01T00:00:00Z")
    claim = file_claim(policy["id"], "2026-05-01T00:00:00Z", manner_of_death="NATURAL")

    resp = api.start_review_claim(claim["id"], CE)
    validate_error(resp, ApiErrorId.ERR_DEATH_CERTIFICATE_MISSING.value)


def test_approve_claim_with_unverified_certificate_rejected(api):
    """PRD §3.13: "Approval requires that the policy's coverage is still ACTIVE,
    otherwise ERR_POLICY_NOT_IN_FORCE, and that the attached death certificate's
    verified flag is true, otherwise ERR_CERTIFICATE_NOT_VERIFIED."

    Design: Corner/state_machines/approve_claim_with_unverified_certificate_rejected
    """
    policy = issue_vested_policy(simple=True, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-03-01T00:00:00Z", policyholder_user_id="ph_uv")
    reviewed = claim_under_review(policy["id"], "2031-03-01T00:00:00Z", manner_of_death="ACCIDENTAL", verified=False, certified_cause="ACCIDENT", certificate_number="DC-UV")

    resp = api.approve_claim(reviewed["id"], CE)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_VERIFIED.value)


def test_contest_outside_contestability_window_rejected(api):
    """PRD §3.13: "Contesting moves the claim from UNDER_REVIEW to CONTESTING for
    a misrepresentation investigation, but is permitted only when the date of
    death falls within contestability_period_months of the policy's issue_date;
    a contest of a death outside the contestability window is rejected with
    ERR_OUTSIDE_CONTESTABILITY."

    Design: Corner/state_machines/contest_outside_contestability_window_rejected
    """
    policy = issue_active_policy_only(simple=True, issue_clock="2026-02-01T00:00:00Z", policyholder_user_id="ph_ou")
    set_clock("2029-03-01T00:00:00Z")  # > 24 months from issue
    reviewed = claim_under_review(policy["id"], "2029-03-01T00:00:00Z", manner_of_death="NATURAL", certificate_number="DC-OT")

    resp = api.contest_claim(reviewed["id"], CE)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_CONTESTABILITY.value)


# ===========================================================================
# Corner / cross_cutting_complexity_layers / lapse_cascades_active_loan_to_called
# ===========================================================================
def test_lapse_cascades_active_loan_to_called(api):
    """PRD §3.7: "as the second step of a depth-3 cascade - transitions every
    ACTIVE policy loan on the policy from ACTIVE to CALLED, because the loan is
    called due on lapse."

    Design: Corner/cross_cutting_complexity_layers/lapse_cascades_active_loan_to_called
    """
    policy, loan = issue_vested_policy_with_loan(principal_cents=5000, issue_clock="2026-02-01T00:00:00Z", vested_clock="2031-02-01T00:00:00Z", policyholder_user_id="ph_ca", pay_through="2031-02-15T00:00:00Z")
    set_clock("2031-04-01T00:00:00Z")  # past grace on the unpaid cycle
    lapsed = validate_success(api.lapse_policy(policy["id"], PA))
    assert lapsed["coverage_status"] == "LAPSED", lapsed

    fresh_loan = validate_success(api.get_policy_loan(loan["id"], PA))
    assert fresh_loan["status"] == "CALLED", fresh_loan
