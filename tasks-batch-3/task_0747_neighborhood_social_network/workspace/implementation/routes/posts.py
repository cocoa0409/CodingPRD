"""Post endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    NotFound,
    ReferenceNotFound,
    Forbidden,
    ResidentSuspended,
    NotVerifiedInNeighborhood,
    NotOwner,
)
from middleware import require_roles
from paging import apply_pagination
from response import success
from services import recompute_post_score, recompute_post_flag_count
from validators import as_str, as_enum


bp = Blueprint("posts", __name__)


POST_CATEGORIES = {
    "GENERAL", "SAFETY", "RECOMMENDATION", "LOST_FOUND",
    "FREE_ITEM", "QUESTION", "ANNOUNCEMENT",
}
ALL_ROLES = ("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")


def _resident_verified_in(neighborhood_id: str, resident_id: str) -> bool:
    for m in DB.resident_memberships.values():
        if (
            m["resident_id"] == resident_id
            and m["neighborhood_id"] == neighborhood_id
            and m["status"] == "VERIFIED"
        ):
            return True
    return False


@bp.post("/neighborhood/posts")
@require_roles("Resident", "Moderator")
def create_post():
    payload = request.get_json(silent=True) or {}
    author_resident_id = as_str(payload, "author_resident_id")
    neighborhood_id = as_str(payload, "neighborhood_id")
    category = as_enum(payload, "category", POST_CATEGORIES)
    title = as_str(payload, "title")
    body = as_str(payload, "body")

    if len(body) > 5000:
        raise InvalidRequest("body exceeds 5000 chars")

    author = DB.residents.get(author_resident_id)
    if author is None:
        raise ReferenceNotFound(f"Resident {author_resident_id} not found")
    n = DB.neighborhoods.get(neighborhood_id)
    if n is None:
        raise ReferenceNotFound(f"Neighborhood {neighborhood_id} not found")

    # Suspension check (priority 90)
    acting = DB.residents.get(g.user_id)
    if acting is not None and acting.get("is_suspended", False):
        raise ResidentSuspended("Resident is suspended")

    # Verified-in-neighborhood check (priority 100). Applies to the ACTING resident.
    if not _resident_verified_in(neighborhood_id, g.user_id):
        raise NotVerifiedInNeighborhood(
            "Acting resident is not verified in the target neighborhood"
        )

    p = {
        "author_resident_id": author_resident_id,
        "neighborhood_id": neighborhood_id,
        "category": category,
        "title": title,
        "body": body,
        "state": "PUBLISHED",
        "flag_count": 0,
        "local_relevance_score": 0.0,
    }
    stamp_new(p)
    DB.posts[p["id"]] = p
    # Initial feed score
    recompute_post_score(p, bump_row=False)
    return success(p, status=201)


@bp.get("/neighborhood/posts/<pid>")
@require_roles(*ALL_ROLES)
def get_post(pid: str):
    p = DB.posts.get(pid)
    if p is None:
        raise NotFound(f"Post {pid} not found")
    return success(p)


@bp.get("/neighborhood/posts")
@require_roles(*ALL_ROLES)
def list_posts():
    nid = request.args.get("neighborhood_id")
    aid = request.args.get("author_resident_id")
    cat = request.args.get("category")

    rows = list(DB.posts.values())
    # Exclude HIDDEN, REMOVED, and suspended-author posts.
    def _visible(p: dict) -> bool:
        if p["state"] in ("HIDDEN", "REMOVED"):
            return False
        author = DB.residents.get(p["author_resident_id"])
        if author is not None and author.get("is_suspended", False):
            return False
        return True
    rows = [p for p in rows if _visible(p)]

    if nid is not None:
        rows = [p for p in rows if p["neighborhood_id"] == nid]
    if aid is not None:
        rows = [p for p in rows if p["author_resident_id"] == aid]
    if cat is not None:
        rows = [p for p in rows if p["category"] == cat]

    # Feed order: local_relevance_score DESC, created_at DESC as tiebreak.
    # Use two-pass stable sort: created_at DESC first, then score DESC.
    rows.sort(key=lambda p: p["created_at"], reverse=True)
    rows.sort(key=lambda p: float(p.get("local_relevance_score", 0.0)), reverse=True)
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.delete("/neighborhood/posts/<pid>")
@require_roles("Resident", "PlatformAdmin")
def delete_post(pid: str):
    p = DB.posts.get(pid)
    if p is None:
        raise NotFound(f"Post {pid} not found")

    # NOT_OWNER check for Resident (priority 140). PlatformAdmin bypasses.
    if g.user_role == "Resident" and p["author_resident_id"] != g.user_id:
        raise NotOwner("Only the post author may delete this post")

    if p["state"] == "REMOVED":
        # Deleting a REMOVED post is invalid state — the state machine has no exit.
        # But the PRD spec is only PUBLISHED -> REMOVED. Reject as invalid state.
        from errors import InvalidState
        raise InvalidState("Post is already REMOVED")

    p["state"] = "REMOVED"
    bump(p)
    # Dismiss all OPEN FlagReports against this Post
    for f in DB.flag_reports.values():
        if f["target_type"] == "POST" and f["target_id"] == pid and f["status"] == "OPEN":
            f["status"] = "DISMISSED"
            bump(f)
    # Recompute flag_count (though HIDDEN/REMOVED posts are excluded from feed anyway)
    new_fc = recompute_post_flag_count(pid)
    if p.get("flag_count") != new_fc:
        p["flag_count"] = new_fc
        bump(p)
    return success(p)
