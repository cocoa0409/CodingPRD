"""Inter-library loan endpoints (PRD §3.8)."""

from flask import Blueprint, request

import clock
import db
import errors
import response
from middleware import (
    authenticate, require_roles, require_owner_if_patron,
    ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER,
)
from services import serialize, derive
from routes import helpers

bp = Blueprint("ill_requests", __name__)

ILL_STATUSES = {"REQUESTED", "APPROVED", "SHIPPED", "RECEIVED", "RETURNED", "DENIED"}
ILL_ACTIONS = {"approve", "deny", "ship", "receive", "return"}


@bp.post("/library/ill-requests")
def create_ill():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["patron_id", "branch_id", "isbn"])
    patron_id = helpers.require_string(body, "patron_id")
    branch_id = helpers.require_string(body, "branch_id")
    isbn = helpers.require_string(body, "isbn")

    # existence (priority 3), left-to-right: patron then branch
    patron = helpers.find_or_404(db.patrons, patron_id)
    helpers.find_or_404(db.branches, branch_id)

    # ownership (priority 2): a Patron may only submit for themselves
    require_owner_if_patron(caller, patron_id)

    # priority 7: card ACTIVE (an ILL request requires an active card per §2.8)
    if patron["card_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_CARD_NOT_ACTIVE, 409, "Patron card is not ACTIVE.")

    record = {
        "patron_id": patron_id,
        "branch_id": branch_id,
        "isbn": isbn,
        "status": "REQUESTED",
        "lending_fee_cents": helpers.optional_int(body, "lending_fee_cents", 500),
    }
    db.stamp_create(record)
    db.ill_requests[record["id"]] = record
    return response.object_response(serialize.ill_request(record), status=201)


@bp.get("/library/ill-requests/<iid>")
def get_ill(iid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.ill_requests, iid)
    return response.object_response(serialize.ill_request(record))


@bp.get("/library/ill-requests")
def list_ill():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    patron_id = request.args.get("patron_id")
    branch_id = request.args.get("branch_id")
    status = helpers.enum_filter("status", ILL_STATUSES)
    records = [
        r for r in db.ill_requests.values()
        if (patron_id is None or r["patron_id"] == patron_id)
        and (branch_id is None or r["branch_id"] == branch_id)
        and (status is None or r["status"] == status)
    ]
    return helpers.list_response(records, serialize.ill_request)


# action -> (required source state, target state)
_TRANSITIONS = {
    "approve": ("REQUESTED", "APPROVED"),
    "deny": ("REQUESTED", "DENIED"),
    "ship": ("APPROVED", "SHIPPED"),
    "receive": ("SHIPPED", "RECEIVED"),
    "return": ("RECEIVED", "RETURNED"),
}


@bp.post("/library/ill-requests/<iid>/transition")
def transition(iid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    record = helpers.find_or_404(db.ill_requests, iid)
    body = helpers.get_json_body()

    helpers.require_fields(body, ["action"])
    action = body["action"]
    # Unknown action verb (priority 4 well-formedness) -> ERR_INVALID_ACTION
    if action not in ILL_ACTIONS:
        raise errors.invalid_action(f"Unknown ILL action: {action!r}")

    source, target = _TRANSITIONS[action]

    # state (priority 5)
    if record["status"] != source:
        raise errors.invalid_state(f"ILL request is not in state {source}.")

    # approve requires the patron CLEAR (cross-entity)
    if action == "approve":
        patron = db.patrons.get(record["patron_id"])
        if patron is not None:
            derive.reconcile_patron(patron)
            if patron["borrowing_status"] != "CLEAR":
                raise errors.ApiError(errors.ERR_PATRON_BLOCKED, 409, "Patron is BLOCKED.")

    record["status"] = target

    # receive side effect: create ILL_FEE fine -> recompute patron balance
    if action == "receive":
        fine = {
            "patron_id": record["patron_id"],
            "loan_id": None,
            "fine_type": "ILL_FEE",
            "amount_cents": record["lending_fee_cents"],
            "settlement_status": "UNPAID",
            "settled_at": None,
        }
        db.stamp_create(fine)
        db.fines[fine["id"]] = fine
        db.touch(record)
        derive.reconcile_patron_by_id(record["patron_id"])
    else:
        db.touch(record)

    return response.object_response(serialize.ill_request(record))
