"""CrewMember endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_str, as_enum,
                  parse_date, clock_date, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_OUTSIDE_PRODUCTION_WINDOW, ERR_SEASON_NOT_OPEN,
                    ERR_SEASON_SUSPENDED)
from services import core

bp = Blueprint("crew", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}


def get_crew_or_404(cid):
    c = db.crew_members.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, f"crew member {cid} not found")
    return c


@bp.post("/sugarhouse/crew-members")
def create_crew():
    caller = authenticate()
    require_role(caller, MGR)
    data = body_json()
    check_unknown_fields(data, {"season_id", "name", "crew_role", "cert_organic_handler"})
    require_fields(data, ["season_id", "name", "crew_role"])
    season_id = as_str(data["season_id"], "season_id")
    name = as_str(data["name"], "name")
    crew_role = as_enum(data["crew_role"], "crew_role", {"TAPPER", "BOILER", "GRADER"})
    cert = data.get("cert_organic_handler", False)
    if not isinstance(cert, bool):
        raise_err(__import__("errors").ERR_VALIDATION[0],
                  "cert_organic_handler must be a boolean", 400)
    if season_id not in db.seasons:
        raise_err(ERR_NOT_FOUND, f"season {season_id} not found")
    cm = core.new_crew_member(season_id, name, crew_role, cert)
    db.crew_members[cm["id"]] = cm
    return success_object(core.ser_crew_member(cm), status=201)


@bp.get("/sugarhouse/crew-members/<cid>")
def get_crew(cid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    cm = get_crew_or_404(cid)
    return success_object(core.ser_crew_member(cm))


@bp.get("/sugarhouse/crew-members")
def list_crew():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    crew_role = request.args.get("crew_role")
    status = request.args.get("status")
    rows = list(db.crew_members.values())
    if season_id is not None:
        rows = [r for r in rows if r["season_id"] == season_id]
    if crew_role is not None:
        rows = [r for r in rows if r["crew_role"] == crew_role]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_crew_member(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/crew-members/<cid>/activate")
def activate_crew(cid):
    caller = authenticate()
    require_role(caller, MGR)
    cm = get_crew_or_404(cid)
    if cm["status"] != "HIRED":
        raise_err(ERR_INVALID_STATE, f"crew member is {cm['status']}, expected HIRED")
    season = db.seasons.get(cm["season_id"])
    if not season:
        raise_err(ERR_NOT_FOUND, f"season {cm['season_id']} not found")
    if season["status"] == "SUSPENDED":
        raise_err(ERR_SEASON_SUSPENDED, "season is SUSPENDED")
    if season["status"] != "OPEN":
        raise_err(ERR_SEASON_NOT_OPEN, f"season is {season['status']}, expected OPEN")
    today = clock_date()
    od = parse_date(season["opens_on"])
    cd = parse_date(season["closes_on"])
    if not (od <= today <= cd):
        raise_err(ERR_OUTSIDE_PRODUCTION_WINDOW,
                  "logical clock date outside season opens_on..closes_on")
    cm["status"] = "ACTIVE"
    core.bump(cm)
    return success_object(core.ser_crew_member(cm))


@bp.post("/sugarhouse/crew-members/<cid>/release")
def release_crew(cid):
    caller = authenticate()
    require_role(caller, MGR)
    cm = get_crew_or_404(cid)
    if cm["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"crew member is {cm['status']}, expected ACTIVE")
    cm["status"] = "RELEASED"
    core.bump(cm)
    return success_object(core.ser_crew_member(cm))


# FK reverse lookup: evaluations recorded by a crew member
@bp.get("/sugarhouse/crew-members/<cid>/evaluations")
def list_crew_evaluations(cid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    get_crew_or_404(cid)
    limit, offset = parse_pagination(request.args)
    rows = [e for e in db.flavor_evaluations.values() if e["evaluator_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_flavor_evaluation(r) for r in page], limit, offset, total)
