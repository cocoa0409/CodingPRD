"""Exhibitor accounts and the priority-point ledger (PRD 3.3)."""
from flask import Blueprint

import guards
import validate
import views
from db import base_row, db, touch
from middleware import (EXHIBITOR, FLOOR_MANAGER, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, object_response

bp = Blueprint("exhibitors", __name__)


@bp.route("/exhibitors", methods=["POST"])
def create_exhibitor():
    body = validate.body()
    legal_name = validate.text(body, "legal_name", 1, 160)
    contact_email = validate.email(body, "contact_email")
    consecutive_years = validate.integer(body, "consecutive_years", minimum=0,
                                        required=False, default=0)

    authenticate((SHOW_DIRECTOR, SALES_REP))

    folded = legal_name.casefold()
    for other in db.exhibitors.values():
        if other["legal_name"].casefold() == folded:
            validate.bad("legal_name must be unique across exhibitors")

    row = base_row()
    row.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "consecutive_years": consecutive_years,
        "status": "ACTIVE",
        "ledger_points": 0,
        "sponsorship_fulfillment_points": 0,
        "penalty_points": 0,
    })
    db.exhibitors[row["id"]] = row
    return created(views.exhibitor_view(row))


@bp.route("/exhibitors/<exhibitor_id>", methods=["GET"])
def read_exhibitor(exhibitor_id):
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    exhibitor = guards.get_exhibitor(exhibitor_id)
    return object_response(views.exhibitor_view(exhibitor))


@bp.route("/exhibitors/<exhibitor_id>/priority-point-adjustments", methods=["POST"])
def adjust_points(exhibitor_id):
    body = validate.body()
    points_delta = validate.integer(body, "points_delta")
    reason = validate.text(body, "reason", 1, 500)

    authenticate((SHOW_DIRECTOR,))
    exhibitor = guards.get_exhibitor(exhibitor_id)

    exhibitor["ledger_points"] += points_delta
    exhibitor["last_adjustment_reason"] = reason
    touch(exhibitor)
    return object_response(views.exhibitor_view(exhibitor))


@bp.route("/exhibitors/<exhibitor_id>/reinstate", methods=["POST"])
def reinstate_exhibitor(exhibitor_id):
    body = validate.body()
    reason = validate.text(body, "reason", 1, 500)

    authenticate((SHOW_DIRECTOR,))
    exhibitor = guards.get_exhibitor(exhibitor_id)

    exhibitor["status"] = "ACTIVE"
    exhibitor["penalty_points"] = 0
    exhibitor["reinstatement_reason"] = reason
    touch(exhibitor)
    return object_response(views.exhibitor_view(exhibitor))
