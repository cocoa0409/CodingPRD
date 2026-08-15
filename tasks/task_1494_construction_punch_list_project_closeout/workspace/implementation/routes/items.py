"""Punch items (PRD 3.2 intake, 3.3 correction / re-inspection / sign-off)."""
from flask import Blueprint

from authz import (
    GCPM, GCINSP, SUBREP, ALL_ROLES, require_roles, check_responsible_party,
)
from db import store
from derived import maybe_advance_project, recompute_project, recompute_trade
from errors import (
    invalid_request, invalid_state, segregation_of_duties, trade_not_in_project,
    verification_escalated, walk_incomplete, walk_not_in_project,
)
from respond import success
from serialize import ser_item
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, query_filters,
    req_enum, req_str, sorted_by_creation, touch,
)

bp = Blueprint("items", __name__, url_prefix="/closeout")

SEVERITIES = ("LIFE_SAFETY", "MAJOR", "MINOR")

# The five working phases in which item transitions are allowed (PRD 3.3).
WORKING_PHASES = (
    "PUNCH_ACTIVE", "SC_REVIEW", "SUBSTANTIALLY_COMPLETE",
    "CLOSEOUT_IN_PROGRESS", "FINAL_RELEASE_PENDING",
)


@bp.route("/punch-items", methods=["POST"])
def create_item():
    require_roles([GCINSP, GCPM])
    data = json_body()
    project_id = req_str(data, "project_id")
    trade_package_id = req_str(data, "trade_package_id")
    title = req_str(data, "title")
    severity = req_enum(data, "severity", SEVERITIES)
    location_building = req_str(data, "location_building")
    location_floor = req_str(data, "location_floor")
    location_area = req_str(data, "location_area")
    photo_ref = req_str(data, "photo_ref")  # photo attachment is mandatory
    walk_id = data.get("punch_walk_id")
    if walk_id is not None and (isinstance(walk_id, bool) or not isinstance(walk_id, str)):
        raise invalid_request("punch_walk_id must be a string")
    p = get_or_404(store.projects, project_id)
    t = get_or_404(store.trade_packages, trade_package_id)
    w = get_or_404(store.punch_walks, walk_id) if walk_id is not None else None
    # State (priority 8) precedes cross-reference integrity (priority 12).
    if p["status"] != "PUNCH_ACTIVE":
        raise invalid_state("Punch items may only be created while PUNCH_ACTIVE")
    if t["project_id"] != project_id:
        raise trade_not_in_project()
    if w is not None and w["project_id"] != project_id:
        raise walk_not_in_project()
    item = {
        "id": new_id(),
        "_seq": next(store.seq),
        "project_id": project_id,
        "trade_package_id": trade_package_id,
        "punch_walk_id": walk_id,
        "title": title,
        "severity": severity,
        "location_building": location_building,
        "location_floor": location_floor,
        "location_area": location_area,
        "photo_ref": photo_ref,
        "status": "OPEN",
        "ready_by_user_id": None,
        "ready_at": None,
        "verified_by_user_id": None,
        "rejection_count": 0,
        "rejection_reason": None,
    }
    item.update(new_common_fields())
    store.punch_items[item["id"]] = item
    # A new item immediately blocks: counters rise and flags recompute (PRD 3.2).
    recompute_trade(t)
    recompute_project(p)
    return success(ser_item(item), status=201)


@bp.route("/punch-items/<iid>", methods=["GET"])
def get_item(iid):
    require_roles(ALL_ROLES)
    return success(ser_item(get_or_404(store.punch_items, iid)))


@bp.route("/punch-items", methods=["GET"])
def list_items():
    require_roles(ALL_ROLES)
    filters = query_filters(
        "project_id", "trade_package_id", "status", "severity", "punch_walk_id")
    items = [i for i in store.punch_items.values()
             if all(i[k] == v for k, v in filters.items())]
    page, pagination = paginate(sorted_by_creation(items))
    return success([ser_item(i) for i in page], response_type="array",
                   pagination=pagination)


@bp.route("/punch-items/<iid>/mark-ready", methods=["POST"])
def mark_ready(iid):
    uid, role = require_roles([SUBREP, GCPM])
    item = get_or_404(store.punch_items, iid)
    t = store.trade_packages[item["trade_package_id"]]
    # Priority 3: responsible-party ownership (PRD 2.1).
    check_responsible_party(uid, role, t)
    p = store.projects[item["project_id"]]
    if p["status"] not in WORKING_PHASES:
        raise invalid_state("The project is not in a working phase")
    if item["status"] != "OPEN":
        raise invalid_state("Only an OPEN item can be marked ready")
    if not t["has_completed_walk"]:
        raise walk_incomplete()
    item["status"] = "READY_FOR_REVIEW"
    item["ready_by_user_id"] = uid
    item["ready_at"] = store.clock
    touch(item)
    return success(ser_item(item))


@bp.route("/punch-items/<iid>/verify", methods=["POST"])
def verify_item(iid):
    uid, role = require_roles([GCINSP, GCPM])
    item = get_or_404(store.punch_items, iid)
    # Priority 4: segregation of duties, then the rejection-count escalation.
    if uid == item["ready_by_user_id"]:
        raise segregation_of_duties()
    if item["rejection_count"] >= 2 and role != GCPM:
        raise verification_escalated()
    p = store.projects[item["project_id"]]
    if p["status"] not in WORKING_PHASES:
        raise invalid_state("The project is not in a working phase")
    if item["status"] != "READY_FOR_REVIEW":
        raise invalid_state("Only a READY_FOR_REVIEW item can be verified")
    item["status"] = "VERIFIED"
    item["verified_by_user_id"] = uid
    touch(item)
    # Counters fall; closeout_ready recomputes; the cascade may advance the
    # project to FINAL_RELEASE_PENDING (PRD 3.5).
    t = store.trade_packages[item["trade_package_id"]]
    recompute_trade(t)
    recompute_project(p)
    maybe_advance_project(p)
    return success(ser_item(item))


@bp.route("/punch-items/<iid>/reject", methods=["POST"])
def reject_item(iid):
    require_roles([GCINSP])
    data = json_body()
    reason = req_str(data, "reason")
    item = get_or_404(store.punch_items, iid)
    p = store.projects[item["project_id"]]
    if p["status"] not in WORKING_PHASES:
        raise invalid_state("The project is not in a working phase")
    if item["status"] != "READY_FOR_REVIEW":
        raise invalid_state("Only a READY_FOR_REVIEW item can be rejected")
    item["status"] = "OPEN"
    item["rejection_count"] += 1
    item["rejection_reason"] = reason
    item["ready_by_user_id"] = None
    touch(item)
    return success(ser_item(item))


@bp.route("/punch-items/<iid>/void", methods=["POST"])
def void_item(iid):
    require_roles([GCPM])
    item = get_or_404(store.punch_items, iid)
    p = store.projects[item["project_id"]]
    if p["status"] != "PUNCH_ACTIVE":
        raise invalid_state("Items may only be voided while PUNCH_ACTIVE")
    if item["status"] != "OPEN":
        raise invalid_state("Only an OPEN item can be voided")
    item["status"] = "VOIDED"
    touch(item)
    # Voiding releases the blocking counters (PRD 3.3).
    t = store.trade_packages[item["trade_package_id"]]
    recompute_trade(t)
    recompute_project(p)
    return success(ser_item(item))
