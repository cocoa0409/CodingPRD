"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database with the logical clock at the startup
default of 2026-05-01T00:00:00Z, PRD §2.4).

Identity threading: Agent and Policyholder are entity-backed roles (PRD
§2.1). Ownership-gated calls (loans, repayments, non-forfeiture elections,
dividend option) always use make_policyholder_headers(insured["id"]).
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_application_payload,
    create_insured_person_payload,
    create_product_template_payload,
)
from .test_users import TEST_USERS, make_policyholder_headers

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["agent_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
ISSUER = TEST_USERS["policy_issuer_headers"]

DEFAULT_ISSUE_DATE = "2026-05-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(iso: str, days: int) -> str:
    return _fmt(_parse(iso) + timedelta(days=days))


def add_years(iso: str, years: int) -> str:
    dt = _parse(iso)
    try:
        return _fmt(dt.replace(year=dt.year + years))
    except ValueError:  # Feb 29 -> Feb 28 on non-leap target years
        return _fmt(dt.replace(year=dt.year + years, day=28))


def date_part(iso: str) -> str:
    return iso[:10]


# ---------------------------------------------------------------------------
# Tier 0: clock + primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PlatformAdmin only, PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_insured(**overrides):
    payload = create_insured_person_payload(**overrides)
    return get_success_data(api_client.create_insured_person(payload, AGENT))


def create_template(**overrides):
    payload = create_product_template_payload(**overrides)
    return get_success_data(api_client.create_product_template(payload, ADMIN))


def create_application(insured_person_id, product_template_id, **overrides):
    payload = create_application_payload(insured_person_id, product_template_id, **overrides)
    return get_success_data(api_client.create_application(payload, AGENT))


# ---------------------------------------------------------------------------
# Tier 1: application state progression
# ---------------------------------------------------------------------------

def review_and_approve_application(application_id,
                                   underwriting_class="STANDARD_NON_TOBACCO",
                                   underwriter_user_id="uw-1"):
    """SUBMITTED -> UNDER_REVIEW -> APPROVED. Returns the approved application."""
    uw = {"X-User-ID": underwriter_user_id, "X-User-Role": "Underwriter",
          "Content-Type": "application/json"}
    get_success_data(api_client.begin_review(application_id, uw))
    return get_success_data(api_client.approve_application(application_id,
                                                           underwriting_class, uw))


def issue_application(application_id, issuer_user_id="issuer-1"):
    """APPROVED -> ISSUED. Returns the created Policy (201)."""
    issuer = {"X-User-ID": issuer_user_id, "X-User-Role": "PolicyIssuer",
              "Content-Type": "application/json"}
    return get_success_data(api_client.issue_application(application_id, issuer))


# ---------------------------------------------------------------------------
# Tier 2: full entity hierarchy — insured + template + application + policy
# ---------------------------------------------------------------------------

def create_issued_policy(product_type="WHOLE_LIFE_NON_PARTICIPATING",
                         premium_mode="MONTHLY",
                         face_amount_cents=10_000_000,
                         date_of_birth="1990-01-01",
                         tobacco_user=False,
                         gender="FEMALE",
                         base_rate=50,
                         coi_rate_table=None,
                         surrender_charge_schedule=None,
                         participating=False,
                         allows_policy_loans=True,
                         underwriting_class="STANDARD_NON_TOBACCO",
                         min_face_amount_cents=1_000_000,
                         max_face_amount_cents=100_000_000,
                         issue_clock=DEFAULT_ISSUE_DATE):
    """Create insured + template + application, approve, issue.

    Returns dict(insured, template, application, policy).
    """
    set_clock(issue_clock)
    insured = create_insured(date_of_birth=date_of_birth, tobacco_user=tobacco_user,
                             gender=gender)
    template = create_template(
        product_type=product_type,
        participating=participating,
        allows_policy_loans=allows_policy_loans,
        min_face_amount_cents=min_face_amount_cents,
        max_face_amount_cents=max_face_amount_cents,
        base_monthly_premium_rate_per_thousand_cents=base_rate,
        coi_rate_table=coi_rate_table if coi_rate_table is not None else [],
        surrender_charge_schedule=(surrender_charge_schedule
                                   if surrender_charge_schedule is not None else []),
    )
    application = create_application(insured["id"], template["id"],
                                     requested_face_amount_cents=face_amount_cents,
                                     premium_mode=premium_mode)
    review_and_approve_application(application["id"], underwriting_class)
    policy = issue_application(application["id"])
    return {"insured": insured, "template": template,
            "application": application, "policy": policy}


def get_policy(policy_id):
    return get_success_data(api_client.get_policy(policy_id, AGENT))


def list_ledger(policy_id):
    return get_success_data(api_client.list_policy_cash_value_ledger(policy_id, AGENT))


# ---------------------------------------------------------------------------
# Tier 3: cash-value funding via premium payments (PRD §3.4: every premium
# posting writes a PREMIUM_CREDIT ledger entry for the amount paid)
# ---------------------------------------------------------------------------

def add_cash(bundle, amount_cents):
    """Record a premium payment and return the refreshed policy."""
    policy_id = bundle["policy"]["id"]
    get_success_data(api_client.record_premium_payment(policy_id, amount_cents, AGENT))
    return get_policy(policy_id)


def create_funded_policy(cash_to_add, **cfg):
    """Issued policy whose cash value has been credited by an extra payment."""
    bundle = create_issued_policy(**cfg)
    bundle["policy"] = add_cash(bundle, cash_to_add)
    return bundle


# ---------------------------------------------------------------------------
# Tier 3b: loans
# ---------------------------------------------------------------------------

def originate_loan(bundle, requested_amount_cents):
    """Originate a loan as the policyholder (ownership-gated: insured id)."""
    policy_id = bundle["policy"]["id"]
    headers = make_policyholder_headers(bundle["insured"]["id"])
    return get_success_data(api_client.create_loan(policy_id, requested_amount_cents, headers))


def create_policy_with_loan(loan_amount, cash_to_add=10_000_000, **cfg):
    """Funded policy plus one ACTIVE loan. Returns (bundle, loan)."""
    bundle = create_funded_policy(cash_to_add, **cfg)
    loan = originate_loan(bundle, loan_amount)
    return bundle, loan


# ---------------------------------------------------------------------------
# Tier 4: lapse / grace / reinstatement scenarios
# ---------------------------------------------------------------------------

def lapse_policy(bundle, lapse_days_after_issue=200):
    """Advance the clock far past the grace period so the policy lapses.

    200 days after issue exceeds (first unpaid cycle end + 31 grace days)
    for a MONTHLY policy under any reasonable cycle-creation model.
    Returns the refreshed policy."""
    policy_id = bundle["policy"]["id"]
    target = add_days(bundle["policy"]["issue_date"], lapse_days_after_issue)
    set_clock(target)
    return get_policy(policy_id)


def create_lapsed_policy(**cfg):
    """MONTHLY policy, no extra premium paid, lapsed by clock advance.

    Cash value stays minimal (the initial modal premium only), so the
    automatic EXTENDED_TERM election at lapse cannot cover one month's
    cost and is rejected — form_status remains IN_FORCE (PRD §3.4, §3.8).
    """
    cfg.setdefault("premium_mode", "MONTHLY")
    bundle = create_issued_policy(**cfg)
    bundle["policy"] = lapse_policy(bundle)
    return bundle


def create_reinstatement_request(bundle):
    policy_id = bundle["policy"]["id"]
    return get_success_data(api_client.create_reinstatement_request(policy_id, AGENT))


def complete_reinstatement(bundle, request_id,
                           underwriter_user_id="uw-reinstate-1",
                           payment_amount_cents=999_999_999):
    """Drive a reinstatement request through evidence + payment + approval."""
    policy_id = bundle["policy"]["id"]
    uw = {"X-User-ID": underwriter_user_id, "X-User-Role": "Underwriter",
          "Content-Type": "application/json"}
    get_success_data(api_client.request_reinstatement_evidence(policy_id, request_id, uw))
    get_success_data(api_client.submit_reinstatement_evidence(policy_id, request_id, AGENT))
    get_success_data(api_client.pay_reinstatement(policy_id, request_id,
                                                  payment_amount_cents, AGENT))
    return get_success_data(api_client.approve_reinstatement(policy_id, request_id, uw))


# ---------------------------------------------------------------------------
# Tier 5: riders / conversion helpers
# ---------------------------------------------------------------------------

def add_rider(bundle, rider_type="ACCIDENTAL_DEATH_BENEFIT", rider_face_amount_cents=1_000_000):
    policy_id = bundle["policy"]["id"]
    return get_success_data(
        api_client.create_rider(policy_id, rider_type, rider_face_amount_cents, AGENT))


def create_term_convertible_policy(**cfg):
    """Issued TERM_CONVERTIBLE source policy plus a whole-life target template."""
    cfg.setdefault("product_type", "TERM_CONVERTIBLE")
    cfg.setdefault("allows_policy_loans", False)
    cfg.setdefault("base_rate", 20)
    bundle = create_issued_policy(**cfg)
    target = create_template(product_type="WHOLE_LIFE_NON_PARTICIPATING")
    bundle["target_template"] = target
    return bundle
