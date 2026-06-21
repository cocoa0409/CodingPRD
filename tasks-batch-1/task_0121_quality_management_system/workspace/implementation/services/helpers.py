"""Shared service helpers: lookups, pagination, supplier-rating reconciliation."""
from flask import request

from common import touch
from db import db
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, err
from services.calculations import supplier_quality_rating


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return rec


def recompute_supplier_rating(supplier):
    """Recompute quality_rating + approval_status from the supplier's counters.

    This is itself a mutation of the supplier, so it advances version/updated_at
    (PRD 2.8)."""
    rating, approval = supplier_quality_rating(
        supplier["lots_inspected"],
        supplier["lots_rejected"],
        supplier["ncrs_attributed"],
        supplier["open_scar_count"],
    )
    supplier["quality_rating"] = rating
    supplier["approval_status"] = approval
    touch(supplier)


def paginate_args():
    """Resolve limit/offset query params (PRD 2.3). limit default 10, min 1,
    max 100 (over-max clamped to max); offset default 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "Invalid limit")
        if limit < 1:
            raise err(ERR_INVALID_REQUEST, "limit must be >= 1")
        if limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "Invalid offset")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (PRD 2.3) and slice. Returns (page, total)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
