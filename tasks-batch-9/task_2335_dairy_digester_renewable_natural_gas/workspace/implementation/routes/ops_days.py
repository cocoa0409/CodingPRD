from decimal import Decimal

from flask import Blueprint

import config
from db import db
from errors import fail
from middleware import endpoint, body
from numeric import D
from response import created, ok
from routes.common import get_facility, get_ops_day, paged_list, resolve_refs
from services import calc, cascade, derive
from validation import date_of

bp = Blueprint("ops_days", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "ProgramAdministrator",
              "CreditVerifier", "PipelineScheduler", "FinanceController"]

ZERO3 = Decimal("0.000")


def _blank_day(facility_id, ops_date):
    row = {
        "facility_id": facility_id,
        "ops_date": ops_date,
        "status": "OPEN",
        "gas_state": "NOT_PRODUCED",
        "organic_loading_rate": ZERO3,
        "separation_recorded": False,
        "conditioning_attempts": 0,
        "reopen_count": 0,
        "raw_biogas_scf": ZERO3,
        "raw_gas_mmbtu": ZERO3,
        "pipeline_gas_scf": ZERO3,
        "pipeline_gas_mmbtu": ZERO3,
        "digestate_solids_tonnes": ZERO3,
        "digestate_liquid_tonnes": ZERO3,
        "bedding_recovered_tonnes": ZERO3,
    }
    for field in ("avg_digester_temp_c", "temp_excursion_minutes", "vfa_mg_per_l",
                  "alkalinity_mg_per_l", "vfa_alkalinity_ratio", "thermal_status",
                  "stress_points", "stability_status", "raw_ch4_pct", "raw_co2_pct",
                  "raw_h2s_ppm", "raw_moisture_lb_per_mmscf", "raw_hhv_btu_per_scf",
                  "treated_ch4_pct", "treated_co2_pct", "treated_h2s_ppm",
                  "treated_moisture_lb_per_mmscf", "pipeline_hhv_btu_per_scf",
                  "offspec_reason", "solids_capture_pct", "bedding_recovery_pct",
                  "lab_total_nitrogen_mg_per_l"):
        row[field] = None
    return row


@bp.post("/ops-days")
@endpoint(["ProjectOperator"])
def create_ops_day():
    b = body()
    (facility,) = resolve_refs(b, (("facility_id", get_facility),))
    b.date("ops_date")
    ops_date = b.raw["ops_date"]
    for existing in db.ops_days.values():
        if existing["facility_id"] == facility["id"] and existing["ops_date"] == ops_date:
            fail("ERR_OPS_DAY_EXISTS",
                 "An operations day already exists for this facility and date.")
    row = db.new_row(_blank_day(facility["id"], ops_date))
    db.ops_days[row["id"]] = row
    return created(derive.ser_ops_day(row))


@bp.get("/ops-days")
@endpoint(READ_ROLES)
def list_ops_days():
    return paged_list(db.ops_days, derive.ser_ops_day,
                      ("facility_id", "status", "gas_state", "ops_date"))


@bp.get("/ops-days/<ops_day_id>")
@endpoint(READ_ROLES)
def read_ops_day(ops_day_id):
    return ok(derive.ser_ops_day(get_ops_day(ops_day_id)))


@bp.post("/ops-days/<ops_day_id>/close")
@endpoint(["ProjectOperator"])
def close_ops_day(ops_day_id):
    day = get_ops_day(ops_day_id)
    b = body()
    avg_temp = b.number("avg_digester_temp_c", 1)
    excursion = b.integer("temp_excursion_minutes", ge=0)
    vfa = b.number("vfa_mg_per_l", 1, ge=0)
    alkalinity = b.number("alkalinity_mg_per_l", 1, gt=0)
    raw_scf = b.number("raw_biogas_scf", 3, ge=0)
    raw_ch4 = b.number("raw_ch4_pct", 1, ge=0, le=100)
    raw_co2 = b.number("raw_co2_pct", 1, ge=0, le=100)
    raw_h2s = b.number("raw_h2s_ppm", 1, ge=0)
    raw_moisture = b.number("raw_moisture_lb_per_mmscf", 1, ge=0)

    facility = db.facilities[day["facility_id"]]
    if day["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN operations day may be closed.")
    if not derive.deliveries_of_day(day["id"]):
        fail("ERR_INVALID_STATE",
             "At least one ACCEPTED delivery is required before closing.")
    if facility["ops_posture"] == "UPSET":
        fail("ERR_FACILITY_UPSET", "The facility is in biological upset.")

    day["avg_digester_temp_c"] = avg_temp
    day["temp_excursion_minutes"] = excursion
    day["vfa_mg_per_l"] = vfa
    day["alkalinity_mg_per_l"] = alkalinity
    day["raw_biogas_scf"] = raw_scf
    day["raw_ch4_pct"] = raw_ch4
    day["raw_co2_pct"] = raw_co2
    day["raw_h2s_ppm"] = raw_h2s
    day["raw_moisture_lb_per_mmscf"] = raw_moisture

    derive.recompute_day_olr(day)
    thermal, ratio, points, stability = calc.biological_stability(
        avg_temp, excursion, vfa, alkalinity, day["organic_loading_rate"],
        facility["target_temperature_c"], facility["design_max_olr"])
    day["thermal_status"] = thermal
    day["vfa_alkalinity_ratio"] = ratio
    day["stress_points"] = points
    day["stability_status"] = stability

    day["status"] = "CLOSED"
    if raw_scf > 0:
        day["gas_state"] = "RAW"
        hhv, mmbtu = calc.raw_gas_derived(raw_scf, raw_ch4)
        day["raw_hhv_btu_per_scf"] = hhv
        day["raw_gas_mmbtu"] = mmbtu
    db.touch(day)
    db.touch(facility)

    posture = facility["ops_posture"]
    moved = False
    upset = False
    if stability == "STRESSED" and posture == "STABLE":
        facility["ops_posture"] = "WATCH"
        moved = True
    elif stability == "STABLE" and posture in ("WATCH", "RESTRICTED"):
        facility["ops_posture"] = "STABLE"
        if posture == "RESTRICTED":
            facility["posture_override_active"] = False
        moved = True
    elif stability == "INHIBITED" and posture in ("STABLE", "WATCH"):
        facility["ops_posture"] = "UPSET"
        moved = True
        upset = True
    if moved:
        db.touch(facility)
    if upset:
        cascade.cascade_biological_upset(facility)
    return ok(derive.ser_ops_day(day))


@bp.post("/ops-days/<ops_day_id>/reopen")
@endpoint(["ProjectOperator"])
def reopen_ops_day(ops_day_id):
    day = get_ops_day(ops_day_id)
    b = body()
    b.string("reason")
    facility = db.facilities[day["facility_id"]]

    if day["status"] != "CLOSED":
        fail("ERR_INVALID_STATE", "Only a CLOSED operations day may be reopened.")
    for nom in db.nominations.values():
        if nom["ops_day_id"] == day["id"] and nom["status"] in ("CONFIRMED", "DELIVERED"):
            fail("ERR_INVALID_STATE",
                 "A confirmed or delivered nomination draws on this day.")
    ops_date = date_of(day["ops_date"])
    for batch in db.batches.values():
        if batch["facility_id"] != facility["id"]:
            continue
        if batch["status"] not in ("CLAIMED", "VERIFIED", "ISSUED"):
            continue
        if date_of(batch["period_start_date"]) <= ops_date <= date_of(batch["period_end_date"]):
            fail("ERR_INVALID_STATE", "A claimed credit batch covers this operations date.")
    for app in db.applications.values():
        if app["ops_day_id"] == day["id"] and app["status"] == "APPLIED":
            fail("ERR_INVALID_STATE", "An applied nutrient application draws on this day.")
    if day["reopen_count"] >= config.MAX_REOPENS:
        fail("ERR_REOPEN_LIMIT_REACHED", "This operations day has already been reopened.")

    day["status"] = "OPEN"
    day["gas_state"] = "NOT_PRODUCED"
    for field in ("treated_ch4_pct", "treated_co2_pct", "treated_h2s_ppm",
                  "treated_moisture_lb_per_mmscf", "pipeline_hhv_btu_per_scf",
                  "offspec_reason"):
        day[field] = None
    day["pipeline_gas_scf"] = ZERO3
    day["pipeline_gas_mmbtu"] = ZERO3
    day["conditioning_attempts"] = 0
    day["separation_recorded"] = False
    day["digestate_solids_tonnes"] = ZERO3
    day["digestate_liquid_tonnes"] = ZERO3
    day["bedding_recovered_tonnes"] = ZERO3
    day["reopen_count"] += 1
    db.touch(day)
    db.touch(facility)
    return ok(derive.ser_ops_day(day))


@bp.post("/ops-days/<ops_day_id>/condition-gas")
@endpoint(["ProjectOperator"])
def condition_gas(ops_day_id):
    day = get_ops_day(ops_day_id)
    b = body()
    disposition = b.enum("disposition", ("RECONDITION", "FLARE"))
    treated_ch4 = treated_co2 = treated_h2s = treated_moisture = None
    if disposition == "RECONDITION":
        treated_ch4 = b.number("treated_ch4_pct", 1, gt=0, le=100)
        treated_co2 = b.number("treated_co2_pct", 1, ge=0, le=100)
        treated_h2s = b.number("treated_h2s_ppm", 1, ge=0)
        treated_moisture = b.number("treated_moisture_lb_per_mmscf", 1, ge=0)

    allowed = ("RAW", "PIPELINE_SPEC", "OFFSPEC") if disposition == "RECONDITION" \
        else ("OFFSPEC",)
    if day["gas_state"] not in allowed:
        fail("ERR_GAS_NOT_CONDITIONABLE",
             "The day's gas state does not permit this disposition.")

    if disposition == "FLARE":
        day["gas_state"] = "FLARED"
        day["pipeline_gas_scf"] = ZERO3
        day["pipeline_gas_mmbtu"] = ZERO3
        db.touch(day)
        return ok(derive.ser_ops_day(day))

    interconnect = derive.active_interconnect(day["facility_id"])
    if interconnect is None:
        fail("ERR_NO_ACTIVE_INTERCONNECT",
             "No ACTIVE interconnection agreement exists for the facility.")
    if day["conditioning_attempts"] >= config.MAX_CONDITIONING_ATTEMPTS:
        fail("ERR_CONDITIONING_ATTEMPTS_EXHAUSTED",
             "The conditioning attempt ceiling for this day is reached.")

    scf, hhv, offspec, mmbtu = calc.gas_conditioning_yield(
        day["raw_biogas_scf"], day["raw_ch4_pct"], treated_ch4, treated_co2,
        treated_h2s, treated_moisture, interconnect)

    was_pipeline_spec = day["gas_state"] == "PIPELINE_SPEC"
    day["treated_ch4_pct"] = treated_ch4
    day["treated_co2_pct"] = treated_co2
    day["treated_h2s_ppm"] = treated_h2s
    day["treated_moisture_lb_per_mmscf"] = treated_moisture
    day["pipeline_hhv_btu_per_scf"] = hhv
    day["offspec_reason"] = offspec
    day["conditioning_attempts"] += 1
    if offspec:
        day["gas_state"] = "OFFSPEC"
        day["pipeline_gas_scf"] = ZERO3
        day["pipeline_gas_mmbtu"] = ZERO3
    else:
        day["gas_state"] = "PIPELINE_SPEC"
        day["pipeline_gas_scf"] = scf
        day["pipeline_gas_mmbtu"] = mmbtu
    db.touch(day)

    if offspec and was_pipeline_spec:
        cascade.cascade_offspec_retest(day)
    return ok(derive.ser_ops_day(day))


@bp.post("/ops-days/<ops_day_id>/record-separation")
@endpoint(["ProjectOperator"])
def record_separation(ops_day_id):
    day = get_ops_day(ops_day_id)
    b = body()
    capture = b.number("solids_capture_pct", 1, ge=0, le=100)
    bedding_pct = b.number("bedding_recovery_pct", 1, ge=0, le=100)
    lab_n = b.number("lab_total_nitrogen_mg_per_l", 1, ge=0)

    if day["separation_recorded"]:
        fail("ERR_SEPARATION_ALREADY_RECORDED",
             "Separation has already been recorded for this operations day.")

    solids, liquid, bedding = calc.digestate_separation(
        derive.deliveries_of_day(day["id"]), capture, bedding_pct)
    day["solids_capture_pct"] = capture
    day["bedding_recovery_pct"] = bedding_pct
    day["lab_total_nitrogen_mg_per_l"] = lab_n
    day["digestate_solids_tonnes"] = solids
    day["digestate_liquid_tonnes"] = liquid
    day["bedding_recovered_tonnes"] = bedding
    day["separation_recorded"] = True
    db.touch(day)
    db.touch(db.facilities[day["facility_id"]])
    return ok(derive.ser_ops_day(day))
