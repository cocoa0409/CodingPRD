"""Charters and committee members."""
from flask import Blueprint, request

import calc
from authz import ALL_ROLES, ROLE_CHAIR, ROLE_COMPLIANCE_ADMIN, authorize, gate_action, require_action
from core import TouchLog, bad, public, store, success_object
from helpers import apply_eq, paged, sort_charters, sort_created_asc
from validate import (
    as_enum,
    as_integer,
    as_string,
    body_of,
    bool_filter,
    enum_filter,
    opt_bool,
    pagination,
    present,
    req_present,
    str_filter,
)

bp = Blueprint("charter", __name__)

CHARTER_STATUSES = ("DRAFT", "ADOPTED", "SUPERSEDED")
MEMBER_STATUSES = ("ACTIVE", "RECUSED", "VACATED")
FUNCTIONS = ("FINANCE", "LEGAL", "OPERATIONS", "INVESTOR_RELATIONS")


@bp.get("/disclosure/charters")
def list_charters():
    authorize(request, ALL_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("charter")
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", CHARTER_STATUSES))
    rows = apply_eq(rows, "superseded_by_charter_id", str_filter(request.args, "superseded_by_charter_id"))
    return paged(sort_charters(rows), limit, offset)


@bp.get("/disclosure/charters/<charter_id>")
def get_charter(charter_id):
    authorize(request, ALL_ROLES)
    return success_object(public(store.must_get("charter", charter_id)))


@bp.post("/disclosure/charters")
def create_charter():
    authorize(request, [ROLE_COMPLIANCE_ADMIN])
    body = body_of(request)
    name = as_string(req_present(body, "name"), "name", 160)
    version_label = as_string(req_present(body, "version_label"), "version_label", 40)
    min_quorum_count = as_integer(req_present(body, "min_quorum_count"), "min_quorum_count", 1, 12)
    required_functions = req_present(body, "required_functions")
    if not isinstance(required_functions, list) or not required_functions:
        bad("ERR_INVALID_REQUEST", "'required_functions' must be a non-empty list")
    seen = set()
    for entry in required_functions:
        as_enum(entry, "required_functions", FUNCTIONS)
        if entry in seen:
            bad("ERR_INVALID_REQUEST", "'required_functions' must contain distinct values")
        seen.add(entry)
    row = store.new_row(
        "charter",
        {
            "name": name,
            "version_label": version_label,
            "min_quorum_count": min_quorum_count,
            "required_functions": list(required_functions),
            "status": "DRAFT",
            "superseded_by_charter_id": None,
            "adopted_at_utc": None,
            "active_voting_member_count": 0,
            "covered_functions": [],
        },
    )
    return success_object(public(row), 201)


@bp.post("/disclosure/charters/<charter_id>/transitions")
def transition_charter(charter_id):
    actor = authorize(request, [ROLE_CHAIR])
    body = body_of(request)
    gate_action(actor, "charter", body)
    charter = store.must_get("charter", charter_id)
    successor = None
    if present(body, "successor_charter_id"):
        successor = store.must_get("charter", body["successor_charter_id"])
    action = require_action("charter", body)
    if action == "SUPERSEDE" and successor is None:
        bad("ERR_INVALID_REQUEST", "field 'successor_charter_id' is required")
    if charter["status"] == "SUPERSEDED":
        bad("ERR_ENTITY_TERMINAL", "charter is SUPERSEDED")

    log = TouchLog()
    if action == "ADOPT":
        if charter["status"] != "DRAFT":
            bad("ERR_INVALID_STATE", "ADOPT requires a DRAFT charter")
        calc.refresh_charter_derived(charter)
        if not calc.charter_quorum_ok(charter):
            bad("ERR_QUORUM_NOT_MET", "active voting members below min_quorum_count")
        if not calc.charter_coverage_ok(charter):
            bad("ERR_FUNCTION_COVERAGE_GAP", "required_functions are not fully covered")
        charter["status"] = "ADOPTED"
        charter["adopted_at_utc"] = store.clock.now_iso()
        log.touch(charter)
        return success_object(public(charter))

    if charter["status"] != "ADOPTED":
        bad("ERR_INVALID_STATE", "SUPERSEDE requires an ADOPTED charter")
    if successor["id"] == charter["id"] or successor["status"] != "ADOPTED":
        bad("ERR_SUCCESSOR_CHARTER_INVALID", "successor must be a different ADOPTED charter")
    charter["status"] = "SUPERSEDED"
    charter["superseded_by_charter_id"] = successor["id"]
    for member in store.where("member", charter_id=charter["id"]):
        if member["status"] in ("ACTIVE", "RECUSED"):
            member["status"] = "VACATED"
            log.touch(member)
    calc.refresh_charter_derived(charter)
    log.touch(charter)
    return success_object(public(charter))


@bp.get("/disclosure/committee-members")
def list_members():
    authorize(request, ALL_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("member")
    rows = apply_eq(rows, "charter_id", str_filter(request.args, "charter_id"))
    rows = apply_eq(rows, "function", enum_filter(request.args, "function", FUNCTIONS))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", MEMBER_STATUSES))
    rows = apply_eq(rows, "is_officer", bool_filter(request.args, "is_officer"))
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/committee-members/<member_id>")
def get_member(member_id):
    authorize(request, ALL_ROLES)
    return success_object(public(store.must_get("member", member_id)))


@bp.post("/disclosure/charters/<charter_id>/members")
def create_member(charter_id):
    authorize(request, [ROLE_COMPLIANCE_ADMIN])
    body = body_of(request)
    charter = store.must_get("charter", charter_id)
    full_name = as_string(req_present(body, "full_name"), "full_name", 120)
    function = as_enum(req_present(body, "function"), "function", FUNCTIONS)
    is_officer = opt_bool(body, "is_officer", False)
    voting = opt_bool(body, "voting", True)
    if charter["status"] == "SUPERSEDED":
        bad("ERR_ENTITY_TERMINAL", "charter is SUPERSEDED")
    log = TouchLog()
    row = store.new_row(
        "member",
        {
            "charter_id": charter["id"],
            "full_name": full_name,
            "function": function,
            "is_officer": is_officer,
            "voting": voting,
            "status": "ACTIVE",
        },
    )
    calc.refresh_charter_derived(charter)
    log.touch(charter)
    return success_object(public(row), 201)


@bp.post("/disclosure/committee-members/<member_id>/transitions")
def transition_member(member_id):
    actor = authorize(request, [ROLE_CHAIR])
    body = body_of(request)
    gate_action(actor, "member", body)
    member = store.must_get("member", member_id)
    action = require_action("member", body)
    if member["status"] == "VACATED":
        bad("ERR_ENTITY_TERMINAL", "member seat is VACATED")

    log = TouchLog()
    if action == "RECUSE":
        if member["status"] != "ACTIVE":
            bad("ERR_INVALID_STATE", "RECUSE requires an ACTIVE seat")
        member["status"] = "RECUSED"
    elif action == "REINSTATE":
        if member["status"] != "RECUSED":
            bad("ERR_INVALID_STATE", "REINSTATE requires a RECUSED seat")
        member["status"] = "ACTIVE"
    else:
        if member["status"] not in ("ACTIVE", "RECUSED"):
            bad("ERR_INVALID_STATE", "VACATE requires an ACTIVE or RECUSED seat")
        member["status"] = "VACATED"
    log.touch(member)

    charter = store.get("charter", member["charter_id"])
    if charter is not None:
        calc.refresh_charter_derived(charter)
        log.touch(charter)

    if action == "VACATE":
        affected = set()
        for row in store.where("subcert", member_id=member["id"]):
            if row["status"] == "PENDING":
                row["status"] = "VOID"
                log.touch(row)
                affected.add(row["cycle_id"])
        for cycle_id in affected:
            cycle = store.get("cycle", cycle_id)
            if cycle is None:
                continue
            calc.recompute_total_assigned_scope_weight(cycle)
            calc.recompute_certification_coverage_pct(cycle)
            log.touch(cycle)
    return success_object(public(member))
