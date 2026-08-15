"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All roles use opaque operator identities; the
segregation-of-duties-sensitive steps thread explicit X-User-ID values via the
make_* builders so a submitter and an approver never share an identity.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_deal_payload,
    create_environmental_assessment_payload,
    create_estoppel_payload,
    create_financing_application_payload,
    create_lease_payload,
    create_pca_payload,
    create_property_payload,
    create_psa_payload,
    create_snda_payload,
    create_tenant_payload,
    create_title_review_payload,
    create_true_up_payload,
    create_underwriting_model_payload,
    issue_statement_payload,
    proration_line,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_asset_manager_headers,
    make_committee_headers,
    make_dd_officer_headers,
    make_escrow_headers,
)

ANALYST = TEST_USERS["analyst_headers"]
COMMITTEE = TEST_USERS["committee_headers"]
DD_OFFICER = TEST_USERS["dd_officer_headers"]
CMO = TEST_USERS["capital_markets_headers"]
ESCROW = TEST_USERS["escrow_headers"]
ASSET_MANAGER = TEST_USERS["asset_manager_headers"]
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]

# Fixed actor identities used when a workflow compares X-User-ID values
# (segregation of duties): the originating and approving actors must differ.
MODEL_SUBMITTER = make_analyst_headers("analyst-model-submitter")
MODEL_APPROVER = make_committee_headers("committee-model-approver")
STMT_ISSUER = make_escrow_headers("escrow-issuer-1")
STMT_ACKNOWLEDGER = make_analyst_headers("analyst-acknowledger-1")
TRUEUP_PROPOSER = make_asset_manager_headers("am-proposer-1")
TRUEUP_AM_APPROVER = make_asset_manager_headers("am-approver-1")

DEFAULT_CLOSING_DATE = "2026-09-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and small transitions
# ---------------------------------------------------------------------------

def set_clock(to_iso8601="2026-08-01T00:00:00Z"):
    return get_success_data(api_client.set_clock(to_iso8601, PLATFORM_ADMIN))


def create_deal(deal_name="Test Deal", deal_type="SINGLE_TENANT",
                target_close_date="2026-10-01T00:00:00Z",
                earnest_money_cents=250000, purchase_price_cents=15000000,
                sourcing_channel=None):
    """Create a deal (born SOURCING / posture SOURCING). Returns the deal."""
    payload = create_deal_payload(
        deal_name=deal_name, deal_type=deal_type,
        target_close_date=target_close_date,
        earnest_money_cents=earnest_money_cents,
        purchase_price_cents=purchase_price_cents)
    if sourcing_channel is not None:
        payload["sourcing_channel"] = sourcing_channel
    return get_success_data(api_client.create_deal(payload, ANALYST))


def get_deal(deal_id):
    return get_success_data(api_client.get_deal(deal_id, ANALYST))


def create_tenant(legal_name="Test Tenant LLC",
                  credit_rating="INVESTMENT_GRADE", credit_score=800,
                  annual_revenue_cents=100000000, is_guaranteed=True):
    """Create a tenant (credit PENDING). Returns the tenant."""
    payload = create_tenant_payload(
        legal_name=legal_name, credit_rating=credit_rating,
        credit_score=credit_score, annual_revenue_cents=annual_revenue_cents,
        is_guaranteed=is_guaranteed)
    return get_success_data(api_client.create_tenant(payload, ANALYST))


def analyze_tenant(tenant_id):
    return get_success_data(api_client.analyze_credit(tenant_id, COMMITTEE))


def approve_tenant(tenant_id):
    return get_success_data(api_client.approve_credit(tenant_id, COMMITTEE))


def create_approved_tenant(**kwargs):
    """Create a tenant and walk credit PENDING -> ANALYZED -> APPROVED."""
    tenant = create_tenant(**kwargs)
    analyze_tenant(tenant["id"])
    return approve_tenant(tenant["id"])


def add_property(deal_id, address="1 Test St", property_type="RETAIL",
                 rentable_sqft=5000, year_built=2010):
    payload = create_property_payload(
        address=address, property_type=property_type,
        rentable_sqft=rentable_sqft, year_built=year_built)
    return get_success_data(
        api_client.create_property(deal_id, payload, ANALYST))


def add_lease(deal_id, property_id, tenant_id, lease_type="NNN",
              annual_base_rent_cents=1000000,
              lease_commencement_date="2020-01-01T00:00:00Z",
              lease_expiration_date="2036-01-01T00:00:00Z",
              renewal_options_count=None):
    payload = create_lease_payload(
        tenant_id, lease_type=lease_type,
        annual_base_rent_cents=annual_base_rent_cents,
        lease_commencement_date=lease_commencement_date,
        lease_expiration_date=lease_expiration_date)
    if renewal_options_count is not None:
        payload["renewal_options_count"] = renewal_options_count
    return get_success_data(
        api_client.create_lease(deal_id, property_id, payload, ANALYST))


def verify_lease(deal_id, property_id, lease_id):
    return get_success_data(
        api_client.verify_lease(deal_id, property_id, lease_id, ANALYST))


def add_verified_lease(deal_id, property_id, tenant_id, **kwargs):
    lease = add_lease(deal_id, property_id, tenant_id, **kwargs)
    return verify_lease(deal_id, property_id, lease["id"])


def create_model(deal_id, opex_allowance_variant="CONSERVATIVE"):
    payload = create_underwriting_model_payload(
        opex_allowance_variant=opex_allowance_variant)
    return get_success_data(
        api_client.create_underwriting_model(deal_id, payload, ANALYST))


def submit_model(deal_id, model_id, submitter_headers=None):
    return get_success_data(api_client.submit_underwriting_model(
        deal_id, model_id, submitter_headers or MODEL_SUBMITTER))


def approve_model(deal_id, model_id, approver_headers=None):
    return get_success_data(api_client.approve_underwriting_model(
        deal_id, model_id, approver_headers or MODEL_APPROVER))


def create_approved_model(deal_id, opex_allowance_variant="CONSERVATIVE"):
    """Create a model and walk it DRAFT -> SUBMITTED -> APPROVED, honoring
    segregation of duties between submitter and approver."""
    model = create_model(deal_id, opex_allowance_variant)
    submit_model(deal_id, model["id"])
    return approve_model(deal_id, model["id"])


# ---------------------------------------------------------------------------
# Tier 2: deal workspaces
# ---------------------------------------------------------------------------

def setup_deal_with_approved_model(
        deal_name="Test Deal", deal_type="SINGLE_TENANT",
        target_close_date="2026-10-01T00:00:00Z",
        earnest_money_cents=250000, purchase_price_cents=15000000,
        lease_rent_cents=1000000, lease_type="NNN",
        lease_commencement="2020-01-01T00:00:00Z",
        lease_expiration="2036-01-01T00:00:00Z",
        opex_variant="CONSERVATIVE", property_overrides=None,
        tenant_overrides=None):
    """Deal + property + APPROVED tenant + VERIFIED lease + APPROVED model.

    Returns a context dict with every created resource.
    """
    deal = create_deal(deal_name=deal_name, deal_type=deal_type,
                       target_close_date=target_close_date,
                       earnest_money_cents=earnest_money_cents,
                       purchase_price_cents=purchase_price_cents)
    prop = add_property(deal["id"], **(property_overrides or {}))
    tenant = create_approved_tenant(**(tenant_overrides or {}))
    lease = add_verified_lease(
        deal["id"], prop["id"], tenant["id"], lease_type=lease_type,
        annual_base_rent_cents=lease_rent_cents,
        lease_commencement_date=lease_commencement,
        lease_expiration_date=lease_expiration)
    model = create_approved_model(deal["id"], opex_variant)
    return {"deal": deal, "property": prop, "tenant": tenant,
            "lease": lease, "model": model}


def setup_psa_pending(**kwargs):
    """setup_deal_with_approved_model + submit-for-psa (deal PSA_PENDING)."""
    ctx = setup_deal_with_approved_model(**kwargs)
    ctx["deal"] = get_success_data(
        api_client.submit_for_psa(ctx["deal"]["id"], ANALYST))
    return ctx


def create_psa(deal_id, psa_price_cents=15000000, earnest_money_cents=250000,
               dd_period_days=30, financing_contingency_days=0):
    payload = create_psa_payload(
        psa_price_cents=psa_price_cents,
        earnest_money_cents=earnest_money_cents,
        dd_period_days=dd_period_days,
        financing_contingency_days=financing_contingency_days)
    return get_success_data(
        api_client.create_purchase_agreement(deal_id, payload, ANALYST))


def execute_psa(deal_id, psa_id):
    return get_success_data(
        api_client.execute_purchase_agreement(deal_id, psa_id, ANALYST))


def setup_psa_executed(dd_period_days=30, financing_contingency_days=0,
                       psa_price_cents=None, psa_earnest_money_cents=None,
                       **kwargs):
    """Full chain through PSA execution: deal -> PSA_PENDING -> PSA_EXECUTED.

    The eight diligence milestones are auto-created at execution. Returns the
    context dict plus "psa" and "milestones".
    """
    ctx = setup_psa_pending(**kwargs)
    deal_id = ctx["deal"]["id"]
    psa = create_psa(
        deal_id,
        psa_price_cents=psa_price_cents or ctx["deal"]["purchase_price_cents"],
        earnest_money_cents=psa_earnest_money_cents
        or ctx["deal"]["earnest_money_cents"],
        dd_period_days=dd_period_days,
        financing_contingency_days=financing_contingency_days)
    ctx["psa"] = execute_psa(deal_id, psa["id"])
    ctx["deal"] = get_deal(deal_id)
    milestones, _ = validate_paginated(
        api_client.list_milestones(deal_id, DD_OFFICER,
                                   params={"limit": 100}))
    ctx["milestones"] = milestones
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: milestone helpers
# ---------------------------------------------------------------------------

def list_milestones(deal_id, params=None):
    merged = {"limit": 100}
    if params:
        merged.update(params)
    data, _ = validate_paginated(
        api_client.list_milestones(deal_id, DD_OFFICER, params=merged))
    return data


def get_milestone_by_type(deal_id, milestone_type):
    data = list_milestones(deal_id, {"milestone_type": milestone_type})
    matches = [m for m in data if m["milestone_type"] == milestone_type]
    assert matches, f"No {milestone_type} milestone found for deal {deal_id}"
    return matches[0]


def start_and_complete_milestone(deal_id, milestone_id):
    milestone = get_success_data(
        api_client.get_milestone(deal_id, milestone_id, DD_OFFICER))
    if milestone["status"] == "PENDING":
        get_success_data(
            api_client.start_milestone(deal_id, milestone_id, DD_OFFICER))
    return get_success_data(
        api_client.complete_milestone(deal_id, milestone_id, DD_OFFICER))


def complete_all_open_milestones(deal_id):
    """Manually start + complete every milestone still in PENDING or
    IN_PROGRESS (the officer fallback path). Already-terminal milestones
    (SATISFIED / WAIVED / OVERDUE) are left untouched."""
    for milestone in list_milestones(deal_id):
        if milestone["status"] in ("PENDING", "IN_PROGRESS"):
            start_and_complete_milestone(deal_id, milestone["id"])
    return list_milestones(deal_id)


# ---------------------------------------------------------------------------
# Tier 4: diligence artifacts (title / environmental / PCA / estoppel / SNDA)
# ---------------------------------------------------------------------------

def create_title_review_under_review(deal_id, title_company="Test Title Co",
                                     received_at="2026-08-02T00:00:00Z"):
    review = get_success_data(api_client.create_title_review(
        deal_id,
        create_title_review_payload(title_company=title_company,
                                    received_at=received_at),
        DD_OFFICER))
    get_success_data(api_client.begin_title_review(deal_id, review["id"],
                                                   DD_OFFICER))
    return get_success_data(
        api_client.get_title_review(deal_id, review["id"], DD_OFFICER))


def raise_title_exception(deal_id, review_id, exception_code="B2-100",
                          severity="STANDARD", description="Test exception",
                          cure_cost_cents=0, cured_by_exception_id=None):
    payload = {
        "exception_code": exception_code,
        "severity": severity,
        "description": description,
        "cure_cost_cents": cure_cost_cents,
    }
    if cured_by_exception_id is not None:
        payload["cured_by_exception_id"] = cured_by_exception_id
    return get_success_data(api_client.create_title_exception(
        deal_id, review_id, payload, DD_OFFICER))


def cure_exception(deal_id, review_id, exception_id):
    """Propose + confirm cure. Returns the CURED exception."""
    get_success_data(api_client.propose_cure(deal_id, review_id, exception_id,
                                             DD_OFFICER))
    return get_success_data(api_client.confirm_cure(deal_id, review_id,
                                                    exception_id, DD_OFFICER))


def clear_title_review(deal_id, title_company="Test Title Co"):
    """Create -> begin -> clear a title review with zero exceptions.
    Satisfies the TITLE_REVIEW and SURVEY_REVIEW milestones."""
    review = create_title_review_under_review(deal_id, title_company)
    return get_success_data(
        api_client.clear_title_review(deal_id, review["id"], DD_OFFICER))


def clear_environmental_assessment(deal_id):
    """Order -> receive -> clear a clean Phase I EA. Satisfies ENVIRONMENTAL."""
    ea = get_success_data(api_client.create_environmental_assessment(
        deal_id, create_environmental_assessment_payload(), DD_OFFICER))
    get_success_data(
        api_client.receive_environmental_assessment(deal_id, ea["id"],
                                                    DD_OFFICER))
    return get_success_data(
        api_client.clear_environmental_assessment(deal_id, ea["id"],
                                                  DD_OFFICER))


def accept_property_condition_assessment(deal_id):
    """Order -> receive -> committee-accept a GOOD PCA. Satisfies PCA."""
    pca = get_success_data(api_client.create_pca(
        deal_id, create_pca_payload(), DD_OFFICER))
    get_success_data(api_client.receive_pca(deal_id, pca["id"], DD_OFFICER))
    return get_success_data(api_client.accept_pca(deal_id, pca["id"],
                                                  COMMITTEE))


def certify_estoppel(deal_id, lease_id, tenant_id, rent_confirmed_cents):
    """Request -> receive -> certify an estoppel. Returns it CERTIFIED."""
    estoppel = get_success_data(api_client.create_estoppel(
        deal_id,
        create_estoppel_payload(lease_id, tenant_id,
                                rent_confirmed_cents=rent_confirmed_cents),
        DD_OFFICER))
    get_success_data(api_client.receive_estoppel(deal_id, estoppel["id"],
                                                 DD_OFFICER))
    return get_success_data(api_client.certify_estoppel(deal_id,
                                                        estoppel["id"],
                                                        DD_OFFICER))


def certify_snda(deal_id, lease_id, lender_name="Test Bank"):
    """Request -> receive -> certify an SNDA. Returns it CERTIFIED."""
    snda = get_success_data(api_client.create_snda(
        deal_id, create_snda_payload(lease_id, lender_name=lender_name),
        DD_OFFICER))
    get_success_data(api_client.receive_snda(deal_id, snda["id"], DD_OFFICER))
    return get_success_data(api_client.certify_snda(deal_id, snda["id"],
                                                    DD_OFFICER))


# ---------------------------------------------------------------------------
# Tier 5: full pipeline — clear-to-close, issued statement, closed deal
# ---------------------------------------------------------------------------

def setup_clear_to_close(**kwargs):
    """Full pipeline: deal at PSA_EXECUTED with every diligence artifact at
    its terminal-good state, then committee certification.

    Returns ctx with deal (CLEAR_TO_CLOSE), psa, lease, model, and
    statement_id (the provisional closing statement created in DRAFT).
    """
    ctx = setup_psa_executed(**kwargs)
    deal_id = ctx["deal"]["id"]
    ctx["title_review"] = clear_title_review(deal_id, "Pipeline Title Co")
    ctx["ea"] = clear_environmental_assessment(deal_id)
    ctx["pca"] = accept_property_condition_assessment(deal_id)
    ctx["estoppel"] = certify_estoppel(
        deal_id, ctx["lease"]["id"], ctx["tenant"]["id"],
        ctx["lease"]["annual_base_rent_cents"])
    ctx["snda"] = certify_snda(deal_id, ctx["lease"]["id"])
    walkthrough = get_milestone_by_type(deal_id, "FINAL_WALKTHROUGH")
    start_and_complete_milestone(deal_id, walkthrough["id"])
    ctx["deal"] = get_success_data(
        api_client.certify_clear_to_close(deal_id, COMMITTEE))
    statements, _ = validate_paginated(
        api_client.list_closing_statements(deal_id, ESCROW,
                                           params={"limit": 100}))
    assert len(statements) == 1, (
        f"Expected exactly one provisional statement, got {len(statements)}")
    ctx["statement"] = statements[0]
    return ctx


def default_proration_inputs(lease_id):
    """The canonical two-line proration set: one September BASE_RENT line and
    one full-year TAX line, both anchored on the fixture lease."""
    return [
        proration_line("BASE_RENT", lease_id, 1200000,
                       "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"),
        proration_line("TAX", lease_id, 365000,
                       "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"),
    ]


def issue_statement(deal_id, stmt_id, closing_date=DEFAULT_CLOSING_DATE,
                    proration_inputs=None, lease_id=None):
    """Issue a DRAFT closing statement. Returns it ISSUED."""
    if proration_inputs is None:
        assert lease_id is not None, "lease_id required for default prorations"
        proration_inputs = default_proration_inputs(lease_id)
    return get_success_data(api_client.issue_closing_statement(
        deal_id, stmt_id,
        issue_statement_payload(closing_date, proration_inputs),
        STMT_ISSUER))


def acknowledge_statement(deal_id, stmt_id):
    """Acknowledge an ISSUED statement as an analyst identity distinct from
    the issuing escrow officer (segregation of duties)."""
    return get_success_data(api_client.acknowledge_closing_statement(
        deal_id, stmt_id, STMT_ACKNOWLEDGER))


def setup_closed_deal(closing_date=DEFAULT_CLOSING_DATE, **kwargs):
    """Full pipeline through CLOSED: clear-to-close + issue + acknowledge +
    close. Returns ctx with the ACKNOWLEDGED statement and closed deal."""
    ctx = setup_clear_to_close(**kwargs)
    deal_id = ctx["deal"]["id"]
    stmt_id = ctx["statement"]["id"]
    ctx["statement"] = issue_statement(deal_id, stmt_id, closing_date,
                                       lease_id=ctx["lease"]["id"])
    ctx["statement"] = acknowledge_statement(deal_id, stmt_id)
    ctx["deal"] = get_success_data(api_client.close_deal(deal_id, ESCROW))
    return ctx


def propose_true_up(deal_id, stmt_id, line_type="OTHER", amount_cents=1000,
                    reason="Test adjustment"):
    return get_success_data(api_client.create_true_up(
        deal_id, stmt_id,
        create_true_up_payload(line_type=line_type, amount_cents=amount_cents,
                               reason=reason),
        TRUEUP_PROPOSER))
