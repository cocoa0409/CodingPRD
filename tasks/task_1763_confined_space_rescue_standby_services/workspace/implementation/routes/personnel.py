"""Personnel registry (PRD section 3.1)."""

from flask import Blueprint, request

import db
import serializers
from errors import ERR_PERSONNEL_NOT_FOUND, raise_error
from helpers import (
    body, list_response, opt_enum, opt_enum_array, opt_int, reject_unknown,
    req_enum_array, req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object

bp = Blueprint("personnel", __name__)

QUALIFICATIONS = ("ENTRY_SUPERVISOR", "ATTENDANT", "RESCUE_LEAD", "SAFETY_OFFICER", "RESCUER")
CERTIFICATIONS = ("CONFINED_SPACE_RESCUE", "HIGH_ANGLE", "HAZMAT", "MEDIC")
STATUSES = ("ACTIVE", "INACTIVE")


def _get_personnel(personnel_id):
    person = db.personnel.get(personnel_id)
    if person is None:
        raise_error(ERR_PERSONNEL_NOT_FOUND, "Personnel not found")
    return person


@bp.route("/rescue-ops/personnel", methods=["POST"])
def create_personnel():
    require_auth(("OperationsManager",))
    data = body()
    reject_unknown(data, {"full_name", "role_qualifications", "certifications", "max_duty_hours"})
    full_name = req_string(data, "full_name")
    role_qualifications = req_enum_array(data, "role_qualifications", QUALIFICATIONS)
    certifications = opt_enum_array(data, "certifications", CERTIFICATIONS, [])
    max_duty_hours = opt_int(data, "max_duty_hours", 12)
    if max_duty_hours <= 0:
        raise_error(("ERR_INVALID_REQUEST", 400), "max_duty_hours must be positive")
    person = {
        "full_name": full_name,
        "role_qualifications": role_qualifications,
        "certifications": certifications,
        "max_duty_hours": max_duty_hours,
        "status": "ACTIVE",
        "committed_standby_minutes": 0,
    }
    stamp_new(person)
    db.personnel[person["id"]] = person
    return success_object(serializers.personnel(person), 201)


@bp.route("/rescue-ops/personnel", methods=["GET"])
def list_personnel():
    require_auth(ALL_ROLES)
    role_qualification = request.args.get("role_qualification")
    items = list(db.personnel.values())
    if role_qualification is not None:
        items = [p for p in items if role_qualification in p["role_qualifications"]]
    return list_response(items, serializers.personnel, {
        "status": request.args.get("status"),
    })


@bp.route("/rescue-ops/personnel/<personnel_id>", methods=["GET"])
def get_personnel(personnel_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.personnel(_get_personnel(personnel_id)))


@bp.route("/rescue-ops/personnel/<personnel_id>", methods=["PATCH"])
def update_personnel(personnel_id):
    require_auth(("OperationsManager",))
    person = _get_personnel(personnel_id)
    data = body()
    reject_unknown(data, {"status"})
    status = opt_enum(data, "status", STATUSES, None)
    if status is not None and status != person["status"]:
        person["status"] = status
        touch(person)
    return success_object(serializers.personnel(person))
