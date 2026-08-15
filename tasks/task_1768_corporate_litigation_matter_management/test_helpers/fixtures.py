"""Composite setup helpers.

The interesting claims in this PRD all require deep preconditions: an ACTIVE
matter needs an APPROVED budget and an ACTIVE engagement; a work-order
authorize needs an ISSUED hold on top of that; a settlement execution needs
a staged FINANCE_APPROVED payment on a SETTLEMENT_PENDING matter. These
helpers build those chains once so tests can assert, not plumb.

Every helper builds its state from scratch (the server restarts before every
test) using only PRD-declared endpoints, and returns a context dict carrying
both entity ids and identity-bound headers for each staff user.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, TIER1_EXPOSURE
from .factories import (
    create_accrual_entry_payload, create_budget_payload,
    create_counsel_firm_payload, create_deadline_payload,
    create_engagement_payload, create_hold_payload, create_matter_payload,
    create_policy_payload, create_settlement_request_payload,
    create_payment_request_payload, create_staff_user_payload,
    create_vendor_payload, create_work_order_payload,
)
from .test_users import (
    TEST_USERS, make_counsel_headers, make_dgc_headers, make_fin_headers,
    make_gc_headers, make_staff_headers,
)

OPS = TEST_USERS["ops_headers"]


# ----------------------------------------------------------------------
# Atomic creators
# ----------------------------------------------------------------------

def create_staff_user(full_name, email, job_family):
    resp = api_client.create_staff_user(
        create_staff_user_payload(full_name=full_name, email=email,
                                  job_family=job_family), OPS)
    return get_success_data(resp)


def create_matter(counsel_id, *, with_exposure=True, exposure=TIER1_EXPOSURE,
                  **overrides):
    payload_kwargs = dict(owning_counsel_id=counsel_id)
    payload_kwargs.update(overrides)
    if with_exposure:
        low, high, prob = exposure
        payload_kwargs.setdefault("exposure_low_cents", low)
        payload_kwargs.setdefault("exposure_high_cents", high)
        payload_kwargs.setdefault("probability_of_loss_pct", prob)
    resp = api_client.create_matter(create_matter_payload(**payload_kwargs),
                                    make_counsel_headers(counsel_id))
    return get_success_data(resp)


def fresh_matter_version(matter_id, read_headers):
    """Re-read the matter and return its current version (OCC chains)."""
    return get_success_data(api_client.get_matter(matter_id, read_headers))["version"]


def create_deadline(matter_id, counsel_id, **overrides):
    resp = api_client.create_deadline(
        matter_id, create_deadline_payload(**overrides),
        make_counsel_headers(counsel_id))
    return get_success_data(resp)


def create_approved_budget(matter_id, counsel_id, fin_id, *,
                           fy_budget_cents=TEST_DEFAULTS["FY_BUDGET_CENTS"],
                           lifecycle_budget_cents=TEST_DEFAULTS["LIFECYCLE_BUDGET_CENTS"],
                           prior_version_id=None):
    """Create (version-guarded) -> submit -> approve. Returns the APPROVED budget."""
    version = fresh_matter_version(matter_id, make_counsel_headers(counsel_id))
    payload = create_budget_payload(
        fiscal_year=TEST_DEFAULTS["FISCAL_YEAR"],
        lifecycle_budget_cents=lifecycle_budget_cents,
        fy_budget_cents=fy_budget_cents,
        expected_matter_version=version,
    )
    if prior_version_id is not None:
        payload["prior_version_id"] = prior_version_id
    budget = get_success_data(
        api_client.create_budget(matter_id, payload, make_counsel_headers(counsel_id)))
    get_success_data(api_client.submit_budget(budget["id"], make_counsel_headers(counsel_id)))
    return get_success_data(
        api_client.approve_budget(budget["id"], make_fin_headers(fin_id)))


def create_approved_firm(gc_id, *, firm_name="Outside LLP",
                         rate_cap_cents=TEST_DEFAULTS["RATE_CAP_CENTS"],
                         conflict_result="CLEARED"):
    """Register -> conflict-check -> approve-panel. Returns the APPROVED firm."""
    firm = get_success_data(api_client.create_counsel_firm(
        create_counsel_firm_payload(firm_name=firm_name,
                                    blended_rate_cap_cents=rate_cap_cents), OPS))
    get_success_data(api_client.conflict_check_firm(firm["id"], conflict_result, OPS))
    return get_success_data(
        api_client.approve_panel_firm(firm["id"], make_gc_headers(gc_id)))


def create_active_engagement(matter_id, firm_id, counsel_id, dgc_id, *,
                             role_type="LEAD_COUNSEL", fee_arrangement="HOURLY",
                             proposed_rate_cents=TEST_DEFAULTS["PROPOSED_RATE_CENTS"],
                             engagement_letter_executed=True,
                             supersedes_engagement_id=None):
    """Propose -> approve (DGC) -> activate (owner). Returns the ACTIVE engagement."""
    payload = create_engagement_payload(
        firm_id=firm_id, role_type=role_type, fee_arrangement=fee_arrangement,
        proposed_rate_cents=proposed_rate_cents,
        engagement_letter_executed=engagement_letter_executed,
    )
    if supersedes_engagement_id is not None:
        payload["supersedes_engagement_id"] = supersedes_engagement_id
    engagement = get_success_data(api_client.create_engagement(
        matter_id, payload, make_counsel_headers(counsel_id)))
    get_success_data(
        api_client.approve_engagement(engagement["id"], make_dgc_headers(dgc_id)))
    return get_success_data(api_client.activate_engagement(
        engagement["id"], make_counsel_headers(counsel_id)))


# ----------------------------------------------------------------------
# Tier 2: canonical matter chains
# ----------------------------------------------------------------------

def make_staff_quartet(prefix=""):
    """counsel (LEGAL), dgc (EXECUTIVE), fin (FINANCE), gc (EXECUTIVE)."""
    counsel = create_staff_user(f"{prefix}Casey Counsel",
                                f"{prefix}casey@corp.example", "LEGAL")
    dgc = create_staff_user(f"{prefix}Dana Deputy",
                            f"{prefix}dana@corp.example", "EXECUTIVE")
    fin = create_staff_user(f"{prefix}Fin Finance",
                            f"{prefix}fin@corp.example", "FINANCE")
    gc = create_staff_user(f"{prefix}Gena Counsel",
                           f"{prefix}gena@corp.example", "EXECUTIVE")
    return {
        "counsel_id": counsel["id"],
        "dgc_id": dgc["id"],
        "fin_id": fin["id"],
        "gc_id": gc["id"],
        "counsel": make_counsel_headers(counsel["id"]),
        "dgc": make_dgc_headers(dgc["id"]),
        "fin": make_fin_headers(fin["id"]),
        "gc": make_gc_headers(gc["id"]),
        "custodian_self": make_staff_headers(counsel["id"]),
        "ops": OPS,
    }


def setup_staffing_matter(*, with_exposure=True, exposure=TIER1_EXPOSURE,
                          matter_type="COMMERCIAL", staff=None,
                          deadline_type="INTERNAL_REVIEW",
                          deadline_due_at=TEST_DEFAULTS["DEADLINE_DUE"],
                          deadline_is_jurisdictional=None):
    """Matter walked INTAKE -> ASSESSMENT -> STAFFING (calendar seeded).

    Returns ctx with staff quartet + matter. No budget, firm, or engagement.
    """
    ctx = staff or make_staff_quartet()
    matter = create_matter(ctx["counsel_id"], with_exposure=with_exposure,
                           exposure=exposure, matter_type=matter_type)
    ctx["matter"] = matter
    ctx["matter_id"] = matter["id"]
    get_success_data(api_client.submit_assessment(ctx["matter_id"], ctx["counsel"]))
    dl_kwargs = {"deadline_type": deadline_type, "due_at": deadline_due_at}
    if deadline_is_jurisdictional is not None:
        dl_kwargs["is_jurisdictional"] = deadline_is_jurisdictional
    ctx["deadline"] = create_deadline(ctx["matter_id"], ctx["counsel_id"], **dl_kwargs)
    get_success_data(api_client.advance_to_staffing(ctx["matter_id"], ctx["counsel"]))
    return ctx


def setup_active_matter(*, exposure=TIER1_EXPOSURE, matter_type="COMMERCIAL",
                        fy_budget_cents=TEST_DEFAULTS["FY_BUDGET_CENTS"],
                        lifecycle_budget_cents=TEST_DEFAULTS["LIFECYCLE_BUDGET_CENTS"],
                        rate_cap_cents=TEST_DEFAULTS["RATE_CAP_CENTS"],
                        proposed_rate_cents=TEST_DEFAULTS["PROPOSED_RATE_CENTS"],
                        role_type="LEAD_COUNSEL", fee_arrangement="HOURLY",
                        staff=None, deadline_type="INTERNAL_REVIEW",
                        deadline_due_at=TEST_DEFAULTS["DEADLINE_DUE"],
                        deadline_is_jurisdictional=None,
                        second_engagement=False):
    """Full canonical chain: STAFFING matter + APPROVED budget + APPROVED firm
    + ACTIVE engagement + matter ACTIVE. Returns the rich ctx dict."""
    ctx = setup_staffing_matter(
        exposure=exposure, matter_type=matter_type, staff=staff,
        deadline_type=deadline_type, deadline_due_at=deadline_due_at,
        deadline_is_jurisdictional=deadline_is_jurisdictional)
    ctx["budget"] = create_approved_budget(
        ctx["matter_id"], ctx["counsel_id"], ctx["fin_id"],
        fy_budget_cents=fy_budget_cents,
        lifecycle_budget_cents=lifecycle_budget_cents)
    ctx["budget_id"] = ctx["budget"]["id"]
    ctx["firm"] = create_approved_firm(ctx["gc_id"], rate_cap_cents=rate_cap_cents)
    ctx["firm_id"] = ctx["firm"]["id"]
    ctx["engagement"] = create_active_engagement(
        ctx["matter_id"], ctx["firm_id"], ctx["counsel_id"], ctx["dgc_id"],
        role_type=role_type, fee_arrangement=fee_arrangement,
        proposed_rate_cents=proposed_rate_cents)
    ctx["engagement_id"] = ctx["engagement"]["id"]
    if second_engagement:
        ctx["engagement2"] = create_active_engagement(
            ctx["matter_id"], ctx["firm_id"], ctx["counsel_id"], ctx["dgc_id"],
            role_type="CO_COUNSEL", fee_arrangement=fee_arrangement,
            proposed_rate_cents=min(proposed_rate_cents, 70_000))
        ctx["engagement2_id"] = ctx["engagement2"]["id"]
    get_success_data(api_client.activate_matter(ctx["matter_id"], ctx["counsel"]))
    ctx["matter"] = get_success_data(api_client.get_matter(ctx["matter_id"], ctx["counsel"]))
    return ctx


# ----------------------------------------------------------------------
# Tier 2b: holds, custodians, vendors, work orders
# ----------------------------------------------------------------------

def add_hold(ctx, *, custodian_user_id=None, issue=False, acknowledge=False):
    """Create a hold on ctx's matter with one custodian; optionally issue it
    and have the custodian self-acknowledge. Returns (hold, custodian)."""
    hold = get_success_data(api_client.create_hold(
        ctx["matter_id"], create_hold_payload(), ctx["counsel"]))
    custodian_id = custodian_user_id if custodian_user_id is not None else ctx["counsel_id"]
    custodian = get_success_data(api_client.add_custodian(
        hold["id"], custodian_id, ctx["counsel"]))
    if issue or acknowledge:
        hold = get_success_data(api_client.issue_hold(hold["id"], ctx["counsel"]))
    if acknowledge:
        custodian = get_success_data(api_client.acknowledge_custodian(
            custodian["id"], make_staff_headers(custodian_id)))
        hold = get_success_data(api_client.get_hold(hold["id"], ctx["counsel"]))
    return hold, custodian


def add_vendor(ctx, *, capacity_gb=1000, clearance="RESTRICTED",
               vendor_name="DiscCo"):
    vendor = get_success_data(api_client.create_vendor(
        create_vendor_payload(vendor_name=vendor_name,
                              security_clearance_level=clearance,
                              capacity_gb=capacity_gb), OPS))
    return vendor


def create_work_order(ctx, vendor_id, hold_id, **overrides):
    payload_kwargs = {"vendor_id": vendor_id, "hold_id": hold_id}
    payload_kwargs.update(overrides)
    return get_success_data(api_client.create_work_order(
        ctx["matter_id"], create_work_order_payload(**payload_kwargs), OPS))


def create_and_authorize_work_order(ctx, vendor_id, hold_id, **overrides):
    wo = create_work_order(ctx, vendor_id, hold_id, **overrides)
    return get_success_data(api_client.authorize_work_order(wo["id"], OPS))


# ----------------------------------------------------------------------
# Tier 3: accrual lifecycle
# ----------------------------------------------------------------------

def create_accrual(ctx, engagement_id=None, **overrides):
    payload_kwargs = {"engagement_id": engagement_id or ctx["engagement_id"]}
    payload_kwargs.update(overrides)
    return get_success_data(api_client.create_accrual_entry(
        ctx["matter_id"], create_accrual_entry_payload(**payload_kwargs),
        ctx["counsel"]))


def create_submitted_accrual(ctx, engagement_id=None, **overrides):
    entry = create_accrual(ctx, engagement_id=engagement_id, **overrides)
    return get_success_data(api_client.submit_accrual_entry(entry["id"], ctx["counsel"]))


def create_posted_accrual(ctx, engagement_id=None, **overrides):
    entry = create_submitted_accrual(ctx, engagement_id=engagement_id, **overrides)
    return get_success_data(api_client.post_accrual_entry(entry["id"], ctx["fin"]))


# ----------------------------------------------------------------------
# Tier 4: settlement authority + negotiation lifecycle
# ----------------------------------------------------------------------

def create_tier2_policy(ctx, *, approver_role="GeneralCounsel",
                        max_single_amount_cents=10_000_000,
                        dual_approval_required_over_cents=50_000_000):
    return get_success_data(api_client.create_policy(
        create_policy_payload(
            tier="TIER_2", approver_role=approver_role,
            max_single_amount_cents=max_single_amount_cents,
            dual_approval_required_over_cents=dual_approval_required_over_cents),
        ctx["gc"]))


def create_settlement_request(ctx, *, proposed_amount_cents=5_000_000,
                              settlement_kind="PAY_OUT",
                              expires_at=TEST_DEFAULTS["SETTLEMENT_EXPIRES_AT"]):
    """Create (version-guarded on the matter) a DRAFT settlement request."""
    version = fresh_matter_version(ctx["matter_id"], ctx["counsel"])
    payload = create_settlement_request_payload(
        proposed_amount_cents=proposed_amount_cents,
        settlement_kind=settlement_kind, expires_at=expires_at,
        expected_matter_version=version)
    sr = get_success_data(
        api_client.create_settlement_request(ctx["matter_id"], payload, ctx["counsel"]))
    ctx["sr"] = sr
    ctx["sr_id"] = sr["id"]
    return sr


def create_settlement_under_review(ctx, *, proposed_amount_cents=5_000_000,
                                   expires_at=TEST_DEFAULTS["SETTLEMENT_EXPIRES_AT"]):
    """DRAFT -> SUBMITTED (tier snapshot) -> UNDER_REVIEW."""
    sr = create_settlement_request(
        ctx, proposed_amount_cents=proposed_amount_cents, expires_at=expires_at)
    get_success_data(api_client.submit_settlement(sr["id"], ctx["counsel"]))
    return get_success_data(api_client.begin_review_settlement(sr["id"], ctx["dgc"]))


def setup_settlement_pending_matter(*, exposure, matter_type="COMMERCIAL",
                                    proposed_amount_cents=5_000_000,
                                    policy_kwargs=None):
    """ACTIVE TIER-matched matter + policy + fully-approved settlement.

    Single-approval path: the completing approval moves the matter to
    SETTLEMENT_PENDING (suspending the engagement). Returns ctx.
    """
    ctx = setup_active_matter(exposure=exposure, matter_type=matter_type)
    create_tier2_policy(ctx, **(policy_kwargs or {}))
    create_settlement_under_review(
        ctx, proposed_amount_cents=proposed_amount_cents)
    sr = get_success_data(api_client.approve_settlement(ctx["sr_id"], ctx["gc"]))
    ctx["sr"] = sr
    ctx["matter"] = get_success_data(api_client.get_matter(ctx["matter_id"], ctx["counsel"]))
    return ctx


# ----------------------------------------------------------------------
# Tier 5: resolution and payments
# ----------------------------------------------------------------------

def setup_resolved_judgment_matter(*, exposure=TIER1_EXPOSURE,
                                   fy_budget_cents=TEST_DEFAULTS["FY_BUDGET_CENTS"]):
    """ACTIVE matter resolved directly with resolution_type JUDGMENT."""
    ctx = setup_active_matter(exposure=exposure, fy_budget_cents=fy_budget_cents)
    get_success_data(api_client.resolve_matter(ctx["matter_id"], "JUDGMENT", ctx["counsel"]))
    ctx["matter"] = get_success_data(api_client.get_matter(ctx["matter_id"], ctx["counsel"]))
    return ctx


def create_submitted_payment(ctx, *, payment_kind="JUDGMENT", amount_cents=7_000_000,
                             payee_name="Acme Corp", settlement_request_id=None):
    payload = create_payment_request_payload(
        payment_kind=payment_kind, amount_cents=amount_cents, payee_name=payee_name)
    if settlement_request_id is not None:
        payload["settlement_request_id"] = settlement_request_id
    payment = get_success_data(api_client.create_payment_request(
        ctx["matter_id"], payload, ctx["counsel"]))
    return get_success_data(api_client.submit_payment(payment["id"], ctx["counsel"]))


def create_finance_approved_payment(ctx, **kwargs):
    payment = create_submitted_payment(ctx, **kwargs)
    return get_success_data(
        api_client.finance_approve_payment(payment["id"], ctx["fin"]))


def setup_disbursed_payment(ctx=None, *, amount_cents=7_000_000, **kwargs):
    """RESOLVED (JUDGMENT) matter with a DISBURSED payment (rail SENT)."""
    if ctx is None:
        ctx = setup_resolved_judgment_matter()
    payment = create_finance_approved_payment(
        ctx, payment_kind="JUDGMENT", amount_cents=amount_cents, **kwargs)
    return ctx, get_success_data(api_client.disburse_payment(payment["id"], ctx["fin"]))
