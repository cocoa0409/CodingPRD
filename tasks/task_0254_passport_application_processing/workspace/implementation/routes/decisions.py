"""Global adjudication-decisions listing (filter by adjudicator_id / application_id)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_auth
from response import ok_array
from routes._helpers import (
    order_by_created,
    paginate,
    parse_pagination,
    serialize_list,
)

bp = Blueprint("decisions", __name__)


@bp.route("/adjudication-decisions", methods=["GET"])
def list_decisions():
    require_auth(["Adjudicator"])
    limit, offset = parse_pagination()
    items = list(db.adjudication_decisions.values())
    adjudicator_id = request.args.get("adjudicator_id")
    application_id = request.args.get("application_id")
    if adjudicator_id is not None:
        items = [d for d in items if d["adjudicator_id"] == adjudicator_id]
    if application_id is not None:
        items = [d for d in items if d["application_id"] == application_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
