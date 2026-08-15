"""Payer endpoints."""
from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.common import init_common
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_string,
    validate_int, validate_bool,
)

bp = Blueprint("payers", __name__)

PLAN_CLASSES = {"MEDICARE", "MANAGED_MEDICARE", "MEDICAID", "COMMERCIAL"}
ATTRIBUTION_METHODS = {"FIRST_CAUSE", "DOMINANT_CAUSE"}

PAYER_FIELDS = [
    "name", "plan_class", "requires_inpatient_auth",
    "concurrent_review_cadence_hours", "p2p_window_hours",
    "appeal_deadline_days", "bed_day_budget_per_case",
    "avoidable_attribution_method",
]


@bp.post("/api/payers")
def create_payer():
    require_roles(["URDirector"])
    body = get_json_body()
    reject_unknown_fields(body, PAYER_FIELDS)
    validate_string(body, "name")
    validate_enum(body, "plan_class", PLAN_CLASSES)
    validate_bool(body, "requires_inpatient_auth", required=False)
    validate_int(body, "concurrent_review_cadence_hours", min_val=1)
    validate_int(body, "p2p_window_hours", min_val=1)
    validate_int(body, "appeal_deadline_days", min_val=1)
    validate_int(body, "bed_day_budget_per_case", min_val=1)
    validate_enum(body, "avoidable_attribution_method", ATTRIBUTION_METHODS)

    payer = {
        **init_common(),
        "name": body["name"],
        "plan_class": body["plan_class"],
        "requires_inpatient_auth": body.get("requires_inpatient_auth", True),
        "concurrent_review_cadence_hours": body["concurrent_review_cadence_hours"],
        "p2p_window_hours": body["p2p_window_hours"],
        "appeal_deadline_days": body["appeal_deadline_days"],
        "bed_day_budget_per_case": body["bed_day_budget_per_case"],
        "avoidable_attribution_method": body["avoidable_attribution_method"],
    }
    db.payers[payer["id"]] = payer
    return success_object(payer, 201)


@bp.get("/api/payers")
def list_payers():
    any_authenticated()
    items = sorted(db.payers.values(), key=lambda p: p["created_at"])
    plan_class = None
    from flask import request
    if "plan_class" in request.args:
        plan_class = request.args["plan_class"]
        if plan_class not in PLAN_CLASSES:
            from errors import ApiError, ERR_VALIDATION_FAILED
            raise ApiError(ERR_VALIDATION_FAILED, f"Invalid plan_class: {plan_class}", 400)
        items = [p for p in items if p["plan_class"] == plan_class]
    return paginate(items)


@bp.get("/api/payers/<pid>")
def get_payer(pid):
    any_authenticated()
    return success_object(lookup(db.payers, pid, "Payer"))
