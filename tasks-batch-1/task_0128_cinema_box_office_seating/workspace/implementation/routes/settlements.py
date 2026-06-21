"""Settlement reverse-reachability reads (SCAFFOLD §1.5).

GET /settlements/{id} and GET /settlements filterable by distributor_id, film_id,
showtime_id. Distributors may only read their own settlements.
"""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import (
    authenticate, authorize, current_role, current_user_id,
    CINEMA_MANAGER, DISTRIBUTOR,
)
import response
from services import common as C
from routes._helpers import get_or_404, require_distributor_owns_settlement

bp = Blueprint("settlements", __name__)


@bp.route("/settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, DISTRIBUTOR})
    settlement = get_or_404(db.settlements, settlement_id, "Settlement")
    require_distributor_owns_settlement(settlement)
    return response.ok_object(C.serialize(settlement), 200)


@bp.route("/settlements", methods=["GET"])
def list_settlements():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, DISTRIBUTOR})
    limit, offset = C.parse_pagination()
    distributor_id = request.args.get("distributor_id")
    film_id = request.args.get("film_id")
    showtime_id = request.args.get("showtime_id")
    items = list(db.settlements.values())
    if current_role() == DISTRIBUTOR:
        items = [s for s in items if s["distributor_id"] == current_user_id()]
    if distributor_id is not None:
        items = [s for s in items if s["distributor_id"] == distributor_id]
    if film_id is not None:
        items = [s for s in items if s["film_id"] == film_id]
    if showtime_id is not None:
        items = [s for s in items if s["showtime_id"] == showtime_id]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)
