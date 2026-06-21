"""Top-level repair line item listing (PRD §4)."""

from flask import Blueprint, request

from db import store
from helpers import pagination_params, paginate
from middleware import authenticate, require_role
from models import serialize
from response import array_response

bp = Blueprint("repair_line_items", __name__)


@bp.route("/repair-line-items", methods=["GET"])
def list_repair_line_items():
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    assessment_filter = request.args.get("assessment_id")
    records = list(store.repair_line_items.values())
    if assessment_filter is not None:
        records = [r for r in records if r["assessment_id"] == assessment_filter]
    limit, offset = pagination_params()
    page, total = paginate(records, limit, offset)
    return array_response([serialize(r) for r in page], limit, offset, total)
