"""EnforcementAction routes: propose (OCC + threshold), certify, withdraw, reads."""

from flask import Blueprint, request

import errors
import lookup
from common import (
    stamp_create, touch, get_body, as_int, as_enum, fk,
    pagination, paginate, sort_by_created,
)
from db import store
from middleware import require_roles
from response import object_response, array_response
from services import serialize, calc

bp = Blueprint("enforcement", __name__)

ACTION_TYPES = {"TAX_INTERCEPT", "LICENSE_SUSPENSION"}


@bp.route("/enforcement-actions", methods=["POST"])
@require_roles("CaseWorker")
def propose_enforcement(auth):
    body = get_body()
    # Existence (priority 3).
    order = lookup.support_order(fk(body, "support_order_id"))
    # Structural validity (priority 5).
    action_type = as_enum(body, "action_type", ACTION_TYPES)
    expected = as_int(body, "expected_support_order_version")
    # OCC (priority 8). The propose transition (NONE -> INTERCEPT_PENDING) has no
    # explicit state precondition in the spec; OCC is the guard against a second
    # proposal, because the first proposal bumps the order's version (PRD 2.8).
    if expected != order["version"]:
        raise errors.stale_version()
    # ERR_BELOW_ENFORCEMENT_THRESHOLD (priority 9): certifiable arrears must be
    # at/above the statutory threshold (boundary inclusive).
    if calc.certifiable_arrears(order["id"]) < calc.ENFORCEMENT_CERT_THRESHOLD_CENTS:
        raise errors.below_threshold()
    rec = stamp_create({
        "support_order_id": order["id"],
        "action_type": action_type,
        "certified_arrears_cents": None,
        "status": "PROPOSED",
    })
    store.enforcement_actions[rec["id"]] = rec
    # Cross-entity: order.enforcement_status NONE -> INTERCEPT_PENDING, version++.
    order["enforcement_status"] = "INTERCEPT_PENDING"
    touch(order)
    return object_response(serialize.enforcement_action(rec), 201)


@bp.route("/enforcement-actions/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer")
def get_enforcement(auth, rid):
    rec = lookup.enforcement_action(rid)
    return object_response(serialize.enforcement_action(rec), 200)


@bp.route("/enforcement-actions", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer")
def list_enforcement(auth):
    so_id = request.args.get("support_order_id")
    items = list(store.enforcement_actions.values())
    if so_id is not None:
        items = [a for a in items if a["support_order_id"] == so_id]
    items = sort_by_created(items)
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return array_response([serialize.enforcement_action(a) for a in page],
                          limit, offset, total, 200)


@bp.route("/enforcement-actions/<rid>/certify", methods=["POST"])
@require_roles("CaseWorker")
def certify_enforcement(auth, rid):
    rec = lookup.enforcement_action(rid)
    order = store.support_orders.get(rec["support_order_id"])
    # State (priority 7): own status PROPOSED and order enforcement INTERCEPT_PENDING.
    if rec["status"] != "PROPOSED":
        raise errors.invalid_state()
    if order is None or order["enforcement_status"] != "INTERCEPT_PENDING":
        raise errors.invalid_state()
    # Snapshot certified arrears = principal + interest at this moment.
    rec["certified_arrears_cents"] = calc.certifiable_arrears(order["id"])
    rec["status"] = "CERTIFIED"
    touch(rec)
    # Cross-entity: INTERCEPT_PENDING -> INTERCEPT_ACTIVE.
    order["enforcement_status"] = "INTERCEPT_ACTIVE"
    touch(order)
    return object_response(serialize.enforcement_action(rec), 200)


@bp.route("/enforcement-actions/<rid>/withdraw", methods=["POST"])
@require_roles("CaseWorker")
def withdraw_enforcement(auth, rid):
    rec = lookup.enforcement_action(rid)
    if rec["status"] != "PROPOSED":
        raise errors.invalid_state()
    rec["status"] = "WITHDRAWN"
    touch(rec)
    # Cross-entity: order enforcement INTERCEPT_PENDING -> NONE.
    order = store.support_orders.get(rec["support_order_id"])
    if order is not None:
        order["enforcement_status"] = "NONE"
        touch(order)
    return object_response(serialize.enforcement_action(rec), 200)
