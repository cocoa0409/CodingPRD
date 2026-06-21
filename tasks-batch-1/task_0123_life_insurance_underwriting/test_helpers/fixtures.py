"""Composite setup helpers for the life-insurance underwriting workflows.

These encapsulate the multi-step preambles the design instances share so tests
focus on assertions, not plumbing. All setup uses get_success_data() (lenient)
so a broken precondition surfaces as a clear "Setup step failed".

Identity threading: the Underwriter and PolicyOwner roles are entity_backed, so
every ownership/segregation-gated call passes the real entity id via the
make_<role>_headers builders — never the shared TEST_USERS constant.

The test harness restarts the server before every test, so every fixture builds
its preconditions from scratch against an empty database using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_admin_headers, make_underwriter_headers, make_policyowner_headers
from .factories import (
    create_product_payload,
    create_underwriter_payload,
    create_applicant_payload,
    create_application_payload,
    create_paramed_exam_payload,
    create_mib_check_payload,
    create_premium_payment_payload,
    create_policy_loan_payload,
    create_beneficiary_payload,
)

# A non-tobacco exam at h70/w160/bp120 -> BMI 22.955, build_debits 0 -> PREFERRED.
# A non-tobacco exam at h70/w210/bp120 -> BMI 30.129, build_debits 50 -> STANDARD.
EXAM_PREFERRED = {"height_inches": 70, "weight_pounds": 160, "systolic_bp": 120}
EXAM_STANDARD = {"height_inches": 70, "weight_pounds": 210, "systolic_bp": 120}


# ─── Clock control ────────────────────────────────────
def set_clock(iso8601: str):
    """Advance/set the server's logical UTC clock (Admin-only)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": iso8601}, make_admin_headers())
    )


# ─── Tier 1: base configuration (products + staff) ───
def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), make_admin_headers())
    )


def create_underwriter(**overrides) -> dict:
    return get_success_data(
        api_client.create_underwriter(create_underwriter_payload(**overrides), make_admin_headers())
    )


def create_applicant(creator_headers=None, **overrides) -> dict:
    """Applicant create is allowed for Admin or Underwriter; create is not
    ownership-gated so any valid creator works."""
    headers = creator_headers or make_admin_headers()
    return get_success_data(
        api_client.create_applicant(create_applicant_payload(**overrides), headers)
    )


def setup_product_and_two_underwriters(product_overrides=None):
    """Product + orderer underwriter (u1) + decider underwriter (u2).

    Returns (product, u1, u2). u1 orders evidence and u2 decides, satisfying
    segregation of duties (PRD §2.10).
    """
    product = create_product(**(product_overrides or {}))
    u1 = create_underwriter(name="U1 Orderer")
    u2 = create_underwriter(name="U2 Decider")
    return product, u1, u2


# ─── Tier 2/3: application progression ───────────────
def create_draft_application(product_id, u1_id, applicant_overrides=None, **app_overrides):
    """Create an applicant + a DRAFT application owned-by-flow under u1.

    Returns (applicant, application).
    """
    applicant = create_applicant(
        creator_headers=make_underwriter_headers(u1_id), **(applicant_overrides or {})
    )
    application = get_success_data(
        api_client.create_application(
            create_application_payload(applicant["id"], product_id, **app_overrides),
            make_underwriter_headers(u1_id),
        )
    )
    return applicant, application


def submit_application(app_id, u1_id) -> dict:
    return get_success_data(
        api_client.submit_application(app_id, make_underwriter_headers(u1_id))
    )


def attach_completed_exam(app_id, u1_id, exam_overrides=None) -> dict:
    """Order-exam (pins u1 as ordering underwriter) + create exam + complete it.

    Assumes the application is in SUBMITTED or UNDER_REVIEW (order-exam moves it
    to EXAM_PENDING). Returns the completed exam.
    """
    get_success_data(api_client.order_exam(app_id, make_underwriter_headers(u1_id)))
    exam = get_success_data(
        api_client.create_paramed_exam(
            app_id, create_paramed_exam_payload(**(exam_overrides or {})),
            make_underwriter_headers(u1_id),
        )
    )
    get_success_data(api_client.complete_paramed_exam(exam["id"], make_underwriter_headers(u1_id)))
    return exam


def add_mib_check(app_id, u1_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_mib_check(
            app_id, create_mib_check_payload(**overrides), make_underwriter_headers(u1_id)
        )
    )


def setup_application_in_exam_pending(product_overrides=None, app_overrides=None,
                                      applicant_overrides=None):
    """Product + u1 + u2 + applicant + application advanced to EXAM_PENDING with an
    ORDERED (not completed) exam attached. Returns dict of all entities.

    For tests of begin-review preconditions that need exam still ORDERED.
    """
    product, u1, u2 = setup_product_and_two_underwriters(product_overrides)
    applicant, application = create_draft_application(
        product["id"], u1["id"], applicant_overrides, **(app_overrides or {})
    )
    submit_application(application["id"], u1["id"])
    get_success_data(api_client.order_exam(application["id"], make_underwriter_headers(u1["id"])))
    return {"product": product, "u1": u1, "u2": u2,
            "applicant": applicant, "application": application}


def setup_application_under_review(exam_overrides=None, mib_overrides=None,
                                   product_overrides=None, applicant_overrides=None,
                                   app_overrides=None):
    """Full path to UNDER_REVIEW: product + u1 + u2 + applicant + application
    SUBMITTED -> EXAM_PENDING (u1 orders) -> completed exam + mib-check ->
    begin-review (u2). Returns dict including the application's UNDER_REVIEW version.

    exam_overrides default to the STANDARD build (build_debits 50) so a non-tobacco
    applicant lands in STANDARD; pass EXAM_PREFERRED for PREFERRED.
    """
    product, u1, u2 = setup_product_and_two_underwriters(product_overrides)
    applicant, application = create_draft_application(
        product["id"], u1["id"], applicant_overrides, **(app_overrides or {})
    )
    submit_application(application["id"], u1["id"])
    exam = attach_completed_exam(application["id"], u1["id"], exam_overrides or dict(EXAM_STANDARD))
    mib = add_mib_check(application["id"], u1["id"], **(mib_overrides or {}))
    reviewed = get_success_data(
        api_client.begin_review(application["id"], make_underwriter_headers(u2["id"]))
    )
    return {"product": product, "u1": u1, "u2": u2, "applicant": applicant,
            "application": reviewed, "exam": exam, "mib": mib,
            "review_version": reviewed["version"]}


def setup_application_approved(exam_overrides=None, mib_overrides=None,
                               product_overrides=None, applicant_overrides=None,
                               app_overrides=None):
    """Drive an application to APPROVED_OFFER. Returns dict with the approved
    application (and its offer version). u2 approves with the UNDER_REVIEW version.

    Default exam build is STANDARD/non-tobacco so final premium == provisional == 125000.
    """
    ctx = setup_application_under_review(
        exam_overrides, mib_overrides, product_overrides, applicant_overrides, app_overrides
    )
    approved = get_success_data(
        api_client.approve_application(
            ctx["application"]["id"],
            {"expected_application_version": ctx["review_version"]},
            make_underwriter_headers(ctx["u2"]["id"]),
        )
    )
    ctx["application"] = approved
    ctx["offer_version"] = approved["version"]
    return ctx


# ─── Tier 5: issued policy + servicing ───────────────
def setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=None,
                        mib_overrides=None, product_overrides=None,
                        applicant_overrides=None, app_overrides=None):
    """Full lifecycle to an ISSUED Policy at a known issue date.

    Sets the clock to issue_clock first, drives the application to APPROVED_OFFER,
    then issues. Returns dict including 'policy' and 'applicant' (the PolicyOwner
    identity for ownership-gated servicing calls).

    Default STANDARD/non-tobacco: final premium 125000, gross 3750 after issue.
    """
    set_clock(issue_clock)
    ctx = setup_application_approved(
        exam_overrides, mib_overrides, product_overrides, applicant_overrides, app_overrides
    )
    policy = get_success_data(
        api_client.issue_application(
            ctx["application"]["id"],
            {"expected_application_version": ctx["offer_version"]},
            make_underwriter_headers(ctx["u2"]["id"]),
        )
    )
    ctx["policy"] = policy
    return ctx


def make_on_cycle_payment(policy_id, applicant_id, amount_cents=125000, **overrides) -> dict:
    """Record an on-cycle annual premium payment as the PolicyOwner (the applicant)."""
    return get_success_data(
        api_client.create_premium_payment(
            policy_id, create_premium_payment_payload(amount_cents, **overrides),
            make_policyowner_headers(applicant_id),
        )
    )


def fetch_policy(policy_id, applicant_id) -> dict:
    """Fetch the policy as its PolicyOwner (also surfaces lazy transitions on read)."""
    return get_success_data(
        api_client.get_policy(policy_id, make_policyowner_headers(applicant_id))
    )


def setup_issued_policy_with_gross_11250(issue_clock="2026-06-01T00:00:00Z",
                                         product_overrides=None):
    """ISSUED STANDARD policy + one on-cycle payment so gross_cash_value == 11250.

    Returns dict with policy (re-fetched after payment), applicant, and the
    current policy version captured from the post-payment read.
    """
    ctx = setup_issued_policy(
        issue_clock=issue_clock,
        exam_overrides=dict(EXAM_STANDARD),
        product_overrides=product_overrides,
    )
    make_on_cycle_payment(ctx["policy"]["id"], ctx["applicant"]["id"], 125000)
    policy = fetch_policy(ctx["policy"]["id"], ctx["applicant"]["id"])
    ctx["policy"] = policy
    ctx["policy_version"] = policy["version"]
    return ctx


def draw_loan(policy_id, applicant_id, principal_cents, expected_policy_version) -> dict:
    return get_success_data(
        api_client.create_policy_loan(
            policy_id,
            create_policy_loan_payload(principal_cents, expected_policy_version),
            make_policyowner_headers(applicant_id),
        )
    )


def add_beneficiary(policy_id, applicant_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_beneficiary(
            policy_id, create_beneficiary_payload(**overrides),
            make_policyowner_headers(applicant_id),
        )
    )


def setup_lapsed_policy(issue_clock="2026-06-01T00:00:00Z",
                        lapse_clock="2027-08-01T00:00:00Z", product_overrides=None):
    """ISSUED STANDARD policy, then advance the clock past due+grace and read it so
    it lazily reaches LAPSED. Returns dict with policy (post-lapse read) + applicant.
    """
    ctx = setup_issued_policy(
        issue_clock=issue_clock,
        exam_overrides=dict(EXAM_STANDARD),
        product_overrides=product_overrides,
    )
    set_clock(lapse_clock)
    policy = fetch_policy(ctx["policy"]["id"], ctx["applicant"]["id"])
    ctx["policy"] = policy
    return ctx
