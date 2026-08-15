"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Borrower calls are entity-backed by Borrower, so every
borrower-role write threads the acting borrower's real id through
make_borrower_headers(); the shared TEST_USERS borrower entry is never used
for ownership-gated calls.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    complete_inspection_payload,
    create_borrower_payload,
    create_budget_line_payload,
    create_conversion_review_payload,
    create_draw_document_payload,
    create_draw_line_item_payload,
    create_draw_payload,
    create_inspection_payload,
    create_loan_payload,
    create_reallocation_payload,
    create_retainage_release_payload,
    interest_accrual_payload,
    review_decision_payload,
)
from .test_users import TEST_USERS, make_borrower_headers

ADMIN = TEST_USERS["lender_admin_headers"]
PROCESSOR = TEST_USERS["draw_processor_headers"]
OFFICER = TEST_USERS["credit_officer_headers"]
SERVICER = TEST_USERS["loan_servicer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_borrower(legal_name="Acme Builders LLC",
                    contact_email="ops@acme.example", entity_type="LLC"):
    """Register a borrower. Returns the borrower record."""
    return get_success_data(api_client.create_borrower(
        create_borrower_payload(legal_name=legal_name,
                                contact_email=contact_email,
                                entity_type=entity_type),
        ADMIN,
    ))


def create_loan(borrower_id, commitment_amount_cents=None, rate_bps=None,
                reserve_cents=None, maturity_date=None, day_count_convention=None,
                retainage_pct=None, reduced_retainage_pct=None,
                retainage_milestone_pct=None, stored_materials_max_pct=None):
    """Create a loan (born OPEN). Optional policy knobs are only sent when given."""
    over = {}
    if commitment_amount_cents is not None:
        over["commitment_amount_cents"] = commitment_amount_cents
    if rate_bps is not None:
        over["interest_rate_annual_bps"] = rate_bps
    if reserve_cents is not None:
        over["interest_reserve_initial_cents"] = reserve_cents
    if maturity_date is not None:
        over["maturity_date"] = maturity_date
    if day_count_convention is not None:
        over["day_count_convention"] = day_count_convention
    if retainage_pct is not None:
        over["retainage_pct"] = retainage_pct
    if reduced_retainage_pct is not None:
        over["reduced_retainage_pct"] = reduced_retainage_pct
    if retainage_milestone_pct is not None:
        over["retainage_milestone_pct"] = retainage_milestone_pct
    if stored_materials_max_pct is not None:
        over["stored_materials_max_pct"] = stored_materials_max_pct
    return get_success_data(api_client.create_loan(
        create_loan_payload(borrower_id, **over), ADMIN,
    ))


def add_budget_line(loan_id, cost_code="SITE", description="Site work",
                    original_amount_cents=None, is_contingency=None):
    """Add a budget line (born ACTIVE). Returns the line."""
    over = {}
    if original_amount_cents is not None:
        over["original_amount_cents"] = original_amount_cents
    if is_contingency is not None:
        over["is_contingency"] = is_contingency
    return get_success_data(api_client.create_budget_line(
        create_budget_line_payload(loan_id, cost_code=cost_code,
                                   description=description, **over),
        ADMIN,
    ))


def create_draw(loan_id, borrower_id, period_start=None, period_end=None):
    """Create a DRAFT draw as the owning borrower. Returns the draw."""
    over = {}
    if period_start is not None:
        over["period_start_date"] = period_start
    if period_end is not None:
        over["period_end_date"] = period_end
    return get_success_data(api_client.create_draw(
        create_draw_payload(loan_id, **over),
        make_borrower_headers(borrower_id),
    ))


def add_work_line_item(draw_id, budget_line_id, requested_cents, borrower_id):
    """Add a WORK_COMPLETED line item to a DRAFT/REVISION_REQUESTED draw."""
    return get_success_data(api_client.create_draw_line_item(
        create_draw_line_item_payload(draw_id, budget_line_id,
                                      requested_cents=requested_cents),
        make_borrower_headers(borrower_id),
    ))


def add_stored_line_item(draw_id, budget_line_id, requested_cents,
                         invoice_cents, borrower_id,
                         insurance_ref="CERT-1", stored_location="Bonded warehouse, Lot 9",
                         installed_by_date=None):
    """Add a STORED_MATERIALS line item with full evidence."""
    over = {
        "line_type": "STORED_MATERIALS",
        "requested_cents": requested_cents,
        "stored_material_invoice_cents": invoice_cents,
        "insurance_certificate_ref": insurance_ref,
        "stored_location": stored_location,
    }
    if installed_by_date is not None:
        over["installed_by_date"] = installed_by_date
    return get_success_data(api_client.create_draw_line_item(
        create_draw_line_item_payload(draw_id, budget_line_id, **over),
        make_borrower_headers(borrower_id),
    ))


def attach_document(draw_id, doc_type, amount_cents, borrower_id,
                    party_name="Acme GC", doc_date=None):
    """Attach a document (born SUBMITTED) to a DRAFT/REVISION_REQUESTED draw."""
    over = {}
    if doc_date is not None:
        over["doc_date"] = doc_date
    return get_success_data(api_client.create_draw_document(
        create_draw_document_payload(draw_id, doc_type=doc_type,
                                     party_name=party_name,
                                     amount_cents=amount_cents, **over),
        make_borrower_headers(borrower_id),
    ))


def verify_document(doc_id):
    """DrawProcessor verifies a SUBMITTED document. Returns the document."""
    return get_success_data(api_client.review_draw_document(
        doc_id, review_decision_payload("VERIFIED"), PROCESSOR,
    ))


def order_inspection(loan_id, scheduled_date, draw_id=None):
    """Order an inspection (draw inspection when draw_id given)."""
    over = {}
    if draw_id is not None:
        over["draw_id"] = draw_id
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(loan_id, scheduled_date=scheduled_date, **over),
        PROCESSOR,
    ))


def complete_inspection(inspection_id, percent, completed_date,
                        stored_materials_observed_cents=None, notes=None):
    """Inspector reports results for an ORDERED inspection."""
    over = {}
    if stored_materials_observed_cents is not None:
        over["stored_materials_observed_cents"] = stored_materials_observed_cents
    if notes is not None:
        over["notes"] = notes
    return get_success_data(api_client.complete_inspection(
        inspection_id,
        complete_inspection_payload(percent_complete_reported=percent,
                                    completed_date=completed_date, **over),
        INSPECTOR,
    ))


def accept_inspection(inspection_id):
    """DrawProcessor accepts a COMPLETED inspection."""
    return get_success_data(api_client.review_inspection(
        inspection_id, review_decision_payload("ACCEPTED"), PROCESSOR,
    ))


def submit_draw(draw_id, borrower_id):
    return get_success_data(api_client.submit_draw(
        draw_id, make_borrower_headers(borrower_id)))


def start_review_draw(draw_id):
    return get_success_data(api_client.start_review_draw(draw_id, PROCESSOR))


def approve_draw(draw_id):
    return get_success_data(api_client.approve_draw(draw_id, OFFICER))


def fund_draw(draw_id):
    return get_success_data(api_client.fund_draw(draw_id, SERVICER))


def get_loan(loan_id):
    return get_success_data(api_client.get_loan(loan_id, SERVICER))


def get_budget_line(line_id):
    return get_success_data(api_client.get_budget_line(line_id, SERVICER))


def get_draw(draw_id):
    return get_success_data(api_client.get_draw(draw_id, SERVICER))


def get_draw_line_item(item_id):
    return get_success_data(api_client.get_draw_line_item(item_id, SERVICER))


def run_accrual(loan_id, period_start_date, period_end_date):
    """Run one interest accrual; returns the INTEREST_PAYMENT entry created."""
    return get_success_data(api_client.run_interest_accrual(
        loan_id,
        interest_accrual_payload(period_start_date, period_end_date),
        SERVICER,
    ))


# ---------------------------------------------------------------------------
# Tier 2: loan workspace (borrower + loan + budget lines)
# ---------------------------------------------------------------------------

def setup_loan_with_lines(line_specs=(("SITE", "Site work", 40_000_000, False),),
                          **loan_over):
    """Borrower + loan + budget lines.

    line_specs: iterable of (cost_code, description, original_amount_cents,
    is_contingency_or_None). Returns a scenario dict with the borrower, the
    loan, a {cost_code: line} map, and the borrower's ownership headers.
    """
    borrower = create_borrower()
    loan = create_loan(borrower["id"], **loan_over)
    lines = {}
    for cost_code, description, amount, is_contingency in line_specs:
        lines[cost_code] = add_budget_line(
            loan["id"], cost_code=cost_code, description=description,
            original_amount_cents=amount,
            is_contingency=is_contingency if is_contingency else None,
        )
    return {
        "borrower": borrower,
        "loan": loan,
        "lines": lines,
        "borrower_headers": make_borrower_headers(borrower["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3: draw pipeline (walk a draw through its lifecycle)
# ---------------------------------------------------------------------------

def add_draw(sc, period_start="2026-03-01", period_end="2026-03-31"):
    """Create a DRAFT draw inside an existing loan scenario."""
    draw = create_draw(sc["loan"]["id"], sc["borrower"]["id"],
                       period_start=period_start, period_end=period_end)
    sc.setdefault("draws", []).append(draw)
    return draw


def add_draw_documents(sc, draw_id, doc_specs, doc_date="2026-03-25"):
    """Attach (and optionally verify) documents on a draw.

    doc_specs: iterable of (doc_type, amount_cents, verify_bool).
    """
    docs = []
    for doc_type, amount, verify in doc_specs:
        doc = attach_document(draw_id, doc_type, amount,
                              sc["borrower"]["id"], doc_date=doc_date)
        if verify:
            doc = verify_document(doc["id"])
        docs.append(doc)
    return docs


def progress_draw(sc, draw_id, *, submit=True, start_review=True,
                  inspection_pct=None,
                  inspection_scheduled="2026-03-20",
                  inspection_completed="2026-03-21",
                  inspection_observed_cents=None,
                  approve=False, fund=False):
    """Walk a draw: submit -> start-review -> [inspection accepted] -> approve -> fund.

    When inspection_pct is not None, a draw inspection is ordered, completed at
    that percent, and ACCEPTED before approval. Returns the final draw.
    """
    if submit:
        submit_draw(draw_id, sc["borrower"]["id"])
    if start_review:
        start_review_draw(draw_id)
    inspection = None
    if inspection_pct is not None:
        inspection = order_inspection(sc["loan"]["id"], inspection_scheduled,
                                      draw_id=draw_id)
        complete_inspection(inspection["id"], inspection_pct,
                            inspection_completed,
                            stored_materials_observed_cents=inspection_observed_cents)
        accept_inspection(inspection["id"])
        sc.setdefault("inspections", []).append(inspection)
    if approve:
        approve_draw(draw_id)
    if fund:
        fund_draw(draw_id)
    return get_draw(draw_id)


def setup_funded_scenario(*, reserve_cents=0, commitment=100_000_000,
                          rate_bps=1200, day_count=None, line_amount=40_000_000,
                          requested=10_000_000, inspection_pct=50.00,
                          period_start="2026-03-01", period_end="2026-03-31",
                          inspection_scheduled="2026-03-20",
                          inspection_completed="2026-03-21",
                          extra_line_specs=()):
    """Canonical funded scenario.

    borrower -> loan -> one budget line -> draw -> one WORK_COMPLETED line ->
    verified invoice + verified conditional waiver -> submit -> start-review ->
    draw inspection ACCEPTED -> approve -> fund.

    With defaults (inspection 50.00 meets the milestone, so the reduced 5%
    retainage applies at approve): approved 10000000, retainage 500000,
    net funded 9500000.

    Returns a scenario dict: borrower, loan, lines, draw, item, docs,
    inspection, borrower_headers.
    """
    line_specs = [("SITE", "Site work", line_amount, False)] + list(extra_line_specs)
    sc = setup_loan_with_lines(
        line_specs=line_specs,
        commitment_amount_cents=commitment,
        rate_bps=rate_bps,
        reserve_cents=reserve_cents,
        day_count_convention=day_count,
    )
    draw = add_draw(sc, period_start=period_start, period_end=period_end)
    item = add_work_line_item(draw["id"], sc["lines"]["SITE"]["id"],
                              requested, sc["borrower"]["id"])
    docs = add_draw_documents(sc, draw["id"], (
        ("INVOICE", requested, True),
        ("LIEN_WAIVER_CONDITIONAL", requested, True),
    ))
    progress_draw(sc, draw["id"], inspection_pct=inspection_pct,
                  inspection_scheduled=inspection_scheduled,
                  inspection_completed=inspection_completed,
                  approve=True, fund=True)
    sc["draw"] = get_draw(draw["id"])
    sc["item"] = get_draw_line_item(item["id"])
    sc["docs"] = docs
    return sc


# ---------------------------------------------------------------------------
# Tier 4: retainage release helpers
# ---------------------------------------------------------------------------

def create_release(sc, budget_line_id, amount_cents, reason="Milestone release"):
    """Borrower requests a retainage release (born REQUESTED)."""
    return get_success_data(api_client.create_retainage_release(
        create_retainage_release_payload(sc["loan"]["id"], budget_line_id,
                                         amount_cents=amount_cents, reason=reason),
        make_borrower_headers(sc["borrower"]["id"]),
    ))


def create_approved_release(sc, budget_line_id, amount_cents,
                            reason="Milestone release"):
    """Release walked REQUESTED -> APPROVED."""
    release = create_release(sc, budget_line_id, amount_cents, reason=reason)
    return get_success_data(api_client.review_retainage_release(
        release["id"], review_decision_payload("APPROVED"), OFFICER,
    ))


# ---------------------------------------------------------------------------
# Tier 5: conversion / termination helpers
# ---------------------------------------------------------------------------

def setup_completion_inspection(sc, scheduled="2026-06-15",
                                completed="2026-06-16", percent=100.00):
    """Order + complete + ACCEPT a completion inspection (not tied to a draw)."""
    insp = order_inspection(sc["loan"]["id"], scheduled)
    complete_inspection(insp["id"], percent, completed)
    return accept_inspection(insp["id"])


def create_conversion_review(sc):
    """Borrower requests conversion (born REQUESTED)."""
    return get_success_data(api_client.create_conversion_review(
        create_conversion_review_payload(sc["loan"]["id"]),
        make_borrower_headers(sc["borrower"]["id"]),
    ))


def setup_conversion_ready_scenario(reserve_cents=0):
    """Loan + one budget line + ACCEPTED 100.00 completion inspection, no draws.

    Retained is zero and no draw is non-terminal, so a conversion review can be
    approved on this loan.
    """
    sc = setup_loan_with_lines(reserve_cents=reserve_cents)
    sc["completion_inspection"] = setup_completion_inspection(sc)
    return sc


# ---------------------------------------------------------------------------
# Reallocation helpers
# ---------------------------------------------------------------------------

def create_reallocation(sc, from_line_id, to_line_id, amount_cents,
                        justification="Budget rebalance"):
    """Draft a reallocation with the loan's currently observed version (OCC)."""
    version = get_loan(sc["loan"]["id"])["version"]
    return get_success_data(api_client.create_reallocation_request(
        create_reallocation_payload(sc["loan"]["id"], from_line_id, to_line_id,
                                    version, amount_cents=amount_cents,
                                    justification=justification),
        ADMIN,
    ))


def create_applied_reallocation(sc, from_line_id, to_line_id, amount_cents,
                                justification="Budget rebalance"):
    """Reallocation walked PENDING -> APPROVED -> APPLIED."""
    req = create_reallocation(sc, from_line_id, to_line_id, amount_cents,
                              justification=justification)
    get_success_data(api_client.review_reallocation_request(
        req["id"], review_decision_payload("APPROVED"), OFFICER))
    return get_success_data(api_client.apply_reallocation_request(
        req["id"], SERVICER))
