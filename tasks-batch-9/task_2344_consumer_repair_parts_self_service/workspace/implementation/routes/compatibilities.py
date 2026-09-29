"""Part-to-model fitment windows (PRD 3.3)."""
from flask import Blueprint

import db
from db import base_row, touch
from errors import ApiError
from middleware import COMPLIANCE_OFFICER, DOCUMENTATION_ENGINEER, PROGRAM_ADMIN, \
    REPAIR_PROVIDER_TECH, SAFETY_REVIEWER, SELF_REPAIR_CUSTOMER, endpoint
from response import collection, created, ok
from routes.helpers import filter_as_of_date, filter_bool, filter_eq, get_compat, \
    get_model, get_part
from serializers import compat_json
from services.compliance import compat_rows, rollup_documentation_posture
from validation import F, int_range, read_body

bp = Blueprint("compatibilities", __name__)

READ_ROLES = [PROGRAM_ADMIN, SAFETY_REVIEWER, DOCUMENTATION_ENGINEER, COMPLIANCE_OFFICER,
              SELF_REPAIR_CUSTOMER, REPAIR_PROVIDER_TECH]

CREATE_FIELDS = [
    F("part_id", "string", required=True),
    F("model_id", "string", required=True),
    F("effective_from", "datetime", required=True),
    F("effective_until", "datetime"),
    F("self_service_eligible", "bool", default=False),
    F("install_minutes", "int", required=True),
    F("required_tool_part_id", "string"),
]


def _overlaps(a_from, a_until, b_from, b_until):
    """Half-open [from, until) overlap; abutting windows do not collide."""
    if a_until is not None and b_from >= a_until:
        return False
    if b_until is not None and a_from >= b_until:
        return False
    return True


@bp.post("/part-compatibilities")
@endpoint([PROGRAM_ADMIN])
def create_compat():
    body = read_body(CREATE_FIELDS)
    int_range(body["install_minutes"], "install_minutes", 1, 600)
    if body["effective_until"] is not None and body["effective_until"] <= body["effective_from"]:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "effective_until must be strictly after effective_from.")

    part = get_part(body["part_id"])
    model = get_model(body["model_id"])
    if body["required_tool_part_id"] is not None:
        get_part(body["required_tool_part_id"])

    for existing in compat_rows(part_id=part["id"], model_id=model["id"]):
        if _overlaps(existing["effective_from"], existing.get("effective_until"),
                     body["effective_from"], body["effective_until"]):
            raise ApiError("ERR_COMPATIBILITY_WINDOW_OVERLAP")

    row = base_row()
    row.update({
        "part_id": part["id"],
        "model_id": model["id"],
        "required_tool_part_id": body["required_tool_part_id"],
        "self_service_eligible": body["self_service_eligible"],
        "install_minutes": body["install_minutes"],
        "effective_from": body["effective_from"],
        "effective_until": body["effective_until"],
        "superseded_by_safety_restriction": False,
    })
    db.db.compats.add(row)

    # The required-SKU set may have grown, so the model's posture is re-derived.
    rollup_documentation_posture(model)
    touch(model)
    return created(compat_json(row))


@bp.get("/part-compatibilities/<compatibility_id>")
@endpoint(READ_ROLES)
def read_compat(compatibility_id):
    return ok(compat_json(get_compat(compatibility_id)))


@bp.get("/part-compatibilities")
@endpoint(READ_ROLES)
def list_compats():
    rows = db.db.compats.all()
    for field in ("part_id", "model_id", "required_tool_part_id"):
        rows = filter_eq(rows, field)
    rows = filter_bool(rows, "self_service_eligible")
    rows = filter_as_of_date(rows)
    return collection(rows, compat_json)
