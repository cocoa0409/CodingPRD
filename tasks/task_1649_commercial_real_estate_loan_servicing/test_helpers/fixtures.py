"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Borrower calls are entity-backed by Borrower and Inspector
calls are entity-backed by Inspector. Every helper threads the real entity id
through the make_* header builders; ownership-gated calls never fall back to
the shared TEST_USERS constants.

Optimistic-concurrency threading: the two guarded creates (assumption
requests, disbursement requests) re-read the parent's current version by
default so setup chains stay linear; tests that specifically exercise the
stale-version rejection pass an explicit stale token.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import Q2_2026
from .factories import (
    appraise_payload,
    create_assumption_payload,
    create_borrower_payload,
    create_disbursement_payload,
    create_extension_option_payload,
    create_inspector_payload,
    create_insurance_policy_payload,
    create_lease_payload,
    create_loan_payload,
    create_property_payload,
    create_reserve_account_payload,
    create_statement_payload,
    schedule_inspection_payload,
)
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
    make_inspector_headers,
    make_master_servicer_headers,
    make_special_servicer_headers,
)

MS = TEST_USERS["master_servicer_headers"]
MS2 = TEST_USERS["master_servicer_headers_2"]
SS = TEST_USERS["special_servicer_headers"]
SS2 = TEST_USERS["special_servicer_headers_2"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_borrower(legal_name="Test Borrower LLC", tax_id="TX-0001",
                    contact_email="borrower@example.com"):
    """Onboard a borrower (MasterServicer act). Returns the Borrower."""
    return get_success_data(api_client.create_borrower(
        create_borrower_payload(tax_id=tax_id, legal_name=legal_name,
                                contact_email=contact_email), MS))


def create_loan(borrower_id, **overrides):
    """Board a loan (born payment CURRENT / servicing PERFORMING)."""
    return get_success_data(api_client.create_loan(
        create_loan_payload(borrower_id, **overrides), MS))


def create_property(loan_id, **overrides):
    """Attach collateral to a loan. Does not advance the loan's version."""
    return get_success_data(api_client.create_property(
        loan_id, create_property_payload(**overrides), MS))


def appraise_property(property_id, appraised_value_cents, appraisal_date,
                      appraiser_id="ms_user_1"):
    """Record a fresh appraisal; triggers the LTV reassessment cascade."""
    return get_success_data(api_client.appraise_property(
        property_id, appraise_payload(appraised_value_cents, appraisal_date),
        make_master_servicer_headers(appraiser_id)))


def create_inspector(full_name="Test Inspector", license_no="LIC-0001"):
    return get_success_data(api_client.create_inspector(
        create_inspector_payload(license_no=license_no, full_name=full_name), MS))


def create_reserve_account(loan_id, account_type="TI_LC", target_balance_cents=0):
    return get_success_data(api_client.create_reserve_account(
        loan_id, create_reserve_account_payload(
            account_type=account_type, target_balance_cents=target_balance_cents),
        MS))


def deposit_reserve(reserve_account_id, amount_cents, borrower_id=None):
    """Fund a reserve; borrower (owning) or master servicer may post."""
    headers = make_borrower_headers(borrower_id) if borrower_id else MS
    return get_success_data(api_client.deposit_reserve(
        reserve_account_id, amount_cents, headers))


def create_extension_option(loan_id, **overrides):
    return get_success_data(api_client.create_extension_option(
        loan_id, create_extension_option_payload(**overrides), MS))


def set_clock(to_iso8601, headers=None):
    """Advance the logical servicing clock; runs the full sweep."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or MS))


# ---------------------------------------------------------------------------
# Tier 2: the loan workspace (borrower + loan [+ property] [+ reserve])
# ---------------------------------------------------------------------------

def setup_borrower_and_loan(tax_id="TX-0001", **loan_overrides):
    """One borrower with one boarded loan. Returns (borrower, loan)."""
    borrower = create_borrower(tax_id=tax_id)
    loan = create_loan(borrower["id"], **loan_overrides)
    return borrower, loan


def setup_loan_with_property(tax_id="TX-0001", loan_overrides=None,
                             property_overrides=None):
    """Borrower + loan + one collateral property. Returns dict of all three."""
    borrower = create_borrower(tax_id=tax_id)
    loan = create_loan(borrower["id"], **(loan_overrides or {}))
    prop = create_property(loan["id"], **(property_overrides or {}))
    return {"borrower": borrower, "loan": loan, "property": prop}


def borrower_headers_for(ctx):
    return make_borrower_headers(ctx["borrower"]["id"])


# ---------------------------------------------------------------------------
# Statements and covenant assessments
# ---------------------------------------------------------------------------

def submit_statement(loan_id, borrower_id, statement_type, period_start,
                     period_end, net_operating_income_cents=None,
                     occupancy_pct=None):
    """Borrower submits a quarterly statement on its own loan."""
    payload = create_statement_payload(
        statement_type, period_start, period_end,
        net_operating_income_cents=net_operating_income_cents,
        occupancy_pct=occupancy_pct)
    return get_success_data(api_client.create_statement(
        loan_id, payload, make_borrower_headers(borrower_id)))


def accept_statement(statement_id, reviewer_id="ms_user_1"):
    """MasterServicer accepts; reviewer id lands in reviewed_by_user_id."""
    return get_success_data(api_client.review_statement(
        statement_id, {"decision": "ACCEPT"},
        make_master_servicer_headers(reviewer_id)))


def reject_statement(statement_id, rejection_reason="unreconciled figures",
                     reviewer_id="ms_user_1"):
    return get_success_data(api_client.review_statement(
        statement_id, {"decision": "REJECT", "rejection_reason": rejection_reason},
        make_master_servicer_headers(reviewer_id)))


def submit_and_accept_statement(loan_id, borrower_id, statement_type,
                                period_start, period_end,
                                net_operating_income_cents=None,
                                occupancy_pct=None, reviewer_id="ms_user_1"):
    stmt = submit_statement(loan_id, borrower_id, statement_type, period_start,
                            period_end,
                            net_operating_income_cents=net_operating_income_cents,
                            occupancy_pct=occupancy_pct)
    accept_statement(stmt["id"], reviewer_id=reviewer_id)
    return stmt


def list_assessments(loan_id, params=None):
    data, _meta = validate_paginated(api_client.list_loan_assessments(
        loan_id, MS, params=params))
    return data


def newest_assessment(loan_id, params=None):
    """Assessments list newest first by assessed_at."""
    rows = list_assessments(loan_id, params=params)
    assert rows, "expected at least one covenant assessment"
    return rows[0]


def statement_assessments(statement_id, params=None):
    """Assessments sourced from one statement (PRD: each statement exposes them).

    Selection by source statement is deterministic even when several
    assessments share the same logical `assessed_at` clock instant, which the
    loan-level "newest first by assessed_at" listing leaves tie-ordered.
    """
    data, _meta = validate_paginated(api_client.list_statement_assessments(
        statement_id, MS, params=params))
    return data


def list_watchlist_entries(loan_id, params=None):
    data, _meta = validate_paginated(api_client.list_watchlist_entries(
        loan_id, MS, params=params))
    return data


def single_watchlist_entry(loan_id, criterion=None, status=None):
    params = {}
    if criterion is not None:
        params["criterion"] = criterion
    if status is not None:
        params["status"] = status
    data, meta = validate_paginated(api_client.list_watchlist_entries(
        loan_id, MS, params=params or None))
    assert meta["total_count"] == 1, (
        f"expected exactly one watchlist entry ({params}), got {meta['total_count']}")
    return data[0]


def get_loan(loan_id):
    return get_success_data(api_client.get_loan(loan_id, MS))


def get_reserve(reserve_account_id):
    return get_success_data(api_client.get_reserve_account(reserve_account_id, MS))


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

def schedule_inspection(property_id, inspector_id,
                        scheduled_start="2026-08-03T09:00:00Z",
                        scheduled_end="2026-08-03T11:00:00Z"):
    return get_success_data(api_client.schedule_inspection(
        property_id,
        schedule_inspection_payload(inspector_id,
                                    scheduled_start=scheduled_start,
                                    scheduled_end=scheduled_end),
        MS))


def complete_inspection(inspection_id, inspector_id, condition_rating,
                        findings=None):
    """The assigned inspector closes with outcome COMPLETED."""
    payload = {"outcome": "COMPLETED", "condition_rating": condition_rating}
    if findings is not None:
        payload["findings"] = findings
    return get_success_data(api_client.close_inspection(
        inspection_id, payload, make_inspector_headers(inspector_id)))


def cancel_inspection(inspection_id):
    """A MasterServicer closes with outcome CANCELLED."""
    return get_success_data(api_client.close_inspection(
        inspection_id, {"outcome": "CANCELLED"}, MS))


def schedule_and_complete_inspection(property_id, inspector_id=None,
                                     condition_rating="GOOD",
                                     scheduled_start="2026-08-03T09:00:00Z",
                                     scheduled_end="2026-08-03T11:00:00Z",
                                     license_no="LIC-0001"):
    """Register (if needed), schedule, and complete an inspection."""
    if inspector_id is None:
        inspector_id = create_inspector(license_no=license_no)["id"]
    insp = schedule_inspection(property_id, inspector_id,
                               scheduled_start=scheduled_start,
                               scheduled_end=scheduled_end)
    complete_inspection(insp["id"], inspector_id, condition_rating)
    return insp


# ---------------------------------------------------------------------------
# Disbursement lifecycle
# ---------------------------------------------------------------------------

def create_draw(reserve_account_id, borrower_id, purpose, line_items,
                retainage_pct=None, expected_version=None):
    """Borrower requests a draw on its own loan's reserve. The OCC token
    defaults to a fresh read of the reserve's current version."""
    if expected_version is None:
        expected_version = get_reserve(reserve_account_id)["version"]
    payload = create_disbursement_payload(
        purpose, line_items, expected_version, retainage_pct=retainage_pct)
    return get_success_data(api_client.create_disbursement_request(
        reserve_account_id, payload, make_borrower_headers(borrower_id)))


def approve_draw(request_id, headers=None):
    return get_success_data(api_client.review_disbursement(
        request_id, "APPROVE", headers or MS))


def reject_draw(request_id, headers=None):
    return get_success_data(api_client.review_disbursement(
        request_id, "REJECT", headers or MS))


def fund_draw(request_id, headers=None):
    return get_success_data(api_client.fund_disbursement(request_id, headers or MS))


def cancel_draw(request_id, borrower_id):
    return get_success_data(api_client.cancel_disbursement(
        request_id, make_borrower_headers(borrower_id)))


def list_draws(reserve_account_id, params=None):
    data, _meta = validate_paginated(api_client.list_disbursement_requests(
        reserve_account_id, MS, params=params))
    return data


def get_draw_by_id(reserve_account_id, request_id):
    """Draw requests are read through the reserve's collection."""
    for row in list_draws(reserve_account_id):
        if row["id"] == request_id:
            return row
    raise AssertionError(f"draw {request_id} not found in reserve {reserve_account_id}")


def setup_reserve_with_deposit(loan_id, deposit_cents, account_type="TI_LC",
                               target_balance_cents=0, borrower_id=None):
    """Open a reserve and fund it. Returns the reserve (post-deposit)."""
    reserve = create_reserve_account(loan_id, account_type=account_type,
                                     target_balance_cents=target_balance_cents)
    return deposit_reserve(reserve["id"], deposit_cents, borrower_id=borrower_id)


def setup_approved_draw(loan_id, borrower_id, deposit_cents, line_items,
                        account_type="TI_LC", target_balance_cents=0,
                        retainage_pct=None, purpose="CAPITAL_REPAIR"):
    """Reserve funded + draw created + APPROVED (hold placed)."""
    reserve = setup_reserve_with_deposit(loan_id, deposit_cents,
                                         account_type=account_type,
                                         target_balance_cents=target_balance_cents)
    draw = create_draw(reserve["id"], borrower_id, purpose, line_items,
                       retainage_pct=retainage_pct)
    approve_draw(draw["id"])
    return reserve, draw


def setup_funded_draw(loan_id, borrower_id, deposit_cents, line_items,
                      account_type="TI_LC", target_balance_cents=0,
                      retainage_pct=None, purpose="CAPITAL_REPAIR"):
    """Reserve funded + draw created + APPROVED + FUNDED (waterfall run)."""
    reserve, draw = setup_approved_draw(
        loan_id, borrower_id, deposit_cents, line_items,
        account_type=account_type, target_balance_cents=target_balance_cents,
        retainage_pct=retainage_pct, purpose=purpose)
    funded = fund_draw(draw["id"])
    return reserve, funded


# ---------------------------------------------------------------------------
# Leases and estoppels
# ---------------------------------------------------------------------------

def create_lease(property_id, borrower_id, **overrides):
    return get_success_data(api_client.create_lease(
        property_id, create_lease_payload(**overrides),
        make_borrower_headers(borrower_id)))


def submit_lease(lease_id, borrower_id):
    return get_success_data(api_client.submit_lease(
        lease_id, make_borrower_headers(borrower_id)))


def decide_lease(lease_id, decision, conditions=None, headers=None):
    payload = {"decision": decision}
    if conditions is not None:
        payload["conditions"] = conditions
    return get_success_data(api_client.decide_lease(lease_id, payload,
                                                    headers or MS))


def revise_lease(lease_id, borrower_id, **edits):
    return get_success_data(api_client.revise_lease(
        lease_id, edits, make_borrower_headers(borrower_id)))


def request_estoppel(lease_id, due_date="2026-08-20T00:00:00Z"):
    return get_success_data(api_client.request_estoppel(lease_id, due_date, MS))


def execute_estoppel(estoppel_id, borrower_id):
    return get_success_data(api_client.execute_estoppel(
        estoppel_id, make_borrower_headers(borrower_id)))


# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------

def post_policy(property_id, borrower_id, coverage_amount_cents,
                coverage_type="PROPERTY", start_date="2026-01-01T00:00:00Z",
                end_date="2026-12-31T00:00:00Z"):
    return get_success_data(api_client.create_insurance_policy(
        property_id,
        create_insurance_policy_payload(coverage_amount_cents,
                                        coverage_type=coverage_type,
                                        start_date=start_date,
                                        end_date=end_date),
        make_borrower_headers(borrower_id)))


def force_place_insurance(property_id, coverage_type="PROPERTY"):
    return get_success_data(api_client.force_place_insurance(
        property_id, coverage_type, SS))


# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------

def create_assumption(loan_id, borrower_id, expected_version=None, **overrides):
    """Borrower opens an assumption request; the OCC token defaults to a fresh
    read of the loan's current version."""
    if expected_version is None:
        expected_version = get_loan(loan_id)["version"]
    return get_success_data(api_client.create_assumption_request(
        loan_id, create_assumption_payload(expected_version, **overrides),
        make_borrower_headers(borrower_id)))


def start_assumption_review(request_id, headers=None):
    return get_success_data(api_client.start_assumption_review(
        request_id, headers or MS))


def decide_assumption(request_id, decision, rejection_reason=None, headers=None):
    payload = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(api_client.decide_assumption(
        request_id, payload, headers or MS))


# ---------------------------------------------------------------------------
# Distress composites
# ---------------------------------------------------------------------------

def setup_watchlist_via_dscr_breach(tax_id="TX-DSCR", dscr_threshold=1.20,
                                    noi_cents=15_000_000, reviewer_id="ms_user_1",
                                    principal_cents=1_000_000_000, note_rate=0.06,
                                    reserve=None, statement_period=Q2_2026):
    """T3 loan whose first accepted operating statement breaches the DSCR
    covenant -> OPEN assessment -> loan WATCHLIST. Optionally opens and funds
    a reserve first so the posture cascade has a target. Returns a context
    dict; the reserve entry reflects the post-cascade state."""
    borrower = create_borrower(tax_id=tax_id)
    loan = create_loan(borrower["id"],
                       dscr_covenant_threshold=dscr_threshold,
                       dscr_basis="T3_ANNUALIZED",
                       original_principal_cents=principal_cents,
                       note_rate=note_rate)
    reserve_obj = None
    if reserve is not None:
        reserve_obj = create_reserve_account(
            loan["id"], account_type=reserve.get("account_type", "TI_LC"),
            target_balance_cents=reserve.get("target_balance_cents", 0))
        if reserve.get("deposit_cents"):
            reserve_obj = deposit_reserve(reserve_obj["id"],
                                          reserve["deposit_cents"])
    stmt = submit_and_accept_statement(
        loan["id"], borrower["id"], "OPERATING_STATEMENT",
        statement_period[0], statement_period[1],
        net_operating_income_cents=noi_cents, reviewer_id=reviewer_id)
    assessment = newest_assessment(loan["id"], params={"assessment_type": "DSCR"})
    ctx = {"borrower": borrower, "loan": loan, "statement": stmt,
           "assessment": assessment}
    if reserve_obj is not None:
        ctx["reserve"] = get_reserve(reserve_obj["id"])
    return ctx


def setup_watchlist_via_poor_inspection(tax_id="TX-POOR", rating="POOR",
                                        with_reserve=True,
                                        reserve_deposit_cents=None,
                                        reserve_target_cents=0,
                                        option=None, loan_overrides=None,
                                        property_overrides=None):
    """POOR/CRITICAL inspection completion -> POOR_INSPECTION entry ->
    loan WATCHLIST. Returns a context dict with borrower, loan, property,
    inspector, inspection, entry, and (optionally) reserve / option."""
    ctx = setup_loan_with_property(tax_id=tax_id,
                                   loan_overrides=loan_overrides,
                                   property_overrides=property_overrides)
    if with_reserve:
        reserve = create_reserve_account(ctx["loan"]["id"],
                                         target_balance_cents=reserve_target_cents)
        if reserve_deposit_cents:
            reserve = deposit_reserve(reserve["id"], reserve_deposit_cents)
        ctx["reserve"] = reserve
    if option is not None:
        ctx["option"] = create_extension_option(ctx["loan"]["id"], **option)
    inspector = create_inspector(license_no=f"LIC-{tax_id}")
    ctx["inspector"] = inspector
    inspection = schedule_inspection(ctx["property"]["id"], inspector["id"])
    ctx["inspection"] = inspection
    complete_inspection(inspection["id"], inspector["id"], rating)
    ctx["entry"] = single_watchlist_entry(ctx["loan"]["id"],
                                          criterion="POOR_INSPECTION",
                                          status="ACTIVE")
    return ctx


def setup_special_servicing_loan(tax_id="TX-ESC", rating="POOR", **kwargs):
    """Watchlist via inspection, then escalate -> loan SPECIAL_SERVICING.
    The POOR_INSPECTION entry is ESCALATED (terminal) afterwards."""
    ctx = setup_watchlist_via_poor_inspection(tax_id=tax_id, rating=rating, **kwargs)
    get_success_data(api_client.escalate_watchlist_entry(ctx["entry"]["id"], MS))
    ctx["loan"] = get_loan(ctx["loan"]["id"])
    return ctx


def exercise_option(option_id, borrower_id):
    return get_success_data(api_client.exercise_extension_option(
        option_id, make_borrower_headers(borrower_id)))


def set_payment_status(loan_id, to_status, headers=None):
    return get_success_data(api_client.set_payment_status(
        loan_id, to_status, headers or MS))


def waive_assessment(assessment_id, waiver_reason, waver_id="ss_user_1"):
    return get_success_data(api_client.waive_assessment(
        assessment_id, {"waiver_reason": waiver_reason},
        make_special_servicer_headers(waver_id)))
