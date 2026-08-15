"""Lot retrieval endpoints (PRD §3.6); lots are created only by run
completion."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import ALL_ROLES, auth, paginate
from response import success_list, success_object
from serializers import lot_json

lots_bp = Blueprint("lots", __name__)


def get_lot_or_404(lid):
    lot = store.lots.get(lid)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", "Lot not found: %s" % lid)
    return lot


@lots_bp.route("/lots", methods=["GET"])
def list_lots():
    auth(ALL_ROLES)
    items = list(store.lots.values())
    f = request.args.get("product_id")
    if f is not None:
        items = [l for l in items if l["product_id"] == f]
    f = request.args.get("run_id")
    if f is not None:
        items = [l for l in items if l["run_id"] == f]
    f = request.args.get("status")
    if f is not None:
        items = [l for l in items if l["status"] == f]
    items.sort(key=lambda l: l["created_at"])
    page, meta = paginate(items)
    return success_list([lot_json(l) for l in page], meta)


@lots_bp.route("/lots/<lid>", methods=["GET"])
def get_lot(lid):
    auth(ALL_ROLES)
    return success_object(lot_json(get_lot_or_404(lid)))
