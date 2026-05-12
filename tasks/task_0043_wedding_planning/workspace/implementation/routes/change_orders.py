"""ChangeOrder routes."""
from flask import Blueprint, request, g

import db
from errors import (
    raise_error,
    ERR_CHANGE_ORDER_NOT_PENDING,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_CONTRACT_NOT_BOUND,
    ERR_BUDGET_OVERCOMMITTED,
)
from middleware import require_roles, check_planner_owns_project
from response import success, list_response, parse_pagination
from services.lookup import (
    get_project,
    get_contract,
    get_change_order,
    assert_project_not_terminal,
)
from services.budget import recompute_project_ledger
from services.audit import append_audit


bp = Blueprint("change_orders", __name__)


@bp.post("/wedding-projects/<project_id>/contracts/<contract_id>/change-orders")
def create_change_order(project_id, contract_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    c = get_contract(project_id, contract_id)
    body = request.get_json(silent=True) or {}
    co = {
        "contract_id": contract_id,
        "delta_amount_cents": int(body.get("delta_amount_cents", 0)),
        "reason": body.get("reason"),
        "requested_by_user_id": g.user_id,
        "approved_by_user_id": None,
        "status": "PENDING",
    }
    db.add_common_create(co)
    db.change_orders[co["id"]] = co
    return success(co, status=201)


@bp.get("/wedding-projects/<project_id>/contracts/<contract_id>/change-orders")
def list_change_orders(project_id, contract_id):
    require_roles("Planner", "Auditor")
    p = get_project(project_id)
    if g.user_role == "Planner":
        check_planner_owns_project(p)
    get_contract(project_id, contract_id)
    limit, offset = parse_pagination(request.args)
    status_q = request.args.get("status")
    items = [co for co in db.change_orders.values() if co["contract_id"] == contract_id]
    if status_q:
        items = [co for co in items if co["status"] == status_q]
    items.sort(key=lambda co: co["created_at"])
    return list_response(items, limit, offset)


@bp.post("/wedding-projects/<project_id>/contracts/<contract_id>/change-orders/<co_id>/approve")
def approve_change_order(project_id, contract_id, co_id):
    # Per PRD §3.4 the approver is "a second planner" whose X-User-ID differs from
    # the requester. Two distinct planner X-User-IDs must be able to act on the
    # same project, so we do NOT enforce strict ownership on this endpoint —
    # only the role and segregation checks.
    require_roles("Planner")
    p = get_project(project_id)
    assert_project_not_terminal(p)
    c = get_contract(project_id, contract_id)
    co = get_change_order(contract_id, co_id)
    # Priority order:
    # 1. ChangeOrder must be PENDING
    if co["status"] != "PENDING":
        raise_error(ERR_CHANGE_ORDER_NOT_PENDING, "ChangeOrder must be PENDING")
    # 2. Segregation: actor != requester
    if g.user_id == co["requested_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "Approver must differ from requester")
    # 3. Contract must be SIGNED or ACCEPTED
    if c["contract_status"] not in ("SIGNED", "ACCEPTED"):
        raise_error(ERR_CONTRACT_NOT_BOUND, "Contract must be SIGNED or ACCEPTED")
    # 4. After delta, budget_balance >= 0
    if int(p["budget_balance_cents"]) - int(co["delta_amount_cents"]) < 0:
        raise_error(ERR_BUDGET_OVERCOMMITTED, "Approval would exceed budget")
    # Apply
    co["status"] = "APPROVED"
    co["approved_by_user_id"] = g.user_id
    db.bump(co)
    # Audit append BEFORE recomputing settlement so settlement_calc can find the audit entry
    append_audit(
        project_id=project_id,
        subject_type="CHANGE_ORDER",
        subject_id=co["id"],
        event_kind="CHANGE_ORDER_APPROVED",
        payload={
            "delta_amount_cents": co["delta_amount_cents"],
            "contract_id": contract_id,
        },
    )
    # Recompute project ledger
    recompute_project_ledger(p)
    # Recompute settlement preview if a DRAFT settlement exists
    for s in db.settlements.values():
        if s["contract_id"] == contract_id and s["status"] == "DRAFT":
            db.bump(s)
    return success(co)


@bp.post("/wedding-projects/<project_id>/contracts/<contract_id>/change-orders/<co_id>/reject")
def reject_change_order(project_id, contract_id, co_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    get_contract(project_id, contract_id)
    co = get_change_order(contract_id, co_id)
    if co["status"] != "PENDING":
        raise_error(ERR_CHANGE_ORDER_NOT_PENDING, "ChangeOrder must be PENDING")
    co["status"] = "REJECTED"
    db.bump(co)
    return success(co)
