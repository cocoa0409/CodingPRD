"""Dispatch routes (PRD §3.5)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import require_auth
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import lookup_or_404, parse_clock_dt


bp = Blueprint("dispatches", __name__)


VIEW_ROLES = ["PlatformAdmin", "Dispatcher", "Technician"]


@bp.get("/dispatches/<did>")
def get_dispatch(did: str):
    require_auth(VIEW_ROLES)()
    d = lookup_or_404(db.dispatches, did, "Dispatch")
    return ok_object(d, 200)


@bp.get("/dispatches")
def list_dispatches():
    require_auth(VIEW_ROLES)()
    limit, offset = paginate_params(request.args)
    claim_filter = request.args.get("claim_id")
    status_filter = request.args.get("status")

    items = list(db.dispatches.values())
    if claim_filter:
        items = [d for d in items if d["claim_id"] == claim_filter]
    if status_filter:
        items = [d for d in items if d["status"] == status_filter]
    items.sort(key=lambda d: d["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.post("/dispatches/<did>/start")
def start_dispatch(did: str):
    require_auth(["Technician", "PlatformAdmin"])()
    d = lookup_or_404(db.dispatches, did, "Dispatch")
    if d["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot start from status {d['status']}")
    # Must be at or after scheduled time (PRD §3.5).
    now_dt = parse_clock_dt()
    sched_dt = db.parse_iso_dt(d["scheduled_utc"])
    if sched_dt is None or now_dt < sched_dt:
        raise APIError(
            ERR_INVALID_STATE,
            409,
            "Cannot start before scheduled_utc",
        )
    d["status"] = "IN_PROGRESS"
    db.bump(d)
    return ok_object(d, 200)


@bp.post("/dispatches/<did>/complete")
def complete_dispatch(did: str):
    require_auth(["Technician", "PlatformAdmin"])()
    d = lookup_or_404(db.dispatches, did, "Dispatch")
    if d["status"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot complete from status {d['status']}")

    now_dt = parse_clock_dt()
    now_iso = db.iso_format(now_dt)
    d["completed_utc"] = now_iso
    d["status"] = "COMPLETED"
    db.bump(d)

    # Cascade: update parent CoveredItem (the item on the claim).
    claim = db.claim_tickets.get(d["claim_id"])
    if claim is None:
        # Defensive — shouldn't happen.
        raise APIError(ERR_NOT_FOUND, 404, "Claim not found")
    item = db.covered_items.get(claim["covered_item_id"])
    if item is None:
        raise APIError(ERR_NOT_FOUND, 404, "CoveredItem not found")

    item["last_dispatch_completed_utc"] = now_iso
    item["last_dispatch_id"] = d["id"]
    db.bump(item)

    return ok_object(d, 200)


@bp.post("/dispatches/<did>/mark-return-needed")
def mark_return_needed(did: str):
    require_auth(["Technician", "PlatformAdmin"])()
    d = lookup_or_404(db.dispatches, did, "Dispatch")
    if d["status"] != "IN_PROGRESS":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"Cannot mark return-needed from status {d['status']}",
        )
    d["status"] = "RETURN_NEEDED"
    db.bump(d)
    return ok_object(d, 200)
