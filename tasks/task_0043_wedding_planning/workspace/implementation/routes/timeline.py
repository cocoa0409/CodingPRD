"""TimelineSlot routes."""
from flask import Blueprint, request

import db
from errors import (
    raise_error,
    ERR_TIMELINE_VENDOR_NOT_CONTRACTED,
    ERR_VERSION_CONFLICT,
)
from middleware import require_roles, check_planner_owns_project
from response import success, list_response, parse_pagination
from services.lookup import (
    get_project,
    get_timeline_slot,
    assert_project_not_terminal,
)
from services.timeline import check_overlap_rules


bp = Blueprint("timeline", __name__)


def _vendor_has_accepted_contract(project_id, vendor_id) -> bool:
    for c in db.contracts.values():
        if c["project_id"] == project_id and c["vendor_id"] == vendor_id and c["contract_status"] == "ACCEPTED":
            return True
    return False


@bp.post("/wedding-projects/<project_id>/timeline-slots")
def create_slot(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    body = request.get_json(silent=True) or {}
    slot = {
        "project_id": project_id,
        "vendor_id": body.get("vendor_id"),
        "start_at": int(body.get("start_at")) if body.get("start_at") is not None else None,
        "end_at": int(body.get("end_at")) if body.get("end_at") is not None else None,
        "setup_buffer_seconds": int(body.get("setup_buffer_seconds", 0) or 0),
        "kind": body.get("kind") or "CEREMONY",
        "label": body.get("label"),
    }
    if slot["vendor_id"] is not None:
        if not _vendor_has_accepted_contract(project_id, slot["vendor_id"]):
            raise_error(ERR_TIMELINE_VENDOR_NOT_CONTRACTED,
                        "Vendor has no ACCEPTED Contract on this project")
    # Overlap rules
    check_overlap_rules(project_id, slot, exclude_id=None)
    db.add_common_create(slot)
    db.timeline_slots[slot["id"]] = slot
    return success(slot, status=201)


@bp.get("/wedding-projects/<project_id>/timeline-slots")
def list_slots(project_id):
    require_roles("Planner", "Auditor", "Couple", "VendorRep")
    get_project(project_id)
    limit, offset = parse_pagination(request.args)
    kind = request.args.get("kind")
    vendor_id = request.args.get("vendor_id")
    items = [s for s in db.timeline_slots.values() if s["project_id"] == project_id]
    if kind:
        items = [s for s in items if s.get("kind") == kind]
    if vendor_id:
        items = [s for s in items if s.get("vendor_id") == vendor_id]
    items.sort(key=lambda s: s["created_at"])
    return list_response(items, limit, offset)


@bp.patch("/wedding-projects/<project_id>/timeline-slots/<slot_id>")
def patch_slot(project_id, slot_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    s = get_timeline_slot(project_id, slot_id)
    body = request.get_json(silent=True) or {}
    candidate = dict(s)
    if "start_at" in body:
        candidate["start_at"] = int(body["start_at"])
    if "end_at" in body:
        candidate["end_at"] = int(body["end_at"])
    if "setup_buffer_seconds" in body:
        candidate["setup_buffer_seconds"] = int(body["setup_buffer_seconds"] or 0)
    if "label" in body:
        candidate["label"] = body["label"]
    new_version = body.get("version")
    # Overlap re-validate
    check_overlap_rules(project_id, candidate, exclude_id=slot_id)
    # OCC last
    if new_version is not None and int(new_version) != int(s["version"]):
        raise_error(ERR_VERSION_CONFLICT, "Version mismatch")
    s.update({k: candidate[k] for k in ("start_at", "end_at", "setup_buffer_seconds", "label")})
    db.bump(s)
    return success(s)


@bp.delete("/wedding-projects/<project_id>/timeline-slots/<slot_id>")
def delete_slot(project_id, slot_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    get_timeline_slot(project_id, slot_id)
    del db.timeline_slots[slot_id]
    return success({}, status=204)


@bp.post("/wedding-projects/<project_id>/timeline/snapshot-rehearsal")
def snapshot_rehearsal(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    p["rehearsal_version"] = int(p["rehearsal_version"]) + 1
    db.bump(p)
    return success(p)
