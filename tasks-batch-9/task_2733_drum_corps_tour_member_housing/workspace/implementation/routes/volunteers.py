from flask import Blueprint

import find
import serialize
import validators as v
from auth import acting_user_id, endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import add_days, clock_date, db, fmt_date, new_record, sorted_records, touch

bp = Blueprint("volunteers", __name__)

ROLE_TYPES = ("DRIVER", "COOK", "CHAPERONE", "ATHLETIC_TRAINER")
DECISIONS = ("CLEAR", "REJECT")
READ_ROLES = ["CorpsDirector", "TourManager", "VolunteerScreener", "Volunteer"]
LIST_ROLES = ["CorpsDirector", "TourManager", "VolunteerScreener"]
SCREENING_VALID_DAYS = 365


@bp.route("/volunteers", methods=["POST"])
@endpoint(["VolunteerScreener"])
def create_volunteer():
    body = v.get_body()
    full_name = v.req_str(body, "full_name")
    email = v.req_str(body, "email")
    role_type = v.req_enum(body, "role_type", ROLE_TYPES)
    cdl_number = v.opt_str(body, "cdl_number")
    credential_id = v.opt_str(body, "credential_id")
    # Rung 5 -- cdl_number when and only when DRIVER; credential_id when and
    # only when ATHLETIC_TRAINER.
    if role_type == "DRIVER":
        v.conditional(cdl_number is not None, "cdl_number is required for a DRIVER.")
    else:
        v.conditional(cdl_number is None, "cdl_number is only permitted for a DRIVER.")
    if role_type == "ATHLETIC_TRAINER":
        v.conditional(credential_id is not None,
                      "credential_id is required for an ATHLETIC_TRAINER.")
    else:
        v.conditional(credential_id is None,
                      "credential_id is only permitted for an ATHLETIC_TRAINER.")
    # Rung 47 -- email must be unique across all volunteers in the system.
    for other in db.volunteers.values():
        if other["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL", "That email is already registered.")

    record = new_record()
    record.update({
        "full_name": full_name,
        "email": email,
        "role_type": role_type,
        "cdl_number": cdl_number,
        "credential_id": credential_id,
        "screening_status": "PENDING",
        "screening_decided_on": None,
        "screening_expires_on": None,
        "_screening_expires_on": None,
        "screened_by_user_id": None,
    })
    db.volunteers[record["id"]] = record
    return object_response(serialize.volunteer(record), 201)


@bp.route("/volunteers/<volunteer_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_volunteer(volunteer_id):
    return object_response(serialize.volunteer(find.volunteer(volunteer_id)))


@bp.route("/volunteers", methods=["GET"])
@endpoint(LIST_ROLES)
def list_volunteers():
    role_type = v.arg_str("role_type")
    screening_status = v.arg_str("screening_status")
    records = []
    for record in sorted_records(db.volunteers):
        if role_type is not None and record["role_type"] != role_type:
            continue
        if screening_status is not None and record["screening_status"] != screening_status:
            continue
        records.append(record)
    return paginate(records, serialize.volunteer)


@bp.route("/volunteers/<volunteer_id>/screening-decision", methods=["POST"])
@endpoint(["VolunteerScreener"])
def screening_decision(volunteer_id):
    body = v.get_body()
    decision = v.req_enum(body, "decision", DECISIONS)
    decided_raw, decided_on = v.req_date(body, "decided_on")
    volunteer = find.volunteer(volunteer_id)
    # Rung 22 -- a second decision on an already-decided volunteer is refused.
    if volunteer["screening_status"] != "PENDING":
        raise ApiError("ERR_INVALID_SCREENING_STATE",
                       "This volunteer's screening has already been decided.")
    # Rung 44 -- no business date later than the logical-clock date.
    if decided_on > clock_date():
        raise ApiError("ERR_FUTURE_DATED_INPUT",
                       "decided_on may not be later than the logical-clock date.")

    volunteer["screening_decided_on"] = decided_raw
    volunteer["screened_by_user_id"] = acting_user_id()
    if decision == "CLEAR":
        volunteer["screening_status"] = "CLEARED"
        expires = add_days(decided_on, SCREENING_VALID_DAYS)
        volunteer["_screening_expires_on"] = expires
        volunteer["screening_expires_on"] = fmt_date(expires)
    else:
        volunteer["screening_status"] = "REJECTED"
        volunteer["_screening_expires_on"] = None
        volunteer["screening_expires_on"] = None
    touch(volunteer)
    return object_response(serialize.volunteer(volunteer))
