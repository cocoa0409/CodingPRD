"""Routes: logical clock, homes, beds."""

from flask import Blueprint, request
from zoneinfo import ZoneInfo

from db import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_BED_OCCUPIED,
)
from util import (
    ok_object, ok_list, paginate, require_roles, get_or_404, body,
    need_str, need_int, opt_bool, stamp_new, touch, pub, sort_created,
    fmt_ts, now_ts, parse_ts,
)
from logic import (
    recompute_home_counters, close_home_cascade, find_pending_admission_for_bed,
    reject_admission_system, build_segments, scheduled_shifts,
)

bp = Blueprint("routes_a", __name__)

ALL = ("Provider", "Nurse", "CaregiverRole")
PROVIDER = ("Provider",)
PROVIDER_NURSE = ("Provider", "Nurse")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
@require_roles(*PROVIDER)
def set_clock():
    b = body()
    raw = b.get("to_iso8601")
    try:
        dt = parse_ts(raw)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp")
    db.set_clock(dt)
    return ok_object({"current_utc": fmt_ts(db.now())})


# ---------------------------------------------------------------------------
# Homes
# ---------------------------------------------------------------------------

@bp.post("/api/homes")
@require_roles(*PROVIDER)
def create_home():
    b = body()
    license_number = need_str(b, "license_number")
    name = need_str(b, "name")
    capacity = need_int(b, "licensed_bed_capacity")
    if capacity < 2 or capacity > 6:
        raise_err(ERR_INVALID_REQUEST, "licensed_bed_capacity must be between 2 and 6")
    tz = b.get("timezone") or "America/Los_Angeles"
    if not isinstance(tz, str):
        raise_err(ERR_INVALID_REQUEST, "timezone must be a string")
    try:
        ZoneInfo(tz)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "timezone must be a valid IANA timezone")
    for h in db.homes.values():
        if h["license_number"] == license_number:
            raise_err(ERR_INVALID_REQUEST, "license_number must be unique across homes")
    rec = stamp_new({
        "license_number": license_number,
        "name": name,
        "licensed_bed_capacity": capacity,
        "timezone": tz,
        "status": "PROVISIONAL",
        "open_case_count": 0,
        "current_census": 0,
    })
    db.homes[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/homes")
@require_roles(*ALL)
def list_homes():
    items = sort_created(list(db.homes.values()))
    status = request.args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    page, meta = paginate(items)
    return ok_list([pub(h) for h in page], meta)


@bp.get("/api/homes/<id>")
@require_roles(*ALL)
def get_home(id):
    home = get_or_404(db.homes, id, "home")
    return ok_object(pub(home))


@bp.post("/api/homes/<id>/license")
@require_roles(*PROVIDER)
def license_home(id):
    home = get_or_404(db.homes, id, "home")
    if home["status"] != "PROVISIONAL":
        raise_err(ERR_INVALID_STATE, "home is not PROVISIONAL")
    has_bed = any(b["home_id"] == id and b["status"] != "OUT_OF_SERVICE"
                  for b in db.beds.values())
    has_caregiver = any(c["home_id"] == id and c["status"] == "ACTIVE"
                        for c in db.caregivers.values())
    if not has_bed or not has_caregiver:
        raise_err(ERR_INVALID_STATE,
                  "licensing requires at least one in-service bed and one ACTIVE caregiver")
    home["status"] = "LICENSED"
    touch(home)
    return ok_object(pub(home))


@bp.post("/api/homes/<id>/suspend")
@require_roles(*PROVIDER)
def suspend_home(id):
    home = get_or_404(db.homes, id, "home")
    if home["status"] != "LICENSED":
        raise_err(ERR_INVALID_STATE, "home is not LICENSED")
    home["status"] = "SUSPENDED"
    touch(home)
    return ok_object(pub(home))


@bp.post("/api/homes/<id>/reinstate")
@require_roles(*PROVIDER)
def reinstate_home(id):
    home = get_or_404(db.homes, id, "home")
    if home["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "home is not SUSPENDED")
    if home["open_case_count"] != 0:
        raise_err(ERR_INVALID_STATE, "home has open compliance cases")
    home["status"] = "LICENSED"
    touch(home)
    return ok_object(pub(home))


@bp.post("/api/homes/<id>/close")
@require_roles(*PROVIDER)
def close_home(id):
    home = get_or_404(db.homes, id, "home")
    if home["status"] not in ("LICENSED", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "home cannot be closed from its current state")
    if home["current_census"] != 0:
        raise_err(ERR_INVALID_STATE, "home still has ADMITTED residents")
    close_home_cascade(home)
    home["status"] = "CLOSED"
    touch(home)
    return ok_object(pub(home))


@bp.get("/api/homes/<id>/staffing-compliance")
@require_roles(*PROVIDER_NURSE)
def staffing_compliance(id):
    home = get_or_404(db.homes, id, "home")
    raw_from = request.args.get("from_iso8601")
    raw_to = request.args.get("to_iso8601")
    if raw_from is None or raw_to is None:
        raise_err(ERR_INVALID_REQUEST, "from_iso8601 and to_iso8601 are required")
    try:
        from_dt = parse_ts(raw_from)
        to_dt = parse_ts(raw_to)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "from_iso8601/to_iso8601 must be ISO 8601 timestamps")
    if to_dt <= from_dt:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be after from_iso8601")
    shifts = scheduled_shifts(id)
    segments = build_segments(home, shifts, from_dt, to_dt, include_uncovered=True)
    compliant = all(s["compliant"] for s in segments)
    return ok_object({"segments": segments, "compliant": compliant})


# ---------------------------------------------------------------------------
# Beds
# ---------------------------------------------------------------------------

@bp.post("/api/homes/<id>/beds")
@require_roles(*PROVIDER)
def create_bed(id):
    home = get_or_404(db.homes, id, "home")
    b = body()
    label = need_str(b, "label")
    medicaid_certified = opt_bool(b, "medicaid_certified", False)
    for bed in db.beds.values():
        if bed["home_id"] == id and bed["label"] == label:
            raise_err(ERR_INVALID_REQUEST, "label must be unique within the home")
    rec = stamp_new({
        "home_id": id,
        "label": label,
        "medicaid_certified": medicaid_certified,
        "status": "AVAILABLE",
    })
    db.beds[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/api/homes/<id>/beds")
@require_roles(*ALL)
def list_beds(id):
    get_or_404(db.homes, id, "home")
    items = sort_created([b for b in db.beds.values() if b["home_id"] == id])
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(items)
    return ok_list([pub(b) for b in page], meta)


@bp.get("/api/beds/<id>")
@require_roles(*PROVIDER_NURSE)
def get_bed(id):
    bed = get_or_404(db.beds, id, "bed")
    return ok_object(pub(bed))


@bp.post("/api/beds/<id>/take-out-of-service")
@require_roles(*PROVIDER)
def take_bed_out_of_service(id):
    bed = get_or_404(db.beds, id, "bed")
    if bed["status"] == "OCCUPIED":
        raise_err(ERR_BED_OCCUPIED, "an occupied bed cannot leave service")
    if bed["status"] not in ("AVAILABLE", "HELD"):
        raise_err(ERR_INVALID_STATE, "bed cannot leave service from its current state")
    if bed["status"] == "HELD":
        adm = find_pending_admission_for_bed(id)
        if adm is not None:
            # Forced rejection; the admission's bed-release compensation is
            # suppressed because the bed is leaving service.
            reject_admission_system(adm)
    bed["status"] = "OUT_OF_SERVICE"
    touch(bed)
    return ok_object(pub(bed))


@bp.post("/api/beds/<id>/return-to-service")
@require_roles(*PROVIDER)
def return_bed_to_service(id):
    bed = get_or_404(db.beds, id, "bed")
    if bed["status"] != "OUT_OF_SERVICE":
        raise_err(ERR_INVALID_STATE, "bed is not OUT_OF_SERVICE")
    home = db.homes.get(bed["home_id"])
    if home is None or home["status"] not in ("PROVISIONAL", "LICENSED"):
        raise_err(ERR_INVALID_STATE, "home must be PROVISIONAL or LICENSED")
    bed["status"] = "AVAILABLE"
    touch(bed)
    return ok_object(pub(bed))
