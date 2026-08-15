"""Business calculations (scaffold section 1.3 / PRD section 3)."""
from datetime import timedelta
from decimal import Decimal

import clock
import db
import util

GESTATION_DAYS = {"SHEEP": 147, "GOAT": 150}

GREASY_PRICE_CENTS = {"SUPERFINE": 380, "FINE": 330, "MEDIUM": 260, "STRONG": 190, "COARSE": 120}
CLEAN_PRICE_CENTS = {"SUPERFINE": 720, "FINE": 640, "MEDIUM": 520, "STRONG": 400, "COARSE": 280}

ADVANCE_RATE = Decimal("0.70")
AUCTION_COMMISSION_PCT = Decimal("3.5")
AUCTION_COMMISSION_CAP_CENTS = 15000
BONUS_PCT = Decimal("0.10")
BONUS_CAP_CENTS = 250000
BREACH_PENALTY_PCT = Decimal("0.20")
RESISTANCE_THRESHOLD_PCT = Decimal("80.0")


# ---------------------------------------------------------------- flock ledger
def flock_headcount(flock_id):
    """PRD 2.10: baseline + born_alive - verified losses - delivered sales."""
    f = db.STORE["flocks"][flock_id]
    h = f["baseline_headcount"]
    season_ids = {s["id"] for s in db.STORE["seasons"].values() if s["flock_id"] == flock_id}
    h += sum(b["born_alive"] for b in db.STORE["births"].values() if b["season_id"] in season_ids)
    h -= sum(l["head_lost"] for l in db.STORE["losses"].values()
             if l["flock_id"] == flock_id and l["report_status"] == "VERIFIED")
    for s in db.STORE["sales"].values():
        if s["flock_id"] == flock_id and s["delivery_status"] == "DELIVERED":
            if s["sale_type"] == "MEAT":
                h -= s["head_count"]
            else:
                h -= s["actual_head_delivered"] or 0
    return h


def flock_withdrawal_until(flock_id):
    """Latest treatment withdrawal strictly after the logical clock; null when none."""
    now = clock.now()
    live = [t["withdrawal_until"] for t in db.STORE["treatments"].values()
            if t["flock_id"] == flock_id and t["withdrawal_until"] > now]
    return max(live) if live else None


# ------------------------------------------------------------------ seasons
def season_totals(season):
    recs = [b for b in db.STORE["births"].values() if b["season_id"] == season["id"]]
    total_born = sum(b["births_reported"] for b in recs)
    total_alive = sum(b["born_alive"] for b in recs)
    rate = util.round1(Decimal(total_alive) / Decimal(season["ewes_bred"]) * Decimal(100))
    return total_born, total_alive, rate


def lambing_window_end(season):
    return season["expected_lambing_start"] + timedelta(days=45)


# ------------------------------------------------------------------ pastures
def pasture_occupied_head(pasture_id):
    return sum(m["head_count"] for m in db.STORE["moves"].values()
               if m["pasture_id"] == pasture_id and m["move_status"] == "ACTIVE")


def pasture_status(pasture):
    occupied = pasture_occupied_head(pasture["id"])
    if occupied > 0:
        return "OCCUPIED", occupied
    completed = [m for m in db.STORE["moves"].values()
                 if m["pasture_id"] == pasture["id"] and m["move_status"] == "COMPLETED"]
    if completed:
        latest = max(completed, key=lambda m: (m["move_end"], m["updated_at"]))
        if clock.now() < latest["move_end"] + timedelta(days=pasture["rest_days"]):
            return "RESTING", occupied
    return "AVAILABLE", occupied


# ------------------------------------------------------------------ treatments
def treatment_efficacy(treatment):
    before = treatment["fecal_egg_count_before"]
    after = treatment["fecal_egg_count_after"]
    if after is None or before == 0:
        return None, False
    eff = util.round1(Decimal(before - after) / Decimal(before) * Decimal(100))
    return eff, (eff < RESISTANCE_THRESHOLD_PCT)


# ------------------------------------------------------------------ wool
def grade_classify(micron):
    """Lower bounds inclusive (PRD 3.4)."""
    if micron < Decimal("19.5"):
        return "SUPERFINE"
    if micron < Decimal("21.5"):
        return "FINE"
    if micron < Decimal("24.5"):
        return "MEDIUM"
    if micron < Decimal("27.5"):
        return "STRONG"
    return "COARSE"


def lot_effective_micron(lot):
    return lot["certified_micron"] if lot["certified_micron"] is not None else lot["estimated_micron"]


def lot_grade_code(lot):
    m = lot_effective_micron(lot)
    return grade_classify(m) if m is not None else None


def lot_effective_value(lot):
    if lot["certified_value_cents"] is not None:
        return lot["certified_value_cents"]
    return lot["provisional_value_cents"]


def provisional_value(lot):
    """weight_lbs * greasy-lb price of the grade banded from estimated micron."""
    grade = grade_classify(lot["estimated_micron"])
    return util.cents(lot["weight_lbs"] * Decimal(GREASY_PRICE_CENTS[grade]))


def certified_value(lot, measured_micron, clean_yield_pct):
    """clean lbs kept at full precision; rounded once at the final cent amount."""
    grade = grade_classify(measured_micron)
    clean_lbs = lot["weight_lbs"] * clean_yield_pct / Decimal(100)
    return util.cents(clean_lbs * Decimal(CLEAN_PRICE_CENTS[grade])), grade


def clip_aggregates(clip):
    lots = [l for l in db.STORE["lots"].values() if l["clip_id"] == clip["id"]]
    allocated = sum((l["weight_lbs"] for l in lots), Decimal("0"))
    unallocated = clip["greasy_weight_lbs"] - clip["skirtings_weight_lbs"] - allocated
    value = sum((lot_effective_value(l) or 0) for l in lots)
    if not lots:
        posture = "UNGRADED"
    elif any(l["lot_status"] in ("CONSIGNED", "SOLD") for l in lots):
        posture = "MARKETING"
    elif all(l["lot_status"] == "SETTLED" for l in lots) and unallocated == 0:
        posture = "SETTLED_OUT"
    else:
        posture = "GRADING"
    return allocated, unallocated, value, posture


# ------------------------------------------------------------------ consignments
def advance_amount(lot):
    return util.cents(ADVANCE_RATE * Decimal(lot_effective_value(lot)))


def pool_fee_cents(pool_ref, sale_gross_cents):
    """Tiered on total consigned lbs across the pool's open/settled consignments."""
    total_lbs = Decimal("0")
    for c in db.STORE["consignments"].values():
        if c["pool_ref"] == pool_ref and c["consignment_status"] in ("ACCEPTED", "ADVANCED", "SOLD", "SETTLED"):
            total_lbs += db.STORE["lots"][c["lot_id"]]["weight_lbs"]
    if total_lbs < Decimal("10000"):
        tier = Decimal("6.5")
    elif total_lbs < Decimal("25000"):
        tier = Decimal("5.0")
    else:
        tier = Decimal("4.0")
    return util.cents(Decimal(sale_gross_cents) * tier / Decimal(100))


def pool_statement(pool_ref):
    rows = [c for c in db.STORE["consignments"].values() if c["pool_ref"] == pool_ref]
    if not rows:
        return None
    settled = [c for c in rows if c["consignment_status"] == "SETTLED"]
    return {
        "pool_ref": pool_ref,
        "consignment_count": len(settled),
        "total_sale_gross_cents": sum(c["sale_gross_cents"] for c in settled),
        "total_pool_fee_cents": sum(c["pool_fee_cents"] for c in settled),
        "total_advance_cents": sum(c["advance_cents"] for c in settled),
        "total_settlement_cents": sum(c["settlement_cents"] for c in settled),
    }


# ------------------------------------------------------------------ sales
def select_holiday_window(scheduled_date):
    """Half-open eligibility; rank by premium desc, then window_start, then created_at."""
    eligible = [w for w in db.STORE["holidays"].values()
                if w["window_start"] <= scheduled_date < w["window_end"]]
    if not eligible:
        return None
    eligible.sort(key=lambda w: (-w["premium_pct"], w["window_start"], w["created_at"], w["seq"]))
    return eligible[0]


def sale_gross_meat(head_count, avg_weight_lbs, base_price_cwt, shrink_pct, channel,
                    actual_total_weight_lbs=None):
    shrink_factor = (Decimal(1) - shrink_pct / Decimal(100)) if channel == "DIRECT" else Decimal(1)
    if actual_total_weight_lbs is None:
        gross = (Decimal(head_count) * avg_weight_lbs * shrink_factor
                 * Decimal(base_price_cwt) / Decimal(100))
    else:
        gross = actual_total_weight_lbs * shrink_factor * Decimal(base_price_cwt) / Decimal(100)
    return util.cents(gross)


def sale_total(gross_cents, channel, premium_pct_applied):
    premium = 0
    if channel == "ETHNIC_MARKET":
        premium = util.cents(Decimal(gross_cents) * premium_pct_applied / Decimal(100))
    commission = 0
    if channel == "AUCTION":
        commission = min(util.cents(Decimal(gross_cents) * AUCTION_COMMISSION_PCT / Decimal(100)),
                         AUCTION_COMMISSION_CAP_CENTS)
    return gross_cents + premium - commission


# ------------------------------------------------------------------ contracts
def grazing_invoice(contract):
    """head_days over COMPLETED moves only; window-clamped whole days."""
    head_days = 0
    for m in db.STORE["moves"].values():
        if m["contract_id"] != contract["id"] or m["move_status"] != "COMPLETED":
            continue
        start = max(m["move_start"], contract["service_window_start"])
        end = min(m["move_end"], contract["service_window_end"])
        head_days += m["head_count"] * util.whole_days(start, end)
    gross = head_days * contract["rate_per_head_day_cents"]
    bonus = 0
    if contract["achieved_cover_reduction_pct"] >= contract["target_cover_reduction_pct"]:
        bonus = min(util.cents(BONUS_PCT * Decimal(gross)), BONUS_CAP_CENTS)
    penalty = util.cents(BREACH_PENALTY_PCT * Decimal(gross)) if contract["breach_flag"] else 0
    return head_days, gross + bonus - penalty
