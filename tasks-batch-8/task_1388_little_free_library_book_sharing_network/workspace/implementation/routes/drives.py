"""Book drive endpoints (PRD §3.7) — fork-join dual approval."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    raise_body_ref_err,
    ERR_DRIVE_NOT_FOUND,
    ERR_DRIVE_WINDOW_INVALID,
    ERR_DRIVE_WINDOW_OVERLAP,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SCHOOL_NOT_ACTIVE,
    ERR_SCHOOL_NOT_FOUND,
    ERR_STEWARD_NOT_ACTIVE,
    ERR_UNGRADED_ITEMS,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_drive
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_enum,
    require_int,
    sort_by_created_at,
)

bp = Blueprint("drives", __name__)

DECISIONS = {"APPROVE", "REJECT"}
DRIVE_TARGET_STATUSES = {"COLLECTION_CLOSED", "COMPLETED", "CANCELLED"}


def _load_drive(drive_id: str) -> dict:
    drive = db.drives.get(drive_id)
    if drive is None:
        raise_err(ERR_DRIVE_NOT_FOUND, "No book drive with the given id")
    return drive


def _create_linked_batch(drive: dict) -> dict:
    """The fork-join join mints the drive's linked DonationBatch (§3.7)."""
    school = db.schools.get(drive["school_id"])
    batch = {
        "source_type": "BOOK_DRIVE",
        "drive_id": drive["id"],
        "region_code": school["region_code"] if school else None,
        "status": "RECEIVED",
    }
    db.stamp_new(batch)
    db.batches[batch["id"]] = batch
    drive["_linked_batch_id"] = batch["id"]
    return batch


@bp.route("/library-network/drives", methods=["POST"])
@require_roles("Steward")
def create_drive(_user_id, _role):
    body = get_json_body()
    school_id = body.get("school_id")

    # Cross-entity gate (stage 6): the proposing steward must be ACTIVE.
    steward = db.stewards.get(_user_id) if _user_id else None
    if steward is None or steward["status"] != "ACTIVE":
        raise_err(ERR_STEWARD_NOT_ACTIVE, "Proposing steward is not ACTIVE")

    # Body referential integrity (stage 4).
    school = None
    if isinstance(school_id, str):
        school = db.schools.get(school_id)
        if school is None:
            raise_body_ref_err(ERR_SCHOOL_NOT_FOUND, "No school with the given id")

    # School must be ACTIVE (ERR_SCHOOL_NOT_ACTIVE, 422).
    if school is not None and school["status"] != "ACTIVE":
        raise_err(ERR_SCHOOL_NOT_ACTIVE, "School is not ACTIVE")

    # Temporal rules (stage 8).
    starts_raw = body.get("starts_at")
    ends_raw = body.get("ends_at")
    starts_at = ends_at = None
    if isinstance(starts_raw, str) and isinstance(ends_raw, str):
        try:
            starts_at = parse_iso8601(starts_raw, "starts_at")
            ends_at = parse_iso8601(ends_raw, "ends_at")
        except Exception:
            starts_at = ends_at = None  # malformed — schema stage reports it
    if starts_at is not None and ends_at is not None:
        if not (starts_at < ends_at):
            raise_err(ERR_DRIVE_WINDOW_INVALID, "starts_at must be strictly before ends_at")
        if school is not None:
            for other in db.drives.values():
                if other["school_id"] != school["id"]:
                    continue
                if other["status"] not in domain.NON_TERMINAL_DRIVE_STATUSES:
                    continue
                o_start = db.parse_iso(other["starts_at"])
                o_end = db.parse_iso(other["ends_at"])
                # Half-open [starts_at, ends_at) overlap; zero-gap adjacency allowed.
                if starts_at < o_end and o_start < ends_at:
                    raise_err(ERR_DRIVE_WINDOW_OVERLAP, "Drive window overlaps another drive of the school")

    # Schema (stage 11).
    if not isinstance(school_id, str) or school_id == "":
        raise_err(ERR_INVALID_REQUEST, "Field school_id must be a non-empty string")
    goal_books = require_int(body, "goal_books", minimum=1)
    starts_dt = parse_iso8601(body.get("starts_at"), "starts_at")
    ends_dt = parse_iso8601(body.get("ends_at"), "ends_at")

    drive = {
        "school_id": school_id,
        "coordinator_steward_id": _user_id,
        "goal_books": goal_books,
        "starts_at": db.format_iso(starts_dt),
        "ends_at": db.format_iso(ends_dt),
        "status": "PROPOSED",
        "school_approval_status": "PENDING",
        "network_approval_status": "PENDING",
        "_linked_batch_id": None,
    }
    db.stamp_new(drive)
    db.drives[drive["id"]] = drive
    return success_object(serialize_drive(drive), 201)


@bp.route("/library-network/drives", methods=["GET"])
@require_roles("Steward", "SchoolLiaison", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_drives(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_drive(d) for d in sort_by_created_at(list(db.drives.values()))]
    items = apply_filters(items, ["school_id", "coordinator_steward_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/drives/<drive_id>", methods=["GET"])
@require_roles("Steward", "SchoolLiaison", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_drive(drive_id: str, _user_id, _role):
    return success_object(serialize_drive(_load_drive(drive_id)))


def _apply_decision(drive: dict, dimension: str, decision: str) -> None:
    """One approval dimension moves; the join fires when both are APPROVED."""
    if decision == "REJECT":
        drive[dimension] = "REJECTED"
        drive["status"] = "REJECTED"
    else:
        drive[dimension] = "APPROVED"
        if (
            drive["school_approval_status"] == "APPROVED"
            and drive["network_approval_status"] == "APPROVED"
        ):
            drive["status"] = "APPROVED"
            _create_linked_batch(drive)
    db.touch(drive)


@bp.route("/library-network/drives/<drive_id>/school-decision", methods=["POST"])
@require_roles("SchoolLiaison")
def school_decision(drive_id: str, _user_id, _role):
    drive = _load_drive(drive_id)
    # Ownership (stage 2): the liaison may decide only their own school's drives.
    if _user_id != drive["school_id"]:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "SchoolLiaison may only decide their own school's drives")
    if drive["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "Drive is not in PROPOSED status")
    decision = require_enum(get_json_body(), "decision", DECISIONS)
    _apply_decision(drive, "school_approval_status", decision)
    return success_object(serialize_drive(drive))


@bp.route("/library-network/drives/<drive_id>/network-decision", methods=["POST"])
@require_roles("NetworkAdmin")
def network_decision(drive_id: str, _user_id, _role):
    drive = _load_drive(drive_id)
    if drive["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "Drive is not in PROPOSED status")
    decision = require_enum(get_json_body(), "decision", DECISIONS)
    _apply_decision(drive, "network_approval_status", decision)
    return success_object(serialize_drive(drive))


@bp.route("/library-network/drives/<drive_id>/status", methods=["POST"])
@require_roles("Steward", "NetworkAdmin")
def drive_status(drive_id: str, _user_id, _role):
    drive = _load_drive(drive_id)

    # Ownership (stage 2): a steward actor must be the drive coordinator.
    if _role == "Steward" and _user_id != drive["coordinator_steward_id"]:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only act on drives they coordinate")

    body = get_json_body()
    target = body.get("target_status")

    # State preconditions (stage 5) per target.
    if target == "COLLECTION_CLOSED":
        if drive["status"] != "OPEN":
            raise_err(ERR_INVALID_STATE, "Drive is not in OPEN status")
    elif target == "COMPLETED":
        if drive["status"] != "COLLECTION_CLOSED":
            raise_err(ERR_INVALID_STATE, "Drive is not in COLLECTION_CLOSED status")
    elif target == "CANCELLED":
        if drive["status"] not in ("PROPOSED", "APPROVED", "OPEN"):
            raise_err(ERR_INVALID_STATE, "Drive cannot be cancelled from its current state")

    # Schema (stage 11).
    target = require_enum(body, "target_status", DRIVE_TARGET_STATUSES)

    if target == "COLLECTION_CLOSED":
        drive["status"] = "COLLECTION_CLOSED"
        db.touch(drive)
    elif target == "COMPLETED":
        # Business constraint (stage 9): the linked batch must be fully graded.
        batch = domain.drive_linked_batch(drive)
        if batch is not None:
            item_count, graded_count = domain.batch_counters(batch)
            if graded_count != item_count:
                raise_err(ERR_UNGRADED_ITEMS, "Linked batch has ungraded items")
        drive["status"] = "COMPLETED"
        db.touch(drive)
        # Recognition: +150 when the drive qualifies for its bonus, else +50.
        metrics = domain.drive_metrics(drive)
        points = 150 if metrics["qualifies_for_bonus"] else 50
        domain.add_recognition_event(
            drive["coordinator_steward_id"], "DRIVE_COMPLETED", points, "BOOK_DRIVE", drive["id"]
        )
    elif target == "CANCELLED":
        previous = drive["status"]
        drive["status"] = "CANCELLED"
        db.touch(drive)
        if previous in ("APPROVED", "OPEN"):
            # Close the linked batch and write off its AVAILABLE books.
            batch = domain.drive_linked_batch(drive)
            if batch is not None and batch["status"] != "CLOSED":
                for item in list(db.book_items.values()):
                    if item["batch_id"] == batch["id"] and item["status"] == "AVAILABLE":
                        item["status"] = "RECYCLED"
                        db.touch(item)
                batch["status"] = "CLOSED"
                db.touch(batch)
    return success_object(serialize_drive(drive))
