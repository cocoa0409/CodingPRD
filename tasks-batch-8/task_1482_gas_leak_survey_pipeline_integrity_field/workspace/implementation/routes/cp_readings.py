"""CathodicProtectionReading endpoints (PRD §3.10)."""
from flask import request

from db import STORE, make_entity, now, serialize, touch
from middleware import (body, parse_bool_param, parse_pagination, req_num,
                        req_str, require_roles)
from errors import err
from response import list_response, success
from services import (CP_ANOMALY_THRESHOLD_MV, FIELDS, get_or_404,
                      refresh_segment, sorted_all, stale_current_snapshots)
from . import bp

CP_ROLES = ("IntegrityAnalyst", "ComplianceOfficer", "FieldTechnician")


def ser(reading):
    return serialize(reading, FIELDS["cp_readings"])


@bp.post("/cp-readings")
@require_roles("FieldTechnician")
def create_reading():
    d = body()
    segment_id = req_str(d, "segment_id")
    test_point_id = req_str(d, "test_point_id")
    psp = req_num(d, "pipe_to_soil_potential_mv")
    ioff = req_num(d, "instant_off_potential_mv")
    seg = get_or_404("pipe_segments", segment_id)
    anomalous = ioff > CP_ANOMALY_THRESHOLD_MV
    reading = make_entity()
    reading.update({
        "segment_id": segment_id, "test_point_id": test_point_id,
        "recorded_at": now(), "pipe_to_soil_potential_mv": psp,
        "instant_off_potential_mv": ioff, "is_anomalous": anomalous,
        "anomaly_status": "OPEN" if anomalous else "NONE",
    })
    STORE["cp_readings"][reading["id"]] = reading
    if anomalous:
        refresh_segment(seg, recompute_risk=True)
        stale_current_snapshots()
    return success(ser(reading), code=201)


@bp.get("/cp-readings")
@require_roles(*CP_ROLES)
def list_readings():
    limit, offset = parse_pagination()
    segment_id = request.args.get("segment_id")
    anomaly_status = request.args.get("anomaly_status")
    is_anomalous = parse_bool_param("is_anomalous")
    items = sorted_all("cp_readings")
    if segment_id is not None:
        items = [r for r in items if r["segment_id"] == segment_id]
    if anomaly_status is not None:
        items = [r for r in items if r["anomaly_status"] == anomaly_status]
    if is_anomalous is not None:
        items = [r for r in items if r["is_anomalous"] == is_anomalous]
    return list_response(items, ser, limit, offset)


@bp.get("/cp-readings/<rid>")
@require_roles(*CP_ROLES)
def get_reading(rid):
    return success(ser(get_or_404("cp_readings", rid)))


@bp.post("/cp-readings/<rid>/acknowledge")
@require_roles("IntegrityAnalyst")
def acknowledge_reading(rid):
    reading = get_or_404("cp_readings", rid)
    if reading["anomaly_status"] != "OPEN":
        raise err("ERR_ANOMALY_NOT_OPEN",
                  "CathodicProtectionReading.anomaly_status != OPEN", 409)
    reading["anomaly_status"] = "ACKNOWLEDGED"
    touch(reading)
    seg = STORE["pipe_segments"].get(reading["segment_id"])
    if seg is not None:
        refresh_segment(seg, recompute_risk=True)
    return success(ser(reading))


@bp.post("/cp-readings/<rid>/resolve")
@require_roles("IntegrityAnalyst")
def resolve_reading(rid):
    reading = get_or_404("cp_readings", rid)
    if reading["anomaly_status"] != "ACKNOWLEDGED":
        raise err("ERR_ANOMALY_NOT_ACKNOWLEDGED",
                  "CathodicProtectionReading.anomaly_status != ACKNOWLEDGED",
                  409)
    cleanup = any(r["segment_id"] == reading["segment_id"]
                  and not r["is_anomalous"]
                  and (r["recorded_at"], r["_seq"])
                      > (reading["recorded_at"], reading["_seq"])
                  for r in STORE["cp_readings"].values())
    if not cleanup:
        raise err("ERR_NO_CLEANUP_READING",
                  "No newer non-anomalous CP reading exists on this segment",
                  422)
    reading["anomaly_status"] = "RESOLVED"
    touch(reading)
    seg = STORE["pipe_segments"].get(reading["segment_id"])
    if seg is not None:
        refresh_segment(seg, recompute_risk=True)
    return success(ser(reading))
