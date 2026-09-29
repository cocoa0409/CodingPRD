"""Window aggregates: racks, expected consumption, variance, savings, dossier."""

from decimal import Decimal

import db
from services import calc, derive
from util import dec, rhu

BASE_PROGRAM_FEE_CENTS = 25000
CREDIT_CAP_CENTS = 15000


def device_readings_in_window(placement_id, start, end):
    out = []
    for reading in db.rows("telemetry_readings"):
        if reading["placement_id"] != placement_id:
            continue
        if reading["source"] != "DEVICE":
            continue
        if start <= reading["reading_at"] < end:
            out.append(reading)
    return out


def rack_eligible_placements(site_id):
    return [
        p for p in derive.placements_of_site(site_id)
        if p["placement_status"] in calc.RACK_PLACEMENT_STATUSES
    ]


def rack_count(placement_id, start, end):
    total = 0
    for reading in device_readings_in_window(placement_id, start, end):
        total += reading["cycle_delta"]
    return total


def site_rack_count(site_id, start, end):
    total = 0
    for placement in rack_eligible_placements(site_id):
        total += rack_count(placement["id"], start, end)
    return total


# --------------------------------------------------------------------------
# expected chemical consumption (single round at the site-level sum)
# --------------------------------------------------------------------------

def dose_at(dispenser, instant):
    best = None
    for record in db.rows("calibration_records"):
        if record["dispenser_id"] != dispenser["id"]:
            continue
        if not record.get("applied"):
            continue
        applied_at = record.get("_applied_at")
        if applied_at is None or applied_at > instant:
            continue
        if best is None:
            best = record
        elif (applied_at, record["_seq"]) > (best["_applied_at"], best["_seq"]):
            best = record
    if best is None:
        return dec(dispenser["_initial_dose"])
    return dec(best["_applied_dose"])


def metering_dispensers(site_id, product_id):
    eligible = set(p["id"] for p in rack_eligible_placements(site_id))
    out = []
    for dispenser in derive.dispensers_of_site(site_id):
        if dispenser["product_id"] != product_id:
            continue
        if dispenser["dispenser_status"] not in ("ACTIVE", "LOCKED_OUT"):
            continue
        if dispenser["placement_id"] not in eligible:
            continue
        out.append(dispenser)
    return out


def expected_consumption_ml(site, product, basis, start, end):
    total = Decimal(0)
    for dispenser in metering_dispensers(site["id"], product["id"]):
        if basis == "NAMEPLATE":
            racks = rack_count(dispenser["placement_id"], start, end)
            total += dec(racks) * dec(product["spec_dose_ml_per_rack"])
        else:
            readings = device_readings_in_window(
                dispenser["placement_id"], start, end
            )
            for reading in readings:
                total += dec(reading["cycle_delta"]) * dose_at(
                    dispenser, reading["reading_at"]
                )
    return int(rhu(total, 0))


# --------------------------------------------------------------------------
# usage variance
# --------------------------------------------------------------------------

def delivered_ml(site_id, product_id, start, end):
    total = Decimal(0)
    for delivery in db.rows("chemical_deliveries"):
        if delivery["site_id"] != site_id:
            continue
        if delivery["product_id"] != product_id:
            continue
        if delivery["status"] != "DELIVERED":
            continue
        if start <= delivery["delivered_at"] < end:
            total += dec(delivery["quantity_ml"])
    return total


def dilution_evidence(site_id, product_id, start, end):
    for record in db.rows("calibration_records"):
        if not record.get("applied"):
            continue
        dispenser = db.get("dispensers", record["dispenser_id"])
        if dispenser is None or dispenser["product_id"] != product_id:
            continue
        placement = db.get("machine_placements", dispenser["placement_id"])
        if placement is None or placement["site_id"] != site_id:
            continue
        visit = db.get("service_visits", record["visit_id"])
        if visit is None or visit["visit_status"] != "VERIFIED":
            continue
        verified_at = visit.get("_verified_at")
        if verified_at is None or not (start <= verified_at < end):
            continue
        if record["drift_pct"] is not None and dec(record["drift_pct"]) <= Decimal("-10.00"):
            return True
    return False


def classify_variance(expected, actual, delivered, dilution):
    """Returns (variance_pct or None, classification)."""
    if expected == 0:
        return None, "INSUFFICIENT_DATA"
    variance = rhu(
        (dec(actual) - dec(expected)) / dec(expected) * Decimal(100), 2
    )
    if variance > Decimal("25.00") and delivered > 0:
        return variance, "THEFT_SUSPECT"
    if variance < Decimal("-15.00") and dilution:
        return variance, "DILUTION_SUSPECT"
    if variance > Decimal("8.00"):
        return variance, "OVERUSE"
    if variance < Decimal("-8.00"):
        return variance, "UNDERUSE"
    return variance, "WITHIN_TOLERANCE"


def compute_review_figures(review, site, product):
    start = review["period_start"]
    end = review["period_end"]
    racks = site_rack_count(site["id"], start, end)
    expected = expected_consumption_ml(site, product, review["basis"], start, end)
    delivered = delivered_ml(site["id"], product["id"], start, end)
    actual = int(
        dec(review["opening_inventory_ml"]) + delivered
        - dec(review["ending_inventory_ml"])
    )
    dilution = dilution_evidence(site["id"], product["id"], start, end)
    variance, classification = classify_variance(
        expected, actual, delivered, dilution
    )
    return {
        "rack_count_in_period": racks,
        "expected_consumption_ml": expected,
        "actual_consumption_ml": actual,
        "variance_pct": variance,
        "classification": classification,
    }


# --------------------------------------------------------------------------
# sustainability report
# --------------------------------------------------------------------------

def service_fee_rate(gross_program_cost_cents):
    if gross_program_cost_cents < 200000:
        return Decimal("0.08")
    if gross_program_cost_cents < 500000:
        return Decimal("0.06")
    return Decimal("0.04")


def sustainability_report(site, basis, start, end):
    water_saved = Decimal(0)
    energy_saved = Decimal(0)
    racks_total = 0
    for placement in rack_eligible_placements(site["id"]):
        model = derive.model_of_placement(placement)
        if model is None:
            continue
        racks = rack_count(placement["id"], start, end)
        racks_total += racks
        rated_water = dec(model["rated_water_l_per_rack"])
        if basis == "RATED":
            effective_water = rated_water
        else:
            readings = device_readings_in_window(placement["id"], start, end)
            if readings:
                total_pressure = Decimal(0)
                for reading in readings:
                    total_pressure += dec(reading["rinse_pressure_psi"])
                average = total_pressure / dec(len(readings))
                factor = rhu(average / dec(model["min_rinse_pressure_psi"]), 4)
            else:
                factor = Decimal("1.0000")
            effective_water = rated_water * factor
        water_saved += dec(racks) * (
            dec(site["baseline_water_l_per_rack"]) - effective_water
        )
        energy_saved += dec(racks) * (
            dec(site["baseline_kwh_per_rack"]) - dec(model["rated_kwh_per_rack"])
        )

    water_savings_cents = int(rhu(
        water_saved / Decimal(1000) * dec(site["water_cost_cents_per_1000l"]), 0
    ))
    energy_savings_cents = int(rhu(
        energy_saved * dec(site["energy_cost_cents_per_kwh"]), 0
    ))
    gross_savings_cents = water_savings_cents + energy_savings_cents

    chemical_spend_cents = 0
    for delivery in db.rows("chemical_deliveries"):
        if delivery["site_id"] != site["id"]:
            continue
        if delivery["status"] != "DELIVERED":
            continue
        if start <= delivery["delivered_at"] < end:
            chemical_spend_cents += delivery["amount_cents"]

    gross_program_cost_cents = chemical_spend_cents + BASE_PROGRAM_FEE_CENTS
    rate = service_fee_rate(gross_program_cost_cents)
    service_fee_cents = int(rhu(dec(chemical_spend_cents) * rate, 0))
    if gross_savings_cents <= 0:
        credit_cents = 0
    else:
        credit_cents = min(
            int(rhu(dec(gross_savings_cents) * Decimal("0.05"), 0)),
            CREDIT_CAP_CENTS,
        )
    net_program_cost_cents = (
        chemical_spend_cents + BASE_PROGRAM_FEE_CENTS + service_fee_cents
        - credit_cents
    )

    customer = db.get("customers", site["customer_id"])
    goal = dec(customer["sustainability_goal_water_l"]) if customer else Decimal(0)
    if goal == 0:
        goal_attainment_pct = None
    else:
        goal_attainment_pct = rhu(water_saved / goal * Decimal(100), 2)

    return {
        "site_id": site["id"],
        "period_start": start,
        "period_end": end,
        "basis": basis,
        "rack_count": racks_total,
        "water_saved_l": water_saved,
        "energy_saved_kwh": energy_saved,
        "water_savings_cents": water_savings_cents,
        "energy_savings_cents": energy_savings_cents,
        "gross_savings_cents": gross_savings_cents,
        "chemical_spend_cents": chemical_spend_cents,
        "gross_program_cost_cents": gross_program_cost_cents,
        "service_fee_rate": rate,
        "service_fee_cents": service_fee_cents,
        "sustainability_credit_cents": credit_cents,
        "net_program_cost_cents": net_program_cost_cents,
        "goal_attainment_pct": goal_attainment_pct,
    }


# --------------------------------------------------------------------------
# inspection dossier
# --------------------------------------------------------------------------

def dossier(site, start, end):
    placement_ids = set(p["id"] for p in derive.placements_of_site(site["id"]))
    in_scope = []
    for record in db.rows("calibration_records"):
        dispenser = db.get("dispensers", record["dispenser_id"])
        if dispenser is None or dispenser["placement_id"] not in placement_ids:
            continue
        visit = db.get("service_visits", record["visit_id"])
        if visit is None or visit["visit_status"] != "VERIFIED":
            continue
        verified_at = visit.get("_verified_at")
        if verified_at is None or not (start <= verified_at < end):
            continue
        in_scope.append((verified_at, record["created_at"], record["_seq"], record))

    in_scope.sort(key=lambda item: (item[0], item[1], item[2]))
    sanitizer = [item for item in in_scope
                 if item[3]["efficacy_result"] != "NOT_APPLICABLE"]
    latest_efficacy = "NOT_APPLICABLE"
    if sanitizer:
        latest_efficacy = sanitizer[-1][3]["efficacy_result"]
    sanitizer_passed = len([
        item for item in sanitizer if item[3]["efficacy_result"] == "PASS"
    ])

    readings_total = 0
    exceptions = 0
    for placement in derive.placements_of_site(site["id"]):
        model = derive.model_of_placement(placement)
        for reading in device_readings_in_window(placement["id"], start, end):
            readings_total += 1
            if model is not None and reading["final_rinse_temp_f"] < model["min_final_rinse_temp_f"]:
                exceptions += 1

    open_critical = 0
    for placement in derive.placements_of_site(site["id"]):
        for alert in derive.alerts_of_placement(placement["id"]):
            if (alert["severity"] == "CRITICAL"
                    and alert["status"] in calc.OPEN_ALERT_STATUSES):
                open_critical += 1

    ready = (
        len(sanitizer) >= 1
        and latest_efficacy == "PASS"
        and exceptions == 0
        and open_critical == 0
    )
    return {
        "site_id": site["id"],
        "period_start": start,
        "period_end": end,
        "calibration_records_total": len(in_scope),
        "sanitizer_tests_total": len(sanitizer),
        "sanitizer_tests_passed": sanitizer_passed,
        "latest_efficacy_result": latest_efficacy,
        "final_rinse_temp_readings_total": readings_total,
        "final_rinse_temp_exceptions": exceptions,
        "open_critical_alert_count": open_critical,
        "dossier_status": "READY" if ready else "DEFICIENT",
    }
