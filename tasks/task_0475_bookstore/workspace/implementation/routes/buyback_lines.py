"""Cross-store BuybackLine reads (operator-only)."""
from flask import Blueprint, request

from common import parse_pagination, paginate
from db import db
from errors import err, ERR_NOT_FOUND
from middleware import authorize
from response import success_object, success_list
from serialize import buyback_line_out

bp = Blueprint("buyback_lines", __name__)

# GET /buyback-lines/{id} and GET /buyback-lines: Bookseller, StoreAdmin
ROLES = {"Bookseller", "StoreAdmin"}


@bp.route("/buyback-lines/<lid>", methods=["GET"])
def get_buyback_line(lid):
    authorize(ROLES)
    line = db.buyback_lines.get(lid)
    if line is None:
        raise err(ERR_NOT_FOUND, "Buyback line not found")
    return success_object(buyback_line_out(line), status=200)


@bp.route("/buyback-lines", methods=["GET"])
def list_buyback_lines():
    authorize(ROLES)
    title_id = request.args.get("title_id")
    buyback_id = request.args.get("buyback_id")
    items = list(db.buyback_lines.values())
    if title_id is not None:
        items = [l for l in items if l["title_id"] == title_id]
    if buyback_id is not None:
        items = [l for l in items if l["buyback_id"] == buyback_id]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([buyback_line_out(l) for l in page], limit, offset, total)
