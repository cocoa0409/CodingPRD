"""Pump calibrations and field samples (PRD section 3.4)."""

from flask import Blueprint, request

import db
from errors import (
    ERR_CALIBRATION_ALREADY_RECORDED,
    ERR_CALIBRATION_IN_USE,
    ERR_CALIBRATION_PUMP_MISMATCH,
    ERR_EMPLOYEE_NOT_SEG_MEMBER,
    ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_OPEN_FOR_SAMPLING,
    ERR_PUMP_DOUBLE_BOOKED,
    ERR_SAMPLE_INVALID_STATE,
    ERR_SAMPLE_OUTSIDE_PLAN_WINDOW,
    raise_error,
)
from helpers import (
    reject_unknown,
    body, forbidden_fields, get_or_404, list_response, req_date, req_int,
    req_number, req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from serializers import calibration_out, sample_out
from services import compute_drift, invalidate_sample, recompute_plan_counts

bp = Blueprint("field", __name__)

TECH = ("FieldTechnician",)
IH = ("IndustrialHygienist",)


# ---------------------------------------------------------------------------
# Pump calibrations
# ---------------------------------------------------------------------------

@bp.route("/ih/pump-calibrations", methods=["POST"])
def create_calibration():
    user_id, _ = require_auth(TECH)
    data = body()
    reject_unknown(data, {"pump_id", "pre_flow_lpm"})
    pump_id = req_string(data, "pump_id")
    pre_flow = req_number(data, "pre_flow_lpm")
    if pre_flow <= 0:
        raise_error(ERR_INVALID_REQUEST, "pre_flow_lpm must be > 0")
    get_or_404(db.pumps, pump_id, "Pump")
    cal = {
        "pump_id": pump_id,
        "pre_flow_lpm": pre_flow,
        "post_flow_lpm": None,
        "drift_pct": None,
        "result": "PENDING",
        "performed_by_user_id": user_id,
        "linked_sample_id": None,
    }
    stamp_new(cal)
    db.pump_calibrations[cal["id"]] = cal
    return success_object(calibration_out(cal), 201)


@bp.route("/ih/pump-calibrations", methods=["GET"])
def list_calibrations():
    require_auth(ALL_ROLES)
    return list_response(list(db.pump_calibrations.values()), calibration_out,
                         {"pump_id": request.args.get("pump_id")})


@bp.route("/ih/pump-calibrations/<cid>", methods=["GET"])
def get_calibration(cid):
    require_auth(ALL_ROLES)
    return success_object(calibration_out(get_or_404(db.pump_calibrations, cid, "PumpCalibration")))


@bp.route("/ih/pump-calibrations/<cid>/record-post", methods=["POST"])
def record_post(cid):
    require_auth(TECH)
    data = body()
    reject_unknown(data, {"post_flow_lpm"})
    post_flow = req_number(data, "post_flow_lpm")
    cal = get_or_404(db.pump_calibrations, cid, "PumpCalibration")
    if cal["result"] != "PENDING":
        raise_error(ERR_CALIBRATION_ALREADY_RECORDED,
                    "post-flow already recorded for this calibration")
    drift, verdict = compute_drift(cal["pre_flow_lpm"], post_flow)
    cal["post_flow_lpm"] = post_flow
    cal["drift_pct"] = drift
    cal["result"] = verdict
    # INVALID verdict cascades: the linked live sample is invalidated with
    # reason PUMP_DRIFT (which also releases the calibration link and may
    # regress the plan). invalidate_sample touches the calibration once,
    # committing this row's mutation and the link release in a single bump.
    linked = db.field_samples.get(cal["linked_sample_id"]) if cal["linked_sample_id"] else None
    if verdict == "INVALID" and linked is not None and linked["status"] in ("COLLECTED", "SEALED"):
        invalidate_sample(linked, "PUMP_DRIFT")
    else:
        touch(cal)
    return success_object(calibration_out(cal), 200)


# ---------------------------------------------------------------------------
# Field samples
# ---------------------------------------------------------------------------

@bp.route("/ih/field-samples", methods=["POST"])
def create_sample():
    user_id, _ = require_auth(TECH)
    data = body()
    reject_unknown(data, {"sampling_plan_id", "sample_type", "employee_id", "pump_id", "pre_calibration_id", "collection_date", "start_minute", "duration_minutes"})
    # ---- Stage 3: schema and conditional-required rules.
    sampling_plan_id = req_string(data, "sampling_plan_id")
    sample_type = req_string(data, "sample_type")
    if sample_type not in ("PERSONAL", "FIELD_BLANK"):
        raise_error(ERR_INVALID_REQUEST, "sample_type must be PERSONAL or FIELD_BLANK")
    if sample_type == "PERSONAL":
        employee_id = req_string(data, "employee_id")
        pump_id = req_string(data, "pump_id")
        pre_calibration_id = req_string(data, "pre_calibration_id")
    else:
        forbidden_fields(data, ("employee_id", "pump_id", "pre_calibration_id"),
                         "on a FIELD_BLANK sample")
        employee_id = None
        pump_id = None
        pre_calibration_id = None
    collection_date = req_date(data, "collection_date")
    start_minute = req_int(data, "start_minute")
    if start_minute < 0 or start_minute > 1439:
        raise_error(ERR_INVALID_REQUEST, "start_minute must be in 0..1439")
    duration_minutes = req_int(data, "duration_minutes")
    if duration_minutes < 1 or duration_minutes > 960:
        raise_error(ERR_INVALID_REQUEST, "duration_minutes must be in 1..960")
    # ---- Stage 4: existence, body FKs in declared input order.
    plan = get_or_404(db.sampling_plans, sampling_plan_id, "SamplingPlan")
    employee = pump = cal = None
    if sample_type == "PERSONAL":
        employee = get_or_404(db.employees, employee_id, "Employee")
        pump = get_or_404(db.pumps, pump_id, "Pump")
        cal = get_or_404(db.pump_calibrations, pre_calibration_id, "PumpCalibration")
    # ---- Stage 6: plan must be APPROVED.
    if plan["status"] != "APPROVED":
        raise_error(ERR_PLAN_NOT_OPEN_FOR_SAMPLING,
                    "Field sample creation requires plan status APPROVED")
    # ---- Stage 7: cross-entity referential coherence (PERSONAL only).
    if sample_type == "PERSONAL":
        member = any(m["seg_id"] == plan["seg_id"] and m["employee_id"] == employee["id"]
                     for m in db.seg_memberships.values())
        if not member:
            raise_error(ERR_EMPLOYEE_NOT_SEG_MEMBER,
                        "Sampled employee holds no SEGMembership in the plan's SEG")
        if cal["pump_id"] != pump["id"]:
            raise_error(ERR_CALIBRATION_PUMP_MISMATCH,
                        "Calibration's pump differs from the sample's pump")
    # ---- Stage 9: collection window, inclusive at both ends.
    from datetime import date as _date
    if not (_date.fromisoformat(plan["planned_start_date"]) <= collection_date
            <= _date.fromisoformat(plan["planned_end_date"])):
        raise_error(ERR_SAMPLE_OUTSIDE_PLAN_WINDOW,
                    "collection_date outside the plan window")
    # ---- Stage 10: pump double-booking, then calibration reuse.
    if sample_type == "PERSONAL":
        new_start = start_minute
        new_end = start_minute + duration_minutes
        for other in db.field_samples.values():
            if (other["pump_id"] != pump["id"] or other["status"] == "INVALIDATED"
                    or other["collection_date"] != collection_date.isoformat()):
                continue
            other_start = other["start_minute"]
            other_end = other_start + other["duration_minutes"]
            # Half-open intervals [start, start+duration); touching is allowed.
            if new_start < other_end and other_start < new_end:
                raise_error(ERR_PUMP_DOUBLE_BOOKED,
                            "Pump already booked for an overlapping interval on that date")
        linked = db.field_samples.get(cal["linked_sample_id"]) if cal["linked_sample_id"] else None
        if linked is not None and linked["status"] != "INVALIDATED":
            raise_error(ERR_CALIBRATION_IN_USE,
                        "Calibration already linked to another non-INVALIDATED sample")
    sample = {
        "sampling_plan_id": sampling_plan_id,
        "sample_type": sample_type,
        "employee_id": employee_id,
        "pump_id": pump_id,
        "pre_calibration_id": pre_calibration_id,
        "collection_date": collection_date.isoformat(),
        "start_minute": start_minute,
        "duration_minutes": duration_minutes,
        "collected_by_user_id": user_id,
        "status": "COLLECTED",
        "invalidate_reason": None,
        "air_volume_liters": None,
        "concentration_mg_m3": None,
        "sample_twa_mg_m3": None,
        "is_detect": None,
    }
    stamp_new(sample)
    db.field_samples[sample["id"]] = sample
    if sample_type == "PERSONAL":
        cal["linked_sample_id"] = sample["id"]
        touch(cal)
        # Counter recompute alone does not advance the plan's version (2.10).
        recompute_plan_counts(plan)
    return success_object(sample_out(sample), 201)


@bp.route("/ih/field-samples", methods=["GET"])
def list_samples():
    require_auth(ALL_ROLES)
    return list_response(list(db.field_samples.values()), sample_out, {
        "sampling_plan_id": request.args.get("sampling_plan_id"),
        "employee_id": request.args.get("employee_id"),
        "pump_id": request.args.get("pump_id"),
        "pre_calibration_id": request.args.get("pre_calibration_id"),
    })


@bp.route("/ih/field-samples/<sid>", methods=["GET"])
def get_sample(sid):
    require_auth(ALL_ROLES)
    return success_object(sample_out(get_or_404(db.field_samples, sid, "FieldSample")))


@bp.route("/ih/field-samples/<sid>/seal", methods=["POST"])
def seal_sample(sid):
    require_auth(TECH)
    sample = get_or_404(db.field_samples, sid, "FieldSample")
    if sample["status"] != "COLLECTED":
        raise_error(ERR_SAMPLE_INVALID_STATE, "seal requires COLLECTED")
    sample["status"] = "SEALED"
    touch(sample)
    return success_object(sample_out(sample), 200)


@bp.route("/ih/field-samples/<sid>/invalidate", methods=["POST"])
def invalidate_sample_endpoint(sid):
    require_auth(IH)
    data = body()
    reject_unknown(data, {"reason"})
    sample = get_or_404(db.field_samples, sid, "FieldSample")
    if sample["status"] not in ("COLLECTED", "SEALED"):
        raise_error(ERR_SAMPLE_INVALID_STATE,
                    "manual invalidate requires COLLECTED or SEALED")
    invalidate_sample(sample, "MANUAL")
    return success_object(sample_out(sample), 200)
