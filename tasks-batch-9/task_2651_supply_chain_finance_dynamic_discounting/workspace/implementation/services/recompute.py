"""Derived-field recomputation.

PRD 2.10: every row a cascade mutates gets its own updated_at refresh and its
own version increment; a row that is merely re-read is never touched.  Both
conserved quantities (a funder's encumbered capital and a buyer's credit used)
are always recomputed in full from the qualifying rows, never delta adjusted.
"""

from decimal import Decimal

from db import clock_date, db, sorted_rows, touch
from services import calc

ENCUMBERING_FUNDING = ("RESERVED", "DEPLOYED")
FACE_COVERING_FUNDING = ("RESERVED", "DEPLOYED", "RELEASED")
FUNDED_CONCENTRATION_FUNDING = ("DEPLOYED", "RELEASED")


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------

def program_invoices(program_id):
    return sorted_rows([i for i in db.invoices.values() if i["program_id"] == program_id])


def invoice_offers(invoice_id):
    return sorted_rows([o for o in db.offers.values() if o["invoice_id"] == invoice_id])


def session_offers(session_id):
    return sorted_rows([o for o in db.offers.values() if o["session_id"] == session_id])


def offer_payments(offer_id):
    return sorted_rows([p for p in db.payments.values() if p["offer_id"] == offer_id])


def invoice_payments(invoice_id):
    return sorted_rows([p for p in db.payments.values() if p["invoice_id"] == invoice_id])


def invoice_disputes(invoice_id):
    return sorted_rows([d for d in db.disputes.values() if d["invoice_id"] == invoice_id])


def funder_commitments(funder_id):
    return sorted_rows([c for c in db.commitments.values() if c["funder_id"] == funder_id])


def supplier_bank_accounts(supplier_id):
    return sorted_rows(
        [b for b in db.bank_accounts.values() if b["supplier_id"] == supplier_id]
    )


def buyer_programs(buyer_id):
    return sorted_rows([p for p in db.programs.values() if p["buyer_id"] == buyer_id])


def program_of_invoice(invoice):
    return db.programs.get(invoice["program_id"])


def buyer_of_program(program):
    return db.buyers.get(program["buyer_id"])


def buyer_of_invoice(invoice):
    program = program_of_invoice(invoice)
    return buyer_of_program(program) if program else None


def program_of_payment(payment):
    invoice = db.invoices.get(payment["invoice_id"])
    return program_of_invoice(invoice) if invoice else None


# --------------------------------------------------------------------------
# adoption analytics + the monotone ceiling rule (PRD 3.10)
# --------------------------------------------------------------------------

def adoption_figures(program_id):
    eligible = 0
    adopted = 0
    apr_rows = []
    for invoice in program_invoices(program_id):
        status = invoice["status"]
        if status in calc.ELIGIBLE_STATUSES:
            eligible += 1
        if status == "EARLY_PAID":
            adopted += 1
            apr_rows.append((invoice["accepted_apr_bps"], invoice["face_amount_cents"]))
    rate = calc.pct(adopted, eligible) if eligible else Decimal("0.00")
    posture = calc.rate_posture(rate)
    weighted = calc.weighted_avg_apr(apr_rows)
    return eligible, adopted, rate, posture, weighted


def recompute_program_adoption(program, force=False):
    eligible, adopted, rate, posture, weighted = adoption_figures(program["id"])
    ceiling = calc.tightened_ceiling(program["max_acceptable_apr_bps"], posture, weighted)
    changed = (
        program["eligible_invoice_count"] != eligible
        or program["adopted_invoice_count"] != adopted
        or program["_adoption_rate_pct"] != rate
        or program["rate_posture"] != posture
        or program["weighted_avg_accepted_apr_bps"] != weighted
        or program["max_acceptable_apr_bps"] != ceiling
    )
    program["eligible_invoice_count"] = eligible
    program["adopted_invoice_count"] = adopted
    program["_adoption_rate_pct"] = rate
    program["adoption_rate_pct"] = float(rate)
    program["rate_posture"] = posture
    program["weighted_avg_accepted_apr_bps"] = weighted
    program["max_acceptable_apr_bps"] = ceiling
    if changed or force:
        touch(program)
    return changed


# --------------------------------------------------------------------------
# conserved quantity: funder capital (PRD 2.10 / 3.7)
# --------------------------------------------------------------------------

def funder_encumbered(funder_id):
    total = 0
    for payment in db.payments.values():
        if payment.get("funder_id") == funder_id and payment["funding_status"] in ENCUMBERING_FUNDING:
            total += payment["net_payment_cents"]
    return total


def funder_committed_at(funder_id, target_date):
    return calc.committed_at(funder_commitments(funder_id), target_date)


def recompute_funder_capital(funder, force=False):
    encumbered = funder_encumbered(funder["id"])
    committed = funder_committed_at(funder["id"], clock_date())
    available = calc.available_capital(committed, encumbered)
    changed = (
        funder["encumbered_capital_cents"] != encumbered
        or funder["available_capital_cents"] != available
    )
    funder["encumbered_capital_cents"] = encumbered
    funder["available_capital_cents"] = available
    if changed or force:
        touch(funder)
    return changed


def recompute_all_funders():
    for funder in sorted_rows(list(db.funders.values())):
        recompute_funder_capital(funder)


def funder_headroom(funder, target_date, encumbered=None):
    if encumbered is None:
        encumbered = funder["encumbered_capital_cents"]
    return funder_committed_at(funder["id"], target_date) - encumbered


# --------------------------------------------------------------------------
# conserved quantity: buyer credit used (PRD 3.8)
# --------------------------------------------------------------------------

def buyer_credit_used(buyer_id, exclude_payment_id=None):
    total = 0
    for payment in db.payments.values():
        if payment["id"] == exclude_payment_id:
            continue
        if payment.get("funding_source") != "BUYER_SELF":
            continue
        if payment["funding_status"] not in ENCUMBERING_FUNDING:
            continue
        program = program_of_payment(payment)
        if program is None or program["buyer_id"] != buyer_id:
            continue
        total += payment["net_payment_cents"]
    return total


def recompute_buyer_credit(buyer, force=False):
    used = buyer_credit_used(buyer["id"])
    changed = buyer["credit_used_cents"] != used
    buyer["credit_used_cents"] = used
    if changed or force:
        touch(buyer)
    return changed


# --------------------------------------------------------------------------
# conserved quantity: invoice face (PRD 2.10)
# --------------------------------------------------------------------------

def recompute_invoice_face(invoice, force=False):
    covered = 0
    for payment in invoice_payments(invoice["id"]):
        if payment["funding_status"] in FACE_COVERING_FUNDING:
            covered += payment["face_covered_cents"]
    remaining = invoice["face_amount_cents"] - covered
    changed = (
        invoice["face_covered_cents"] != covered
        or invoice["remaining_face_cents"] != remaining
    )
    invoice["face_covered_cents"] = covered
    invoice["remaining_face_cents"] = remaining
    if changed or force:
        touch(invoice)
    return changed


# --------------------------------------------------------------------------
# concentration (PRD 3.6 / 3.10)
# --------------------------------------------------------------------------

FACE_CONCENTRATION_STATUSES = ("ELIGIBLE", "OFFERED", "AWARDED", "EARLY_PAID")
FACE_NUMERATOR_STATUSES = ("AWARDED", "EARLY_PAID")


def projected_concentration_pct(program_id, supplier_id, pending_invoice):
    """Forward looking share used by the acceptance gate."""
    denominator = 0
    numerator = 0
    for invoice in program_invoices(program_id):
        if invoice["status"] in FACE_CONCENTRATION_STATUSES:
            denominator += invoice["face_amount_cents"]
        if (
            invoice["supplier_id"] == supplier_id
            and invoice["status"] in FACE_NUMERATOR_STATUSES
            and invoice["id"] != pending_invoice["id"]
        ):
            numerator += invoice["face_amount_cents"]
    numerator += pending_invoice["face_amount_cents"]
    return calc.pct(numerator, denominator)


def top_supplier_face_pct(program_id):
    denominator = 0
    per_supplier = {}
    for invoice in program_invoices(program_id):
        if invoice["status"] in FACE_CONCENTRATION_STATUSES:
            denominator += invoice["face_amount_cents"]
        if invoice["status"] in FACE_NUMERATOR_STATUSES:
            key = invoice["supplier_id"]
            per_supplier[key] = per_supplier.get(key, 0) + invoice["face_amount_cents"]
    if denominator == 0 or not per_supplier:
        return Decimal("0.00")
    return calc.pct(max(per_supplier.values()), denominator)


def top_supplier_funded_pct(program_id):
    denominator = 0
    per_supplier = {}
    for payment in db.payments.values():
        if payment["funding_status"] not in FUNDED_CONCENTRATION_FUNDING:
            continue
        invoice = db.invoices.get(payment["invoice_id"])
        if invoice is None or invoice["program_id"] != program_id:
            continue
        denominator += payment["net_payment_cents"]
        key = invoice["supplier_id"]
        per_supplier[key] = per_supplier.get(key, 0) + payment["net_payment_cents"]
    if denominator == 0 or not per_supplier:
        return Decimal("0.00")
    return calc.pct(max(per_supplier.values()), denominator)
