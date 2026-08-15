"""AgentProfile, Guardian, Talent registry endpoints."""
from flask import Blueprint, request

import db
from errors import err_not_found, err_ref_not_found
from middleware import require_roles
from response import success_object, success_list
from services import domain
from util import (check_datetime, check_enum, check_string, check_bool,
                  get_payload, new_record, paginate, parse_dt, serialize)

S = db.STORE
bp = Blueprint("rosters", __name__)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@bp.post("/casting/agents")
def create_agent():
    require_roles("CastingDirector")
    body = get_payload()
    rec = new_record({
        "agency_name": body.get("agency_name"),
        "contact_email": body.get("contact_email"),
        "franchise_status": body.get("franchise_status", "NON_FRANCHISED"),
        "active": body.get("active", True),
    })
    check_string(body, "agency_name")
    check_string(body, "contact_email")
    check_enum(body, "franchise_status", {"FRANCHISED", "NON_FRANCHISED"}, required=False)
    check_bool(body, "active", required=False)
    S["agents"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/casting/agents/<aid>")
def get_agent(aid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")
    a = domain.find("agents", aid)
    if a is None:
        raise err_not_found("AgentProfile not found")
    return success_object(serialize(a))


# ---------------------------------------------------------------------------
# Guardians
# ---------------------------------------------------------------------------

@bp.post("/casting/guardians")
def create_guardian():
    require_roles("ProductionCoordinator")
    body = get_payload()
    rec = new_record({
        "full_name": body.get("full_name"),
        "contact_email": body.get("contact_email"),
        "relationship": body.get("relationship"),
    })
    check_string(body, "full_name")
    check_string(body, "contact_email")
    check_string(body, "relationship")
    S["guardians"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/casting/guardians/<gid>")
def get_guardian(gid):
    require_roles("CastingDirector", "ProductionCoordinator", "Guardian")
    g = domain.find("guardians", gid)
    if g is None:
        raise err_not_found("Guardian not found")
    return success_object(serialize(g))


# ---------------------------------------------------------------------------
# Talents
# ---------------------------------------------------------------------------

def _serialize_talent(t):
    """is_minor is recomputed against the current logical clock on read."""
    return serialize(t, {"is_minor": domain.compute_is_minor(t)})


@bp.post("/casting/talents")
def create_talent():
    require_roles("CastingDirector", "Agent")
    body = get_payload()
    agent_id = body.get("agent_id")
    if agent_id is not None and domain.find("agents", agent_id) is None:
        raise err_ref_not_found("agent_id does not reference an AgentProfile")
    rec = new_record({
        "full_name": body.get("full_name"),
        "stage_name": body.get("stage_name"),
        "date_of_birth": parse_dt(body.get("date_of_birth")) if body.get("date_of_birth") is not None else None,
        "is_minor": False,  # recomputed on read against the logical clock
        "union_status": body.get("union_status", "NON_UNION"),
        "agent_id": agent_id,
        "union_engagement_count_365d": 0,
    })
    check_string(body, "full_name")
    if body.get("stage_name") is not None:
        check_string(body, "stage_name", required=False)
    check_datetime(body, "date_of_birth")
    check_enum(body, "union_status", {"UNION_MEMBER", "NON_UNION", "ELIGIBLE_PENDING"}, required=False)
    rec["is_minor"] = domain.compute_is_minor(rec)
    S["talents"][rec["id"]] = rec
    return success_object(_serialize_talent(rec), 201)


@bp.get("/casting/talents/<tid>")
def get_talent(tid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent", "Guardian")
    t = domain.find("talents", tid)
    if t is None:
        raise err_not_found("Talent not found")
    return success_object(_serialize_talent(t))


@bp.get("/casting/talents")
def list_talents():
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")
    records = list(S["talents"].values())
    agent_id = request.args.get("agent_id")
    if agent_id is not None:
        records = [r for r in records if r.get("agent_id") == agent_id]
    us = request.args.get("union_status")
    if us is not None:
        records = [r for r in records if r.get("union_status") == us]
    page, limit, offset, total = paginate(records)
    return success_list([_serialize_talent(r) for r in page], limit, offset, total)
