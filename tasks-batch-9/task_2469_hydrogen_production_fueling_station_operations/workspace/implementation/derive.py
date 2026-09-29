"""Derived fields and the thirteen declared calculations."""
from datetime import timedelta
from decimal import Decimal as D
from decimal import ROUND_HALF_UP

from constants import (
    ADMIN_RATE_HIGH,
    ADMIN_RATE_LOW,
    ADMIN_RATE_MID,
    ADMIN_TIER_HIGH_MT,
    ADMIN_TIER_MID_MT,
    ANALYTE_ORDER,
    BANK_ORDER_CASCADE,
    BANK_ORDER_MAKEUP,
    CI_BENCHMARK_GCO2E_PER_MJ,
    COMPRESSION_ADDER_G_PER_KG,
    DAILY_BOILOFF_RATE,
    EER,
    H2_LHV_MJ_PER_KG,
    INSPECTION_GRACE_DAYS,
    KG_PER_L_PER_BAR,
    MC_FORMULA_RELIEF_C,
    METER_TOLERANCE_PCT,
    MIN_HIGH_BANK_DELIVERABLE_KG,
    NG_TOTAL_G_PER_MMBTU,
    OPTIONAL_ANALYTES,
    PRECOOL_TABLE,
    PRESSURE_COEFF_PER_BAR,
    PURITY_LIMITS,
    REF_PRESSURE_BAR,
    REF_TEMP_C,
    TEMP_COEFF_PER_C,
    TERMINAL_BAR,
)
from errors import raise_error
from store import db, sort_created

ZERO3 = D("0.000")


# --------------------------------------------------------------------------
# rounding
# --------------------------------------------------------------------------
def rq(value, dp):
    if not isinstance(value, D):
        value = D(str(value))
    return value.quantize(D(1).scaleb(-dp), rounding=ROUND_HALF_UP)


def q0(value):
    return int(rq(value, 0))


def q1(value):
    return rq(value, 1)


def q2(value):
    return rq(value, 2)


def q3(value):
    return rq(value, 3)


def q4(value):
    return rq(value, 4)


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def clock():
    return db.clock


def clock_date():
    return db.clock.date()


# --------------------------------------------------------------------------
# collections
# --------------------------------------------------------------------------
def vessels_of(station_id):
    return sort_created([v for v in db.pressure_vessels.values()
                         if v["station_id"] == station_id])


def events_of(station_id):
    return sort_created([e for e in db.safety_events.values()
                         if e["station_id"] == station_id])


def certs_of(station_id):
    return sort_created([c for c in db.responder_certs.values()
                         if c["station_id"] == station_id])


def sessions_of(station_id):
    return sort_created([s for s in db.dispense_sessions.values()
                         if s["station_id"] == station_id])


def deliveries_of(station_id):
    return sort_created([d for d in db.deliveries.values()
                         if d["station_id"] == station_id])


def ledger_of(station_id):
    """Replay order: occurred_at ASC then sequence_no ASC (PRD 2.9)."""
    rows = [e for e in db.ledger_entries.values() if e["station_id"] == station_id]
    return sorted(rows, key=lambda e: (e["occurred_at"], e["sequence_no"]))


def claims_of(station_id):
    return sort_created([c for c in db.incentive_claims.values()
                         if c["station_id"] == station_id])


def reports_of_agreement(agreement_id):
    return sort_created([r for r in db.uptime_reports.values()
                         if r["funding_agreement_id"] == agreement_id])


def reports_of_station(station_id):
    return sort_created([r for r in db.uptime_reports.values()
                         if r["station_id"] == station_id])


def tests_of_lot(lot_id):
    return [t for t in db.purity_tests.values() if t["production_lot_id"] == lot_id]


def contracts_of_asset(asset_id):
    return sort_created([c for c in db.power_contracts.values()
                         if c["production_asset_id"] == asset_id])


def deliveries_of_lot(lot_id):
    return sort_created([d for d in db.deliveries.values()
                         if d["production_lot_id"] == lot_id])


# --------------------------------------------------------------------------
# PressureVessel derivations (calculations.operational_thresholds (1))
# --------------------------------------------------------------------------
def vessel_status(vessel):
    if vessel["condemned"]:
        return "CONDEMNED"
    today = clock_date()
    due = vessel["next_inspection_due_date"]
    if today < due:
        return "CURRENT"
    if today <= due + timedelta(days=INSPECTION_GRACE_DAYS):
        return "DUE"
    return "OVERDUE"


def vessel_stored_mass(vessel):
    return q3(vessel["current_pressure_bar"] * vessel["water_volume_l"] * KG_PER_L_PER_BAR)


def vessel_deliverable(vessel):
    usable = vessel["current_pressure_bar"] - vessel["min_residual_bar"]
    if usable < 0:
        usable = D(0)
    return usable * vessel["water_volume_l"] * KG_PER_L_PER_BAR


# --------------------------------------------------------------------------
# ResponderCertification (calculations.operational_thresholds (2))
# --------------------------------------------------------------------------
def cert_is_current(cert):
    today = clock_date()
    return cert["valid_from"] <= today <= cert["expires_on"]


def trained_responders(station_id):
    return sum(1 for c in certs_of(station_id)
               if c["cert_type"] == "EMERGENCY_RESPONSE" and cert_is_current(c))


# --------------------------------------------------------------------------
# Inventory ledger (calculations.onsite_inventory_reconciliation)
# --------------------------------------------------------------------------
def replay_ledger(station_id):
    """Returns a list of (entry, resulting_onsite_kg) in replay order."""
    running = ZERO3
    out = []
    for entry in ledger_of(station_id):
        running = q3(running + entry["delta_kg"])
        out.append((entry, running))
    return out


def onsite_inventory(station_id):
    replay = replay_ledger(station_id)
    return replay[-1][1] if replay else ZERO3


def reserved_kg(station_id):
    total = D(0)
    for session in sessions_of(station_id):
        if session["fill_status"] in ("PRECOOLING", "FUELING"):
            total += session["planned_kg"]
    return q3(total)


def inbound_planned_kg(station_id):
    total = D(0)
    for delivery in deliveries_of(station_id):
        if delivery["status"] in ("SCHEDULED", "ARRIVED"):
            total += delivery["planned_kg"]
    return q3(total)


def total_deliverable_kg(station_id, high_only=False):
    total = D(0)
    for vessel in vessels_of(station_id):
        if vessel_status(vessel) not in ("CURRENT", "DUE"):
            continue
        if high_only and vessel["bank_tier"] != "HIGH":
            continue
        total += vessel_deliverable(vessel)
    return q3(total)


def available_kg(station_id):
    return q3(onsite_inventory(station_id) - reserved_kg(station_id))


def projected_available_kg(station_id):
    return q3(available_kg(station_id) + inbound_planned_kg(station_id))


def supply_alert(station):
    return projected_available_kg(station["id"]) < station["reserve_floor_kg"]


# --------------------------------------------------------------------------
# calculations.station_safety_posture
# --------------------------------------------------------------------------
def safety_posture(station):
    station_id = station["id"]
    outstanding = [e for e in events_of(station_id)
                   if e["status"] in ("OPEN", "ACKNOWLEDGED")]
    if (station["leak_detection_status"] == "ALARM"
            or station["ventilation_status"] == "FAULT"
            or station["setback_compliant"] is False
            or any(e["severity"] == "CRITICAL" for e in outstanding)):
        return "FROZEN"
    if (station["compressor_status"] == "OFFLINE"
            or total_deliverable_kg(station_id, high_only=True) < MIN_HIGH_BANK_DELIVERABLE_KG
            or any(vessel_status(v) in ("OVERDUE", "CONDEMNED")
                   for v in vessels_of(station_id))
            or any(e["severity"] == "MAJOR" for e in outstanding)):
        return "RESTRICTED"
    return "OPEN"


# --------------------------------------------------------------------------
# calculations.metering_accuracy_rollup
# --------------------------------------------------------------------------
def metering_rollup(station_id):
    now = clock()
    rows = [s for s in sessions_of(station_id)
            if s["billing_status"] == "METERED"
            and s["started_at"] is not None
            and s["started_at"].year == now.year
            and s["started_at"].month == now.month]
    if not rows:
        return {
            "metered_kg_mtd": ZERO3,
            "corrected_kg_mtd": ZERO3,
            "metering_error_pct_mtd": ZERO3,
            "metering_accuracy_flag": "WITHIN_TOLERANCE",
        }
    metered = q3(sum((s["metered_kg"] for s in rows), D(0)))
    # rounding order is pinned: per-session corrected_kg is already rounded to 3 dp
    corrected = q3(sum((s["corrected_kg"] for s in rows), D(0)))
    if corrected == 0:
        error_pct = ZERO3
    else:
        error_pct = q3((metered - corrected) / corrected * 100)
    flag = "WITHIN_TOLERANCE" if abs(error_pct) <= METER_TOLERANCE_PCT else "OUT_OF_TOLERANCE"
    return {
        "metered_kg_mtd": metered,
        "corrected_kg_mtd": corrected,
        "metering_error_pct_mtd": error_pct,
        "metering_accuracy_flag": flag,
    }


def credits_issued_total_mt(station_id):
    total = D(0)
    for claim in claims_of(station_id):
        if claim["status"] == "CREDITS_ISSUED":
            total += claim["net_credits_mt"]
    return q3(total)


# --------------------------------------------------------------------------
# FundingAgreement holdback
# --------------------------------------------------------------------------
def holdback_balance_cents(agreement, exclude_report_id=None):
    charged = 0
    for report in reports_of_agreement(agreement["id"]):
        if exclude_report_id is not None and report["id"] == exclude_report_id:
            continue
        if report["status"] == "FINAL":
            charged += report["penalty_cents"]
    value = agreement["initial_holdback_cents"] - charged
    return value if value > 0 else 0


# --------------------------------------------------------------------------
# ProductionLot derivations
# --------------------------------------------------------------------------
def accepted_delivered_kg(lot_id):
    total = D(0)
    for delivery in deliveries_of_lot(lot_id):
        if delivery["status"] == "ACCEPTED" and delivery["net_receipt_kg"] is not None:
            total += delivery["net_receipt_kg"]
    return q3(total)


def latest_purity_test(lot_id):
    rows = tests_of_lot(lot_id)
    if not rows:
        return None
    rows.sort(key=lambda t: (t["sampled_at"], t["created_at"], t["_seq"]))
    return rows[-1]


# --------------------------------------------------------------------------
# calculations.production_lot_carbon_intensity
# --------------------------------------------------------------------------
def select_power_contract(asset_id, at_instant):
    candidates = [c for c in contracts_of_asset(asset_id)
                  if c["effective_from"] <= at_instant < c["effective_to"]]
    if not candidates:
        return None
    # created_at ASC is the tie-break; a stable sort by effective_from DESC keeps it.
    candidates.sort(key=lambda c: (c["created_at"], c["_seq"]))
    candidates.sort(key=lambda c: c["effective_from"], reverse=True)
    return candidates[0]


def carbon_intensity(lot, contract, asset, variant, certified):
    renewable_pct = (contract["hourly_matched_renewable_pct"] if variant == "HOURLY_MATCHED"
                     else contract["annual_renewable_pct"])
    fresh_kg = lot["mass_kg"] - lot["carryover_kg"]
    electricity_g = (lot["energy_consumed_kwh"]
                     * (contract["grid_ci_gco2e_per_mwh"] / D(1000))
                     * (D(1) - renewable_pct / D(100)))
    feedstock_g = (lot["feedstock_consumed_mmbtu"]
                   * NG_TOTAL_G_PER_MMBTU
                   * (D(1) - asset["ccs_capture_rate"]))
    compression_g = fresh_kg * COMPRESSION_ADDER_G_PER_KG
    own_g = electricity_g + feedstock_g + compression_g

    if not lot["predecessor_lot_id"] or lot["carryover_kg"] == 0:
        carryover_g = D(0)
    else:
        predecessor = db.production_lots[lot["predecessor_lot_id"]]
        predecessor_ci = (predecessor["ci_certified_gco2e_per_mj"] if certified
                          else predecessor["ci_provisional_gco2e_per_mj"])
        if predecessor_ci is None:
            predecessor_ci = D(0)
        carryover_g = lot["carryover_kg"] * H2_LHV_MJ_PER_KG * predecessor_ci

    return q2((own_g + carryover_g) / (lot["mass_kg"] * H2_LHV_MJ_PER_KG))


# --------------------------------------------------------------------------
# calculations.purity_verdict
# --------------------------------------------------------------------------
def purity_verdict(values):
    measured = [name for name in ANALYTE_ORDER if values.get(name) is not None]
    failing = [name for name in measured if values[name] > PURITY_LIMITS[name]]
    if failing:
        verdict = "FAIL"
    elif any(values.get(name) is None for name in OPTIONAL_ANALYTES):
        verdict = "INDETERMINATE"
    else:
        verdict = "PASS"
    margins = [q3((PURITY_LIMITS[name] - values[name]) / PURITY_LIMITS[name] * 100)
               for name in measured]
    margin = min(margins) if margins else ZERO3
    return verdict, failing, margin


# --------------------------------------------------------------------------
# calculations.required_precool_temperature
# --------------------------------------------------------------------------
def required_precool_c(ambient_temp_c, pressure_class, fill_protocol):
    if ambient_temp_c > D("30.0"):
        band = "HOT"
    elif ambient_temp_c > D("10.0"):
        band = "MILD"
    else:
        band = "COLD"
    value = PRECOOL_TABLE[pressure_class][band]
    if fill_protocol == "MC_FORMULA":
        value = value + MC_FORMULA_RELIEF_C
    return q1(value)


# --------------------------------------------------------------------------
# calculations.cascade_fill_allocation
# --------------------------------------------------------------------------
def cascade_allocation(station, session):
    """Pure simulation. Returns (plan, direct_kg, makeup_kg, pressures) or raises."""
    terminal = TERMINAL_BAR[session["target_pressure_class"]]
    candidates = [v for v in vessels_of(station["id"])
                  if vessel_status(v) in ("CURRENT", "DUE")]
    pressures = {v["id"]: v["current_pressure_bar"] for v in candidates}
    plan = []

    def sweep(order, use_terminal_floor):
        nonlocal remaining
        for tier in order:
            for vessel in [v for v in candidates if v["bank_tier"] == tier]:
                floor_bar = vessel["min_residual_bar"]
                if use_terminal_floor and terminal > floor_bar:
                    floor_bar = terminal
                usable_bar = pressures[vessel["id"]] - floor_bar
                if usable_bar < 0:
                    usable_bar = D(0)
                vessel_kg = usable_bar * vessel["water_volume_l"] * KG_PER_L_PER_BAR
                take = q3(remaining if remaining < vessel_kg else vessel_kg)
                if take > 0:
                    pressures[vessel["id"]] = q2(
                        pressures[vessel["id"]]
                        - take / (vessel["water_volume_l"] * KG_PER_L_PER_BAR))
                    plan.append({
                        "bank_tier": vessel["bank_tier"],
                        "vessel_id": vessel["id"],
                        "kg": take,
                        "pressure_after_bar": pressures[vessel["id"]],
                    })
                    remaining = q3(remaining - take)

    remaining = session["planned_kg"]
    sweep(BANK_ORDER_CASCADE, True)
    direct_kg = q3(sum((row["kg"] for row in plan), D(0)))

    makeup_kg = q3(session["planned_kg"] - direct_kg)
    if makeup_kg > 0 and station["compressor_status"] == "OFFLINE":
        raise_error("ERR_COMPRESSOR_OFFLINE")
    remaining = makeup_kg
    sweep(BANK_ORDER_MAKEUP, False)
    if remaining > 0:
        raise_error("ERR_CASCADE_INSUFFICIENT")
    return plan, direct_kg, makeup_kg, pressures


# --------------------------------------------------------------------------
# calculations.dispense_metered_mass_correction
# --------------------------------------------------------------------------
def meter_correction(metered_kg, ambient_temp_c, avg_dispense_pressure_bar):
    factor = (D(1)
              + (REF_TEMP_C - ambient_temp_c) * TEMP_COEFF_PER_C
              + (avg_dispense_pressure_bar - REF_PRESSURE_BAR) * PRESSURE_COEFF_PER_BAR)
    corrected = q3(metered_kg * factor)
    if corrected == 0:
        error_pct = ZERO3
    else:
        error_pct = q3((metered_kg - corrected) / corrected * 100)
    return factor, corrected, error_pct, abs(error_pct) <= METER_TOLERANCE_PCT


# --------------------------------------------------------------------------
# calculations.delivery_net_receipt
# --------------------------------------------------------------------------
def delivery_loss_terms(delivery, arrived_at):
    transit_hours = q3(
        D(str((arrived_at - delivery["departed_at"]).total_seconds())) / D(3600))
    if delivery["mode"] == "TUBE_TRAILER":
        heel_kg = q3(delivery["trailer_final_pressure_bar"]
                     * delivery["trailer_water_volume_l"]
                     * KG_PER_L_PER_BAR)
        boiloff_kg = ZERO3
    else:
        heel_kg = ZERO3
        boiloff_kg = q3(delivery["planned_kg"] * DAILY_BOILOFF_RATE * transit_hours / D(24))
    net_receipt_kg = q3(delivery["planned_kg"] - heel_kg - boiloff_kg)
    return transit_hours, heel_kg, boiloff_kg, net_receipt_kg


# --------------------------------------------------------------------------
# calculations.incentive_credit_netting
# --------------------------------------------------------------------------
def credit_netting(claim):
    rows = [s for s in sessions_of(claim["station_id"])
            if s["billing_status"] == "METERED"
            and s["started_at"] is not None
            and claim["period_start"] <= s["started_at"].date() <= claim["period_end"]]
    dispensed_kg = q3(sum((s["corrected_kg"] for s in rows), D(0)))
    energy_mj = q3(dispensed_kg * H2_LHV_MJ_PER_KG)

    lots = [db.production_lots[lot_id] for lot_id in claim["production_lot_ids"]]
    weights = [accepted_delivered_kg(lot["id"]) for lot in lots]
    total_weight = sum(weights, D(0))
    intensities = [lot["ci_certified_gco2e_per_mj"] or D(0) for lot in lots]
    if total_weight > 0:
        weighted = sum((ci * w for ci, w in zip(intensities, weights)), D(0))
        pathway_ci = q2(weighted / total_weight)
    else:
        pathway_ci = q2(sum(intensities, D(0)) / D(len(lots)))

    gross = q3((CI_BENCHMARK_GCO2E_PER_MJ - pathway_ci / EER) * energy_mj / D(1000000))
    if gross < 0:
        gross = ZERO3
    if gross >= ADMIN_TIER_HIGH_MT:
        rate = ADMIN_RATE_HIGH
    elif gross >= ADMIN_TIER_MID_MT:
        rate = ADMIN_RATE_MID
    else:
        rate = ADMIN_RATE_LOW
    fee = q3(gross * rate)
    net = q3(gross - fee)
    return {
        "dispensed_kg": dispensed_kg,
        "energy_mj": energy_mj,
        "pathway_ci_gco2e_per_mj": pathway_ci,
        "gross_credits_mt": gross,
        "admin_fee_rate": rate,
        "admin_fee_mt": fee,
        "net_credits_mt": net,
    }


# --------------------------------------------------------------------------
# calculations.station_uptime_pct
# --------------------------------------------------------------------------
def _minutes(delta):
    return D(str(delta.total_seconds())) / D(60)


def uptime_figures(station, agreement, period_start, period_end, nozzle_snapshot):
    period_minutes = _minutes(period_end - period_start)
    clipped = []
    for event in events_of(station["id"]):
        if event["severity"] not in ("MAJOR", "CRITICAL"):
            continue
        if event["status"] != "CLEARED" or event["cleared_at"] is None:
            continue
        start = max(event["opened_at"], period_start)
        end = min(event["cleared_at"], period_end)
        if end <= start:
            continue
        clipped.append((start, end, event["affected_nozzle_count"]))

    downtime_nozzle = sum((_minutes(end - start) * D(nozzles)
                           for start, end, nozzles in clipped), D(0))
    downtime_nozzle_minutes = q3(downtime_nozzle)

    full = sorted([(s, e) for s, e, n in clipped if n == nozzle_snapshot])
    merged = []
    for start, end in full:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    full_outage = sum((_minutes(end - start) for start, end in merged), D(0))
    full_outage_minutes = q3(full_outage)

    denominator = period_minutes * D(nozzle_snapshot)
    if denominator == 0:
        uptime_nozzle = q3(D(100))
    else:
        uptime_nozzle = q3(D(100) - downtime_nozzle / denominator * D(100))
    if period_minutes == 0:
        uptime_station = q3(D(100))
    else:
        uptime_station = q3(D(100) - full_outage / period_minutes * D(100))

    uptime_pct = (uptime_nozzle if agreement["uptime_method"] == "NOZZLE_WEIGHTED"
                  else uptime_station)
    shortfall = agreement["min_uptime_pct"] - uptime_pct
    if shortfall < 0:
        shortfall = D(0)
    return {
        "downtime_nozzle_minutes": downtime_nozzle_minutes,
        "full_outage_minutes": full_outage_minutes,
        "uptime_pct_nozzle_weighted": uptime_nozzle,
        "uptime_pct_station_level": uptime_station,
        "uptime_pct": uptime_pct,
        "shortfall_points": q3(shortfall),
    }


# --------------------------------------------------------------------------
# calculations.funding_penalty
# --------------------------------------------------------------------------
def funding_penalty(report, agreement):
    holdback_before = holdback_balance_cents(agreement, exclude_report_id=report["id"])
    raw = q0(report["shortfall_points"] * D(agreement["penalty_per_point_cents"]))
    return raw if raw < holdback_before else holdback_before
