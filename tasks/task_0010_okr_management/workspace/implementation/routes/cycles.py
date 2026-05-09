"""OKRCycle endpoints + lifecycle transitions."""

from flask import Blueprint, request

import db
from audit import write_audit
from auth import require_role
from clock import now, format_ts, parse_ts
from envelope import success_object, success_array
from errors import ApiError
from serialize import s_cycle, s_objective, s_link
from services.alignment import recompute_link_impact
from util import (get_json_body, parse_pagination, paginate,
                  require_fields, stamp_create, stamp_update,
                  round4)


bp = Blueprint("cycles", __name__)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open: A.end == B.start is NOT overlap."""
    return (a_start < b_end) and (b_start < a_end)


def _check_cycle_overlap(start_date, end_date, exclude_id=None):
    a_s = parse_ts(start_date)
    a_e = parse_ts(end_date)
    for c in db.cycles.values():
        if exclude_id and c["id"] == exclude_id:
            continue
        if c["status"] == "ARCHIVED":
            continue
        b_s = parse_ts(c["start_date"])
        b_e = parse_ts(c["end_date"])
        if _intervals_overlap(a_s, a_e, b_s, b_e):
            raise ApiError("ERR_CYCLE_OVERLAP", 409,
                           f"cycle interval overlaps with cycle {c['id']}")


def _check_cycle_overlap_open(target):
    """Used by /cycles/{id}/open: same overlap rule but compare against currently OPEN/IN_REVIEW cycles."""
    a_s = parse_ts(target["start_date"])
    a_e = parse_ts(target["end_date"])
    for c in db.cycles.values():
        if c["id"] == target["id"]:
            continue
        if c["status"] not in ("OPEN", "IN_REVIEW"):
            continue
        b_s = parse_ts(c["start_date"])
        b_e = parse_ts(c["end_date"])
        if _intervals_overlap(a_s, a_e, b_s, b_e):
            raise ApiError("ERR_CYCLE_OVERLAP", 409,
                           f"cycle interval overlaps with cycle {c['id']}")


def _audit_cycle(cycle, action, before=None, after=None, system=False):
    write_audit(entity_type="OKR_CYCLE", entity_id=cycle["id"], action=action,
                before=before, after=after,
                actor_override="SYSTEM" if system else None,
                role_override="SYSTEM" if system else None)


def _recompute_cycle_completion(cycle):
    obj_in_cycle = [o for o in db.objectives.values()
                    if o["cycle_id"] == cycle["id"] and o["status"] != "ARCHIVED"]
    if not obj_in_cycle:
        cycle["completion_rate"] = 0.0
        return
    locked = [o for o in obj_in_cycle if o["status"] == "LOCKED"]
    cycle["completion_rate"] = round4(len(locked) / len(obj_in_cycle))


@bp.post("/cycles")
def create_cycle():
    require_role("PlatformAdmin")
    body = get_json_body()
    require_fields(body, "cycle_code", "year", "quarter", "start_date", "end_date")
    cycle_code = body["cycle_code"]
    year = body["year"]
    quarter = body["quarter"]
    start_date = body["start_date"]
    end_date = body["end_date"]
    if not isinstance(year, int) or not isinstance(quarter, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "year/quarter must be integers")
    if quarter < 1 or quarter > 4:
        raise ApiError("ERR_INVALID_REQUEST", 400, "quarter must be 1..4")
    # Validate dates
    try:
        s = parse_ts(start_date)
        e = parse_ts(end_date)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_date/end_date must be ISO 8601")
    if not (s < e):
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_date must be < end_date")
    # Cycle code uniqueness
    for c in db.cycles.values():
        if c["cycle_code"] == cycle_code:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"cycle_code '{cycle_code}' already exists")
    # Overlap check at creation
    _check_cycle_overlap(start_date, end_date)
    cycle = {
        "cycle_code": cycle_code,
        "year": year,
        "quarter": quarter,
        "start_date": start_date,
        "end_date": end_date,
        "status": "DRAFT",
        "completion_rate": 0.0,
    }
    stamp_create(cycle)
    db.cycles[cycle["id"]] = cycle
    _audit_cycle(cycle, "CREATE", after=s_cycle(cycle))
    return success_object(s_cycle(cycle), status=201)


@bp.get("/cycles")
def list_cycles():
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    year = request.args.get("year")
    items = list(db.cycles.values())
    if status:
        items = [c for c in items if c["status"] == status]
    if year is not None:
        try:
            y = int(year)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "year must be integer")
        items = [c for c in items if c["year"] == y]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([s_cycle(c) for c in page], total, limit, offset)


@bp.get("/cycles/<id>")
def read_cycle(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    c = db.cycles.get(id)
    if not c:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    return success_object(s_cycle(c))


@bp.post("/cycles/<id>/open")
def open_cycle(id):
    require_role("PlatformAdmin")
    body = get_json_body()
    c = db.cycles.get(id)
    if not c:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    # OCC
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(c["version"]):
            raise ApiError("ERR_VERSION_CONFLICT", 409, "version mismatch")
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, f"cycle in status {c['status']}")
    _check_cycle_overlap(c["start_date"], c["end_date"], exclude_id=c["id"])
    before = s_cycle(c)
    c["status"] = "OPEN"
    stamp_update(c)
    _audit_cycle(c, "STATE_TRANSITION", before=before, after=s_cycle(c))
    return success_object(s_cycle(c))


@bp.post("/cycles/<id>/start-review")
def start_review(id):
    require_role("PlatformAdmin")
    c = db.cycles.get(id)
    if not c:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, f"cycle in status {c['status']}")
    # Cascade: ACTIVE objectives -> IN_REVIEW; create ReviewScore for each.
    affected = [o for o in db.objectives.values()
                if o["cycle_id"] == id and o["status"] == "ACTIVE"]
    before = s_cycle(c)
    c["status"] = "IN_REVIEW"
    stamp_update(c)
    _audit_cycle(c, "STATE_TRANSITION", before=before, after=s_cycle(c))
    from routes.reviews import _create_review_for_objective  # avoid circ import
    for o in affected:
        ob_before = s_objective(o)
        o["status"] = "IN_REVIEW"
        stamp_update(o)
        write_audit(entity_type="OBJECTIVE", entity_id=o["id"],
                    action="STATE_TRANSITION", before=ob_before, after=s_objective(o),
                    actor_override="SYSTEM", role_override="SYSTEM")
        _create_review_for_objective(o, system=True)
    return success_object(s_cycle(c))


@bp.post("/cycles/<id>/lock")
def lock_cycle(id):
    require_role("PlatformAdmin")
    c = db.cycles.get(id)
    if not c:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    if c["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, f"cycle in status {c['status']}")
    # Every ReviewScore for objectives in this cycle must be LOCKED
    revs = [r for r in db.review_scores.values() if r["cycle_id"] == id]
    if not all(r["status"] == "LOCKED" for r in revs):
        raise ApiError("ERR_INVALID_STATE", 409, "not all reviews are LOCKED")
    before = s_cycle(c)
    c["status"] = "LOCKED"
    stamp_update(c)
    # Cascade: IN_REVIEW objectives -> LOCKED  (in practice already cascaded by review.lock)
    for o in db.objectives.values():
        if o["cycle_id"] == id and o["status"] == "IN_REVIEW":
            ob_before = s_objective(o)
            o["status"] = "LOCKED"
            stamp_update(o)
            write_audit(entity_type="OBJECTIVE", entity_id=o["id"],
                        action="STATE_TRANSITION", before=ob_before, after=s_objective(o),
                        actor_override="SYSTEM", role_override="SYSTEM")
    _recompute_cycle_completion(c)
    _audit_cycle(c, "STATE_TRANSITION", before=before, after=s_cycle(c))
    return success_object(s_cycle(c))


@bp.post("/cycles/<id>/archive")
def archive_cycle(id):
    require_role("PlatformAdmin")
    c = db.cycles.get(id)
    if not c:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    if c["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, f"cycle in status {c['status']}")
    before = s_cycle(c)
    c["status"] = "ARCHIVED"
    stamp_update(c)
    # Cascade: every objective in cycle -> ARCHIVED
    archived_obj_ids = set()
    for o in db.objectives.values():
        if o["cycle_id"] == id and o["status"] != "ARCHIVED":
            ob_before = s_objective(o)
            o["status"] = "ARCHIVED"
            stamp_update(o)
            archived_obj_ids.add(o["id"])
            write_audit(entity_type="OBJECTIVE", entity_id=o["id"],
                        action="STATE_TRANSITION", before=ob_before, after=s_objective(o),
                        actor_override="SYSTEM", role_override="SYSTEM")
    # Cascade alignment links
    for l in db.alignment_links.values():
        if l["upstream_objective_id"] in archived_obj_ids or l["downstream_objective_id"] in archived_obj_ids:
            li_before = s_link(l)
            if l["status"] == "ACCEPTED":
                l["status"] = "BROKEN"
                stamp_update(l)
                write_audit(entity_type="ALIGNMENT_LINK", entity_id=l["id"],
                            action="STATE_TRANSITION", before=li_before, after=s_link(l),
                            actor_override="SYSTEM", role_override="SYSTEM")
            elif l["status"] == "PENDING":
                l["status"] = "REJECTED"
                l["rejection_reason"] = "cycle_archived"
                stamp_update(l)
                write_audit(entity_type="ALIGNMENT_LINK", entity_id=l["id"],
                            action="STATE_TRANSITION", before=li_before, after=s_link(l),
                            actor_override="SYSTEM", role_override="SYSTEM")
    _audit_cycle(c, "STATE_TRANSITION", before=before, after=s_cycle(c))
    return success_object(s_cycle(c))
