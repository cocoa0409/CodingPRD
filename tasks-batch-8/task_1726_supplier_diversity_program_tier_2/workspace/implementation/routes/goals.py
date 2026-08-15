"""Program goals: create (with OCC), list, publish (PRD 2.7, 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SOD_VIOLATION,
    ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import GOAL_CATEGORIES, make_record, touch, pub_goal
from validate import get_body, req_int, req_enum, opt_bool, req_decimal, get_resource

bp = Blueprint("goals", __name__)

ADMIN = ["DiversityAdmin"]
READERS = ["DiversityAdmin", "DiversityAnalyst", "BusinessUnitLead", "Auditor"]


def _same_key(goal, business_unit_id, cert_category, fiscal_year):
    return (goal["business_unit_id"] == business_unit_id
            and goal["cert_category"] == cert_category
            and goal["fiscal_year"] == fiscal_year)


@bp.route("/api/v1/business-units/<rid>/goals", methods=["POST"])
def create_goal(rid):
    caller = authorized(ADMIN)
    bu = get_resource("business_units", rid)
    body = get_body()
    # OCC (PRD 2.7): the only endpoint taking an expected_..._version field.
    expected = body.get("expected_business_unit_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_business_unit_version is required")
    if expected != bu["version"]:
        raise_error(ERR_STALE_VERSION, "business unit version does not match")
    fiscal_year = req_int(body, "fiscal_year")
    cert_category = req_enum(body, "cert_category", GOAL_CATEGORIES)
    goal_type = req_enum(body, "goal_type", ("PERCENT_OF_SPEND", "ABSOLUTE_AMOUNT"))
    target_raw = req_decimal(body, "target_value")
    if goal_type == "PERCENT_OF_SPEND":
        if target_raw <= 0 or target_raw > Decimal("100.00"):
            raise_error(
                ERR_INVALID_REQUEST,
                "target_value for PERCENT_OF_SPEND must be in (0, 100.00]",
            )
        target_value = float(target_raw)
    else:
        raw = body.get("target_value")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise_error(
                ERR_INVALID_REQUEST,
                "target_value for ABSOLUTE_AMOUNT must be an integer cents amount > 0",
            )
        target_value = raw
    include_tier2 = opt_bool(body, "include_tier2", True)
    # A new DRAFT supersedes any existing DRAFT with the same key (PRD 3.6).
    for other in db["goals"].values():
        if other["status"] == "DRAFT" and _same_key(other, bu["id"], cert_category, fiscal_year):
            other["status"] = "SUPERSEDED"
            touch(other)
    rec = make_record({
        "business_unit_id": bu["id"],
        "fiscal_year": fiscal_year,
        "cert_category": cert_category,
        "goal_type": goal_type,
        "target_value": target_value,
        "include_tier2": include_tier2,
        "status": "DRAFT",
        "created_by_user_id": caller.user_id,
    })
    db["goals"][rec["id"]] = rec
    touch(bu)
    return success_object(pub_goal(rec), status=201)


@bp.route("/api/v1/business-units/<rid>/goals", methods=["GET"])
def list_goals(rid):
    authorized(READERS)
    bu = get_resource("business_units", rid)
    filters = {
        "fiscal_year": request.args.get("fiscal_year"),
        "status": request.args.get("status"),
    }
    records = [g for g in db["goals"].values() if g["business_unit_id"] == bu["id"]]
    return list_response(records, filters, pub_goal)


@bp.route("/api/v1/goals/<rid>/publish", methods=["POST"])
def publish_goal(rid):
    caller = authorized(ADMIN)
    goal = get_resource("goals", rid)
    if goal["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "publish requires status DRAFT")
    if caller.user_id == goal["created_by_user_id"]:
        raise_error(ERR_SOD_VIOLATION, "publisher must differ from goal creator")
    # At most one PUBLISHED goal per (business_unit, cert_category, fiscal_year).
    for other in db["goals"].values():
        if (other["id"] != goal["id"]
                and other["status"] == "PUBLISHED"
                and _same_key(other, goal["business_unit_id"],
                              goal["cert_category"], goal["fiscal_year"])):
            other["status"] = "SUPERSEDED"
            touch(other)
    goal["status"] = "PUBLISHED"
    touch(goal)
    return success_object(pub_goal(goal))
