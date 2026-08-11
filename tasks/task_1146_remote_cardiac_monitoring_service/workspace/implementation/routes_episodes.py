"""Episodes, suspension intervals, transmissions."""
import db
from bp import bp
from clock import now
from db import base_record, touch
from errors import ApiError
from helpers import (READ_ROLES, ROLES, auth, body, pagination, req_enum,
                     req_int, require, sorted_by_creation)
from response import serialize, success, success_list

COMPLETE_REASONS = {"COMPLETED", "TERMINATED_EARLY"}


def _get_episode_or_404(episode_id):
    ep = db.episodes.get(episode_id)
    if ep is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND", 404, "Episode not found")
    return ep


def _open_event_count(episode_id):
    return sum(1 for ev in db.compliance_events.values()
               if ev["episode_id"] == episode_id and ev["status"] == "OPEN")


@bp.get("/v1/episodes")
def list_episodes():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    enr_f = request.args.get("enrollment_id")
    pat_f = request.args.get("patient_id")
    clin_f = request.args.get("clinical_status")
    comp_f = request.args.get("compliance_status")
    items = list(db.episodes.values())
    if enr_f is not None:
        items = [x for x in items if x["enrollment_id"] == enr_f]
    if pat_f is not None:
        items = [x for x in items if x["patient_id"] == pat_f]
    if clin_f is not None:
        items = [x for x in items if x["clinical_status"] == clin_f]
    if comp_f is not None:
        items = [x for x in items if x["compliance_status"] == comp_f]
    return success_list(sorted_by_creation(items), limit, offset)


@bp.get("/v1/episodes/<episode_id>")
def get_episode(episode_id):
    uid, role = auth()
    require(role, READ_ROLES)
    return success(serialize(_get_episode_or_404(episode_id)))


@bp.post("/v1/episodes/<episode_id>/complete")
def complete_episode(episode_id):
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    ep = _get_episode_or_404(episode_id)
    d = body()
    reason = req_enum(d, "reason", COMPLETE_REASONS)
    if ep["clinical_status"] != "MONITORING":
        raise ApiError("ERR_INVALID_STATE", 409, "Episode is already terminal")
    if _open_event_count(ep["id"]) > 0:
        raise ApiError("ERR_OPEN_COMPLIANCE_EVENTS", 422,
                       "Episode has OPEN compliance events")
    ep["clinical_status"] = reason
    ep["completed_at"] = now()
    touch(ep)
    enr = db.enrollments.get(ep["enrollment_id"])
    if enr is not None:
        order = db.orders.get(enr["order_id"])
        if order is not None and order["status"] == "IN_SERVICE":
            order["status"] = "FULFILLED"
            touch(order)
    return success(serialize(ep))


@bp.post("/v1/episodes/<episode_id>/resume")
def resume_episode(episode_id):
    uid, role = auth()
    require(role, {"EnrollmentCoordinator"})
    ep = _get_episode_or_404(episode_id)
    if ep["compliance_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Episode is not SUSPENDED")
    if _open_event_count(ep["id"]) > 0:
        raise ApiError("ERR_OPEN_COMPLIANCE_EVENTS", 422,
                       "Episode has OPEN compliance events")
    t = now()
    for iv in db.suspension_intervals.values():
        if iv["episode_id"] == ep["id"] and iv["ended_at"] is None:
            iv["ended_at"] = t
            touch(iv)
    ep["compliance_status"] = "COMPLIANT"
    ep["strike_count"] = 0
    touch(ep)
    return success(serialize(ep))


@bp.get("/v1/episodes/<episode_id>/suspension-intervals")
def list_suspension_intervals(episode_id):
    uid, role = auth()
    require(role, READ_ROLES)
    _get_episode_or_404(episode_id)
    limit, offset = pagination()
    items = [x for x in db.suspension_intervals.values()
             if x["episode_id"] == episode_id]
    return success_list(sorted_by_creation(items), limit, offset)


# --------------------------------------------------------------- transmissions
@bp.post("/v1/episodes/<episode_id>/transmissions")
def ingest_transmission(episode_id):
    uid, role = auth()
    require(role, {"DeviceGateway"})
    ep = _get_episode_or_404(episode_id)
    d = body()
    seq_no = req_int(d, "seq_no")
    bytes_received = req_int(d, "bytes_received", lo=1)
    signal_quality = req_int(d, "signal_quality", lo=0, hi=100)
    if ep["clinical_status"] != "MONITORING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Episode is not in MONITORING clinical status")
    if any(tr for tr in db.transmissions.values()
           if tr["episode_id"] == ep["id"] and tr["seq_no"] == seq_no):
        raise ApiError("ERR_DUPLICATE_TRANSMISSION_SEQ", 409,
                       "seq_no already used within the episode")
    rec = base_record()
    status = "PROCESSED" if signal_quality >= 30 else "FAILED"
    rec.update({
        "episode_id": ep["id"],
        "seq_no": seq_no,
        "bytes_received": bytes_received,
        "signal_quality": signal_quality,
        "received_at": now(),
        "status": status,
    })
    db.transmissions[rec["id"]] = rec
    if status == "PROCESSED":
        ep["transmission_count"] += 1
        touch(ep)
    return success(serialize(rec), 201)


@bp.get("/v1/episodes/<episode_id>/transmissions")
def list_transmissions(episode_id):
    uid, role = auth()
    require(role, ROLES)  # every role including DeviceGateway
    _get_episode_or_404(episode_id)
    limit, offset = pagination()
    from flask import request
    status_f = request.args.get("status")
    items = [x for x in db.transmissions.values() if x["episode_id"] == episode_id]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    return success_list(sorted_by_creation(items), limit, offset)


@bp.post("/v1/transmissions/<transmission_id>/reprocess")
def reprocess_transmission(transmission_id):
    uid, role = auth()
    require(role, {"MonitoringTechnician"})
    rec = db.transmissions.get(transmission_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Transmission not found")
    d = body()
    signal_quality = req_int(d, "signal_quality", lo=0, hi=100)
    if rec["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only FAILED transmissions can be reprocessed")
    if signal_quality >= 30:
        rec["status"] = "PROCESSED"
        rec["signal_quality"] = signal_quality
        touch(rec)
        ep = db.episodes.get(rec["episode_id"])
        if ep is not None:
            ep["transmission_count"] += 1
            touch(ep)
    return success(serialize(rec))
