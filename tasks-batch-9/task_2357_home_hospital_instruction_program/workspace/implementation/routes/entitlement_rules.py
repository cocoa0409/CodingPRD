"""The entitlement rule catalogue (PRD §2.10)."""

from flask import Blueprint

import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import DELIVERY_MODES, GRADE_BANDS, RULE_STATUSES, listing
from validation import fail

bp = Blueprint("entitlement_rules", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager"]

CREATE_BODY = {
    "grade_band": {"type": "string", "required": True, "enum": GRADE_BANDS},
    "delivery_mode": {"type": "string", "required": True, "enum": DELIVERY_MODES},
    "base_weekly_minutes": {"type": "integer", "required": True, "min": 1},
    "cap_weekly_minutes": {"type": "integer", "required": True, "min": 0},
    "min_session_minutes": {"type": "integer", "required": True, "min": 1},
    "max_session_minutes": {"type": "integer", "required": True, "min": 0},
    "max_daily_minutes": {"type": "integer", "required": True, "min": 0},
    "min_gap_minutes": {"type": "integer", "required": True, "min": 0},
    "travel_buffer_minutes": {"type": "integer", "required": True, "min": 0},
    "status": {"type": "string", "enum": RULE_STATUSES},
}

LIST_QUERY = {
    "grade_band": {"type": "string", "enum": GRADE_BANDS},
    "delivery_mode": {"type": "string", "enum": DELIVERY_MODES},
    "status": {"type": "string", "enum": RULE_STATUSES},
}


@bp.post("/hhi/entitlement-rules")
@endpoint(["ProgramAdministrator"], body=CREATE_BODY, status=201)
def create_rule():
    body = middleware.body()
    if body["cap_weekly_minutes"] < body["base_weekly_minutes"]:
        fail("cap_weekly_minutes must be at least base_weekly_minutes.")
    if body["max_session_minutes"] < body["min_session_minutes"]:
        fail("max_session_minutes must be at least min_session_minutes.")
    if body["max_daily_minutes"] < body["max_session_minutes"]:
        fail("max_daily_minutes must be at least max_session_minutes.")

    status = body.get("status", "PUBLISHED")
    if status == "PUBLISHED":
        for rule in db.store["entitlement_rules"].values():
            if (
                rule["status"] == "PUBLISHED"
                and rule["grade_band"] == body["grade_band"]
                and rule["delivery_mode"] == body["delivery_mode"]
            ):
                raise ApiError("ERR_DUPLICATE_ENTITLEMENT_RULE")

    row = db.insert(
        "entitlement_rules",
        {
            "grade_band": body["grade_band"],
            "delivery_mode": body["delivery_mode"],
            "base_weekly_minutes": body["base_weekly_minutes"],
            "cap_weekly_minutes": body["cap_weekly_minutes"],
            "min_session_minutes": body["min_session_minutes"],
            "max_session_minutes": body["max_session_minutes"],
            "max_daily_minutes": body["max_daily_minutes"],
            "min_gap_minutes": body["min_gap_minutes"],
            "travel_buffer_minutes": body["travel_buffer_minutes"],
            "status": status,
        },
    )
    return middleware.obj(row)


@bp.get("/hhi/entitlement-rules/<rule_id>")
@endpoint(READ_ROLES)
def read_rule(rule_id):
    row = db.get("entitlement_rules", rule_id)
    if row is None:
        raise ApiError("ERR_ENTITLEMENT_RULE_NOT_FOUND")
    return middleware.obj(row)


@bp.get("/hhi/entitlement-rules")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_rules():
    return listing("entitlement_rules", LIST_QUERY)


@bp.post("/hhi/entitlement-rules/<rule_id>/retire")
@endpoint(["ProgramAdministrator"])
def retire_rule(rule_id):
    row = db.get("entitlement_rules", rule_id)
    if row is None:
        raise ApiError("ERR_ENTITLEMENT_RULE_NOT_FOUND")
    if row["status"] != "PUBLISHED":
        raise ApiError("ERR_RULE_ALREADY_RETIRED")
    db.set_field(row, "status", "RETIRED")
    return middleware.obj(row)
