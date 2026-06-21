"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors instead of confusing assertion failures.

Each fixture builds preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server against an empty DB before every test).

Operator identity convention (all roles opaque, PRD §2.1):
  LoanOfficer    -> headers with X-User-ID "officer-1"
  CreditApprover -> headers with X-User-ID "approver-1" (distinct from officer-1
                    so the four-eyes guard, PRD §3.5, is satisfied)
  SbaOfficer / InvestorServicer -> opaque, identity irrelevant to ownership.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers
from .api_client import api_client
from .factories import (
    create_lender_payload,
    create_borrower_payload,
    create_application_payload,
    create_proceeds_payload,
    create_collateral_payload,
    create_form_package_payload,
    create_credit_memo_payload,
    create_disbursement_payload,
    create_guaranty_sale_payload,
    create_servicing_report_payload,
    create_liquidation_payload,
    create_guaranty_purchase_payload,
)
from .test_users import TEST_USERS, OFFICER_USER_ID, APPROVER_USER_ID

# Role headers reused throughout. The four-eyes rule requires distinct ids for
# the authoring officer and the approver.
OFFICER = TEST_USERS["loan_officer_headers"]
APPROVER = TEST_USERS["credit_approver_headers"]
SBA = TEST_USERS["sba_officer_headers"]
INVESTOR = TEST_USERS["investor_servicer_headers"]


# ─── Tier 0: atomic builders ──────────────────────────────────────────────────

def create_lender(program="7A", name="Test CDC"):
    """Create a Lender (SbaOfficer). Returns the lender entity."""
    return get_success_data(api_client.create_lender(
        create_lender_payload(name=name, program=program), SBA))


def create_borrower(lender_id, **overrides):
    """Create a Borrower under a lender (LoanOfficer). Returns the borrower entity."""
    return get_success_data(api_client.create_borrower(
        create_borrower_payload(lender_id, **overrides), OFFICER))


def create_application(borrower_id, **overrides):
    """Create a DRAFT Application (LoanOfficer). Returns the application entity."""
    return get_success_data(api_client.create_application(
        create_application_payload(borrower_id, **overrides), OFFICER))


def add_proceeds(application_id, use_category="REAL_ESTATE", amount_cents=50_000_000):
    return get_success_data(api_client.create_proceeds(
        create_proceeds_payload(application_id, use_category=use_category, amount_cents=amount_cents),
        OFFICER))


def add_collateral(application_id, asset_type="REAL_ESTATE", appraised_value_cents=70_000_000, **overrides):
    return get_success_data(api_client.create_collateral(
        create_collateral_payload(application_id, asset_type=asset_type,
                                  appraised_value_cents=appraised_value_cents, **overrides),
        OFFICER))


# ─── Tier 1: state progression on a single Application ─────────────────────────

def create_draft_application(lender_program="7A", borrower_overrides=None, app_overrides=None,
                             proceeds=True, proceeds_amount=None):
    """Lender + Borrower + DRAFT Application (optionally with one matching proceeds line).

    Returns dict {lender, borrower, application}. proceeds_amount defaults to the
    application's requested_amount_cents so a later submit passes the proceeds-sum check.
    """
    lender = create_lender(program=lender_program)
    borrower = create_borrower(lender["id"], **(borrower_overrides or {}))
    application = create_application(borrower["id"], **(app_overrides or {}))
    if proceeds:
        amt = proceeds_amount if proceeds_amount is not None else application["requested_amount_cents"]
        add_proceeds(application["id"], amount_cents=amt)
    return {"lender": lender, "borrower": borrower, "application": application}


def submit_application(application_id):
    """Submit a DRAFT application into UNDERWRITING. Returns the updated application."""
    return get_success_data(api_client.submit_application(application_id, OFFICER))


def create_underwriting_application(lender_program="7A", borrower_overrides=None,
                                    app_overrides=None, proceeds_amount=None):
    """Reach UNDERWRITING: draft + proceeds + submit. Returns {lender, borrower, application}."""
    ctx = create_draft_application(
        lender_program=lender_program, borrower_overrides=borrower_overrides,
        app_overrides=app_overrides, proceeds=True, proceeds_amount=proceeds_amount)
    ctx["application"] = submit_application(ctx["application"]["id"])
    return ctx


def cleared_form_package(application_id, character_cleared=True):
    """Create a FormPackage, submit it, and review it (-> CLEARED or FLAGGED).

    Returns the reviewed form package entity.
    """
    fp = get_success_data(api_client.create_form_package(
        create_form_package_payload(application_id, character_cleared=character_cleared), OFFICER))
    get_success_data(api_client.submit_form_package(fp["id"], OFFICER))
    return get_success_data(api_client.review_form_package(fp["id"], APPROVER))


def author_credit_memo(application_id, recommendation="APPROVE", dscr=1.35, risk_rating=3):
    """Author a DRAFT credit memo (authored_by_user_id = officer-1). Returns the memo."""
    return get_success_data(api_client.create_credit_memo(
        create_credit_memo_payload(application_id, recommendation=recommendation,
                                   dscr=dscr, risk_rating=risk_rating), OFFICER))


def reach_pending_approval(lender_program="7A", app_overrides=None, borrower_overrides=None,
                           collateral_specs=None, character_cleared=True,
                           recommendation="APPROVE", proceeds_amount=None):
    """Walk an application to PENDING_APPROVAL with a SUBMITTED credit memo.

    Sequence: underwriting application + collateral + cleared form package +
    authored memo + submit memo. Returns dict
    {lender, borrower, application, form_package, credit_memo}.

    collateral_specs: list of kwargs dicts passed to add_collateral. Defaults to a
    single REAL_ESTATE item appraised 70000000 (net 56000000), which covers the
    standard 50000000 long-term requirement.
    """
    ctx = create_underwriting_application(
        lender_program=lender_program, app_overrides=app_overrides,
        borrower_overrides=borrower_overrides, proceeds_amount=proceeds_amount)
    aid = ctx["application"]["id"]
    if collateral_specs is None:
        collateral_specs = [{"asset_type": "REAL_ESTATE", "appraised_value_cents": 70_000_000}]
    for spec in collateral_specs:
        add_collateral(aid, **spec)
    ctx["form_package"] = cleared_form_package(aid, character_cleared=character_cleared)
    ctx["credit_memo"] = author_credit_memo(aid, recommendation=recommendation)
    get_success_data(api_client.submit_credit_memo(ctx["credit_memo"]["id"], OFFICER))
    ctx["application"] = get_success_data(api_client.get_application(aid, SBA))
    return ctx


def reach_approved(**kwargs):
    """Walk to APPROVED (PENDING_APPROVAL then approve). Returns the same ctx dict,
    with ctx["application"] refreshed to the approve response."""
    ctx = reach_pending_approval(**kwargs)
    ctx["application"] = get_success_data(
        api_client.approve_application(ctx["application"]["id"], APPROVER))
    return ctx


def reach_authorized(**kwargs):
    """Walk to AUTHORIZED (freezes guaranteed amount + guaranty fee). Returns ctx with
    ctx["application"] = authorize response (carries frozen figures + post-auth version)."""
    ctx = reach_approved(**kwargs)
    ctx["application"] = get_success_data(
        api_client.authorize_application(ctx["application"]["id"], SBA))
    return ctx


# ─── Tier 3: disbursement / full-funding shortcuts ────────────────────────────

def create_and_post_disbursement(application_id, amount_cents, start_day, end_day, label="Draw"):
    """Create a disbursement draw and POST it. Returns the posted disbursement."""
    disb = get_success_data(api_client.create_disbursement(
        create_disbursement_payload(application_id, amount_cents=amount_cents,
                                    tranche_label=label, draw_window_start_day=start_day,
                                    draw_window_end_day=end_day), OFFICER))
    return get_success_data(api_client.post_disbursement(disb["id"], OFFICER))


def reach_fully_disbursed(window_start=0, window_end=30, **kwargs):
    """AUTHORIZED loan, then a single POSTED draw for the full requested amount.

    Drives status AUTHORIZED -> DISBURSING and servicing_status NOT_SERVICING ->
    CURRENT. Returns ctx with ctx["disbursement"] added and ctx["application"]
    refreshed.
    """
    ctx = reach_authorized(**kwargs)
    aid = ctx["application"]["id"]
    amount = ctx["application"]["requested_amount_cents"]
    ctx["disbursement"] = create_and_post_disbursement(
        aid, amount, window_start, window_end, label="Initial")
    ctx["application"] = get_success_data(api_client.get_application(aid, SBA))
    return ctx


# ─── Tier 4: servicing / accumulation toward the servicing axis ───────────────

def file_servicing_report(application_id, period_start_month, period_end_month,
                          principal_paid_cents=0, days_past_due=0, period_index=None,
                          interest_paid_cents=100_000):
    """File a PENDING servicing report. Returns the report entity."""
    if period_index is None:
        period_index = period_start_month
    return get_success_data(api_client.create_servicing_report(
        create_servicing_report_payload(
            application_id, period_index=period_index, period_start_month=period_start_month,
            period_end_month=period_end_month, principal_paid_cents=principal_paid_cents,
            interest_paid_cents=interest_paid_cents, days_past_due=days_past_due), OFFICER))


def file_and_accept_servicing_report(application_id, period_start_month, period_end_month,
                                     principal_paid_cents=0, days_past_due=0, period_index=None):
    """File a report and ACCEPT it (SbaOfficer). Returns the accepted report."""
    rpt = file_servicing_report(application_id, period_start_month, period_end_month,
                                principal_paid_cents=principal_paid_cents,
                                days_past_due=days_past_due, period_index=period_index)
    return get_success_data(api_client.accept_servicing_report(rpt["id"], SBA))


def reach_defaulted(days_past_due=95, **kwargs):
    """Fully-disbursed loan driven to servicing_status DEFAULTED.

    Files+accepts a single period-0 report with days_past_due (>=90) so the loan is
    DELINQUENT, then declares default. Returns ctx with ctx["application"] refreshed.
    """
    ctx = reach_fully_disbursed(**kwargs)
    aid = ctx["application"]["id"]
    file_and_accept_servicing_report(aid, 0, 0, principal_paid_cents=0, days_past_due=days_past_due)
    get_success_data(api_client.declare_default(aid, OFFICER))
    ctx["application"] = get_success_data(api_client.get_application(aid, SBA))
    return ctx


# ─── Tier 4b: guaranty sale shortcuts ─────────────────────────────────────────

def offer_guaranty_sale(application_id, sold_principal_cents, premium_bps=350,
                        investor_user_id="inv-9"):
    """Create an OFFERED guaranty sale. Returns the sale entity."""
    return get_success_data(api_client.create_guaranty_sale(
        create_guaranty_sale_payload(application_id, sold_principal_cents,
                                     premium_bps=premium_bps, investor_user_id=investor_user_id),
        OFFICER))


def settle_guaranty_sale(sale_id, expected_application_version):
    """Settle an OFFERED sale (InvestorServicer, OCC-guarded). Returns the settled sale."""
    return get_success_data(api_client.settle_guaranty_sale(
        sale_id, {"expected_application_version": expected_application_version}, INVESTOR))


def reach_sold(premium_bps=350, **kwargs):
    """AUTHORIZED loan with a SETTLED guaranty sale (guaranty_status SOLD).

    Sells exactly guaranteed_amount_cents. Returns ctx with ctx["sale"] (settled),
    ctx["sale_version"] (the application version observed at authorize, used for the
    expected_application_version), and ctx["application"] refreshed.
    """
    ctx = reach_authorized(**kwargs)
    aid = ctx["application"]["id"]
    app_v = ctx["application"]["version"]
    guaranteed = ctx["application"]["guaranteed_amount_cents"]
    sale = offer_guaranty_sale(aid, guaranteed, premium_bps=premium_bps)
    ctx["sale"] = settle_guaranty_sale(sale["id"], app_v)
    ctx["sale_version"] = app_v
    ctx["application"] = get_success_data(api_client.get_application(aid, SBA))
    return ctx


# ─── Tier 5: liquidation / guaranty-purchase shortcuts ────────────────────────

def open_liquidation(application_id, recovery_cents, expense_cents=0):
    """Open an OPEN LiquidationEvent on a defaulted loan. Returns the event."""
    return get_success_data(api_client.create_liquidation(
        create_liquidation_payload(application_id, recovery_cents=recovery_cents,
                                   expense_cents=expense_cents), OFFICER))


def file_guaranty_purchase(application_id, claimed_principal_cents, repair_pct=0):
    """File a FILED GuarantyPurchase. Returns the purchase entity."""
    return get_success_data(api_client.create_guaranty_purchase(
        create_guaranty_purchase_payload(application_id, claimed_principal_cents,
                                         repair_pct=repair_pct), OFFICER))
