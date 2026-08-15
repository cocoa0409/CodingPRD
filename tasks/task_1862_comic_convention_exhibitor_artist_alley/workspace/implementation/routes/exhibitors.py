"""Exhibitor routes."""

from flask import Blueprint

import db
from errors import fail
from helpers import get_json_body, require_str, opt_int, require_enum, get_or_404
from middleware import require_roles
from response import success_object
from services import calc

bp = Blueprint("exhibitors", __name__)

CATEGORIES = ("ARTIST_ALLEY", "DEALER", "PUBLISHER", "STUDIO", "NONPROFIT")


def exhibitor_view(e):
    return {k: e[k] for k in (
        "id", "legal_name", "category", "prior_years_completed",
        "prior_on_time_payments", "strike_points", "standing",
        "renewal_priority_score", "created_at", "updated_at", "version")}


@bp.route("/exhibitors", methods=["POST"])
def create_exhibitor():
    # Anonymous self-registration: still requires headers per validation
    # priority 1 (X-User-Role may be Anonymous).
    require_roles("Anonymous")
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    category = require_enum(body, "category", CATEGORIES)
    prior_years = opt_int(body, "prior_years_completed", minimum=0)
    prior_payments = opt_int(body, "prior_on_time_payments", minimum=0)
    e = {
        "id": db.new_id(),
        "legal_name": legal_name,
        "category": category,
        "prior_years_completed": prior_years if prior_years is not None else 0,
        "prior_on_time_payments": prior_payments if prior_payments is not None else 0,
        "strike_points": 0,
        "standing": "GOOD",
        "renewal_priority_score": 0,
    }
    db.stamp_created(e)
    e["renewal_priority_score"] = calc.renewal_priority_score(e)
    db.exhibitors[e["id"]] = e
    return success_object(exhibitor_view(e), 201)


@bp.route("/exhibitors/<exhibitorId>", methods=["GET"])
def get_exhibitor(exhibitorId):
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    e = get_or_404(db.exhibitors, exhibitorId)
    if role == "Exhibitor" and user_id != exhibitorId:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "Exhibitor role may read only its own record")
    return success_object(exhibitor_view(e), 200)
