"""Special drives: create (buffered window conflict), read, close (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint

import services as svc
from db import stamp_new, store, touch
from errors import ApiError, invalid_state, not_found
from middleware import require_roles
from response import ok
from util import get_body, v_dt, v_enum, v_int

bp = Blueprint("drives", __name__)

DRIVE_TYPES = {"INTERVIEW_ATTIRE", "WINTER_COATS"}
# drive_type -> required target_category pairing.
DRIVE_TARGET_CATEGORY = {
    "INTERVIEW_ATTIRE": "INTERVIEW_ATTIRE",
    "WINTER_COATS": "COATS",
}
BUFFER = timedelta(days=7)


def get_drive_or_404(drive_id):
    d = store.drives.get(drive_id)
    if d is None:
        raise not_found("Special drive not found")
    svc.refresh_drive(d)
    return d


@bp.post("/closet/drives")
@require_roles("ProgramAdmin")
def create_drive():
    data = get_body()
    drive_type = v_enum(data, "drive_type", DRIVE_TYPES)
    target_category = v_enum(data, "target_category", svc.CATEGORIES)
    start_at = v_dt(data, "start_at")
    end_at = v_dt(data, "end_at")
    bonus = v_int(data, "bonus_items_per_client", lo=1)
    if target_category != DRIVE_TARGET_CATEGORY[drive_type]:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            f"{drive_type} drives must target {DRIVE_TARGET_CATEGORY[drive_type]}",
        )
    if not end_at > start_at:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_at must be after start_at")
    # Same-type drives may not crowd one another within the 7-day buffer.
    for other in store.drives.values():
        if other["drive_type"] != drive_type:
            continue
        if start_at < other["end_at"] + BUFFER and other["start_at"] < end_at + BUFFER:
            raise ApiError(
                "ERR_DRIVE_WINDOW_CONFLICT", 409,
                "Same-type drive window conflict within the 7-day buffer",
            )
    d = stamp_new({
        "drive_type": drive_type,
        "target_category": target_category,
        "start_at": start_at,
        "end_at": end_at,
        "bonus_items_per_client": bonus,
        "status": "UPCOMING",
    })
    store.drives[d["id"]] = d
    return ok(svc.serialize_drive(d), 201)


@bp.get("/closet/drives/<did>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_drive(did):
    return ok(svc.serialize_drive(get_drive_or_404(did)))


@bp.post("/closet/drives/<did>/close")
@require_roles("ProgramAdmin")
def close_drive(did):
    d = get_drive_or_404(did)
    if d["status"] == "CLOSED":
        raise invalid_state("Drive is already CLOSED")
    d["status"] = "CLOSED"
    touch(d)
    return ok(svc.serialize_drive(d))
