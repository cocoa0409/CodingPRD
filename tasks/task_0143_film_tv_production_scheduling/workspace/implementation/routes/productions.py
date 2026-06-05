"""Production lifecycle, budget lines, manual actuals, budget summary."""
from flask import Blueprint

from db import db, now_iso, new_id
from errors import err
from middleware import authenticate, authorize
from helpers import (get_json_body, require_string, require_enum, require_int,
                     parse_pagination, paginate)
from response import success_object, success_array
from services.serialize import public
from services.recompute import (touch, recompute_committed_cost, recompute_variance,
                                assignments_for_production)

bp = Blueprint("productions", __name__)

PRODUCTION_TYPES = {"FEATURE", "EPISODIC"}
BUDGET_CATEGORIES = {"ABOVE_THE_LINE", "BELOW_THE_LINE_LABOR", "LOCATIONS", "POST", "FRINGES"}

ALL_ROLES = {"LineProducer", "FirstAD", "PayrollCoordinator", "PostSupervisor", "UnionRep"}


def _new_production(title, production_type, total_budget_cents):
    ts = now_iso()
    return {
        "id": new_id(),
        "title": title,
        "production_type": production_type,
        "status": "DRAFT",
        "total_budget_cents": total_budget_cents,
        "committed_cost_cents": 0,
        "actual_cost_cents": 0,
        "residual_reserve_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


# --- Production CRUD --------------------------------------------------------
@bp.route("/productions", methods=["POST"])
def create_production():
    role = authenticate()
    authorize(role, {"LineProducer"})
    body = get_json_body()
    title = require_string(body, "title")
    ptype = require_enum(body, "production_type", PRODUCTION_TYPES)
    budget = require_int(body, "total_budget_cents", minimum=0)
    with db.lock:
        prod = _new_production(title, ptype, budget)
        db.productions[prod["id"]] = prod
        return success_object(public(prod), status=201)


@bp.route("/productions/<pid>", methods=["GET"])
def get_production(pid):
    role = authenticate()
    authorize(role, ALL_ROLES)
    prod = db.productions.get(pid)
    if not prod:
        raise err("ERR_NOT_FOUND", "Production not found.")
    return success_object(public(prod))


@bp.route("/productions", methods=["GET"])
def list_productions():
    role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = parse_pagination()
    from flask import request
    status = request.args.get("status")
    items = list(db.productions.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_array([public(p) for p in page], limit, offset, total)


@bp.route("/productions/<pid>/advance", methods=["POST"])
def advance_production(pid):
    role = authenticate()
    authorize(role, {"LineProducer"})
    with db.lock:
        prod = db.productions.get(pid)
        if not prod:
            raise err("ERR_NOT_FOUND", "Production not found.")
        status = prod["status"]
        if status == "DRAFT":
            # require at least one budget line
            if not any(bl["production_id"] == pid for bl in db.budget_lines.values()):
                raise err("ERR_INVALID_STATE",
                          "Cannot advance: at least one budget line required.")
            prod["status"] = "PRE_PRODUCTION"
        elif status == "PRE_PRODUCTION":
            if not any(d["production_id"] == pid for d in db.shooting_days.values()):
                raise err("ERR_INVALID_STATE",
                          "Cannot advance: at least one shooting day required.")
            prod["status"] = "ACTIVE"
        elif status == "ACTIVE":
            blocking = {"PLANNED", "CALLED", "IN_PROGRESS"}
            if any(d["production_id"] == pid and d["status"] in blocking
                   for d in db.shooting_days.values()):
                raise err("ERR_INVALID_STATE",
                          "Cannot wrap: some shooting days are still open.")
            prod["status"] = "WRAPPED"
        else:
            raise err("ERR_INVALID_STATE", f"Cannot advance from {status}.")
        touch(prod)
        return success_object(public(prod))


@bp.route("/productions/<pid>/close", methods=["POST"])
def close_production(pid):
    role = authenticate()
    authorize(role, {"LineProducer"})
    with db.lock:
        prod = db.productions.get(pid)
        if not prod:
            raise err("ERR_NOT_FOUND", "Production not found.")
        if prod["status"] != "WRAPPED":
            raise err("ERR_INVALID_STATE", "Production must be WRAPPED to close.")
        for a in assignments_for_production(pid):
            if a["payment_status"] in ("UNPAID", "APPROVED"):
                raise err("ERR_INVALID_STATE",
                          "Cannot close: an assignment is still financially open.")
        prod["status"] = "CLOSED"
        touch(prod)
        return success_object(public(prod))


@bp.route("/productions/<pid>/budget-summary", methods=["GET"])
def budget_summary(pid):
    role = authenticate()
    authorize(role, {"LineProducer", "PayrollCoordinator", "UnionRep"})
    prod = db.productions.get(pid)
    if not prod:
        raise err("ERR_NOT_FOUND", "Production not found.")
    lines = [bl for bl in db.budget_lines.values() if bl["production_id"] == pid]
    total_estimated = sum(bl["estimated_cents"] for bl in lines)
    total_actual = sum(bl["actual_cents"] for bl in lines)
    summary = {
        "total_estimated_cents": total_estimated,
        "total_actual_cents": total_actual,
        "total_variance_cents": total_estimated - total_actual,
        "over_budget": total_actual > total_estimated,
        "residual_reserve_cents": prod["residual_reserve_cents"],
    }
    return success_object(summary)


# --- BudgetLine -------------------------------------------------------------
def _new_budget_line(production_id, category, estimated_cents):
    ts = now_iso()
    return {
        "id": new_id(),
        "production_id": production_id,
        "category": category,
        "estimated_cents": estimated_cents,
        "actual_cents": 0,
        "variance_cents": estimated_cents,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


@bp.route("/budget-lines", methods=["POST"])
def create_budget_line():
    role = authenticate()
    authorize(role, {"LineProducer"})
    body = get_json_body()
    production_id = require_string(body, "production_id")
    if production_id not in db.productions:
        raise err("ERR_NOT_FOUND", "Production not found.")
    category = require_enum(body, "category", BUDGET_CATEGORIES)
    estimated = require_int(body, "estimated_cents", minimum=0)
    with db.lock:
        bl = _new_budget_line(production_id, category, estimated)
        db.budget_lines[bl["id"]] = bl
        return success_object(public(bl), status=201)


@bp.route("/budget-lines/<bid>", methods=["GET"])
def get_budget_line(bid):
    role = authenticate()
    authorize(role, {"LineProducer", "PayrollCoordinator", "UnionRep"})
    bl = db.budget_lines.get(bid)
    if not bl:
        raise err("ERR_NOT_FOUND", "Budget line not found.")
    return success_object(public(bl))


@bp.route("/budget-lines", methods=["GET"])
def list_budget_lines():
    role = authenticate()
    authorize(role, {"LineProducer", "PayrollCoordinator", "UnionRep"})
    limit, offset = parse_pagination()
    from flask import request
    production_id = request.args.get("production_id")
    items = list(db.budget_lines.values())
    if production_id is not None:
        items = [bl for bl in items if bl["production_id"] == production_id]
    page, total = paginate(items, limit, offset)
    return success_array([public(bl) for bl in page], limit, offset, total)


@bp.route("/budget-lines/<bid>/post-actual", methods=["POST"])
def post_actual(bid):
    role = authenticate()
    authorize(role, {"LineProducer"})
    bl = db.budget_lines.get(bid)
    if not bl:
        raise err("ERR_NOT_FOUND", "Budget line not found.")
    body = get_json_body()
    amount = require_int(body, "amount_cents", minimum=0)
    # OCC field is required (priority 6). Missing -> treat as invalid request.
    if "expected_production_version" not in body or body["expected_production_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_production_version.")
    expected = require_int(body, "expected_production_version")
    with db.lock:
        prod = db.productions.get(bl["production_id"])
        if not prod:
            raise err("ERR_NOT_FOUND", "Production not found.")
        if expected != prod["version"]:
            raise err("ERR_STALE_VERSION", "Production version is stale.")
        bl["actual_cents"] += amount
        recompute_variance(bl)
        touch(bl)
        touch(prod)
        return success_object(public(bl))
