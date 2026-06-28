"""SOAP notes (PRD §3.5)."""
from flask import Blueprint, request

import db
import helpers as h
import response
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_VERSION, ERR_UNAUTHORIZED,
)
from middleware import authenticate, require_role

bp = Blueprint("soap_notes", __name__)

NARRATIVE = ("subjective", "objective", "assessment", "plan")


def serialize(n):
    return h.public(n)


def _apply_clearances(note):
    """Record each cleared tag for the client (increment per-tag counter)."""
    appt = db.appointments[note["appointment_id"]]
    client = db.clients[appt["client_id"]]
    counts = client.setdefault("_clear_counts", {})
    cleared = client.setdefault("_cleared_tags", set())
    for tag in note["clears_contraindication_tags"]:
        counts[tag] = counts.get(tag, 0) + 1
        cleared.add(tag)
    note["_applied_tags"] = list(note["clears_contraindication_tags"])


def _revoke_clearances(note):
    """Un-clear exactly the tags this note had applied (decrement counters)."""
    appt = db.appointments[note["appointment_id"]]
    client = db.clients[appt["client_id"]]
    counts = client.setdefault("_clear_counts", {})
    cleared = client.setdefault("_cleared_tags", set())
    for tag in note.get("_applied_tags", []):
        if counts.get(tag, 0) > 0:
            counts[tag] -= 1
        if counts.get(tag, 0) <= 0:
            cleared.discard(tag)
    note["_applied_tags"] = []


@bp.post("/practice/soap-notes")
def create_note():
    caller = authenticate()
    require_role(caller, {"Therapist"})
    body = h.get_body()

    appointment_id = h.as_str(h.require(body, "appointment_id"), "appointment_id")
    appt = h.resolve(db.appointments, appointment_id)
    # Therapist must be the one assigned to the appointment to act on it.
    if appt["therapist_id"] != caller.user_id:
        raise ApiError(*ERR_UNAUTHORIZED, message="not assigned therapist")

    subjective = h.opt(body, "subjective", "")
    objective = h.opt(body, "objective", "")
    assessment = h.opt(body, "assessment", "")
    plan = h.opt(body, "plan", "")
    clears = h.opt(body, "clears_contraindication_tags", [])
    if not isinstance(clears, list):
        raise ApiError(*ERR_INVALID_REQUEST, message="clears_contraindication_tags must be a list")

    ent = h.new_entity({
        "appointment_id": appointment_id,
        "subjective": subjective if subjective is not None else "",
        "objective": objective if objective is not None else "",
        "assessment": assessment if assessment is not None else "",
        "plan": plan if plan is not None else "",
        "clears_contraindication_tags": list(clears),
        "note_status": "DRAFT",
    })
    ent["_applied_tags"] = []
    ent["_ever_finalized"] = False
    db.soap_notes[ent["id"]] = ent
    return response.success(serialize(ent), status=201)


@bp.get("/practice/soap-notes")
def list_notes():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "Therapist", "FrontDesk"})
    limit, offset = h.get_pagination()
    appointment_id = request.args.get("appointment_id")
    items = list(db.soap_notes.values())
    if appointment_id is not None:
        items = [n for n in items if n["appointment_id"] == appointment_id]
    if caller.role == "Therapist":
        items = [n for n in items
                 if db.appointments.get(n["appointment_id"], {}).get("therapist_id") == caller.user_id]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([serialize(n) for n in page], limit, offset, total)


@bp.get("/practice/soap-notes/<id>")
def get_note(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "Therapist", "FrontDesk"})
    ent = h.resolve(db.soap_notes, id)
    if caller.role == "Therapist":
        appt = db.appointments.get(ent["appointment_id"])
        if appt is None or appt["therapist_id"] != caller.user_id:
            raise ApiError(*ERR_NOT_FOUND, message="not found")
    return response.success(serialize(ent))


@bp.patch("/practice/soap-notes/<id>")
def edit_note(id):
    caller = authenticate()
    require_role(caller, {"Therapist"})
    ent = h.resolve(db.soap_notes, id)
    appt = db.appointments[ent["appointment_id"]]
    if appt["therapist_id"] != caller.user_id:
        raise ApiError(*ERR_UNAUTHORIZED, message="not assigned therapist")
    body = h.get_body()
    expected = h.require(body, "expected_soap_note_version")
    expected = h.as_int(expected, "expected_soap_note_version")
    # editable only while DRAFT
    if ent["note_status"] != "DRAFT":
        raise ApiError(*ERR_INVALID_STATE, message="note not DRAFT")
    if expected != ent["version"]:
        raise ApiError(*ERR_STALE_VERSION, message="stale note version")

    for field in NARRATIVE:
        if field in body and body[field] is not None:
            ent[field] = h.as_str(body[field], field)
    if "clears_contraindication_tags" in body and body["clears_contraindication_tags"] is not None:
        clears = body["clears_contraindication_tags"]
        if not isinstance(clears, list):
            raise ApiError(*ERR_INVALID_REQUEST, message="clears_contraindication_tags must be a list")
        ent["clears_contraindication_tags"] = list(clears)
    h.touch(ent)
    return response.success(serialize(ent))


@bp.post("/practice/soap-notes/<id>/finalize")
def finalize_note(id):
    caller = authenticate()
    require_role(caller, {"Therapist"})
    ent = h.resolve(db.soap_notes, id)
    appt = db.appointments[ent["appointment_id"]]
    if appt["therapist_id"] != caller.user_id:
        raise ApiError(*ERR_UNAUTHORIZED, message="not assigned therapist")
    if ent["note_status"] != "DRAFT":
        raise ApiError(*ERR_INVALID_STATE, message="note not DRAFT")
    for field in NARRATIVE:
        if not ent.get(field):
            raise ApiError(*ERR_INVALID_REQUEST, message=f"{field} must be non-empty")

    if ent.get("_ever_finalized"):
        ent["note_status"] = "AMENDED"
    else:
        ent["note_status"] = "FINALIZED"
    ent["_ever_finalized"] = True
    # record clearances
    _apply_clearances(ent)
    h.touch(ent)
    return response.success(serialize(ent))


@bp.post("/practice/soap-notes/<id>/reopen")
def reopen_note(id):
    caller = authenticate()
    require_role(caller, {"Therapist"})
    ent = h.resolve(db.soap_notes, id)
    appt = db.appointments[ent["appointment_id"]]
    if appt["therapist_id"] != caller.user_id:
        raise ApiError(*ERR_UNAUTHORIZED, message="not assigned therapist")
    if ent["note_status"] not in ("FINALIZED", "AMENDED"):
        raise ApiError(*ERR_INVALID_STATE, message="note not finalized")
    # only while linked appointment's settlement_status is not yet PAID
    if appt["settlement_status"] == "PAID":
        raise ApiError(*ERR_INVALID_STATE, message="appointment already paid")

    _revoke_clearances(ent)
    ent["note_status"] = "DRAFT"
    h.touch(ent)
    return response.success(serialize(ent))
