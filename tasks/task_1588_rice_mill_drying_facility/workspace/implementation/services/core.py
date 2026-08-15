"""Business logic: calculations (scaffold §1.3), cascades, derived state."""
from datetime import timedelta
from decimal import Decimal

from db import db
from util import D, q2, q0, parse_dt, parse_date, fmt_dt, now_ts, add_hours

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VARIETIES = ("LONG_GRAIN", "MEDIUM_GRAIN")
GRADES = ("US_NO_1", "US_NO_2", "US_NO_3", "US_NO_4", "US_NO_5", "SAMPLE")
PRODUCTS = ("HEAD_RICE", "BROKEN", "BREWERS", "BRAN", "HULL")
BYPRODUCT_PRODUCTS = ("BRAN", "HULL", "BROKEN", "BREWERS")

BASE_MOISTURE = Decimal("13.0")
HANDLING_LOSS_PCT = Decimal("0.5")
CHECKOFF_RATE = Decimal("0.005")
OVERDELIVERY_TOLERANCE = Decimal("1.05")
KG_TO_LB = Decimal("2.20462262")
CHANGEOVER_MINUTES = 30

TOTAL_RICE_PCT = {"LONG_GRAIN": Decimal("0.68"), "MEDIUM_GRAIN": Decimal("0.72")}
HEAD_RATIO = {"LONG_GRAIN": Decimal("0.60"), "MEDIUM_GRAIN": Decimal("0.66")}
BREWERS_PCT = Decimal("0.05")
BRAN_PCT = Decimal("0.08")
LOSS_PCT = Decimal("0.02")

MILL_FIELD = {
    "HEAD_RICE": "head",
    "BROKEN": "broken",
    "BREWERS": "brewers",
    "BRAN": "bran",
    "HULL": "hull",
}


# ---------------------------------------------------------------------------
# Common record plumbing (PRD §2.5)
# ---------------------------------------------------------------------------

def bump(rec):
    rec["version"] = int(rec.get("version", 1)) + 1
    rec["updated_at"] = now_ts()


def touch_new(rec):
    rec["version"] = 1
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts


# ---------------------------------------------------------------------------
# Season logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def season_clock_dt(season):
    return parse_dt(season["current_clock_iso"])


def season_clock_date_str(season):
    return season_clock_dt(season).date().isoformat()


# ---------------------------------------------------------------------------
# Hold helpers
# ---------------------------------------------------------------------------

def active_hold_on(season_id, target_type, target_id) -> bool:
    for h in db["holds"].values():
        if (h["season_id"] == season_id and h["status"] == "ACTIVE"
                and h["target_type"] == target_type and h["target_id"] == target_id):
            return True
    return False


def any_active_hold_in_season(season_id) -> bool:
    for h in db["holds"].values():
        if h["season_id"] == season_id and h["status"] == "ACTIVE":
            return True
    return False


# ---------------------------------------------------------------------------
# Paddy weight / grading calculations (§1.3)
# ---------------------------------------------------------------------------

def compute_net_wet_cwt(gross_lbs: int, tare_lbs: int) -> Decimal:
    return q2(Decimal(gross_lbs - tare_lbs) / Decimal(100))


def compute_shrink(net_wet: Decimal, moisture: Decimal):
    """Returns (dry_weight_cwt, moisture_shrink_cwt, handling_loss_cwt)."""
    if moisture > BASE_MOISTURE:
        ms_pct = Decimal(100) * (moisture - BASE_MOISTURE) / (Decimal(100) - BASE_MOISTURE)
        hl_pct = HANDLING_LOSS_PCT
    else:
        ms_pct = Decimal(0)
        hl_pct = Decimal(0)
    total_pct = ms_pct + hl_pct
    dry = q2(net_wet * (1 - total_pct / Decimal(100)))
    ms_cwt = q2(net_wet * ms_pct / Decimal(100))
    hl_cwt = q2(net_wet * hl_pct / Decimal(100))
    return dry, ms_cwt, hl_cwt


def drying_charge_cents(net_wet: Decimal, moisture_official: Decimal) -> int:
    points = max(Decimal(0), moisture_official - BASE_MOISTURE)
    tier1 = min(points, Decimal("3.0")) * 4
    tier2 = min(max(points - Decimal("3.0"), Decimal(0)), Decimal("3.0")) * 7
    tier3 = max(points - Decimal("6.0"), Decimal(0)) * 12
    rate = tier1 + tier2 + tier3
    return q0(net_wet * rate)


def grade_score_and_grade(fm: Decimal, dmg: Decimal, brk: Decimal):
    score = q2(2 * fm + 3 * dmg + brk)
    if score <= Decimal("2.0"):
        grade = "US_NO_1"
    elif score <= Decimal("5.0"):
        grade = "US_NO_2"
    elif score <= Decimal("10.0"):
        grade = "US_NO_3"
    elif score <= Decimal("15.0"):
        grade = "US_NO_4"
    elif score <= Decimal("20.0"):
        grade = "US_NO_5"
    else:
        grade = "SAMPLE"
    return score, grade


def line_value_cents(dry_weight: Decimal, price_cents) -> int:
    return q0(dry_weight * D(price_cents))


# ---------------------------------------------------------------------------
# Contract fulfillment (§1.3 contract_fulfillment, §3.2)
# ---------------------------------------------------------------------------

def recompute_contract_fulfillment(contract, force_bump=False):
    total = Decimal("0.00")
    for lot in db["lots"].values():
        if (lot["contract_id"] == contract["id"]
                and lot["status"] in ("GRADED", "BINNED", "SETTLED")):
            total += D(lot["dry_weight_cwt"])
    total = q2(total)
    changed = total != D(contract["fulfilled_cwt"])
    contract["fulfilled_cwt"] = total
    if contract["status"] in ("OPEN", "PARTIALLY_FULFILLED", "FULFILLED"):
        if total == 0:
            new_status = "OPEN"
        elif total < D(contract["contracted_cwt"]):
            new_status = "PARTIALLY_FULFILLED"
        else:
            new_status = "FULFILLED"
        if new_status != contract["status"]:
            contract["status"] = new_status
            changed = True
    if changed or force_bump:
        bump(contract)


# ---------------------------------------------------------------------------
# Bin capacity accounting (§1.3 bin_capacity_allocation, PRD §2.9)
# ---------------------------------------------------------------------------

def refresh_bin(b):
    b["available_cwt"] = q2(D(b["capacity_cwt"]) - D(b["stock_cwt"]) - D(b["reserved_cwt"]))
    if D(b["stock_cwt"]) == 0 and D(b["reserved_cwt"]) == 0:
        b["variety_lock"] = None


# ---------------------------------------------------------------------------
# Milling yield (§1.3 milling_yield_split)
# ---------------------------------------------------------------------------

def mill_estimates(input_cwt: Decimal, variety: str):
    rice_pct = TOTAL_RICE_PCT[variety]
    head_ratio = HEAD_RATIO[variety]
    total_rice = q2(input_cwt * rice_pct)
    est_head = q2(total_rice * head_ratio)
    est_brewers = q2(total_rice * BREWERS_PCT)
    est_broken = q2(total_rice - est_head - est_brewers)  # plug within rice (exact)
    est_bran = q2(input_cwt * BRAN_PCT)
    est_loss = q2(input_cwt * LOSS_PCT)
    est_hull = q2(input_cwt - total_rice - est_bran - est_loss)  # global plug (exact)
    return {
        "est_head_cwt": est_head,
        "est_broken_cwt": est_broken,
        "est_brewers_cwt": est_brewers,
        "est_bran_cwt": est_bran,
        "est_hull_cwt": est_hull,
        "est_loss_cwt": est_loss,
    }


# ---------------------------------------------------------------------------
# Byproduct / milled-rice inventory ledger (§1.3 byproduct_inventory, PRD §2.10)
# ---------------------------------------------------------------------------

def season_inventory(season_id):
    produced = {p: Decimal("0.00") for p in PRODUCTS}
    consumed = {p: Decimal("0.00") for p in PRODUCTS}
    reserved = {p: Decimal("0.00") for p in PRODUCTS}
    shipped = {p: Decimal("0.00") for p in PRODUCTS}

    for r in db["mill_runs"].values():
        if r["season_id"] != season_id:
            continue
        if r["status"] == "COMPLETED":
            for p, f in MILL_FIELD.items():
                produced[p] += D(r[f"est_{f}_cwt"])
        elif r["status"] == "VERIFIED":
            for p, f in MILL_FIELD.items():
                produced[p] += D(r[f"act_{f}_cwt"])

    for r in db["packaging_runs"].values():
        if r["season_id"] == season_id and r["status"] == "COMPLETED":
            consumed["HEAD_RICE"] += D(r["head_rice_consumed_cwt"])

    for o in db["byproduct_orders"].values():
        if o["season_id"] != season_id:
            continue
        if o["status"] == "RESERVED":
            reserved[o["product"]] += D(o["quantity_cwt"])
        elif o["status"] == "SHIPPED":
            shipped[o["product"]] += D(o["quantity_cwt"])

    out = {}
    for p in PRODUCTS:
        available = produced[p] - consumed[p] - reserved[p] - shipped[p]
        out[p] = {
            "produced_cwt": q2(produced[p]),
            "consumed_cwt": q2(consumed[p]),
            "reserved_cwt": q2(reserved[p]),
            "shipped_cwt": q2(shipped[p]),
            "available_cwt": q2(available),
        }
    return out


def packaging_head_rice_cwt(units_produced: int, package_size_kg: Decimal) -> Decimal:
    return q2(D(units_produced) * package_size_kg * KG_TO_LB / Decimal(100))


# ---------------------------------------------------------------------------
# Settlement amounts (§1.3 settlement_amount; pinned gross->drying->checkoff->advance->net)
# ---------------------------------------------------------------------------

def settlement_lots(settlement):
    return [db["lots"][lid] for lid in settlement["lot_ids"] if lid in db["lots"]]


def compute_provisional(settlement):
    lots = settlement_lots(settlement)
    gross = sum(int(l["line_value_cents"]) for l in lots)
    drying = sum(int(l["drying_charge_cents"]) for l in lots)
    checkoff = sum(q0(D(l["line_value_cents"]) * CHECKOFF_RATE) for l in lots)
    grower = db["growers"].get(settlement["grower_id"])
    outstanding = int(grower["advance_outstanding_cents"]) if grower else 0
    advance_repay = min(outstanding, max(0, gross - drying - checkoff))
    net = gross - drying - checkoff - advance_repay
    settlement["provisional_gross_cents"] = gross
    settlement["provisional_drying_cents"] = drying
    settlement["provisional_checkoff_cents"] = checkoff
    settlement["provisional_advance_repay_cents"] = advance_repay
    settlement["provisional_net_cents"] = net


def compute_final(settlement):
    lots = settlement_lots(settlement)
    exact_gross = Decimal(0)
    for l in lots:
        exact_gross += D(l["dry_weight_cwt"]) * D(l["price_cents_per_cwt"])
    gross = q0(exact_gross)
    drying = sum(int(l["drying_charge_cents"]) for l in lots)
    checkoff = q0(exact_gross * CHECKOFF_RATE)
    grower = db["growers"].get(settlement["grower_id"])
    outstanding = int(grower["advance_outstanding_cents"]) if grower else 0
    advance_repay = min(outstanding, max(0, gross - drying - checkoff))
    net = gross - drying - checkoff - advance_repay
    settlement["final_gross_cents"] = gross
    settlement["final_drying_cents"] = drying
    settlement["final_checkoff_cents"] = checkoff
    settlement["final_advance_repay_cents"] = advance_repay
    settlement["final_net_cents"] = net


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def season_revert_on_dispute(season_id):
    season = db["seasons"].get(season_id)
    if season is not None and season["status"] == "SETTLEMENT_REVIEW":
        season["status"] = "INTAKE_CLOSED"
        bump(season)


def cancel_drying_run(run, release=True):
    """Manual or automatic (fumigation) cancellation of a PLANNED run."""
    b = db["bins"].get(run["destination_bin_id"])
    if b is not None:
        b["reserved_cwt"] = q2(D(b["reserved_cwt"]) - D(run["expected_output_cwt"]))
        refresh_bin(b)
        bump(b)
    for lid in run["lot_ids"]:
        lot = db["lots"].get(lid)
        if lot is not None and lot.get("drying_run_id") == run["id"]:
            lot["drying_run_id"] = None
            bump(lot)
    run["status"] = "CANCELLED"
    bump(run)
