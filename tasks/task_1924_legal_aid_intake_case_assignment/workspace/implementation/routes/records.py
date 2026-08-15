"""Read-only auxiliary resources: time entries, unmet-need records, waitlist."""
from flask import Blueprint, request

from db import db
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.common import get_or_404, list_response
from services.serialize import (time_entry_json, unmet_record_json,
                                waitlist_entry_json)

bp = Blueprint("records", __name__)

_UNMET_ROLES = ["IntakeSpecialist", "SupervisingAttorney", "GrantsManager",
                "ProgramDirector"]
_WAITLIST_ROLES = ["IntakeSpecialist", "SupervisingAttorney",
                   "ProgramDirector"]


@bp.route("/time-entries/<tid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_time_entry(tid):
    return ok_object(time_entry_json(get_or_404(db.time_entries, tid)))


@bp.route("/time-entries", methods=["GET"])
@require_roles(ALL_ROLES)
def list_time_entries():
    records = list(db.time_entries.values())
    for param in ("case_id", "staff_id"):
        value = request.args.get(param)
        if value is not None:
            records = [t for t in records if t[param] == value]
    return list_response(records, time_entry_json)


@bp.route("/unmet-need-records/<rid>", methods=["GET"])
@require_roles(_UNMET_ROLES)
def get_unmet_record(rid):
    return ok_object(unmet_record_json(get_or_404(db.unmet_records, rid)))


@bp.route("/unmet-need-records", methods=["GET"])
@require_roles(_UNMET_ROLES)
def list_unmet_records():
    records = list(db.unmet_records.values())
    for param in ("application_id", "reason_code"):
        value = request.args.get(param)
        if value is not None:
            records = [r for r in records if r[param] == value]
    return list_response(records, unmet_record_json)


@bp.route("/waitlist-entries/<wid>", methods=["GET"])
@require_roles(_WAITLIST_ROLES)
def get_waitlist_entry(wid):
    return ok_object(waitlist_entry_json(get_or_404(db.waitlist_entries,
                                                    wid)))


@bp.route("/waitlist-entries", methods=["GET"])
@require_roles(_WAITLIST_ROLES)
def list_waitlist_entries():
    records = list(db.waitlist_entries.values())
    value = request.args.get("application_id")
    if value is not None:
        records = [e for e in records if e["application_id"] == value]
    return list_response(records, waitlist_entry_json, order="ranked")
