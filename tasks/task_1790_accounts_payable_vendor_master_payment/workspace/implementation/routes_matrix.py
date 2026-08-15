"""Approval matrix rules (Controller-administered)."""
from flask import Blueprint

import db
import services as svc
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_RULE_RANGE_OVERLAP,
    raise_err,
)
from middleware import require_auth, require_role, get_body, req_str, req_int, get_or_404
from response import ok

bp = Blueprint("matrix", __name__)


@bp.route("/approval-matrix-rules", methods=["POST"])
def create_rule():
    ctx = require_auth()
    require_role(ctx, ["Controller"])
    body = get_body()
    cost_center = req_str(body, "cost_center")
    min_amount = req_int(body, "min_amount_cents")
    if min_amount < 0:
        raise_err(ERR_INVALID_REQUEST, "min_amount_cents must be non-negative.")
    max_amount = body.get("max_amount_cents")
    if max_amount is not None:
        if not isinstance(max_amount, int) or isinstance(max_amount, bool):
            raise_err(ERR_INVALID_REQUEST, "max_amount_cents must be an integer.")
    tier = req_int(body, "tier")
    if tier not in (1, 2, 3):
        raise_err(ERR_INVALID_REQUEST, "tier must be one of 1, 2, 3.")

    # half-open [min, max) overlap gate among ACTIVE rules sharing the cost_center;
    # adjacency (new.min == existing.max) is allowed
    new_hi = max_amount if max_amount is not None else float("inf")
    for rule in db.approval_matrix_rules.values():
        if rule["status"] != "ACTIVE" or rule["cost_center"] != cost_center:
            continue
        ex_hi = rule["max_amount_cents"] if rule["max_amount_cents"] is not None else float("inf")
        if min_amount < ex_hi and rule["min_amount_cents"] < new_hi:
            raise_err(ERR_RULE_RANGE_OVERLAP,
                      "Rule bracket overlaps an existing ACTIVE rule for cost_center '%s'." % cost_center)

    rule = db.stamp_new({
        "id": db.new_id(),
        "cost_center": cost_center,
        "min_amount_cents": min_amount,
        "max_amount_cents": max_amount,
        "tier": tier,
        "status": "ACTIVE",
    })
    db.approval_matrix_rules[rule["id"]] = rule
    svc.audit("ApprovalMatrixRule", rule["id"], "CREATE", ctx)
    return ok(rule, status=201)


@bp.route("/approval-matrix-rules/<rule_id>/retire", methods=["POST"])
def retire_rule(rule_id):
    ctx = require_auth()
    require_role(ctx, ["Controller"])
    rule = get_or_404(db.approval_matrix_rules, rule_id, "ApprovalMatrixRule")
    if rule["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Approval matrix rule in status %s cannot be retired." % rule["status"])
    rule["status"] = "RETIRED"
    db.touch(rule)
    svc.audit("ApprovalMatrixRule", rule["id"], "RETIRE", ctx)
    return ok(rule)
