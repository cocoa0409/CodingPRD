"""Voter list entries: statutory content and the six ordered eligibility rules."""

from flask import Blueprint

import auth
import gates
import store
import validate
from routes import common

bp = Blueprint("entries", __name__)

BASE = "/labor-relations/voter-list-entries"
READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.BOARD, auth.UNION)


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.ANALYST, auth.DIRECTOR])
def create_entry(user_id, role):
    schema = validate.Schema(validate.body())
    voter_list_id = schema.reference("voter_list_id")
    classification_id = schema.reference("classification_id")
    full_name = schema.string("full_name")
    hire_date = schema.date("hire_date")
    termination_date = schema.date("termination_date", required=False)
    home_address = schema.string("home_address", required=False, allow_empty=True)
    personal_email = schema.string("personal_email", required=False, allow_empty=True)
    personal_phone = schema.string("personal_phone", required=False, allow_empty=True)
    shift_code = schema.string("shift_code", required=False, allow_empty=True)
    work_location = schema.string("work_location", required=False, allow_empty=True)
    on_leave_type = schema.enum("on_leave_type", common.LEAVE_TYPES,
                                required=False, default="NONE")

    voter_list = gates.must_exist("voter_lists", voter_list_id)
    classification = gates.must_exist("classifications", classification_id)
    gates.require_same_petition(voter_list["petition_id"], classification["petition_id"])

    row = store.insert("voter_list_entries", {
        "voter_list_id": voter_list_id,
        "classification_id": classification_id,
        "full_name": full_name,
        "hire_date": hire_date,
        "termination_date": termination_date,
        "home_address": home_address,
        "personal_email": personal_email,
        "personal_phone": personal_phone,
        "shift_code": shift_code,
        "work_location": work_location,
        "on_leave_type": on_leave_type,
        "is_statutory_content_complete": False,
        "missing_field_count": 0,
        "eligibility_status": "CHALLENGED",
        "ineligibility_reason": None,
    })
    gates.recompute_entry(row)
    gates.recount_list(voter_list)
    store.touch(voter_list)
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_entries(user_id, role):
    voter_list_id = validate.query_string("voter_list_id")
    classification_id = validate.query_string("classification_id")
    eligibility_status = validate.query_enum("eligibility_status", common.ELIGIBILITY_STATUSES)
    rows = store.ordered("voter_list_entries")
    if voter_list_id is not None:
        rows = [r for r in rows if r["voter_list_id"] == voter_list_id]
    if classification_id is not None:
        rows = [r for r in rows if r["classification_id"] == classification_id]
    if eligibility_status is not None:
        rows = [r for r in rows if r["eligibility_status"] == eligibility_status]
    return common.list_response(rows)


@bp.route(BASE + "/<eid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_entry(user_id, role, eid):
    return common.one(gates.must_exist("voter_list_entries", eid))


@bp.route(BASE + "/<eid>", methods=["PATCH"])
@auth.endpoint([auth.ANALYST, auth.DIRECTOR])
def update_entry(user_id, role, eid):
    schema = validate.Schema(validate.body())
    home_address = schema.string("home_address", required=False, allow_empty=True)
    personal_email = schema.string("personal_email", required=False, allow_empty=True)
    personal_phone = schema.string("personal_phone", required=False, allow_empty=True)
    shift_code = schema.string("shift_code", required=False, allow_empty=True)
    work_location = schema.string("work_location", required=False, allow_empty=True)
    termination_date = schema.date("termination_date", required=False)
    on_leave_type = schema.enum("on_leave_type", common.LEAVE_TYPES, required=False)

    entry = gates.must_exist("voter_list_entries", eid)
    updates = (
        ("home_address", home_address),
        ("personal_email", personal_email),
        ("personal_phone", personal_phone),
        ("shift_code", shift_code),
        ("work_location", work_location),
        ("termination_date", termination_date),
        ("on_leave_type", on_leave_type),
    )
    for name, value in updates:
        if schema.present(name):
            entry[name] = value

    gates.recompute_entry(entry)
    store.touch(entry)
    voter_list = store.get("voter_lists", entry["voter_list_id"])
    if voter_list is not None:
        gates.recount_list(voter_list)
        store.touch(voter_list)
    return common.one(entry)
