"""Instrument and Calibration endpoints (PRD §2.6, §3.2)."""
from datetime import timedelta

from flask import g, request

from db import STORE, make_entity, now, serialize, touch
from errors import bad_request, err, invalid_state
from middleware import (body, parse_pagination, req_enum, req_num, req_str,
                        require_roles)
from response import list_response, success
from services import (CAL_INTERVAL_DAYS, FIELDS, MAX_DRIFT_PCT, get_or_404,
                      sorted_all)
from . import bp

INSTRUMENT_TYPES = ["FLAME_IONIZATION", "CGI", "OMD", "AERIAL_LIDAR",
                    "CP_VOLTMETER"]


def ser(inst):
    return serialize(inst, FIELDS["instruments"])


def ser_cal(cal):
    return serialize(cal, FIELDS["calibrations"])


@bp.post("/instruments")
@require_roles("CalibrationTech")
def create_instrument():
    d = body()
    serial = req_str(d, "serial_number")
    itype = req_enum(d, "instrument_type", INSTRUMENT_TYPES)
    if any(i["serial_number"] == serial for i in STORE["instruments"].values()):
        raise bad_request("serial_number must be unique")
    inst = make_entity()
    inst.update({
        "serial_number": serial, "instrument_type": itype,
        "calibrated_at": None, "calibration_due_at": None,
        "status": "IN_SERVICE",
    })
    STORE["instruments"][inst["id"]] = inst
    return success(ser(inst), code=201)


@bp.get("/instruments")
@require_roles("CalibrationTech", "FieldTechnician", "IntegrityAnalyst")
def list_instruments():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    itype = request.args.get("instrument_type")
    items = sorted_all("instruments")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if itype is not None:
        items = [i for i in items if i["instrument_type"] == itype]
    return list_response(items, ser, limit, offset)


@bp.get("/instruments/<iid>")
@require_roles("CalibrationTech", "FieldTechnician", "IntegrityAnalyst")
def get_instrument(iid):
    return success(ser(get_or_404("instruments", iid)))


@bp.get("/instruments/<iid>/calibrations")
@require_roles("CalibrationTech", "IntegrityAnalyst")
def list_calibrations(iid):
    get_or_404("instruments", iid)
    limit, offset = parse_pagination()
    items = [c for c in sorted_all("calibrations") if c["instrument_id"] == iid]
    return list_response(items, ser_cal, limit, offset)


@bp.post("/instruments/<iid>/calibrate")
@require_roles("CalibrationTech")
def calibrate_instrument(iid):
    inst = get_or_404("instruments", iid)
    d = body()
    ref = req_num(d, "reference_gas_ppm")
    obs = req_num(d, "observed_ppm")
    if inst["status"] == "RETIRED":
        raise invalid_state("Instrument is RETIRED")
    if ref <= 0:
        raise bad_request("reference_gas_ppm must be > 0")
    drift = abs(obs - ref) / ref * 100.0
    if drift > MAX_DRIFT_PCT:
        raise err("ERR_CALIBRATION_DRIFT_EXCEEDED",
                  "Calibration drift_pct exceeds MAX_DRIFT_PCT (5.0)", 422)
    cal = make_entity()
    cal.update({
        "instrument_id": inst["id"], "performed_by_user_id": g.user_id,
        "reference_gas_ppm": ref, "observed_ppm": obs, "drift_pct": drift,
        "outcome": "PASS",
    })
    STORE["calibrations"][cal["id"]] = cal
    n = now()
    inst["calibrated_at"] = n
    inst["calibration_due_at"] = n + timedelta(
        days=CAL_INTERVAL_DAYS[inst["instrument_type"]])
    inst["status"] = "IN_SERVICE"
    touch(inst)
    return success(ser_cal(cal), code=201)


@bp.post("/instruments/<iid>/retire")
@require_roles("CalibrationTech")
def retire_instrument(iid):
    inst = get_or_404("instruments", iid)
    if inst["status"] != "IN_SERVICE":
        raise invalid_state("Instrument is not IN_SERVICE")
    in_use = any(r["instrument_id"] == iid and r["status"] in ("DRAFT", "SUBMITTED")
                 for r in STORE["survey_runs"].values())
    if in_use:
        raise err("ERR_INSTRUMENT_IN_USE",
                  "Instrument referenced by an active SurveyRun", 422)
    inst["status"] = "RETIRED"
    touch(inst)
    return success(ser(inst))
