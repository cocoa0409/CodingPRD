"""LossTriangle endpoints."""
from flask import Blueprint, request

from db import db
from middleware import authorized
from response import success_object, success_list
from routes.helpers import new_common_record, touch, sorted_by_creation
from services.calculations import aggregate_triangle
from services.serializers import triangle_view
from validate import (
    get_body,
    parse_pagination,
    reject_server_managed,
    req_enum,
    req_quarter,
    req_str,
    require_body_fk,
    require_path_resource,
)

bp = Blueprint("triangles", __name__)

TRIANGLE_COMPUTED = ["cells", "large_loss_cells", "is_stale"]


@bp.post("/actuarial/triangles")
def create_or_reaggregate():
    authorized(["ActuarialAnalyst"])
    body = get_body()
    reject_server_managed(body, TRIANGLE_COMPUTED)
    segment_id = req_str(body, "segment_id")
    basis = req_enum(body, "basis", ["PAID", "INCURRED"])
    valuation_quarter = req_quarter(body, "valuation_quarter")

    require_body_fk("segments", segment_id, "segment_id")

    # Upsert on (segment_id, basis, valuation_quarter).
    existing = None
    for t in db["triangles"].values():
        if (t["segment_id"] == segment_id and t["basis"] == basis
                and t["valuation_quarter"] == valuation_quarter):
            existing = t
            break

    cells, large_cells = aggregate_triangle(segment_id, basis, valuation_quarter)

    if existing is None:
        rec = new_common_record({
            "segment_id": segment_id,
            "basis": basis,
            "valuation_quarter": valuation_quarter,
            "cells": cells,
            "large_loss_cells": large_cells,
            "is_stale": False,
        })
        db["triangles"][rec["id"]] = rec
        return success_object(triangle_view(rec), status=201)

    # Re-aggregate in place: clears staleness, bumps version, does NOT rehabilitate runs.
    existing["cells"] = cells
    existing["large_loss_cells"] = large_cells
    existing["is_stale"] = False
    touch(existing)
    return success_object(triangle_view(existing), status=200)


@bp.get("/actuarial/triangles/<tid>")
def get_triangle(tid):
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    rec = require_path_resource("triangles", tid)
    return success_object(triangle_view(rec))


@bp.get("/actuarial/triangles")
def list_triangles():
    authorized(["ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    limit, offset = parse_pagination()
    segment_id = request.args.get("segment_id")
    basis = request.args.get("basis")
    vq = request.args.get("valuation_quarter")
    items = list(db["triangles"].values())
    if segment_id is not None:
        items = [t for t in items if t["segment_id"] == segment_id]
    if basis is not None:
        items = [t for t in items if t["basis"] == basis]
    if vq is not None:
        items = [t for t in items if t["valuation_quarter"] == vq]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([triangle_view(t) for t in page], total, limit, offset)
