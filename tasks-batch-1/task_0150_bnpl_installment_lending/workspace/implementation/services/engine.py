"""Domain engine: serializers, aggregate reconciliation, posture, and the
cross-entity cascades (payment allocation, pay-off bubble, returns, settlement
clawback, default/cancel).  PRD §3.

Entities are stored as plain dicts in db.* tables. System fields:
  id, created_at, updated_at, version  (DisclosureAcceptance: id + created_at only)
"""
from datetime import timedelta

import db
from services import calculations as calc

# ── system field helpers ──────────────────────────────────────────────────────
def stamp_new(record, with_version=True):
    ts = db.iso_millis(db.now())
    record["id"] = record.get("id") or db.new_id()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on every mutation (PRD §2.5)."""
    record["updated_at"] = db.iso_millis(db.now())
    record["version"] = record.get("version", 1) + 1


# ── serializers (strip private fields) ────────────────────────────────────────
def _public(record, fields):
    out = {}
    for f in fields:
        out[f] = record.get(f)
    return out


def serialize_merchant(m):
    return {
        "id": m["id"],
        "display_name": m["display_name"],
        "mdr_bps": m["mdr_bps"],
        "settlement_hold_days": m["settlement_hold_days"],
        "status": m["status"],
        "gross_financed_cents": compute_merchant_gross(m["id"]),
        "net_settled_cents": compute_merchant_net_settled(m["id"]),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_borrower(b):
    outstanding = compute_borrower_outstanding(b["id"])
    available = max(0, b["eligible_credit_limit_cents"] - outstanding)
    return {
        "id": b["id"],
        "full_name": b["full_name"],
        "email": b["email"],
        "annual_income_cents": b["annual_income_cents"],
        "soft_credit_score": b["soft_credit_score"],
        "eligible_credit_limit_cents": b["eligible_credit_limit_cents"],
        "outstanding_principal_cents": outstanding,
        "available_credit_cents": available,
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_application(a):
    return {
        "id": a["id"],
        "borrower_id": a["borrower_id"],
        "merchant_id": a["merchant_id"],
        "cart_amount_cents": a["cart_amount_cents"],
        "plan_type": a["plan_type"],
        "term_months": a.get("term_months"),
        "requested_down_payment_cents": a["requested_down_payment_cents"],
        "apr_bps": a["apr_bps"],
        "financed_principal_cents": a["financed_principal_cents"],
        "approved_down_payment_cents": a.get("approved_down_payment_cents"),
        "finance_charge_cents": a["finance_charge_cents"],
        "total_of_payments_cents": a["total_of_payments_cents"],
        "status": a["status"],
        "decline_reason": a.get("decline_reason"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_disclosure(d):
    return {
        "id": d["id"],
        "application_id": d["application_id"],
        "disclosed_apr_bps": d["disclosed_apr_bps"],
        "disclosed_finance_charge_cents": d["disclosed_finance_charge_cents"],
        "disclosed_total_of_payments_cents": d["disclosed_total_of_payments_cents"],
        "disclosed_installment_count": d["disclosed_installment_count"],
        "accepted": d["accepted"],
        "created_at": d["created_at"],
    }


def serialize_loan(l):
    return {
        "id": l["id"],
        "application_id": l["application_id"],
        "borrower_id": l["borrower_id"],
        "merchant_id": l["merchant_id"],
        "financed_principal_cents": l["financed_principal_cents"],
        "apr_bps": l["apr_bps"],
        "finance_charge_cents": l["finance_charge_cents"],
        "remaining_principal_cents": max(0, l["remaining_principal_cents"]),
        "total_paid_cents": compute_loan_total_paid(l["id"]),
        "late_fee_accrued_cents": compute_loan_late_fees(l["id"]),
        "status": l["status"],
        "delinquency_status": l["delinquency_status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_installment(i):
    return {
        "id": i["id"],
        "loan_id": i["loan_id"],
        "sequence_no": i["sequence_no"],
        "due_date": i["due_date"],
        "amount_due_cents": i["amount_due_cents"],
        "principal_portion_cents": i["principal_portion_cents"],
        "amount_paid_cents": i["amount_paid_cents"],
        "late_fee_cents": i["late_fee_cents"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_payment(p):
    return {
        "id": p["id"],
        "loan_id": p["loan_id"],
        "amount_cents": p["amount_cents"],
        "source": p["source"],
        "allocation": p["allocation"],
        "unapplied_cents": p["unapplied_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_return(r):
    return {
        "id": r["id"],
        "loan_id": r["loan_id"],
        "merchant_id": r["merchant_id"],
        "return_amount_cents": r["return_amount_cents"],
        "principal_reduction_cents": r["principal_reduction_cents"],
        "settlement_clawback_cents": r["settlement_clawback_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_mandate(m):
    return {
        "id": m["id"],
        "loan_id": m["loan_id"],
        "borrower_id": m["borrower_id"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_settlement(s):
    return {
        "id": s["id"],
        "merchant_id": s["merchant_id"],
        "loan_id": s["loan_id"],
        "gross_financed_cents": s["gross_financed_cents"],
        "mdr_fee_cents": s["mdr_fee_cents"],
        "net_settlement_cents": s["net_settlement_cents"],
        "clawed_back_cents": s["clawed_back_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# ── aggregate computations (PRD §2.5) ─────────────────────────────────────────
def compute_borrower_outstanding(borrower_id):
    total = 0
    for l in db.loans.values():
        if l["borrower_id"] == borrower_id and l["status"] in ("ACTIVE", "DELINQUENT"):
            total += max(0, l["remaining_principal_cents"])
    return total


def compute_merchant_gross(merchant_id):
    total = 0
    for l in db.loans.values():
        if l["merchant_id"] == merchant_id and l["status"] in (
            "ACTIVE", "PAID_OFF", "DELINQUENT", "DEFAULTED"
        ):
            total += l["financed_principal_cents"]
    return total


def compute_merchant_net_settled(merchant_id):
    total = 0
    for s in db.merchant_settlements.values():
        if s["merchant_id"] == merchant_id and s["status"] == "RELEASED":
            total += s["net_settlement_cents"] - s["clawed_back_cents"]
    return total


def compute_loan_total_paid(loan_id):
    return sum(p["amount_cents"] for p in db.payments.values()
               if p["loan_id"] == loan_id)


def compute_loan_late_fees(loan_id):
    total = 0
    for i in db.installments.values():
        if i["loan_id"] == loan_id and i["status"] in ("LATE", "PAID"):
            total += i["late_fee_cents"]
    return total


def loan_installments(loan_id):
    rows = [i for i in db.installments.values() if i["loan_id"] == loan_id]
    rows.sort(key=lambda i: (i["sequence_no"], i["_seq"]))
    return rows


# ── delinquency posture (PRD §3.6) ────────────────────────────────────────────
def recompute_posture(loan):
    """Recompute delinquency_status from the oldest unpaid installment."""
    open_insts = [i for i in loan_installments(loan["id"])
                  if i["status"] in ("SCHEDULED", "LATE")]
    if not open_insts:
        loan["delinquency_status"] = "CURRENT"
        return
    # oldest by sequence_no, tie-break created_at (via _seq) ASC
    oldest = min(open_insts, key=lambda i: (i["sequence_no"], i["_seq"]))
    due = _parse_iso(oldest["due_date"])
    now = db.now()
    dpd = calc.days_between(now, due)
    # CURRENT if not yet past due+GRACE_DAYS
    past_grace = now > (due + timedelta(days=calc.GRACE_DAYS))
    if dpd < 0 or not past_grace:
        loan["delinquency_status"] = "CURRENT"
    elif dpd >= calc.DELINQUENT_DAYS:
        loan["delinquency_status"] = "DELINQUENT"
    else:
        loan["delinquency_status"] = "LATE"


def _parse_iso(s):
    from datetime import datetime, timezone
    txt = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── borrower / merchant aggregate touch (bump version+timestamp) ──────────────
def reconcile_borrower(borrower_id):
    b = db.borrowers.get(borrower_id)
    if b:
        touch(b)


def reconcile_merchant(merchant_id):
    m = db.merchants.get(merchant_id)
    if m:
        touch(m)


# ── payment allocation + pay-off bubble (PRD §3.5) ───────────────────────────
def allocate_payment(loan, amount_cents):
    """Allocate amount_cents oldest-due-first. Returns (allocation, unapplied)."""
    open_insts = [i for i in loan_installments(loan["id"])
                  if i["status"] in ("SCHEDULED", "LATE")]
    # ascending sequence_no, tie-break created_at ASC then sequence_no ASC
    open_insts.sort(key=lambda i: (i["sequence_no"], i["_seq"]))

    remaining = amount_cents
    allocation = []
    for inst in open_insts:
        if remaining <= 0:
            break
        need = inst["amount_due_cents"] - inst["amount_paid_cents"]
        if need <= 0:
            continue
        applied = min(remaining, need)
        inst["amount_paid_cents"] += applied
        remaining -= applied
        allocation.append({"installment_id": inst["id"], "applied_cents": applied})
        if inst["amount_paid_cents"] >= inst["amount_due_cents"]:
            inst["status"] = "PAID"
            touch(inst)
            # reduce remaining principal by this installment's principal portion
            loan["remaining_principal_cents"] = max(
                0, loan["remaining_principal_cents"] - inst["principal_portion_cents"])
        else:
            touch(inst)
    unapplied = remaining
    return allocation, unapplied


def maybe_payoff(loan):
    """Bubble ACTIVE -> PAID_OFF when principal hits 0 and no SCHEDULED/LATE remains."""
    if loan["status"] != "ACTIVE":
        return
    remaining_principal = max(0, loan["remaining_principal_cents"])
    has_open = any(i["status"] in ("SCHEDULED", "LATE")
                   for i in loan_installments(loan["id"]))
    if remaining_principal == 0 and not has_open:
        loan["status"] = "PAID_OFF"
        loan["delinquency_status"] = "CURRENT"
        touch(loan)
        # disable any ENABLED autopay mandate
        for mnd in db.autopay_mandates.values():
            if mnd["loan_id"] == loan["id"] and mnd["status"] == "ENABLED":
                mnd["status"] = "DISABLED"
                touch(mnd)
        reconcile_borrower(loan["borrower_id"])
        reconcile_merchant(loan["merchant_id"])


# ── settlement clawback (PRD §3.8) ────────────────────────────────────────────
def settlement_for_loan(loan_id):
    for s in db.merchant_settlements.values():
        if s["loan_id"] == loan_id:
            return s
    return None


def claw_back_full(settlement):
    """Claw back the full net settlement (loan default-while-pending / cancel)."""
    settlement["clawed_back_cents"] = settlement["net_settlement_cents"]
    settlement["status"] = "CLAWED_BACK"
    touch(settlement)


def apply_return_clawback(settlement, clawback_cents):
    """Add clawback to settlement; flip to CLAWED_BACK if it reaches the net."""
    settlement["clawed_back_cents"] += clawback_cents
    if settlement["clawed_back_cents"] >= settlement["net_settlement_cents"]:
        settlement["status"] = "CLAWED_BACK"
    touch(settlement)
