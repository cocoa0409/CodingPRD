"""Domain services: lazy derivations, calculations, cross-entity cascades.

Implements SCAFFOLD §1.3 calculation rules with exact precision/rounding:
  animal_unit_factor (4dp), grazing_aum_demand (2dp), effective_pasture_capacity (2dp),
  ranch_production_pct_and_posture (1dp), destock_required_reduction (single pass),
  lease_usage_measurement (2dp), lease_settlement_charge (2dp, two variants),
  adjusted_205d_weight (1dp, two variants), sale_lot_settlement (2dp, pinned order),
  pregnancy_rate (1dp), supplement_costs (2dp).
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from core import (
    CLOCK, db, d1, d2, d4, dec, num, date_str,
)

# --- Constants from SCAFFOLD §1.3 -------------------------------------------
REF_WEIGHT_LBS = Decimal("1000")
WEIGHT_AU_COEF = Decimal("0.30")
BASE_AU = {
    "MATURE_COW": Decimal("1.00"),
    "REPLACEMENT_HEIFER": Decimal("0.70"),
    "GROWING": Decimal("0.75"),
}
DAYS_PER_AUM_MONTH = Decimal("30")
SEASON_MONTHS = Decimal("5")

POSTURE_FACTOR = {
    "NORMAL": Decimal("1.00"),
    "WATCH": Decimal("0.85"),
    "ALERT": Decimal("0.70"),
    "CRITICAL": Decimal("0.50"),
}

COWS_PER_BULL = 25
BSE_VALIDITY_DAYS = 365
MIN_BULL_TURNAROUND_DAYS = 7
PRECON_MIN_WEAN_DAYS = 45
VACCINE_MIN_SPACING_DAYS = 14

DAM_ADJ = {2: Decimal("54"), 3: Decimal("20")}
DAM_ADJ_11_PLUS = Decimal("20")

PREMIUM = {"NONE": Decimal("0"), "ENROLLED": Decimal("250"), "CERTIFIED": Decimal("600")}
MIN_PRICE_CENTS_PER_CWT = Decimal("100")

PRECON_RANK = {"NONE": 0, "ENROLLED": 1, "CERTIFIED": 2}

# destock class priority: GROWING first, then MATURE_COW, then REPLACEMENT_HEIFER
DESTOCK_CLASS_PRIORITY = {"GROWING": 0, "MATURE_COW": 1, "REPLACEMENT_HEIFER": 2}

REDUCTION_REASONS = {"SALE", "CULL", "DEATH", "TRANSFER", "LIQUIDATION"}


# ===========================================================================
# Calculations
# ===========================================================================
def animal_unit_factor(animal_class: str, avg_weight_lbs) -> Decimal:
    base = BASE_AU[animal_class]
    excess = max(Decimal("0"), dec(avg_weight_lbs) - REF_WEIGHT_LBS)
    return d4(base * (Decimal("1") + excess / REF_WEIGHT_LBS * WEIGHT_AU_COEF))


def posture_for_pct(pct: Decimal) -> str:
    if pct >= Decimal("90"):
        return "NORMAL"
    if pct >= Decimal("75"):
        return "WATCH"
    if pct >= Decimal("55"):
        return "ALERT"
    return "CRITICAL"


def overlap_days_half_open(a_start: date, a_end: date, b_start: date, b_end: date) -> int:
    """Days of intersection between half-open windows [a_start,a_end) and [b_start,b_end)."""
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    if hi <= lo:
        return 0
    return (hi - lo).days


# ===========================================================================
# Lazy derivations / computed fields
# ===========================================================================
def refresh_pasture(p: dict) -> dict:
    """Recompute effective/committed/consumed/available + condition_status."""
    ranch = db.ranches.get(p["ranch_id"])
    posture = ranch["drought_posture"] if ranch else "NORMAL"
    factor = POSTURE_FACTOR[posture]
    p["effective_capacity_aum"] = num(d2(dec(p["base_capacity_aum"]) * factor))

    committed = Decimal("0")
    consumed = Decimal("0")
    for a in db.grazing_assignments.values():
        if a["pasture_id"] != p["id"]:
            continue
        if a["assignment_status"] == "ACTIVE":
            committed += dec(a["reserved_aum"])
        elif a["assignment_status"] in ("COMPLETED", "SHORTENED"):
            consumed += dec(a.get("consumed_aum") or 0)
    p["committed_aum"] = num(d2(committed))
    p["consumed_total_aum"] = num(d2(consumed))
    p["available_aum"] = num(d2(dec(p["effective_capacity_aum"]) - committed - consumed))

    if p.get("closed_flag"):
        p["condition_status"] = "CLOSED"
    else:
        ru = p.get("resting_until")
        if ru is not None and CLOCK.current_date() < ru:
            p["condition_status"] = "RESTING"
        else:
            p["condition_status"] = "GRAZEABLE"
    return p


def refresh_lease(lease: dict) -> dict:
    """Lazy expiry: ACTIVE lease past end_date reads EXPIRED."""
    if lease["lease_status"] == "ACTIVE" and CLOCK.current_date() > lease["end_date"]:
        lease["lease_status"] = "EXPIRED"
    return lease


def refresh_bull(b: dict) -> dict:
    """Lazy BSE expiry: PASSED -> EXPIRED when current_date > last_bse_date + validity."""
    if b.get("last_bse_result") == "PASSED" and b.get("last_bse_date") is not None:
        if CLOCK.current_date() > b["last_bse_date"] + timedelta(days=BSE_VALIDITY_DAYS):
            b["bse_status"] = "EXPIRED"
        else:
            b["bse_status"] = "PASSED"
    elif b.get("last_bse_result") == "FAILED":
        b["bse_status"] = "FAILED"
    else:
        b["bse_status"] = "UNTESTED"
    return b


def crop_reserved(crop: dict, cls: str) -> int:
    total = 0
    for lot in db.sale_lots.values():
        if lot["calf_crop_id"] != crop["id"]:
            continue
        if lot["lot_class"] != cls:
            continue
        if lot["lot_status"] in ("OFFERED", "CONTRACTED", "DELIVERED", "DISPUTED"):
            total += lot["head_count"]
    return total


def refresh_crop(c: dict) -> dict:
    c["reserved_steer_head"] = crop_reserved(c, "STEER")
    c["reserved_heifer_head"] = crop_reserved(c, "HEIFER")
    c["available_steer_head"] = (
        c["steer_head"] - c["death_loss_steer_head"]
        - c["reserved_steer_head"] - c["marketed_steer_head"]
    )
    c["available_heifer_head"] = (
        c["heifer_head"] - c["death_loss_heifer_head"]
        - c["reserved_heifer_head"] - c["marketed_heifer_head"]
        - c["retained_heifer_head"]
    )
    return c


def maybe_close_crop(c: dict):
    """Lifecycle bubble-up: ACTIVE -> CLOSED when fully accounted (§3.6)."""
    if c["lifecycle_status"] != "ACTIVE":
        return
    refresh_crop(c)
    if c["available_steer_head"] != 0 or c["available_heifer_head"] != 0:
        return
    open_statuses = {"DRAFT", "OFFERED", "CONTRACTED", "DELIVERED", "DISPUTED"}
    for lot in db.sale_lots.values():
        if lot["calf_crop_id"] == c["id"] and lot["lot_status"] in open_statuses:
            return
    c["lifecycle_status"] = "CLOSED"
    # bubble-up mutation bumps the crop version
    from core import touch
    touch(c)


# ===========================================================================
# Sale-lot settlement (§3.7, pinned order)
# ===========================================================================
def compute_settlement(lot: dict):
    pay_weight = d2(dec(lot["delivered_avg_weight_lbs"]) * (Decimal("1") - dec(lot["shrink_pct"])))
    slid = dec(lot["base_price_cents_per_cwt"]) + (dec(lot["base_weight_lbs"]) - pay_weight) * dec(lot["slide_cents_per_lb"])
    premium = PREMIUM[lot["precon_claim"]]
    final_price = d2(max(MIN_PRICE_CENTS_PER_CWT, slid) + premium)
    per_head_gross = d2(final_price * pay_weight / Decimal("100"))
    gross = per_head_gross * Decimal(lot["head_count"])  # round per head THEN multiply
    commission = d2(gross * dec(lot["commission_pct"]))
    freight = lot["head_count"] * lot["freight_cents_per_head"]
    net = gross - commission - Decimal(freight)
    lot["pay_weight_lbs"] = num(pay_weight)
    lot["final_price_cents_per_cwt"] = num(final_price)
    lot["per_head_gross_cents"] = num(per_head_gross)
    lot["gross_cents"] = num(gross)
    lot["commission_cents"] = num(commission)
    lot["freight_cents"] = freight
    lot["net_settlement_cents"] = num(net)


# ===========================================================================
# Lease statement charge (§3.2)
# ===========================================================================
def lease_usage(lease: dict, period_year: int) -> Decimal:
    window_start = date(period_year, 1, 1)
    window_end = date(period_year + 1, 1, 1)
    total = Decimal("0")
    for a in db.grazing_assignments.values():
        if a["pasture_id"] != lease["pasture_id"]:
            continue
        if a["assignment_status"] not in ("COMPLETED", "SHORTENED"):
            continue
        days_in = overlap_days_half_open(a["start_date"], a["actual_end_date"], window_start, window_end)
        if days_in <= 0:
            continue
        total += d2(dec(a["daily_demand_aum"]) * Decimal(days_in))
    return d2(total)


def lease_charges(lease: dict, actual_aum_used: Decimal):
    overage = max(Decimal("0"), actual_aum_used - dec(lease["aum_allotment"]))
    tier1 = min(overage, dec(lease["overage_tier1_cap_aum"]))
    tier2 = max(Decimal("0"), overage - dec(lease["overage_tier1_cap_aum"]))
    overage_charge = d2(tier1 * dec(lease["overage_tier1_rate_cents"]) + tier2 * dec(lease["overage_tier2_rate_cents"]))
    if lease["settlement_basis"] == "ALLOTMENT":
        base_charge = d2(dec(lease["aum_allotment"]) * dec(lease["rate_per_aum_cents"]))
    else:  # ACTUAL_USE
        base_charge = d2(max(actual_aum_used, dec(lease["minimum_commit_aum"])) * dec(lease["rate_per_aum_cents"]))
    total = d2(base_charge + overage_charge)
    return base_charge, overage_charge, total


# ===========================================================================
# Drought assessment preview figures (§3.8)
# ===========================================================================
def assessment_figures(ranch: dict, measurements: list):
    """Returns (ranch_production_pct Decimal(1dp), resulting_posture,
    monthly_supply_aum(2dp), monthly_demand_aum(2dp), deficit(2dp))."""
    pct_by_pid = {m["pasture_id"]: dec(m["production_pct_of_normal"]) for m in measurements}
    open_pastures = [p for p in db.pastures.values()
                     if p["ranch_id"] == ranch["id"] and not p.get("closed_flag")]
    weighted = Decimal("0")
    total_base = Decimal("0")
    for p in open_pastures:
        base = dec(p["base_capacity_aum"])
        weighted += base * pct_by_pid[p["id"]]
        total_base += base
    if total_base > 0:
        ranch_pct = d1(weighted / total_base)
    else:
        ranch_pct = d1(Decimal("100"))
    posture = posture_for_pct(ranch_pct)

    supply = Decimal("0")
    for p in open_pastures:
        supply += dec(p["base_capacity_aum"]) * POSTURE_FACTOR[posture]
    monthly_supply = d2(supply / SEASON_MONTHS)

    demand = Decimal("0")
    for g in db.herd_groups.values():
        if g["ranch_id"] != ranch["id"] or g["group_status"] == "LIQUIDATED":
            continue
        au = animal_unit_factor(g["animal_class"], g["avg_weight_lbs"])
        demand += dec(g["head_count"]) * au
    monthly_demand = d2(demand)

    deficit = d2(monthly_demand - monthly_supply)
    return ranch_pct, posture, monthly_supply, monthly_demand, deficit


def destock_required_reduction(ranch: dict, deficit: Decimal) -> int:
    """Single left-to-right pass, pinned order (§3.8)."""
    candidates = [g for g in db.herd_groups.values()
                  if g["ranch_id"] == ranch["id"] and g["group_status"] != "LIQUIDATED"]
    candidates.sort(key=lambda g: (
        DESTOCK_CLASS_PRIORITY[g["animal_class"]],
        -dec(g["avg_weight_lbs"]),
        g["created_at"],
        g["id"],
    ))
    remaining = deficit
    required = 0
    for g in candidates:
        if remaining <= 0:
            break
        per_head = animal_unit_factor(g["animal_class"], g["avg_weight_lbs"])
        if per_head <= 0:
            continue
        removable = min(g["head_count"], math.ceil(remaining / per_head))
        if removable <= 0:
            continue
        required += removable
        remaining -= Decimal(removable) * per_head
    return required


def flip_groups_to_destocking(ranch_id: str):
    from core import touch
    for g in db.herd_groups.values():
        if g["ranch_id"] == ranch_id and g["group_status"] == "ACTIVE":
            g["group_status"] = "DESTOCKING"
            touch(g)


def release_groups_from_destocking(ranch_id: str):
    """DESTOCKING -> ACTIVE once no covering order remains OPEN|EXPIRED (§3.8)."""
    from core import touch
    blocking = any(
        o["ranch_id"] == ranch_id and o["order_status"] in ("OPEN", "EXPIRED")
        for o in db.destock_orders.values()
    )
    if blocking:
        return
    for g in db.herd_groups.values():
        if g["ranch_id"] == ranch_id and g["group_status"] == "DESTOCKING":
            g["group_status"] = "ACTIVE"
            touch(g)


# ===========================================================================
# Serializers (dates as YYYY-MM-DD strings; numbers as JSON numbers)
# ===========================================================================
def ranch_out(r: dict) -> dict:
    return {
        "id": r["id"], "name": r["name"], "hq_state": r["hq_state"],
        "destock_grace_days": r["destock_grace_days"],
        "drought_posture": r["drought_posture"],
        "ranch_production_pct": num(dec(r["ranch_production_pct"])),
        "assessment_seq": r["assessment_seq"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def pasture_out(p: dict) -> dict:
    refresh_pasture(p)
    return {
        "id": p["id"], "ranch_id": p["ranch_id"], "name": p["name"],
        "acreage": p["acreage"], "tenure": p["tenure"], "forage_type": p["forage_type"],
        "base_capacity_aum": p["base_capacity_aum"], "min_rest_days": p["min_rest_days"],
        "effective_capacity_aum": p["effective_capacity_aum"],
        "committed_aum": p["committed_aum"],
        "consumed_total_aum": p["consumed_total_aum"],
        "available_aum": p["available_aum"],
        "resting_until": date_str(p["resting_until"]) if p.get("resting_until") else None,
        "closed_flag": p["closed_flag"],
        "condition_status": p["condition_status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def lease_out(l: dict) -> dict:
    refresh_lease(l)
    return {
        "id": l["id"], "ranch_id": l["ranch_id"], "pasture_id": l["pasture_id"],
        "lessor_name": l["lessor_name"],
        "start_date": date_str(l["start_date"]), "end_date": date_str(l["end_date"]),
        "aum_allotment": l["aum_allotment"], "rate_per_aum_cents": l["rate_per_aum_cents"],
        "minimum_commit_aum": l["minimum_commit_aum"],
        "overage_tier1_cap_aum": l["overage_tier1_cap_aum"],
        "overage_tier1_rate_cents": l["overage_tier1_rate_cents"],
        "overage_tier2_rate_cents": l["overage_tier2_rate_cents"],
        "settlement_basis": l["settlement_basis"],
        "lease_status": l["lease_status"],
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


def statement_out(s: dict) -> dict:
    return {
        "id": s["id"], "lease_id": s["lease_id"], "ranch_id": s["ranch_id"],
        "period_year": s["period_year"],
        "actual_aum_used": num(dec(s["actual_aum_used"])),
        "base_charge_cents": num(dec(s["base_charge_cents"])),
        "overage_charge_cents": num(dec(s["overage_charge_cents"])),
        "total_due_cents": num(dec(s["total_due_cents"])),
        "recorded_by_user_id": s["recorded_by_user_id"],
        "approved_by_user_id": s["approved_by_user_id"],
        "statement_status": s["statement_status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def herd_group_out(g: dict) -> dict:
    return {
        "id": g["id"], "ranch_id": g["ranch_id"], "group_name": g["group_name"],
        "animal_class": g["animal_class"], "head_count": g["head_count"],
        "avg_weight_lbs": g["avg_weight_lbs"],
        "marked_open_head": g["marked_open_head"],
        "retained_from_crop_id": g["retained_from_crop_id"],
        "group_status": g["group_status"],
        "created_at": g["created_at"], "updated_at": g["updated_at"], "version": g["version"],
    }


def season_out(s: dict) -> dict:
    return {
        "id": s["id"], "ranch_id": s["ranch_id"], "herd_group_id": s["herd_group_id"],
        "season_year": s["season_year"],
        "planned_turnout_date": date_str(s["planned_turnout_date"]),
        "planned_removal_date": date_str(s["planned_removal_date"]),
        "exposed_head_count": s["exposed_head_count"],
        "required_bull_count": s["required_bull_count"],
        "season_status": s["season_status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def bull_out(b: dict) -> dict:
    refresh_bull(b)
    return {
        "id": b["id"], "ranch_id": b["ranch_id"], "tag": b["tag"], "breed": b["breed"],
        "birth_year": b["birth_year"],
        "last_bse_date": date_str(b["last_bse_date"]) if b.get("last_bse_date") else None,
        "last_bse_result": b.get("last_bse_result"),
        "scrotal_cm": num(dec(b["scrotal_cm"])) if b.get("scrotal_cm") is not None else None,
        "bse_status": b["bse_status"],
        "life_status": b["life_status"],
        "created_at": b["created_at"], "updated_at": b["updated_at"], "version": b["version"],
    }


def turnout_out(t: dict) -> dict:
    return {
        "id": t["id"], "bull_id": t["bull_id"], "breeding_season_id": t["breeding_season_id"],
        "ranch_id": t["ranch_id"],
        "turnout_date": date_str(t["turnout_date"]),
        "planned_removal_date": date_str(t["planned_removal_date"]),
        "actual_removal_date": date_str(t["actual_removal_date"]) if t.get("actual_removal_date") else None,
        "turnout_status": t["turnout_status"],
        "created_at": t["created_at"], "updated_at": t["updated_at"], "version": t["version"],
    }


def preg_check_out(pc: dict) -> dict:
    return {
        "id": pc["id"], "breeding_season_id": pc["breeding_season_id"], "ranch_id": pc["ranch_id"],
        "check_date": date_str(pc["check_date"]),
        "exposed_head_count": pc["exposed_head_count"],
        "pregnant_count": pc.get("pregnant_count"),
        "open_count": pc.get("open_count"),
        "dead_count": pc.get("dead_count"),
        "pregnancy_rate_pct": num(dec(pc["pregnancy_rate_pct"])) if pc.get("pregnancy_rate_pct") is not None else None,
        "check_status": pc["check_status"],
        "created_at": pc["created_at"], "updated_at": pc["updated_at"], "version": pc["version"],
    }


def calf_crop_out(c: dict) -> dict:
    refresh_crop(c)
    return {
        "id": c["id"], "breeding_season_id": c["breeding_season_id"], "ranch_id": c["ranch_id"],
        "crop_year": c["crop_year"], "steer_head": c["steer_head"], "heifer_head": c["heifer_head"],
        "weaning_date": date_str(c["weaning_date"]) if c.get("weaning_date") else None,
        "avg_wean_weight_lbs": num(dec(c["avg_wean_weight_lbs"])) if c.get("avg_wean_weight_lbs") is not None else None,
        "avg_wean_age_days": c.get("avg_wean_age_days"),
        "avg_birth_weight_lbs": num(dec(c["avg_birth_weight_lbs"])) if c.get("avg_birth_weight_lbs") is not None else None,
        "avg_dam_age_years": c.get("avg_dam_age_years"),
        "adj205_age_only_lbs": num(dec(c["adj205_age_only_lbs"])) if c.get("adj205_age_only_lbs") is not None else None,
        "adj205_dam_adjusted_lbs": num(dec(c["adj205_dam_adjusted_lbs"])) if c.get("adj205_dam_adjusted_lbs") is not None else None,
        "vaccine_round_1_date": date_str(c["vaccine_round_1_date"]) if c.get("vaccine_round_1_date") else None,
        "vaccine_round_2_date": date_str(c["vaccine_round_2_date"]) if c.get("vaccine_round_2_date") else None,
        "retained_heifer_head": c["retained_heifer_head"],
        "death_loss_steer_head": c["death_loss_steer_head"],
        "death_loss_heifer_head": c["death_loss_heifer_head"],
        "marketed_steer_head": c["marketed_steer_head"],
        "marketed_heifer_head": c["marketed_heifer_head"],
        "reserved_steer_head": c["reserved_steer_head"],
        "reserved_heifer_head": c["reserved_heifer_head"],
        "available_steer_head": c["available_steer_head"],
        "available_heifer_head": c["available_heifer_head"],
        "wean_status": c["wean_status"],
        "precon_status": c["precon_status"],
        "lifecycle_status": c["lifecycle_status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def sale_lot_out(l: dict) -> dict:
    def n(k):
        v = l.get(k)
        return num(dec(v)) if v is not None else None
    return {
        "id": l["id"], "calf_crop_id": l["calf_crop_id"], "ranch_id": l["ranch_id"],
        "lot_class": l["lot_class"], "head_count": l["head_count"],
        "base_price_cents_per_cwt": num(dec(l["base_price_cents_per_cwt"])),
        "slide_cents_per_lb": num(dec(l["slide_cents_per_lb"])),
        "base_weight_lbs": num(dec(l["base_weight_lbs"])),
        "shrink_pct": num(dec(l["shrink_pct"])),
        "precon_claim": l["precon_claim"],
        "freight_cents_per_head": l["freight_cents_per_head"],
        "commission_pct": num(dec(l["commission_pct"])),
        "buyer_name": l.get("buyer_name"),
        "delivered_avg_weight_lbs": n("delivered_avg_weight_lbs"),
        "pay_weight_lbs": n("pay_weight_lbs"),
        "final_price_cents_per_cwt": n("final_price_cents_per_cwt"),
        "per_head_gross_cents": n("per_head_gross_cents"),
        "gross_cents": n("gross_cents"),
        "commission_cents": n("commission_cents"),
        "freight_cents": l.get("freight_cents"),
        "net_settlement_cents": n("net_settlement_cents"),
        "relist_count": l["relist_count"],
        "sold_by_user_id": l["sold_by_user_id"],
        "settled_by_user_id": l.get("settled_by_user_id"),
        "lot_status": l["lot_status"],
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


def assignment_out(a: dict) -> dict:
    return {
        "id": a["id"], "pasture_id": a["pasture_id"], "herd_group_id": a["herd_group_id"],
        "ranch_id": a["ranch_id"],
        "start_date": date_str(a["start_date"]),
        "planned_end_date": date_str(a["planned_end_date"]),
        "grazing_days": a["grazing_days"],
        "au_factor": num(dec(a["au_factor"])),
        "daily_demand_aum": num(dec(a["daily_demand_aum"])),
        "reserved_aum": num(dec(a["reserved_aum"])),
        "consumed_aum": num(dec(a["consumed_aum"])) if a.get("consumed_aum") is not None else None,
        "actual_end_date": date_str(a["actual_end_date"]) if a.get("actual_end_date") else None,
        "assignment_status": a["assignment_status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def program_out(p: dict) -> dict:
    return {
        "id": p["id"], "herd_group_id": p["herd_group_id"], "ranch_id": p["ranch_id"],
        "program_type": p["program_type"],
        "start_date": date_str(p["start_date"]), "end_date": date_str(p["end_date"]),
        "feed_rate_oz_per_head_day": num(dec(p["feed_rate_oz_per_head_day"])),
        "cost_cents_per_ton": p["cost_cents_per_ton"],
        "delivered_lbs_total": num(dec(p["delivered_lbs_total"])),
        "cost_to_date_cents": num(dec(p["cost_to_date_cents"])),
        "projected_consumption_lbs": num(dec(p["projected_consumption_lbs"])),
        "program_status": p["program_status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def assessment_out(a: dict) -> dict:
    return {
        "id": a["id"], "ranch_id": a["ranch_id"],
        "assessment_date": date_str(a["assessment_date"]),
        "pasture_measurements": a["pasture_measurements"],
        "ranch_production_pct": num(dec(a["ranch_production_pct"])),
        "monthly_supply_aum": num(dec(a["monthly_supply_aum"])),
        "monthly_demand_aum": num(dec(a["monthly_demand_aum"])),
        "deficit_aum_per_30d": num(dec(a["deficit_aum_per_30d"])),
        "resulting_posture": a["resulting_posture"],
        "assessment_status": a["assessment_status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def destock_order_out(o: dict) -> dict:
    return {
        "id": o["id"], "ranch_id": o["ranch_id"],
        "drought_assessment_id": o["drought_assessment_id"],
        "required_reduction_head": o["required_reduction_head"],
        "received_reduction_head": o["received_reduction_head"],
        "deadline_date": date_str(o["deadline_date"]),
        "waiver_note": o.get("waiver_note"),
        "order_status": o["order_status"],
        "created_at": o["created_at"], "updated_at": o["updated_at"], "version": o["version"],
    }
