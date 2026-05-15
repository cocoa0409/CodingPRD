"""BoothAllocation workflow (§3.4)."""

from __future__ import annotations

from datetime import timedelta
from flask import g

import db
import clock
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_INPUT,
    ERR_BOOTH_ALREADY_ALLOCATED,
    ERR_OBJECTION_WINDOW_CLOSED,
    ERR_RELOCATION_TIER_MISMATCH,
    ERR_FORBIDDEN,
)
from services.common import (
    stamp_create,
    bump,
    check_occ,
    must_dict,
    write_audit,
)
from services import calculations


def _get_allocation(alloc_id: str) -> dict:
    al = db.allocations.get(alloc_id)
    if al is None:
        raise AppError(ERR_NOT_FOUND, "Allocation not found.", 404)
    return al


def _check_exhibitor_owner(al):
    if g.role == "Exhibitor" and al["exhibitor_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Allocation not owned by exhibitor.", 403)


def create_allocation(body: dict) -> dict:
    body = must_dict(body)
    app_id = body.get("application_id")
    booth_id = body.get("booth_id")
    if not app_id or not booth_id:
        raise AppError(ERR_INVALID_INPUT, "application_id and booth_id are required.", 422)
    app = db.applications.get(app_id)
    if app is None:
        raise AppError(ERR_NOT_FOUND, "Application not found.", 404)
    booth = db.booths.get(booth_id)
    if booth is None:
        raise AppError(ERR_NOT_FOUND, "Booth not found.", 404)
    # Application must be QUALIFIED.
    if app["status"] != "QUALIFIED":
        raise AppError(ERR_INVALID_STATE, "Application not in QUALIFIED.", 409)
    # Booth must be AVAILABLE.
    with db.LOCK:
        if booth["status"] != "AVAILABLE":
            raise AppError(ERR_BOOTH_ALREADY_ALLOCATED, "Booth not AVAILABLE.", 409)
        row = {
            "application_id": app_id,
            "booth_id": booth_id,
            "exhibition_id": app["exhibition_id"],
            "exhibitor_id": app["exhibitor_id"],
            "quoted_price_cents": 0,
            "status": "PROPOSED",
            "published_at": None,
            "relocation_source_booth_id": None,
        }
        stamp_create(row)
        db.allocations[row["id"]] = row
        booth["status"] = "RESERVED"
        bump(booth)
        app["status"] = "ALLOCATED"
        bump(app)
    return row


def object_allocation(alloc_id: str, body: dict) -> dict:
    al = _get_allocation(alloc_id)
    _check_exhibitor_owner(al)
    ex = db.exhibitions.get(al["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    if al["status"] != "PUBLISHED":
        raise AppError(ERR_INVALID_STATE, "Allocation not in PUBLISHED.", 409)
    body = must_dict(body)
    reason = body.get("reason")
    if not reason or not isinstance(reason, str):
        raise AppError(ERR_INVALID_INPUT, "reason is required.", 422)
    pub_at = clock.parse_iso(al.get("published_at"))
    if pub_at is None:
        raise AppError(ERR_INVALID_STATE, "Allocation has no published_at.", 409)
    deadline = pub_at + timedelta(hours=int(ex["objection_window_hours"]))
    if clock.now() >= deadline:
        raise AppError(ERR_OBJECTION_WINDOW_CLOSED, "Objection window closed.", 409)
    check_occ(al, body)
    al["status"] = "OBJECTED"
    bump(al)
    write_audit("ALLOCATION", al["id"], "OBJECT", {"reason": reason})
    return al


def confirm_allocation(alloc_id: str, body: dict) -> dict:
    al = _get_allocation(alloc_id)
    _check_exhibitor_owner(al)
    with db.LOCK:
        if al["status"] != "PUBLISHED":
            raise AppError(ERR_INVALID_STATE, "Allocation not in PUBLISHED.", 409)
        check_occ(al, body)
        al["status"] = "CONFIRMED"
        bump(al)
    return al


def start_relocation(alloc_id: str, body: dict) -> dict:
    al = _get_allocation(alloc_id)
    if al["status"] != "OBJECTED":
        raise AppError(ERR_INVALID_STATE, "Allocation not in OBJECTED.", 409)
    check_occ(al, body)
    booth = db.booths.get(al["booth_id"])
    al["relocation_source_booth_id"] = al["booth_id"]
    al["status"] = "RELOCATING"
    if booth is not None:
        booth["status"] = "AVAILABLE"
        bump(booth)
    bump(al)
    return al


def relocate_allocation(alloc_id: str, body: dict) -> dict:
    al = _get_allocation(alloc_id)
    ex = db.exhibitions.get(al["exhibition_id"])
    with db.LOCK:
        if al["status"] != "RELOCATING":
            raise AppError(ERR_INVALID_STATE, "Allocation not in RELOCATING.", 409)
        body = must_dict(body)
        target_booth_id = body.get("target_booth_id")
        if not target_booth_id:
            raise AppError(ERR_INVALID_INPUT, "target_booth_id is required.", 422)
        target_booth = db.booths.get(target_booth_id)
        if target_booth is None:
            raise AppError(ERR_NOT_FOUND, "Target booth not found.", 404)
        if target_booth["status"] != "AVAILABLE":
            raise AppError(ERR_INVALID_STATE, "Target booth not AVAILABLE.", 409)
        # Tier match.
        original_booth_id = al.get("relocation_source_booth_id") or al["booth_id"]
        original_booth = db.booths.get(original_booth_id)
        if original_booth and target_booth["tier"] != original_booth["tier"]:
            raise AppError(ERR_RELOCATION_TIER_MISMATCH, "Tier mismatch.", 422)
        check_occ(al, body)
        from_booth_id = al["booth_id"]
        al["booth_id"] = target_booth["id"]
        target_booth["status"] = "ALLOCATED"
        bump(target_booth)
        al["quoted_price_cents"] = calculations.booth_quoted_price(target_booth, ex)
        al["status"] = "PUBLISHED"
        al["published_at"] = clock.iso()
        bump(al)
        write_audit("ALLOCATION", al["id"], "RELOCATE", {
            "from_booth_id": from_booth_id,
            "to_booth_id": target_booth["id"],
        })
    return al


def revoke_allocation(alloc_id: str, body: dict) -> dict:
    al = _get_allocation(alloc_id)
    ex = db.exhibitions.get(al["exhibition_id"])
    with db.LOCK:
        if al["status"] != "PUBLISHED":
            raise AppError(ERR_INVALID_STATE, "Allocation not in PUBLISHED.", 409)
        if ex is None or ex["status"] != "ALLOCATION_PUBLISHED":
            raise AppError(ERR_INVALID_STATE, "Exhibition not in ALLOCATION_PUBLISHED.", 409)
        body = must_dict(body)
        reason = body.get("reason")
        if not reason or not isinstance(reason, str):
            raise AppError(ERR_INVALID_INPUT, "reason is required.", 422)
        check_occ(al, body)
        al["status"] = "REVOKED"
        bump(al)
        booth = db.booths.get(al["booth_id"])
        if booth is not None:
            booth["status"] = "AVAILABLE"
            bump(booth)
        app = db.applications.get(al["application_id"])
        if app is not None:
            app["status"] = "QUALIFIED"
            bump(app)
        write_audit("ALLOCATION", al["id"], "REVOKE", {"reason": reason})
    return al


def get_allocation(alloc_id: str) -> dict:
    return _get_allocation(alloc_id)


def list_audit_log(exhibition_id: str, subject_kind: str | None, limit: int, offset: int):
    ex = db.exhibitions.get(exhibition_id)
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    # Collect entries whose subject is an allocation/entitlement that belongs to this exhibition.
    rows = []
    for e in db.audit_logs.values():
        sk = e["subject_kind"]
        sid = e["subject_id"]
        if subject_kind and sk != subject_kind:
            continue
        if sk == "ALLOCATION":
            al = db.allocations.get(sid)
            if al and al["exhibition_id"] == exhibition_id:
                rows.append(e)
        elif sk == "ENTITLEMENT":
            ent = db.entitlements.get(sid)
            if ent and ent["exhibition_id"] == exhibition_id:
                rows.append(e)
    rows.sort(key=lambda r: r["created_at"])
    return rows[offset:offset + limit], len(rows)
