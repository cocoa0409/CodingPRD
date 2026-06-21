from flask import Blueprint, request

import db
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup

bp = Blueprint("statement_lines", __name__)


@bp.get("/statement-lines/<line_id>")
@require("Admin", "Arranger")
def get_statement_line(line_id):
    line = lookup.statement_line(line_id)
    return ok_object(serialize.statement_line(line), 200)


@bp.get("/statement-lines")
@require("Admin", "Arranger")
def list_statement_lines():
    limit, offset = validate.pagination()
    case_id = request.args.get("case_id")
    gpl_item_id = request.args.get("gpl_item_id")
    items = list(db.statement_lines.values())
    if case_id is not None:
        items = [l for l in items if l["case_id"] == case_id]
    if gpl_item_id is not None:
        items = [l for l in items if l["gpl_item_id"] == gpl_item_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.statement_line(l) for l in window], limit, offset, total)
