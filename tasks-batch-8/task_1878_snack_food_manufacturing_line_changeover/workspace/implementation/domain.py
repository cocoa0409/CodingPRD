"""Core business logic: derived fields, oil model, changeover matrix,
margin/giveaway calculations, freshness, cascades."""
import math
from datetime import timedelta
from decimal import Decimal

from errors import ApiError
from store import touch, sort_key
from util import D, rhu, rhu_int, num

ALLERGENS = {"PEANUT", "TREE_NUT", "DAIRY", "SOY", "GLUTEN", "SESAME", "EGG"}
FLAVOR_GROUPS = {"PLAIN", "CHEESE", "SPICY", "SWEET"}
PROCESS_TYPES = {"FRYER", "OVEN"}
LINE_TYPES = {"FRYER", "OVEN", "BOTH"}
MOVEMENT_TYPES = {"TOP_OFF", "DISCARD", "FILTRATION", "FULL_REPLACE"}
ROUTES = {"DSD", "WAREHOUSE", "AUTO"}

TPM_RATE_PER_1000_LBS = Decimal("2.0")
TEMP_DEVIATION_LIMIT_C = Decimal("5.0")
TEMP_FACTOR_HIGH = Decimal("1.5")
FILTRATION_FACTOR = Decimal("0.6")
TPM_HOLD_THRESHOLD = Decimal("27.0")
FRESH_TPM = Decimal("0.5")
ABSORB_GAL_PER_1000_LBS = Decimal("1.5")
INGREDIENT_CENTS_PER_LB = 80
SEASONING_CENTS_PER_G = 2
GRAMS_PER_LB = Decimal("453.592")
MAX_REJECT_RATIO = Decimal("0.025")
DSD_MIN_DAYS = 4
WH_MIN_DAYS = 10
STALE_HOURS = 48


# ---------------------------------------------------------------------------
# Existence lookups (validation tier 3)
# ---------------------------------------------------------------------------

def _lookup(table, key, error_id):
    e = table.get(key) if isinstance(key, str) else None
    if e is None:
        raise ApiError(error_id, 404, f"resource not found: {key}")
    return e


def get_product(store, pid):
    return _lookup(store.products, pid, "ERR_PRODUCT_NOT_FOUND")


def get_line(store, lid):
    return _lookup(store.lines, lid, "ERR_LINE_NOT_FOUND")


def get_run(store, rid):
    return _lookup(store.runs, rid, "ERR_RUN_NOT_FOUND")


def get_changeover(store, cid):
    return _lookup(store.changeovers, cid, "ERR_CHANGEOVER_NOT_FOUND")


def get_oil(store, oid):
    return _lookup(store.oils, oid, "ERR_OIL_NOT_FOUND")


def get_movement(store, mid):
    return _lookup(store.movements, mid, "ERR_MOVEMENT_NOT_FOUND")


def get_check(store, wid):
    return _lookup(store.checks, wid, "ERR_WEIGHT_CHECK_NOT_FOUND")


def get_shipment(store, sid):
    return _lookup(store.shipments, sid, "ERR_SHIPMENT_NOT_FOUND")


def get_window(store, wid):
    return _lookup(store.windows, wid, "ERR_PROMO_WINDOW_NOT_FOUND")


def get_case(store, cid):
    return _lookup(store.cases, cid, "ERR_DISPLAY_CASE_NOT_FOUND")


def get_coman(store, cid):
    return _lookup(store.comans, cid, "ERR_COMAN_NOT_FOUND")


def get_agreement(store, aid):
    return _lookup(store.agreements, aid, "ERR_AGREEMENT_NOT_FOUND")


def get_slot(store, sid):
    return _lookup(store.slots, sid, "ERR_SLOT_NOT_FOUND")


def oil_for_line(store, line_id):
    oid = store.oil_by_line.get(line_id)
    return store.oils.get(oid) if oid else None


# ---------------------------------------------------------------------------
# Changeover requirement matrix
# ---------------------------------------------------------------------------

def changeover_requirement(from_allergens, from_flavor, to_allergens, to_flavor):
    fa, ta = set(from_allergens), set(to_allergens)
    if fa - ta:
        return "FULL_WASH"
    if fa == ta and from_flavor != to_flavor:
        return "DRY_CLEAN"
    return "NONE"


# ---------------------------------------------------------------------------
# Derived line state
# ---------------------------------------------------------------------------

def line_current_profile(store, line):
    completed = [r for r in store.runs.values()
                 if r["line_id"] == line["id"] and r["execution_status"] == "COMPLETED"]
    if not completed:
        return [], "PLAIN"
    latest = max(completed, key=lambda r: (r["_completed_dt"], r["_seq"]))
    product = store.products.get(latest["product_id"])
    if product is None:
        return [], "PLAIN"
    return list(product["allergen_profile"]), product["flavor_group"]


def line_posture(store, line):
    lid = line["id"]
    for r in store.runs.values():
        if r["line_id"] == lid and r["execution_status"] == "RUNNING":
            return "RUNNING"
    for c in store.changeovers.values():
        if c["line_id"] == lid and c["status"] in ("REQUIRED", "CLEANING", "SWAB_PENDING"):
            return "CLEANING"
    oil = oil_for_line(store, lid)
    if oil is not None and oil["state"] in ("QUALITY_HOLD", "DRAINING"):
        return "BLOCKED"
    return "IDLE"


# ---------------------------------------------------------------------------
# Case reservation ledger
# ---------------------------------------------------------------------------

def cases_unrouted(store, run):
    base = run["accepted_cases"] if run["execution_status"] == "COMPLETED" else run["cases_planned"]
    s = sum(sh["cases"] for sh in store.shipments.values()
            if sh["run_id"] == run["id"] and sh["status"] != "CANCELLED")
    d = sum(dc["cases_planned"] for dc in store.cases.values()
            if dc["run_id"] == run["id"] and dc["status"] in ("PLANNED", "BUILT"))
    return base - s - d


# ---------------------------------------------------------------------------
# Fryer oil model
# ---------------------------------------------------------------------------

def absorbed_gallons(total_lbs: Decimal) -> Decimal:
    return rhu(total_lbs * ABSORB_GAL_PER_1000_LBS / Decimal(1000), 3)


def oil_state_reeval(store, oil):
    """Re-evaluate ACTIVE <-> QUALITY_HOLD after any tpm recompute.
    Applies only while the oil is in one of those two states (DRAINING
    exits exclusively via FULL_REPLACE)."""
    if oil["state"] == "ACTIVE" and oil["tpm_pct"] >= TPM_HOLD_THRESHOLD:
        oil["state"] = "QUALITY_HOLD"
        run = next((r for r in store.runs.values()
                    if r["line_id"] == oil["line_id"] and r["execution_status"] == "RUNNING"), None)
        if run is not None:
            run["execution_status"] = "HELD"
            run["hold_placed_by_user_id"] = None
            touch(store, run)
            for dc in store.cases.values():
                if dc["run_id"] == run["id"] and dc["status"] == "PLANNED":
                    dc["status"] = "CANCELLED"
                    dc["cancelled_reason"] = "OIL_HOLD"
                    touch(store, dc)
    elif oil["state"] == "QUALITY_HOLD" and oil["tpm_pct"] < TPM_HOLD_THRESHOLD:
        oil["state"] = "ACTIVE"


def frying_accrual(store, oil, lbs: Decimal, factor: Decimal):
    """Accrual with an explicit temperature factor."""
    if lbs == 0:
        return
    old_abs = absorbed_gallons(oil["total_lbs_since_replace"])
    oil["total_lbs_since_replace"] = oil["total_lbs_since_replace"] + lbs
    new_abs = absorbed_gallons(oil["total_lbs_since_replace"])
    oil["current_gallons"] = oil["current_gallons"] - (new_abs - old_abs)
    oil["tpm_pct"] = rhu(oil["tpm_pct"] + (lbs / Decimal(1000)) * TPM_RATE_PER_1000_LBS * factor, 2)
    oil_state_reeval(store, oil)
    if lbs > 0:
        touch(store, oil)


def temp_factor(product, avg_temp):
    if product["process_type"] != "FRYER":
        return Decimal("1.0")
    if avg_temp is None or product.get("fry_target_temp_c") is None:
        return Decimal("1.0")
    if abs(D(avg_temp) - D(product["fry_target_temp_c"])) > TEMP_DEVIATION_LIMIT_C:
        return TEMP_FACTOR_HIGH
    return Decimal("1.0")


def last_oil_price(store, oil):
    priced = [m for m in store.movements.values()
              if m["fryer_oil_id"] == oil["id"]
              and m["movement_type"] in ("TOP_OFF", "FULL_REPLACE")
              and m.get("unit_price_cents_per_gal") is not None]
    if not priced:
        return None
    latest = max(priced, key=lambda m: (m["_recorded_dt"], m["_seq"]))
    return latest["unit_price_cents_per_gal"]


# ---------------------------------------------------------------------------
# Giveaway / reject statistics (derived on read)
# ---------------------------------------------------------------------------

def run_checks(store, run):
    return sorted((c for c in store.checks.values() if c["run_id"] == run["id"]),
                  key=lambda c: c["_seq"])


def giveaway_figures(store, run, product):
    """Returns (provisional_pct, final_pct, reject_ratio_display,
    reject_ratio_raw, mean_weight_raw). Nones when no (non-reject) checks."""
    checks = run_checks(store, run)
    declared = D(product["declared_net_weight_g"])
    tne = D(product["tne_g"])
    limit = declared - 2 * tne
    if not checks:
        return None, None, None, None, None
    weights = [D(c["bag_weight_g"]) for c in checks]
    rejects = [w for w in weights if w < limit]
    nonrej = [w for w in weights if not (w < limit)]
    n = len(weights)
    mean_all = sum(weights) / Decimal(n)
    provisional = rhu(Decimal(100) * (mean_all - declared) / declared, 2)
    ratio_raw = Decimal(len(rejects)) / Decimal(n)
    ratio = ratio_raw
    if nonrej:
        per_check = [rhu(w - declared, 1) for w in nonrej]
        mean_rounded = sum(per_check) / Decimal(len(per_check))
        final = rhu(Decimal(100) * mean_rounded / declared, 2)
    else:
        final = None
    return provisional, final, ratio, ratio_raw, mean_all


# ---------------------------------------------------------------------------
# Margin calculation (dual variant, pinned evaluation order)
# ---------------------------------------------------------------------------

def seasoning_cost_cents(lbs: Decimal, pct: Decimal) -> int:
    grams = rhu(lbs * GRAMS_PER_LB * pct / Decimal(100), 1)
    return rhu_int(grams * SEASONING_CENTS_PER_G)


def margin_standard(run, product, locked_price):
    cases_basis = run["cases_planned"]
    lbs = D(run["lbs_planned"])
    absorbed = rhu(lbs * ABSORB_GAL_PER_1000_LBS / Decimal(1000), 3)
    oil_cost = rhu_int(absorbed * Decimal(locked_price))
    ingredient = rhu_int(lbs * INGREDIENT_CENTS_PER_LB)
    seasoning = seasoning_cost_cents(lbs, D(product["seasoning_target_pct"]))
    return cases_basis * product["case_revenue_cents"] - (ingredient + oil_cost + seasoning)


def margin_actual(store, run, product):
    cases_basis = run["accepted_cases"]
    lbs = D(run["lbs_produced"])
    absorbed = rhu(lbs * ABSORB_GAL_PER_1000_LBS / Decimal(1000), 3)
    oil = oil_for_line(store, run["line_id"])
    window_movs = []
    if oil is not None:
        for m in store.movements.values():
            if (m["fryer_oil_id"] == oil["id"] and m["movement_type"] == "TOP_OFF"
                    and run["_started_dt"] <= m["_recorded_dt"] <= run["_completed_dt"]):
                window_movs.append(m)
    if window_movs:
        total_gal = sum(D(m["gallons"]) for m in window_movs)
        weighted = sum(Decimal(m["unit_price_cents_per_gal"]) * D(m["gallons"])
                       for m in window_movs) / total_gal
        price = weighted
    else:
        price = Decimal(run["locked_oil_price_cents_per_gal"])
    oil_cost = rhu_int(absorbed * price)
    ingredient = rhu_int(lbs * INGREDIENT_CENTS_PER_LB)
    seasoning = seasoning_cost_cents(lbs, D(run["seasoning_actual_pct"]))
    return cases_basis * product["case_revenue_cents"] - (ingredient + oil_cost + seasoning)


def margin_per_case(run):
    if run.get("margin_actual_cents") is None:
        return None
    accepted = run["accepted_cases"]
    if not accepted:
        return None
    return rhu_int(Decimal(run["margin_actual_cents"]) / Decimal(accepted))


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

def elapsed_days(now, completed_at) -> int:
    secs = (now - completed_at).total_seconds()
    return math.floor(secs / 86400)


def freshness_remaining(product, now, completed_at) -> int:
    return product["shelf_life_days"] - elapsed_days(now, completed_at)


# ---------------------------------------------------------------------------
# Promo quota
# ---------------------------------------------------------------------------

def quota_remaining(window):
    return (window["quota_total_cases"] - window["quota_consumed_cases"]
            + window["quota_released_cases"])


def window_exhaustion_check(store, window):
    """ACTIVE -> EXHAUSTED when remaining hits exactly 0; cascades to PLANNED cases."""
    if window["status"] == "ACTIVE" and quota_remaining(window) == 0:
        window["status"] = "EXHAUSTED"
        touch(store, window)
        for dc in store.cases.values():
            if dc["promo_window_id"] == window["id"] and dc["status"] == "PLANNED":
                dc["status"] = "CANCELLED"
                dc["cancelled_reason"] = "QUOTA_EXHAUSTED"
                touch(store, dc)


def window_reactivation_check(store, window):
    """EXHAUSTED -> ACTIVE when a release lifts remaining above 0."""
    if window["status"] == "EXHAUSTED" and quota_remaining(window) > 0:
        window["status"] = "ACTIVE"
        touch(store, window)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def dump_product(p):
    return {
        "id": p["id"], "name": p["name"], "process_type": p["process_type"],
        "allergen_profile": list(p["allergen_profile"]), "flavor_group": p["flavor_group"],
        "declared_net_weight_g": num(p["declared_net_weight_g"]), "tne_g": num(p["tne_g"]),
        "giveaway_target_pct": num(p["giveaway_target_pct"]),
        "giveaway_max_pct": num(p["giveaway_max_pct"]),
        "shelf_life_days": p["shelf_life_days"],
        "seasoning_target_pct": num(p["seasoning_target_pct"]),
        "fry_target_temp_c": (num(p["fry_target_temp_c"]) if p.get("fry_target_temp_c") is not None else None),
        "standard_oil_price_cents_per_gal": p["standard_oil_price_cents_per_gal"],
        "case_revenue_cents": p["case_revenue_cents"],
        "min_margin_cents_per_case": p["min_margin_cents_per_case"],
        "bags_per_case": p["bags_per_case"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def dump_line(store, line):
    allergens, flavor = line_current_profile(store, line)
    return {
        "id": line["id"], "name": line["name"], "line_type": line["line_type"],
        "oil_capacity_gallons": num(line["oil_capacity_gallons"]),
        "cleaning_minutes_full_wash": line["cleaning_minutes_full_wash"],
        "cleaning_minutes_dry": line["cleaning_minutes_dry"],
        "posture": line_posture(store, line),
        "current_allergen_profile": allergens,
        "current_flavor_group": flavor,
        "created_at": line["created_at"], "updated_at": line["updated_at"],
        "version": line["version"],
    }


def dump_oil(store, oil):
    return {
        "id": oil["id"], "line_id": oil["line_id"],
        "initial_charge_gallons": num(oil["initial_charge_gallons"]),
        "current_gallons": num(oil["current_gallons"]),
        "tpm_pct": num(oil["tpm_pct"]), "state": oil["state"],
        "total_lbs_since_replace": num(oil["total_lbs_since_replace"]),
        "last_oil_price_cents_per_gal": last_oil_price(store, oil),
        "created_at": oil["created_at"], "updated_at": oil["updated_at"],
        "version": oil["version"],
    }


def dump_movement(m):
    return {
        "id": m["id"], "fryer_oil_id": m["fryer_oil_id"],
        "movement_type": m["movement_type"], "gallons": num(m["gallons"]),
        "unit_price_cents_per_gal": m.get("unit_price_cents_per_gal"),
        "tpm_after_pct": num(m["tpm_after_pct"]),
        "recorded_at": m["recorded_at"], "recorded_by_user_id": m["recorded_by_user_id"],
        "created_at": m["created_at"],
    }


def dump_changeover(c):
    return {
        "id": c["id"], "line_id": c["line_id"], "to_product_id": c["to_product_id"],
        "from_allergen_profile": list(c["from_allergen_profile"]),
        "to_allergen_profile": list(c["to_allergen_profile"]),
        "from_flavor_group": c["from_flavor_group"], "to_flavor_group": c["to_flavor_group"],
        "required_level": c["required_level"], "status": c["status"],
        "cleaned_by_user_id": c["cleaned_by_user_id"], "swab_result": c["swab_result"],
        "swab_attempts": c["swab_attempts"], "validated_by_user_id": c["validated_by_user_id"],
        "validated_at": c["validated_at"], "consumed_by_run_id": c["consumed_by_run_id"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def dump_run(store, run):
    product = store.products.get(run["product_id"])
    provisional, final, ratio, _, _ = (giveaway_figures(store, run, product)
                                       if product is not None else (None,) * 5)
    return {
        "id": run["id"], "line_id": run["line_id"], "product_id": run["product_id"],
        "scheduled_start": run["scheduled_start"], "scheduled_end": run["scheduled_end"],
        "lbs_planned": num(run["lbs_planned"]), "cases_planned": run["cases_planned"],
        "execution_status": run["execution_status"], "quality_status": run["quality_status"],
        "started_at": run["started_at"], "completed_at": run["completed_at"],
        "lbs_produced": (num(run["lbs_produced"]) if run.get("lbs_produced") is not None else None),
        "cases_produced": run.get("cases_produced"),
        "rejected_cases": run.get("rejected_cases"),
        "seasoning_actual_pct": (num(run["seasoning_actual_pct"])
                                 if run.get("seasoning_actual_pct") is not None else None),
        "accepted_cases": run["accepted_cases"],
        "cases_unrouted": cases_unrouted(store, run),
        "hold_placed_by_user_id": run["hold_placed_by_user_id"],
        "locked_oil_price_cents_per_gal": run["locked_oil_price_cents_per_gal"],
        "margin_standard_cents": run["margin_standard_cents"],
        "margin_actual_cents": run["margin_actual_cents"],
        "giveaway_provisional_pct": (num(provisional) if provisional is not None else None),
        "giveaway_final_pct": (num(final) if final is not None else None),
        "reject_ratio": (num(ratio) if ratio is not None else None),
        "created_at": run["created_at"], "updated_at": run["updated_at"], "version": run["version"],
    }


def dump_check(c):
    return {
        "id": c["id"], "run_id": c["run_id"], "bag_weight_g": num(c["bag_weight_g"]),
        "lbs_fried_since_last_check": num(c["lbs_fried_since_last_check"]),
        "avg_fry_temp_c": (num(c["avg_fry_temp_c"]) if c.get("avg_fry_temp_c") is not None else None),
        "is_reject": c["is_reject"], "recorded_at": c["recorded_at"],
        "checked_by_user_id": c["checked_by_user_id"], "created_at": c["created_at"],
    }


def dump_shipment(sh):
    return {
        "id": sh["id"], "run_id": sh["run_id"], "cases": sh["cases"],
        "requested_route": sh["requested_route"], "transit_days": sh["transit_days"],
        "planned_route": sh["planned_route"], "status": sh["status"],
        "freshness_days_at_plan": sh["freshness_days_at_plan"],
        "dispatched_at": sh["dispatched_at"],
        "created_at": sh["created_at"], "updated_at": sh["updated_at"], "version": sh["version"],
    }


def dump_window(w):
    return {
        "id": w["id"], "product_id": w["product_id"],
        "quota_total_cases": w["quota_total_cases"],
        "window_start_date": w["window_start_date"], "window_end_date": w["window_end_date"],
        "case_size_bags": w["case_size_bags"], "status": w["status"],
        "quota_consumed_cases": w["quota_consumed_cases"],
        "quota_released_cases": w["quota_released_cases"],
        "quota_remaining_cases": quota_remaining(w),
        "created_at": w["created_at"], "updated_at": w["updated_at"], "version": w["version"],
    }


def dump_case(dc):
    return {
        "id": dc["id"], "promo_window_id": dc["promo_window_id"], "run_id": dc["run_id"],
        "cases_planned": dc["cases_planned"], "status": dc["status"],
        "cancelled_reason": dc["cancelled_reason"],
        "created_at": dc["created_at"], "updated_at": dc["updated_at"], "version": dc["version"],
    }


def dump_coman(cm):
    return {
        "id": cm["id"], "name": cm["name"], "active": cm["active"],
        "created_at": cm["created_at"], "updated_at": cm["updated_at"], "version": cm["version"],
    }


def dump_agreement(a):
    return {
        "id": a["id"], "co_manufacturer_id": a["co_manufacturer_id"],
        "weekly_capacity_lbs": num(a["weekly_capacity_lbs"]),
        "rate_per_lb_cents": a["rate_per_lb_cents"], "budget_cents": a["budget_cents"],
        "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def dump_slot(s):
    return {
        "id": s["id"], "agreement_id": s["agreement_id"], "product_id": s["product_id"],
        "week_start_date": s["week_start_date"], "reserved_lbs": num(s["reserved_lbs"]),
        "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }
