"""Composite setup helpers.

The interesting claims in this PRD require a guarantee to be walked through a long
lifecycle (quote -> approve -> pay fee -> agreement sign/countersign -> activate,
and onward to claims and recovery). These helpers encapsulate those chains so
tests focus on assertions. All setup uses get_success_data() (lenient) so a broken
precondition surfaces as a clear "Setup failed".

Because the harness restarts the server (empty DB) before every test, every helper
builds its own preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_portfolio_payload, create_applicant_payload, create_landlord_payload,
    create_guarantee_payload, create_agreement_payload, create_claim_payload,
    pay_fee_payload, create_compliance_review_payload, create_installment_payload,
)
from .test_users import (
    TEST_USERS, UW1, CA1, CO1, RA1,
    make_underwriter_headers, make_claims_adjuster_headers,
    make_compliance_officer_headers, make_landlord_headers, make_applicant_headers,
    make_recovery_agent_headers,
)
from .constants import STD_FINAL_FEE_CENTS_TIER_A

DEFAULT_CLOCK = "2026-09-15T00:00:00Z"

_ADMIN = TEST_USERS["platform_admin_headers"]


def _u(overrides):
    return dict(overrides or {})


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def set_clock(api, iso: str = DEFAULT_CLOCK) -> None:
    """Advance the server logical clock (PRD §2.10)."""
    get_success_data(api.set_clock(iso, _ADMIN))


def create_portfolio(api, **overrides) -> dict:
    return get_success_data(api.create_portfolio(create_portfolio_payload(**overrides), _ADMIN))


def create_landlord(api, **overrides) -> dict:
    return get_success_data(api.create_landlord(create_landlord_payload(**overrides), _ADMIN))


def create_applicant(api, **overrides) -> dict:
    """Create a DRAFT applicant (registered by an Underwriter)."""
    return get_success_data(
        api.create_applicant(create_applicant_payload(**overrides),
                             TEST_USERS["underwriter_headers"]))


def create_verified_applicant(api, **overrides) -> dict:
    """Create then verify an applicant. Returns the VERIFIED applicant."""
    ap = create_applicant(api, **overrides)
    return get_success_data(
        api.verify_applicant(ap["id"], TEST_USERS["underwriter_headers"]))


def create_quoted_guarantee(api, portfolio_id: str, applicant_id: str,
                            uw_id: str = UW1, **overrides) -> dict:
    return get_success_data(
        api.create_guarantee(create_guarantee_payload(portfolio_id, applicant_id, **overrides),
                             make_underwriter_headers(uw_id)))


# ---------------------------------------------------------------------------
# Guarantee lifecycle composites
# ---------------------------------------------------------------------------
def setup_quoted_guarantee(api, *, portfolio_overrides=None, applicant_overrides=None,
                           guarantee_overrides=None, verify=True, uw_id=UW1) -> dict:
    """Portfolio + (verified) applicant + QUOTED guarantee.

    Returns a context dict with portfolio / applicant / guarantee data and ids.
    """
    portfolio = create_portfolio(api, **_u(portfolio_overrides))
    if verify:
        applicant = create_verified_applicant(api, **_u(applicant_overrides))
    else:
        applicant = create_applicant(api, **_u(applicant_overrides))
    guarantee = create_quoted_guarantee(api, portfolio["id"], applicant["id"],
                                        uw_id=uw_id, **_u(guarantee_overrides))
    return {
        "portfolio": portfolio, "applicant": applicant, "guarantee": guarantee,
        "pf_id": portfolio["id"], "ap_id": applicant["id"], "g_id": guarantee["id"],
        "unit_id": guarantee["unit_id"], "uw_id": uw_id,
    }


def setup_approved_guarantee(api, *, portfolio_overrides=None, applicant_overrides=None,
                             guarantee_overrides=None, uw_id=UW1) -> dict:
    """QUOTED -> APPROVED. Returns context with the approved guarantee."""
    ctx = setup_quoted_guarantee(api, portfolio_overrides=portfolio_overrides,
                                 applicant_overrides=applicant_overrides,
                                 guarantee_overrides=guarantee_overrides,
                                 verify=True, uw_id=uw_id)
    ctx["guarantee"] = get_success_data(
        api.approve_guarantee(ctx["g_id"], make_underwriter_headers(uw_id)))
    return ctx


def setup_active_guarantee(api, *, clock=DEFAULT_CLOCK, portfolio_overrides=None,
                           applicant_overrides=None, guarantee_overrides=None,
                           landlord_overrides=None, agreement_overrides=None,
                           fee_amount=STD_FINAL_FEE_CENTS_TIER_A, uw_id=UW1) -> dict:
    """Full chain: set clock -> portfolio + landlord + verified applicant ->
    QUOTED guarantee -> approve -> pay fee -> agreement create/sign/countersign ->
    activate. Returns context with the ACTIVE guarantee and its post-activation
    version.
    """
    if clock is not None:
        set_clock(api, clock)
    ctx = setup_approved_guarantee(api, portfolio_overrides=portfolio_overrides,
                                   applicant_overrides=applicant_overrides,
                                   guarantee_overrides=guarantee_overrides, uw_id=uw_id)
    landlord = create_landlord(api, **_u(landlord_overrides))
    ctx["landlord"] = landlord
    ctx["ll_id"] = landlord["id"]

    ll_headers = make_landlord_headers(landlord["id"])
    ap_headers = make_applicant_headers(ctx["ap_id"])
    uw_headers = make_underwriter_headers(uw_id)

    # Collect the fee.
    get_success_data(api.pay_fee(ctx["g_id"], pay_fee_payload(fee_amount), ap_headers))

    # Agreement: window and unit default to the guarantee's own.
    guarantee = ctx["guarantee"]
    ag_defaults = {
        "coverage_start_date": guarantee["lease_start_date"],
        "coverage_end_date": guarantee["lease_end_date"],
    }
    ag_defaults.update(_u(agreement_overrides))
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(ctx["g_id"], landlord["id"], ctx["unit_id"], **ag_defaults),
        ll_headers))
    get_success_data(api.sign_agreement(agreement["id"], ll_headers))
    get_success_data(api.countersign_agreement(agreement["id"], uw_headers))
    ctx["agreement"] = agreement
    ctx["ag_id"] = agreement["id"]

    # Activate.
    activated = get_success_data(api.activate_guarantee(ctx["g_id"], uw_headers))
    ctx["guarantee"] = activated
    ctx["g_version"] = activated["version"]
    return ctx


def setup_preactivation(api, *, clock=DEFAULT_CLOCK, pay_fee=True, countersign=True,
                        portfolio_overrides=None, applicant_overrides=None,
                        guarantee_overrides=None, landlord_overrides=None,
                        agreement_overrides=None, fee_amount=STD_FINAL_FEE_CENTS_TIER_A,
                        uw_id=UW1) -> dict:
    """Approved guarantee + landlord + agreement created & signed, optionally fee-paid
    and optionally countersigned (agreement ACTIVE) — but NOT activated. Lets a test
    knock out exactly one activation precondition.
    """
    if clock is not None:
        set_clock(api, clock)
    ctx = setup_approved_guarantee(api, portfolio_overrides=portfolio_overrides,
                                   applicant_overrides=applicant_overrides,
                                   guarantee_overrides=guarantee_overrides, uw_id=uw_id)
    landlord = create_landlord(api, **_u(landlord_overrides))
    ctx["landlord"] = landlord
    ctx["ll_id"] = landlord["id"]
    ll_headers = make_landlord_headers(landlord["id"])
    ap_headers = make_applicant_headers(ctx["ap_id"])
    uw_headers = make_underwriter_headers(uw_id)

    if pay_fee:
        get_success_data(api.pay_fee(ctx["g_id"], pay_fee_payload(fee_amount), ap_headers))

    guarantee = ctx["guarantee"]
    ag_defaults = {
        "coverage_start_date": guarantee["lease_start_date"],
        "coverage_end_date": guarantee["lease_end_date"],
    }
    ag_defaults.update(_u(agreement_overrides))
    agreement = get_success_data(api.create_agreement(
        create_agreement_payload(ctx["g_id"], landlord["id"], ctx["unit_id"], **ag_defaults),
        ll_headers))
    get_success_data(api.sign_agreement(agreement["id"], ll_headers))
    if countersign:
        get_success_data(api.countersign_agreement(agreement["id"], uw_headers))
    ctx["agreement"] = agreement
    ctx["ag_id"] = agreement["id"]
    return ctx


def file_claim(api, ctx, *, missed_months=5, acceleration_requested=False,
               default_date="2026-09-01T00:00:00Z", expected_version=None) -> dict:
    """File a claim as the guarantee's bound landlord. Returns the SUBMITTED claim."""
    version = ctx["g_version"] if expected_version is None else expected_version
    payload = create_claim_payload(version, missed_months=missed_months,
                                   acceleration_requested=acceleration_requested,
                                   default_date=default_date)
    return get_success_data(
        api.create_claim(ctx["g_id"], payload, make_landlord_headers(ctx["ll_id"])))


def setup_active_guarantee_with_claim(api, *, missed_months=5, acceleration_requested=False,
                                      default_date="2026-09-01T00:00:00Z", **kwargs) -> dict:
    """Active guarantee + one SUBMITTED claim. Adds 'claim' / 'cl_id' to the context."""
    ctx = setup_active_guarantee(api, **kwargs)
    claim = file_claim(api, ctx, missed_months=missed_months,
                       acceleration_requested=acceleration_requested, default_date=default_date)
    ctx["claim"] = claim
    ctx["cl_id"] = claim["id"]
    return ctx


def setup_reviewed_claim(api, *, adjuster_id=CA1, **kwargs) -> dict:
    """Active guarantee + a claim moved to UNDER_REVIEW by an adjuster."""
    ctx = setup_active_guarantee_with_claim(api, **kwargs)
    ctx["claim"] = get_success_data(
        api.review_claim(ctx["cl_id"], make_claims_adjuster_headers(adjuster_id)))
    return ctx


def setup_paid_claim(api, *, adjuster_id=CA1, missed_months=5, acceleration_requested=False,
                     **kwargs) -> dict:
    """Active guarantee + a claim reviewed and APPROVED (auto-PAID) by an adjuster,
    with the resulting RecoveryPlan fetched. Adds 'claim' and 'recovery_plan' to ctx.
    """
    ctx = setup_reviewed_claim(api, adjuster_id=adjuster_id, missed_months=missed_months,
                               acceleration_requested=acceleration_requested, **kwargs)
    ctx["claim"] = get_success_data(
        api.approve_claim(ctx["cl_id"], make_claims_adjuster_headers(adjuster_id)))
    plans, _meta = _list_recovery_plans_for_claim(api, ctx["cl_id"])
    ctx["recovery_plan"] = plans[0] if plans else None
    if ctx["recovery_plan"]:
        ctx["rp_id"] = ctx["recovery_plan"]["id"]
    return ctx


def _list_recovery_plans_for_claim(api, claim_id):
    resp = api.list_recovery_plans(TEST_USERS["recovery_agent_headers"],
                                   params={"claim_id": claim_id})
    body = resp.json()
    meta = body.get("meta", {})
    return body.get("data", []), meta


# ---------------------------------------------------------------------------
# Compliance / recovery helpers
# ---------------------------------------------------------------------------
def open_compliance_review(api, guarantee_id, *, reason="KYC_MISMATCH", officer_id=CO1) -> dict:
    """Open a ComplianceReview against a guarantee (records opened_by_user_id)."""
    return get_success_data(api.create_compliance_review(
        create_compliance_review_payload(guarantee_id, reason=reason),
        make_compliance_officer_headers(officer_id)))


def post_installment(api, plan_id, amount_cents, *, agent_id=RA1) -> dict:
    """Record a RecoveryInstallment against an ACTIVE plan (RecoveryAgent)."""
    return get_success_data(api.create_installment(
        plan_id, create_installment_payload(amount_cents),
        make_recovery_agent_headers(agent_id)))
