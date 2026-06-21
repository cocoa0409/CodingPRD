"""Hold endpoints (PRD §3.6: holds queue & promotion loop)."""

from flask import Blueprint, request

import clock
import db
import errors
import response
from constants import PICKUP_WINDOW_DAYS
from middleware import (
    authenticate, require_roles, require_owner_if_patron,
    ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER,
)
from services import serialize, derive, loans as loan_svc, cascade
from routes import helpers
from timeutil import add_days

bp = Blueprint("holds", __name__)

HOLD_STATUSES = {"WAITING", "READY", "FULFILLED", "CANCELLED", "EXPIRED"}


def _branch_for_patron(patron):
    return db.branches.get(patron["branch_id"])


@bp.post("/library/holds")
def place_hold():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["title_id", "patron_id"])
    title_id = helpers.require_string(body, "title_id")
    patron_id = helpers.require_string(body, "patron_id")

    # existence (priority 3), left-to-right: title then patron
    title = helpers.find_or_404(db.titles, title_id)
    patron = helpers.find_or_404(db.patrons, patron_id)

    # ownership (priority 2): a Patron may only place a hold for themselves
    require_owner_if_patron(caller, patron_id)

    # priority 6: title must not be WITHDRAWN
    if title["status"] == "WITHDRAWN":
        raise errors.ApiError(errors.ERR_TITLE_WITHDRAWN, 409, "Title is WITHDRAWN.")

    # priority 7: card ACTIVE
    if patron["card_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_CARD_NOT_ACTIVE, 409, "Patron card is not ACTIVE.")

    # priority 8: patron CLEAR
    derive.reconcile_patron(patron)
    if patron["borrowing_status"] == "BLOCKED":
        raise errors.ApiError(errors.ERR_PATRON_BLOCKED, 409, "Patron is BLOCKED.")

    # priority 10: hold_limit not exceeded
    open_holds = sum(
        1 for h in db.holds.values()
        if h["patron_id"] == patron_id and h["status"] in ("WAITING", "READY")
    )
    if open_holds >= patron["hold_limit"]:
        raise errors.ApiError(errors.ERR_LIMIT_EXCEEDED, 409, "hold_limit exceeded.")

    record = {
        "title_id": title_id,
        "patron_id": patron_id,
        "status": "WAITING",
        "ready_copy_id": None,
        "ready_at": None,
    }
    db.stamp_create(record)
    db.holds[record["id"]] = record

    derive.reconcile_title(title)
    derive.reconcile_patron(patron)
    return response.object_response(serialize.hold(record), status=201)


@bp.get("/library/holds/<hid>")
def get_hold(hid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.holds, hid)
    return response.object_response(serialize.hold(record))


@bp.get("/library/holds")
def list_holds():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    title_id = request.args.get("title_id")
    patron_id = request.args.get("patron_id")
    ready_copy_id = request.args.get("ready_copy_id")
    status = helpers.enum_filter("status", HOLD_STATUSES)
    records = [
        h for h in db.holds.values()
        if (title_id is None or h["title_id"] == title_id)
        and (patron_id is None or h["patron_id"] == patron_id)
        and (ready_copy_id is None or h.get("ready_copy_id") == ready_copy_id)
        and (status is None or h["status"] == status)
    ]
    return helpers.list_response(records, serialize.hold)


@bp.post("/library/holds/<hid>/checkout")
def checkout_hold(hid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    hold = helpers.find_or_404(db.holds, hid)

    # state (priority 5): must be READY
    if hold["status"] != "READY":
        raise errors.ApiError(errors.ERR_HOLD_NOT_READY, 409, "Hold is not READY.")

    now = clock.now()
    deadline = add_days(hold["ready_at"], PICKUP_WINDOW_DAYS)
    if now > deadline:
        raise errors.ApiError(errors.ERR_PICKUP_EXPIRED, 409, "Pickup window has expired.")

    copy = db.copies.get(hold["ready_copy_id"])
    patron = db.patrons.get(hold["patron_id"])
    branch = _branch_for_patron(patron) if patron else None

    # Fulfil: hold READY -> FULFILLED; create loan on ready_copy_id
    hold["status"] = "FULFILLED"
    db.touch(hold)

    # copy ON_HOLD_SHELF -> ON_LOAN handled by create_loan (sets ON_LOAN)
    loan_svc.create_loan(copy, patron, branch)

    if copy is not None:
        derive.reconcile_title_by_id(copy["title_id"])
    derive.reconcile_patron_by_id(hold["patron_id"])
    return response.object_response(serialize.hold(hold))


@bp.post("/library/holds/<hid>/expire-ready")
def expire_ready(hid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    hold = helpers.find_or_404(db.holds, hid)

    # state (priority 5): must be READY
    if hold["status"] != "READY":
        raise errors.invalid_state("Hold is not READY.")

    now = clock.now()
    deadline = add_days(hold["ready_at"], PICKUP_WINDOW_DAYS)
    if not (now > deadline):
        raise errors.ApiError(errors.ERR_NOT_YET_DUE, 409, "Pickup window has not yet passed.")

    copy = db.copies.get(hold["ready_copy_id"])
    patron_id = hold["patron_id"]

    hold["status"] = "EXPIRED"
    hold["ready_copy_id"] = None
    db.touch(hold)

    # Release the reserved copy; promotion loop re-fires.
    if copy is not None:
        copy["status"] = "AVAILABLE"
        db.touch(copy)
        promoted = cascade.promote_head_hold_for_title(copy["title_id"], copy)
        derive.reconcile_title_by_id(copy["title_id"])

    derive.reconcile_patron_by_id(patron_id)
    return response.object_response(serialize.hold(hold))


@bp.post("/library/holds/<hid>/cancel")
def cancel_hold(hid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN})
    hold = helpers.find_or_404(db.holds, hid)

    # ownership (priority 2)
    require_owner_if_patron(caller, hold["patron_id"])

    # state (priority 5): WAITING or READY
    if hold["status"] not in ("WAITING", "READY"):
        raise errors.invalid_state("Hold is not WAITING or READY.")

    was_ready = hold["status"] == "READY"
    copy = db.copies.get(hold["ready_copy_id"]) if hold.get("ready_copy_id") else None
    title_id = hold["title_id"]
    patron_id = hold["patron_id"]

    hold["status"] = "CANCELLED"
    hold["ready_copy_id"] = None
    db.touch(hold)

    if was_ready and copy is not None:
        copy["status"] = "AVAILABLE"
        db.touch(copy)
        cascade.promote_head_hold_for_title(copy["title_id"], copy)

    derive.reconcile_title_by_id(title_id)
    derive.reconcile_patron_by_id(patron_id)
    return response.object_response(serialize.hold(hold))
