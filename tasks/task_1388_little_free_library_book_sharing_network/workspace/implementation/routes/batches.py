"""Donation batch endpoints and bulk item intake (PRD §3.8)."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    raise_body_ref_err,
    ERR_BATCH_NOT_FOUND,
    ERR_CONTENT_POLICY_VIOLATION,
    ERR_DRIVE_LINK_FORBIDDEN,
    ERR_DRIVE_LINK_REQUIRED,
    ERR_DRIVE_NOT_APPROVED,
    ERR_DRIVE_NOT_FOUND,
    ERR_DRIVE_NOT_OPEN,
    ERR_DRIVE_WINDOW_CLOSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_UNGRADED_ITEMS,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_batch, serialize_item, serialize_run
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_list,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("batches", __name__)

SOURCE_TYPES = {"PUBLIC_DROP", "STEWARD_TRANSFER", "BOOK_DRIVE"}
GRADES = {"A", "B", "C"}


def _load_batch(batch_id: str) -> dict:
    batch = db.batches.get(batch_id)
    if batch is None:
        raise_err(ERR_BATCH_NOT_FOUND, "No donation batch with the given id")
    return batch


@bp.route("/library-network/batches", methods=["POST"])
@require_roles("HubCoordinator", "NetworkAdmin")
def create_batch(_user_id, _role):
    body = get_json_body()
    source_type = body.get("source_type")
    drive_id = body.get("drive_id")

    # Body referential integrity (stage 4): the drive link shape rules.
    drive = None
    if source_type == "BOOK_DRIVE" and (drive_id is None):
        raise_err(ERR_DRIVE_LINK_REQUIRED, "source_type BOOK_DRIVE requires drive_id")
    if source_type in ("PUBLIC_DROP", "STEWARD_TRANSFER") and drive_id is not None:
        raise_err(ERR_DRIVE_LINK_FORBIDDEN, "drive_id is forbidden for this source_type")
    if drive_id is not None:
        if not isinstance(drive_id, str) or drive_id not in db.drives:
            raise_body_ref_err(ERR_DRIVE_NOT_FOUND, "No book drive with the given id")
        drive = db.drives[drive_id]

    # Cross-entity gate (stage 6): the linked drive must be APPROVED or OPEN.
    if drive is not None and drive["status"] not in ("APPROVED", "OPEN"):
        raise_err(ERR_DRIVE_NOT_APPROVED, "Linked drive is not APPROVED or OPEN")

    # Schema (stage 11).
    source_type = require_enum(body, "source_type", SOURCE_TYPES)
    region_code = require_string(body, "region_code")
    if source_type == "BOOK_DRIVE" and drive_id is None:
        raise_err(ERR_DRIVE_LINK_REQUIRED, "source_type BOOK_DRIVE requires drive_id")
    if source_type != "BOOK_DRIVE" and drive_id is not None:
        raise_err(ERR_DRIVE_LINK_FORBIDDEN, "drive_id is forbidden for this source_type")

    batch = {
        "source_type": source_type,
        "drive_id": drive_id if source_type == "BOOK_DRIVE" else None,
        "region_code": region_code,
        "status": "RECEIVED",
    }
    db.stamp_new(batch)
    db.batches[batch["id"]] = batch
    # If this batch links a drive that has no linked batch yet, adopt it.
    if drive is not None and not drive.get("_linked_batch_id"):
        drive["_linked_batch_id"] = batch["id"]
    return success_object(serialize_batch(batch), 201)


@bp.route("/library-network/batches", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_batches(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_batch(b) for b in sort_by_created_at(list(db.batches.values()))]
    items = apply_filters(items, ["drive_id", "source_type", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/batches/<batch_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_batch(batch_id: str, _user_id, _role):
    return success_object(serialize_batch(_load_batch(batch_id)))


@bp.route("/library-network/batches/<batch_id>/items", methods=["POST"])
@require_roles("HubCoordinator", "NetworkAdmin")
def bulk_intake(batch_id: str, _user_id, _role):
    """Bulk best-effort intake: every element is judged on its own (§3.8)."""
    batch = _load_batch(batch_id)

    # State preconditions (stage 5).
    if batch["status"] != "RECEIVED":
        raise_err(ERR_INVALID_STATE, "Batch is not in RECEIVED status")
    drive = None
    if batch.get("drive_id"):
        drive = db.drives.get(batch["drive_id"])
        if drive is not None and drive["status"] != "OPEN":
            raise_err(ERR_DRIVE_NOT_OPEN, "The linked drive is not OPEN")

    # Temporal rule (stage 8): intake only before the drive's ends_at.
    if drive is not None and db.clock() >= db.parse_iso(drive["ends_at"]):
        raise_err(ERR_DRIVE_WINDOW_CLOSED, "The drive collection window has closed")

    # Schema (stage 11) for the envelope of the request itself.
    items = require_list(get_json_body(), "items")

    school = db.schools.get(drive["school_id"]) if drive is not None else None
    restricted = set(school.get("restricted_categories", [])) if school else set()

    created_ids: list[str] = []
    rejected: list[dict] = []
    now = db.clock()
    for index, element in enumerate(items):
        # Per-item judgment: malformed entries fail individually.
        if not isinstance(element, dict):
            rejected.append({"index": index, "error_id": ERR_INVALID_REQUEST})
            continue
        title = element.get("title")
        category = element.get("category")
        grade = element.get("condition_grade")
        if not isinstance(title, str) or title == "":
            rejected.append({"index": index, "error_id": ERR_INVALID_REQUEST})
            continue
        if not isinstance(category, str) or category not in domain.BOOK_CATEGORIES:
            rejected.append({"index": index, "error_id": ERR_INVALID_REQUEST})
            continue
        if grade is not None and grade not in GRADES:
            rejected.append({"index": index, "error_id": ERR_INVALID_REQUEST})
            continue
        # Content policy (stage 7): the school's forbidden categories.
        if category in restricted:
            rejected.append({"index": index, "error_id": ERR_CONTENT_POLICY_VIOLATION})
            continue
        item = {
            "batch_id": batch_id,
            "title": title,
            "category": category,
            "condition_grade": grade,
            "status": "AVAILABLE",
            "box_id": None,
        }
        db.stamp_new(item)
        # Monotonically increasing created_at in array order (§3.8).
        item["created_at"] = db.format_iso(now + timedelta(milliseconds=len(created_ids)))
        item["updated_at"] = item["created_at"]
        db.book_items[item["id"]] = item
        created_ids.append(item["id"])

    return success_object(
        {
            "created_count": len(created_ids),
            "created_item_ids": created_ids,
            "rejected": rejected,
        }
    )


@bp.route("/library-network/batches/<batch_id>/sort-complete", methods=["POST"])
@require_roles("HubCoordinator", "NetworkAdmin")
def sort_complete(batch_id: str, _user_id, _role):
    batch = _load_batch(batch_id)
    if batch["status"] != "RECEIVED":
        raise_err(ERR_INVALID_STATE, "Batch is not in RECEIVED status")
    item_count, graded_count = domain.batch_counters(batch)
    if graded_count != item_count:
        raise_err(ERR_UNGRADED_ITEMS, "Batch still holds ungraded items")
    batch["status"] = "SORTED"
    db.touch(batch)
    return success_object(serialize_batch(batch))


@bp.route("/library-network/batches/<batch_id>/distribution-runs", methods=["POST"])
@require_roles("HubCoordinator", "NetworkAdmin")
def create_distribution_run(batch_id: str, _user_id, _role):
    batch = _load_batch(batch_id)
    body = get_json_body()

    # State precondition (stage 5).
    if batch["status"] != "SORTED":
        raise_err(ERR_INVALID_STATE, "Batch is not in SORTED status")

    # Business constraint (stage 9): the selector must produce a non-empty plan.
    plan = domain.build_plan(batch)

    # OCC (stage 10): expected_batch_version is a non-optional input (§2.7).
    expected = body.get("expected_batch_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != batch["version"]:
            raise_err(ERR_STALE_VERSION, "expected_batch_version does not match the batch version")
    elif expected is not None:
        raise_err(ERR_INVALID_REQUEST, "Field expected_batch_version must be an integer")

    # Schema (stage 11).
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "Field expected_batch_version is required")

    # Creating a newer run supersedes any DRAFT run for the batch.
    for run in list(db.distribution_runs.values()):
        if run["batch_id"] == batch_id and run["status"] == "DRAFT":
            run["status"] = "SUPERSEDED"
            db.touch(run)

    run = {
        "batch_id": batch_id,
        "status": "DRAFT",
        "plan_snapshot": plan,
        "planned_item_count": sum(entry["quantity"] for entry in plan),
    }
    db.stamp_new(run)
    db.distribution_runs[run["id"]] = run
    # Creating the run itself advances the batch's version (§3.8).
    db.touch(batch)
    return success_object(serialize_run(run), 201)
