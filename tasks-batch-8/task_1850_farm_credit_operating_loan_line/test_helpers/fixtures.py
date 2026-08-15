"""Composite setup helpers: multi-step preconditions behind one call.

Every fixture builds from an empty database using only PRD-declared endpoints,
using get_success_data() internally so setup failures surface as clear errors.
Borrower-role writes thread the entity-backed identity via
make_borrower_headers(borrower_id) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as _api
from .factories import (
    approve_loan_payload, create_association_payload, create_budget_payload,
    create_borrower_payload, create_claim_payload, create_collateral_payload,
    create_deferral_payload, create_distribution_payload, create_draw_payload,
    create_loan_payload, create_policy_payload, create_repayment_payload,
    create_ucc_filing_payload, declare_disaster_payload,
)
from .test_users import TEST_USERS, make_borrower_headers

BOARD = TEST_USERS["board_headers"]
OFFICER = TEST_USERS["loan_officer_headers"]
OFFICER2 = TEST_USERS["loan_officer2_headers"]
COMMITTEE = TEST_USERS["committee_headers"]
COMMITTEE2 = TEST_USERS["committee2_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
SYSTEM = TEST_USERS["system_headers"]

DEFAULT_CLOCK = "2026-03-01T00:00:00Z"


def set_clock(to_iso8601=DEFAULT_CLOCK):
    return get_success_data(_api.set_clock(to_iso8601, SYSTEM))


def create_association(name="Blackhawk FCS", charter_number="CH-1850"):
    return get_success_data(_api.create_association(
        create_association_payload(name=name, charter_number=charter_number), BOARD))


def create_borrower(association_id, legal_name="Sunrise Farms LLC",
                    tax_id="41-0000001", county="BLACKHAWK"):
    return get_success_data(_api.create_borrower(
        create_borrower_payload(association_id=association_id, legal_name=legal_name,
                                tax_id=tax_id, county=county),
        OFFICER))


def get_loan(loan_id):
    return get_success_data(_api.get_loan(loan_id, OFFICER))


def fresh_loan_version(loan_id):
    return get_loan(loan_id)["version"]


def get_borrower(borrower_id):
    return get_success_data(_api.get_borrower(borrower_id, OFFICER))


def get_summary(loan_id):
    return get_success_data(_api.get_financial_summary(loan_id, OFFICER))


def list_margin_notices(loan_id, status=None):
    params = {"loan_account_id": loan_id}
    if status:
        params["status"] = status
    data, _meta = validate_paginated(_api.list_margin_call_notices(OFFICER, params))
    return data


def single_margin_notice(loan_id):
    notices = list_margin_notices(loan_id)
    assert len(notices) == 1, f"expected exactly one margin call notice, got {notices}"
    return notices[0]


# ---------------------------------------------------------------------------
# Tier 1/2: origination ladder
# ---------------------------------------------------------------------------

def create_draft_loan(commitment_cents=50_000_000, rate_bps=700,
                      season_year=2026, maturity_date="2027-02-28T00:00:00Z",
                      association_name="Blackhawk FCS", charter_number="CH-1850"):
    """Association + borrower + DRAFT loan. Returns ctx dict of entities."""
    assoc = create_association(association_name, charter_number)
    bor = create_borrower(assoc["id"])
    loan = get_success_data(_api.create_loan(
        create_loan_payload(borrower_id=bor["id"],
                            requested_commitment_cents=commitment_cents,
                            rate_bps=rate_bps, season_year=season_year,
                            maturity_date=maturity_date),
        OFFICER))
    return {"assoc": assoc, "bor": bor, "loan": loan}


def create_approved_loan(approved_commitment_cents=None, **loan_kw):
    """DRAFT -> SUBMITTED -> APPROVED. ctx carries the post-approve loan."""
    ctx = create_draft_loan(**loan_kw)
    loan = ctx["loan"]
    get_success_data(_api.submit_loan(loan["id"], OFFICER))
    commitment = approved_commitment_cents or loan["requested_commitment_cents"]
    ctx["loan"] = get_success_data(_api.approve_loan(
        loan["id"], approve_loan_payload(approved_commitment_cents=commitment),
        COMMITTEE))
    return ctx


def create_budget(ctx, projected_revenue_cents=20_000_000,
                  projected_expenses_cents=12_000_000, crop_type="CORN",
                  acres=1000, season_year=None):
    """Borrower files a budget against ctx's loan (OCC version read fresh)."""
    loan = ctx["loan"]
    version = fresh_loan_version(loan["id"])
    return get_success_data(_api.create_crop_budget(
        create_budget_payload(
            loan_account_id=loan["id"],
            season_year=season_year or loan["season_year"],
            crop_type=crop_type, acres=acres,
            projected_revenue_cents=projected_revenue_cents,
            projected_expenses_cents=projected_expenses_cents,
            expected_loan_version=version),
        make_borrower_headers(ctx["bor"]["id"])))


def setup_loan_with_approved_budget(projected_revenue_cents=20_000_000,
                                    projected_expenses_cents=12_000_000,
                                    **loan_kw):
    """APPROVED loan + APPROVED budget. Borrowing base carries the crop leg."""
    ctx = create_approved_loan(**loan_kw)
    bud = create_budget(ctx, projected_revenue_cents=projected_revenue_cents,
                        projected_expenses_cents=projected_expenses_cents)
    ctx["bud"] = get_success_data(_api.approve_crop_budget(bud["id"], OFFICER))
    ctx["loan"] = get_loan(ctx["loan"]["id"])
    return ctx


def add_collateral(ctx, collateral_type="EQUIPMENT", appraised_value_cents=10_000_000,
                   prior_lien_cents=None, description="Sprayer", perfect=True,
                   filing_number="UCC-26-001", filed_date="2026-03-05T00:00:00Z"):
    """Pledge collateral; when perfect=True also file a UCC-1 (FILED)."""
    payload = create_collateral_payload(
        loan_account_id=ctx["loan"]["id"], collateral_type=collateral_type,
        description=description, appraised_value_cents=appraised_value_cents)
    if prior_lien_cents is not None:
        payload["prior_lien_cents"] = prior_lien_cents
    col = get_success_data(_api.create_collateral(payload, OFFICER))
    fil = None
    if perfect:
        fil = get_success_data(_api.create_ucc_filing(
            create_ucc_filing_payload(collateral_id=col["id"],
                                      filing_number=filing_number,
                                      filed_date=filed_date),
            OFFICER))
    return col, fil


def add_assigned_policy(ctx, policy_number="POL-001", coverage_amount_cents=40_000_000,
                        coverage_start="2026-03-01T00:00:00Z",
                        coverage_end="2027-03-01T00:00:00Z",
                        crop_type="CORN", county=None):
    """Create + assign an ACTIVE policy naming ctx's loan (lender loss payee)."""
    pol = get_success_data(_api.create_insurance_policy(
        create_policy_payload(borrower_id=ctx["bor"]["id"],
                              policy_number=policy_number, crop_type=crop_type,
                              county=county or ctx["bor"]["county"],
                              coverage_start=coverage_start,
                              coverage_end=coverage_end,
                              coverage_amount_cents=coverage_amount_cents),
        OFFICER))
    pol = get_success_data(_api.assign_insurance_policy(
        pol["id"], {"loan_account_id": ctx["loan"]["id"]}, OFFICER))
    return pol


def setup_activatable_loan(collateral_type="EQUIPMENT",
                           appraised_value_cents=10_000_000,
                           projected_revenue_cents=20_000_000, **loan_kw):
    """All four activation gates satisfiable: budget APPROVED, collateral
    PERFECTED, policy ASSIGNED, maturity in the future. Not yet activated."""
    ctx = setup_loan_with_approved_budget(
        projected_revenue_cents=projected_revenue_cents, **loan_kw)
    col, fil = add_collateral(ctx, collateral_type=collateral_type,
                              appraised_value_cents=appraised_value_cents)
    ctx["col"], ctx["fil"] = col, fil
    ctx["pol"] = add_assigned_policy(ctx)
    ctx["loan"] = get_loan(ctx["loan"]["id"])
    return ctx


def setup_active_loan(clock=DEFAULT_CLOCK, **kwargs):
    """Full origination through ACTIVE. Returns ctx with all entities."""
    set_clock(clock)
    ctx = setup_activatable_loan(**kwargs)
    ctx["loan"] = get_success_data(_api.activate_loan(ctx["loan"]["id"], OFFICER))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: draws, distress, claims
# ---------------------------------------------------------------------------

def disburse_draw(ctx, amount_cents, purpose="SEED", as_borrower=False):
    """Create + approve + disburse a draw against ctx's ACTIVE loan."""
    headers = make_borrower_headers(ctx["bor"]["id"]) if as_borrower else OFFICER
    drw = get_success_data(_api.create_draw_request(
        create_draw_payload(loan_account_id=ctx["loan"]["id"],
                            amount_cents=amount_cents, purpose=purpose),
        headers))
    get_success_data(_api.approve_draw_request(drw["id"], OFFICER))
    drw = get_success_data(_api.disburse_draw_request(drw["id"], OFFICER))
    ctx["loan"] = get_loan(ctx["loan"]["id"])
    return drw


def setup_loan_with_draw(amount_cents=19_000_000, draw_clock="2026-04-01T00:00:00Z",
                         purpose="SEED", **kwargs):
    """ACTIVE loan with one DISBURSED draw of amount_cents at draw_clock."""
    ctx = setup_active_loan(**kwargs)
    if draw_clock:
        set_clock(draw_clock)
    ctx["drw"] = disburse_draw(ctx, amount_cents, purpose=purpose)
    return ctx


def setup_distressed_loan(draw_cents=19_000_000, terminate_clock=None, **kwargs):
    """ACTIVE loan drawn to its 19,000,000 base, then the filing is terminated:
    base falls to 12,000,000, coverage goes negative, posture DELINQUENT, a
    margin call notice opens ISSUED, and the borrower is SUSPENDED."""
    ctx = setup_loan_with_draw(amount_cents=draw_cents, **kwargs)
    if terminate_clock:
        set_clock(terminate_clock)
    get_success_data(_api.terminate_ucc_filing(ctx["fil"]["id"], OFFICER))
    ctx["loan"] = get_loan(ctx["loan"]["id"])
    ctx["notice"] = single_margin_notice(ctx["loan"]["id"])
    return ctx


def create_plan(ctx, officer_headers=OFFICER, **overrides):
    """Officer proposes a restructure plan; OCC version read fresh."""
    from .factories import create_plan_payload
    version = fresh_loan_version(ctx["loan"]["id"])
    return get_success_data(_api.create_restructure_plan(
        create_plan_payload(loan_account_id=ctx["loan"]["id"],
                            expected_loan_version=version, **overrides),
        officer_headers))


def setup_distressed_loan_with_plan(officer_headers=OFFICER, **plan_overrides):
    """Distressed loan + a PROPOSED STANDARD restructure plan (loan now
    RESTRUCTURING). Returns ctx with plan."""
    ctx = setup_distressed_loan()
    ctx["plan"] = create_plan(ctx, officer_headers=officer_headers, **plan_overrides)
    ctx["loan"] = get_loan(ctx["loan"]["id"])
    return ctx


def setup_active_loan_with_reported_claim(claimed_loss_cents=3_000_000, **kwargs):
    """ACTIVE loan + REPORTED claim under its ASSIGNED policy."""
    ctx = setup_active_loan(**kwargs)
    clm = get_success_data(_api.create_insurance_claim(
        create_claim_payload(policy_id=ctx["pol"]["id"],
                             loan_account_id=ctx["loan"]["id"],
                             claimed_loss_cents=claimed_loss_cents),
        OFFICER))
    ctx["clm"] = clm
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: deferrals and disasters
# ---------------------------------------------------------------------------

def declare_disaster(assoc_id, disaster_ref="DR-2026-07", counties=("BLACKHAWK",),
                     start_date="2026-05-01T00:00:00Z",
                     end_date="2026-12-31T00:00:00Z"):
    return get_success_data(_api.declare_disaster(
        assoc_id, declare_disaster_payload(disaster_ref=disaster_ref,
                                           counties=list(counties),
                                           start_date=start_date,
                                           end_date=end_date),
        BOARD))


def create_deferral(ctx, disaster_ref="DR-2026-07",
                    requested_start="2026-06-01T00:00:00Z",
                    requested_end="2026-08-01T00:00:00Z"):
    return get_success_data(_api.create_deferral_request(
        create_deferral_payload(loan_account_id=ctx["loan"]["id"],
                                disaster_ref=disaster_ref,
                                requested_start=requested_start,
                                requested_end=requested_end),
        make_borrower_headers(ctx["bor"]["id"])))


def setup_active_loan_with_deferral(requested_start="2026-06-01T00:00:00Z",
                                    requested_end="2026-08-01T00:00:00Z",
                                    disaster_start="2026-05-01T00:00:00Z",
                                    disaster_end="2026-12-31T00:00:00Z",
                                    request_clock="2026-05-15T00:00:00Z",
                                    **kwargs):
    """ACTIVE loan + disaster DR-2026-07 declared + one APPROVED deferral."""
    ctx = setup_active_loan(**kwargs)
    declare_disaster(ctx["assoc"]["id"], start_date=disaster_start,
                     end_date=disaster_end)
    set_clock(request_clock)
    d1 = create_deferral(ctx, requested_start=requested_start,
                         requested_end=requested_end)
    ctx["d1"] = get_success_data(_api.approve_deferral_request(d1["id"], COMMITTEE))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: patronage scenarios
# ---------------------------------------------------------------------------

def setup_repaid_borrower(assoc, legal_name, tax_id, draw_cents, repay_cents,
                          repay_clock, maturity_date="2028-12-31T00:00:00Z",
                          coverage_end="2029-01-01T00:00:00Z",
                          policy_number="POL-A", filing_number="UCC-A",
                          commitment_cents=None, start_clock=DEFAULT_CLOCK):
    """A borrower whose ACTIVE loan is drawn and (partially or fully) repaid at
    repay_clock; the repayment's applied_interest_cents is its patronage weight.
    Assumes the logical clock is already at start_clock on entry; leaves the
    clock at repay_clock."""
    bor = create_borrower(assoc["id"], legal_name=legal_name, tax_id=tax_id)
    commitment = commitment_cents or draw_cents
    loan = get_success_data(_api.create_loan(
        create_loan_payload(borrower_id=bor["id"],
                            requested_commitment_cents=commitment,
                            maturity_date=maturity_date), OFFICER))
    get_success_data(_api.submit_loan(loan["id"], OFFICER))
    loan = get_success_data(_api.approve_loan(
        loan["id"], approve_loan_payload(approved_commitment_cents=commitment),
        COMMITTEE))
    ctx = {"assoc": assoc, "bor": bor, "loan": loan}
    bud = create_budget(ctx, projected_revenue_cents=80_000_000,
                        projected_expenses_cents=50_000_000, acres=4000)
    ctx["bud"] = get_success_data(_api.approve_crop_budget(bud["id"], OFFICER))
    col, fil = add_collateral(ctx, collateral_type="REAL_ESTATE",
                              appraised_value_cents=60_000_000,
                              description="Farmland", filing_number=filing_number)
    ctx["col"], ctx["fil"] = col, fil
    ctx["pol"] = add_assigned_policy(ctx, policy_number=policy_number,
                                     coverage_amount_cents=60_000_000,
                                     coverage_end=coverage_end)
    ctx["loan"] = get_success_data(_api.activate_loan(loan["id"], OFFICER))
    ctx["drw"] = disburse_draw(ctx, draw_cents, as_borrower=True)
    set_clock(repay_clock)
    ctx["repay"] = get_success_data(_api.create_repayment(
        create_repayment_payload(loan_account_id=loan["id"],
                                 amount_cents=repay_cents),
        make_borrower_headers(bor["id"])))
    ctx["loan"] = get_loan(loan["id"])
    return ctx


def setup_declared_distribution(assoc_id, fiscal_year=2028, pool_cents=100_000,
                                declaration_clock="2029-01-15T00:00:00Z"):
    """DECLARED patronage distribution for the year just closed."""
    set_clock(declaration_clock)
    return get_success_data(_api.create_patronage_distribution(
        create_distribution_payload(association_id=assoc_id,
                                    fiscal_year=fiscal_year, pool_cents=pool_cents),
        BOARD))


# ---------------------------------------------------------------------------
# Covenant helpers
# ---------------------------------------------------------------------------

def record_evaluation(ctx, assets, liabilities, as_of_date="2026-03-15T00:00:00Z",
                      officer_headers=OFFICER):
    from .factories import create_covenant_evaluation_payload
    return get_success_data(_api.create_covenant_evaluation(
        create_covenant_evaluation_payload(loan_account_id=ctx["loan"]["id"],
                                           as_of_date=as_of_date,
                                           current_assets_cents=assets,
                                           current_liabilities_cents=liabilities),
        officer_headers))
