"""TrackSegments, TrackInspections, Incidents (PRD 3.6, 3.8)."""

from flask import Blueprint, request

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INSPECTION_OVERLAP,
                    ERR_FRA_REPORT_REQUIRED, ERR_INCIDENT_NOT_REPORTABLE,
                    not_found, invalid_state)
from util import (json_body, req_str, opt_str, req_int, opt_int, req_dt,
                  req_enum, opt_enum, req_num, parse_date, paginate)
from domain import (new_record, touch, segment_view, inspection_view,
                    incident_view, recompute_segment_speed, restrict_segment,
                    segment_is_overdue, FRA_CLASSES, DEFECT_SEVERITIES,
                    INCIDENT_TYPES, FRA_DAMAGE_THRESHOLD_CENTS)

bp = Blueprint("track", __name__)


# ---------------------------------------------------------------------------
# Track segments
# ---------------------------------------------------------------------------

@bp.post("/rail/track-segments")
def create_segment():
    uid, role = authenticate()
    body = json_body(required=True)
    name = req_str(body, "name")
    mp_start = req_num(body, "milepost_start")
    mp_end = req_num(body, "milepost_end")
    if not (mp_end > mp_start):
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "milepost_end must be strictly greater than milepost_start")
    fra_class = req_enum(body, "fra_class", FRA_CLASSES)
    require_role(role, ["SystemAdmin"])
    rec = new_record({
        "name": name,
        "milepost_start": mp_start,
        "milepost_end": mp_end,
        "fra_class": fra_class,
        "effective_speed_mph": 0,
        "defect_open": False,
        "open_defect_severity": None,
        "is_overdue": False,
        "status": "IN_SERVICE",
        "last_inspection_at": store.now,
    })
    recompute_segment_speed(rec)
    store.track_segments[rec["id"]] = rec
    return success_object(segment_view(rec), status=201)


@bp.get("/rail/track-segments")
def list_segments():
    uid, role = authenticate()
    records = list(store.track_segments.values())
    f_class = request.args.get("fra_class")
    f_status = request.args.get("status")
    if f_class is not None:
        records = [s for s in records if s["fra_class"] == f_class]
    if f_status is not None:
        records = [s for s in records if s["status"] == f_status]
    limit, offset, total, page = paginate(records)
    return success_list([segment_view(s) for s in page], limit, offset, total)


def _get_segment(sid):
    rec = store.track_segments.get(sid)
    if rec is None:
        raise not_found("track segment not found")
    return rec


@bp.get("/rail/track-segments/<sid>")
def get_segment(sid):
    uid, role = authenticate()
    return success_object(segment_view(_get_segment(sid)))


@bp.post("/rail/track-segments/<sid>/change-class")
def change_segment_class(sid):
    uid, role = authenticate()
    body = json_body(required=True)
    new_class = req_enum(body, "new_fra_class", FRA_CLASSES)
    require_role(role, ["SystemAdmin"])
    seg = _get_segment(sid)
    seg["fra_class"] = new_class
    recompute_segment_speed(seg)
    touch(seg)
    return success_object(segment_view(seg))


# ---------------------------------------------------------------------------
# Track inspections
# ---------------------------------------------------------------------------

@bp.post("/rail/track-inspections")
def create_inspection():
    uid, role = authenticate()
    body = json_body(required=True)
    segment_id = req_str(body, "segment_id")
    scheduled_raw = req_str(body, "scheduled_date")
    scheduled = parse_date(scheduled_raw, "scheduled_date")
    require_role(role, ["TrackInspector"])
    if segment_id not in store.track_segments:
        raise not_found("track segment not found")
    # Closed day interval on the same segment requires at least one full day of
    # gap: |new_date - existing_date| < 2 days is rejected.
    for insp in store.track_inspections.values():
        if insp["segment_id"] != segment_id:
            continue
        existing = parse_date(insp["scheduled_date"], "scheduled_date")
        if abs((scheduled - existing).days) < 2:
            raise ApiError(409, ERR_INSPECTION_OVERLAP,
                           "inspection day within one full day of an existing inspection")
    rec = new_record({
        "segment_id": segment_id,
        "scheduled_date": scheduled_raw,
        "status": "SCHEDULED",
        "defect_found": None,
        "defect_severity": None,
        "findings": None,
        "filed_at": None,
    })
    store.track_inspections[rec["id"]] = rec
    return success_object(inspection_view(rec), status=201)


@bp.get("/rail/track-inspections")
def list_inspections():
    uid, role = authenticate()
    records = list(store.track_inspections.values())
    f_segment = request.args.get("segment_id")
    f_status = request.args.get("status")
    if f_segment is not None:
        records = [i for i in records if i["segment_id"] == f_segment]
    if f_status is not None:
        records = [i for i in records if i["status"] == f_status]
    limit, offset, total, page = paginate(records)
    return success_list([inspection_view(i) for i in page], limit, offset, total)


def _get_inspection(iid):
    rec = store.track_inspections.get(iid)
    if rec is None:
        raise not_found("track inspection not found")
    return rec


@bp.get("/rail/track-inspections/<iid>")
def get_inspection(iid):
    uid, role = authenticate()
    return success_object(inspection_view(_get_inspection(iid)))


@bp.post("/rail/track-inspections/<iid>/file")
def file_inspection(iid):
    uid, role = authenticate()
    body = json_body(required=True)
    defect_found = body.get("defect_found")
    if not isinstance(defect_found, bool):
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "defect_found is required and must be a boolean")
    defect_severity = opt_enum(body, "defect_severity", DEFECT_SEVERITIES)
    findings = opt_str(body, "findings")
    if defect_found and defect_severity is None:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "defect_severity is required when defect_found is true")
    require_role(role, ["TrackInspector"])
    insp = _get_inspection(iid)
    if insp["status"] != "SCHEDULED":
        raise invalid_state("only a SCHEDULED inspection can be filed")
    seg = store.track_segments[insp["segment_id"]]
    now = store.now
    insp["filed_at"] = now
    insp["defect_found"] = defect_found
    insp["findings"] = findings
    # Filing always refreshes the segment's inspection timestamp and clears overdue.
    seg["last_inspection_at"] = now
    seg["is_overdue"] = False
    if defect_found:
        insp["defect_severity"] = defect_severity
        insp["status"] = "DEFECT_FILED"
        seg["defect_open"] = True
        seg["open_defect_severity"] = defect_severity
        recompute_segment_speed(seg)
        if defect_severity == "CRITICAL":
            restrict_segment(seg)  # movement cascade when IN_SERVICE -> RESTRICTED
    else:
        insp["status"] = "FILED"
        # A fresh filing with no open defect returns an overdue-restricted
        # segment to service.
        if (not seg["defect_open"] and seg["status"] == "RESTRICTED"
                and not segment_is_overdue(seg, now)):
            seg["status"] = "IN_SERVICE"
    touch(seg)
    touch(insp)
    return success_object(inspection_view(insp))


def _close_defect(iid, new_status):
    insp = _get_inspection(iid)
    if insp["status"] != "DEFECT_FILED":
        raise invalid_state("only a DEFECT_FILED inspection can be %s" % new_status.lower())
    seg = store.track_segments[insp["segment_id"]]
    seg["defect_open"] = False
    seg["open_defect_severity"] = None
    recompute_segment_speed(seg)
    if seg["status"] == "RESTRICTED" and not segment_is_overdue(seg, store.now):
        seg["status"] = "IN_SERVICE"
    touch(seg)
    insp["status"] = new_status
    touch(insp)
    return insp


@bp.post("/rail/track-inspections/<iid>/remediate")
def remediate_inspection(iid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["TrackInspector"])
    insp = _close_defect(iid, "REMEDIATED")
    return success_object(inspection_view(insp))


@bp.post("/rail/track-inspections/<iid>/waive")
def waive_inspection(iid):
    uid, role = authenticate()
    body = json_body()
    opt_str(body, "justification")
    require_role(role, ["RegulatorOfficer"])
    insp = _close_defect(iid, "WAIVED")
    return success_object(inspection_view(insp))


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@bp.post("/rail/incidents")
def create_incident():
    uid, role = authenticate()
    body = json_body(required=True)
    incident_type = req_enum(body, "incident_type", INCIDENT_TYPES)
    segment_id = req_str(body, "segment_id")
    occurred_at = req_dt(body, "occurred_at")
    damage = req_int(body, "estimated_damage_cents")
    movement_id = opt_str(body, "movement_id")
    injuries = opt_int(body, "injuries_count")
    require_role(role, ["Dispatcher"])
    if segment_id not in store.track_segments:
        raise not_found("track segment not found")
    if movement_id is not None and movement_id not in store.movements:
        raise not_found("train movement not found")
    fra_reportable = (incident_type in ("DERAILMENT", "COLLISION", "HAZMAT")
                      or damage >= FRA_DAMAGE_THRESHOLD_CENTS)
    rec = new_record({
        "incident_type": incident_type,
        "segment_id": segment_id,
        "movement_id": movement_id,
        "occurred_at": occurred_at,
        "estimated_damage_cents": damage,
        "injuries_count": 0 if injuries is None else injuries,
        "status": "REPORTED",
        "fra_reportable": fra_reportable,
        "fra_report_number": None,
    })
    store.incidents[rec["id"]] = rec
    # Safety cascade: loaded / in-transit cars on the involved movement are held.
    if movement_id is not None:
        for wb in store.waybills.values():
            if wb["movement_id"] != movement_id:
                continue
            car = store.railcars.get(wb["railcar_id"])
            if car is not None and car["status"] in ("LOADED", "IN_TRANSIT"):
                car["status"] = "HELD"
                touch(car)
    return success_object(incident_view(rec), status=201)


@bp.get("/rail/incidents")
def list_incidents():
    uid, role = authenticate()
    records = list(store.incidents.values())
    for param, field in (("segment_id", "segment_id"),
                         ("movement_id", "movement_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [i for i in records if i[field] == v]
    limit, offset, total, page = paginate(records)
    return success_list([incident_view(i) for i in page], limit, offset, total)


def _get_incident(iid):
    rec = store.incidents.get(iid)
    if rec is None:
        raise not_found("incident not found")
    return rec


@bp.get("/rail/incidents/<iid>")
def get_incident(iid):
    uid, role = authenticate()
    return success_object(incident_view(_get_incident(iid)))


@bp.post("/rail/incidents/<iid>/investigate")
def investigate_incident(iid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["Dispatcher"])
    inc = _get_incident(iid)
    if inc["status"] not in ("REPORTED", "REOPENED"):
        raise invalid_state("only a REPORTED or REOPENED incident can be investigated")
    inc["status"] = "INVESTIGATING"
    touch(inc)
    return success_object(incident_view(inc))


@bp.post("/rail/incidents/<iid>/file-fra-report")
def file_fra_report(iid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["RegulatorOfficer"])
    inc = _get_incident(iid)
    if inc["status"] != "INVESTIGATING":
        raise invalid_state("only an INVESTIGATING incident can be FRA filed")
    if not inc["fra_reportable"]:
        raise ApiError(422, ERR_INCIDENT_NOT_REPORTABLE,
                       "incident is not FRA reportable")
    inc["fra_report_number"] = store.next_fra_number()
    inc["status"] = "FRA_FILED"
    touch(inc)
    return success_object(incident_view(inc))


@bp.post("/rail/incidents/<iid>/close")
def close_incident(iid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["RegulatorOfficer"])
    inc = _get_incident(iid)
    if inc["status"] == "INVESTIGATING":
        if inc["fra_reportable"]:
            raise ApiError(422, ERR_FRA_REPORT_REQUIRED,
                           "reportable incident must file the FRA report before close")
        inc["status"] = "CLOSED"
    elif inc["status"] == "FRA_FILED":
        inc["status"] = "CLOSED"
    else:
        raise invalid_state("only an INVESTIGATING or FRA_FILED incident can be closed")
    touch(inc)
    return success_object(incident_view(inc))


@bp.post("/rail/incidents/<iid>/reopen")
def reopen_incident(iid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["RegulatorOfficer"])
    inc = _get_incident(iid)
    if inc["status"] != "CLOSED":
        raise invalid_state("only a CLOSED incident can be reopened")
    inc["status"] = "REOPENED"
    touch(inc)
    return success_object(incident_view(inc))
