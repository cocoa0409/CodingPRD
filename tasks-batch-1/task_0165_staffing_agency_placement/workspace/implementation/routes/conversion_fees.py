"""ConversionFee read routes (PRD 3.7)."""

from flask import Blueprint, request

import db
import errors
from middleware import (
    get_user_context, require_role, parse_pagination, paginate,
)
from response import object_response, array_response
from services import common, serialize, ownership

bp = Blueprint("conversion_fees", __name__)


@bp.route("/staffing/conversion-fees", methods=["GET"])
def list_conversion_fees():
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Client"})
    limit, offset = parse_pagination()

    placement_filter = request.args.get("placement_id")
    client_filter = request.args.get("client_id")

    rows = list(db.conversion_fees.values())
    if placement_filter is not None:
        rows = [r for r in rows if r["placement_id"] == placement_filter]
    if client_filter is not None:
        rows = [r for r in rows if r["client_id"] == client_filter]
    if role == "Client":
        rows = [r for r in rows if r["client_id"] == user_id]

    page, total = paginate(rows, limit, offset)
    return array_response([serialize.conversion_fee(r) for r in page], limit, offset, total)


@bp.route("/staffing/conversion-fees/<fid>", methods=["GET"])
def get_conversion_fee(fid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Client"})
    rec = common.get_or_404(db.conversion_fees, fid, errors.ERR_CONVERSION_FEE_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, rec["client_id"])
    return object_response(serialize.conversion_fee(rec), 200)
