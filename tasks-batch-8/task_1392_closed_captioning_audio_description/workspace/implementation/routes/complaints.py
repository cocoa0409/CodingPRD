"""Complaint endpoints (PRD §3.8): file, triage, dismiss, begin-remediation,
resolve, reopen — with the dispute/remediation cascades."""
from datetime import timedelta
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, now, stamp_new, touch
from errors import (
    ApiError,
    ERR_COMPLAINT_ALREADY_OPEN,
    ERR_COMPLAINT_WINDOW_CLOSED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_REOPEN_WINDOW_CLOSED,
    ERR_RESOLUTION_ARTIFACT_INCOMPLETE,
    ERR_SEGREGATION_OF_DUTIES,
    invalid_transition,
    not_found,
    validation,
)
from respond import list_response, ok_object
from serialize import order_active_complaint_count
from services import workflow

bp = Blueprint("complaints", __name__)

SEVERITIES = {"FCC_CRITICAL", "MAJOR", "MINOR"}


def get_complaint(complaint_id):
    c = DB.complaints.get(complaint_id)
    if c is None:
        raise not_found("Complaint not found")
    return c


def _subject_client_id(caption_track_id, ad_track_id, live_event_id):
    if caption_track_id:
        track = DB.caption_tracks[caption_track_id]
        return DB.work_orders[track["work_order_id"]]["client_id"]
    if ad_track_id:
        track = DB.ad_tracks[ad_track_id]
        return DB.work_orders[track["work_order_id"]]["client_id"]
    return DB.live_events[live_event_id]["client_id"]


def _subject_completion(caption_track_id, ad_track_id, live_event_id):
    """For tracks, the work order's most recent delivered_at; for live events,
    the event's end_at."""
    if caption_track_id:
        track = DB.caption_tracks[caption_track_id]
        return DB.work_orders[track["work_order_id"]]["delivered_at"]
    if ad_track_id:
        track = DB.ad_tracks[ad_track_id]
        return DB.work_orders[track["work_order_id"]]["delivered_at"]
    return DB.live_events[live_event_id]["end_at"]


def _subject_state_eligible(caption_track_id, ad_track_id, live_event_id):
    """caption/AD track DELIVERED, live event WRAP or SETTLED."""
    if caption_track_id:
        return DB.caption_tracks[caption_track_id]["track_status"] == "DELIVERED"
    if ad_track_id:
        return DB.ad_tracks[ad_track_id]["ad_status"] == "DELIVERED"
    return DB.live_events[live_event_id]["event_status"] in ("WRAP", "SETTLED")


def _has_open_complaint(caption_track_id, ad_track_id, live_event_id):
    for c in DB.complaints.values():
        if c["complaint_status"] not in ("OPEN", "TRIAGED", "REMEDIATING", "REOPENED"):
            continue
        if caption_track_id and c["caption_track_id"] == caption_track_id:
            return True
        if ad_track_id and c["audio_description_track_id"] == ad_track_id:
            return True
        if live_event_id and c["live_event_id"] == live_event_id:
            return True
    return False


@bp.post("/caption-ad/complaints")
@guarded({"ClientContact"})
def create_complaint(_user_id, _role):
    data = body()
    caption_track_id = data.get("caption_track_id")
    ad_track_id = data.get("audio_description_track_id")
    live_event_id = data.get("live_event_id")
    # Existence (priority 3): every supplied subject FK must resolve.
    for value, table, label in (
        (caption_track_id, DB.caption_tracks, "caption_track_id"),
        (ad_track_id, DB.ad_tracks, "audio_description_track_id"),
        (live_event_id, DB.live_events, "live_event_id"),
    ):
        if value is not None:
            if not isinstance(value, str):
                raise validation(f"Field '{label}' must be a string or null")
            if value not in table:
                raise not_found(f"Referenced {label} does not exist")
    # Ownership (priority 4): the caller must own the subject's client.
    for value in (caption_track_id, ad_track_id, live_event_id):
        if value is not None:
            owner = _subject_client_id(caption_track_id if value == caption_track_id else None,
                                       ad_track_id if value == ad_track_id else None,
                                       live_event_id if value == live_event_id else None)
            if owner != _user_id:
                raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "The acting client does not own the complaint subject")
    # Shape (priority 5): exactly one subject FK non-null.
    supplied = [v for v in (caption_track_id, ad_track_id, live_event_id) if v is not None]
    if len(supplied) != 1:
        raise validation("Exactly one of caption_track_id, audio_description_track_id, live_event_id must be non-null")
    severity = data.get("severity")
    if severity not in SEVERITIES:
        raise validation("Field 'severity' must be FCC_CRITICAL, MAJOR, or MINOR")
    description = data.get("description")
    if not isinstance(description, str) or description == "":
        raise validation("Field 'description' is required and must be non-empty")
    # Temporal (priority 9): within 30 days inclusive of subject completion.
    completion = _subject_completion(caption_track_id, ad_track_id, live_event_id)
    t = now()
    if completion is not None and t > completion + timedelta(days=30):
        raise ApiError(ERR_COMPLAINT_WINDOW_CLOSED, 409, "Complaint opened more than 30 days after subject completion")
    # Cardinality (priority 10): one non-terminal complaint per subject.
    if _has_open_complaint(caption_track_id, ad_track_id, live_event_id):
        raise ApiError(ERR_COMPLAINT_ALREADY_OPEN, 409, "Subject already has a non-terminal complaint")
    # Linked-entity state (priority 11).
    if not _subject_state_eligible(caption_track_id, ad_track_id, live_event_id):
        raise invalid_transition("Complaint subject must be a DELIVERED track or a WRAP/SETTLED live event")
    rec = {
        "client_id": _subject_client_id(caption_track_id, ad_track_id, live_event_id),
        "caption_track_id": caption_track_id,
        "audio_description_track_id": ad_track_id,
        "live_event_id": live_event_id,
        "severity": severity,
        "description": description,
        "complaint_status": "OPEN",
        "escalation_level": 0,
        "remediation_track_id": None,
        "resolved_at": None,
        "resolver_user_id": None,
    }
    stamp_new(rec)
    DB.complaints[rec["id"]] = rec
    workflow.dispute_cascade(rec)
    return ok_object(serialize.complaint(rec), status=201)


@bp.get("/caption-ad/complaints")
@guarded(set(ALL_ROLES))
def list_complaints(_user_id, _role):
    records = list(DB.complaints.values())
    for param in (
        "client_id",
        "caption_track_id",
        "audio_description_track_id",
        "live_event_id",
        "remediation_track_id",
        "complaint_status",
    ):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[param] == v]
    return list_response(records, serialize.complaint)


@bp.get("/caption-ad/complaints/<complaintId>")
@guarded(set(ALL_ROLES))
def get_one_complaint(complaintId, _user_id, _role):
    return ok_object(serialize.complaint(get_complaint(complaintId)))


@bp.post("/caption-ad/complaints/<complaintId>/triage")
@guarded({"OperationsManager"})
def triage_complaint(complaintId, _user_id, _role):
    c = get_complaint(complaintId)
    new_severity = body().get("severity")
    if new_severity is not None and new_severity not in SEVERITIES:
        raise validation("Field 'severity' must be FCC_CRITICAL, MAJOR, or MINOR")
    if c["complaint_status"] not in ("OPEN", "REOPENED"):
        raise invalid_transition("Only an OPEN or REOPENED complaint can be triaged")
    c["complaint_status"] = "TRIAGED"
    if new_severity is not None:
        c["severity"] = new_severity  # triage may re-grade severity
    touch(c)
    return ok_object(serialize.complaint(c))


@bp.post("/caption-ad/complaints/<complaintId>/dismiss")
@guarded({"OperationsManager"})
def dismiss_complaint(complaintId, _user_id, _role):
    c = get_complaint(complaintId)
    rationale = body().get("rationale")
    if not isinstance(rationale, str) or rationale == "":
        raise validation("Field 'rationale' is required and must be non-empty")
    if c["complaint_status"] not in ("OPEN", "TRIAGED"):
        raise invalid_transition("Only an OPEN or TRIAGED complaint can be dismissed")
    c["complaint_status"] = "DISMISSED"
    touch(c)
    workflow.dismiss_cascade(c)
    return ok_object(serialize.complaint(c))


@bp.post("/caption-ad/complaints/<complaintId>/begin-remediation")
@guarded({"OperationsManager"})
def begin_remediation(complaintId, _user_id, _role):
    c = get_complaint(complaintId)
    if c["complaint_status"] != "TRIAGED":
        raise invalid_transition("Only a TRIAGED complaint can begin remediation")
    if c["live_event_id"] is not None:
        # Live-event subjects have no remediation artifact.
        raise invalid_transition("Live-event subjects have no remediation artifact")
    c["complaint_status"] = "REMEDIATING"
    if c["caption_track_id"] is not None:
        workflow.create_remediation_caption_track(c, _user_id)
    else:
        workflow.begin_remediation_ad(c)
    touch(c)
    return ok_object(serialize.complaint(c))


@bp.post("/caption-ad/complaints/<complaintId>/resolve")
@guarded({"OperationsManager"})
def resolve_complaint(complaintId, _user_id, _role):
    c = get_complaint(complaintId)
    data = body()
    if c["live_event_id"] is not None:
        # Live-event subjects resolve from TRIAGED and require a note.
        note = data.get("resolution_note")
        if not isinstance(note, str) or note == "":
            raise validation("Field 'resolution_note' is required for live-event complaints")
        if c["complaint_status"] != "TRIAGED":
            raise invalid_transition("A live-event complaint resolves from TRIAGED")
        c["complaint_status"] = "RESOLVED"
        c["resolved_at"] = now()
        c["resolver_user_id"] = _user_id
        touch(c)
        workflow.set_dispute_freeze(False, live_event_id=c["live_event_id"])
        return ok_object(serialize.complaint(c))
    # Track subjects resolve from REMEDIATING with a DELIVERED artifact.
    if c["complaint_status"] != "REMEDIATING":
        raise invalid_transition("A track complaint resolves from REMEDIATING")
    # Segregation of duties: resolver must differ from the disputed track's author.
    if c["caption_track_id"] is not None:
        disputed = DB.caption_tracks[c["caption_track_id"]]
    else:
        disputed = DB.ad_tracks[c["audio_description_track_id"]]
    if _user_id == disputed["author_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Resolver must differ from the disputed track's author")
    kind, artifact = workflow.current_artifact(c)
    artifact_status = artifact["track_status"] if kind == "caption" else artifact["ad_status"]
    if artifact_status != "DELIVERED":
        raise ApiError(ERR_RESOLUTION_ARTIFACT_INCOMPLETE, 409, "The remediation artifact is not DELIVERED")
    c["complaint_status"] = "RESOLVED"
    c["resolved_at"] = now()
    c["resolver_user_id"] = _user_id
    touch(c)
    if kind == "caption":
        workflow.set_dispute_freeze(False, caption_track_id=artifact["id"])
        workflow.set_dispute_freeze(False, caption_track_id=c["caption_track_id"])
    else:
        workflow.set_dispute_freeze(False, ad_track_id=artifact["id"])
    return ok_object(serialize.complaint(c))


@bp.post("/caption-ad/complaints/<complaintId>/reopen")
@guarded({"ClientContact"})
def reopen_complaint(complaintId, _user_id, _role):
    c = get_complaint(complaintId)
    if c["client_id"] != _user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "The acting client does not own this complaint")
    if c["complaint_status"] != "RESOLVED":
        raise invalid_transition("Only a RESOLVED complaint can be reopened")
    t = now()
    # Reopen within 14 days inclusive of resolved_at.
    if t > c["resolved_at"] + timedelta(days=14):
        raise ApiError(ERR_REOPEN_WINDOW_CLOSED, 409, "Reopen attempted more than 14 days after resolution")
    c["complaint_status"] = "REOPENED"
    c["escalation_level"] += 1  # reopen adds its own increment immediately
    touch(c)
    # Re-dispute the current artifact (remediation track when set, otherwise
    # the original subject track) and push the order back to REMEDIATION.
    if c["live_event_id"] is None:
        kind, artifact = workflow.current_artifact(c)
        status_field = "track_status" if kind == "caption" else "ad_status"
        if artifact[status_field] == "DELIVERED":
            artifact[status_field] = "DISPUTED"
            touch(artifact)
        if kind == "caption":
            workflow.set_dispute_freeze(True, caption_track_id=artifact["id"])
        else:
            workflow.set_dispute_freeze(True, ad_track_id=artifact["id"])
        order = DB.work_orders[artifact["work_order_id"]]
        if order["order_status"] == "DELIVERED":
            order["order_status"] = "REMEDIATION"
            touch(order)
    return ok_object(serialize.complaint(c))
