"""Investigator profile endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_DUPLICATE
from middleware import authorize
from response import success_object
from services.core import (
    new_record, touch, require_path, require_ref, list_response,
    serialize_investigator,
)
from validate import Payload

bp = Blueprint("investigators", __name__)

CERTIFICATION_LEVELS = {"LEVEL_1", "LEVEL_2", "LEVEL_3"}

# Certification ladder: LEVEL_1 leads LOW only; LEVEL_2 LOW|MEDIUM; LEVEL_3 any.
CERT_COVERS = {
    "LEVEL_1": {"LOW"},
    "LEVEL_2": {"LOW", "MEDIUM"},
    "LEVEL_3": {"LOW", "MEDIUM", "HIGH", "CRITICAL"},
}


@bp.post("/er/investigators")
def create_investigator():
    authorize({"ERManager"})
    p = Payload(request.get_json(silent=True))
    employee_id = p.get_str("employee_id", required=True)
    certification_level = p.get_enum("certification_level", CERTIFICATION_LEVELS,
                                     required=True)
    max_active_cases = p.get_int("max_active_cases", required=True, minimum=1)
    conflicted = p.get_list_of_str("conflicted_employee_ids", required=False)

    # priority 5 — body FK resolution
    if employee_id is not None:
        require_ref("employees", employee_id, "employee_id")
    if conflicted is not None:
        for cid in conflicted:
            require_ref("employees", cid, "conflicted_employee_ids")

    # priority 15 — one profile per employee
    for inv in db["investigators"].values():
        if employee_id is not None and inv["employee_id"] == employee_id:
            raise_error(ERR_DUPLICATE,
                        f"an investigator profile already exists for employee {employee_id}")

    # priority 24
    p.raise_if_errors()

    rec = new_record()
    rec.update({
        "employee_id": employee_id,
        "certification_level": certification_level,
        "max_active_cases": max_active_cases,
        "active_case_count": 0,
        "conflicted_employee_ids": list(conflicted or []),
    })
    db["investigators"][rec["id"]] = rec
    return success_object(serialize_investigator(rec), status=201)


@bp.get("/er/investigators/<iid>")
def get_investigator(iid):
    authorize({"ERManager", "Investigator", "LegalCounsel"})
    rec = require_path("investigators", iid)
    return success_object(serialize_investigator(rec))


@bp.get("/er/investigators")
def list_investigators():
    authorize({"ERManager", "LegalCounsel", "HRAnalyst"})
    items = list(db["investigators"].values())
    for field in ("certification_level", "employee_id"):
        v = request.args.get(field)
        if v is not None:
            items = [i for i in items if i.get(field) == v]
    return list_response(items, serialize_investigator)


@bp.patch("/er/investigators/<iid>")
def patch_investigator(iid):
    authorize({"ERManager"})
    rec = require_path("investigators", iid)
    p = Payload(request.get_json(silent=True))
    certification_level = p.get_enum("certification_level", CERTIFICATION_LEVELS)
    max_active_cases = p.get_int("max_active_cases", minimum=1)
    conflicted = p.get_list_of_str("conflicted_employee_ids")

    # priority 5
    if conflicted is not None:
        for cid in conflicted:
            require_ref("employees", cid, "conflicted_employee_ids")

    # priority 24
    p.raise_if_errors()

    changed = False
    if certification_level is not None:
        rec["certification_level"] = certification_level
        changed = True
    if max_active_cases is not None:
        rec["max_active_cases"] = max_active_cases
        changed = True
    if conflicted is not None:
        rec["conflicted_employee_ids"] = list(conflicted)
        changed = True
    if changed:
        touch(rec)
    return success_object(serialize_investigator(rec))
