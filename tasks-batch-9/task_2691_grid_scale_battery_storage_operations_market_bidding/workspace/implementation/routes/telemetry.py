"""Telemetry samples (PRD 3.5) — append-only, and the thermal cascade."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from numeric import D
from services import calc, core

bp = Blueprint("telemetry", __name__)


@bp.post("/telemetry-samples")
def append_sample():
    user_id, role = middleware.authorize("SiteController")
    body = v.json_body()

    dispatch_id = v.ident(body, "dispatch_id")
    sample_index = v.integer(body, "sample_index", ge=1)
    sampled_raw, sampled_at = v.timestamp(body, "sampled_at")
    measured_mw = v.num(body, "measured_mw", ge=0)
    measured_mvar = v.num(body, "measured_mvar", allow_negative=True)
    soc_reading = v.num(body, "soc_mwh_reading", ge=0)
    max_cell_temp = v.num(body, "max_cell_temp_c")

    instruction = core.get_dispatch(dispatch_id)
    middleware.check_asset_ownership(user_id, role, instruction["asset_id"])
    asset = core.get_asset(instruction["asset_id"])

    if instruction["execution_status"] not in ("EXECUTING", "COMPLETED"):
        raise ApiError(errors.ERR_DISPATCH_NOT_EXECUTING, 409,
                       "The instruction is not accepting telemetry.")

    # validation 16 — the interconnection active-power and apparent-power limits
    apparent = calc.sample_apparent_mva(measured_mw, measured_mvar)
    if (D(measured_mw) > D(asset["poi_mw_limit"])
            or D(apparent) > D(asset["poi_mva_limit"])):
        raise ApiError(errors.ERR_POI_LIMIT_EXCEEDED, 422,
                       "The sample breaches the interconnection limit.")

    # validation 17 — the reactive-power support obligation
    magnitude = D(measured_mvar)
    if magnitude < 0:
        magnitude = -magnitude
    if magnitude > D(asset["reactive_capability_mvar"]):
        raise ApiError(errors.ERR_REACTIVE_LIMIT_EXCEEDED, 422,
                       "The sample breaches the reactive-power capability.")

    # validation 24 — telemetry arrives in order
    existing = core.samples_of(dispatch_id)
    setpoint_start = db.parse_dt(instruction["setpoint_start"])
    if sampled_at < setpoint_start:
        raise ApiError(errors.ERR_TELEMETRY_OUT_OF_ORDER, 409,
                       "The sample predates the instruction's setpoint window.")
    if existing:
        newest = max(existing, key=lambda s: db.parse_dt(s["sampled_at"]))
        if sampled_at <= db.parse_dt(newest["sampled_at"]):
            raise ApiError(errors.ERR_TELEMETRY_OUT_OF_ORDER, 409,
                           "sampled_at must be strictly later than the newest "
                           "existing sample.")
        highest_index = max(s["sample_index"] for s in existing)
        if sample_index <= highest_index:
            raise ApiError(errors.ERR_TELEMETRY_OUT_OF_ORDER, 409,
                           "sample_index must be strictly greater than the "
                           "current maximum.")

    deviation = calc.sample_deviation(measured_mw, instruction["instructed_mw"])
    error_ratio = calc.sample_error_ratio(deviation, instruction["instructed_mw"])
    band = calc.thermal_band(max_cell_temp)

    sample = db.new_row(versioned=False)
    sample.update({
        "dispatch_id": dispatch_id,
        "sample_index": sample_index,
        "sampled_at": sampled_raw,
        "measured_mw": measured_mw,
        "measured_mvar": measured_mvar,
        "soc_mwh_reading": soc_reading,
        "max_cell_temp_c": max_cell_temp,
        "apparent_mva": apparent,
        "deviation_mw": deviation,
        "error_ratio": error_ratio,
        "within_deadband": D(error_ratio) <= calc.DEADBAND_RATIO,
        "thermal_escalation": band,
    })
    db.telemetry[sample["id"]] = sample

    instruction["telemetry_sample_count"] = instruction["telemetry_sample_count"] + 1
    db.touch(instruction)

    # the thermal cascade — exactly one event per sample, runaway outranking
    if band == "RUNAWAY":
        core.open_safety_event(asset, "THERMAL_RUNAWAY", "CRITICAL", max_cell_temp,
                               "TELEMETRY_AUTO", middleware.SYSTEM_ACTOR,
                               source_dispatch_id=dispatch_id,
                               source_sample_index=sample_index)
    elif band == "WARNING":
        core.open_safety_event(asset, "THERMAL_ANOMALY", "WARNING", max_cell_temp,
                               "TELEMETRY_AUTO", middleware.SYSTEM_ACTOR,
                               source_dispatch_id=dispatch_id,
                               source_sample_index=sample_index)

    return response.created(db.serialize(sample))


@bp.get("/dispatch-instructions/<dispatch_id>/telemetry-samples")
def list_samples(dispatch_id):
    middleware.any_role()
    limit, offset = v.pagination()
    instruction = core.get_dispatch(dispatch_id)

    rows = core.samples_of(instruction["id"])
    rows.sort(key=lambda s: (db.parse_dt(s["sampled_at"]), s["_seq"]))
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)
