"""Calculation rules (SCAFFOLD §1.3): credit valuation, partner scores, posture."""
from decimal import Decimal, ROUND_HALF_UP

from db import store

# --- constants (SCAFFOLD §1.3) ---
RATE_CENTS_PER_KG = {"RESALE": 120, "RECYCLE": 45, "FIBER": 20}
CONTAM_MULT = {
    "NONE": Decimal("1.0"),
    "MINOR": Decimal("0.9"),
    "MAJOR": Decimal("0.5"),
    "SEVERE": Decimal("0.0"),
}
BULK_THRESHOLD_KG = Decimal("20.0")
BULK_BONUS_CENTS = 500
SPONSOR_BONUS_PCT = Decimal("0.10")
EST_KG_PER_BAG = Decimal("4.0")
VEHICLE_CAPACITY_KG = Decimal("800.0")
SCORE_FLOOR = 40
PENALTY = {"SEVERE": 20, "MAJOR": 15, "MINOR": 0}
WINDOW_DAYS = 30
DECAY_HALF_LIFE_DAYS = 30
STRIKE_LIMIT = 3
MAX_RESCHEDULES = 3
MAX_REBOOKS = 2
FULL_THRESHOLD_PCT = Decimal("85.0")
FILLING_THRESHOLD_PCT = Decimal("50.0")

SEVERITY_ORDER = {"NONE": 0, "MINOR": 1, "MAJOR": 2, "SEVERE": 3}


def dec(value):
    """Decimal from a JSON number without float artifacts."""
    return Decimal(str(value))


def rhu_int(d):
    """Round-half-up a Decimal to integer cents."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num_out(d):
    """Decimal -> int when integral else float (for JSON output)."""
    d = Decimal(d)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def credit_value(weight_kg, grade, severity, fund_available=None):
    """diversion_credit_value: pinned order base -> contam -> bulk -> bonus -> total.

    Returns (value_cents, after_contam, bulk_bonus, sponsor_bonus).
    When fund_available is None the sponsor bonus is uncapped (projected variant).
    """
    w = dec(weight_kg)
    base = rhu_int(w * RATE_CENTS_PER_KG[grade])
    after_contam = rhu_int(Decimal(base) * CONTAM_MULT[severity])
    bulk_bonus = BULK_BONUS_CENTS if w >= BULK_THRESHOLD_KG else 0
    uncapped_bonus = rhu_int(SPONSOR_BONUS_PCT * Decimal(after_contam))
    if fund_available is None:
        sponsor_bonus = uncapped_bonus
    else:
        headroom = max(0, fund_available - after_contam - bulk_bonus)
        sponsor_bonus = min(uncapped_bonus, headroom)
    return after_contam + bulk_bonus + sponsor_bonus, after_contam, bulk_bonus, sponsor_bonus


def projected_credit_cents(provisional_weight_kg):
    """projected_credit_cents_rule: provisional weight, RECYCLE, NONE, uncapped."""
    total, _, _, _ = credit_value(provisional_weight_kg, "RECYCLE", "NONE", None)
    return total


def est_weight(bags_claimed):
    """estimated_pickup_weight: bags * 4.0, exact to 1 decimal."""
    return float(dec(bags_claimed) * EST_KG_PER_BAG)


def partner_report_events(partner_id):
    """UPHELD reports on tickets holding an ACCEPTED/COMPLETED assignment to partner."""
    events = []
    for rep in store.reports.values():
        if rep.get("outcome") != "UPHELD":
            continue
        ticket_id = rep["ticket_id"]
        for a in store.assignments.values():
            if (a["ticket_id"] == ticket_id and a["partner_id"] == partner_id
                    and a["status"] in ("ACCEPTED", "COMPLETED")):
                events.append(rep)
                break
    return events


def partner_scores(partner_id, now):
    """partner_quality_scores: dual variant (rolling window + decay weighted).

    Returns (routing_score:int, report_score:float 2dp).
    """
    from datetime import timedelta
    events = partner_report_events(partner_id)
    lower = now - timedelta(days=WINDOW_DAYS)
    routing_sum = 0
    decay_sum = 0.0
    for rep in events:
        pen = PENALTY[rep["severity"]]
        at = rep["_adjudicated_at"]
        if lower <= at <= now:
            routing_sum += pen
        age_days = (now - at).total_seconds() / 86400.0
        decay_sum += pen * (0.5 ** (age_days / float(DECAY_HALF_LIFE_DAYS)))
    routing_score = max(0, 100 - routing_sum)
    report_raw = max(0.0, 100.0 - decay_sum)
    report_score = float(Decimal(str(report_raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return routing_score, report_score


def posture_for(fill_pct):
    """dropbox_fill_posture thresholds (inclusive >=)."""
    d = dec(fill_pct)
    if d >= FULL_THRESHOLD_PCT:
        return "FULL_PENDING_COLLECTION"
    if d >= FILLING_THRESHOLD_PCT:
        return "FILLING"
    return "OK"


def charity_split_lines(gross_cents, splits, charities_by_id):
    """charity_split_allocation: floor each line first, remainder assigned later.

    Returns (lines, remainder) where lines are [{charity_id, pct, amount_cents}]
    ordered by the charity's created_at ASC.
    """
    def charity_key(line):
        ch = charities_by_id.get(line["charity_id"])
        return (ch["created_at"], ch["_seq"]) if ch else ("", 0)

    lines = []
    for line in sorted(splits, key=charity_key):
        amount = (gross_cents * line["pct"]) // 100  # integer floor per line
        lines.append({"charity_id": line["charity_id"], "pct": line["pct"],
                      "amount_cents": amount})
    remainder = gross_cents - sum(l["amount_cents"] for l in lines)
    return lines, remainder
