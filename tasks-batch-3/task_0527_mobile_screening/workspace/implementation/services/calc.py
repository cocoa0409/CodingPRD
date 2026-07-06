"""Calculation rules (SCAFFOLD §1.3, PRD §2.8-2.9, §3)."""
from decimal import Decimal, ROUND_HALF_UP
from db import db
from services.common import round_half_up

MODALITY_PRICE_CENTS = {
    "MAMMOGRAPHY": 20000,
    "BLOOD_PANEL": 8000,
    "BONE_DENSITY": 12000,
    "SKIN": 6000,
}
INSURANCE_ESTIMATE_COINSURANCE = Decimal("0.20")
DEPLETION_FLOOR_CENTS = 0
NO_SHOW_STRIKE_LIMIT = 3
URGENT_SLA_DAYS = 7
ROUTINE_SLA_DAYS = 30


# ---------------- Grant depletion (§2.8, calc grant_depletion) ----------------

def recompute_grant(grant):
    """Recompute committed/settled/remaining/is_depleted from live charges."""
    committed = 0
    settled = 0
    for ch in db.charges.values():
        if ch.get("grant_id") != grant["id"]:
            continue
        gc = ch.get("grant_covered_cents") or 0
        if ch["status"] in ("DRAFT", "ADJUDICATED", "SETTLED"):
            committed += gc
        if ch["status"] == "SETTLED":
            settled += gc
    grant["committed_cents"] = committed
    grant["settled_cents"] = settled
    grant["remaining_cents"] = grant["total_budget_cents"] - committed
    grant["is_depleted"] = grant["remaining_cents"] <= DEPLETION_FLOOR_CENTS
    return grant


# ---------------- Patient responsibility (calc patient_responsibility) --------

def provisional_responsibility(pay_type, list_price, grant_remaining):
    """Returns (grant_covered_cents, provisional_patient_responsibility_cents)."""
    if pay_type == "SELF_PAY":
        return 0, list_price
    if pay_type == "INSURANCE":
        est = round_half_up(Decimal(list_price) * INSURANCE_ESTIMATE_COINSURANCE)
        return 0, est
    if pay_type == "GRANT":
        covered = min(list_price, grant_remaining)
        if covered < 0:
            covered = 0
        return covered, list_price - covered
    raise ValueError("bad pay_type")


def finalized_responsibility(pay_type, list_price, insurance_allowed, grant_covered):
    if pay_type == "SELF_PAY":
        return list_price
    if pay_type == "INSURANCE":
        return list_price - insurance_allowed
    if pay_type == "GRANT":
        return list_price - grant_covered
    raise ValueError("bad pay_type")


# ---------------- Referral priority (calc referral_priority) ------------------

def referral_priority_and_due(flagged_urgent, event_date):
    from datetime import date, timedelta
    priority = "URGENT" if flagged_urgent else "ROUTINE"
    sla = URGENT_SLA_DAYS if priority == "URGENT" else ROUTINE_SLA_DAYS
    y, m, d = (int(x) for x in event_date.split("-"))
    due = date(y, m, d) + timedelta(days=sla)
    return priority, due.isoformat()
