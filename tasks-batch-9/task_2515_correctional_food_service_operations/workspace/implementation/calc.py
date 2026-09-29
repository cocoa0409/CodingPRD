"""Derived quantities: rounding discipline, nutrition, cost, forecasting,
temperature ranges, cook-chill, sharps accountability, kitchen posture,
missed meals, liquidated damages, substitution equivalence and SLA windows.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

from core import (
    DB, all_rows, elapsed_minutes, now_logical, date_midnight, touch,
)

# --------------------------------------------------------------------------
# Rounding discipline (PRD 2.7)
# --------------------------------------------------------------------------
ZERO = Decimal("0")


def D(value):
    """Coerce any JSON-ish number to an exact Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantum(places):
    if places <= 0:
        return Decimal("1")
    return Decimal("1").scaleb(-places)


def rhu(value, places=2):
    """Round half up to the given number of decimal places."""
    return D(value).quantize(_quantum(places), rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole number, returned as int."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    """Round up (ceiling) to a whole number."""
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    """Round down (floor) to a whole number."""
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def clamp(value, low, high):
    if value < D(low):
        return D(low)
    if value > D(high):
        return D(high)
    return value


# --------------------------------------------------------------------------
# Constants declared by the PRD
# --------------------------------------------------------------------------
MEAL_SLOTS_PER_DAY = 3
GENERAL_ATTENDANCE_RATE = Decimal("0.94")
SATELLITE_TRANSPORT_BUFFER = Decimal("0.03")
WASTE_SMALL_FLAT = 8
WASTE_SMALL_THRESHOLD = 500
WASTE_MID_RATE = Decimal("0.02")
WASTE_MID_THRESHOLD = 2000
WASTE_LARGE_RATE = Decimal("0.015")

SATELLITE_TIER_NONE = Decimal("1.00")
SATELLITE_TIER_SMALL = Decimal("1.02")
SATELLITE_TIER_LARGE = Decimal("1.05")

COOK_END_MIN_F = Decimal("165.0")
CHILL_INTERMEDIATE_MAX_F = Decimal("80.0")
CHILL_INTERMEDIATE_MAX_MINUTES = 120
CHILL_FINAL_MAX_F = Decimal("40.0")
CHILL_FINAL_MAX_MINUTES = 360
TRANSPORT_MAX_F = Decimal("41.0")
REHEAT_MIN_F = Decimal("165.0")
REHEAT_MAX_MINUTES = 30
CHILLER_RELEASE_BUFFER_MINUTES = 30

RELIGIOUS_VERIFICATION_DAYS = 180
MEDICAL_VERIFICATION_DAYS = 30
MAX_REVERIFICATIONS = 2

SHARP_CLASSES = ("SHARP_KNIFE", "MEAT_SAW", "SCISSORS")

MISSED_MEAL_TOLERANCE_RATE = Decimal("0.02")
SPECIAL_DIET_MISS_WEIGHT = 3

GRIEVANCE_SLA_BREACH_PENALTY_CENTS = 25000
SUBSTITUTION_SURCHARGE_RATE = Decimal("0.15")
COST_RECOVERY_RATE = Decimal("0.20")
MISSED_MEAL_ESCALATION_THRESHOLD = 25
GRIEVANCE_BREACH_ESCALATION_THRESHOLD = 3
CORRECTIVE_ACTION_SCORE_FLOOR = Decimal("70.0")
SCORE_MISSED_MEAL_WEIGHT = Decimal("2.5")
SCORE_BREACH_WEIGHT = Decimal("5.0")
SCORE_COST_WEIGHT = Decimal("0.1")

GRIEVANCE_FAST_CATEGORIES = ("RELIGIOUS_DIET_DENIAL", "DIET_NOT_HONORED")
GRIEVANCE_FAST_DAYS = 5
GRIEVANCE_STANDARD_DAYS = 10

KCAL_EQUIVALENCE_BAND = Decimal("10.00")
PROTEIN_EQUIVALENCE_FLOOR = Decimal("-5.00")
SODIUM_EQUIVALENCE_CEILING = Decimal("200.00")


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------
def rows_where(collection, **criteria):
    out = []
    for row in all_rows(collection):
        keep = True
        for key, value in criteria.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def cycle_items(cycle_id):
    return rows_where("menu_cycle_items", menu_cycle_id=cycle_id)


def facility_cycles(facility_id):
    return rows_where("menu_cycles", facility_id=facility_id)


def contract_facilities(contract_id):
    return rows_where("facilities", contract_id=contract_id)


def inmate_diet_orders(inmate_id):
    return rows_where("diet_orders", inmate_id=inmate_id)


def facility_batches(facility_id):
    return rows_where("production_batches", facility_id=facility_id)


def batch_logs(batch_id):
    return rows_where("temperature_logs", production_batch_id=batch_id)


def facility_issuances(facility_id):
    return rows_where("tool_issuances", facility_id=facility_id)


def facility_incidents(facility_id):
    return rows_where("contraband_incidents", facility_id=facility_id)


def contract_of_facility(facility):
    return DB.col("service_contracts").get(facility["contract_id"])


def facility_of(row):
    return DB.col("facilities").get(row.get("facility_id"))


# --------------------------------------------------------------------------
# Menu cycle nutrition adequacy and cost (PRD 3.2)
# --------------------------------------------------------------------------
def item_kcal(item):
    return rhu_int(D(item["kcal_per_100g"]) * D(item["portion_grams"]) / Decimal("100"))


def item_protein(item):
    return rhu(D(item["protein_grams_per_100g"]) * D(item["portion_grams"]) / Decimal("100"), 2)


def item_sodium(item):
    return rhu_int(D(item["sodium_mg_per_100g"]) * D(item["portion_grams"]) / Decimal("100"))


def cycle_nutrition(cycle):
    """Per-item figures rounded first, then summed, then divided per meal-day."""
    items = cycle_items(cycle["id"])
    days = D(cycle["cycle_length_days"])
    kcal_total = 0
    protein_total = ZERO
    sodium_total = 0
    for item in items:
        kcal_total += item_kcal(item)
        protein_total += item_protein(item)
        sodium_total += item_sodium(item)
    return {
        "kcal_total": kcal_total,
        "protein_total": protein_total,
        "sodium_total": sodium_total,
        "approved_kcal_per_meal_day": rhu_int(D(kcal_total) / days),
        "approved_protein_grams_per_meal_day": rhu(protein_total / days, 2),
        "approved_sodium_mg_per_meal_day": rhu_int(D(sodium_total) / days),
    }


def satellite_multiplier(facility):
    sites = facility.get("satellite_site_count") or 0
    if sites == 0:
        return SATELLITE_TIER_NONE
    if sites <= 2:
        return SATELLITE_TIER_SMALL
    return SATELLITE_TIER_LARGE


def cycle_cost(cycle, facility):
    """raw_cost_total / cycle_length_days, multiplied, ceilinged exactly once."""
    items = cycle_items(cycle["id"])
    raw_total = 0
    for item in items:
        raw_total += int(item["raw_cost_cents"])
    base = D(raw_total) / D(cycle["cycle_length_days"])
    return raw_total, ceil_int(base * satellite_multiplier(facility))


# --------------------------------------------------------------------------
# Meal forecast tray math (PRD 3.4)
# --------------------------------------------------------------------------
def waste_allowance(line_trays):
    if line_trays <= WASTE_SMALL_THRESHOLD:
        return WASTE_SMALL_FLAT
    if line_trays <= WASTE_MID_THRESHOLD:
        return ceil_int(D(line_trays) * WASTE_MID_RATE)
    return ceil_int(D(line_trays) * WASTE_LARGE_RATE)


def forecast_trays(count):
    general = int(count["general_population"])
    segregation = int(count["segregation_population"])
    satellite = int(count["satellite_population"])
    medical = int(count["medical_population"])
    general_line = ceil_int(D(general + medical) * GENERAL_ATTENDANCE_RATE)
    segregation_trays = segregation
    satellite_trays = ceil_int(D(satellite) * (Decimal("1") + SATELLITE_TRANSPORT_BUFFER))
    line_trays = general_line + segregation_trays + satellite_trays
    waste = waste_allowance(line_trays)
    return {
        "general_line_trays": general_line,
        "segregation_trays": segregation_trays,
        "satellite_trays": satellite_trays,
        "line_trays": line_trays,
        "waste_allowance_trays": waste,
        "total_forecast_trays": line_trays + waste,
    }


def special_diet_trays_for(facility_id, service_date):
    """ACTIVE orders for IN_CUSTODY inmates of this facility whose half-open
    coverage window contains the service date at midnight UTC."""
    at = date_midnight(service_date)
    if at is None:
        return 0
    total = 0
    for order in all_rows("diet_orders"):
        if order["status"] != "ACTIVE":
            continue
        inmate = DB.col("inmates").get(order["inmate_id"])
        if inmate is None:
            continue
        if inmate["facility_id"] != facility_id or inmate["status"] != "IN_CUSTODY":
            continue
        if order["effective_from"] <= at < order["effective_to"]:
            total += 1
    return total


def roster_segments(facility_id):
    """ROSTER_DRIVEN: recount IN_CUSTODY inmates bucketed by housing_unit."""
    buckets = {"GENERAL": 0, "SEGREGATION": 0, "SATELLITE": 0, "MEDICAL": 0}
    for inmate in all_rows("inmates"):
        if inmate["facility_id"] != facility_id or inmate["status"] != "IN_CUSTODY":
            continue
        unit = inmate.get("housing_unit")
        if unit in buckets:
            buckets[unit] += 1
    return {
        "general_population": buckets["GENERAL"],
        "segregation_population": buckets["SEGREGATION"],
        "satellite_population": buckets["SATELLITE"],
        "medical_population": buckets["MEDICAL"],
    }


# --------------------------------------------------------------------------
# Temperature ranges and cook-chill compliance (PRD 3.5)
# --------------------------------------------------------------------------
def temperature_in_range(log_point, temperature_f, minutes_since_cook_end,
                         minutes_since_transport_arrive):
    """Both the temperature gate and the elapsed-time gate for the log point."""
    temp = rhu(D(temperature_f), 1)
    if log_point == "COOK_END":
        return temp >= COOK_END_MIN_F
    if log_point == "CHILL_INTERMEDIATE":
        if temp > CHILL_INTERMEDIATE_MAX_F:
            return False
        return minutes_since_cook_end is not None and minutes_since_cook_end <= CHILL_INTERMEDIATE_MAX_MINUTES
    if log_point == "CHILL_FINAL":
        if temp > CHILL_FINAL_MAX_F:
            return False
        return minutes_since_cook_end is not None and minutes_since_cook_end <= CHILL_FINAL_MAX_MINUTES
    if log_point == "TRANSPORT_DEPART":
        return temp <= TRANSPORT_MAX_F
    if log_point == "TRANSPORT_ARRIVE":
        return temp <= TRANSPORT_MAX_F
    if log_point == "REHEAT_SERVE":
        if temp < REHEAT_MIN_F:
            return False
        if minutes_since_transport_arrive is None:
            # No transport arrival on record: the time clause is satisfied.
            return True
        return minutes_since_transport_arrive <= REHEAT_MAX_MINUTES
    return False


def latest_transport_arrive_at(batch_id):
    latest = None
    for log in batch_logs(batch_id):
        if log["log_point"] != "TRANSPORT_ARRIVE":
            continue
        if latest is None or log["logged_at"] > latest:
            latest = log["logged_at"]
    return latest


def _earliest(logs):
    best = None
    for log in logs:
        if best is None:
            best = log
        elif (log["logged_at"], log["created_at"], log["_seq"]) < \
                (best["logged_at"], best["created_at"], best["_seq"]):
            best = log
    return best


def recompute_batch_anchors(batch):
    """cook_end_at, chill_final_at, chill_minutes and cook_chill_compliant."""
    logs = batch_logs(batch["id"])
    cook_logs = [l for l in logs if l["log_point"] == "COOK_END"]
    earliest_cook = _earliest(cook_logs)
    batch["cook_end_at"] = earliest_cook["logged_at"] if earliest_cook else None

    chill_final_logs = [l for l in logs if l["log_point"] == "CHILL_FINAL"]
    in_range_final = [l for l in chill_final_logs if l["in_range"]]
    chosen = _earliest(in_range_final) or _earliest(chill_final_logs)
    batch["chill_final_at"] = chosen["logged_at"] if chosen else None

    if batch["cook_end_at"] is not None and batch["chill_final_at"] is not None:
        batch["chill_minutes"] = elapsed_minutes(batch["cook_end_at"], batch["chill_final_at"])
    else:
        batch["chill_minutes"] = None

    has_cook = any(l["in_range"] for l in cook_logs)
    has_intermediate = any(l["log_point"] == "CHILL_INTERMEDIATE" and l["in_range"] for l in logs)
    has_final = any(l["in_range"] for l in chill_final_logs)
    batch["cook_chill_compliant"] = bool(has_cook and has_intermediate and has_final)


# --------------------------------------------------------------------------
# Blast chiller occupancy (PRD 3.5)
# --------------------------------------------------------------------------
CHILLER_OCCUPANCY_STAGES = ("PLANNED", "COOKED", "CHILLED")


def chiller_window(scheduled_cook_start_at):
    chill_deadline_at = scheduled_cook_start_at + timedelta(minutes=CHILL_FINAL_MAX_MINUTES)
    buffered_release_at = chill_deadline_at + timedelta(minutes=CHILLER_RELEASE_BUFFER_MINUTES)
    return chill_deadline_at, buffered_release_at


def chiller_overlap_count(facility_id, new_start, new_release):
    count = 0
    for batch in facility_batches(facility_id):
        if batch["production_stage"] not in CHILLER_OCCUPANCY_STAGES:
            continue
        if new_start <= batch["buffered_release_at"] and batch["scheduled_cook_start_at"] <= new_release:
            count += 1
    return count


# --------------------------------------------------------------------------
# Sharps accountability and kitchen posture (PRD 3.6, 2.9)
# --------------------------------------------------------------------------
def is_sharp(tool_class):
    return tool_class in SHARP_CLASSES


def unaccounted_sharp_present(facility_id):
    for issuance in facility_issuances(facility_id):
        if issuance["status"] == "UNACCOUNTED" and is_sharp(issuance["tool_class"]):
            return True
    return False


def unaccounted_nonsharp_present(facility_id):
    for issuance in facility_issuances(facility_id):
        if issuance["status"] == "UNACCOUNTED" and not is_sharp(issuance["tool_class"]):
            return True
    return False


def unaccounted_any_present(facility_id):
    for issuance in facility_issuances(facility_id):
        if issuance["status"] == "UNACCOUNTED":
            return True
    return False


def derive_posture(facility, skip_unaccounted_clauses=False):
    """The waterfall of PRD 2.9; first matching clause wins.

    skip_unaccounted_clauses implements the tool-issue carve-out, where the
    unaccounted-tool clauses are reported one priority later instead.
    """
    facility_id = facility["id"]
    if not skip_unaccounted_clauses and unaccounted_sharp_present(facility_id):
        return "LOCKDOWN"
    if (facility.get("sharps_audit_shortfall") or 0) >= 1:
        return "LOCKDOWN"
    if facility.get("corrective_action_required"):
        return "RESTRICTED"
    if (facility.get("open_contraband_incident_count") or 0) >= 2:
        return "RESTRICTED"
    if not skip_unaccounted_clauses and unaccounted_nonsharp_present(facility_id):
        return "RESTRICTED"
    return "OPEN"


def refresh_facility(facility):
    """Reconcile every derived counter from its source rows and re-derive the
    posture. Returns True when any field actually moved."""
    before = (
        facility.get("sharps_issued_count"),
        facility.get("sharps_unaccounted_count"),
        facility.get("open_sharps_discrepancy_count"),
        facility.get("open_contraband_incident_count"),
        facility.get("active_special_diet_count"),
        facility.get("kitchen_posture"),
    )
    facility_id = facility["id"]
    issued = 0
    unaccounted = 0
    for issuance in facility_issuances(facility_id):
        if not is_sharp(issuance["tool_class"]):
            continue
        if issuance["status"] == "ISSUED":
            issued += 1
        elif issuance["status"] == "UNACCOUNTED":
            unaccounted += 1
    facility["sharps_issued_count"] = issued
    facility["sharps_unaccounted_count"] = unaccounted
    facility["open_sharps_discrepancy_count"] = unaccounted + (facility.get("sharps_audit_shortfall") or 0)
    facility["open_contraband_incident_count"] = len(
        [i for i in facility_incidents(facility_id) if i["status"] == "OPEN"])
    facility["active_special_diet_count"] = active_special_diet_count(facility_id)
    facility["kitchen_posture"] = derive_posture(facility)
    after = (
        facility["sharps_issued_count"],
        facility["sharps_unaccounted_count"],
        facility["open_sharps_discrepancy_count"],
        facility["open_contraband_incident_count"],
        facility["active_special_diet_count"],
        facility["kitchen_posture"],
    )
    return before != after


def active_special_diet_count(facility_id):
    total = 0
    for order in all_rows("diet_orders"):
        if order["status"] != "ACTIVE":
            continue
        inmate = DB.col("inmates").get(order["inmate_id"])
        if inmate is None:
            continue
        if inmate["facility_id"] == facility_id and inmate["status"] == "IN_CUSTODY":
            total += 1
    return total


def refresh_inmate(inmate):
    before = inmate.get("active_diet_order_count")
    inmate["active_diet_order_count"] = len(
        [o for o in inmate_diet_orders(inmate["id"]) if o["status"] == "ACTIVE"])
    return before != inmate["active_diet_order_count"]


def refresh_worker_strikes(worker):
    before = worker.get("contraband_strike_count")
    worker["contraband_strike_count"] = len([
        i for i in all_rows("contraband_incidents")
        if i.get("inmate_worker_id") == worker["id"] and i["status"] == "SANCTIONED"])
    return before != worker["contraband_strike_count"]


# --------------------------------------------------------------------------
# Missed meals (PRD 3.7)
# --------------------------------------------------------------------------
def missed_meal_count(record, forecast):
    expected = int(record["expected_service_trays"])
    served = int(record["total_trays_served"])
    tray_shortfall = max(0, expected - served)
    tolerance = floor_int(D(expected) * MISSED_MEAL_TOLERANCE_RATE)
    special_shortfall = max(
        0, int(forecast["forecast_special_diet_trays"]) - int(record["special_diet_trays_served"]))
    if tray_shortfall <= tolerance and special_shortfall == 0:
        return 0
    return max(0, tray_shortfall - tolerance) + special_shortfall * SPECIAL_DIET_MISS_WEIGHT


# --------------------------------------------------------------------------
# Contract liquidated damages waterfall (PRD 3.9)
# --------------------------------------------------------------------------
LEDGER_INPUT_STATUSES = ("CLOSED", "DISPUTED")


def contract_service_records(contract):
    facility_ids = set(f["id"] for f in contract_facilities(contract["id"]))
    return [r for r in all_rows("meal_service_records") if r["facility_id"] in facility_ids]


def contract_ledger_records(contract):
    return [r for r in contract_service_records(contract)
            if r["status"] in LEDGER_INPUT_STATUSES]


def contract_grievance_breaches(contract):
    facility_ids = set(f["id"] for f in contract_facilities(contract["id"]))
    return len([g for g in all_rows("grievances")
                if g["facility_id"] in facility_ids and g.get("sla_breached")])


def reference_cost_cents(contract):
    """Highest approved cost among ACTIVE cycles at the contract's facilities,
    ties broken by earliest created_at; the cost ceiling when none exist."""
    facility_ids = set(f["id"] for f in contract_facilities(contract["id"]))
    candidates = [c for c in all_rows("menu_cycles")
                  if c["facility_id"] in facility_ids and c["status"] == "ACTIVE"
                  and c.get("approved_cost_cents_per_meal_day") is not None]
    if not candidates:
        return int(contract["cost_ceiling_cents_per_meal_day"])
    candidates.sort(key=lambda c: (-int(c["approved_cost_cents_per_meal_day"]),
                                   c["created_at"], c["_seq"]))
    return int(candidates[0]["approved_cost_cents_per_meal_day"])


def apply_ledger(contract):
    """Steps 4 through 9, reading the step 1-3 totals already on the contract."""
    total_trays = int(contract["total_trays_served"])
    meal_days = int(contract["meal_days_served"])
    missed = int(contract["missed_meal_total"])
    breaches = int(contract["grievance_sla_breach_count"])
    subs = int(contract["substitution_total"])

    # step 4
    rate = rhu(D(subs) * Decimal("100") / D(max(1, total_trays)), 2)
    contract["substitution_rate_pct"] = rate

    # step 5
    reference = reference_cost_cents(contract)
    gross = meal_days * reference
    contract["gross_food_cost_cents"] = gross
    contract["cost_cents_per_meal_day_actual"] = rhu(D(gross) / D(max(1, meal_days)), 2)

    # step 6
    allowance = D(contract["substitution_allowance_pct"])
    if rate > allowance:
        excess = rhu(rate - allowance, 2)
        surcharge = ceil_int(D(gross) * excess / Decimal("100") * SUBSTITUTION_SURCHARGE_RATE)
    else:
        surcharge = 0
    contract["substitution_surcharge_cents"] = surcharge

    # step 7
    ld_rate = int(contract["ld_cents_per_missed_meal"])
    variant = contract.get("ld_variant") or "INCIDENT_BASED"
    if variant == "POPULATION_WEIGHTED":
        severity = Decimal("1") + rhu(D(missed) / D(max(1, meal_days)), 2)
        variant_term = ceil_int(D(missed) * D(ld_rate) * severity)
    else:
        variant_term = missed * ld_rate
    raw = variant_term + breaches * GRIEVANCE_SLA_BREACH_PENALTY_CENTS
    contract["raw_liquidated_damages_cents"] = raw

    # step 8 — the cap lands strictly before the credit
    pre_cap = raw + surcharge
    capped = min(pre_cap, int(contract["ld_monthly_cap_cents"]))
    contract["liquidated_damages_cents"] = capped

    # step 9
    credit = floor_int(D(min(capped, gross)) * COST_RECOVERY_RATE)
    contract["cost_recovery_credit_cents"] = credit
    contract["net_liquidated_damages_cents"] = max(0, capped - credit)
    ceiling = D(contract["cost_ceiling_cents_per_meal_day"])
    overrun = contract["cost_cents_per_meal_day_actual"] - ceiling
    if overrun < ZERO:
        overrun = ZERO
    score = rhu(
        Decimal("100")
        - D(missed) * SCORE_MISSED_MEAL_WEIGHT
        - D(breaches) * SCORE_BREACH_WEIGHT
        - overrun * SCORE_COST_WEIGHT, 2)
    contract["performance_score"] = clamp(score, "0.00", "100.00")


def reconcile_ledger_from_source(contract):
    """Steps 1 through 3 recomputed from source rows, then steps 4 through 9."""
    records = contract_ledger_records(contract)
    total_trays = sum(int(r["total_trays_served"]) for r in records)
    contract["total_trays_served"] = total_trays
    contract["meal_days_served"] = floor_int(D(total_trays) / D(MEAL_SLOTS_PER_DAY))
    contract["missed_meal_total"] = sum(int(r["missed_meal_count"]) for r in records)
    contract["grievance_sla_breach_count"] = contract_grievance_breaches(contract)
    record_ids = set(r["id"] for r in records)
    contract["substitution_total"] = len([
        s for s in all_rows("menu_substitutions")
        if s["approval_status"] == "APPROVED" and s["meal_service_record_id"] in record_ids])
    apply_ledger(contract)


# --------------------------------------------------------------------------
# Substitution nutrition equivalence (PRD 3.7)
# --------------------------------------------------------------------------
def substitution_equivalence(item, body):
    planned_kcal = rhu(D(item["kcal_per_100g"]) * D(item["portion_grams"]) / Decimal("100"), 2)
    planned_protein = rhu(D(item["protein_grams_per_100g"]) * D(item["portion_grams"]) / Decimal("100"), 2)
    planned_sodium = rhu(D(item["sodium_mg_per_100g"]) * D(item["portion_grams"]) / Decimal("100"), 2)
    portion = D(body["substitute_portion_grams"])
    sub_kcal = rhu(D(body["substitute_kcal_per_100g"]) * portion / Decimal("100"), 2)
    sub_protein = rhu(D(body["substitute_protein_grams_per_100g"]) * portion / Decimal("100"), 2)
    sub_sodium = rhu(D(body["substitute_sodium_mg_per_100g"]) * portion / Decimal("100"), 2)
    kcal_delta_pct = rhu((sub_kcal - planned_kcal) * Decimal("100") / planned_kcal, 2)
    protein_floor = planned_protein if planned_protein > Decimal("0.01") else Decimal("0.01")
    protein_delta_pct = rhu((sub_protein - planned_protein) * Decimal("100") / protein_floor, 2)
    sodium_delta_mg = rhu(sub_sodium - planned_sodium, 2)
    cost_variance = int(body["substitute_cost_cents"]) - int(item["raw_cost_cents"])
    equivalent = (abs(kcal_delta_pct) <= KCAL_EQUIVALENCE_BAND
                  and protein_delta_pct >= PROTEIN_EQUIVALENCE_FLOOR
                  and sodium_delta_mg <= SODIUM_EQUIVALENCE_CEILING)
    return {
        "kcal_delta_pct": kcal_delta_pct,
        "protein_delta_pct": protein_delta_pct,
        "sodium_delta_mg": sodium_delta_mg,
        "cost_variance_cents": cost_variance,
        "nutrition_equivalent": bool(equivalent),
    }


# --------------------------------------------------------------------------
# Grievance response SLA (PRD 3.8)
# --------------------------------------------------------------------------
def response_window_days(category):
    if category in GRIEVANCE_FAST_CATEGORIES:
        return GRIEVANCE_FAST_DAYS
    return GRIEVANCE_STANDARD_DAYS


def response_due_at(filed_at, category):
    return filed_at + timedelta(hours=24 * response_window_days(category))


# --------------------------------------------------------------------------
# Diet order coverage windows and verification expiry (PRD 3.3)
# --------------------------------------------------------------------------
OVERLAP_STATUSES = ("PENDING_VERIFICATION", "ACTIVE", "SUSPENDED")

RELIGIOUS_DIET_CODES = ("KOSHER", "HALAL", "VEGETARIAN_RELIGIOUS")
MEDICAL_DIET_CODES = ("RENAL", "DIABETIC_2000", "GLUTEN_FREE", "MECHANICAL_SOFT")
ALL_DIET_CODES = RELIGIOUS_DIET_CODES + MEDICAL_DIET_CODES


def verification_window_days(order_type):
    if order_type == "RELIGIOUS":
        return RELIGIOUS_VERIFICATION_DAYS
    return MEDICAL_VERIFICATION_DAYS


def window_conflict(inmate_id, order_type, new_from, new_to, exclude_id):
    """Half-open overlap against live orders of the same type for the inmate."""
    for order in inmate_diet_orders(inmate_id):
        if order["status"] not in OVERLAP_STATUSES:
            continue
        if order["order_type"] != order_type:
            continue
        if exclude_id is not None and order["id"] == exclude_id:
            continue
        if new_from < order["effective_to"] and order["effective_from"] < new_to:
            return order
    return None


def expire_due_orders(facility_id=None):
    """Sweep ACTIVE orders whose verification window has closed. Returns the
    set of rows mutated so the caller can bump versions and counters."""
    now = now_logical()
    expired = []
    for order in all_rows("diet_orders"):
        if order["status"] != "ACTIVE":
            continue
        expires = order.get("verification_expires_at")
        if expires is None or now < expires:
            continue
        inmate = DB.col("inmates").get(order["inmate_id"])
        if facility_id is not None and (inmate is None or inmate["facility_id"] != facility_id):
            continue
        order["status"] = "EXPIRED"
        touch(order)
        expired.append(order)
    return expired
