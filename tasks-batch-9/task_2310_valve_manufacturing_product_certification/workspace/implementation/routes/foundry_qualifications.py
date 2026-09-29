"""Foundry process/material qualifications (PRD 3.2)."""

from flask import Blueprint

import domain
from auth import ANY, require_action_role, require_roles
from db import clock_now, db, new_row, sort_rows, touch
from errors import api_error
from response import list_response, object_response
from validation import (
    MATERIAL_GRADES,
    PRESSURE_CLASSES,
    PROCESSES,
    filter_value,
    get_body,
    get_datetime,
    get_enum,
    get_int,
    get_string,
    invalid,
    paginate,
    parse_pagination,
)

bp = Blueprint("foundry_qualifications", __name__)

ACTION_ROLES = {
    "QUALIFY": ["QualityManager"],
    "REVOKE": ["QualityManager"],
    "REQUALIFY": ["ProcurementSpecialist"],
}
ACTIONS = list(ACTION_ROLES.keys())


@bp.post("/valve-mfg/foundry-qualifications")
def create_qualification():
    require_roles(["ProcurementSpecialist"])
    body = get_body()
    foundry_id = get_string(body, "foundry_id")
    process = get_enum(body, "process", PROCESSES)
    material_grade = get_enum(body, "material_grade", MATERIAL_GRADES)
    max_pressure_class = get_int(body, "max_pressure_class", allowed=PRESSURE_CLASSES)
    valid_from_raw, valid_from = get_datetime(body, "valid_from")
    valid_until_raw, valid_until = get_datetime(body, "valid_until")
    if valid_from >= valid_until:
        raise invalid("valid_from must be strictly before valid_until")

    domain.find_foundry(foundry_id)

    row = new_row(
        {
            "foundry_id": foundry_id,
            "process": process,
            "material_grade": material_grade,
            "max_pressure_class": max_pressure_class,
            "valid_from": valid_from_raw,
            "valid_until": valid_until_raw,
            "_valid_from_dt": valid_from,
            "_valid_until_dt": valid_until,
            "status": "PENDING",
            "qualified_by_user_id": None,
            "requalification_count": 0,
        }
    )
    db.qualifications[row["id"]] = row
    return object_response(domain.serialize_qualification(row), 201)


@bp.get("/valve-mfg/foundry-qualifications")
def list_qualifications():
    require_roles(ANY)
    limit, offset = parse_pagination()
    rows = sort_rows(list(db.qualifications.values()))
    for row in rows:
        domain.refresh_qualification(row)
    foundry_id = filter_value("foundry_id")
    status = filter_value("status")
    process = filter_value("process")
    material_grade = filter_value("material_grade")
    if foundry_id is not None:
        rows = [r for r in rows if r["foundry_id"] == foundry_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if process is not None:
        rows = [r for r in rows if r["process"] == process]
    if material_grade is not None:
        rows = [r for r in rows if r["material_grade"] == material_grade]
    page, total = paginate(rows, limit, offset)
    return list_response(
        [domain.serialize_qualification(r) for r in page], limit, offset, total
    )


@bp.get("/valve-mfg/foundry-qualifications/<qual_id>")
def get_qualification(qual_id):
    require_roles(ANY)
    row = domain.find_qualification(qual_id)
    return object_response(domain.serialize_qualification(row))


def _overlaps(row, valid_from, valid_until):
    return row["_valid_from_dt"] <= valid_until and valid_from <= row["_valid_until_dt"]


@bp.post("/valve-mfg/foundry-qualifications/<qual_id>/actions")
def qualification_actions(qual_id):
    user_id, role = require_roles(["ProcurementSpecialist", "QualityManager"])
    body = get_body()
    action = get_enum(body, "action", ACTIONS)
    require_action_role(role, action, ACTION_ROLES)

    new_from_raw = new_from = new_until_raw = new_until = None
    if action == "REQUALIFY":
        new_from_raw, new_from = get_datetime(body, "valid_from")
        new_until_raw, new_until = get_datetime(body, "valid_until")
        if new_from >= new_until:
            raise invalid("valid_from must be strictly before valid_until")

    qual = domain.find_qualification(qual_id)

    if action == "QUALIFY":
        if qual["status"] != "PENDING":
            raise api_error(
                "ERR_STATE_INVALID",
                "QUALIFY requires status PENDING (current: %s)" % qual["status"],
            )
        if clock_now() > qual["_valid_until_dt"]:
            raise api_error(
                "ERR_STATE_INVALID", "the qualification window has already closed"
            )
        for other in sort_rows(list(db.qualifications.values())):
            if other["id"] == qual["id"]:
                continue
            if (
                other["foundry_id"] != qual["foundry_id"]
                or other["process"] != qual["process"]
                or other["material_grade"] != qual["material_grade"]
            ):
                continue
            domain.refresh_qualification(other)
            if other["status"] not in ("PENDING", "QUALIFIED"):
                continue
            if _overlaps(other, qual["_valid_from_dt"], qual["_valid_until_dt"]):
                raise api_error(
                    "ERR_QUALIFICATION_WINDOW_OVERLAP",
                    "an existing qualification window intersects this one",
                )
        qual["status"] = "QUALIFIED"
        qual["qualified_by_user_id"] = user_id
        touch(qual)
        foundry = db.foundries.get(qual["foundry_id"])
        if foundry is not None:
            touch(foundry)

    elif action == "REVOKE":
        if qual["status"] != "QUALIFIED":
            raise api_error(
                "ERR_STATE_INVALID",
                "REVOKE requires status QUALIFIED (current: %s)" % qual["status"],
            )
        qual["status"] = "REVOKED"
        touch(qual)
        foundry = db.foundries.get(qual["foundry_id"])
        if foundry is not None:
            touch(foundry)

    else:  # REQUALIFY
        if qual["status"] != "EXPIRED":
            raise api_error(
                "ERR_STATE_INVALID",
                "REQUALIFY requires status EXPIRED (current: %s)" % qual["status"],
            )
        if new_from <= qual["_valid_until_dt"]:
            raise api_error(
                "ERR_QUALIFICATION_WINDOW_OVERLAP",
                "valid_from must be strictly later than the previous valid_until",
            )
        qual["status"] = "PENDING"
        qual["valid_from"] = new_from_raw
        qual["valid_until"] = new_until_raw
        qual["_valid_from_dt"] = new_from
        qual["_valid_until_dt"] = new_until
        qual["requalification_count"] = qual.get("requalification_count", 0) + 1
        qual["qualified_by_user_id"] = None
        touch(qual)

    return object_response(domain.serialize_qualification(qual))
