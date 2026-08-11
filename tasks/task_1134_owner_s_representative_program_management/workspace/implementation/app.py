"""Owner's Representative & Program Management API — Flask entry point."""
import os
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_TRANSITION, \
    ERR_PROGRAM_NOT_ACTIVE, ERR_NO_APPROVED_CHARTER, ERR_NO_APPROVED_BASELINE, \
    ERR_CONTRACT_NOT_EXECUTED, ERR_OPEN_CHANGE_ORDERS_EXIST, \
    ERR_PROGRAM_HAS_OPEN_ITEMS, ERR_CLOSEOUT_INCOMPLETE, \
    ERR_LESSON_ENTRIES_REQUIRED, ERR_CONTINGENCY_POSTURE_CRITICAL, \
    ERR_PLAN_NOT_READY, ERR_PLAN_NOT_ACCEPTING_WAVES, ERR_OPEN_WAVES_EXIST, \
    ERR_DUPLICATE_REPORT_PERIOD, ERR_CROSS_PROGRAM_REFERENCE, \
    ERR_SUPERSEDES_TARGET_INVALID, ERR_DOCK_OVERLAP, ERR_ENGAGEMENT_OVERLAP, \
    ERR_ENGAGEMENT_DAILY_CAP_EXCEEDED, ERR_SEGREGATION_OF_DUTIES, \
    ERR_AWARD_EXCEEDS_BUDGET, ERR_CONTINGENCY_EXCEEDED, \
    ERR_BASELINE_UNDERCUTS_COMMITMENTS, ERR_STALE_PROGRAM_VERSION
from helpers import (
    ESCALATION_THRESHOLD_CENTS, ENGAGEMENT_DAILY_CAP_MINUTES,
    TURNOVER_BUFFER_HOURS, get_or_404, body, req_str, opt_str, req_int,
    req_enum, req_date, req_month, parse_dt, round_half_up_int,
    round_half_up_2dp, touch, make_common, recompute_pool, recompute_posture,
    compute_forecast, refresh_draft_reports,
)
from middleware import require_roles
from response import success_object, success_list, error_response, now_iso

app = Flask(__name__)

ALL_ROLES = ("OwnerRepPM", "OwnerRepExecutive", "Owner")
PM = ("OwnerRepPM",)
EXEC = ("OwnerRepExecutive",)
OWNER = ("Owner",)


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _not_found(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _method(e):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def list_response(store, filters):
    """filters: list of (query_param, entity_field) pairs."""
    require_roles(*ALL_ROLES)
    items = list(store.values())
    for qp, field in filters:
        v = request.args.get(qp)
        if v is not None:
            items = [it for it in items if str(it.get(field)) == v]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameter", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameter", 400)
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)


def get_one(kind, rid):
    require_roles(*ALL_ROLES)
    ent = get_or_404(kind, rid)
    return success_object(ent)


def program_of(entity):
    return db.programs.get(entity["program_id"])


def require_program_active(program):
    if program["status"] != "ACTIVE":
        raise ApiError(ERR_PROGRAM_NOT_ACTIVE, "Operation requires the program to be ACTIVE", 409)


# ===========================================================================
# Programs
# ===========================================================================

@app.post("/programs")
def create_program():
    user_id, _ = require_roles(*PM)
    data = body()
    name = req_str(data, "program_name")
    org = req_str(data, "owner_organization")
    p = make_common({})
    p.update({
        "program_name": name,
        "owner_organization": org,
        "status": "CHARTERING",
        "current_budget_cents": None,
        "contingency_total_cents": 0,
        "contingency_reserved_cents": 0,
        "contingency_committed_cents": 0,
        "contingency_drawn_cents": 0,
        "contingency_available_cents": 0,
        "contingency_posture": "CRITICAL",
        "approved_charter_id": None,
        "approved_baseline_id": None,
        "baseline_version_no": None,
        "target_finish_date": None,
    })
    db.programs[p["id"]] = p
    return success_object(p, 201)


@app.get("/programs")
def list_programs():
    return list_response(db.programs, [("status", "status")])


@app.get("/programs/<pid>")
def get_program(pid):
    return get_one("program", pid)


@app.post("/programs/<pid>/activate")
def activate_program(pid):
    require_roles(*PM)
    p = get_or_404("program", pid)
    if p["status"] != "CHARTERING":
        raise ApiError(ERR_INVALID_TRANSITION, "Program is not in CHARTERING", 409)
    if not p["approved_charter_id"]:
        raise ApiError(ERR_NO_APPROVED_CHARTER, "Program activation requires an APPROVED charter", 409)
    if not p["approved_baseline_id"]:
        raise ApiError(ERR_NO_APPROVED_BASELINE, "Program activation requires an APPROVED baseline", 409)
    p["status"] = "ACTIVE"
    touch(p)
    return success_object(p)


@app.post("/programs/<pid>/begin-closing")
def begin_closing_program(pid):
    require_roles(*PM)
    p = get_or_404("program", pid)
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_TRANSITION, "Program is not ACTIVE", 409)
    open_contracts = any(
        c["program_id"] == pid and c["status"] in ("SOLICITED", "UNDER_NEGOTIATION", "COUNTERED", "EXECUTED")
        for c in db.contracts.values())
    open_cos = any(
        co["program_id"] == pid and co["status"] in ("DRAFT", "UNDER_REVIEW", "RECOMMEND_APPROVAL", "RECOMMEND_REJECTION", "APPROVED")
        for co in db.change_orders.values())
    open_risks = any(
        r["program_id"] == pid and r["status"] in ("IDENTIFIED", "ASSESSED", "MITIGATING", "MONITORING", "ESCALATED")
        for r in db.risk_entries.values())
    open_dds = any(
        d["program_id"] == pid and d["status"] in ("RESERVED", "COMMITTED")
        for d in db.drawdowns.values())
    open_reports = any(
        r["program_id"] == pid and r["status"] in ("DRAFT", "SUBMITTED", "RETURNED")
        for r in db.owner_reports.values())
    if open_contracts or open_cos or open_risks or open_dds or open_reports:
        raise ApiError(ERR_PROGRAM_HAS_OPEN_ITEMS,
                       "begin-closing blocked: non-terminal contracts, change orders, risks, drawdowns, or reports exist", 409)
    p["status"] = "CLOSING"
    touch(p)
    return success_object(p)


@app.post("/programs/<pid>/close")
def close_program(pid):
    require_roles(*OWNER)
    p = get_or_404("program", pid)
    if p["status"] != "CLOSING":
        raise ApiError(ERR_INVALID_TRANSITION, "Program is not CLOSING", 409)
    if any(ci["program_id"] == pid and ci["status"] != "VERIFIED" for ci in db.closeout_items.values()):
        raise ApiError(ERR_CLOSEOUT_INCOMPLETE, "Program close blocked: not all closeout items are VERIFIED", 409)
    if not any(le["program_id"] == pid for le in db.lesson_entries.values()):
        raise ApiError(ERR_LESSON_ENTRIES_REQUIRED, "Program close blocked: no lesson entries recorded", 409)
    p["status"] = "CLOSED"
    touch(p)
    return success_object(p)


@app.post("/programs/<pid>/reopen")
def reopen_program(pid):
    require_roles(*PM)
    p = get_or_404("program", pid)
    if p["status"] != "CLOSING":
        raise ApiError(ERR_INVALID_TRANSITION, "Program is not CLOSING", 409)
    p["status"] = "ACTIVE"
    touch(p)
    return success_object(p)


# ===========================================================================
# Charters
# ===========================================================================

CHARTER_PROGRAM_STATES = ("CHARTERING", "ACTIVE")


@app.post("/charters")
def create_charter():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    objectives = req_str(data, "objectives")
    scope = req_str(data, "scope_statement")
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    if p["status"] not in CHARTER_PROGRAM_STATES:
        raise ApiError(ERR_INVALID_TRANSITION, "Program must be CHARTERING or ACTIVE", 409)
    ver = max([c["version_no"] for c in db.charters.values() if c["program_id"] == program_id], default=0) + 1
    c = make_common({})
    c.update({
        "program_id": program_id,
        "version_no": ver,
        "objectives": objectives,
        "scope_statement": scope,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "return_note": None,
    })
    db.charters[c["id"]] = c
    touch(p)
    return success_object(c, 201)


@app.get("/charters")
def list_charters():
    return list_response(db.charters, [("program_id", "program_id"), ("status", "status")])


@app.get("/charters/<cid>")
def get_charter(cid):
    return get_one("charter", cid)


@app.post("/charters/<cid>/submit")
def submit_charter(cid):
    user_id, _ = require_roles(*PM)
    c = get_or_404("charter", cid)
    p = program_of(c)
    if p["status"] not in CHARTER_PROGRAM_STATES:
        raise ApiError(ERR_INVALID_TRANSITION, "Program must be CHARTERING or ACTIVE", 409)
    if c["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_TRANSITION, "Charter is not DRAFT", 409)
    c["status"] = "SUBMITTED"
    c["submitted_by_user_id"] = user_id
    touch(c)
    touch(p)
    return success_object(c)


@app.post("/charters/<cid>/decide")
def decide_charter(cid):
    user_id, _ = require_roles(*OWNER)
    data = body()
    decision = data.get("decision")
    if decision not in ("APPROVE", "RETURN"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or RETURN", 400)
    epv = data.get("expected_program_version")
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_program_version is required", 400)
    return_note = opt_str(data, "return_note")
    c = get_or_404("charter", cid)
    p = program_of(c)
    if c["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, "Charter is not SUBMITTED", 409)
    if epv != p["version"]:
        raise ApiError(ERR_STALE_PROGRAM_VERSION, "expected_program_version does not match the program's current version", 412)
    if decision == "APPROVE":
        for other in db.charters.values():
            if other["program_id"] == p["id"] and other["status"] == "APPROVED" and other["id"] != c["id"]:
                other["status"] = "SUPERSEDED"
                touch(other)
        c["status"] = "APPROVED"
        p["approved_charter_id"] = c["id"]
    else:
        c["status"] = "RETURNED"
        c["return_note"] = return_note
    c["decided_by_user_id"] = user_id
    touch(c)
    touch(p)
    return success_object(c)


@app.post("/charters/<cid>/revise")
def revise_charter(cid):
    require_roles(*PM)
    c = get_or_404("charter", cid)
    p = program_of(c)
    if c["status"] != "RETURNED":
        raise ApiError(ERR_INVALID_TRANSITION, "Charter is not RETURNED", 409)
    data = body()
    obj = opt_str(data, "objectives")
    scope = opt_str(data, "scope_statement")
    if obj is not None:
        c["objectives"] = obj
    if scope is not None:
        c["scope_statement"] = scope
    c["status"] = "DRAFT"
    touch(c)
    touch(p)
    return success_object(c)


# ===========================================================================
# Baselines
# ===========================================================================

def validate_baseline_payload(data, partial=False):
    """Validate baseline fields. For create (partial=False) all required."""
    out = {}
    if not partial or "total_budget_cents" in data:
        out["total_budget_cents"] = req_int(data, "total_budget_cents", gt=0)
    if not partial or "contingency_total_cents" in data:
        out["contingency_total_cents"] = req_int(data, "contingency_total_cents", minimum=0)
    if not partial or "target_finish_date" in data:
        out["target_finish_date"] = req_date(data, "target_finish_date")
    if not partial or "lines" in data:
        lines = data.get("lines")
        if not isinstance(lines, list) or not lines:
            raise ApiError(ERR_INVALID_REQUEST, "lines must be a non-empty array", 400)
        seen = set()
        norm = []
        for ln in lines:
            if not isinstance(ln, dict):
                raise ApiError(ERR_INVALID_REQUEST, "each line must be an object", 400)
            cc = ln.get("cost_code")
            amt = ln.get("amount_cents")
            if not isinstance(cc, str) or not cc:
                raise ApiError(ERR_INVALID_REQUEST, "line cost_code required", 400)
            if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
                raise ApiError(ERR_INVALID_REQUEST, "line amount_cents must be positive integer", 400)
            if cc in seen:
                raise ApiError(ERR_INVALID_REQUEST, "cost_code must be unique within baseline", 400)
            seen.add(cc)
            norm.append({"cost_code": cc, "amount_cents": amt})
        out["lines"] = norm
    # cross-field checks when both present in `out`
    tb = out.get("total_budget_cents")
    ct = out.get("contingency_total_cents")
    lines = out.get("lines")
    if tb is not None and ct is not None and ct > tb:
        raise ApiError(ERR_INVALID_REQUEST, "contingency_total_cents must be <= total_budget_cents", 400)
    if lines is not None and tb is not None:
        if sum(l["amount_cents"] for l in lines) != tb:
            raise ApiError(ERR_INVALID_REQUEST, "lines must sum to total_budget_cents", 400)
    return out


@app.post("/baselines")
def create_baseline():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    fields = validate_baseline_payload(data, partial=False)
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    if p["status"] not in CHARTER_PROGRAM_STATES:
        raise ApiError(ERR_INVALID_TRANSITION, "Program must be CHARTERING or ACTIVE", 409)
    ver = max([b["version_no"] for b in db.baselines.values() if b["program_id"] == program_id], default=0) + 1
    b = make_common({})
    b.update({
        "program_id": program_id,
        "version_no": ver,
        "total_budget_cents": fields["total_budget_cents"],
        "contingency_total_cents": fields["contingency_total_cents"],
        "target_finish_date": fields["target_finish_date"],
        "lines": fields["lines"],
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "return_note": None,
    })
    db.baselines[b["id"]] = b
    touch(p)
    return success_object(b, 201)


@app.get("/baselines")
def list_baselines():
    return list_response(db.baselines, [("program_id", "program_id"), ("status", "status")])


@app.get("/baselines/<bid>")
def get_baseline(bid):
    return get_one("baseline", bid)


@app.post("/baselines/<bid>/submit")
def submit_baseline(bid):
    user_id, _ = require_roles(*PM)
    b = get_or_404("baseline", bid)
    p = program_of(b)
    if p["status"] not in CHARTER_PROGRAM_STATES:
        raise ApiError(ERR_INVALID_TRANSITION, "Program must be CHARTERING or ACTIVE", 409)
    if b["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_TRANSITION, "Baseline is not DRAFT", 409)
    b["status"] = "SUBMITTED"
    b["submitted_by_user_id"] = user_id
    touch(b)
    touch(p)
    return success_object(b)


@app.post("/baselines/<bid>/decide")
def decide_baseline(bid):
    user_id, _ = require_roles(*OWNER)
    data = body()
    decision = data.get("decision")
    if decision not in ("APPROVE", "RETURN"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or RETURN", 400)
    epv = data.get("expected_program_version")
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_program_version is required", 400)
    return_note = opt_str(data, "return_note")
    b = get_or_404("baseline", bid)
    p = program_of(b)
    if b["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, "Baseline is not SUBMITTED", 409)
    if epv != p["version"]:
        raise ApiError(ERR_STALE_PROGRAM_VERSION, "expected_program_version does not match the program's current version", 412)
    if decision == "APPROVE":
        outstanding = (p["contingency_reserved_cents"] + p["contingency_committed_cents"]
                       + p["contingency_drawn_cents"])
        if b["contingency_total_cents"] < outstanding:
            raise ApiError(ERR_BASELINE_UNDERCUTS_COMMITMENTS,
                           "Rebaseline approval would set contingency_total below outstanding reserved+committed+drawn", 402)
        for other in db.baselines.values():
            if other["program_id"] == p["id"] and other["status"] == "APPROVED" and other["id"] != b["id"]:
                other["status"] = "SUPERSEDED"
                touch(other)
        b["status"] = "APPROVED"
        p["approved_baseline_id"] = b["id"]
        p["baseline_version_no"] = b["version_no"]
        p["current_budget_cents"] = b["total_budget_cents"]
        p["contingency_total_cents"] = b["contingency_total_cents"]
        p["target_finish_date"] = b["target_finish_date"]
        recompute_pool(p)
        refresh_draft_reports(p)
    else:
        b["status"] = "RETURNED"
        b["return_note"] = return_note
    b["decided_by_user_id"] = user_id
    touch(b)
    touch(p)
    return success_object(b)


@app.post("/baselines/<bid>/revise")
def revise_baseline(bid):
    require_roles(*PM)
    b = get_or_404("baseline", bid)
    p = program_of(b)
    if b["status"] != "RETURNED":
        raise ApiError(ERR_INVALID_TRANSITION, "Baseline is not RETURNED", 409)
    data = body()
    fields = validate_baseline_payload(data, partial=True)
    # merged cross-checks against existing values
    tb = fields.get("total_budget_cents", b["total_budget_cents"])
    ct = fields.get("contingency_total_cents", b["contingency_total_cents"])
    lines = fields.get("lines", b["lines"])
    if ct > tb:
        raise ApiError(ERR_INVALID_REQUEST, "contingency_total_cents must be <= total_budget_cents", 400)
    if sum(l["amount_cents"] for l in lines) != tb:
        raise ApiError(ERR_INVALID_REQUEST, "lines must sum to total_budget_cents", 400)
    for k in ("total_budget_cents", "contingency_total_cents", "target_finish_date", "lines"):
        if k in fields:
            b[k] = fields[k]
    b["status"] = "DRAFT"
    touch(b)
    touch(p)
    return success_object(b)


# ===========================================================================
# Contracts
# ===========================================================================

CONTRACT_TYPES = ("CONSULTANT", "CONTRACTOR")


@app.post("/contracts")
def create_contract():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    vendor = req_str(data, "vendor_name")
    ctype = req_enum(data, "contract_type", CONTRACT_TYPES)
    estimate = req_int(data, "solicitation_estimate_cents", gt=0)
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    require_program_active(p)
    c = make_common({})
    c.update({
        "program_id": program_id,
        "vendor_name": vendor,
        "contract_type": ctype,
        "solicitation_estimate_cents": estimate,
        "status": "SOLICITED",
        "negotiator_user_id": None,
        "negotiation_rounds": 0,
        "latest_counter_amount_cents": None,
        "awarded_amount_cents": None,
        "current_commitment_cents": None,
        "executed_by_user_id": None,
    })
    db.contracts[c["id"]] = c
    return success_object(c, 201)


@app.get("/contracts")
def list_contracts():
    return list_response(db.contracts, [("program_id", "program_id"), ("status", "status")])


@app.get("/contracts/<cid>")
def get_contract(cid):
    return get_one("contract", cid)


@app.post("/contracts/<cid>/begin-negotiation")
def begin_negotiation(cid):
    user_id, _ = require_roles(*PM)
    c = get_or_404("contract", cid)
    if c["status"] != "SOLICITED":
        raise ApiError(ERR_INVALID_TRANSITION, "Contract is not SOLICITED", 409)
    c["status"] = "UNDER_NEGOTIATION"
    c["negotiator_user_id"] = user_id
    touch(c)
    return success_object(c)


@app.post("/contracts/<cid>/counter")
def counter_contract(cid):
    require_roles(*PM)
    data = body()
    amount = req_int(data, "counter_amount_cents", gt=0)
    c = get_or_404("contract", cid)
    if c["status"] == "UNDER_NEGOTIATION":
        c["status"] = "COUNTERED"
    elif c["status"] == "COUNTERED":
        c["status"] = "UNDER_NEGOTIATION"
    else:
        raise ApiError(ERR_INVALID_TRANSITION, "Contract is not in a negotiable state", 409)
    c["latest_counter_amount_cents"] = amount
    c["negotiation_rounds"] += 1
    touch(c)
    return success_object(c)


@app.post("/contracts/<cid>/execute")
def execute_contract(cid):
    user_id, _ = require_roles(*EXEC)
    data = body()
    awarded = req_int(data, "awarded_amount_cents", gt=0)
    c = get_or_404("contract", cid)
    if c["status"] not in ("UNDER_NEGOTIATION", "COUNTERED"):
        raise ApiError(ERR_INVALID_TRANSITION, "Contract is not in a executable state", 409)
    if user_id == c["negotiator_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Contract executor must differ from negotiator_user_id", 403)
    p = program_of(c)
    existing = sum(
        x["current_commitment_cents"] or 0
        for x in db.contracts.values()
        if x["program_id"] == p["id"] and x["status"] == "EXECUTED"
    )
    budget = p["current_budget_cents"] or 0
    if awarded > budget - existing:
        raise ApiError(ERR_AWARD_EXCEEDS_BUDGET,
                       "awarded_amount_cents exceeds program budget remaining after existing EXECUTED commitments", 402)
    c["status"] = "EXECUTED"
    c["awarded_amount_cents"] = awarded
    c["current_commitment_cents"] = awarded
    c["executed_by_user_id"] = user_id
    touch(c)
    refresh_draft_reports(p)
    return success_object(c)


@app.post("/contracts/<cid>/complete")
def complete_contract(cid):
    require_roles(*PM)
    c = get_or_404("contract", cid)
    if c["status"] != "EXECUTED":
        raise ApiError(ERR_INVALID_TRANSITION, "Contract is not EXECUTED", 409)
    open_cos = any(
        co["contract_id"] == cid and co["status"] in
        ("DRAFT", "UNDER_REVIEW", "RECOMMEND_APPROVAL", "RECOMMEND_REJECTION", "APPROVED")
        for co in db.change_orders.values())
    if open_cos:
        raise ApiError(ERR_OPEN_CHANGE_ORDERS_EXIST,
                       "Contract completion blocked by change orders in non-terminal states", 409)
    c["status"] = "COMPLETED"
    touch(c)
    p = program_of(c)
    refresh_draft_reports(p)
    return success_object(c)


# ===========================================================================
# Change Orders
# ===========================================================================

@app.post("/change-orders")
def create_change_order():
    require_roles(*PM)
    data = body()
    contract_id = data.get("contract_id")
    title = req_str(data, "title")
    reason = req_str(data, "reason")
    amount = req_int(data, "amount_cents", gt=0)
    supersedes_id = data.get("supersedes_id")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "supersedes_id must be a string", 400)
    if not isinstance(contract_id, str) or not contract_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: contract_id", 400)
    contract = get_or_404("contract", contract_id)
    predecessor = None
    if supersedes_id is not None:
        predecessor = db.change_orders.get(supersedes_id)
        if predecessor is None:
            raise ApiError("ERR_CHANGE_ORDER_NOT_FOUND", "change order id does not exist", 404)
        if predecessor["status"] != "UNDER_REVIEW" or predecessor["contract_id"] != contract_id:
            raise ApiError(ERR_SUPERSEDES_TARGET_INVALID,
                           "supersedes_id does not reference an UNDER_REVIEW change order on the same contract", 409)
    co = make_common({})
    co.update({
        "program_id": contract["program_id"],
        "contract_id": contract_id,
        "supersedes_id": supersedes_id,
        "superseded_by_id": None,
        "title": title,
        "reason": reason,
        "amount_cents": amount,
        "allocated_lines": [],
        "status": "DRAFT",
        "recommended_by_user_id": None,
        "decided_by_user_id": None,
        "linked_drawdown_id": None,
        "revision_note": None,
        "void_reason": None,
    })
    db.change_orders[co["id"]] = co
    if predecessor is not None:
        predecessor["status"] = "REJECTED"
        predecessor["superseded_by_id"] = co["id"]
        touch(predecessor)
    return success_object(co, 201)


@app.get("/change-orders")
def list_change_orders():
    return list_response(db.change_orders, [
        ("program_id", "program_id"), ("contract_id", "contract_id"),
        ("supersedes_id", "supersedes_id"), ("superseded_by_id", "superseded_by_id"),
        ("linked_drawdown_id", "linked_drawdown_id"), ("status", "status"),
    ])


@app.get("/change-orders/<cid>")
def get_change_order(cid):
    return get_one("change_order", cid)


@app.post("/change-orders/<cid>/submit")
def submit_change_order(cid):
    require_roles(*PM)
    co = get_or_404("change_order", cid)
    if co["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_TRANSITION, "Change order is not DRAFT", 409)
    contract = get_or_404("contract", co["contract_id"])
    if contract["status"] != "EXECUTED":
        raise ApiError(ERR_CONTRACT_NOT_EXECUTED,
                       "Change-order submit requires the contract to be EXECUTED", 409)
    p = program_of(co)
    if p["contingency_posture"] == "CRITICAL":
        raise ApiError(ERR_CONTINGENCY_POSTURE_CRITICAL,
                       "Change-order submit blocked while program contingency posture is CRITICAL", 409)
    co["status"] = "UNDER_REVIEW"
    touch(co)
    return success_object(co)


@app.post("/change-orders/<cid>/request-revision")
def request_revision(cid):
    require_roles(*PM)
    data = body()
    note = req_str(data, "revision_note")
    co = get_or_404("change_order", cid)
    if co["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_TRANSITION, "Change order is not UNDER_REVIEW", 409)
    co["status"] = "DRAFT"
    co["revision_note"] = note
    touch(co)
    return success_object(co)


@app.post("/change-orders/<cid>/recommend")
def recommend_change_order(cid):
    user_id, _ = require_roles(*PM)
    data = body()
    rec = data.get("recommendation")
    if rec not in ("APPROVE", "REJECT"):
        raise ApiError(ERR_INVALID_REQUEST, "recommendation must be APPROVE or REJECT", 400)
    req_str(data, "analysis_note")
    co = get_or_404("change_order", cid)
    if co["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_TRANSITION, "Change order is not UNDER_REVIEW", 409)
    co["status"] = "RECOMMEND_APPROVAL" if rec == "APPROVE" else "RECOMMEND_REJECTION"
    co["recommended_by_user_id"] = user_id
    touch(co)
    return success_object(co)


def compute_allocated_lines(amount, program):
    """Waterfall allocation per calculations.change_order_cost_code_distribution."""
    baseline = db.baselines.get(program["approved_baseline_id"]) if program.get("approved_baseline_id") else None
    if baseline is None:
        return []
    lines = baseline["lines"]
    W = sum(l["amount_cents"] for l in lines)
    if W == 0:
        return []
    exacts = []  # list of Decimal exact shares
    fracs = []   # fractional parts of exact
    shares = []
    for l in lines:
        exact = Decimal(amount) * Decimal(l["amount_cents"]) / Decimal(W)
        share = int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        exacts.append(exact)
        fracs.append(exact - Decimal(int(exact)))
        shares.append(share)
    delta = amount - sum(shares)
    if delta != 0:
        if delta > 0:
            # largest fractional part; ties by cost_code ascending
            best = None
            for i, l in enumerate(lines):
                if best is None or fracs[i] > fracs[best] or \
                   (fracs[i] == fracs[best] and l["cost_code"] < lines[best]["cost_code"]):
                    best = i
        else:
            # smallest fractional part; ties by cost_code ascending
            best = None
            for i, l in enumerate(lines):
                if best is None or fracs[i] < fracs[best] or \
                   (fracs[i] == fracs[best] and l["cost_code"] < lines[best]["cost_code"]):
                    best = i
        shares[best] += delta
    return [{"cost_code": l["cost_code"], "allocated_cents": shares[i]}
            for i, l in enumerate(lines)]


@app.post("/change-orders/<cid>/decide")
def decide_change_order(cid):
    user_id, _ = require_roles(*OWNER)
    data = body()
    decision = data.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT", 400)
    co = get_or_404("change_order", cid)
    if co["status"] not in ("RECOMMEND_APPROVAL", "RECOMMEND_REJECTION"):
        raise ApiError(ERR_INVALID_TRANSITION, "Change order is not in a recommendation state", 409)
    if user_id == co["recommended_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "CO decider must differ from recommended_by_user_id", 403)
    p = program_of(co)
    if decision == "APPROVE":
        if co["amount_cents"] > p["contingency_available_cents"]:
            raise ApiError(ERR_CONTINGENCY_EXCEEDED,
                           "Requested draw/reserve/loss exceeds contingency_available_cents", 402)
        contract = get_or_404("contract", co["contract_id"])
        # link 1: commitment up
        contract["current_commitment_cents"] = (contract["current_commitment_cents"] or 0) + co["amount_cents"]
        touch(contract)
        # link 2: auto-create COMMITTED drawdown
        dd = make_common({})
        dd.update({
            "program_id": p["id"],
            "risk_entry_id": None,
            "change_order_id": co["id"],
            "source": "CHANGE_ORDER",
            "purpose": f"Auto-created COMMITTED draw for change order {co['id']}",
            "amount_cents": co["amount_cents"],
            "status": "COMMITTED",
        })
        db.drawdowns[dd["id"]] = dd
        co["linked_drawdown_id"] = dd["id"]
        # link 3: pool move + posture
        p["contingency_committed_cents"] += co["amount_cents"]
        p["contingency_available_cents"] -= co["amount_cents"]
        recompute_posture(p)
        touch(p)
        # allocated lines
        co["allocated_lines"] = compute_allocated_lines(co["amount_cents"], p)
        # link 4: refresh DRAFT reports
        refresh_draft_reports(p)
        co["status"] = "APPROVED"
    else:
        co["status"] = "REJECTED"
    co["decided_by_user_id"] = user_id
    touch(co)
    return success_object(co)


@app.post("/change-orders/<cid>/void")
def void_change_order(cid):
    require_roles(*OWNER)
    data = body()
    reason = req_str(data, "void_reason")
    co = get_or_404("change_order", cid)
    if co["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_TRANSITION, "Change order is not APPROVED", 409)
    contract = get_or_404("contract", co["contract_id"])
    p = program_of(co)
    # compensation link 1
    contract["current_commitment_cents"] = (contract["current_commitment_cents"] or 0) - co["amount_cents"]
    touch(contract)
    # link 2: release linked drawdown
    dd = db.drawdowns.get(co["linked_drawdown_id"])
    if dd is not None and dd["status"] == "COMMITTED":
        dd["status"] = "RELEASED"
        touch(dd)
    # link 3: pool release
    p["contingency_committed_cents"] -= co["amount_cents"]
    p["contingency_available_cents"] += co["amount_cents"]
    recompute_posture(p)
    touch(p)
    # link 4: refresh DRAFT reports
    refresh_draft_reports(p)
    co["status"] = "VOID"
    co["void_reason"] = reason
    touch(co)
    return success_object(co)


# ===========================================================================
# Risk Entries
# ===========================================================================

RISK_CATEGORIES = ("SCHEDULE", "COST", "SCOPE", "STAKEHOLDER", "SITE")


def compute_exposure(prob, impact):
    return round_half_up_int(prob * impact, 100)


@app.post("/risk-entries")
def create_risk_entry():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    title = req_str(data, "title")
    category = req_enum(data, "category", RISK_CATEGORIES)
    prob = req_int(data, "probability_pct", minimum=1, maximum=100)
    impact = req_int(data, "impact_cents", minimum=0)
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    require_program_active(p)
    r = make_common({})
    r.update({
        "program_id": program_id,
        "title": title,
        "category": category,
        "probability_pct": prob,
        "impact_cents": impact,
        "exposure_cents": compute_exposure(prob, impact),
        "status": "IDENTIFIED",
        "mitigation_plan": None,
        "realized_loss_cents": None,
        "linked_drawdown_id": None,
    })
    db.risk_entries[r["id"]] = r
    return success_object(r, 201)


@app.get("/risk-entries")
def list_risk_entries():
    return list_response(db.risk_entries, [
        ("program_id", "program_id"), ("status", "status"),
        ("linked_drawdown_id", "linked_drawdown_id"),
    ])


@app.get("/risk-entries/<rid>")
def get_risk_entry(rid):
    return get_one("risk_entry", rid)


@app.post("/risk-entries/<rid>/assess")
def assess_risk(rid):
    require_roles(*PM)
    data = body()
    prob = req_int(data, "probability_pct", minimum=1, maximum=100)
    impact = req_int(data, "impact_cents", minimum=0)
    r = get_or_404("risk_entry", rid)
    if r["status"] not in ("IDENTIFIED", "ASSESSED", "MONITORING", "ESCALATED"):
        raise ApiError(ERR_INVALID_TRANSITION, "Risk entry is not assessable", 409)
    exposure = compute_exposure(prob, impact)
    r["probability_pct"] = prob
    r["impact_cents"] = impact
    r["exposure_cents"] = exposure
    at_or_above = exposure >= ESCALATION_THRESHOLD_CENTS
    cur = r["status"]
    if cur == "IDENTIFIED":
        r["status"] = "ESCALATED" if at_or_above else "ASSESSED"
    elif cur == "ASSESSED":
        r["status"] = "ESCALATED" if at_or_above else "ASSESSED"
    elif cur == "MONITORING":
        r["status"] = "ESCALATED" if at_or_above else "MONITORING"
    elif cur == "ESCALATED":
        r["status"] = "ESCALATED" if at_or_above else "MONITORING"
    touch(r)
    return success_object(r)


@app.post("/risk-entries/<rid>/mitigate")
def mitigate_risk(rid):
    require_roles(*PM)
    data = body()
    plan = req_str(data, "mitigation_plan")
    r = get_or_404("risk_entry", rid)
    if r["status"] not in ("ASSESSED", "ESCALATED"):
        raise ApiError(ERR_INVALID_TRANSITION, "Risk entry is not in ASSESSED or ESCALATED", 409)
    r["status"] = "MITIGATING"
    r["mitigation_plan"] = plan
    touch(r)
    return success_object(r)


@app.post("/risk-entries/<rid>/monitor")
def monitor_risk(rid):
    require_roles(*PM)
    r = get_or_404("risk_entry", rid)
    if r["status"] != "MITIGATING":
        raise ApiError(ERR_INVALID_TRANSITION, "Risk entry is not MITIGATING", 409)
    r["status"] = "MONITORING"
    touch(r)
    return success_object(r)


@app.post("/risk-entries/<rid>/realize")
def realize_risk(rid):
    require_roles(*PM)
    data = body()
    loss = req_int(data, "actual_loss_cents", gt=0)
    r = get_or_404("risk_entry", rid)
    if r["status"] not in ("ESCALATED", "MONITORING"):
        raise ApiError(ERR_INVALID_TRANSITION, "Risk entry is not ESCALATED or MONITORING", 409)
    p = program_of(r)
    if loss > p["contingency_available_cents"]:
        raise ApiError(ERR_CONTINGENCY_EXCEEDED,
                       "Requested draw/reserve/loss exceeds contingency_available_cents", 402)
    # link 1
    r["realized_loss_cents"] = loss
    dd = make_common({})
    dd.update({
        "program_id": p["id"],
        "risk_entry_id": r["id"],
        "change_order_id": None,
        "source": "RISK_REALIZATION",
        "purpose": f"Auto-created COMMITTED draw for risk realization {r['id']}",
        "amount_cents": loss,
        "status": "COMMITTED",
    })
    db.drawdowns[dd["id"]] = dd
    r["linked_drawdown_id"] = dd["id"]
    r["status"] = "REALIZED"
    touch(r)
    # link 2
    p["contingency_committed_cents"] += loss
    p["contingency_available_cents"] -= loss
    recompute_posture(p)
    touch(p)
    # link 3
    refresh_draft_reports(p)
    return success_object(r)


@app.post("/risk-entries/<rid>/close")
def close_risk(rid):
    require_roles(*PM)
    r = get_or_404("risk_entry", rid)
    if r["status"] not in ("ASSESSED", "MITIGATING", "MONITORING"):
        raise ApiError(ERR_INVALID_TRANSITION, "Risk entry is not closable", 409)
    r["status"] = "CLOSED"
    touch(r)
    return success_object(r)


# ===========================================================================
# Contingency Drawdowns
# ===========================================================================

@app.post("/contingency-drawdowns")
def create_drawdown():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    purpose = req_str(data, "purpose")
    amount = req_int(data, "amount_cents", gt=0)
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    if amount > p["contingency_available_cents"]:
        raise ApiError(ERR_CONTINGENCY_EXCEEDED,
                       "Requested draw/reserve/loss exceeds contingency_available_cents", 402)
    dd = make_common({})
    dd.update({
        "program_id": program_id,
        "risk_entry_id": None,
        "change_order_id": None,
        "source": "MANUAL_RESERVE",
        "purpose": purpose,
        "amount_cents": amount,
        "status": "RESERVED",
    })
    db.drawdowns[dd["id"]] = dd
    p["contingency_reserved_cents"] += amount
    p["contingency_available_cents"] -= amount
    recompute_posture(p)
    touch(p)
    refresh_draft_reports(p)
    return success_object(dd, 201)


@app.get("/contingency-drawdowns")
def list_drawdowns():
    return list_response(db.drawdowns, [
        ("program_id", "program_id"), ("risk_entry_id", "risk_entry_id"),
        ("change_order_id", "change_order_id"), ("status", "status"),
    ])


@app.get("/contingency-drawdowns/<did>")
def get_drawdown(did):
    return get_one("drawdown", did)


def _pool_after_dd_transition(p, dd, frm, to):
    if frm == "RESERVED":
        p["contingency_reserved_cents"] -= dd["amount_cents"]
    elif frm == "COMMITTED":
        p["contingency_committed_cents"] -= dd["amount_cents"]
    if to == "COMMITTED":
        p["contingency_committed_cents"] += dd["amount_cents"]
    elif to == "DRAWN":
        p["contingency_drawn_cents"] += dd["amount_cents"]
    elif to == "RELEASED":
        p["contingency_available_cents"] += dd["amount_cents"]
    recompute_posture(p)
    touch(p)


@app.post("/contingency-drawdowns/<did>/commit")
def commit_drawdown(did):
    require_roles(*PM)
    dd = get_or_404("drawdown", did)
    if dd["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_TRANSITION, "Drawdown is not RESERVED", 409)
    dd["status"] = "COMMITTED"
    touch(dd)
    p = program_of(dd)
    _pool_after_dd_transition(p, dd, "RESERVED", "COMMITTED")
    refresh_draft_reports(p)
    return success_object(dd)


@app.post("/contingency-drawdowns/<did>/draw")
def draw_drawdown(did):
    require_roles(*PM)
    dd = get_or_404("drawdown", did)
    if dd["status"] != "COMMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, "Drawdown is not COMMITTED", 409)
    dd["status"] = "DRAWN"
    touch(dd)
    p = program_of(dd)
    _pool_after_dd_transition(p, dd, "COMMITTED", "DRAWN")
    refresh_draft_reports(p)
    return success_object(dd)


@app.post("/contingency-drawdowns/<did>/release")
def release_drawdown(did):
    require_roles(*PM)
    dd = get_or_404("drawdown", did)
    if dd["status"] not in ("RESERVED", "COMMITTED"):
        raise ApiError(ERR_INVALID_TRANSITION, "Drawdown is not RESERVED or COMMITTED", 409)
    frm = dd["status"]
    dd["status"] = "RELEASED"
    touch(dd)
    p = program_of(dd)
    _pool_after_dd_transition(p, dd, frm, "RELEASED")
    refresh_draft_reports(p)
    return success_object(dd)


# ===========================================================================
# Owner Reports
# ===========================================================================

@app.post("/owner-reports")
def create_owner_report():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    period = req_month(data, "period")
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    require_program_active(p)
    if any(r["program_id"] == program_id and r["period"] == period
           for r in db.owner_reports.values()):
        raise ApiError(ERR_DUPLICATE_REPORT_PERIOD,
                       "An owner report already exists for this (program_id, period)", 409)
    fields = compute_forecast(p)
    rep = make_common({})
    rep.update({
        "program_id": program_id,
        "period": period,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "accepted_by_user_id": None,
        "return_note": None,
        "accepted_at": None,
    })
    rep.update(fields)
    db.owner_reports[rep["id"]] = rep
    return success_object(rep, 201)


@app.get("/owner-reports")
def list_owner_reports():
    return list_response(db.owner_reports, [
        ("program_id", "program_id"), ("status", "status"), ("period", "period"),
    ])


@app.get("/owner-reports/<rid>")
def get_owner_report(rid):
    return get_one("owner_report", rid)


@app.post("/owner-reports/<rid>/submit")
def submit_owner_report(rid):
    user_id, _ = require_roles(*PM)
    rep = get_or_404("owner_report", rid)
    if rep["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(ERR_INVALID_TRANSITION, "Report is not DRAFT or RETURNED", 409)
    p = program_of(rep)
    rep.update(compute_forecast(p))
    rep["status"] = "SUBMITTED"
    rep["submitted_by_user_id"] = user_id
    touch(rep)
    return success_object(rep)


@app.post("/owner-reports/<rid>/accept")
def accept_owner_report(rid):
    user_id, _ = require_roles(*OWNER)
    rep = get_or_404("owner_report", rid)
    if rep["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, "Report is not SUBMITTED", 409)
    if user_id == rep["submitted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Report accepter must differ from submitted_by_user_id", 403)
    rep["status"] = "ACCEPTED"
    rep["accepted_by_user_id"] = user_id
    rep["accepted_at"] = now_iso()
    touch(rep)
    return success_object(rep)


@app.post("/owner-reports/<rid>/return")
def return_owner_report(rid):
    require_roles(*OWNER)
    data = body()
    note = req_str(data, "return_note")
    rep = get_or_404("owner_report", rid)
    if rep["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, "Report is not SUBMITTED", 409)
    rep["status"] = "RETURNED"
    rep["return_note"] = note
    touch(rep)
    return success_object(rep)


# ===========================================================================
# Stakeholder Groups
# ===========================================================================

GROUP_TYPES = ("USER_GROUP", "AUTHORITIES", "COMMUNITY", "OPERATIONS")


@app.post("/stakeholder-groups")
def create_stakeholder_group():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    name = req_str(data, "group_name")
    gtype = req_enum(data, "group_type", GROUP_TYPES)
    email = req_str(data, "contact_email")
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    require_program_active(p)
    g = make_common({})
    g.update({
        "program_id": program_id,
        "group_name": name,
        "group_type": gtype,
        "contact_email": email,
    })
    db.stakeholder_groups[g["id"]] = g
    return success_object(g, 201)


@app.get("/stakeholder-groups")
def list_stakeholder_groups():
    return list_response(db.stakeholder_groups, [
        ("program_id", "program_id"), ("group_type", "group_type"),
    ])


@app.get("/stakeholder-groups/<gid>")
def get_stakeholder_group(gid):
    return get_one("stakeholder_group", gid)


# ===========================================================================
# Engagement Items
# ===========================================================================

@app.post("/engagements")
def create_engagement():
    require_roles(*PM)
    data = body()
    group_id = data.get("stakeholder_group_id")
    title = req_str(data, "title")
    start = parse_dt(data.get("scheduled_start"), "scheduled_start")
    end = parse_dt(data.get("scheduled_end"), "scheduled_end")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, "scheduled_end must be after scheduled_start", 400)
    if not isinstance(group_id, str) or not group_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: stakeholder_group_id", 400)
    g = get_or_404("stakeholder_group", group_id)
    duration = int((end - start).total_seconds() // 60)
    e = make_common({})
    e.update({
        "program_id": g["program_id"],
        "stakeholder_group_id": group_id,
        "title": title,
        "scheduled_start": data.get("scheduled_start"),
        "scheduled_end": data.get("scheduled_end"),
        "duration_minutes": duration,
        "status": "PROPOSED",
        "_start_dt": start,
        "_end_dt": end,
    })
    db.engagements[e["id"]] = e
    out = {k: v for k, v in e.items() if not k.startswith("_")}
    return success_object(out, 201)


def _eng_public(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


@app.get("/engagements")
def list_engagements():
    require_roles(*ALL_ROLES)
    items = list(db.engagements.values())
    for qp, field in [("program_id", "program_id"), ("stakeholder_group_id", "stakeholder_group_id"),
                      ("status", "status")]:
        v = request.args.get(qp)
        if v is not None:
            items = [it for it in items if str(it.get(field)) == v]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameter", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameter", 400)
    page = [_eng_public(it) for it in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@app.get("/engagements/<eid>")
def get_engagement(eid):
    require_roles(*ALL_ROLES)
    e = get_or_404("engagement", eid)
    return success_object(_eng_public(e))


@app.post("/engagements/<eid>/schedule")
def schedule_engagement(eid):
    require_roles(*PM)
    e = get_or_404("engagement", eid)
    if e["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_TRANSITION, "Engagement is not PROPOSED", 409)
    gid = e["stakeholder_group_id"]
    start = e["_start_dt"]
    end = e["_end_dt"]
    # closed-interval overlap: touching endpoints conflict
    for other in db.engagements.values():
        if other["id"] == eid or other["stakeholder_group_id"] != gid:
            continue
        if other["status"] != "SCHEDULED":
            continue
        os_, oe = other["_start_dt"], other["_end_dt"]
        if start <= oe and os_ <= end:
            raise ApiError(ERR_ENGAGEMENT_OVERLAP,
                           "Engagement collides with another SCHEDULED engagement of the same group", 409)
    # daily cap (inclusive 360) keyed on UTC date of candidate start
    day = start.date()
    load = sum(
        o["duration_minutes"]
        for o in db.engagements.values()
        if o["stakeholder_group_id"] == gid and o["status"] == "SCHEDULED"
        and o["_start_dt"].date() == day
    )
    if load + e["duration_minutes"] > ENGAGEMENT_DAILY_CAP_MINUTES:
        raise ApiError(ERR_ENGAGEMENT_DAILY_CAP_EXCEEDED,
                       "Group's SCHEDULED minutes for the UTC date would exceed 360", 409)
    e["status"] = "SCHEDULED"
    touch(e)
    return success_object(_eng_public(e))


@app.post("/engagements/<eid>/complete")
def complete_engagement(eid):
    require_roles(*PM)
    e = get_or_404("engagement", eid)
    if e["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_TRANSITION, "Engagement is not SCHEDULED", 409)
    e["status"] = "HELD"
    touch(e)
    return success_object(_eng_public(e))


@app.post("/engagements/<eid>/cancel")
def cancel_engagement(eid):
    require_roles(*PM)
    e = get_or_404("engagement", eid)
    if e["status"] not in ("PROPOSED", "SCHEDULED"):
        raise ApiError(ERR_INVALID_TRANSITION, "Engagement is not PROPOSED or SCHEDULED", 409)
    e["status"] = "CANCELLED"
    touch(e)
    return success_object(_eng_public(e))


# ===========================================================================
# Occupancy Plans
# ===========================================================================

@app.post("/occupancy-plans")
def create_occupancy_plan():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    name = req_str(data, "plan_name")
    month = req_month(data, "target_move_month")
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    if p["status"] not in ("CHARTERING", "ACTIVE"):
        raise ApiError(ERR_INVALID_TRANSITION, "Program must be CHARTERING or ACTIVE", 409)
    op = make_common({})
    op.update({
        "program_id": program_id,
        "plan_name": name,
        "target_move_month": month,
        "status": "PLANNING",
        "readiness_unweighted_pct": 0.0,
        "readiness_weighted_pct": 0.0,
    })
    db.occupancy_plans[op["id"]] = op
    return success_object(op, 201)


@app.get("/occupancy-plans")
def list_occupancy_plans():
    return list_response(db.occupancy_plans, [
        ("program_id", "program_id"), ("status", "status"),
    ])


@app.get("/occupancy-plans/<oid>")
def get_occupancy_plan(oid):
    return get_one("occupancy_plan", oid)


def compute_readiness(plan):
    waves = [
        w for w in db.move_in_waves.values()
        if w["occupancy_plan_id"] == plan["id"] and w["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETE")
    ]
    count = len(waves)
    done = sum(1 for w in waves if w["status"] == "COMPLETE")
    unweighted = round_half_up_2dp(100 * done, count) if count else 0.0
    total_weight = sum(w["criticality_weight"] for w in waves)
    done_weight = sum(w["criticality_weight"] for w in waves if w["status"] == "COMPLETE")
    weighted = round_half_up_2dp(100 * done_weight, total_weight) if total_weight else 0.0
    plan["readiness_unweighted_pct"] = unweighted
    plan["readiness_weighted_pct"] = weighted


@app.post("/occupancy-plans/<oid>/coordinate")
def coordinate_plan(oid):
    require_roles(*PM)
    op = get_or_404("occupancy_plan", oid)
    if op["status"] not in ("PLANNING", "READY"):
        raise ApiError(ERR_INVALID_TRANSITION, "Plan is not PLANNING or READY", 409)
    op["status"] = "COORDINATING"
    touch(op)
    return success_object(op)


@app.post("/occupancy-plans/<oid>/mark-ready")
def mark_ready_plan(oid):
    require_roles(*PM)
    op = get_or_404("occupancy_plan", oid)
    if op["status"] != "COORDINATING":
        raise ApiError(ERR_INVALID_TRANSITION, "Plan is not COORDINATING", 409)
    p = program_of(op)
    if not p["approved_baseline_id"]:
        raise ApiError(ERR_NO_APPROVED_BASELINE,
                       "Plan mark-ready requires an APPROVED baseline", 409)
    op["status"] = "READY"
    compute_readiness(op)
    touch(op)
    return success_object(op)


@app.post("/occupancy-plans/<oid>/execute")
def execute_plan(oid):
    require_roles(*PM)
    op = get_or_404("occupancy_plan", oid)
    if op["status"] != "READY":
        raise ApiError(ERR_INVALID_TRANSITION, "Plan is not READY", 409)
    op["status"] = "EXECUTING"
    touch(op)
    return success_object(op)


@app.post("/occupancy-plans/<oid>/complete")
def complete_plan(oid):
    require_roles(*PM)
    op = get_or_404("occupancy_plan", oid)
    if op["status"] != "EXECUTING":
        raise ApiError(ERR_INVALID_TRANSITION, "Plan is not EXECUTING", 409)
    open_waves = any(
        w["occupancy_plan_id"] == oid and w["status"] in ("SCHEDULED", "CONFIRMED")
        for w in db.move_in_waves.values())
    if open_waves:
        raise ApiError(ERR_OPEN_WAVES_EXIST,
                       "Plan completion blocked: waves still in SCHEDULED or CONFIRMED", 409)
    op["status"] = "COMPLETE"
    touch(op)
    return success_object(op)


# ===========================================================================
# Move-In Waves
# ===========================================================================

DOCK_RESOURCES = ("DOCK_A", "DOCK_B", "DOCK_C")


def _dock_conflict(program_id, dock, start, end, exclude_id=None):
    """Half-open [start, end+buffer) overlap among SCHEDULED/CONFIRMED waves."""
    buf = timedelta(hours=TURNOVER_BUFFER_HOURS)
    cand_end = end + buf
    for w in db.move_in_waves.values():
        if exclude_id is not None and w["id"] == exclude_id:
            continue
        if w["program_id"] != program_id or w["dock_resource"] != dock:
            continue
        if w["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        ws = w["_move_start_dt"]
        we = w["_move_end_dt"] + buf
        if start < we and ws < cand_end:
            return True
    return False


@app.post("/move-in-waves")
def create_wave():
    require_roles(*PM)
    data = body()
    plan_id = data.get("occupancy_plan_id")
    group_id = data.get("stakeholder_group_id")
    wave_name = req_str(data, "wave_name")
    dock = req_enum(data, "dock_resource", DOCK_RESOURCES)
    mstart = parse_dt(data.get("move_start"), "move_start")
    mend = parse_dt(data.get("move_end"), "move_end")
    if mend <= mstart:
        raise ApiError(ERR_INVALID_REQUEST, "move_end must be after move_start", 400)
    weight = req_int(data, "criticality_weight", minimum=1)
    if not isinstance(plan_id, str) or not plan_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: occupancy_plan_id", 400)
    if not isinstance(group_id, str) or not group_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: stakeholder_group_id", 400)
    plan = get_or_404("occupancy_plan", plan_id)
    group = get_or_404("stakeholder_group", group_id)
    if plan["status"] not in ("COORDINATING", "READY", "EXECUTING"):
        raise ApiError(ERR_PLAN_NOT_ACCEPTING_WAVES,
                       "Wave creation requires the plan to be COORDINATING, READY, or EXECUTING", 409)
    if group["program_id"] != plan["program_id"]:
        raise ApiError(ERR_CROSS_PROGRAM_REFERENCE,
                       "Body-supplied FK references an entity belonging to a different program", 409)
    if _dock_conflict(plan["program_id"], dock, mstart, mend):
        raise ApiError(ERR_DOCK_OVERLAP,
                       "Wave collides with an occupying wave on the same dock", 409)
    w = make_common({})
    w.update({
        "program_id": plan["program_id"],
        "occupancy_plan_id": plan_id,
        "stakeholder_group_id": group_id,
        "wave_name": wave_name,
        "dock_resource": dock,
        "move_start": data.get("move_start"),
        "move_end": data.get("move_end"),
        "criticality_weight": weight,
        "status": "SCHEDULED",
        "_move_start_dt": mstart,
        "_move_end_dt": mend,
    })
    db.move_in_waves[w["id"]] = w
    return success_object(_wave_public(w), 201)


def _wave_public(w):
    return {k: v for k, v in w.items() if not k.startswith("_")}


@app.get("/move-in-waves")
def list_waves():
    require_roles(*ALL_ROLES)
    items = list(db.move_in_waves.values())
    for qp, field in [("occupancy_plan_id", "occupancy_plan_id"),
                      ("stakeholder_group_id", "stakeholder_group_id"),
                      ("program_id", "program_id"), ("status", "status")]:
        v = request.args.get(qp)
        if v is not None:
            items = [it for it in items if str(it.get(field)) == v]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameter", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid pagination parameter", 400)
    page = [_wave_public(it) for it in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@app.get("/move-in-waves/<wid>")
def get_wave(wid):
    require_roles(*ALL_ROLES)
    w = get_or_404("move_in_wave", wid)
    return success_object(_wave_public(w))


@app.post("/move-in-waves/<wid>/confirm")
def confirm_wave(wid):
    require_roles(*PM)
    w = get_or_404("move_in_wave", wid)
    if w["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_TRANSITION, "Wave is not SCHEDULED", 409)
    plan = get_or_404("occupancy_plan", w["occupancy_plan_id"])
    if plan["status"] not in ("READY", "EXECUTING"):
        raise ApiError(ERR_PLAN_NOT_READY,
                       "Wave confirm requires the occupancy plan to be READY or EXECUTING", 409)
    if _dock_conflict(w["program_id"], w["dock_resource"], w["_move_start_dt"], w["_move_end_dt"], exclude_id=wid):
        raise ApiError(ERR_DOCK_OVERLAP,
                       "Wave collides with an occupying wave on the same dock", 409)
    w["status"] = "CONFIRMED"
    touch(w)
    return success_object(_wave_public(w))


@app.post("/move-in-waves/<wid>/complete")
def complete_wave(wid):
    require_roles(*PM)
    w = get_or_404("move_in_wave", wid)
    if w["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_TRANSITION, "Wave is not CONFIRMED", 409)
    w["status"] = "COMPLETE"
    touch(w)
    plan = get_or_404("occupancy_plan", w["occupancy_plan_id"])
    compute_readiness(plan)
    touch(plan)
    return success_object(_wave_public(w))


@app.post("/move-in-waves/<wid>/cancel")
def cancel_wave(wid):
    require_roles(*PM)
    w = get_or_404("move_in_wave", wid)
    if w["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_TRANSITION, "Wave is not SCHEDULED or CONFIRMED", 409)
    w["status"] = "CANCELLED"
    touch(w)
    plan = get_or_404("occupancy_plan", w["occupancy_plan_id"])
    compute_readiness(plan)
    touch(plan)
    return success_object(_wave_public(w))


# ===========================================================================
# Closeout Items
# ===========================================================================

CLOSEOUT_TYPES = ("PUNCH_LIST", "WARRANTY", "AS_BUILT", "FINAL_ACCOUNT", "TRAINING")


@app.post("/closeout-items")
def create_closeout_item():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    itype = req_enum(data, "item_type", CLOSEOUT_TYPES)
    title = req_str(data, "title")
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    if p["status"] not in ("ACTIVE", "CLOSING"):
        raise ApiError(ERR_INVALID_TRANSITION, "Program must be ACTIVE or CLOSING", 409)
    ci = make_common({})
    ci.update({
        "program_id": program_id,
        "item_type": itype,
        "title": title,
        "status": "OPEN",
        "submitted_by_user_id": None,
        "verified_by_user_id": None,
        "rejection_note": None,
    })
    db.closeout_items[ci["id"]] = ci
    return success_object(ci, 201)


@app.get("/closeout-items")
def list_closeout_items():
    return list_response(db.closeout_items, [
        ("program_id", "program_id"), ("item_type", "item_type"), ("status", "status"),
    ])


@app.get("/closeout-items/<cid>")
def get_closeout_item(cid):
    return get_one("closeout_item", cid)


@app.post("/closeout-items/<cid>/submit")
def submit_closeout_item(cid):
    user_id, _ = require_roles(*PM)
    ci = get_or_404("closeout_item", cid)
    if ci["status"] != "OPEN":
        raise ApiError(ERR_INVALID_TRANSITION, "Closeout item is not OPEN", 409)
    ci["status"] = "SUBMITTED"
    ci["submitted_by_user_id"] = user_id
    touch(ci)
    return success_object(ci)


@app.post("/closeout-items/<cid>/verify")
def verify_closeout_item(cid):
    user_id, _ = require_roles(*EXEC)
    ci = get_or_404("closeout_item", cid)
    if ci["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, "Closeout item is not SUBMITTED", 409)
    if user_id == ci["submitted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Closeout verifier must differ from submitted_by_user_id", 403)
    ci["status"] = "VERIFIED"
    ci["verified_by_user_id"] = user_id
    touch(ci)
    return success_object(ci)


@app.post("/closeout-items/<cid>/reject")
def reject_closeout_item(cid):
    require_roles(*EXEC)
    data = body()
    note = req_str(data, "rejection_note")
    ci = get_or_404("closeout_item", cid)
    if ci["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, "Closeout item is not SUBMITTED", 409)
    ci["status"] = "OPEN"
    ci["rejection_note"] = note
    touch(ci)
    return success_object(ci)


# ===========================================================================
# Lesson Entries (append-only)
# ===========================================================================

LESSON_CATEGORIES = ("SCHEDULE", "COST", "SCOPE", "STAKEHOLDER", "SITE", "PROCUREMENT")


@app.post("/lesson-entries")
def create_lesson_entry():
    require_roles(*PM)
    data = body()
    program_id = data.get("program_id")
    category = req_enum(data, "category", LESSON_CATEGORIES)
    text = req_str(data, "lesson_text")
    rec = req_str(data, "recommendation")
    if not isinstance(program_id, str) or not program_id:
        raise ApiError(ERR_INVALID_REQUEST, "Missing or invalid required field: program_id", 400)
    p = get_or_404("program", program_id)
    if p["status"] not in ("ACTIVE", "CLOSING"):
        raise ApiError(ERR_INVALID_TRANSITION, "Program must be ACTIVE or CLOSING", 409)
    import uuid as _uuid
    le = {
        "id": str(_uuid.uuid4()),
        "created_at": now_iso(),
        "program_id": program_id,
        "category": category,
        "lesson_text": text,
        "recommendation": rec,
    }
    db.lesson_entries[le["id"]] = le
    return success_object(le, 201)


@app.get("/lesson-entries")
def list_lesson_entries():
    return list_response(db.lesson_entries, [
        ("program_id", "program_id"), ("category", "category"),
    ])


@app.get("/lesson-entries/<lid>")
def get_lesson_entry(lid):
    require_roles(*ALL_ROLES)
    le = db.lesson_entries.get(lid)
    if le is None:
        raise ApiError("ERR_LESSON_ENTRY_NOT_FOUND", "lesson entry id does not exist", 404)
    return success_object(le)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
