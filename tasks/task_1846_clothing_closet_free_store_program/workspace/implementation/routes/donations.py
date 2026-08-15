"""Donation intake, sorting, and grading (PRD 3.5)."""
from flask import Blueprint, g

import db
import services as svc
from db import stamp_new, store, touch
from errors import ApiError, invalid_state, not_found
from middleware import require_roles
from response import ok
from util import get_body, v_enum, v_int, v_str

bp = Blueprint("donations", __name__)


def get_batch_or_404(batch_id):
    b = store.batches.get(batch_id)
    if b is None:
        raise not_found("Donation batch not found")
    return b


@bp.post("/closet/donation-batches")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def create_batch():
    data = get_body()
    donor_name = v_str(data, "donor_name")
    declared = v_int(data, "item_count_declared", lo=1)
    donor_email = v_str(data, "donor_email", required=False)
    b = stamp_new({
        "donor_name": donor_name,
        "donor_email": donor_email,
        "item_count_declared": declared,
        "status": "RECEIVED",
        "sorted_by_user_id": None,
        "closed_by_user_id": None,
    })
    store.batches[b["id"]] = b
    return ok(svc.serialize_batch(b), 201)


@bp.get("/closet/donation-batches/<bid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_batch(bid):
    return ok(svc.serialize_batch(get_batch_or_404(bid)))


@bp.post("/closet/donation-batches/<bid>/start-sorting")
@require_roles("VolunteerLead", "Volunteer")
def start_sorting(bid):
    b = get_batch_or_404(bid)
    if b["status"] != "RECEIVED":
        raise invalid_state("Only a RECEIVED batch can start sorting")
    # Staffed-sorting requirement: a CHECKED_IN signup on a SORTING shift
    # (OPEN or LOCKED) whose window covers now.
    now = db.now()
    staffed = False
    for s in store.signups.values():
        if s["status"] != "CHECKED_IN":
            continue
        shift = store.shifts.get(s["shift_id"])
        if (
            shift is not None
            and shift["role_type"] == "SORTING"
            and shift["status"] in ("OPEN", "LOCKED")
            and shift["start_at"] <= now <= shift["end_at"]
        ):
            staffed = True
            break
    if not staffed:
        raise ApiError(
            "ERR_NO_SORTING_STAFF", 409,
            "No checked-in sorting staff on a SORTING shift covering now",
        )
    b["status"] = "IN_SORT"
    b["sorted_by_user_id"] = g.user_id
    touch(b)
    return ok(svc.serialize_batch(b))


@bp.post("/closet/donation-batches/<bid>/items")
@require_roles("VolunteerLead", "Volunteer")
def grade_item(bid):
    b = get_batch_or_404(bid)
    data = get_body()
    drive_id = data.get("drive_id")
    if drive_id is not None:
        if not isinstance(drive_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "drive_id must be a string")
        if drive_id not in store.drives:
            raise not_found("Special drive not found")
    category = v_enum(data, "category", svc.CATEGORIES)
    season = v_enum(data, "season", svc.SEASONS)
    grade = v_enum(data, "quality_grade", svc.GRADES)
    if b["status"] != "IN_SORT":
        raise invalid_state("Items can only be created while the batch is IN_SORT")
    item = stamp_new({
        "donation_batch_id": b["id"],
        "category": category,
        "season": season,
        "quality_grade": grade,
        "drive_id": drive_id,
        "status": "REJECTED" if grade == "REJECT" else "PENDING_STOCK",
        "storage_zone_id": None,
        "reserved_visit_id": None,
        "recycling_batch_id": None,
        "graded_by_user_id": g.user_id,
        "stocked_at": None,
        "distributed_at": None,
        "distributed_from_zone_id": None,
    })
    store.items[item["id"]] = item
    # Auto-advance IN_SORT -> SORTED once the declared count is reached.
    if (
        b["status"] == "IN_SORT"
        and svc.batch_items_created_count(b["id"]) >= b["item_count_declared"]
    ):
        b["status"] = "SORTED"
        touch(b)
    return ok(svc.serialize_item(item), 201)


@bp.post("/closet/donation-batches/<bid>/close")
@require_roles("ProgramAdmin", "VolunteerLead")
def close_batch(bid):
    b = get_batch_or_404(bid)
    if b["status"] != "SORTED":
        raise invalid_state("Only a SORTED batch can be closed")
    if b["sorted_by_user_id"] == g.user_id:
        raise ApiError(
            "ERR_SOD_SORTER_CANNOT_CLOSE", 409,
            "The operator who started sorting cannot close the batch",
        )
    b["status"] = "CLOSED"
    b["closed_by_user_id"] = g.user_id
    touch(b)
    return ok(svc.serialize_batch(b))
