"""Construction phases: closure limits, overlap, contractor buffer."""
from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_ROLES, require
from domain import CLOSURE_TYPES, ser_phase
from errors import ApiError, err_invalid_state, err_validation
from store import DB
from util import (as_enum, as_str, body, get_or_404, need, new_entity,
                  parse_dt, respond, respond_list, touch)

bp = Blueprint("phases", __name__)

MAX_DURATION = {"FULL_CLOSURE": timedelta(hours=72),
                "NIGHT_ONLY": timedelta(hours=8)}
BUFFER = timedelta(hours=24)


@bp.route("/aip/construction-phases", methods=["POST"])
@require("SponsorStaff")
def create_phase():
    b = body()
    for fk, entity in (("grant_id", "Grant"),
                       ("cip_project_id", "CIPProject"),
                       ("facility_id", "AirfieldFacility"),
                       ("contractor_id", "Contractor")):
        if fk not in b or b[fk] is None:
            raise err_validation(f"Missing required field: {fk}")
    grant = get_or_404(DB.grants, b["grant_id"], "Grant")
    project = get_or_404(DB.projects, b["cip_project_id"], "CIPProject")
    facility = get_or_404(DB.facilities, b["facility_id"], "AirfieldFacility")
    contractor = get_or_404(DB.contractors, b["contractor_id"], "Contractor")
    closure_type = as_enum(need(b, "closure_type"), "closure_type",
                           CLOSURE_TYPES)
    start_raw = as_str(need(b, "start_utc"), "start_utc")
    end_raw = as_str(need(b, "end_utc"), "end_utc")
    start = parse_dt(start_raw, "start_utc")
    end = parse_dt(end_raw, "end_utc")
    # Pinned order: duration -> window validity -> overlap -> buffer -> xref.
    if end - start > MAX_DURATION[closure_type]:
        raise ApiError("ERR_CLOSURE_DURATION_EXCEEDED", 422,
                       f"{closure_type} phase exceeds its duration limit")
    if end <= start:
        raise ApiError("ERR_PHASE_WINDOW_INVALID", 422,
                       "end_utc must be strictly after start_utc")
    if closure_type == "FULL_CLOSURE":
        for p in DB.phases.values():
            if (p["facility_id"] == facility["id"]
                    and p["closure_type"] == "FULL_CLOSURE"
                    and p["status"] in ("PLANNED", "ACTIVE")):
                s2, e2 = parse_dt(p["start_utc"], "start_utc"), \
                    parse_dt(p["end_utc"], "end_utc")
                if start < e2 and s2 < end:  # half-open overlap; adjacency OK
                    raise ApiError("ERR_FACILITY_OVERLAP", 409,
                                   "FULL_CLOSURE overlap on the same "
                                   "facility")
    for p in DB.phases.values():
        if (p["contractor_id"] == contractor["id"]
                and p["status"] in ("PLANNED", "ACTIVE")):
            s2, e2 = parse_dt(p["start_utc"], "start_utc"), \
                parse_dt(p["end_utc"], "end_utc")
            if not (start >= e2 + BUFFER or s2 >= end + BUFFER):
                raise ApiError("ERR_CONTRACTOR_BUFFER_CONFLICT", 409,
                               "Same-contractor phases require a 24h buffer")
    program = DB.programs.get(project["program_id"])
    if (facility["sponsor_id"] != grant["sponsor_id"]
            or contractor["sponsor_id"] != grant["sponsor_id"]
            or program is None
            or program["sponsor_id"] != grant["sponsor_id"]):
        raise ApiError("ERR_CROSS_SPONSOR_REFERENCE", 422,
                       "Facility/contractor/project must belong to the "
                       "grant's sponsor")
    p = new_entity()
    p.update({"grant_id": grant["id"], "cip_project_id": project["id"],
              "facility_id": facility["id"],
              "contractor_id": contractor["id"], "closure_type": closure_type,
              "start_utc": start_raw, "end_utc": end_raw,
              "status": "PLANNED"})
    DB.phases[p["id"]] = p
    return respond(ser_phase(p), 201)


@bp.route("/aip/construction-phases", methods=["GET"])
@require(*ALL_ROLES)
def list_phases():
    items = list(DB.phases.values())
    filters = {"grant_id": "grant_id", "facility_id": "facility_id",
               "contractor_id": "contractor_id",
               "cip_project_id": "cip_project_id",
               "closure_type": "closure_type"}
    for param, field in filters.items():
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p[field] == v]
    return respond_list(items, ser_phase)


@bp.route("/aip/construction-phases/<phaseId>", methods=["GET"])
@require(*ALL_ROLES)
def get_phase(phaseId):
    return respond(ser_phase(
        get_or_404(DB.phases, phaseId, "ConstructionPhase")))


def _get_phase(pid):
    return get_or_404(DB.phases, pid, "ConstructionPhase")


@bp.route("/aip/construction-phases/<phaseId>/activate", methods=["POST"])
@require("SponsorStaff")
def activate_phase(phaseId):
    p = _get_phase(phaseId)
    if p["status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED phase can be activated")
    grant = DB.grants[p["grant_id"]]
    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_GRANT_NOT_ACTIVE", 409,
                       "Phase activation requires an ACTIVE grant")
    start = parse_dt(p["start_utc"], "start_utc")
    end = parse_dt(p["end_utc"], "end_utc")
    if not (start <= DB.clock < end):
        raise ApiError("ERR_PHASE_OUTSIDE_WINDOW", 422,
                       "Clock is outside [start_utc, end_utc)")
    p["status"] = "ACTIVE"
    touch(p)
    return respond(ser_phase(p))


@bp.route("/aip/construction-phases/<phaseId>/complete", methods=["POST"])
@require("SponsorStaff")
def complete_phase(phaseId):
    p = _get_phase(phaseId)
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE phase can be completed")
    p["status"] = "COMPLETED"
    touch(p)
    return respond(ser_phase(p))


@bp.route("/aip/construction-phases/<phaseId>/cancel", methods=["POST"])
@require("SponsorStaff")
def cancel_phase(phaseId):
    p = _get_phase(phaseId)
    if p["status"] not in ("PLANNED", "ACTIVE"):
        raise err_invalid_state(
            "Only a PLANNED or ACTIVE phase can be cancelled")
    p["status"] = "CANCELLED"
    touch(p)
    return respond(ser_phase(p))
