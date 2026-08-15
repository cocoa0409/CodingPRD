from flask import Blueprint

import db
import services
from auth import (
    authenticate,
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_INTAKE_COORDINATOR,
    ROLE_BARN_MANAGER,
)
from errors import (
    raise_err,
    ERR_HORSE_NOT_FOUND,
    ERR_STALL_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALL_OVERLAP,
    ERR_DISINFECTION_GAP_REQUIRED,
    ERR_STALL_ZONE_MISMATCH,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    as_bool,
    as_enum,
    as_str,
    body,
    get_path_or_404,
    opt_bool,
    pagination_args,
    parse_dt,
    parse_query_bool,
    query_str,
    require_present,
    sorted_page,
)

bp = Blueprint("housing", __name__)

BARN_ZONES = {"QUARANTINE_BARN", "MAIN_BARN", "ISOLATION"}
READ_ROLES = [ROLE_SANCTUARY_DIRECTOR, ROLE_INTAKE_COORDINATOR, ROLE_BARN_MANAGER]


@bp.post("/rescue-ops/stalls")
def create_stall():
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    data = body()
    stall_code = as_str(require_present(data, "stall_code"), "stall_code")
    barn_zone = as_enum(require_present(data, "barn_zone"), "barn_zone", BARN_ZONES)
    active = opt_bool(data, "active", True)
    if any(s["stall_code"] == stall_code for s in db.stalls.values()):
        raise_err(ERR_INVALID_REQUEST, "stall_code must be unique")
    rec = services.new_entity({"stall_code": stall_code, "barn_zone": barn_zone, "active": active})
    db.stalls[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/stalls")
def list_stalls():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    value = query_str("barn_zone")
    if value is not None:
        filters.append(("barn_zone", value))
    active = parse_query_bool("active")
    if active is not None:
        filters.append(("active", active))
    rows, total = sorted_page(db.stalls.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/stalls/<stall_id>")
def get_stall(stall_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.stalls, stall_id)))


def _overlaps(ns, ne, s, e):
    """Closed date-interval overlap; None end is open-ended."""
    if ne is not None and s > ne:
        return False
    if e is not None and ns > e:
        return False
    return True


def _has_gap_day(ns, ne, s, e):
    """True when at least one full calendar day separates the windows."""
    if e is not None and ns > e:
        return (ns.date() - e.date()).days >= 2
    if ne is not None and s > ne:
        return (s.date() - ne.date()).days >= 2
    return False


@bp.post("/rescue-ops/stall-assignments")
def create_assignment():
    authenticate([ROLE_INTAKE_COORDINATOR])
    data = body()
    horse_id = data.get("horse_id")
    if horse_id is not None and horse_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "horse_id does not reference an existing horse")
    stall_id = data.get("stall_id")
    if stall_id is not None and stall_id not in db.stalls:
        raise_err(ERR_STALL_NOT_FOUND, "stall_id does not reference an existing stall")
    horse_id = require_present(data, "horse_id")
    stall_id = require_present(data, "stall_id")
    start = parse_dt(require_present(data, "start_date"), "start_date")
    end = None
    if data.get("end_date") is not None:
        end = parse_dt(data["end_date"], "end_date")
        if end.date() < start.date():
            raise_err(ERR_INVALID_REQUEST, "end_date must not precede start_date")

    stall = db.stalls[stall_id]
    horse = db.horses[horse_id]

    # Tier 15: stall occupancy calendar rules.
    for other in db.stall_assignments.values():
        if other["stall_id"] != stall_id:
            continue
        if _overlaps(start, end, other["start_date"], other["end_date"]):
            raise_err(ERR_STALL_OVERLAP, "Stall occupancy windows overlap")
        if stall["barn_zone"] == "QUARANTINE_BARN" and not _has_gap_day(
            start, end, other["start_date"], other["end_date"]
        ):
            raise_err(
                ERR_DISINFECTION_GAP_REQUIRED,
                "QUARANTINE_BARN requires one full gap day between occupants",
            )

    # Tier 24: zone/posture and active-stall gates.
    if horse["status"] == "QUARANTINE" and stall["barn_zone"] != "QUARANTINE_BARN":
        raise_err(ERR_STALL_ZONE_MISMATCH, "QUARANTINE horses require a QUARANTINE_BARN stall")
    if not stall["active"]:
        raise_err(ERR_STALL_ZONE_MISMATCH, "Stall is inactive")

    rec = services.new_entity(
        {
            "horse_id": horse_id,
            "stall_id": stall_id,
            "start_date": start,
            "end_date": end,
            "status": "ACTIVE",
        }
    )
    db.stall_assignments[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/stall-assignments")
def list_assignments():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("horse_id", "stall_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.stall_assignments.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/stall-assignments/<assign_id>")
def get_assignment(assign_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.stall_assignments, assign_id)))


@bp.post("/rescue-ops/stall-assignments/<assign_id>/end")
def end_assignment(assign_id):
    authenticate([ROLE_INTAKE_COORDINATOR])
    rec = get_path_or_404(db.stall_assignments, assign_id)
    data = body()
    end = parse_dt(require_present(data, "end_date"), "end_date")
    if end.date() < rec["start_date"].date():
        raise_err(ERR_INVALID_REQUEST, "end_date must not precede start_date")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Assignment is not ACTIVE")
    rec["status"] = "ENDED"
    rec["end_date"] = end
    services.touch(rec)
    return ok_object(serialize(rec))
