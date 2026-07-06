"""Sprint routes: CRUD + start/close, window validation & overlap."""
from flask import Blueprint, request

import services
from auth import require_auth, require_role
from clock import parse_iso8601, iso_format
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, require_int, find, assert_owns_client,
    paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("sprints", __name__)

SPRINT_OPEN_DELIVERABLE = {"ASSIGNED", "IN_PROGRESS", "IN_REVIEW"}


@bp.route("/sprints", methods=["POST"])
def create_sprint():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    body = get_body()
    client_id = require_str(body, "client_id")
    retainer_id = require_str(body, "retainer_id")
    client = find("client", client_id)
    retainer = find("retainer", retainer_id)
    name = require_str(body, "name")
    starts_at_raw = require_str(body, "starts_at")
    ends_at_raw = require_str(body, "ends_at")
    capacity_credits = require_int(body, "capacity_credits", minimum=0)

    starts_at = parse_iso8601(starts_at_raw)
    ends_at = parse_iso8601(ends_at_raw)
    if starts_at is None or ends_at is None:
        raise err("ERR_INVALID_REQUEST", "starts_at and ends_at must be valid ISO-8601 datetimes")
    if not (ends_at > starts_at):
        raise err("ERR_INVALID_SPRINT_WINDOW", "ends_at must be strictly after starts_at")

    # overlap check: half-open [starts_at, ends_at) vs same-retainer PLANNING/ACTIVE sprints
    for s in store.sprints.values():
        if s["retainer_id"] != retainer_id:
            continue
        if s["status"] not in ("PLANNING", "ACTIVE"):
            continue
        s_start = parse_iso8601(s["starts_at"])
        s_end = parse_iso8601(s["ends_at"])
        # overlap iff starts_at < s_end and s_start < ends_at (touching allowed)
        if starts_at < s_end and s_start < ends_at:
            raise err("ERR_SPRINT_WINDOW_OVERLAP", "Sprint window overlaps an existing sprint")

    rec = base_record(versioned=True)
    rec.update({
        "client_id": client_id,
        "retainer_id": retainer_id,
        "name": name,
        "starts_at": iso_format(starts_at),
        "ends_at": iso_format(ends_at),
        "capacity_credits": capacity_credits,
        "committed_credits": 0,
        "status": "PLANNING",
    })
    store.sprints[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/sprints/<sid>", methods=["GET"])
def get_sprint(sid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    s = find("sprint", sid)
    client = find("client", s["client_id"])
    assert_owns_client(principal, client)
    services.recompute_sprint_committed(s)
    return ok_object(s, 200)


@bp.route("/sprints", methods=["GET"])
def list_sprints():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    parse_pagination()
    client_filter = request.args.get("client_id")
    retainer_filter = request.args.get("retainer_id")
    status_filter = request.args.get("status")
    records = list(store.sprints.values())
    if principal.role == "Client":
        records = [s for s in records if s["client_id"] == principal.user_id]
    if client_filter is not None:
        records = [s for s in records if s["client_id"] == client_filter]
    if retainer_filter is not None:
        records = [s for s in records if s["retainer_id"] == retainer_filter]
    if status_filter is not None:
        records = [s for s in records if s["status"] == status_filter]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


@bp.route("/sprints/<sid>/start", methods=["POST"])
def start_sprint(sid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    s = find("sprint", sid)
    if s["status"] != "PLANNING":
        raise err("ERR_INVALID_STATE", "Sprint must be PLANNING to start")
    retainer = find("retainer", s["retainer_id"])
    if retainer["status"] != "ACTIVE":
        raise err("ERR_RETAINER_NOT_ACTIVE", "Linked retainer must be ACTIVE")
    s["status"] = "ACTIVE"
    touch(s)
    return ok_object(s, 200)


@bp.route("/sprints/<sid>/close", methods=["POST"])
def close_sprint(sid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    s = find("sprint", sid)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Sprint must be ACTIVE to close")
    for d in store.deliverables.values():
        if d["sprint_id"] == sid and d["status"] in SPRINT_OPEN_DELIVERABLE:
            raise err("ERR_SPRINT_HAS_OPEN_WORK", "Sprint has open deliverables")
    s["status"] = "CLOSED"
    touch(s)
    return ok_object(s, 200)
