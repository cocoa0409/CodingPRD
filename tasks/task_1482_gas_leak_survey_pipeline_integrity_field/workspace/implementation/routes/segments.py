"""PipeSegment endpoints (PRD §3.1, §3.12)."""
from datetime import timedelta

from flask import request

from db import STORE, fmt_dt, make_entity, now, serialize, touch
from errors import bad_request, err
from middleware import (body, parse_bool_param, parse_pagination, req_bool,
                        req_enum, req_int, req_num, req_str, require_roles)
from response import list_response, success
from services import (FIELDS, OPEN_LEAK_STATUSES, compute_interval_days,
                      compute_risk_score, get_or_404, refresh_segment,
                      sorted_all)
from . import bp

MATERIALS = ["STEEL", "CAST_IRON", "PLASTIC_PE", "PLASTIC_PVC", "COPPER"]
PRESSURE_CLASSES = ["DISTRIBUTION", "TRANSMISSION", "SERVICE"]
READ_ROLES = ("IntegrityAnalyst", "ComplianceOfficer", "FieldTechnician",
              "DispatchCoordinator")


def ser(seg):
    return serialize(seg, FIELDS["pipe_segments"])


def _arg(name):
    return request.args.get(name)


@bp.post("/pipe-segments")
@require_roles("IntegrityAnalyst")
def create_segment():
    d = body()
    segment_code = req_str(d, "segment_code")
    install_year = req_int(d, "install_year")
    material = req_enum(d, "material", MATERIALS)
    diameter = req_num(d, "diameter_inches")
    length = req_num(d, "length_feet")
    pressure = req_num(d, "operating_pressure_psi")
    pclass = req_enum(d, "pressure_class", PRESSURE_CLASSES)
    hca = req_bool(d, "is_high_consequence_area")
    region_hint = d.get("region_hint")
    if region_hint is not None and not isinstance(region_hint, str):
        raise bad_request("region_hint must be a string or null")
    if install_year < 1900:
        raise bad_request("install_year must be >= 1900")
    if any(s["segment_code"] == segment_code
           for s in STORE["pipe_segments"].values()):
        raise bad_request("segment_code must be unique")
    seg = make_entity()
    seg.update({
        "segment_code": segment_code, "install_year": install_year,
        "material": material, "diameter_inches": diameter,
        "length_feet": length, "operating_pressure_psi": pressure,
        "pressure_class": pclass, "is_high_consequence_area": hca,
        "region_hint": region_hint, "open_grade1_count": 0,
        "open_grade2_count": 0, "open_grade3_count": 0, "posture": "NORMAL",
        "last_surveyed_at": None, "next_survey_due_at": None,
        "status": "ACTIVE",
    })
    seg["risk_score"] = compute_risk_score(seg)
    STORE["pipe_segments"][seg["id"]] = seg
    return success(ser(seg), code=201)


@bp.get("/pipe-segments")
@require_roles(*READ_ROLES)
def list_segments():
    limit, offset = parse_pagination()
    status = _arg("status")
    posture = _arg("posture")
    pclass = _arg("pressure_class")
    hca = parse_bool_param("is_high_consequence_area")
    items = sorted_all("pipe_segments")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if posture is not None:
        items = [s for s in items if s["posture"] == posture]
    if pclass is not None:
        items = [s for s in items if s["pressure_class"] == pclass]
    if hca is not None:
        items = [s for s in items if s["is_high_consequence_area"] == hca]
    return list_response(items, ser, limit, offset)


@bp.get("/pipe-segments/<sid>")
@require_roles(*READ_ROLES)
def get_segment(sid):
    return success(ser(get_or_404("pipe_segments", sid)))


@bp.get("/pipe-segments/<sid>/leaks")
@require_roles(*READ_ROLES)
def segment_leaks(sid):
    get_or_404("pipe_segments", sid)
    limit, offset = parse_pagination()
    status = _arg("status")
    grade = _arg("grade")
    items = [l for l in sorted_all("leaks") if l["segment_id"] == sid]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if grade is not None:
        items = [l for l in items if l["grade"] == grade]
    return list_response(items, lambda l: serialize(l, FIELDS["leaks"]),
                         limit, offset)


@bp.get("/pipe-segments/<sid>/cp-readings")
@require_roles("IntegrityAnalyst", "ComplianceOfficer", "FieldTechnician")
def segment_cp_readings(sid):
    get_or_404("pipe_segments", sid)
    limit, offset = parse_pagination()
    anomaly_status = _arg("anomaly_status")
    is_anomalous = parse_bool_param("is_anomalous")
    items = [r for r in sorted_all("cp_readings") if r["segment_id"] == sid]
    if anomaly_status is not None:
        items = [r for r in items if r["anomaly_status"] == anomaly_status]
    if is_anomalous is not None:
        items = [r for r in items if r["is_anomalous"] == is_anomalous]
    return list_response(items,
                         lambda r: serialize(r, FIELDS["cp_readings"]),
                         limit, offset)


@bp.get("/pipe-segments/<sid>/compliance-summary")
@require_roles("IntegrityAnalyst", "ComplianceOfficer")
def segment_compliance_summary(sid):
    seg = get_or_404("pipe_segments", sid)
    n = now()
    overdue = sum(1 for l in STORE["leaks"].values()
                  if l["segment_id"] == sid
                  and l["status"] in OPEN_LEAK_STATUSES
                  and n > l["repair_due_at"])
    return success({
        "overdue_leak_count": overdue,
        "posture": seg["posture"],
        "next_survey_due_at": fmt_dt(seg["next_survey_due_at"]),
        "open_grade1_count": seg["open_grade1_count"],
        "open_grade2_count": seg["open_grade2_count"],
        "open_grade3_count": seg["open_grade3_count"],
        "risk_score": seg.get("risk_score"),
    })


@bp.get("/pipe-segments/<sid>/next-survey-due")
@require_roles("IntegrityAnalyst")
def segment_next_survey_due(sid):
    seg = get_or_404("pipe_segments", sid)
    interval = compute_interval_days(seg)
    anchor = seg["last_surveyed_at"] if seg["last_surveyed_at"] is not None else now()
    due = anchor + timedelta(days=interval)
    return success({"next_survey_due_at": fmt_dt(due), "interval_days": interval})


@bp.post("/pipe-segments/<sid>/out-of-service")
@require_roles("IntegrityAnalyst")
def segment_out_of_service(sid):
    seg = get_or_404("pipe_segments", sid)
    if seg["status"] != "ACTIVE":
        raise err("ERR_SEGMENT_NOT_ACTIVE", "PipeSegment.status != ACTIVE", 409)
    open_orders = [o for o in STORE["repair_orders"].values()
                   if o["dispatch_status"] in ("DISPATCHED", "ON_SITE")
                   and STORE["leaks"].get(o["leak_id"]) is not None
                   and STORE["leaks"][o["leak_id"]]["segment_id"] == sid]
    if open_orders:
        raise err("ERR_OPEN_REPAIR_ORDERS_EXIST",
                  "RepairOrders in DISPATCHED/ON_SITE exist on this segment", 422)
    seg["status"] = "OUT_OF_SERVICE"
    touch(seg)
    for leak in [l for l in STORE["leaks"].values()
                 if l["segment_id"] == sid
                 and l["status"] in ("OPEN", "REPAIR_SCHEDULED")]:
        leak["status"] = "ABANDONED_SEGMENT"
        touch(leak)
        for order in [o for o in STORE["repair_orders"].values()
                      if o["leak_id"] == leak["id"]
                      and o["dispatch_status"] == "PENDING_DISPATCH"]:
            order["dispatch_status"] = "CANCELLED"
            touch(order)
    refresh_segment(seg)
    return success(ser(seg))


@bp.post("/pipe-segments/<sid>/return-to-service")
@require_roles("IntegrityAnalyst")
def segment_return_to_service(sid):
    seg = get_or_404("pipe_segments", sid)
    if seg["status"] != "OUT_OF_SERVICE":
        raise err("ERR_SEGMENT_NOT_OUT_OF_SERVICE",
                  "PipeSegment.status != OUT_OF_SERVICE", 409)
    n = now()
    cutoff = n - timedelta(days=90)
    clean = any(r["segment_id"] == sid and not r["is_anomalous"]
                and r["recorded_at"] >= cutoff
                for r in STORE["cp_readings"].values())
    if not clean:
        raise err("ERR_NO_RECENT_CLEAN_CP_READING",
                  "Return-to-service requires a clean CP reading in last 90 days",
                  422)
    seg["status"] = "ACTIVE"
    touch(seg)
    refresh_segment(seg)
    return success(ser(seg))


@bp.post("/pipe-segments/<sid>/abandon")
@require_roles("IntegrityAnalyst")
def segment_abandon(sid):
    seg = get_or_404("pipe_segments", sid)
    if seg["status"] != "OUT_OF_SERVICE":
        raise err("ERR_SEGMENT_NOT_OUT_OF_SERVICE",
                  "PipeSegment.status != OUT_OF_SERVICE", 409)
    seg["status"] = "ABANDONED"
    touch(seg)
    return success(ser(seg))
