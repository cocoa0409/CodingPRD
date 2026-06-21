"""Concession combo endpoints (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import authenticate, authorize, CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER
import response
from services import common as C
from routes._helpers import get_or_404

bp = Blueprint("combos", __name__)


@bp.route("/combos", methods=["POST"])
def create_combo():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    body = C.get_body()
    C.require_fields(body, ["name", "price_cents"])
    name = C.require_str(body, "name")
    price = C.require_int(body, "price_cents")
    if price < 0:
        raise E.invalid_request("price_cents must be >= 0")

    pct = body.get("member_discount_pct", 0)
    if pct is None:
        pct = 0
    if not C.is_number(pct) or pct < 0 or pct > 1:
        raise E.invalid_request("member_discount_pct must be a number in [0,1]")

    combo = C.new_common_fields()
    combo.update({
        "name": name,
        "price_cents": price,
        "member_discount_pct": pct,
        "status": "AVAILABLE",
    })
    db.combos[combo["id"]] = combo
    return response.ok_object(C.serialize(combo), 201)


@bp.route("/combos/<combo_id>", methods=["GET"])
def get_combo(combo_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER})
    combo = get_or_404(db.combos, combo_id, "ConcessionCombo")
    return response.ok_object(C.serialize(combo), 200)


@bp.route("/combos", methods=["GET"])
def list_combos():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER})
    limit, offset = C.parse_pagination()
    status = request.args.get("status")
    items = list(db.combos.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)
