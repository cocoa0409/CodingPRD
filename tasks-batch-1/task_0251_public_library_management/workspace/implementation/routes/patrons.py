"""Patron endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db
import response
from middleware import authenticate, require_roles, ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER
from services import serialize, derive, calc
from routes import helpers

bp = Blueprint("patrons", __name__)

PATRON_TYPES = {"ADULT", "JUVENILE", "STAFF"}
CARD_STATUSES = {"ACTIVE", "SUSPENDED", "EXPIRED"}


@bp.post("/library/patrons")
def create_patron():
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN, ROLE_MANAGER})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["branch_id", "full_name"])
    branch_id = helpers.require_string(body, "branch_id")
    full_name = helpers.require_string(body, "full_name")
    patron_type = helpers.enum_value(body, "patron_type", PATRON_TYPES, default="ADULT")

    # existence (priority 3): branch FK must resolve
    helpers.find_or_404(db.branches, branch_id)

    record = {
        "branch_id": branch_id,
        "full_name": full_name,
        "patron_type": patron_type,
        "card_status": "ACTIVE",
        "borrowing_status": "CLEAR",
        "checkout_limit": helpers.optional_int(body, "checkout_limit", 20),
        "hold_limit": helpers.optional_int(body, "hold_limit", 10),
        "active_loan_count": 0,
        "active_hold_count": 0,
        "total_owed_cents": 0,
        "ready_pickup_count": 0,
    }
    db.stamp_create(record)
    db.patrons[record["id"]] = record
    return response.object_response(serialize.patron(record), status=201)


@bp.get("/library/patrons/<pid>")
def get_patron(pid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.patrons, pid)
    derive.reconcile_patron(record)
    return response.object_response(serialize.patron(record))


@bp.get("/library/patrons")
def list_patrons():
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN, ROLE_MANAGER})
    branch_id = request.args.get("branch_id")
    records = [
        p for p in db.patrons.values()
        if branch_id is None or p["branch_id"] == branch_id
    ]
    for p in records:
        derive.reconcile_patron(p)
    return helpers.list_response(records, serialize.patron)


@bp.post("/library/patrons/<pid>/set-card-status")
def set_card_status(pid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.patrons, pid)
    body = helpers.get_json_body()
    new_status = helpers.enum_value(body, "card_status", CARD_STATUSES, required=True)
    record["card_status"] = new_status
    db.touch(record)
    derive.reconcile_patron(record)
    return response.object_response(serialize.patron(record))


@bp.get("/library/patrons/<pid>/account-summary")
def account_summary(pid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.patrons, pid)
    summary = calc.account_summary(record)
    return response.object_response(summary)
