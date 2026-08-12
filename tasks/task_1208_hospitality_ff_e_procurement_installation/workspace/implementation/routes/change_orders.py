"""ChangeOrder endpoints (PRD 3.9)."""
from flask import Blueprint

import db
import services as svc
from errors import ApiError
from middleware import auth, require_role, body, req_str
from response import ok
from routes.projects import ANY

bp = Blueprint("change_orders", __name__)
S = db.STORE


def _parse_adjustments(b):
    adjustments = b.get("adjustments")
    if not isinstance(adjustments, list):
        raise ApiError("ERR_INVALID_REQUEST", "adjustments must be an array")
    parsed = []
    for entry in adjustments:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST",
                           "each adjustments entry must be an object")
        bl_id = entry.get("budget_line_id")
        if not isinstance(bl_id, str):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Missing or invalid field: budget_line_id")
        delta = entry.get("delta_cents")
        if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0:
            raise ApiError("ERR_INVALID_REQUEST", "delta_cents must be a non-zero integer")
        parsed.append({"budget_line_id": bl_id, "delta_cents": delta})
    return parsed


@bp.route("/api/change-orders", methods=["POST"])
def create_change_order():
    user_id, role = auth()
    require_role(role, ("PurchasingAgent", "OwnerRep"))
    b = body()
    project_id = b.get("project_id")
    if not isinstance(project_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: project_id")
    title = req_str(b, "title")
    adjustments = _parse_adjustments(b)
    svc.get_project(project_id)
    lines = [svc.get_budget_line(a["budget_line_id"]) for a in adjustments]
    for bl in lines:
        if bl["project_id"] != project_id:
            raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                           "Adjustments must reference budget lines of the "
                           "change order's project")
    co = db.create("change_orders", {
        "project_id": project_id,
        "title": title,
        "adjustments": adjustments,
        "proposer_user_id": user_id,
        "fee_cents": None,
        "status": "PROPOSED",
    })
    return ok(db.pub(co), 201)


@bp.route("/api/change-orders/<changeOrderId>", methods=["GET"])
def get_change_order(changeOrderId):
    auth_user, role = auth()
    require_role(role, ANY)
    return ok(db.pub(svc.get_change_order(changeOrderId)))


def _check_self_decision(co, user_id):
    """Segregation of duties (stage 2): the proposer may not decide."""
    if user_id == co["proposer_user_id"]:
        raise ApiError("ERR_CHANGE_ORDER_SELF_APPROVAL",
                       "The proposer may not apply or reject their own change order")


@bp.route("/api/change-orders/<changeOrderId>/apply", methods=["POST"])
def apply_change_order(changeOrderId):
    user_id, role = auth()
    require_role(role, ("OwnerRep",))
    co = svc.get_change_order(changeOrderId)
    _check_self_decision(co, user_id)
    b = body()
    expected = b.get("expected_project_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_project_version is required")
    if co["status"] != "PROPOSED":
        raise ApiError("ERR_CO_NOT_PROPOSED",
                       "Change-order apply requires status PROPOSED")
    project = svc.get_project(co["project_id"])
    # stage 6 OCC
    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION",
                       "expected_project_version does not match the project's "
                       "current version")
    # stage 11 fiscal checks, in pinned order (funding, then obligations floor)
    svc.recompute_project_financials(project["id"])
    pos = sum(a["delta_cents"] for a in co["adjustments"] if a["delta_cents"] > 0)
    neg = sum(-a["delta_cents"] for a in co["adjustments"] if a["delta_cents"] < 0)
    fee = svc.compute_draw_fee(project, pos)
    if project["unallocated_contingency_cents"] + neg < pos + fee:
        raise ApiError("ERR_CHANGE_ORDER_UNFUNDED",
                       "unallocated_contingency_cents + NEG < POS + fee_cents")
    adjusted = [svc.get_budget_line(a["budget_line_id"]) for a in co["adjustments"]]
    for a, bl in zip(co["adjustments"], adjusted):
        if bl["budgeted_cents"] + a["delta_cents"] < bl["committed_cents"] + bl["actual_cents"]:
            raise ApiError("ERR_BUDGET_BELOW_OBLIGATIONS",
                           "A negative adjustment would drop a budget line below "
                           "its committed + actual obligations")
    # Link 1: apply budget deltas and move contingency
    for a, bl in zip(co["adjustments"], adjusted):
        bl["budgeted_cents"] += a["delta_cents"]
        db.touch(bl)
    project["unallocated_contingency_cents"] += neg - pos - fee
    project["sunk_fees_cents"] += fee
    co["fee_cents"] = fee
    # Link 2 + 3: variances on mutated lines, project rollups and posture
    svc.recompute_project_financials(project["id"])
    db.touch(project)  # side effect: project.version += 1
    co["status"] = "APPLIED"
    db.touch(co)
    return ok(db.pub(co))


@bp.route("/api/change-orders/<changeOrderId>/reject", methods=["POST"])
def reject_change_order(changeOrderId):
    user_id, role = auth()
    require_role(role, ("OwnerRep",))
    co = svc.get_change_order(changeOrderId)
    _check_self_decision(co, user_id)
    if co["status"] != "PROPOSED":
        raise ApiError("ERR_CO_NOT_PROPOSED",
                       "Change-order reject requires status PROPOSED")
    co["status"] = "REJECTED"
    db.touch(co)
    return ok(db.pub(co))
