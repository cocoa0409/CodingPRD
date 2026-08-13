"""Library box endpoints (PRD §3.3 / §3.4)."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    raise_body_ref_err,
    ERR_BOX_LIMIT_REACHED,
    ERR_BOX_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INSPECTION_REQUIRED,
    ERR_INSPECTION_TOO_SOON,
    ERR_STEWARD_NOT_ACTIVE,
    ERR_STEWARD_NOT_FOUND,
    ERR_UNAUTHORIZED_ROLE,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_box, serialize_inspection
from util import (
    apply_filters,
    get_json_body,
    optional_string,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_number,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("boxes", __name__)

INSPECTION_RESULTS = {"CONFIRMED", "NOT_FOUND", "FAILED_CONDITION"}
BOX_TARGET_STATUSES = {"CHARTERED", "ACTIVE", "SUSPENDED", "DECOMMISSIONED"}
# Role-restricted transition targets on POST /boxes/{id}/status (§2.1).
ADMIN_ONLY_TARGETS = {"CHARTERED", "SUSPENDED", "DECOMMISSIONED"}


def _load_box(box_id: str) -> dict:
    box = db.boxes.get(box_id)
    if box is None:
        raise_err(ERR_BOX_NOT_FOUND, "No box with the given id")
    return box


@bp.route("/library-network/boxes", methods=["POST"])
@require_roles("Steward", "NetworkAdmin")
def create_box(_user_id, _role):
    body = get_json_body()
    steward_id = body.get("steward_id")

    # Ownership (stage 2): a steward may propose boxes only for themself.
    if _role == "Steward" and isinstance(steward_id, str) and steward_id != _user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only propose boxes for themself")

    # Body referential integrity (stage 4).
    steward = None
    if isinstance(steward_id, str):
        steward = db.stewards.get(steward_id)
        if steward is None:
            raise_body_ref_err(ERR_STEWARD_NOT_FOUND, "No steward with the given id")

    # Cross-entity gate (stage 6): the proposing steward must be ACTIVE.
    if steward is not None and steward["status"] != "ACTIVE":
        raise_err(ERR_STEWARD_NOT_ACTIVE, "Steward is not ACTIVE")

    # Business constraint (stage 9): recognition-tier box capacity.
    if steward is not None:
        rec = domain.steward_recognition(steward)
        limit = domain.TIER_LIMITS[rec["recognition_tier"]]
        current = sum(
            1 for b in db.boxes.values()
            if b["steward_id"] == steward["id"]
            and b["charter_status"] in ("DRAFT", "CHARTERED", "ACTIVE", "SUSPENDED")
        )
        if current >= limit:
            raise_err(ERR_BOX_LIMIT_REACHED, "Steward is at their box capacity limit")

    # Schema (stage 11).
    steward_id = require_string(body, "steward_id")
    name = require_string(body, "name")
    latitude = require_number(body, "latitude", minimum=-90, maximum=90)
    longitude = require_number(body, "longitude", minimum=-180, maximum=180)
    capacity_books = require_int(body, "capacity_books", minimum=1)
    region_code = require_string(body, "region_code")

    box = {
        "steward_id": steward_id,
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "capacity_books": capacity_books,
        "region_code": region_code,
        "charter_number": None,
        "charter_status": "DRAFT",
        "listing_posture": "UNLISTED",
        "installed_at": None,
        "suspended_at": None,
        "last_activity_at": None,
    }
    db.stamp_new(box)
    db.boxes[box["id"]] = box
    return success_object(serialize_box(box), 201)


@bp.route("/library-network/boxes", methods=["GET"])
@require_roles("Anonymous", "Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_boxes(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_box(b) for b in sort_by_created_at(list(db.boxes.values()))]
    items = apply_filters(items, ["steward_id", "charter_status", "listing_posture", "region_code"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/boxes/<box_id>", methods=["GET"])
@require_roles("Anonymous", "Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_box(box_id: str, _user_id, _role):
    return success_object(serialize_box(_load_box(box_id)))


@bp.route("/library-network/boxes/<box_id>/status", methods=["POST"])
@require_roles("Steward", "NetworkAdmin")
def box_status_transition(box_id: str, _user_id, _role):
    body = get_json_body()
    target = body.get("target_status")

    # Role-restricted transition targets (stage 2, §2.1): only NetworkAdmin may
    # request CHARTERED / SUSPENDED / DECOMMISSIONED; a Steward may request only
    # ACTIVE, and only on their own suspended box.
    if _role == "Steward" and isinstance(target, str) and target in ADMIN_ONLY_TARGETS:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Only NetworkAdmin may request this target_status")

    box = _load_box(box_id)

    # Ownership (stage 2): steward reactivation applies only to their own box.
    if _role == "Steward" and box["steward_id"] != _user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only act on their own boxes")

    steward = db.stewards.get(box["steward_id"])

    # State preconditions and cross-entity gates per target (stages 5-6).
    if target == "CHARTERED":
        if box["charter_status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "Box is not in DRAFT status")
        if steward is None or steward["status"] != "ACTIVE":
            raise_err(ERR_STEWARD_NOT_ACTIVE, "Owning steward is not ACTIVE")
    elif target == "ACTIVE":
        if box["charter_status"] == "CHARTERED":
            confirmed = any(
                r["box_id"] == box_id and r["result"] == "CONFIRMED"
                for r in db.inspections.values()
            )
            if not confirmed:
                raise_err(ERR_INSPECTION_REQUIRED, "A CONFIRMED inspection is required")
            if steward is None or steward["status"] != "ACTIVE":
                raise_err(ERR_STEWARD_NOT_ACTIVE, "Owning steward is not ACTIVE")
        elif box["charter_status"] == "SUSPENDED":
            # Reactivation requires a CONFIRMED inspection created strictly
            # after suspended_at.
            suspended_at = box.get("suspended_at")
            fresh = any(
                r["box_id"] == box_id
                and r["result"] == "CONFIRMED"
                and suspended_at is not None
                and db.parse_iso(r["created_at"]) > db.parse_iso(suspended_at)
                for r in db.inspections.values()
            )
            if not fresh:
                raise_err(ERR_INSPECTION_REQUIRED, "A fresh CONFIRMED inspection is required")
        else:
            raise_err(ERR_INVALID_STATE, "Box cannot transition to ACTIVE from its current state")
    elif target == "SUSPENDED":
        if box["charter_status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE, "Box is not in ACTIVE status")
    elif target == "DECOMMISSIONED":
        if box["charter_status"] not in ("CHARTERED", "ACTIVE", "SUSPENDED"):
            raise_err(ERR_INVALID_STATE, "Box cannot be decommissioned from its current state")
    # Schema (stage 11): target_status present and a valid member.
    target = require_enum(body, "target_status", BOX_TARGET_STATUSES)

    # ---- Apply the transition ----
    if target == "CHARTERED":
        previously_chartered = sum(
            1 for b in db.boxes.values() if b.get("charter_number") is not None
        )
        box["charter_number"] = f"CH-{previously_chartered + 1:06d}"
        box["charter_status"] = "CHARTERED"
        db.touch(box)
    elif target == "ACTIVE":
        now_iso = db.now_logical_iso()
        if box["charter_status"] == "CHARTERED":
            box["charter_status"] = "ACTIVE"
            box["installed_at"] = now_iso
            box["last_activity_at"] = now_iso
            box["listing_posture"] = "LISTED"  # activation lists directly (§3.3)
            db.touch(box)
        else:  # SUSPENDED -> ACTIVE reactivation
            box["charter_status"] = "ACTIVE"
            box["suspended_at"] = None
            box["last_activity_at"] = now_iso
            db.touch(box)
            domain.recompute_posture(box)  # from live conditions (§3.3)
    elif target == "SUSPENDED":
        domain.suspend_box(box)
    elif target == "DECOMMISSIONED":
        if box["charter_status"] == "CHARTERED":
            box["charter_status"] = "DECOMMISSIONED"
            box["listing_posture"] = "DELISTED"
            db.touch(box)
        else:
            domain.decommission_box(box)
    return success_object(serialize_box(box))


@bp.route("/library-network/boxes/<box_id>/inspections", methods=["POST"])
@require_roles("Moderator", "NetworkAdmin")
def create_inspection(box_id: str, _user_id, _role):
    box = _load_box(box_id)
    body = get_json_body()
    result = body.get("result")

    # State precondition (stage 5).
    if box["charter_status"] not in ("CHARTERED", "ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "Box cannot be inspected in its current state")

    # Temporal rule (stage 8): CONFIRMED inspections need a 30-day gap.
    if result == "CONFIRMED":
        previous = [
            r for r in db.inspections.values()
            if r["box_id"] == box_id and r["result"] == "CONFIRMED"
        ]
        if previous:
            latest = max(db.parse_iso(r["created_at"]) for r in previous)
            if (db.clock() - latest) < timedelta(days=30):
                raise_err(
                    ERR_INSPECTION_TOO_SOON,
                    "A CONFIRMED inspection requires 30 days since the previous one",
                )

    # Schema (stage 11).
    result = require_enum(body, "result", INSPECTION_RESULTS)
    notes = optional_string(body, "notes")

    record = {
        "box_id": box_id,
        "inspector_user_id": _user_id,
        "result": result,
        "notes": notes,
    }
    db.stamp_new_light(record)
    db.inspections[record["id"]] = record

    if result == "CONFIRMED":
        domain.refresh_box_activity(box)
    elif result == "NOT_FOUND":
        if box["charter_status"] == "ACTIVE":
            domain.suspend_box(box)
        # CHARTERED / SUSPENDED: stored with no charter change.
    elif result == "FAILED_CONDITION":
        now = db.clock()
        request_ = {
            "box_id": box_id,
            "category": "WEAR",
            "description": "Spawned from FAILED_CONDITION inspection",
            "severity": None,
            "status": "REPORTED",
            "season_at_report": domain.season_for(now),
            "season_multiplier": 2.0 if domain.season_for(now) == "WINTER" else 1.0,
            "sla_deadline_at": None,
            "triaged_at": None,
            "scheduled_date": None,
            "resolved_at": None,
            "resolution_count": 0,
            "reimbursement_cents": None,
            "sla_breached": False,
        }
        db.stamp_new(request_)
        db.maintenance_requests[request_["id"]] = request_
        domain.recompute_posture(box)

    return success_object(serialize_inspection(record), 201)


@bp.route("/library-network/boxes/<box_id>/inspections", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_inspections(box_id: str, _user_id, _role):
    _load_box(box_id)
    limit, offset = parse_pagination()
    items = [
        serialize_inspection(r)
        for r in sort_by_created_at(list(db.inspections.values()))
        if r["box_id"] == box_id
    ]
    items = apply_filters(items, ["result"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
