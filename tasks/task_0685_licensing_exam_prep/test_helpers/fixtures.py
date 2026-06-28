"""Composite setup helpers for the Licensing Exam Prep test suite.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints — the harness restarts the server (empty DB) before every test.

Fixtures use get_success_data() (lenient) internally so setup failures surface
as clear "Setup failed" errors, and they thread the owning Learner.id through
make_learner_headers() for every ownership-gated Learner call.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_learner_headers,
)
from . import factories as F

ADMIN = TEST_USERS["content_admin_headers"]
PROCTOR = TEST_USERS["exam_proctor_headers"]
OPS = TEST_USERS["platform_ops_headers"]


# ==========================================================================
# Low-level builders
# ==========================================================================
def create_program(license_code="CPA-FAR", domain_weights=None, passing_scaled_score=75):
    """Create a DRAFT license program. Returns the program dict."""
    if domain_weights is None:
        domain_weights = [{"domain_code": "A", "weight": 1.00}]
    resp = api_client.create_license_program(
        F.create_license_program_payload(
            license_code=license_code,
            title=license_code,
            passing_scaled_score=passing_scaled_score,
            domain_weights=domain_weights,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def add_item(program_id, domain_code="A", difficulty="EASY", correct_choice="A"):
    resp = api_client.add_question_item(
        program_id,
        F.create_question_item_payload(
            domain_code=domain_code, difficulty=difficulty, correct_choice=correct_choice
        ),
        ADMIN,
    )
    return get_success_data(resp)


def publish_program(program_id):
    resp = api_client.publish_license_program(program_id, ADMIN)
    return get_success_data(resp)


def create_published_program(license_code="CPA-FAR", domain_weights=None, passing_scaled_score=75):
    """Create program + one item per distinct domain + publish. Returns the published program."""
    if domain_weights is None:
        domain_weights = [{"domain_code": "A", "weight": 1.00}]
    prog = create_program(license_code, domain_weights, passing_scaled_score)
    add_item(prog["id"], domain_code=domain_weights[0]["domain_code"])
    return publish_program(prog["id"])


def create_plan(**overrides):
    """Create an ACTIVE subscription plan. Returns the plan dict."""
    resp = api_client.create_subscription_plan(F.create_subscription_plan_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_bundle(license_program_id, ce_credits_total=12, modules_total=4):
    resp = api_client.create_ce_bundle(
        F.create_ce_bundle_payload(
            license_program_id, ce_credits_total=ce_credits_total, modules_total=modules_total
        ),
        ADMIN,
    )
    return get_success_data(resp)


def create_learner(email="learner@x.com", full_name="Test Learner"):
    resp = api_client.create_learner(
        F.create_learner_payload(email=email, full_name=full_name),
        TEST_USERS["learner_headers"],
    )
    return get_success_data(resp)


def create_cohort(license_program_id, title="Cohort", capacity=5):
    resp = api_client.create_cohort(
        F.create_cohort_payload(license_program_id, title=title, capacity=capacity), ADMIN
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def create_enrollment(learner, program_id, plan_id, financed=False, ce_bundle_id=None):
    """Create a DRAFT enrollment owned by `learner`. Returns the enrollment dict."""
    overrides = {"financed": financed}
    if ce_bundle_id is not None:
        overrides["ce_bundle_id"] = ce_bundle_id
    resp = api_client.create_enrollment(
        F.create_enrollment_payload(learner["id"], program_id, plan_id, **overrides),
        make_learner_headers(learner["id"]),
    )
    return get_success_data(resp)


def list_installments(enrollment_id, learner_id, params=None):
    resp = api_client.list_installments(enrollment_id, make_learner_headers(learner_id), params=params)
    return get_success_data(resp)


def pay_installment(enrollment_id, installment_id, learner_id):
    resp = api_client.pay_installment(enrollment_id, installment_id, make_learner_headers(learner_id))
    return get_success_data(resp)


def activate(enrollment_id, learner_id):
    resp = api_client.activate_enrollment(enrollment_id, make_learner_headers(learner_id))
    return get_success_data(resp)


def get_enrollment(enrollment_id, learner_id):
    resp = api_client.get_enrollment(enrollment_id, make_learner_headers(learner_id))
    return get_success_data(resp)


# ==========================================================================
# Tier 1 / 2: programs + plans + learners + activated enrollments
# ==========================================================================
def setup_active_enrollment(
    license_code="ACT",
    domain_weights=None,
    plan_overrides=None,
    learner_email="active@x.com",
    pay_in_full=False,
):
    """Published program + ACTIVE plan + learner + paid-in-full DRAFT->ACTIVE enrollment.

    Returns dict: {program, plan, learner, enrollment}. The enrollment is created
    financed=false so activation needs no down payment.

    When pay_in_full=True, every DUE installment is PAID before certification so the
    enrollment's financing_balance_cents is 0 — the PRD §3.5 precondition for a PASS
    certification ("the enrollment owe nothing"). Left False by default so withdraw /
    void scenarios still observe the unpaid installment.
    """
    plan_overrides = plan_overrides or {}
    prog = create_published_program(license_code, domain_weights)
    plan = create_plan(**plan_overrides)
    learner = create_learner(email=learner_email, full_name=learner_email)
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False)
    activate(enr["id"], learner["id"])
    if pay_in_full:
        due = list_installments(enr["id"], learner["id"], params={"status": "DUE"})
        for inst in due:
            pay_installment(enr["id"], inst["id"], learner["id"])
    enr = get_enrollment(enr["id"], learner["id"])
    return {"program": prog, "plan": plan, "learner": learner, "enrollment": enr}


def setup_draft_enrollment(
    license_code="DRF",
    domain_weights=None,
    plan_overrides=None,
    financed=False,
    publish=True,
    learner_email="draft@x.com",
    ce_bundle_id=None,
):
    """Program (published unless publish=False) + plan + learner + DRAFT enrollment.

    Returns dict: {program, plan, learner, enrollment}.
    """
    plan_overrides = plan_overrides or {}
    if publish:
        prog = create_published_program(license_code, domain_weights)
    else:
        prog = create_program(license_code, domain_weights)
    plan = create_plan(**plan_overrides)
    learner = create_learner(email=learner_email, full_name=learner_email)
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=financed, ce_bundle_id=ce_bundle_id)
    return {"program": prog, "plan": plan, "learner": learner, "enrollment": enr}


def setup_financed_active_enrollment(
    license_code="FIN",
    plan_overrides=None,
    learner_email="fin@x.com",
):
    """Published program + financed plan + learner + financed enrollment with the down
    payment (installment seq 1) PAID and then ACTIVATED.

    Returns dict: {program, plan, learner, enrollment, installments}.
    The remaining installments (seq 2..n+1) stay DUE.
    """
    plan_overrides = plan_overrides or {
        "tier": "PLUS",
        "total_price_cents": 120000,
        "down_payment_pct": 0.20,
        "financing_months": 6,
        "included_mock_credits": 8,
    }
    prog = create_published_program(license_code)
    plan = create_plan(**plan_overrides)
    learner = create_learner(email=learner_email, full_name=learner_email)
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=True)
    installments = list_installments(enr["id"], learner["id"])
    pay_installment(enr["id"], installments[0]["id"], learner["id"])
    activate(enr["id"], learner["id"])
    enr = get_enrollment(enr["id"], learner["id"])
    installments = list_installments(enr["id"], learner["id"])
    return {
        "program": prog,
        "plan": plan,
        "learner": learner,
        "enrollment": enr,
        "installments": installments,
    }


# ==========================================================================
# Tier 4: accumulation toward guarantee eligibility / readiness
# ==========================================================================
def accumulate_eligibility(enrollment_id, learner_id, domain_code="A",
                           clock_1="2026-05-03T09:00:00Z", clock_2="2026-05-04T09:00:00Z",
                           mock1_raw=70, mock2_raw=84):
    """Drive an ACTIVE single-domain enrollment to guarantee-eligible state:
    200 questions answered (one 200/200 practice session) + 2 completed mocks,
    the latest mock scaled 84 -> conservative readiness 76 (>= 75).

    Returns the refreshed enrollment dict.
    """
    lh = make_learner_headers(learner_id)
    get_success_data(api_client.create_practice_session(
        enrollment_id,
        F.create_practice_session_payload(domain_code=domain_code, answered_count=200, correct_count=200),
        lh,
    ))
    set_clock(clock_1)
    get_success_data(api_client.create_mock_exam(
        enrollment_id, F.create_mock_exam_payload(raw_score=mock1_raw, item_count=100), lh))
    set_clock(clock_2)
    get_success_data(api_client.create_mock_exam(
        enrollment_id, F.create_mock_exam_payload(raw_score=mock2_raw, item_count=100), lh))
    return get_enrollment(enrollment_id, learner_id)


def certify(enrollment_id, outcome):
    """ExamProctor certifies PASS or FAIL. Returns enrollment dict."""
    resp = api_client.certify_exam(enrollment_id, {"outcome": outcome}, PROCTOR)
    return get_success_data(resp)


def file_claim(enrollment_id, learner_id, remedy):
    resp = api_client.create_pass_guarantee_claim(
        F.create_pass_guarantee_claim_payload(enrollment_id, remedy=remedy),
        make_learner_headers(learner_id),
    )
    return get_success_data(resp)


def decide_claim(claim_id, decision):
    resp = api_client.decide_pass_guarantee_claim(claim_id, {"decision": decision}, PROCTOR)
    return get_success_data(resp)


# ==========================================================================
# Tier 5: terminal / claim-ready lifecycle shortcuts
# ==========================================================================
def setup_eligible_failed_enrollment(
    license_code="ELG",
    plan_overrides=None,
    financed=False,
    pay_extra_installments=None,
    learner_email="elig@x.com",
):
    """ACTIVE enrollment driven to guarantee-eligible, then certified FAIL.

    plan_overrides default to a PRO pass_guarantee plan. If financed, the down
    payment is paid before activation; pay_extra_installments (list of 0-based
    installment indices) lets the caller PAY additional installments after
    activation (e.g. for refund-arithmetic setups).

    Returns dict: {program, plan, learner, enrollment, installments}.
    The enrollment is in FAILED status with guarantee_eligible == true.
    """
    plan_overrides = plan_overrides or {
        "tier": "PRO",
        "total_price_cents": 50000,
        "down_payment_pct": 0.00,
        "financing_months": 1,
        "included_mock_credits": 5,
        "pass_guarantee": True,
        "guarantee_refund_pct": 0.50,
    }
    prog = create_published_program(license_code)
    plan = create_plan(**plan_overrides)
    learner = create_learner(email=learner_email, full_name=learner_email)
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=financed)
    installments = list_installments(enr["id"], learner["id"])
    if financed:
        pay_installment(enr["id"], installments[0]["id"], learner["id"])
    activate(enr["id"], learner["id"])
    if pay_extra_installments:
        for idx in pay_extra_installments:
            pay_installment(enr["id"], installments[idx]["id"], learner["id"])
    accumulate_eligibility(enr["id"], learner["id"])
    certify(enr["id"], "FAIL")
    enr = get_enrollment(enr["id"], learner["id"])
    installments = list_installments(enr["id"], learner["id"])
    return {
        "program": prog,
        "plan": plan,
        "learner": learner,
        "enrollment": enr,
        "installments": installments,
    }


def setup_ineligible_failed_enrollment(
    license_code="INE",
    learner_email="ineli@x.com",
):
    """ACTIVE enrollment on a pass_guarantee plan but with ZERO practice/mocks
    (so guarantee_eligible == false), then certified FAIL.

    Returns dict: {program, plan, learner, enrollment}.
    """
    prog = create_published_program(license_code)
    plan = create_plan(
        tier="PRO", total_price_cents=40000, down_payment_pct=0.00, financing_months=1,
        included_mock_credits=5, pass_guarantee=True, guarantee_refund_pct=0.50,
    )
    learner = create_learner(email=learner_email, full_name=learner_email)
    enr = create_enrollment(learner, prog["id"], plan["id"], financed=False)
    activate(enr["id"], learner["id"])
    certify(enr["id"], "FAIL")
    enr = get_enrollment(enr["id"], learner["id"])
    return {"program": prog, "plan": plan, "learner": learner, "enrollment": enr}


def join_cohort(cohort_id, enrollment_id, learner_id,
                session_start_utc="2026-06-01T10:00:00Z",
                session_end_utc="2026-06-01T12:00:00Z"):
    resp = api_client.create_cohort_membership(
        cohort_id,
        F.create_cohort_membership_payload(
            enrollment_id, session_start_utc=session_start_utc, session_end_utc=session_end_utc
        ),
        make_learner_headers(learner_id),
    )
    return get_success_data(resp)
