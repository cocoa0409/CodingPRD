"""Exhibitor accounts and the suspension chain (PRD §3.2)."""
from flask import Blueprint

import db
import guards
import response
from middleware import ANY_ROLE, own_exhibitor, require_roles
from services import state
from validation import json_body, require_row

bp = Blueprint("exhibitors", __name__)
store = db.store


@bp.post("/exhibitors")
def create_exhibitor():
    require_roles("ShowOperations", "FinanceController")
    body = json_body()
    company_name = body.string("company_name")
    contact_email = body.string("contact_email")
    credit_limit = body.integer("credit_limit_cents", required=False, default=500000)

    exhibitor = {
        "id": db.new_id(),
        "company_name": company_name,
        "contact_email": contact_email,
        "credit_limit_cents": credit_limit,
        "account_balance_cents": 0,
        "status": "ACTIVE",
        "suspension_reason": None,
    }
    db.stamp_common(exhibitor)
    store.exhibitors[exhibitor["id"]] = exhibitor
    return response.created(exhibitor)


@bp.get("/exhibitors/<exhibitor_id>")
def get_exhibitor(exhibitor_id):
    require_roles(ANY_ROLE)
    own_exhibitor(exhibitor_id)
    exhibitor = require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND",
                            "Exhibitor")
    return response.ok(exhibitor)


@bp.post("/exhibitors/<exhibitor_id>/status")
def set_status(exhibitor_id):
    require_roles("FinanceController")
    body = json_body()
    to_status = body.enum("to_status", ("ACTIVE", "SUSPENDED"))
    reason = body.string("reason", required=False, default=None)
    exhibitor = require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND",
                            "Exhibitor")

    allowed_from = ("ACTIVE",) if to_status == "SUSPENDED" else ("SUSPENDED",)
    guards.transition(exhibitor["status"], (), allowed_from)

    exhibitor["status"] = to_status
    if to_status == "SUSPENDED":
        exhibitor["suspension_reason"] = reason
    db.touch(exhibitor)

    # Suspension freezes every booth the exhibitor holds, which holds its pending
    # orders, which cancels their requested labor calls. Reinstatement walks back
    # only as far as posture and the held orders.
    state.refresh_exhibitor_booths(exhibitor_id)
    return response.ok(exhibitor)
