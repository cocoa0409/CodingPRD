"""Coordinators and Agents."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, mint, pub, pub_list
from response import ok_object, ok_list

bp = Blueprint("roster", __name__)

ALL_ROLES = ("SystemAdmin", "Coordinator", "Agent", "TitleRep", "LenderRep")


@bp.post("/tc/coordinators")
def create_coordinator():
    uid, role = mw.auth()
    mw.require_roles(role, {"SystemAdmin"})
    data = mw.body()
    mw.validate_shape(data, [
        ("full_name", "string", True),
        ("email", "string", True),
        ("license_number", "string", True),
    ])
    for c in store.coordinators.values():
        if c["email"] == data["email"]:
            E.raise_err(E.ERR_INVALID_REQUEST, "email must be unique across coordinators")
    rec = mint({
        "full_name": data["full_name"],
        "email": data["email"],
        "license_number": data["license_number"],
        "status": "ACTIVE",
    })
    store.coordinators[rec["id"]] = rec
    return ok_object(pub("coordinator", rec), 201)


@bp.get("/tc/coordinators/<coordinatorId>")
def get_coordinator(coordinatorId):
    mw.auth()
    rec = mw.get_or_404("coordinator", coordinatorId)
    return ok_object(pub("coordinator", rec))


@bp.post("/tc/agents")
def create_agent():
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    data = mw.body()
    mw.validate_shape(data, [
        ("full_name", "string", True),
        ("email", "string", True),
        ("brokerage", "string", True),
    ])
    rec = mint({
        "coordinator_id": uid,
        "full_name": data["full_name"],
        "email": data["email"],
        "brokerage": data["brokerage"],
        "status": "ACTIVE",
    })
    store.agents[rec["id"]] = rec
    return ok_object(pub("agent", rec), 201)


@bp.get("/tc/agents/<agentId>")
def get_agent(agentId):
    mw.auth()
    rec = mw.get_or_404("agent", agentId)
    return ok_object(pub("agent", rec))


@bp.get("/tc/agents")
def list_agents():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.agents.values())
    recs = mw.filter_eq(recs, "coordinator_id", request.args.get("coordinator_id"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("agent", page), limit, offset, total)
