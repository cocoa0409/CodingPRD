"""Deliverable routes: CRUD + full lifecycle with credit ledger reconciliation."""
from flask import Blueprint, request

import calc
import services
from auth import require_auth, require_role
from clock import parse_iso8601
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, require_enum, opt_enum, require_int, find,
    assert_owns_client, paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("deliverables", __name__)

KINDS = {"CONTENT", "BACKLINK", "TECHNICAL"}
COMPLEXITIES = {"STANDARD", "COMPLEX"}
RESERVED = {"ASSIGNED", "IN_PROGRESS", "IN_REVIEW"}
NON_TERMINAL = {"DRAFT", "ASSIGNED", "IN_PROGRESS", "IN_REVIEW"}


@bp.route("/deliverables", methods=["POST"])
def create_deliverable():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    body = get_body()
    client_id = require_str(body, "client_id")
    retainer_id = require_str(body, "retainer_id")
    sprint_id = require_str(body, "sprint_id")
    client = find("client", client_id)
    retainer = find("retainer", retainer_id)
    sprint = find("sprint", sprint_id)
    kind = require_enum(body, "kind", KINDS)
    complexity = opt_enum(body, "complexity", COMPLEXITIES, default="STANDARD")

    # New deliverable creation blocked while retainer SUSPENDED (PRD §3.4)
    if retainer["status"] == "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Cannot create deliverable while retainer is SUSPENDED")

    credit_cost = calc.deliverable_credit_cost(kind, complexity)

    rec = base_record(versioned=True)
    rec.update({
        "client_id": client_id,
        "retainer_id": retainer_id,
        "sprint_id": sprint_id,
        "kind": kind,
        "complexity": complexity,
        "credit_cost": credit_cost,
        "revision_count": 0,
        "status": "DRAFT",
        "_approved_cycle": None,
    })
    store.deliverables[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/deliverables/<did>", methods=["GET"])
def get_deliverable(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    d = find("deliverable", did)
    client = find("client", d["client_id"])
    assert_owns_client(principal, client)
    return ok_object(d, 200)


@bp.route("/deliverables", methods=["GET"])
def list_deliverables():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    parse_pagination()
    client_filter = request.args.get("client_id")
    retainer_filter = request.args.get("retainer_id")
    sprint_filter = request.args.get("sprint_id")
    status_filter = request.args.get("status")
    records = list(store.deliverables.values())
    if principal.role == "Client":
        records = [d for d in records if d["client_id"] == principal.user_id]
    if client_filter is not None:
        records = [d for d in records if d["client_id"] == client_filter]
    if retainer_filter is not None:
        records = [d for d in records if d["retainer_id"] == retainer_filter]
    if sprint_filter is not None:
        records = [d for d in records if d["sprint_id"] == sprint_filter]
    if status_filter is not None:
        records = [d for d in records if d["status"] == status_filter]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


@bp.route("/deliverables/<did>/assign", methods=["POST"])
def assign_deliverable(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    d = find("deliverable", did)
    body = get_body()
    expected_version = require_int(body, "expected_retainer_version")

    # (6) state
    if d["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Deliverable must be DRAFT to assign")

    retainer = find("retainer", d["retainer_id"])
    sprint = find("sprint", d["sprint_id"])

    # (7) OCC
    if expected_version != retainer["version"]:
        raise err("ERR_STALE_RETAINER_VERSION", "expected_retainer_version is stale")

    # (8) retainer must be ACTIVE
    if retainer["status"] != "ACTIVE":
        raise err("ERR_RETAINER_NOT_ACTIVE", "Linked retainer must be ACTIVE")

    # sprint must be PLANNING or ACTIVE
    if sprint["status"] not in ("PLANNING", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Linked sprint must be PLANNING or ACTIVE")

    # (16) for ACTIVE sprint, window must contain clock_now
    if sprint["status"] == "ACTIVE":
        now = store.clock.now()
        s_start = parse_iso8601(sprint["starts_at"])
        s_end = parse_iso8601(sprint["ends_at"])
        if not (s_start <= now < s_end):
            raise err("ERR_INVALID_SPRINT_WINDOW", "Clock is outside the ACTIVE sprint window")

    # refresh ledgers before capacity/credit checks
    services.recompute_retainer_balance(retainer)
    services.recompute_sprint_committed(sprint)

    # (18) sprint capacity
    if sprint["committed_credits"] + d["credit_cost"] > sprint["capacity_credits"]:
        raise err("ERR_SPRINT_CAPACITY_EXCEEDED", "Sprint capacity would be exceeded")

    # (19) retainer credits
    if retainer["credits_available"] < d["credit_cost"]:
        raise err("ERR_INSUFFICIENT_CREDITS", "Retainer has insufficient credits")

    # commit
    d["status"] = "ASSIGNED"
    touch(d)
    services.recompute_retainer_balance(retainer)
    touch(retainer)
    services.recompute_sprint_committed(sprint)
    touch(sprint)
    return ok_object(d, 200)


@bp.route("/deliverables/<did>/start", methods=["POST"])
def start_deliverable(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    d = find("deliverable", did)
    if d["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Deliverable must be ASSIGNED to start")
    d["status"] = "IN_PROGRESS"
    touch(d)
    return ok_object(d, 200)


@bp.route("/deliverables/<did>/submit", methods=["POST"])
def submit_deliverable(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    d = find("deliverable", did)
    if d["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Deliverable must be IN_PROGRESS to submit")
    d["status"] = "IN_REVIEW"
    touch(d)
    return ok_object(d, 200)


@bp.route("/deliverables/<did>/request_revision", methods=["POST"])
def request_revision(did):
    principal = require_auth()
    require_role(principal, ["Client"])
    d = find("deliverable", did)
    client = find("client", d["client_id"])
    assert_owns_client(principal, client)
    if d["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Deliverable must be IN_REVIEW to request revision")
    d["status"] = "IN_PROGRESS"
    d["revision_count"] += 1
    touch(d)
    return ok_object(d, 200)


@bp.route("/deliverables/<did>/approve", methods=["POST"])
def approve_deliverable(did):
    principal = require_auth()
    require_role(principal, ["Client"])
    d = find("deliverable", did)
    client = find("client", d["client_id"])
    assert_owns_client(principal, client)
    if d["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Deliverable must be IN_REVIEW to approve")
    retainer = find("retainer", d["retainer_id"])
    d["status"] = "APPROVED"
    d["_approved_cycle"] = retainer["cycle_index"]
    touch(d)
    # commit -> consume (credits_available unchanged at approval)
    services.recompute_retainer_balance(retainer)
    touch(retainer)
    return ok_object(d, 200)


@bp.route("/deliverables/<did>/reject", methods=["POST"])
def reject_deliverable(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    d = find("deliverable", did)
    if d["status"] not in RESERVED:
        raise err("ERR_INVALID_STATE", "Deliverable must be ASSIGNED/IN_PROGRESS/IN_REVIEW to reject")
    retainer = find("retainer", d["retainer_id"])
    sprint = find("sprint", d["sprint_id"])
    d["status"] = "REJECTED"
    touch(d)
    services.recompute_retainer_balance(retainer)
    touch(retainer)
    services.recompute_sprint_committed(sprint)
    touch(sprint)
    return ok_object(d, 200)


@bp.route("/deliverables/<did>/cancel", methods=["POST"])
def cancel_deliverable(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    d = find("deliverable", did)
    if d["status"] not in NON_TERMINAL:
        raise err("ERR_INVALID_STATE", "Deliverable must be non-terminal to cancel")
    was_reserved = d["status"] in RESERVED
    retainer = find("retainer", d["retainer_id"])
    sprint = find("sprint", d["sprint_id"])
    d["status"] = "CANCELLED"
    touch(d)
    if was_reserved:
        services.recompute_retainer_balance(retainer)
        touch(retainer)
        services.recompute_sprint_committed(sprint)
        touch(sprint)
    return ok_object(d, 200)
