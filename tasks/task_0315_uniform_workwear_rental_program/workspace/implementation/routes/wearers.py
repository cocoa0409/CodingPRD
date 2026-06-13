"""Wearer endpoints and ramp lifecycle (PRD §3.2)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_role, require_role, parse_pagination, paginate
from response import object_response, array_response
from services.common import make_record, touch, public_view, sort_by_created
from services.ledger import recompute_account
from services import validate

bp = Blueprint("wearers", __name__)


def _ensure_account(account_id):
    acct = db.accounts.get(account_id)
    if acct is None:
        raise errors.not_found("Account not found.")
    return acct


def _ensure_wearer(wearer_id):
    w = db.wearers.get(wearer_id)
    if w is None:
        raise errors.not_found("Wearer not found.")
    return w


@bp.route("/accounts/<account_id>/wearers", methods=["POST"])
def add_wearer(account_id):
    role = get_role()
    require_role(role, {"AccountManager"})
    acct = _ensure_account(account_id)
    body = validate.get_body()

    full_name = validate.require_str(body, "full_name")
    shirt_size = validate.require_enum(body, "shirt_size", validate.SHIRT_SIZES)
    pant_size = validate.require_int(body, "pant_size", minimum=28, maximum=48)
    locker_label = validate.require_str(body, "locker_label")

    # locker_label unique among non-REMOVED wearers within the account.
    for w in db.wearers.values():
        if (
            w["account_id"] == account_id
            and w["roster_status"] != "REMOVED"
            and w["locker_label"] == locker_label
        ):
            raise errors.duplicate_key("locker_label already in use for this account.")

    wearer = make_record("wearers", {
        "account_id": account_id,
        "full_name": full_name,
        "shirt_size": shirt_size,
        "pant_size": pant_size,
        "locker_label": locker_label,
        "roster_status": "ACTIVE",
        "assigned_garment_count": 0,
    })
    recompute_account(acct)
    return object_response(public_view(wearer), 201)


@bp.route("/accounts/<account_id>/wearers", methods=["GET"])
def list_wearers(account_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    _ensure_account(account_id)
    limit, offset = parse_pagination()
    roster_status = request.args.get("roster_status")

    rows = [w for w in db.wearers.values() if w["account_id"] == account_id]
    if roster_status is not None:
        rows = [w for w in rows if w["roster_status"] == roster_status]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([public_view(w) for w in page], limit, offset, total)


@bp.route("/wearers/<wearer_id>", methods=["GET"])
def get_wearer(wearer_id):
    role = get_role()
    require_role(role, {"ProgramAdmin", "AccountManager"})
    w = _ensure_wearer(wearer_id)
    return object_response(public_view(w), 200)


@bp.route("/wearers/<wearer_id>/ramp-down", methods=["POST"])
def ramp_down(wearer_id):
    role = get_role()
    require_role(role, {"AccountManager"})
    w = _ensure_wearer(wearer_id)
    acct = db.accounts[w["account_id"]]
    # priority 5 (state) before priority 6 (account on hold).
    if w["roster_status"] != "ACTIVE":
        raise errors.invalid_state("ramp-down requires an ACTIVE wearer.")
    if acct["billing_status"] == "ON_HOLD":
        raise errors.account_on_hold()
    w["roster_status"] = "RAMP_DOWN"
    touch(w)
    recompute_account(acct)
    return object_response(public_view(w), 200)


@bp.route("/wearers/<wearer_id>/reinstate", methods=["POST"])
def reinstate(wearer_id):
    role = get_role()
    require_role(role, {"AccountManager"})
    w = _ensure_wearer(wearer_id)
    acct = db.accounts[w["account_id"]]
    if w["roster_status"] != "RAMP_DOWN":
        raise errors.invalid_state("reinstate requires a RAMP_DOWN wearer.")
    if acct["billing_status"] == "ON_HOLD":
        raise errors.account_on_hold()
    w["roster_status"] = "ACTIVE"
    touch(w)
    recompute_account(acct)
    return object_response(public_view(w), 200)


@bp.route("/wearers/<wearer_id>/remove", methods=["POST"])
def remove(wearer_id):
    role = get_role()
    require_role(role, {"AccountManager"})
    w = _ensure_wearer(wearer_id)
    acct = db.accounts[w["account_id"]]
    # priority 5 (state) before priority 8 (wearer-has-garments).
    if w["roster_status"] != "RAMP_DOWN":
        raise errors.invalid_state("remove requires a RAMP_DOWN wearer.")
    if w["assigned_garment_count"] > 0:
        raise errors.wearer_has_garments()
    w["roster_status"] = "REMOVED"
    touch(w)
    recompute_account(acct)
    return object_response(public_view(w), 200)
