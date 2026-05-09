"""AlignmentLink endpoints."""

from flask import Blueprint, request

import db
from audit import write_audit
from auth import require_role, is_owner_or_co_owner
from clock import now, format_ts
from envelope import success_object, success_array
from errors import ApiError
from serialize import s_link
from services.alignment import (would_introduce_cycle, recompute_link_impact,
                                count_accepted_upstreams, compute_forward_impact,
                                compute_backward_impact)
from util import (get_json_body, parse_pagination, paginate, require_fields,
                  stamp_create, stamp_update, actor_id, actor_role)


bp = Blueprint("alignment", __name__)


def _audit_link(l, action, before=None, after=None, system=False):
    write_audit(entity_type="ALIGNMENT_LINK", entity_id=l["id"], action=action,
                before=before, after=after,
                actor_override="SYSTEM" if system else None,
                role_override="SYSTEM" if system else None)


@bp.post("/alignment-links")
def create_link():
    require_role("PlatformAdmin", "Manager", "Employee")
    body = get_json_body()
    require_fields(body, "upstream_objective_id", "downstream_objective_id", "dependency_type")
    up_id = body["upstream_objective_id"]
    down_id = body["downstream_objective_id"]
    dep_type = body["dependency_type"]
    up = db.objectives.get(up_id)
    if not up:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "upstream objective not found")
    down = db.objectives.get(down_id)
    if not down:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "downstream objective not found")
    if dep_type not in ("SUPPORTS", "BLOCKS", "INFORMS"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "dependency_type invalid")
    if up_id == down_id:
        raise ApiError("ERR_DUPLICATE_LINK", 409, "upstream cannot equal downstream")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(up, aid) and not is_owner_or_co_owner(down, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner of one endpoint")
    # Uniqueness: no non-REJECTED link with same (up,down)
    for l in db.alignment_links.values():
        if (l["upstream_objective_id"] == up_id and
                l["downstream_objective_id"] == down_id and
                l["status"] != "REJECTED"):
            raise ApiError("ERR_DUPLICATE_LINK", 409, "duplicate link")
    link = {
        "upstream_objective_id": up_id,
        "downstream_objective_id": down_id,
        "dependency_type": dep_type,
        "declared_by_user_id": aid,
        "status": "PENDING",
        "accepted_at": None,
        "rejection_reason": None,
        "forward_impact_score": None,
        "backward_impact_score": None,
    }
    stamp_create(link)
    db.alignment_links[link["id"]] = link
    _audit_link(link, "CREATE", after=s_link(link))
    return success_object(s_link(link), status=201)


@bp.get("/alignment-links")
def list_links():
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    limit, offset = parse_pagination()
    items = list(db.alignment_links.values())
    up = request.args.get("upstream_objective_id")
    down = request.args.get("downstream_objective_id")
    status = request.args.get("status")
    dep = request.args.get("dependency_type")
    if up:
        items = [l for l in items if l["upstream_objective_id"] == up]
    if down:
        items = [l for l in items if l["downstream_objective_id"] == down]
    if status:
        items = [l for l in items if l["status"] == status]
    if dep:
        items = [l for l in items if l["dependency_type"] == dep]
    items.sort(key=lambda l: l["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([s_link(l) for l in page], total, limit, offset)


@bp.post("/alignment-links/<id>/accept")
def accept_link(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    l = db.alignment_links.get(id)
    if not l:
        raise ApiError("ERR_LINK_NOT_FOUND", 404, "link not found")
    up = db.objectives.get(l["upstream_objective_id"])
    down = db.objectives.get(l["downstream_objective_id"])
    if not up or not down:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "endpoint not found")
    aid = actor_id()
    arole = actor_role()
    # Downstream owner / co-owner / admin
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(down, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be downstream owner/co-owner")
    if l["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, f"link status {l['status']}")
    if up["status"] != "ACTIVE" or down["status"] != "ACTIVE":
        raise ApiError("ERR_OBJECTIVE_NOT_ACTIVE", 409, "both endpoints must be ACTIVE")
    if would_introduce_cycle(l["upstream_objective_id"], l["downstream_objective_id"]):
        raise ApiError("ERR_CIRCULAR_REFERENCE", 422, "would introduce cycle")
    before = s_link(l)
    l["status"] = "ACCEPTED"
    l["accepted_at"] = format_ts(now())
    stamp_update(l)
    recompute_link_impact(l)
    _audit_link(l, "STATE_TRANSITION", before=before, after=s_link(l))
    return success_object(s_link(l))


@bp.post("/alignment-links/<id>/reject")
def reject_link(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    l = db.alignment_links.get(id)
    if not l:
        raise ApiError("ERR_LINK_NOT_FOUND", 404, "link not found")
    down = db.objectives.get(l["downstream_objective_id"])
    if not down:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "downstream not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(down, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be downstream owner/co-owner")
    if l["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, f"link status {l['status']}")
    body = get_json_body()
    reason = body.get("rejection_reason")
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "rejection_reason required")
    before = s_link(l)
    l["status"] = "REJECTED"
    l["rejection_reason"] = reason
    stamp_update(l)
    _audit_link(l, "STATE_TRANSITION", before=before, after=s_link(l))
    return success_object(s_link(l))
