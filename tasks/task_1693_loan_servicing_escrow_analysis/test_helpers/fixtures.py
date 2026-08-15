"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All helpers use get_success_data() so a setup
failure surfaces as a clear "Setup step failed" message.

Identity threading: Borrower calls are entity-backed by Loan; helpers that
file error cases or acknowledge notices build borrower headers from the real
loan id via make_borrower_headers.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    acknowledge_notice_payload,
    assign_case_payload,
    charge_force_placement_payload,
    create_advance_payload,
    create_analysis_payload,
    create_deposit_payload,
    create_disbursement_payload,
    create_error_case_payload,
    create_insurance_policy_payload,
    create_line_item_payload,
    create_loan_payload,
    create_payee_payload,
    create_tax_record_payload,
    mark_tax_paid_payload,
    recover_advance_payload,
    reinstate_policy_payload,
    resolve_case_payload,
)
from .test_users import TEST_USERS, make_borrower_headers

CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
EA1 = TEST_USERS["escrow_analyst_headers"]
EA9 = TEST_USERS["escrow_analyst_2_headers"]
DP1 = TEST_USERS["disbursement_processor_headers"]
DP2 = TEST_USERS["disbursement_processor_2_headers"]
PV1 = TEST_USERS["payee_verifier_headers"]
PV2 = TEST_USERS["payee_verifier_2_headers"]
IS1 = TEST_USERS["insurance_specialist_headers"]

# Standard two-line-item expense picture used across many scenarios:
# PROPERTY_TAX 240000/yr in 2 installments (first due 2026-12-15) plus
# HAZARD_INSURANCE 120000/yr in 1 installment (first due 2027-03-01).
# Annual 360000 -> cushion 60000, base monthly 30000.
STANDARD_LINE_ITEMS = [
    {"expense_type": "PROPERTY_TAX", "expected_annual_amount_cents": 240_000,
     "installments_per_year": 2, "first_due_date": "2026-12-15"},
    {"expense_type": "HAZARD_INSURANCE", "expected_annual_amount_cents": 120_000,
     "installments_per_year": 1, "first_due_date": "2027-03-01"},
]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation / state progression
# ---------------------------------------------------------------------------

def create_verified_payee(payee_type="TAX_AUTHORITY", legal_name="County Treasurer",
                          remit_to_address="1 Civic Center", ach_routing_mask="****1234",
                          creator_headers=None, verifier_headers=None):
    """Create a payee (PENDING_VERIFICATION) and verify it. Returns payee."""
    creator = creator_headers or DP1
    verifier = verifier_headers or PV1
    payee = get_success_data(api_client.create_payee(
        create_payee_payload(payee_type=payee_type, legal_name=legal_name,
                             remit_to_address=remit_to_address,
                             ach_routing_mask=ach_routing_mask), creator))
    return get_success_data(api_client.verify_payee(payee["id"], verifier))


def create_unverified_payee(payee_type="INSURANCE_CARRIER",
                            legal_name="Unverified Mutual", creator_headers=None):
    """Create a payee left in PENDING_VERIFICATION."""
    creator = creator_headers or DP1
    return get_success_data(api_client.create_payee(
        create_payee_payload(payee_type=payee_type, legal_name=legal_name,
                             remit_to_address="5 Doubt St",
                             ach_routing_mask="****5555"), creator))


def create_onboarding_loan(loan_number="LN-0001", borrower_name="Test Borrower",
                           closing_date="2026-08-01", escrow_required=True,
                           principal_balance_cents=30_000_000,
                           monthly_pi_cents=180_000):
    """Board a loan (born ONBOARDING). Returns the loan."""
    return get_success_data(api_client.create_loan(
        create_loan_payload(loan_number=loan_number, borrower_name=borrower_name,
                            closing_date=closing_date,
                            escrow_required=escrow_required,
                            principal_balance_cents=principal_balance_cents,
                            monthly_pi_cents=monthly_pi_cents), CO1))


def create_active_bare_loan(loan_number="LN-0001", borrower_name="Test Borrower",
                            closing_date="2026-07-01"):
    """Board and activate a loan with escrow_required=false (no escrow account).
    Used by insurance/tax/error-case scenarios that need no escrow account."""
    loan = create_onboarding_loan(loan_number=loan_number, borrower_name=borrower_name,
                                  closing_date=closing_date, escrow_required=False,
                                  principal_balance_cents=22_000_000,
                                  monthly_pi_cents=140_000)
    return get_success_data(api_client.activate_loan(loan["id"], CO1))


def add_line_item(account_id, payee_id, expense_type="PROPERTY_TAX",
                  expected_annual_amount_cents=240_000, installments_per_year=2,
                  first_due_date="2026-12-15"):
    """Add an ACTIVE line item to an account. Returns the line item."""
    return get_success_data(api_client.create_line_item(
        account_id,
        create_line_item_payload(
            payee_id, expense_type=expense_type,
            expected_annual_amount_cents=expected_annual_amount_cents,
            installments_per_year=installments_per_year,
            first_due_date=first_due_date),
        EA1))


def post_deposit(account_id, amount_cents, effective_date, headers=None):
    """Post a borrower escrow deposit (DEPOSIT entry + recovery waterfall)."""
    return get_success_data(api_client.create_deposit(
        account_id,
        create_deposit_payload(amount_cents=amount_cents, effective_date=effective_date),
        headers or EA1))


def set_clock(to_iso8601):
    """Advance the logical clock (ComplianceOfficer only)."""
    return get_success_data(api_client.set_clock(to_iso8601, CO1))


def get_account(account_id):
    return get_success_data(api_client.get_escrow_account(account_id, EA1))


def get_ledger(account_id, params=None):
    data, _meta = validate_paginated(api_client.list_ledger(account_id, EA1,
                                                            params=params))
    return data


# ---------------------------------------------------------------------------
# Tier 2: the escrow workspace (payee + loan + account + line items)
# ---------------------------------------------------------------------------

def setup_active_account(loan_number="LN-1000", borrower_name="Test Borrower",
                         line_items=None, closing_date="2026-08-01",
                         activate_loan=True, deposits=None, payee=None):
    """Verified payee + escrow-required loan + ACTIVE escrow account with the
    given line items (default: STANDARD_LINE_ITEMS). When activate_loan is
    true the loan is also ACTIVE. Optional deposits are posted in order.

    Returns dict: payee, loan, account (post-activation snapshot),
    line_items (list of created line-item dicts).
    """
    payee = payee or create_verified_payee()
    loan = create_onboarding_loan(loan_number=loan_number, borrower_name=borrower_name,
                                  closing_date=closing_date)
    account = get_success_data(api_client.create_escrow_account(loan["id"], {}, EA1))
    items = []
    for spec in (line_items if line_items is not None else STANDARD_LINE_ITEMS):
        items.append(add_line_item(account["id"], payee["id"], **spec))
    account = get_success_data(api_client.activate_escrow_account(account["id"], EA1))
    if activate_loan:
        loan = get_success_data(api_client.activate_loan(loan["id"], CO1))
    for amount, eff_date in (deposits or []):
        post_deposit(account["id"], amount, eff_date)
    return {"payee": payee, "loan": loan, "account": account, "line_items": items}


# ---------------------------------------------------------------------------
# Tier 3: disbursement lifecycle
# ---------------------------------------------------------------------------

def schedule_disbursement(account_id, line_item_id, payee_id, amount_cents=30_000,
                          due_date="2026-12-20", scheduled_release_date="2026-12-01",
                          scheduler_headers=None):
    """Schedule a disbursement (born SCHEDULED). Returns the disbursement."""
    return get_success_data(api_client.create_disbursement(
        account_id,
        create_disbursement_payload(
            line_item_id, payee_id, amount_cents=amount_cents, due_date=due_date,
            scheduled_release_date=scheduled_release_date),
        scheduler_headers or DP1))


def release_disbursement(disbursement_id, releaser_headers=None):
    """Release a disbursement with a peer processor (SoD-clean by default)."""
    return get_success_data(api_client.release_disbursement(
        disbursement_id, releaser_headers or DP2))


def setup_account_with_scheduled_disbursement(loan_number="LN-2000",
                                              deposit_amount=100_000,
                                              deposit_effective_date="2026-08-05",
                                              disbursement_amount=30_000,
                                              due_date="2026-08-20",
                                              scheduled_release_date="2026-08-10"):
    """ACTIVE account funded with one deposit and one SCHEDULED disbursement.
    Returns (ctx, disbursement)."""
    ctx = setup_active_account(loan_number=loan_number,
                               deposits=[(deposit_amount, deposit_effective_date)])
    disb = schedule_disbursement(
        ctx["account"]["id"], ctx["line_items"][0]["id"], ctx["payee"]["id"],
        amount_cents=disbursement_amount, due_date=due_date,
        scheduled_release_date=scheduled_release_date)
    return ctx, disb


def setup_released_disbursement(loan_number="LN-2001", deposit_amount=100_000,
                                disbursement_amount=30_000, due_date="2026-08-20",
                                scheduled_release_date="2026-08-10",
                                release_clock="2026-08-10T00:00:00Z"):
    """Funded account + disbursement already RELEASED at release_clock.
    Returns (ctx, disbursement)."""
    ctx, disb = setup_account_with_scheduled_disbursement(
        loan_number=loan_number, deposit_amount=deposit_amount,
        disbursement_amount=disbursement_amount, due_date=due_date,
        scheduled_release_date=scheduled_release_date)
    set_clock(release_clock)
    disb = release_disbursement(disb["id"])
    return ctx, disb


# ---------------------------------------------------------------------------
# Tier 3b: advances
# ---------------------------------------------------------------------------

def create_manual_advance(account_id, amount_cents, reason="MANUAL_CORRECTION"):
    """Create a manual corporate advance (born OUTSTANDING)."""
    return get_success_data(api_client.create_advance(
        account_id, create_advance_payload(amount_cents=amount_cents, reason=reason),
        CO1))


def recover_advance(advance_id, amount_cents):
    return get_success_data(api_client.recover_advance(
        advance_id, recover_advance_payload(amount_cents), EA1))


# ---------------------------------------------------------------------------
# Tier 3c: insurance policies
# ---------------------------------------------------------------------------

def create_policy(loan_id, policy_type="HAZARD", carrier_name="Carrier A",
                  policy_number="POL-1", coverage_start_date="2026-01-01",
                  coverage_end_date="2027-01-01", annual_premium_cents=120_000,
                  headers=None):
    """Register a borrower policy (born ACTIVE). Loan must be ACTIVE."""
    return get_success_data(api_client.create_insurance_policy(
        loan_id,
        create_insurance_policy_payload(
            policy_type=policy_type, carrier_name=carrier_name,
            policy_number=policy_number, coverage_start_date=coverage_start_date,
            coverage_end_date=coverage_end_date,
            annual_premium_cents=annual_premium_cents),
        headers or IS1))


def reinstate_policy(policy_id, new_coverage_start_date, new_coverage_end_date,
                     new_annual_premium_cents=None, headers=None):
    payload = reinstate_policy_payload(
        new_coverage_start_date=new_coverage_start_date,
        new_coverage_end_date=new_coverage_end_date)
    if new_annual_premium_cents is not None:
        payload["new_annual_premium_cents"] = new_annual_premium_cents
    return get_success_data(api_client.reinstate_policy(policy_id, payload,
                                                        headers or IS1))


def setup_lapsed_policy_with_notice1(loan_number="LN-3000", policy_number="POL-L1"):
    """ACTIVE bare loan + policy reported lapsed + first notice sent at the
    default clock (2026-08-01). Returns (loan, policy)."""
    loan = create_active_bare_loan(loan_number=loan_number)
    policy = create_policy(loan["id"], policy_number=policy_number)
    get_success_data(api_client.report_lapse(policy["id"], IS1))
    policy = get_success_data(api_client.send_first_notice(policy["id"], IS1))
    return loan, policy


def setup_policy_notice2(loan_number="LN-3001", policy_number="POL-N2",
                         reminder_clock="2026-08-31T00:00:00Z"):
    """Policy in NOTICE_2_SENT: first notice at 2026-08-01, reminder at
    reminder_clock (default exactly +30 days). Returns (loan, policy)."""
    loan, policy = setup_lapsed_policy_with_notice1(loan_number=loan_number,
                                                    policy_number=policy_number)
    set_clock(reminder_clock)
    policy = get_success_data(api_client.send_reminder_notice(policy["id"], IS1))
    return loan, policy


def charge_force_placement(policy_id, fp_premium_cents=182_500,
                           day_count_convention=None):
    payload = charge_force_placement_payload(fp_premium_cents=fp_premium_cents)
    if day_count_convention is not None:
        payload["day_count_convention"] = day_count_convention
    return get_success_data(api_client.charge_force_placement(policy_id, payload, IS1))


# ---------------------------------------------------------------------------
# Tier 3d: tax monitoring
# ---------------------------------------------------------------------------

def create_tax_record(loan_id, parcel_number="P-1", tax_year=2026,
                      installment_sequence=1, amount_due_cents=300_000,
                      due_date="2026-08-01", grace_period_days=0,
                      monthly_penalty_rate_bps=150, penalty_method="SIMPLE"):
    return get_success_data(api_client.create_tax_record(
        loan_id,
        create_tax_record_payload(
            parcel_number=parcel_number, tax_year=tax_year,
            installment_sequence=installment_sequence,
            amount_due_cents=amount_due_cents, due_date=due_date,
            grace_period_days=grace_period_days,
            monthly_penalty_rate_bps=monthly_penalty_rate_bps,
            penalty_method=penalty_method),
        EA1))


# ---------------------------------------------------------------------------
# Tier 4/5: analysis cycles, notices, error cases
# ---------------------------------------------------------------------------

def open_analysis_cycle(account_id, analysis_year=2027,
                        projection_start_date="2026-09-01", method="PROSPECTIVE"):
    """Open a DRAFT analysis cycle, threading the account's current version
    (OCC). Returns the created cycle."""
    account = get_account(account_id)
    return get_success_data(api_client.create_analysis(
        account_id,
        create_analysis_payload(account["version"], analysis_year=analysis_year,
                                projection_start_date=projection_start_date,
                                method=method),
        EA1))


def compute_cycle(analysis_id):
    return get_success_data(api_client.compute_analysis(analysis_id, EA1))


def setup_computed_analysis(loan_number="LN-4000", deposits=None,
                            line_items=None, method="PROSPECTIVE",
                            projection_start_date="2026-09-01", analysis_year=2027):
    """ACTIVE account (default deposits: one 60000 deposit eff 2026-08-10) plus
    a COMPUTED analysis cycle. Returns dict(ctx..., analysis)."""
    ctx = setup_active_account(loan_number=loan_number, line_items=line_items,
                               deposits=(deposits if deposits is not None
                                         else [(60_000, "2026-08-10")]))
    analysis = open_analysis_cycle(ctx["account"]["id"], analysis_year=analysis_year,
                                   projection_start_date=projection_start_date,
                                   method=method)
    analysis = compute_cycle(analysis["id"])
    ctx["analysis"] = analysis
    return ctx


def setup_effective_analysis(loan_number="LN-4001", deposits=None, line_items=None,
                             method="PROSPECTIVE",
                             projection_start_date="2026-09-01", analysis_year=2027):
    """Full lifecycle: computed -> statement issued -> EFFECTIVE, with the
    DRAFT payment-change notice fetched. Returns dict(ctx..., analysis,
    notice)."""
    ctx = setup_computed_analysis(loan_number=loan_number, deposits=deposits,
                                  line_items=line_items, method=method,
                                  projection_start_date=projection_start_date,
                                  analysis_year=analysis_year)
    get_success_data(api_client.issue_statement(ctx["analysis"]["id"], EA1))
    analysis = get_success_data(api_client.finalize_analysis(ctx["analysis"]["id"], EA1))
    notices, _meta = validate_paginated(api_client.list_notices(analysis["id"], EA1))
    ctx["analysis"] = analysis
    ctx["notice"] = notices[0]
    return ctx


def send_notice(notice_id):
    return get_success_data(api_client.send_notice(notice_id, EA1))


def acknowledge_notice(notice_id, loan_id, shortage_option=None):
    payload = acknowledge_notice_payload()
    if shortage_option is not None:
        payload["shortage_option"] = shortage_option
    return get_success_data(api_client.acknowledge_notice(
        notice_id, payload, make_borrower_headers(loan_id)))


def file_error_case(loan_id, error_type="OTHER_COVERED",
                    description="Borrower-asserted error", asserted_amount_cents=None):
    """File a notice of error as the owning borrower (born RECEIVED)."""
    payload = create_error_case_payload(error_type=error_type, description=description)
    if asserted_amount_cents is not None:
        payload["asserted_amount_cents"] = asserted_amount_cents
    return get_success_data(api_client.create_error_case(
        loan_id, payload, make_borrower_headers(loan_id)))


def advance_case_to_investigating(case_id, investigator="ea_9"):
    """RECEIVED -> ACKNOWLEDGED -> INVESTIGATING (assignee recorded)."""
    get_success_data(api_client.acknowledge_case(case_id, CO1))
    return get_success_data(api_client.assign_case(
        case_id, assign_case_payload(investigator), CO1))


def resolve_case(case_id, outcome="NO_ERROR", correction_amount_cents=None,
                 resolution_note=None, resolver_headers=None):
    payload = resolve_case_payload(outcome=outcome)
    if correction_amount_cents is not None:
        payload["correction_amount_cents"] = correction_amount_cents
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return get_success_data(api_client.resolve_case(case_id, payload,
                                                    resolver_headers or CO1))
