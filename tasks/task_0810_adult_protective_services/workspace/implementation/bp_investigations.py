"""Investigations: open, submit findings, return, dispose (PRD 3.3)."""
from flask import Blueprint, request

from store import store
from errors import ApiError
from envelope import success
from helpers import (authenticate, authorize, get_body, require_str, check_enum,
                     resolve, resolve_body_id, base_fields, touch, paginate,
                     sort_key, serialize)

bp = Blueprint("investigations", __name__)

DISPOSITIONS = {"SUBSTANTIATED", "UNSUBSTANTIATED", "INCONCLUSIVE"}


@bp.post("/investigations")
def create_investigation():
    uid, role = authenticate()
    authorize(role, {"Caseworker"})
    body = get_body()
    resolve_body_id(body, "case_id", "case")
    case_id = require_str(body, "case_id")
    case = resolve("case", case_id)
    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_INVALID_STATE", "Case is not OPEN", 409)

    inv = base_fields()
    inv.update({
        "case_id": case_id,
        "assigned_caseworker_id": uid,
        "status": "IN_PROGRESS",
        "finding_summary": None,
        "disposition": None,
        "return_count": 0,
        "disposed_at": None,
    })
    store.investigations[inv["id"]] = inv
    case["status"] = "UNDER_INVESTIGATION"
    touch(case)
    return success(serialize(inv, "investigation")), 201


@bp.get("/investigations/<iid>")
def get_investigation(iid):
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    inv = resolve("investigation", iid)
    return success(serialize(inv, "investigation")), 200


@bp.get("/investigations")
def list_investigations():
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    items = list(store.investigations.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [i for i in items if i["case_id"] == case_id]
    items.sort(key=sort_key)
    page, pag = paginate(items)
    return success([serialize(i, "investigation") for i in page], "array", pag), 200


@bp.post("/investigations/<iid>/submit-findings")
def submit_findings(iid):
    uid, role = authenticate()
    authorize(role, {"Caseworker"})
    inv = resolve("investigation", iid)
    body = get_body()
    finding_summary = require_str(body, "finding_summary")
    if inv["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVESTIGATION_INVALID_STATE", "Investigation is not IN_PROGRESS", 409)
    case = store.cases[inv["case_id"]]
    client = store.clients[case["client_id"]]
    if client["comprehensive_risk_score"] is None:
        raise ApiError("ERR_COMPREHENSIVE_ASSESSMENT_REQUIRED",
                       "A comprehensive risk assessment is required", 409)
    inv["finding_summary"] = finding_summary
    inv["status"] = "FINDINGS_SUBMITTED"
    touch(inv)
    return success(serialize(inv, "investigation")), 200


@bp.post("/investigations/<iid>/return")
def return_findings(iid):
    uid, role = authenticate()
    authorize(role, {"Supervisor"})
    inv = resolve("investigation", iid)
    body = get_body()
    require_str(body, "return_reason")
    if inv["status"] != "FINDINGS_SUBMITTED":
        raise ApiError("ERR_INVESTIGATION_INVALID_STATE", "Investigation is not FINDINGS_SUBMITTED", 409)
    inv["status"] = "IN_PROGRESS"
    inv["return_count"] += 1
    touch(inv)
    return success(serialize(inv, "investigation")), 200


@bp.post("/investigations/<iid>/dispose")
def dispose(iid):
    uid, role = authenticate()
    authorize(role, {"Supervisor"})
    inv = resolve("investigation", iid)
    body = get_body()
    disposition = require_str(body, "disposition")
    check_enum(disposition, DISPOSITIONS)
    if inv["status"] != "FINDINGS_SUBMITTED":
        raise ApiError("ERR_INVESTIGATION_INVALID_STATE", "Investigation is not FINDINGS_SUBMITTED", 409)
    inv["disposition"] = disposition
    inv["disposed_at"] = store.clock
    inv["status"] = "DISPOSED"
    touch(inv)
    # cascade A -> B -> C
    case = store.cases[inv["case_id"]]
    if case["status"] == "UNDER_INVESTIGATION":
        case["status"] = "READY_FOR_CLOSURE"
        touch(case)
        client = store.clients[case["client_id"]]
        if client["status"] == "UNDER_INVESTIGATION":
            client["status"] = "SERVICES_PENDING"
            touch(client)
    return success(serialize(inv, "investigation")), 200
