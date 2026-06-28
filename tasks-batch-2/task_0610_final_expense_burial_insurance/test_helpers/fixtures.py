"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every test.
Fixtures use the lenient get_success_data() validator internally so a broken
setup step surfaces as a clear "Setup failed" rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_policyholder_headers
from .factories import (
    create_product_plan_payload,
    create_simple_plan_payload,
    create_applicant_payload,
    create_application_payload,
    create_questionnaire_payload,
    create_premium_payment_payload,
    create_policy_loan_payload,
    create_claim_payload,
    create_death_certificate_payload,
)

PA = TEST_USERS["policy_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]


# --------------------------------------------------------------------------- #
# Clock                                                                        #
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601, headers=None):
    """Set the logical clock. Any of the three clock-authorized roles may call it."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or PA))


# --------------------------------------------------------------------------- #
# Tier 1 / Tier 2: plan + applicant + draft application + questionnaire        #
# --------------------------------------------------------------------------- #
def create_plan(simple=False, **plan_overrides):
    """Create a ProductPlan. simple=True uses the minimal single-tier plan."""
    payload = (
        create_simple_plan_payload(**plan_overrides)
        if simple
        else create_product_plan_payload(**plan_overrides)
    )
    return get_success_data(api_client.create_product_plan(payload, PA))


def create_applicant(**overrides):
    return get_success_data(api_client.create_applicant(create_applicant_payload(**overrides), UW))


def create_draft_application_with_questionnaire(
    plan_id,
    applicant_id,
    face_cents=1000000,
    questionnaire_overrides=None,
):
    """Plan + applicant already exist. Create a DRAFT application against the
    plan and attach a clean questionnaire. Returns the application dict."""
    app = get_success_data(
        api_client.create_application(
            create_application_payload(applicant_id, plan_id, requested_face_amount_cents=face_cents),
            UW,
        )
    )
    api_client.attach_questionnaire(
        app["id"],
        create_questionnaire_payload(**(questionnaire_overrides or {})),
        UW,
    )
    return app


def submit_application(application_id):
    return get_success_data(api_client.submit_application(application_id, UW))


def issue_policy(application_id, policyholder_user_id="ph_test"):
    """Issue an APPROVED application into a Policy. Returns the Policy dict."""
    return get_success_data(
        api_client.issue_application(
            application_id, {"policyholder_user_id": policyholder_user_id}, PA
        )
    )


# --------------------------------------------------------------------------- #
# Tier 1: state progression to an ACTIVE issued policy                         #
# --------------------------------------------------------------------------- #
def issue_active_policy(
    simple=False,
    face_cents=1000000,
    issue_clock="2026-02-01T00:00:00Z",
    policyholder_user_id="ph_test",
    plan_overrides=None,
    applicant_overrides=None,
    questionnaire_overrides=None,
):
    """Full underwriting chain: plan -> applicant -> draft+questionnaire -> set
    issue clock -> submit (auto-APPROVED) -> issue. Returns (plan, applicant,
    application, policy). The policy is ACTIVE.

    By default uses a clean applicant (age 65 STANDARD on 2026-02-01) so the
    submission auto-approves with no decline/referral.
    """
    plan = create_plan(simple=simple, **(plan_overrides or {}))
    applicant = create_applicant(**(applicant_overrides or {}))
    app = create_draft_application_with_questionnaire(
        plan["id"], applicant["id"], face_cents=face_cents,
        questionnaire_overrides=questionnaire_overrides,
    )
    set_clock(issue_clock)
    submit_application(app["id"])
    policy = issue_policy(app["id"], policyholder_user_id=policyholder_user_id)
    return plan, applicant, app, policy


def issue_active_policy_only(**kwargs):
    """Convenience: same as issue_active_policy but returns only the policy."""
    _, _, _, policy = issue_active_policy(**kwargs)
    return policy


# --------------------------------------------------------------------------- #
# Tier 4: accumulation / vesting targeting                                     #
# --------------------------------------------------------------------------- #
def issue_vested_policy(
    simple=True,
    face_cents=1000000,
    issue_clock="2026-02-01T00:00:00Z",
    vested_clock="2031-02-01T00:00:00Z",
    policyholder_user_id="ph_test",
    plan_overrides=None,
    pay_through="2040-01-01T00:00:00Z",
):
    """Issue an ACTIVE policy then advance the clock past the vesting threshold
    (default: issued 2026-02-01, advanced to 2031-02-01 = 5 whole years, vested
    years 2, gross cash value 30000 for face 1000000c). Returns the policy dict
    re-read at the vested clock (so its computed cash-value fields are populated).

    Per PRD §2.4/§3.6 a policy left unpaid as the clock advances past its grace
    window would lapse for non-payment. To keep the policy in force across the
    multi-year vesting advance (so it stays ACTIVE/CURRENT, the precondition the
    vesting/surrender/claim scenarios require), a single premium is posted up
    front covering [issue_clock, pay_through) before the clock is advanced.
    Premiums do not alter gross cash value, so the vesting figures are unchanged.
    Pass an earlier ``pay_through`` to let grace expire for lapse scenarios.
    """
    plan, applicant, app, policy = issue_active_policy(
        simple=simple, face_cents=face_cents, issue_clock=issue_clock,
        policyholder_user_id=policyholder_user_id, plan_overrides=plan_overrides,
    )
    # Keep the policy paid up so the vesting advance does not lapse it.
    post_premium(policy["id"], 6000, issue_clock, pay_through)
    set_clock(vested_clock)
    fresh = get_success_data(api_client.get_policy(policy["id"], PA))
    return fresh


def disburse_loan(policy_id, principal_cents=20000, headers=None):
    """Read the policy version then disburse a loan. Returns the loan dict."""
    pol = get_success_data(api_client.get_policy(policy_id, PA))
    loan = get_success_data(
        api_client.create_policy_loan(
            create_policy_loan_payload(policy_id, pol["version"], principal_cents=principal_cents),
            headers or PA,
        )
    )
    return loan


def issue_vested_policy_with_loan(
    principal_cents=20000,
    issue_clock="2026-02-01T00:00:00Z",
    vested_clock="2031-02-01T00:00:00Z",
    policyholder_user_id="ph_test",
    pay_through="2040-01-01T00:00:00Z",
):
    """Vested ACTIVE policy with one ACTIVE loan disbursed at the vested clock.
    Returns (policy, loan). ``pay_through`` controls how long the policy stays
    paid up (pass an earlier value to let grace expire for a lapse scenario)."""
    policy = issue_vested_policy(
        issue_clock=issue_clock, vested_clock=vested_clock,
        policyholder_user_id=policyholder_user_id, pay_through=pay_through,
    )
    loan = disburse_loan(policy["id"], principal_cents=principal_cents)
    return policy, loan


# --------------------------------------------------------------------------- #
# Tier 3 / Tier 5: claims lifecycle shortcuts                                  #
# --------------------------------------------------------------------------- #
def file_claim(policy_id, date_of_death, manner_of_death="NATURAL"):
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(policy_id, date_of_death=date_of_death, manner_of_death=manner_of_death),
            CE,
        )
    )


def attach_certificate(claim_id, verified=True, certified_cause="ILLNESS", certificate_number="DC-1"):
    return get_success_data(
        api_client.attach_death_certificate(
            claim_id,
            create_death_certificate_payload(
                certificate_number=certificate_number,
                certified_cause=certified_cause,
                verified=verified,
            ),
            CE,
        )
    )


def claim_under_review(
    policy_id,
    date_of_death,
    manner_of_death="NATURAL",
    verified=True,
    certified_cause="ILLNESS",
    certificate_number="DC-1",
):
    """File a claim, attach a certificate, and start review. Returns the claim
    dict as returned by start-review (carries provisional gross/payout_basis)."""
    claim = file_claim(policy_id, date_of_death, manner_of_death=manner_of_death)
    attach_certificate(
        claim["id"], verified=verified, certified_cause=certified_cause,
        certificate_number=certificate_number,
    )
    reviewed = get_success_data(api_client.start_review_claim(claim["id"], CE))
    return reviewed


def post_premium(policy_id, amount_cents, coverage_start, coverage_end):
    return get_success_data(
        api_client.create_premium_payment(
            create_premium_payment_payload(
                policy_id, amount_cents=amount_cents,
                coverage_start=coverage_start, coverage_end=coverage_end,
            ),
            PA,
        )
    )


def surrender_policy(policy_id, headers=None):
    return get_success_data(api_client.surrender_policy(policy_id, headers or PA))
