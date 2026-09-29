"""Requesters and citizen complaints (PRD section 3.3)."""

from flask import Blueprint

import auth
import clock
import derive
import lookups
import response
import serializers
import validators
from auth import CITIZEN_LIAISON, PUBLIC_REQUESTER
from db import base_row, db, touch
from errors import fail

bp = Blueprint("citizens", __name__)

CONTACT_PREFS = ("EMAIL", "PHONE", "NONE")
CATEGORIES = ("COORDINATION", "PEDESTRIAN", "DETECTION", "TIMING_OTHER")
DISPOSITIONS = ("TRIAGE", "NO_ACTION")


@bp.route("/signal-ops/requesters", methods=["POST"])
@auth.roles(CITIZEN_LIAISON)
def create_requester():
    data = validators.body()
    display_name = validators.req_str(data, "display_name", 1, 80)
    email = validators.req_str(data, "email", 1, None)
    if "@" not in email:
        fail("ERR_INVALID_REQUEST", "email must contain an @ character.")
    contact_pref = validators.opt_enum(data, "contact_pref", CONTACT_PREFS, "EMAIL")
    for existing in db.requesters.values():
        if existing["email"].lower() == email.lower():
            fail("ERR_DUPLICATE_REQUESTER_EMAIL")
    row = {
        "display_name": display_name,
        "email": email,
        "contact_pref": contact_pref,
    }
    row.update(base_row())
    db.requesters[row["id"]] = row
    return response.created(serializers.requester(row))


@bp.route("/signal-ops/requesters/<requester_id>", methods=["GET"])
@auth.roles(CITIZEN_LIAISON, PUBLIC_REQUESTER)
def read_requester(requester_id):
    auth.require_owner(requester_id)
    row = lookups.requester(requester_id)
    return response.ok(serializers.requester(row))


@bp.route("/signal-ops/requesters/<requester_id>/complaints", methods=["GET"])
@auth.roles(CITIZEN_LIAISON, PUBLIC_REQUESTER)
def list_requester_complaints(requester_id):
    auth.require_owner(requester_id)
    lookups.requester(requester_id)
    rows = [c for c in db.complaints.values() if c["requester_id"] == requester_id]
    rows.sort(key=lambda c: c["_seq"])
    rows = lookups.apply_filter(rows, "status")
    return lookups.listing(rows, serializers.complaint)


@bp.route("/signal-ops/complaints", methods=["POST"])
@auth.roles(CITIZEN_LIAISON, PUBLIC_REQUESTER)
def create_complaint():
    data = validators.body()
    # Rung 5 -- ownership precedes body foreign-key resolution.
    if auth.role() == PUBLIC_REQUESTER and data.get("requester_id") != auth.user_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    requester_id = validators.req_id(data, "requester_id")
    corridor_id = validators.req_id(data, "corridor_id")
    requester = lookups.requester(requester_id)
    corridor = lookups.corridor(corridor_id)
    category = validators.req_enum(data, "category", CATEGORIES)
    narrative = validators.req_str(data, "narrative", 1, 1000)

    row = {
        "requester_id": requester["id"],
        "corridor_id": corridor["id"],
        "linked_project_id": None,
        "category": category,
        "narrative": narrative,
        "received_at": clock.now(),
        "status": "OPEN",
        "reopen_count": 0,
    }
    row.update(base_row())
    db.complaints[row["id"]] = row
    return response.created(serializers.complaint(row))


@bp.route("/signal-ops/complaints/<complaint_id>/triage", methods=["POST"])
@auth.roles(CITIZEN_LIAISON)
def triage_complaint(complaint_id):
    complaint = lookups.complaint(complaint_id)
    data = validators.body()
    disposition = validators.req_enum(data, "disposition", DISPOSITIONS)
    validators.opt_str(data, "note", 1, None)
    if complaint["status"] != "OPEN":
        fail("ERR_COMPLAINT_INVALID_STATE")
    complaint["status"] = "TRIAGED" if disposition == "TRIAGE" else "CLOSED_NO_ACTION"
    touch(complaint)
    return response.ok(serializers.complaint(complaint))


@bp.route("/signal-ops/complaints/<complaint_id>/link", methods=["POST"])
@auth.roles(CITIZEN_LIAISON)
def link_complaint(complaint_id):
    complaint = lookups.complaint(complaint_id)
    data = validators.body()
    project = lookups.project(validators.req_id(data, "project_id"))
    if complaint["status"] != "TRIAGED":
        fail("ERR_COMPLAINT_INVALID_STATE")
    lookups.not_terminal(project)
    if project["corridor_id"] != complaint["corridor_id"]:
        fail("ERR_COMPLAINT_PROJECT_MISMATCH")
    complaint["status"] = "LINKED"
    complaint["linked_project_id"] = project["id"]
    touch(complaint)
    return response.ok(serializers.complaint(complaint))


@bp.route("/signal-ops/complaints/<complaint_id>/resolve", methods=["POST"])
@auth.roles(CITIZEN_LIAISON)
def resolve_complaint(complaint_id):
    complaint = lookups.complaint(complaint_id)
    data = validators.body()
    validators.opt_str(data, "resolution_note", 1, None)
    if complaint["status"] != "LINKED":
        fail("ERR_COMPLAINT_INVALID_STATE")
    project = db.projects.get(complaint.get("linked_project_id"))
    if project is None or project["status"] not in ("EVALUATION", "CLOSED"):
        fail("ERR_PROJECT_NOT_IN_EVALUATION")
    complaint["status"] = "RESOLVED"
    touch(complaint)
    return response.ok(serializers.complaint(complaint))


@bp.route("/signal-ops/complaints/<complaint_id>/reopen", methods=["POST"])
@auth.roles(CITIZEN_LIAISON)
def reopen_complaint(complaint_id):
    complaint = lookups.complaint(complaint_id)
    data = validators.body()
    validators.opt_str(data, "reason", 1, None)
    if complaint["status"] != "RESOLVED":
        fail("ERR_COMPLAINT_INVALID_STATE")
    complaint["status"] = "OPEN"
    complaint["linked_project_id"] = None
    complaint["reopen_count"] = complaint["reopen_count"] + 1
    touch(complaint)
    return response.ok(serializers.complaint(complaint))
