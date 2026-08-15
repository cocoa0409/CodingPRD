"""CaseNote endpoints (append-only documentation)."""

from flask import Blueprint

from db import store, new_id, stamp_new_note
from errors import ApiError, ERR_NOT_FOUND
from helpers import body_dict, req_string, req_enum, opt_date
from middleware import (
    authenticate,
    authorize,
    AUTHOR_ROLE_BY_ROLE,
    CASE_MANAGER,
    HOUSING_COORDINATOR,
    EMPLOYMENT_SPECIALIST,
    AGENCY_DIRECTOR,
)
from response import success_object, success_list
from serializers import ser_note
from services import notes_of_case, sorted_records
from routes.cases import get_case_or_404

bp = Blueprint("notes", __name__)

NOTE_TYPES = {"GENERAL", "SERVICE_DELIVERY", "INCIDENT", "TRANSFER"}
AUTHOR_ROLES = {CASE_MANAGER, HOUSING_COORDINATOR, EMPLOYMENT_SPECIALIST, AGENCY_DIRECTOR}


@bp.post("/case-notes")
def create_note():
    _uid, role = authenticate()
    authorize(role, AUTHOR_ROLES)  # FederalOfficer cannot author notes
    d = body_dict()
    # Priority 3: body FK existence
    case_id = req_string(d, "case_id")
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "case_id does not identify an existing case.")
    # Priority 4: schema
    note_type = req_enum(d, "note_type", NOTE_TYPES)
    body = req_string(d, "body")
    service_date = opt_date(d, "service_date")
    note = {
        "id": new_id(),
        "case_id": case["id"],
        "note_type": note_type,
        "body": body,
        "service_date": service_date,
        "author_role": AUTHOR_ROLE_BY_ROLE[role],
    }
    stamp_new_note(note)
    store.case_notes[note["id"]] = note
    return success_object(ser_note(note), 201)


@bp.get("/cases/<case_id>/case-notes")
def list_notes_of_case(case_id):
    authenticate()
    case = get_case_or_404(case_id)
    return success_list(sorted_records(notes_of_case(case["id"])), ser_note)
