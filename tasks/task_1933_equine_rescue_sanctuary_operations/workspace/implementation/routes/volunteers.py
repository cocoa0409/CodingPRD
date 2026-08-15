from flask import Blueprint

import calc
import db
import services
from auth import (
    authenticate,
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_VOLUNTEER_COORDINATOR,
    ROLE_VOLUNTEER,
)
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
    ERR_VOLUNTEER_NOT_ACTIVE,
    ERR_RELIABILITY_TOO_LOW,
    ERR_SKILL_MISMATCH,
    ERR_SHIFT_OVERLAP,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    as_enum,
    as_str,
    body,
    get_path_or_404,
    pagination_args,
    parse_dt,
    parse_hhmm,
    query_str,
    require_present,
    sorted_page,
)
from util import iso_z

bp = Blueprint("volunteers", __name__)

SKILLS = {"FEEDING", "CLEANING", "HANDLING", "MAINTENANCE"}
SHIFT_ZONES = {"QUARANTINE_BARN", "MAIN_BARN", "ISOLATION", "PASTURES"}
REQUIRED_SKILLS = SKILLS | {"ANY"}
COORD_READ = [ROLE_VOLUNTEER_COORDINATOR, ROLE_SANCTUARY_DIRECTOR]


# --------------------------------------------------------------------------
# Volunteers
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/volunteers")
def create_volunteer():
    authenticate([ROLE_VOLUNTEER])
    data = body()
    name = as_str(require_present(data, "name"), "name")
    email = as_str(require_present(data, "contact_email"), "contact_email")
    skills = require_present(data, "skills")
    if not isinstance(skills, list) or not skills:
        raise_err(ERR_INVALID_REQUEST, "skills must be a non-empty list")
    for skill in skills:
        if skill not in SKILLS:
            raise_err(ERR_INVALID_REQUEST, "skills entries must be FEEDING/CLEANING/HANDLING/MAINTENANCE")
    rec = services.new_entity(
        {
            "name": name,
            "contact_email": email,
            "skills": list(skills),
            "status": "ACTIVE",
            "completed_shift_count": 0,
            "no_show_count": 0,
            "reliability_score": 50,
        }
    )
    db.volunteers[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/volunteers")
def list_volunteers():
    authenticate(COORD_READ)
    limit, offset = pagination_args()
    filters = []
    value = query_str("status")
    if value is not None:
        filters.append(("status", value))
    rows, total = sorted_page(db.volunteers.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/volunteers/<vol_id>")
def get_volunteer(vol_id):
    user_id, role = authenticate(COORD_READ + [ROLE_VOLUNTEER])
    rec = get_path_or_404(db.volunteers, vol_id)
    if role == ROLE_VOLUNTEER and user_id != vol_id:
        raise_err(ERR_FORBIDDEN, "Volunteers may read only their own record")
    return ok_object(serialize(rec))


# --------------------------------------------------------------------------
# Barn shifts
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/barn-shifts")
def create_shift():
    authenticate([ROLE_VOLUNTEER_COORDINATOR])
    data = body()
    shift_date = parse_dt(require_present(data, "shift_date"), "shift_date")
    start = require_present(data, "start_time")
    end = require_present(data, "end_time")
    start_min = parse_hhmm(start, "start_time")
    end_min = parse_hhmm(end, "end_time")
    if end_min <= start_min:
        raise_err(ERR_INVALID_REQUEST, "end_time must be after start_time")
    zone = as_enum(require_present(data, "barn_zone"), "barn_zone", SHIFT_ZONES)
    skill = as_enum(require_present(data, "required_skill"), "required_skill", REQUIRED_SKILLS)
    rec = services.new_entity(
        {
            "volunteer_id": None,
            "shift_date": shift_date,
            "start_time": start,
            "end_time": end,
            "barn_zone": zone,
            "required_skill": skill,
            "status": "OPEN",
        }
    )
    db.shifts[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/barn-shifts")
def list_shifts():
    authenticate(COORD_READ + [ROLE_VOLUNTEER])
    limit, offset = pagination_args()
    filters = []
    for param in ("volunteer_id", "barn_zone", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows = [r for r in db.shifts.values() if all(r.get(k) == v for k, v in filters)]
    date_q = query_str("shift_date")
    if date_q is not None:
        rows = [
            r
            for r in rows
            if r["shift_date"].date().isoformat() == date_q or iso_z(r["shift_date"]) == date_q
        ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list(serialize_many(rows[offset : offset + limit]), limit, offset, total)


@bp.get("/rescue-ops/barn-shifts/<shift_id>")
def get_shift(shift_id):
    authenticate(COORD_READ + [ROLE_VOLUNTEER])
    return ok_object(serialize(get_path_or_404(db.shifts, shift_id)))


@bp.post("/rescue-ops/barn-shifts/<shift_id>/claim")
def claim_shift(shift_id):
    user_id, _ = authenticate([ROLE_VOLUNTEER])
    shift = get_path_or_404(db.shifts, shift_id)
    if shift["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Shift is not OPEN")
    volunteer = db.volunteers[user_id]
    new_start = parse_hhmm(shift["start_time"], "start_time")
    new_end = parse_hhmm(shift["end_time"], "end_time")
    for other in db.shifts.values():
        if other["id"] == shift["id"]:
            continue
        if other["volunteer_id"] != user_id or other["status"] != "ASSIGNED":
            continue
        if other["shift_date"].date() != shift["shift_date"].date():
            continue
        o_start = parse_hhmm(other["start_time"], "start_time")
        o_end = parse_hhmm(other["end_time"], "end_time")
        if new_start < o_end and o_start < new_end:
            raise_err(ERR_SHIFT_OVERLAP, "Shift overlaps another assigned shift that day")
    if volunteer["status"] != "ACTIVE":
        raise_err(ERR_VOLUNTEER_NOT_ACTIVE, "Volunteer is not ACTIVE")
    if volunteer["reliability_score"] < 40:
        raise_err(ERR_RELIABILITY_TOO_LOW, "reliability_score is below 40")
    if shift["required_skill"] != "ANY" and shift["required_skill"] not in volunteer["skills"]:
        raise_err(ERR_SKILL_MISMATCH, "Volunteer lacks the required skill")
    shift["status"] = "ASSIGNED"
    shift["volunteer_id"] = user_id
    services.touch(shift)
    return ok_object(serialize(shift))


@bp.post("/rescue-ops/barn-shifts/<shift_id>/release")
def release_shift(shift_id):
    user_id, _ = authenticate([ROLE_VOLUNTEER])
    shift = get_path_or_404(db.shifts, shift_id)
    if shift["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE, "Shift is not ASSIGNED")
    if shift["volunteer_id"] != user_id:
        raise_err(ERR_FORBIDDEN, "Only the assigned volunteer may release the shift")
    shift["status"] = "OPEN"
    shift["volunteer_id"] = None
    services.touch(shift)
    return ok_object(serialize(shift))


@bp.post("/rescue-ops/barn-shifts/<shift_id>/complete")
def complete_shift(shift_id):
    authenticate([ROLE_VOLUNTEER_COORDINATOR])
    shift = get_path_or_404(db.shifts, shift_id)
    if shift["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE, "Shift is not ASSIGNED")
    shift["status"] = "COMPLETED"
    services.touch(shift)
    volunteer = db.volunteers.get(shift["volunteer_id"])
    if volunteer is not None:
        volunteer["completed_shift_count"] += 1
        volunteer["reliability_score"] = calc.reliability(
            volunteer["completed_shift_count"], volunteer["no_show_count"]
        )
        services.touch(volunteer)
    return ok_object(serialize(shift))


@bp.post("/rescue-ops/barn-shifts/<shift_id>/mark-no-show")
def mark_no_show(shift_id):
    authenticate([ROLE_VOLUNTEER_COORDINATOR])
    shift = get_path_or_404(db.shifts, shift_id)
    if shift["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE, "Shift is not ASSIGNED")
    shift["status"] = "NO_SHOW"
    services.touch(shift)
    volunteer = db.volunteers.get(shift["volunteer_id"])
    if volunteer is not None:
        volunteer["no_show_count"] += 1
        volunteer["reliability_score"] = calc.reliability(
            volunteer["completed_shift_count"], volunteer["no_show_count"]
        )
        if volunteer["reliability_score"] < 20:
            volunteer["status"] = "SUSPENDED"
        services.touch(volunteer)
    return ok_object(serialize(shift))
