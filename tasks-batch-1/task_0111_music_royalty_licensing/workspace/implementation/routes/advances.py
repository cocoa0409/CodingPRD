"""Advance routes: issue, read, list, write-off."""
from flask import Blueprint, request

import db
from errors import fail, ERR_INVALID_STATE
from middleware import authorize, get_auth
from response import success
from services import serialize as S
from services.common import (stamp_create, touch, require_body, require_int,
                             optional_number, parse_pagination, paginate,
                             sorted_by_creation)
from services.lookup import path_get, fk_get, require_owner

bp = Blueprint("advances", __name__)


@bp.route("/advances", methods=["POST"])
def create_advance():
    authorize({"Administrator"})
    data = require_body(request.get_json(silent=True))
    rightsholder_id = data.get("rightsholder_id")
    fk_get(db.rightsholders, rightsholder_id)
    principal_cents = require_int(data, "principal_cents", minimum=1)
    # recoupment_pct default 1.0, must be > 0 and <= 1.0.
    recoupment_pct = optional_number(data, "recoupment_pct", 1.0)
    if recoupment_pct <= 0 or recoupment_pct > 1.0:
        from errors import ERR_INVALID_REQUEST
        fail(ERR_INVALID_REQUEST, "recoupment_pct must be > 0 and <= 1.0")
    rec = {
        "rightsholder_id": rightsholder_id,
        "principal_cents": principal_cents,
        "recoupment_pct": recoupment_pct,
        "recouped_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.advances[rec["id"]] = rec
    # Rightsholder.unrecouped_balance_cents is recomputed read-time; no write
    # needed (PRD §2.5 derived field).
    return success(S.advance(rec), status=201)


@bp.route("/advances/<rid>", methods=["GET"])
def get_advance(rid):
    user_id, role = authorize({"Administrator", "RoyaltyOperator", "Rightsholder"})
    rec = path_get(db.advances, rid)
    require_owner(rec["rightsholder_id"], user_id, role)
    return success(S.advance(rec))


@bp.route("/advances", methods=["GET"])
def list_advances():
    user_id, role = authorize({"Administrator", "RoyaltyOperator", "Rightsholder"})
    limit, offset = parse_pagination(request.args)
    items = list(db.advances.values())
    rightsholder_id = request.args.get("rightsholder_id")
    status = request.args.get("status")
    if rightsholder_id is not None:
        items = [a for a in items if a["rightsholder_id"] == rightsholder_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    # Rightsholder sees only own advances.
    if role == "Rightsholder":
        items = [a for a in items if a["rightsholder_id"] == user_id]
    items = sorted_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return success([S.advance(a) for a in page], pagination=meta)


@bp.route("/advances/<rid>/write-off", methods=["POST"])
def write_off_advance(rid):
    authorize({"Administrator"})
    rec = path_get(db.advances, rid)
    if rec["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Only an ACTIVE advance can be written off")
    rec["status"] = "WRITTEN_OFF"
    touch(rec)
    # unrecouped_balance_cents recomputed read-time (excludes WRITTEN_OFF).
    return success(S.advance(rec))
