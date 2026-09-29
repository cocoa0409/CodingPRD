"""The fourteen calculation rules of the battery warranty domain."""
from datetime import timedelta
from decimal import Decimal

from common import (D, db, now, rhu, rhu_int, pack_modules, vehicle_snapshots,
                    pack_thermal_events, by_created)

VALID = "VALID"


# ------------------------------------------------- 1. temperature correction
def temperature_correction_factor(coolant_temp_c):
    c = D(coolant_temp_c)
    if c < D("0.0"):
        return D("1.06")
    if c < D("15.0"):
        return D("1.03")
    if c <= D("35.0"):
        return D("1.00")
    return D("0.97")


def corrected_capacity(reported_capacity_kwh, coolant_temp_c):
    factor = temperature_correction_factor(coolant_temp_c)
    return rhu(D(reported_capacity_kwh) * factor, 3)


# ------------------------------------------------- 2. snapshot validity flag
def snapshot_validity(vehicle, pack, captured_at, odometer_miles, reported_capacity_kwh):
    if captured_at > now():
        return "INVALID_FUTURE_CAPTURE"
    reported = D(reported_capacity_kwh)
    if reported <= 0:
        return "INVALID_CAPACITY_RANGE"
    if pack is not None:
        ceiling = D(pack["nominal_capacity_kwh"]) * D("1.05")
        if reported > ceiling:
            return "INVALID_CAPACITY_RANGE"
    for prior in vehicle_snapshots(vehicle["id"]):
        if prior["validity_flag"] != VALID:
            continue
        if prior["captured_at"] <= captured_at and prior["odometer_miles"] > odometer_miles:
            return "INVALID_ODOMETER_REGRESSION"
    return VALID


def derive_vehicle_odometer(vehicle_id):
    """MAX(odometer_miles) over VALID snapshots, else 0."""
    best = 0
    for snap in db.snapshots.values():
        if snap["vehicle_id"] != vehicle_id:
            continue
        if snap["validity_flag"] != VALID:
            continue
        if snap["odometer_miles"] > best:
            best = snap["odometer_miles"]
    return best


# --------------------------------------------- 3. diagnostic validity gating
def snapshot_window(vehicle, program):
    """Returns (all_valid, fresh, window) using the pinned ordering."""
    all_valid = [s for s in vehicle_snapshots(vehicle["id"]) if s["validity_flag"] == VALID]
    cutoff = now() - timedelta(days=program["snapshot_freshness_days"])
    fresh = [s for s in all_valid if s["captured_at"] >= cutoff]
    ordered = sorted(fresh, key=lambda s: (s["captured_at"], s["_seq"]), reverse=True)
    window = ordered[:program["snapshot_window_size"]]
    return all_valid, fresh, window


def nominal_basis(variant, pack, faulted_after_write):
    if variant == "TELEMATICS_FLEET":
        return rhu(pack["nominal_capacity_kwh"], 3)
    healthy = pack["module_count"] - faulted_after_write
    return rhu(D(pack["nominal_capacity_kwh"]) * D(healthy) / D(pack["module_count"]), 3)


def diagnostic_validity(variant, program, all_valid, fresh, window, basis, bench):
    if not all_valid:
        return "INSUFFICIENT_DATA"
    if not fresh:
        return "STALE_TELEMETRY"
    if variant == "TELEMATICS_FLEET":
        if len(window) < program["snapshot_min_count"]:
            return "INSUFFICIENT_DATA"
    else:
        if bench is None:
            return "INSUFFICIENT_DATA"
        if D(bench) > D(basis) * D("1.05"):
            return "BENCH_OUT_OF_RANGE"
    return VALID


# ------------------------------------------------------ 4. state-of-health %
def estimated_capacity(variant, program, window, bench):
    if variant != "TELEMATICS_FLEET":
        # BENCH_CAPACITY_TEST: "the numerator is simply `bench_measured_capacity_kwh`".
        if bench is None:
            return None
        return rhu(bench, 3)
    if not window:
        return None
    values = [D(s["corrected_capacity_kwh"]) for s in window]
    if len(values) == program["snapshot_window_size"]:
        ordered = sorted(values)
        trimmed = ordered[1:-1]
    else:
        trimmed = values
    if not trimmed:
        return None
    total = Decimal(0)
    for v in trimmed:
        total += v
    return rhu(total / D(len(trimmed)), 3)


def retention_pct(estimated, basis):
    if estimated is None or basis is None or D(basis) == 0:
        return None
    return rhu(D(estimated) / D(basis) * D(100), 2)


# --------------------------------------- 5. elapsed months + coverage banding
def elapsed_months(in_service_date, at):
    months = (at.year - in_service_date.year) * 12 + (at.month - in_service_date.month)
    if at.day < in_service_date.day:
        months -= 1
    return months


def coverage_position(program, months, miles):
    for row in program["retention_schedule"]:
        if months <= row["through_months"] and miles <= row["through_miles"]:
            return "IN_COVERAGE", row["min_retention_pct"]
    goodwill_months = program["coverage_months"] + program["goodwill_months"]
    goodwill_miles = program["coverage_miles"] + program["goodwill_miles"]
    if months <= goodwill_months and miles <= goodwill_miles:
        return "GOODWILL_BAND", program["retention_schedule"][-1]["min_retention_pct"]
    return "OUT_OF_COVERAGE", None


def qualifies(validity, position, retention, applicable):
    if validity != VALID:
        return False
    if position not in ("IN_COVERAGE", "GOODWILL_BAND"):
        return False
    if retention is None or applicable is None:
        return False
    return D(retention) <= D(applicable)


# ------------------------------------------------------- pack module counters
def faulted_module_count(pack_id):
    return len([m for m in pack_modules(pack_id) if m["status"] == "FAULTED"])


def replaced_module_count(pack_id):
    return len([m for m in pack_modules(pack_id) if m["status"] == "REPLACED"])


# ------------------------------------------------------- 6. remedy escalation
def remedy_decision(program, pack, assessment):
    faulted = faulted_module_count(pack["id"])
    module_count = pack["module_count"]
    delta = assessment["max_cell_delta_mv"] or 0
    retention = assessment["retention_pct"]
    replaced = replaced_module_count(pack["id"])
    severe = [e for e in pack_thermal_events(pack["id"]) if e["severity"] in ("S3", "S4")]
    if len(severe) >= 1:
        return "PACK_REPLACEMENT", "THERMAL_HISTORY"
    if delta >= program["cell_delta_pack_threshold_mv"]:
        return "PACK_REPLACEMENT", "CELL_DELTA"
    if retention is not None and D(retention) < D(program["pack_replacement_retention_pct"]):
        return "PACK_REPLACEMENT", "RETENTION_FLOOR"
    allowance = max(0, program["module_replacement_cap"] - replaced)
    module_cap = module_count // 4
    if faulted > min(allowance, module_cap):
        return "PACK_REPLACEMENT", "MODULE_ALLOWANCE"
    if faulted >= 1:
        return "MODULE_REPLACEMENT", "MODULE_FAULT"
    return "SOFTWARE_REMEDIATION", "NO_MODULE_FAULT"


# ------------------------------------------------------------ 7. remedy costs
def remedy_cost_cents(program, center, pack, remedy, replacement_pack):
    faulted = faulted_module_count(pack["id"])
    module_count = pack["module_count"]
    if remedy == "MODULE_REPLACEMENT":
        parts = program["module_unit_price_cents"] * faulted
        hours = D(program["labor_hours_module"])
    elif remedy == "PACK_REPLACEMENT":
        pack_type = replacement_pack["pack_type"] if replacement_pack else "REMANUFACTURED"
        if pack_type == "REMANUFACTURED":
            parts = program["pack_price_reman_cents"]
        else:
            parts = program["pack_price_new_cents"]
        hours = D(program["labor_hours_pack"])
    else:
        parts = 0
        hours = D("0.50")
    labor = rhu_int(hours * D(center["labor_rate_cents_per_hour"]))
    if remedy == "SOFTWARE_REMEDIATION":
        basis = 0
        weight = D("0.000")
    else:
        if pack["damaged_defective"]:
            basis = program["surcharge_un3536_cents"]
        elif remedy == "PACK_REPLACEMENT":
            basis = program["surcharge_un3480_cents"]
        else:
            basis = program["surcharge_un3481_cents"]
        if remedy == "PACK_REPLACEMENT":
            weight = D(pack["gross_weight_kg"])
        else:
            weight = rhu(D(pack["gross_weight_kg"]) * D(faulted) / D(module_count), 3)
    hazmat = rhu_int(D(basis) * weight / D(100))
    diagnostic = program["diagnostic_fee_cents"]
    return int(parts) + int(labor) + int(hazmat) + int(diagnostic)


# --------------------------------------------------------- 8. claim settlement
ADMIN_FEE_TIERS = ((200000, 0), (500000, 7500))
ADMIN_FEE_TOP = 15000


def admin_fee_for(oem_share_cents):
    for ceiling, fee in ADMIN_FEE_TIERS:
        if oem_share_cents < ceiling:
            return fee
    return ADMIN_FEE_TOP


def settlement(program, assessment, cost_cents):
    position = assessment["coverage_position"]
    if position == "IN_COVERAGE":
        variant = "FULL_COVERAGE"
        factor = D("0.0000")
    else:
        variant = "GOODWILL_PRORATED"
        months_over = max(0, assessment["elapsed_months"] - program["coverage_months"])
        miles_over = max(0, assessment["assessed_odometer_miles"] - program["coverage_miles"])
        if program["goodwill_months"] > 0:
            month_ratio = D(months_over) / D(program["goodwill_months"])
        else:
            month_ratio = D(1) if months_over > 0 else D(0)
        if program["goodwill_miles"] > 0:
            mile_ratio = D(miles_over) / D(program["goodwill_miles"])
        else:
            mile_ratio = D(1) if miles_over > 0 else D(0)
        raw = max(month_ratio, mile_ratio)
        if raw > D(1):
            raw = D(1)
        factor = rhu(raw, 4)
    owner = rhu_int(D(cost_cents) * factor)
    oem = int(cost_cents) - int(owner)
    admin = admin_fee_for(oem)
    return {
        "settlement_variant": variant,
        "proration_factor": factor,
        "owner_share_cents": int(owner),
        "oem_share_cents": int(oem),
        "admin_fee_cents": int(admin),
        "oem_total_cents": int(oem) + int(admin),
    }


# ------------------------------------------------ 9. replacement pack selector
def _eligible_common(pack, center, removed):
    if pack["status"] != "STOCK":
        return False
    if pack["installed_vehicle_id"] is not None:
        return False
    if pack["stock_region_code"] != center["region_code"]:
        return False
    if pack["module_count"] != removed["module_count"]:
        return False
    if D(pack["nominal_capacity_kwh"]) < D(removed["nominal_capacity_kwh"]):
        return False
    return True


def select_replacement_pack(program, center, removed):
    reman = []
    for pack in db.packs.values():
        if pack["id"] == removed["id"]:
            continue
        if pack["pack_type"] != "REMANUFACTURED":
            continue
        if not _eligible_common(pack, center, removed):
            continue
        if pack["refurb_soh_pct"] is None:
            continue
        if D(pack["refurb_soh_pct"]) < D(program["reman_min_soh_pct"]):
            continue
        reman.append(pack)
    if reman:
        reman.sort(key=lambda p: (-D(p["refurb_soh_pct"]), p["remanufacture_count"],
                                  p["created_at"], p["_seq"]))
        return reman[0]
    if not program["allow_new_pack_substitution"]:
        return None
    fresh = []
    for pack in db.packs.values():
        if pack["id"] == removed["id"]:
            continue
        if pack["pack_type"] != "NEW":
            continue
        if not _eligible_common(pack, center, removed):
            continue
        fresh.append(pack)
    if not fresh:
        return None
    fresh.sort(key=lambda p: (p["remanufacture_count"], p["created_at"], p["_seq"]))
    return fresh[0]


# ----------------------------------------------- 10. hazmat classification set
def resolve_program_for_pack(pack):
    """Packs carry no program FK; resolve one through the pack's vehicle history."""
    vehicle_id = pack.get("installed_vehicle_id") or pack.get("_last_vehicle_id")
    if vehicle_id and vehicle_id in db.vehicles:
        vehicle = db.vehicles[vehicle_id]
        if vehicle["warranty_program_id"] in db.programs:
            return db.programs[vehicle["warranty_program_id"]]
    for assessment in reversed(by_created(list(db.assessments.values()))):
        if assessment["pack_id"] == pack["id"]:
            vehicle = db.vehicles.get(assessment["vehicle_id"])
            if vehicle and vehicle["warranty_program_id"] in db.programs:
                return db.programs[vehicle["warranty_program_id"]]
    for claim in reversed(by_created(list(db.claims.values()))):
        if claim.get("replacement_pack_id") == pack["id"]:
            vehicle = db.vehicles.get(claim["vehicle_id"])
            if vehicle and vehicle["warranty_program_id"] in db.programs:
                return db.programs[vehicle["warranty_program_id"]]
    programs = by_created(list(db.programs.values()))
    return programs[0] if programs else None


HAZMAT_SURCHARGE_FIELD = {
    "UN3480": "surcharge_un3480_cents",
    "UN3481": "surcharge_un3481_cents",
    "UN3536": "surcharge_un3536_cents",
}


def shipment_hazmat(pack, shipment_contents, transport_mode):
    if pack["damaged_defective"]:
        classification = "UN3536"
    elif shipment_contents == "FULL_PACK":
        classification = "UN3480"
    else:
        classification = "UN3481"
    if classification == "UN3536":
        required_spec = "SP376_STRONG_OUTER"
    else:
        required_spec = "STANDARD_UN_4G"
    if classification == "UN3536" or transport_mode == "AIR":
        soc_limit = D("30.00")
    else:
        soc_limit = D("50.00")
    if shipment_contents == "FULL_PACK":
        weight = rhu(pack["gross_weight_kg"], 3)
    else:
        replaced = replaced_module_count(pack["id"])
        weight = rhu(D(pack["gross_weight_kg"]) * D(replaced) / D(pack["module_count"]), 3)
    program = resolve_program_for_pack(pack)
    if program is None:
        basis = 0
    else:
        basis = program[HAZMAT_SURCHARGE_FIELD[classification]]
    fee = rhu_int(D(basis) * weight / D(100))
    return {
        "hazmat_classification": classification,
        "required_packaging_spec": required_spec,
        "gross_weight_kg": weight,
        "hazmat_fee_cents": int(fee),
        "soc_limit_pct": soc_limit,
    }


# --------------------------------------- 11. regulatory notification deadline
def notification_deadline(severity, detected_at):
    if severity == "S4":
        return detected_at + timedelta(hours=24)
    if severity == "S3":
        return detected_at + timedelta(hours=72)
    return None


def notification_required(severity):
    return severity in ("S3", "S4")


# ------------------------------------------------------- 12. HV bay occupancy
def windows_overlap(existing_start, existing_end, new_start, new_end):
    return existing_start < new_end and new_start < existing_end


OCCUPYING_STATUSES = ("FULFILLED", "CLOSED")


def bay_occupancy(center_id, new_start, new_end, exclude_claim_id=None):
    count = 0
    for claim in db.claims.values():
        if claim["id"] == exclude_claim_id:
            continue
        if claim["service_center_id"] != center_id:
            continue
        if claim["adjudication_status"] not in OCCUPYING_STATUSES:
            continue
        start = claim.get("hv_bay_window_start")
        end = claim.get("hv_bay_window_end")
        if start is None or end is None:
            continue
        if windows_overlap(start, end, new_start, new_end):
            count += 1
    return count


# --------------------------------------------------- 13. technician cool-down
COOLDOWN = timedelta(minutes=60)


def cooldown_conflict(technician, new_start):
    last = technician.get("last_hv_window_end_at")
    if last is None:
        return False
    return new_start < (last + COOLDOWN)


# -------------------------------------------------------- 14. lab deviation %
def lab_deviation(basis, lab_measured, oem_retention):
    lab_retention = retention_pct(rhu(lab_measured, 3), basis)
    if lab_retention is None or oem_retention is None:
        return lab_retention, None
    deviation = rhu(D(lab_retention) - D(oem_retention), 2)
    return lab_retention, deviation


def dispute_outcome(deviation, tolerance):
    if deviation is None:
        return "RESOLVED_UPHELD"
    tol = D(tolerance)
    if D(deviation) < -tol:
        return "RESOLVED_OVERTURNED"
    if D(deviation) > tol:
        return "RESOLVED_DOWNGRADED"
    return "RESOLVED_UPHELD"


# ------------------------------------------------- center compliance scoring
def compliance_score_for(center):
    score = 100 - 15 * center["rejected_shipment_count"] - 40 * center["late_notification_count"]
    return max(0, score)
