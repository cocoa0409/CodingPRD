"""Assessment fee invoice pricing, payment, waiver and settlement (PRD 3.10)."""
from db import appeals_of_claim, db, invoice_of_claim, new_row, portfolio_of_claim
from util import rhu, touch

BASE_ASSESSMENT_FEE = {
    "CREDIT_BY_EXAM": 5000,
    "PORTFOLIO": 15000,
    "MILITARY_TRAINING": 0,
    "INDUSTRY_CREDENTIAL": 7500,
}
PER_CREDIT_FEE_CENTS = 2500
APPEAL_FILING_FEE_CENTS = 6000
RUSH_SURCHARGE_BP = 2500
SLA_SERVICE_CREDIT_BP = 1500
APPEAL_FEE_STATUSES = ("FILED", "UNDER_REVIEW", "UPHELD", "OVERTURNED")
PAYMENT_METHODS = ["CARD", "CASH", "CHECK", "THIRD_PARTY", "FINANCIAL_AID"]

LINE_ORDER = [
    "BASE_ASSESSMENT_FEE", "PER_CREDIT_FEE", "ARTIFACT_TIER_SURCHARGE",
    "RUSH_SURCHARGE", "APPEAL_FILING_FEE", "SLA_SERVICE_CREDIT",
]


def artifact_tier_surcharge(artifact_count):
    if artifact_count <= 3:
        return 0
    if artifact_count <= 8:
        return 4000
    return 9000


def build_lines(claim):
    base = BASE_ASSESSMENT_FEE.get(claim["source_type"], 0)
    per_credit = PER_CREDIT_FEE_CENTS * claim["credits_requested"]
    portfolio = portfolio_of_claim(claim["id"])
    artifact = artifact_tier_surcharge(portfolio["artifact_count"]) if portfolio else 0
    rush = rhu((base + per_credit) * RUSH_SURCHARGE_BP, 10000) if claim["rush_requested"] else 0
    appeal = 0
    for appeal_row in appeals_of_claim(claim["id"]):
        if appeal_row["status"] in APPEAL_FEE_STATUSES:
            appeal = APPEAL_FILING_FEE_CENTS
            break
    sla = 0
    if claim["sla_breach_count"] >= 1:
        sla = -rhu((base + per_credit + artifact + rush) * SLA_SERVICE_CREDIT_BP, 10000)
    amounts = {
        "BASE_ASSESSMENT_FEE": base,
        "PER_CREDIT_FEE": per_credit,
        "ARTIFACT_TIER_SURCHARGE": artifact,
        "RUSH_SURCHARGE": rush,
        "APPEAL_FILING_FEE": appeal,
        "SLA_SERVICE_CREDIT": sla,
    }
    return [{"line_type": name, "amount_cents": amounts[name]}
            for name in LINE_ORDER if amounts[name] != 0]


def discount_bp_for(subtotal):
    if subtotal >= 25000:
        return 1000
    if subtotal >= 10000:
        return 500
    return 0


def price(invoice, claim):
    """Steps one through three: lines, subtotal, discount, total."""
    lines = build_lines(claim)
    subtotal = sum(line["amount_cents"] for line in lines)
    discount_bp = discount_bp_for(subtotal)
    discount_cents = rhu(subtotal * discount_bp, 10000)
    invoice["lines"] = lines
    invoice["subtotal_cents"] = subtotal
    invoice["discount_bp"] = discount_bp
    invoice["discount_cents"] = discount_cents
    invoice["total_cents"] = subtotal - discount_cents


def net_paid(invoice):
    return invoice["paid_cents"] - invoice["refunded_cents"]


def outstanding(invoice):
    return invoice["total_cents"] - invoice["waived_cents"] - net_paid(invoice)


def sweep_excess(invoice):
    """Step four: only negative balances are swept."""
    balance = outstanding(invoice)
    if balance < 0:
        invoice["refunded_cents"] += -balance
        balance = 0
    invoice["balance_due_cents"] = balance
    return balance


def restatus(claim, invoice):
    if claim["fee_status"] in ("UNBILLED", "WAIVED", "REFUNDED", "RETAINED"):
        return
    target = invoice["total_cents"] - invoice["waived_cents"]
    net = net_paid(invoice)
    if net >= target:
        claim["fee_status"] = "PAID"
    elif net > 0:
        claim["fee_status"] = "PARTIALLY_PAID"
    else:
        claim["fee_status"] = "INVOICED"


def recompute_student_fee_net(student):
    total = 0
    for invoice in db.invoices.values():
        if invoice["student_id"] == student["id"]:
            total += net_paid(invoice)
    if student["fee_paid_net_cents"] != total:
        student["fee_paid_net_cents"] = total
        touch(student)


def create_invoice(claim):
    invoice = new_row("FeeInvoice")
    invoice["claim_id"] = claim["id"]
    invoice["student_id"] = claim["student_id"]
    invoice["fee_status"] = "INVOICED"
    invoice["paid_cents"] = 0
    invoice["refunded_cents"] = 0
    invoice["waived_cents"] = 0
    invoice["aid_eligible"] = False
    invoice["recompute_count"] = 0
    price(invoice, claim)
    invoice["balance_due_cents"] = outstanding(invoice)
    db.invoices[invoice["id"]] = invoice
    claim["fee_status"] = "INVOICED"
    return invoice


def recompute(claim, student=None, extra_refund=0):
    """Full repricing of an existing invoice; counts as one recompute.

    An ordered refund (the remand's fixed 6000 cents) is applied before the
    excess sweep, which then only absorbs whatever is still left over.
    """
    invoice = invoice_of_claim(claim["id"])
    if invoice is None:
        return None
    price(invoice, claim)
    invoice["recompute_count"] += 1
    if extra_refund:
        invoice["refunded_cents"] += extra_refund
    sweep_excess(invoice)
    restatus(claim, invoice)
    invoice["fee_status"] = claim["fee_status"]
    touch(invoice)
    if student is not None:
        recompute_student_fee_net(student)
    return invoice


def apply_payment(claim, invoice, student, amount_cents):
    invoice["paid_cents"] += amount_cents
    balance = outstanding(invoice)
    invoice["balance_due_cents"] = balance if balance > 0 else 0
    target = invoice["total_cents"] - invoice["waived_cents"]
    claim["fee_status"] = "PAID" if net_paid(invoice) >= target else "PARTIALLY_PAID"
    invoice["fee_status"] = claim["fee_status"]
    student["fee_paid_net_cents"] += amount_cents
    touch(student)
    touch(invoice)
    touch(claim)


def waive(claim, invoice, student, whole_total=False):
    """Coordinator waiver and the institution's own waivers."""
    net = net_paid(invoice)
    if whole_total:
        invoice["waived_cents"] = invoice["total_cents"]
    else:
        invoice["waived_cents"] = invoice["total_cents"] - net
    invoice["refunded_cents"] += net
    invoice["balance_due_cents"] = 0
    claim["fee_status"] = "WAIVED"
    invoice["fee_status"] = "WAIVED"
    touch(invoice)
    touch(claim)
    recompute_student_fee_net(student)


def settle(claim, invoice, student, retention_bp):
    """Settlement on exit: retain a share, refund the complement, waive the rest."""
    net = net_paid(invoice)
    retained = rhu(net * retention_bp, 10000)
    refund = net - retained
    invoice["refunded_cents"] += refund
    balance = outstanding(invoice)
    if balance > 0:
        invoice["waived_cents"] += balance
        balance = 0
    elif balance < 0:
        invoice["refunded_cents"] += -balance
        balance = 0
    invoice["balance_due_cents"] = balance
    claim["fee_status"] = "REFUNDED" if refund > 0 else "WAIVED"
    invoice["fee_status"] = claim["fee_status"]
    touch(invoice)
    recompute_student_fee_net(student)
    return refund
