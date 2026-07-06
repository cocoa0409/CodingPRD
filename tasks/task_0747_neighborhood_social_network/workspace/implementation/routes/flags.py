"""FlagReport endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    NotFound,
    ReferenceNotFound,
    ResidentSuspended,
    NotVerifiedInNeighborhood,
    DuplicateFlag,
)
from middleware import require_roles
from paging import apply_pagination
from response import success
from services import (
    FLAG_HIDE_THRESHOLD,
    recompute_post_flag_count,
    recompute_post_score,
)
from validators import as_str, as_enum


bp = Blueprint("flags", __name__)

TARGET_TYPES = {"POST", "MARKETPLACE_LISTING", "INCIDENT", "CIVIC_NOTICE", "EVENT"}
REASONS = {"SPAM", "HARASSMENT", "MISINFORMATION", "PROHIBITED", "OFF_TOPIC", "PRIVACY"}
_TARGET_TO_STORE = {
    "POST": "posts",
    "MARKETPLACE_LISTING": "marketplace_listings",
    "INCIDENT": "incidents",
    "CIVIC_NOTICE": "civic_notices",
    "EVENT": "events",
}


def _resident_verified_in(neighborhood_id: str, resident_id: str) -> bool:
    for m in DB.resident_memberships.values():
        if (
            m["resident_id"] == resident_id
            and m["neighborhood_id"] == neighborhood_id
            and m["status"] == "VERIFIED"
        ):
            return True
    return False


def _target_neighborhood(target_type: str, target_row: dict) -> str | None:
    return target_row.get("neighborhood_id")


@bp.post("/neighborhood/flag-reports")
@require_roles("Resident", "Moderator")
def create_flag():
    payload = request.get_json(silent=True) or {}
    reporter_resident_id = as_str(payload, "reporter_resident_id")
    target_type = as_enum(payload, "target_type", TARGET_TYPES)
    target_id = as_str(payload, "target_id")
    reason = as_enum(payload, "reason", REASONS)

    reporter = DB.residents.get(reporter_resident_id)
    if reporter is None:
        raise ReferenceNotFound(f"Resident {reporter_resident_id} not found")

    store_name = _TARGET_TO_STORE[target_type]
    target_store = getattr(DB, store_name)
    target_row = target_store.get(target_id)
    if target_row is None:
        raise ReferenceNotFound(f"{target_type} {target_id} not found")

    # Suspension check (priority 90)
    acting = DB.residents.get(g.user_id)
    if acting is not None and acting.get("is_suspended", False):
        raise ResidentSuspended("Resident is suspended")

    # Verified-in-neighborhood — flag-reports use the flagged row's neighborhood
    tnid = _target_neighborhood(target_type, target_row)
    if tnid is not None:
        if not _resident_verified_in(tnid, g.user_id):
            raise NotVerifiedInNeighborhood(
                "Acting resident is not verified in the target's neighborhood"
            )

    # Duplicate flag (priority 170): same reporter + target with OPEN/UPHELD
    for existing in DB.flag_reports.values():
        if (
            existing["reporter_resident_id"] == reporter_resident_id
            and existing["target_type"] == target_type
            and existing["target_id"] == target_id
            and existing["status"] in ("OPEN", "UPHELD")
        ):
            raise DuplicateFlag("Reporter has already flagged this target")

    f = {
        "reporter_resident_id": reporter_resident_id,
        "target_type": target_type,
        "target_id": target_id,
        "reason": reason,
        "status": "OPEN",
        "linked_decision_id": None,
    }
    stamp_new(f)
    DB.flag_reports[f["id"]] = f

    # If target is a Post, recompute flag_count and possibly auto-transition to FLAGGED
    if target_type == "POST":
        post = DB.posts.get(target_id)
        if post is not None:
            new_fc = recompute_post_flag_count(target_id)
            if post.get("flag_count") != new_fc:
                post["flag_count"] = new_fc
                bump(post)
            if post["state"] == "PUBLISHED" and new_fc >= FLAG_HIDE_THRESHOLD:
                post["state"] = "FLAGGED"
                bump(post)
            # Recompute local_relevance_score with flag penalty
            recompute_post_score(post, bump_row=True)

    return success(f, status=201)


@bp.get("/neighborhood/flag-reports/<fid>")
@require_roles("Moderator", "PlatformAdmin")
def get_flag(fid: str):
    f = DB.flag_reports.get(fid)
    if f is None:
        raise NotFound(f"FlagReport {fid} not found")
    return success(f)


@bp.get("/neighborhood/flag-reports")
@require_roles("Moderator", "PlatformAdmin")
def list_flags():
    rid = request.args.get("reporter_resident_id")
    ttype = request.args.get("target_type")
    tid = request.args.get("target_id")
    status = request.args.get("status")
    ldid = request.args.get("linked_decision_id")
    rows = list(DB.flag_reports.values())
    if rid is not None:
        rows = [r for r in rows if r["reporter_resident_id"] == rid]
    if ttype is not None:
        rows = [r for r in rows if r["target_type"] == ttype]
    if tid is not None:
        rows = [r for r in rows if r["target_id"] == tid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if ldid is not None:
        rows = [r for r in rows if r.get("linked_decision_id") == ldid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)
