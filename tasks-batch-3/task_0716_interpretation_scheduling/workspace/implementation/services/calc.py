import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from errors import err
from clock import parse_iso
from services import constants as C


def find_active_rate_plan(client_id, tier, modality):
    for rp in db.rate_plans.values():
        if (rp["client_id"] == client_id and rp["certification_tier"] == tier
                and rp["modality"] == modality and rp["active"]):
            return rp
    return None


def round_half_up_cents(amount_decimal):
    return int(amount_decimal.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def estimated_min_charge(plan, modality):
    charge = plan["min_block_units"] * plan["rate_cents"]
    if modality == "ONSITE":
        charge += plan["travel_surcharge_cents"]
    return charge


def session_billing(plan, modality, duration_seconds):
    """Return (billed_units, billed_amount_cents) from elapsed duration."""
    if plan["billing_mode"] == "PER_MINUTE":
        raw_units = math.ceil(duration_seconds / 60)
        billed_units = max(raw_units, plan["min_block_units"])
        amount = billed_units * plan["rate_cents"]
    else:  # PER_HOUR
        raw_units = math.ceil(duration_seconds / 3600)
        billed_units = max(raw_units, plan["min_block_units"])
        amount = billed_units * plan["rate_cents"]
        if modality == "ONSITE":
            amount += plan["travel_surcharge_cents"]
    return billed_units, amount


def reconcile_billing(plan, modality, corrected_units):
    """Corrected units already whole; floor to min_block, apply rate + surcharge."""
    billed_units = max(corrected_units, plan["min_block_units"])
    amount = billed_units * plan["rate_cents"]
    if plan["billing_mode"] == "PER_HOUR" and modality == "ONSITE":
        amount += plan["travel_surcharge_cents"]
    elif plan["billing_mode"] == "PER_MINUTE":
        pass
    return billed_units, amount


def cancellation_fee(request, plan):
    """Compute cancellation fee in integer cents."""
    modality = request["modality"]
    if request["scheduling_mode"] == "ON_DEMAND":
        return 0
    base = estimated_min_charge(plan, modality)
    window_start = parse_iso(request["window_start"])
    now = db.clock.now()
    lead_seconds = (window_start - now).total_seconds()
    if lead_seconds >= C.LATE_CANCEL_WINDOW_SECONDS:
        return 0
    elif lead_seconds >= 0:
        return round_half_up_cents(Decimal(base) * Decimal(C.LATE_CANCEL_PCT))
    else:
        return round_half_up_cents(Decimal(base) * Decimal(C.NO_SHOW_PCT))


def no_show_fee(plan, modality):
    base = estimated_min_charge(plan, modality)
    return round_half_up_cents(Decimal(base) * Decimal(C.NO_SHOW_PCT))


def rating_aggregate(interpreter_id):
    ratings = [r for r in db.ratings.values() if r["interpreter_id"] == interpreter_id]
    count = len(ratings)
    if count == 0:
        return None, 0
    total = sum(r["score"] for r in ratings)
    avg = (Decimal(total) / Decimal(count)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(avg), count


def acceptance_pct(interpreter_id):
    """Percentage of offers ACCEPTED against (accepted + declined + expired)."""
    accepted = 0
    total = 0
    for a in db.assignments.values():
        if a["interpreter_id"] != interpreter_id:
            continue
        if a.get("_was_accepted"):
            accepted += 1
            total += 1
        elif a["lifecycle_status"] in ("DECLINED", "EXPIRED"):
            total += 1
    if total == 0:
        return 100
    return float((Decimal(accepted * 100) / Decimal(total)))


def selection_score(interp):
    if interp["rating_count"] > 0:
        rating_for = Decimal(str(interp["rating_avg"]))
    else:
        rating_for = Decimal(C.DEFAULT_RATING)
    load_ratio = Decimal(interp["active_load"]) / Decimal(interp["max_concurrent_load"])
    score = (rating_for * Decimal(100) * Decimal(C.W_RATING)
             + Decimal(str(interp["acceptance_pct"])) * Decimal(C.W_ACCEPT)
             + (Decimal(1) - load_ratio) * Decimal(100) * Decimal(C.W_LOAD))
    return score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
