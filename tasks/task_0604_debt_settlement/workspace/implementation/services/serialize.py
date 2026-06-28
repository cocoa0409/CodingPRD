"""Serialize entities to JSON-friendly dicts with computed fields."""
from decimal import Decimal

from db import num
from services import core


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def client_out(c):
    out = _common(c)
    out.update({
        "full_name": c["full_name"],
        "email": c["email"],
        "state_code": c["state_code"],
        "refunded_to_client_cents": c["refunded_to_client_cents"],
    })
    return out


def program_out(p):
    # Lazily expire offers, then recompute standing.
    core.expire_program_offers(p["id"])
    standing = core.recompute_account_standing(p)
    total_enrolled = core.total_enrolled_balance(p["id"])
    out = _common(p)
    out.update({
        "client_id": p["client_id"],
        "program_phase": p["program_phase"],
        "account_standing": standing,
        "target_settlement_pct": num(Decimal(str(p["target_settlement_pct"]))),
        "monthly_deposit_amount": num(Decimal(str(p["monthly_deposit_amount"]))),
        "deposit_day_of_month": p["deposit_day_of_month"],
        "total_enrolled_balance": num(total_enrolled),
        "fee_tier_pct": num(core.fee_tier_for_total(total_enrolled)),
        "missed_deposit_count": core.missed_deposit_count(p["id"]),
        "estimated_total_savings": num(core.estimated_total_savings(p)),
        "realized_total_savings": num(core.realized_total_savings(p)),
        "completion_eligible": core.completion_eligible(p),
    })
    return out


def account_out(a):
    pid = a["program_id"]
    out = _common(a)
    out.update({
        "program_id": pid,
        "balance": num(core.account_balance(pid)),
        "lifetime_deposited": num(core.lifetime_deposited(pid)),
        "lifetime_disbursed": num(core.lifetime_disbursed(pid)),
        "reserve_floor": num(Decimal(str(a["reserve_floor"]))),
    })
    return out


def debt_out(d):
    out = _common(d)
    orig = Decimal(str(d["original_balance"]))
    settled = Decimal(str(d["settled_amount"]))
    forgiven = Decimal(str(d["forgiven_amount"]))
    if d["status"] == "SETTLED":
        current = orig - settled - forgiven
    else:
        current = orig
    out.update({
        "program_id": d["program_id"],
        "creditor_name": d["creditor_name"],
        "account_number": d["account_number"],
        "original_balance": num(orig),
        "current_balance": num(current),
        "settled_amount": num(settled),
        "forgiven_amount": num(forgiven),
        "fee_rate_pct": num(Decimal(str(d["fee_rate_pct"]))),
        "status": d["status"],
        "settled_offer_id": d["settled_offer_id"],
    })
    return out


def deposit_out(d):
    out = _common(d)
    out.update({
        "program_id": d["program_id"],
        "scheduled_for": d["scheduled_for"],
        "amount": num(Decimal(str(d["amount"]))),
        "status": d["status"],
    })
    return out


def offer_out(o):
    core.expire_offer_if_due(o)
    out = _common(o)
    out.update({
        "program_id": o["program_id"],
        "debt_id": o["debt_id"],
        "offer_pct": num(Decimal(str(o["offer_pct"]))),
        "settlement_amount": num(Decimal(str(o["settlement_amount"]))),
        "projected_fee": num(Decimal(str(o["projected_fee"]))),
        "due_date": o["due_date"],
        "status": o["status"],
    })
    return out


def settlement_out(s):
    out = _common(s)
    out.update({
        "program_id": s["program_id"],
        "offer_id": s["offer_id"],
        "debt_id": s["debt_id"],
        "funded_amount": num(Decimal(str(s["funded_amount"]))),
        "forgiven_amount": num(Decimal(str(s["forgiven_amount"]))),
        "status": s["status"],
    })
    return out


def fee_out(f):
    out = _common(f)
    out.update({
        "program_id": f["program_id"],
        "settlement_id": f["settlement_id"],
        "amount": num(Decimal(str(f["amount"]))),
        "status": f["status"],
    })
    return out


def lawsuit_out(lw):
    out = _common(lw)
    out.update({
        "program_id": lw["program_id"],
        "debt_id": lw["debt_id"],
        "court_reference": lw["court_reference"],
        "filed_at": lw["filed_at"],
        "status": lw["status"],
    })
    return out


def tax_event_out(t):
    out = _common(t)
    out.update({
        "program_id": t["program_id"],
        "source_settlement_id": t["source_settlement_id"],
        "forgiven_amount": num(Decimal(str(t["forgiven_amount"]))),
        "tax_year": t["tax_year"],
        "reportable": t["reportable"],
        "status": t["status"],
    })
    return out
