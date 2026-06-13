"""AuthorizationHold create/read/list/release (PRD §3.4)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db
from core import (
    get_body, stamp_new, touch, paginate, now_iso,
    check_str, check_int, parse_iso,
)
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_hold, get_card
import serialize

bp = Blueprint("holds", __name__)


@bp.post("/v1/holds")
def create_hold():
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate"})
    body = get_body()
    card_id = check_str(body, "card_id")
    amount = check_int(body, "amount_cents")

    # Body FK existence (priority 5).
    if card_id not in db.cards:
        raise err("ERR_REFERENCE_NOT_FOUND", "card_id does not exist.")
    card = db.cards[card_id]
    # Domain shape (priority 6): amount must be > 0.
    if amount <= 0:
        raise err("ERR_INVALID_REDEMPTION", "amount_cents must be positive.")
    # Risk gate (priority 9): no new hold on a FROZEN_RISK card.
    if card["risk_status"] == "FROZEN_RISK":
        raise err("ERR_CARD_RISK_FROZEN", "Card is frozen.")

    program = db.programs[card["program_id"]]
    now = db.clock.now()
    expires = now + timedelta(seconds=program["hold_ttl_seconds"])
    h = {
        "card_id": card_id,
        "amount_cents": amount,
        "expires_at": now_iso(expires),
        "status": "ACTIVE",
    }
    stamp_new(h)
    db.holds[h["id"]] = h
    return success(serialize.hold(h), status=201)


@bp.get("/v1/holds/<hold_id>")
def read_hold(hold_id):
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin", "FraudAnalyst"})
    h = get_hold(hold_id)
    return success(serialize.hold(h))


@bp.get("/v1/holds")
def list_holds():
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin", "FraudAnalyst"})
    items = list(db.holds.values())
    for key in ("card_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [h for h in items if h.get(key) == val]
    page, pg = paginate(items)
    return success([serialize.hold(h) for h in page], pagination=pg)


@bp.post("/v1/holds/<hold_id>/release")
def release_hold(hold_id):
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate"})
    h = get_hold(hold_id)
    # State (priority 8): only an ACTIVE hold can be released.
    if h["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Hold is not ACTIVE.")
    now = db.clock.now()
    expires = parse_iso(h["expires_at"])
    # At/after expiry -> finalize as EXPIRED; otherwise RELEASED (PRD §3.4).
    if now >= expires:
        h["status"] = "EXPIRED"
    else:
        h["status"] = "RELEASED"
    touch(h)
    return success(serialize.hold(h))
