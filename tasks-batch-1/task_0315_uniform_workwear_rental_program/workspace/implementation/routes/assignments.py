"""Assignment junction endpoints (PRD §3.4)."""
from flask import Blueprint, request

import errors
from db import db, now_iso
from middleware import get_role, require_role, parse_pagination, paginate
from response import object_response, array_response
from services.common import make_record, touch, public_view, sort_by_created
from services.ledger import (
    recompute_account, create_charge, loss_fee, damage_fee,
)
from services import validate

bp = Blueprint("assignments", __name__)


def _ensure_assignment(assignment_id):
    a = db.assignments.get(assignment_id)
    if a is None:
        raise errors.not_found("Assignment not found.")
    return a


@bp.route("/assignments", methods=["POST"])
def create_assignment():
    role = get_role()
    require_role(role, {"AccountManager"})
    body = validate.get_body()

    garment_id = validate.require_str(body, "garment_id")
    wearer_id = validate.require_str(body, "wearer_id")

    # priority 4: FK integrity. Both must resolve; and garment+wearer must
    # belong to the same account.
    garment = db.garments.get(garment_id)
    wearer = db.wearers.get(wearer_id)
    if garment is None or wearer is None:
        raise errors.fk_integrity("garment_id or wearer_id does not resolve.")
    if garment["account_id"] != wearer["account_id"]:
        raise errors.fk_integrity("garment and wearer belong to different accounts.")

    account = db.accounts[garment["account_id"]]

    # priority 5: state legality of garment (IN_STOCK + AT_PLANT).
    if not (garment["lifecycle_status"] == "IN_STOCK" and garment["wash_location"] == "AT_PLANT"):
        raise errors.invalid_state("garment is not assignable.")

    # priority 6: account on hold.
    if account["billing_status"] == "ON_HOLD":
        raise errors.account_on_hold()

    # priority 7: wearer must be ACTIVE.
    if wearer["roster_status"] != "ACTIVE":
        raise errors.wearer_not_active()

    assignment = make_record("assignments", {
        "garment_id": garment_id,
        "wearer_id": wearer_id,
        "account_id": garment["account_id"],
        "status": "ASSIGNED",
        "assigned_at_iso": now_iso(),
        "closed_at_iso": None,
    })

    # Garment IN_STOCK->ASSIGNED + AT_PLANT->AT_CUSTOMER, one version bump.
    garment["lifecycle_status"] = "ASSIGNED"
    garment["wash_location"] = "AT_CUSTOMER"
    touch(garment)

    # Wearer assigned_garment_count++.
    wearer["assigned_garment_count"] += 1
    touch(wearer)

    return object_response(public_view(assignment), 201)


@bp.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    a = _ensure_assignment(assignment_id)
    return object_response(public_view(a), 200)


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    limit, offset = parse_pagination()
    garment_id = request.args.get("garment_id")
    wearer_id = request.args.get("wearer_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")

    rows = list(db.assignments.values())
    if garment_id is not None:
        rows = [a for a in rows if a["garment_id"] == garment_id]
    if wearer_id is not None:
        rows = [a for a in rows if a["wearer_id"] == wearer_id]
    if account_id is not None:
        rows = [a for a in rows if a["account_id"] == account_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(a) for a in page], limit, offset, total)


def _terminal_preconditions(a):
    """Shared state gate for return/loss/damage (priority 5)."""
    if a["status"] != "ASSIGNED":
        raise errors.invalid_state("assignment is not ASSIGNED.")
    garment = db.garments.get(a["garment_id"])
    if garment is None or garment["lifecycle_status"] != "ASSIGNED":
        raise errors.invalid_state("linked garment is not ASSIGNED.")
    return garment


@bp.route("/assignments/<assignment_id>/return", methods=["POST"])
def return_assignment(assignment_id):
    role = get_role()
    require_role(role, {"AccountManager"})
    a = _ensure_assignment(assignment_id)
    garment = _terminal_preconditions(a)

    a["status"] = "RETURNED"
    a["closed_at_iso"] = now_iso()
    touch(a)

    # Garment ASSIGNED->IN_STOCK, wash_location back to AT_PLANT.
    garment["lifecycle_status"] = "IN_STOCK"
    garment["wash_location"] = "AT_PLANT"
    touch(garment)

    wearer = db.wearers.get(a["wearer_id"])
    if wearer is not None:
        wearer["assigned_garment_count"] -= 1
        touch(wearer)

    return object_response(public_view(a), 200)


@bp.route("/assignments/<assignment_id>/declare-loss", methods=["POST"])
def declare_loss(assignment_id):
    role = get_role()
    require_role(role, {"AccountManager"})
    a = _ensure_assignment(assignment_id)
    garment = _terminal_preconditions(a)

    a["status"] = "LOST"
    a["closed_at_iso"] = now_iso()
    touch(a)

    garment["lifecycle_status"] = "LOST"
    touch(garment)

    gt = db.garment_types[garment["garment_type_id"]]
    create_charge(None, a["account_id"], "LOSS", loss_fee(gt))

    wearer = db.wearers.get(a["wearer_id"])
    if wearer is not None:
        wearer["assigned_garment_count"] -= 1
        touch(wearer)

    account = db.accounts[a["account_id"]]
    recompute_account(account)

    return object_response(public_view(a), 200)


@bp.route("/assignments/<assignment_id>/declare-damage", methods=["POST"])
def declare_damage(assignment_id):
    role = get_role()
    require_role(role, {"AccountManager"})
    a = _ensure_assignment(assignment_id)
    garment = _terminal_preconditions(a)

    a["status"] = "DAMAGED"
    a["closed_at_iso"] = now_iso()
    touch(a)

    gt = db.garment_types[garment["garment_type_id"]]
    fee = damage_fee(garment, gt)  # compute before lifecycle change (uses soil_strikes)

    garment["lifecycle_status"] = "RETIRED"
    touch(garment)

    create_charge(None, a["account_id"], "DAMAGE", fee)

    wearer = db.wearers.get(a["wearer_id"])
    if wearer is not None:
        wearer["assigned_garment_count"] -= 1
        touch(wearer)

    account = db.accounts[a["account_id"]]
    recompute_account(account)

    return object_response(public_view(a), 200)
