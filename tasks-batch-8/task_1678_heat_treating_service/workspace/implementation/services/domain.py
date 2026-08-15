"""Business logic: posture derivation, schedule gates, pinned calculations, cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store, touch
from errors import ApiError

# ---------------------------------------------------------------------------
# Constants (PRD §3, scaffold calculations)
# ---------------------------------------------------------------------------
QUENCH_MEDIA = ["OIL", "WATER", "POLYMER", "AIR", "GAS"]
FURNACE_CLASSES = ["CLASS_1", "CLASS_2", "CLASS_3", "CLASS_5"]
CLASS_RANK = {"CLASS_1": 1, "CLASS_2": 2, "CLASS_3": 3, "CLASS_5": 5}
TUS_INTERVAL_DAYS = {"CLASS_1": 30, "CLASS_2": 60, "CLASS_3": 90, "CLASS_5": 180}
CALIBRATION_INTERVAL_DAYS = 90

RUSH_BASE_CENTS = 15000
RUSH_PCT = Decimal("0.20")
RUSH_MIN_CENTS = 25000
RUSH_CAP_CENTS = 200000
EXPEDITE_THRESHOLD_HOURS = 24
EXPEDITE_MULT = Decimal("1.5")

STANDARD_LIABILITY_MULT = 3
EXTENDED_RATE_CENTS_PER_LB = 85
ENERGY_RATE_CENTS_PER_LB = 133

PURGE_GAP_SECONDS = 60 * 60  # 60 minutes

LIABILITY_TIERS = ["STANDARD", "EXTENDED"]
SERVICE_LANES = ["STANDARD", "RUSH"]
RECORD_TYPES = ["TUS", "INSTRUMENT_CALIBRATION"]
RESULTS = ["PASS", "FAIL"]
DECISIONS = ["RE_TREAT", "SCRAP", "RETURN_AS_IS"]


# ---------------------------------------------------------------------------
# Numeric helpers (money is integer cents; round-half-up at each marked step)
# ---------------------------------------------------------------------------
def _cents(d):
    """Decimal -> whole-cent integer, round half up."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(v):
    """Exact Decimal view of a JSON number."""
    return Decimal(str(v))


def num_out(d):
    """Decimal -> int when integral else float (weights, up to 3 decimals)."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Rush surcharge (calculations.rush_surcharge_quote)
# ---------------------------------------------------------------------------
def rush_quote(processing_charge_cents, guaranteed_turnaround_hours):
    base = RUSH_BASE_CENTS + _cents(RUSH_PCT * dec(processing_charge_cents))
    if guaranteed_turnaround_hours <= EXPEDITE_THRESHOLD_HOURS:
        base = _cents(dec(base) * EXPEDITE_MULT)
    return max(RUSH_MIN_CENTS, min(RUSH_CAP_CENTS, base))


# ---------------------------------------------------------------------------
# Liability payout (calculations.liability_payout)
# ---------------------------------------------------------------------------
def liability_payout(work_order, customer):
    if customer["liability_tier"] == "EXTENDED":
        rounded = _cents(dec(EXTENDED_RATE_CENTS_PER_LB) * dec(work_order["received_weight_lb"]))
        return min(work_order["declared_value_cents"], rounded)
    return min(work_order["declared_value_cents"],
               STANDARD_LIABILITY_MULT * work_order["processing_charge_cents"])


# ---------------------------------------------------------------------------
# Energy surcharge (calculations.energy_surcharge_settlement) — per-order line
# ---------------------------------------------------------------------------
def energy_surcharge_for(work_order):
    return _cents(dec(ENERGY_RATE_CENTS_PER_LB) * dec(work_order["received_weight_lb"]))


# ---------------------------------------------------------------------------
# Customer liability exposure (entities.CustomerAccount.outstanding_*)
# ---------------------------------------------------------------------------
def recompute_exposure(customer):
    total = sum(c["payout_cents"] for c in store.liability_claims.values()
                if c["customer_id"] == customer["id"] and c["status"] in ("PENDING", "ACCEPTED"))
    if total != customer["outstanding_liability_exposure_cents"]:
        customer["outstanding_liability_exposure_cents"] = total
        touch(customer)


# ---------------------------------------------------------------------------
# Load weight (calculations.load_weight_utilization)
# ---------------------------------------------------------------------------
def active_assignments(load_id):
    return [a for a in store.load_assignments.values()
            if a["load_batch_id"] == load_id and a["status"] == "ACTIVE"]


def load_weight(load_id):
    total = Decimal("0")
    for a in active_assignments(load_id):
        wo = store.work_orders.get(a["work_order_id"])
        if wo is not None:
            total += dec(wo["received_weight_lb"])
    return total


def recompute_load_weight(load):
    load["total_weight_lb"] = num_out(load_weight(load["id"]))


# ---------------------------------------------------------------------------
# Pyrometry (calculations.pyrometry_next_due) and posture (furnace_qualification_posture)
# ---------------------------------------------------------------------------
def pyrometry_next_due(record_type, furnace_class, performed_at):
    if record_type == "TUS":
        days = TUS_INTERVAL_DAYS[furnace_class]
    else:
        days = CALIBRATION_INTERVAL_DAYS
    return performed_at + timedelta(days=days)


def _latest_record(furnace_id, record_type, require_pass=False):
    cand = [r for r in store.pyrometry_records.values()
            if r["furnace_id"] == furnace_id and r["record_type"] == record_type
            and (not require_pass or r["result"] == "PASS")]
    if not cand:
        return None
    # greatest performed_at; tie-break: greatest created_at, then insertion order
    return max(cand, key=lambda r: (r["performed_at"], r["created_at"], r["_seq"]))


def recompute_posture(furnace):
    """Recompute qualification_status against the logical clock; fire HOLD cascades
    whenever the posture leaves or returns to QUALIFIED (PRD §2.7 / §3.3)."""
    now = db.clock()
    tus = _latest_record(furnace["id"], "TUS")
    cal = _latest_record(furnace["id"], "INSTRUMENT_CALIBRATION")
    tus_pass = _latest_record(furnace["id"], "TUS", require_pass=True)
    cal_pass = _latest_record(furnace["id"], "INSTRUMENT_CALIBRATION", require_pass=True)

    if (tus is None or tus["result"] == "FAIL") or (cal is None or cal["result"] == "FAIL"):
        new = "UNQUALIFIED"
    elif tus["next_due_at"] < now:
        new = "SURVEY_OVERDUE"
    elif cal["next_due_at"] < now:
        new = "CALIBRATION_OVERDUE"
    else:
        new = "QUALIFIED"

    old = furnace.get("qualification_status", "UNQUALIFIED")
    furnace["qualification_status"] = new
    furnace["current_tus_due_at"] = tus_pass["next_due_at"] if tus_pass else None
    furnace["current_calibration_due_at"] = cal_pass["next_due_at"] if cal_pass else None

    if old == "QUALIFIED" and new != "QUALIFIED":
        for lb in store.load_batches.values():
            if lb["furnace_id"] == furnace["id"] and lb["status"] == "BUILDING":
                lb["status"] = "HOLD"
                touch(lb)
    elif old != "QUALIFIED" and new == "QUALIFIED":
        for lb in store.load_batches.values():
            if lb["furnace_id"] == furnace["id"] and lb["status"] == "HOLD":
                lb["status"] = "BUILDING"
                touch(lb)
    return new


# ---------------------------------------------------------------------------
# Furnace schedule gates (overlap + quench purge gap)
# ---------------------------------------------------------------------------
def check_schedule(furnace_id, recipe, start, end, exclude_load_id=None):
    """Tier-8 temporal gate vs loads in {RELEASED, RUNNING, COMPLETED} on this furnace."""
    committed = [lb for lb in store.load_batches.values()
                 if lb["furnace_id"] == furnace_id
                 and lb["status"] in ("RELEASED", "RUNNING", "COMPLETED")
                 and lb["id"] != exclude_load_id]
    for other in committed:
        o_start, o_end = other["scheduled_start_at"], other["scheduled_end_at"]
        if start < o_end and o_start < end:
            raise ApiError("ERR_FURNACE_SCHEDULE_OVERLAP", 409,
                           "Load window overlaps another committed load on this furnace")
    for other in committed:
        other_recipe = store.recipes.get(other["recipe_id"])
        if other_recipe is None or other_recipe["quench_media"] == recipe["quench_media"]:
            continue
        o_start, o_end = other["scheduled_start_at"], other["scheduled_end_at"]
        if start >= o_end:
            gap = (start - o_end).total_seconds()
        elif o_start >= end:
            gap = (o_start - end).total_seconds()
        else:
            continue  # overlapping handled above
        if gap < PURGE_GAP_SECONDS:
            raise ApiError("ERR_QUENCH_PURGE_GAP_VIOLATION", 409,
                           "Adjacent loads with different quench media require a 60-minute purge gap")


def check_pyrometry_window(furnace, start, end):
    """Tier-8 containment of [start, end] in the latest PASS TUS and calibration
    validity intervals [performed_at, next_due_at]."""
    for record_type, label in (("TUS", "survey"), ("INSTRUMENT_CALIBRATION", "calibration")):
        latest_pass = _latest_record(furnace["id"], record_type, require_pass=True)
        if latest_pass is None:
            raise ApiError("ERR_PYROMETRY_WINDOW_VIOLATION", 422,
                           "No passing %s on this furnace" % label)
        if start < latest_pass["performed_at"] or end > latest_pass["next_due_at"]:
            raise ApiError("ERR_PYROMETRY_WINDOW_VIOLATION", 422,
                           "Load window is not contained in the latest PASS %s validity interval" % label)
