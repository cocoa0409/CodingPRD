"""Lease list/get endpoints (PRD §3.4, §2.4)."""

from flask import Blueprint, request

import errors
import middleware
import response
import serializers
import validate
from db import db

bp = Blueprint("leases", __name__)


@bp.route("/leases", methods=["GET"])
def list_leases():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    unit_id = request.args.get("unit_id")
    household_id = request.args.get("household_id")
    items = list(db.leases.values())
    if unit_id is not None:
        items = [l for l in items if l["unit_id"] == unit_id]
    if household_id is not None:
        items = [l for l in items if l["household_id"] == household_id]
    items = serializers.sort_by_created(items)
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/leases/<lid>", methods=["GET"])
def get_lease(lid):
    middleware.require_role("OwnerAgent", "StateHFA")
    lease = db.leases.get(lid)
    if lease is None:
        raise errors.not_found("Lease not found")
    return response.success(serializers.public(lease), status=200)
