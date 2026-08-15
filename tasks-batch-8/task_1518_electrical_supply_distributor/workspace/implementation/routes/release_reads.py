"""ReleaseLine and BackorderAllocation read endpoints (PRD §4)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from db import sort_key
from errors import raise_err, ERR_RELEASE_NOT_FOUND
from middleware import ROLES, require_roles
from response import success_list, success_object
from serializers import ser_backorder_allocation, ser_release_line
from util import paginate

bp = Blueprint("release_reads", __name__, url_prefix="/distributor")


def _query_arg(name: str):
    value = request.args.get(name)
    return value if value not in (None, "") else None


@bp.get("/release-lines")
@require_roles(*ROLES)
def list_release_lines():
    release_id = _query_arg("release_id")
    catalog_item_id = _query_arg("catalog_item_id")
    status = _query_arg("status")
    items = sorted(db.release_lines.values(), key=sort_key)
    if release_id is not None:
        items = [l for l in items if l["release_id"] == release_id]
    if catalog_item_id is not None:
        items = [l for l in items if l["catalog_item_id"] == catalog_item_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([ser_release_line(l) for l in page], limit, offset, total)


@bp.get("/release-lines/<line_id>")
@require_roles(*ROLES)
def get_release_line(line_id: str):
    line = db.release_lines.get(line_id)
    if line is None:
        raise_err(ERR_RELEASE_NOT_FOUND, "No release line with the given id")
    return success_object(ser_release_line(line))


@bp.get("/backorder-allocations")
@require_roles(*ROLES)
def list_backorder_allocations():
    release_line_id = _query_arg("release_line_id")
    catalog_item_id = _query_arg("catalog_item_id")
    status = _query_arg("status")
    items = sorted(db.backorder_allocations.values(), key=sort_key)
    if release_line_id is not None:
        items = [b for b in items if b["release_line_id"] == release_line_id]
    if catalog_item_id is not None:
        items = [b for b in items if b["catalog_item_id"] == catalog_item_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([ser_backorder_allocation(b) for b in page], limit, offset, total)


@bp.get("/backorder-allocations/<bo_id>")
@require_roles(*ROLES)
def get_backorder_allocation(bo_id: str):
    backorder = db.backorder_allocations.get(bo_id)
    if backorder is None:
        raise_err(ERR_RELEASE_NOT_FOUND, "No backorder allocation with the given id")
    return success_object(ser_backorder_allocation(backorder))
