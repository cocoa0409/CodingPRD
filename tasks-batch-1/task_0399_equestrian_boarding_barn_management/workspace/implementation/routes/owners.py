"""Owner, deposit, and waiver routes (PRD §3.1, §3.4)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from clock import parse_iso, add_days, format_iso
from services.common import (
    new_common, touch, require_str, require_int, parse_pagination, paginate,
    sort_by_created,
)
from services.serialize import view, view_list
from services.lookups import get_owner, get_waiver, require_owner_owns
from services.standing import compute_provisional, recompute_committed, SUSPEND_SCORE
from services.cascades import waiver_expiry_cascade, waiver_resign_cascade

bp = Blueprint("owners", __name__)

WAIVER_VALIDITY_DAYS = 365


# ---- Owner ----

@bp.route("/owners", methods=["POST"])
def create_owner():
    caller = get_caller()
    require_role(caller, ["BarnManager"])
    body = request.get_json(silent=True) or {}
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    # email unique across owners (PRD §3.1)
    for o in db.owners.values():
        if o["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique across owners")
    owner = new_common()
    owner.update({
        "full_name": full_name,
        "email": email,
        "deposit_held_cents": 0,
        "account_balance_cents": 0,
        "standing_score": 0,
        "provisional_standing_score": 0,
        "status": "ACTIVE",
    })
    db.owners[owner["id"]] = owner
    return success(view(owner), 201)


@bp.route("/owners/<owner_id>", methods=["GET"])
def get_owner_route(owner_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    owner = get_owner(owner_id)
    require_owner_owns(caller, owner["id"])
    # recompute provisional_standing_score without persisting committed fields,
    # but the recompute is itself a mutation of the owner (PRD §2.4, §3.1)
    owner["provisional_standing_score"] = compute_provisional(owner)
    touch(owner)
    return success(view(owner), 200)


@bp.route("/owners/<owner_id>/deposit", methods=["POST"])
def adjust_deposit(owner_id):
    caller = get_caller()
    require_role(caller, ["BarnManager"])
    owner = get_owner(owner_id)
    body = request.get_json(silent=True) or {}
    amount = require_int(body, "amount_cents")
    new_held = owner["deposit_held_cents"] + amount
    if new_held < 0:
        raise err("ERR_INSUFFICIENT_DEPOSIT", "Deposit may not be driven below zero")
    owner["deposit_held_cents"] = new_held
    touch(owner)
    return success(view(owner), 200)


# ---- LiabilityWaiver ----

@bp.route("/owners/<owner_id>/waivers", methods=["POST"])
def create_waiver(owner_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    owner = get_owner(owner_id)
    require_owner_owns(caller, owner["id"])
    waiver = new_common()
    waiver.update({
        "owner_id": owner["id"],
        "signed_at": None,
        "expires_at": None,
        "superseded_by_id": None,
        "status": "PENDING",
    })
    # supersede any existing SIGNED waiver of this owner (PRD §3.4)
    for w in db.waivers.values():
        if w["owner_id"] == owner["id"] and w["status"] == "SIGNED":
            w["superseded_by_id"] = waiver["id"]
            w["status"] = "SUPERSEDED"
            touch(w)
    db.waivers[waiver["id"]] = waiver
    return success(view(waiver), 201)


def _fire_lazy_expiry(owner):
    """Lazily expire SIGNED waivers whose clock now >= expires_at, with cascade.
    Realized when the owner's waiver list is read (PRD §3.4, §2.11)."""
    now = db.clock.now
    for w in db.waivers.values():
        if w["owner_id"] != owner["id"]:
            continue
        if w["status"] != "SIGNED":
            continue
        if not w["expires_at"]:
            continue
        if now >= parse_iso(w["expires_at"]):
            w["status"] = "EXPIRED"
            touch(w)
            waiver_expiry_cascade(owner)


@bp.route("/owners/<owner_id>/waivers", methods=["GET"])
def list_waivers(owner_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    owner = get_owner(owner_id)
    require_owner_owns(caller, owner["id"])
    # lazy expiry + suspension cascade BEFORE the list is returned (PRD §3.4)
    _fire_lazy_expiry(owner)
    limit, offset = parse_pagination(request.args)
    items = [w for w in db.waivers.values() if w["owner_id"] == owner["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.route("/owners/<owner_id>/waivers/<waiver_id>/sign", methods=["POST"])
def sign_waiver(owner_id, waiver_id):
    caller = get_caller()
    require_role(caller, ["Owner"])
    owner = get_owner(owner_id)
    require_owner_owns(caller, owner["id"])
    waiver = get_waiver(waiver_id)
    if waiver["owner_id"] != owner["id"]:
        raise err("ERR_WAIVER_NOT_FOUND", "Waiver not found for this owner")
    if waiver["status"] not in ("PENDING", "EXPIRED"):
        raise err("ERR_WAIVER_NOT_SIGNABLE", "Waiver is not in PENDING or EXPIRED")
    was_expired = waiver["status"] == "EXPIRED"
    now = db.clock.now
    waiver["signed_at"] = format_iso(now)
    waiver["expires_at"] = format_iso(add_days(now, WAIVER_VALIDITY_DAYS))
    waiver["status"] = "SIGNED"
    touch(waiver)
    # re-sign of an EXPIRED waiver carries the reinstate cascade (PRD §3.4)
    if was_expired:
        waiver_resign_cascade(owner)
    return success(view(waiver), 200)
