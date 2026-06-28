"""Form 8609 list/get endpoints (PRD §3.6, §2.4)."""

from flask import Blueprint, request

import errors
import middleware
import response
import serializers
import validate
from db import db

bp = Blueprint("form8609s", __name__)


@bp.route("/form8609s", methods=["GET"])
def list_form8609s():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    building_id = request.args.get("building_id")
    items = list(db.form8609s.values())
    if building_id is not None:
        items = [f for f in items if f["building_id"] == building_id]
    items = serializers.sort_by_created(items)
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/form8609s/<fid>", methods=["GET"])
def get_form8609(fid):
    middleware.require_role("OwnerAgent", "StateHFA")
    form = db.form8609s.get(fid)
    if form is None:
        raise errors.not_found("Form 8609 not found")
    return response.success(serializers.public(form), status=200)
