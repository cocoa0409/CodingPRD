"""Modification routes: open, submit, decide, revise, apply (OCC), reads."""

from flask import Blueprint, request

import errors
import lookup
from common import (
    stamp_create, touch, get_body, as_int, as_str, as_enum, fk,
    pagination, paginate, sort_by_created,
)
from db import store, parse_iso
from middleware import require_roles
from response import object_response, array_response
from services import serialize

bp = Blueprint("modifications", __name__)

DECISIONS = {"APPROVE", "REJECT"}


@bp.route("/modifications", methods=["POST"])
@require_roles("CaseWorker")
def create_modification(auth):
    body = get_body()
    # Existence (priority 3).
    order = lookup.support_order(fk(body, "support_order_id"))
    # Structural validity (priority 5).
    proposed = as_int(body, "proposed_current_support_cents")
    start_raw = as_str(body, "coverage_start_at")
    end_raw = as_str(body, "coverage_end_at")
    start = parse_iso(start_raw)
    end = parse_iso(end_raw)
    if start is None or end is None:
        raise errors.invalid_request("coverage_start_at / coverage_end_at must be ISO 8601")
    # ERR_MODIFICATION_PERIOD_OVERLAP (priority 19): closed [start, end] vs any
    # non-REJECTED modification on the same order; boundary instants DO collide.
    for other in store.modifications.values():
        if other["support_order_id"] != order["id"]:
            continue
        if other["status"] == "REJECTED":
            continue
        o_start = parse_iso(other["coverage_start_at"])
        o_end = parse_iso(other["coverage_end_at"])
        # Closed-interval overlap: start <= o_end AND o_start <= end.
        if start <= o_end and o_start <= end:
            raise errors.modification_period_overlap()
    rec = stamp_create({
        "support_order_id": order["id"],
        "proposed_current_support_cents": proposed,
        "coverage_start_at": start_raw,
        "coverage_end_at": end_raw,
        "status": "DRAFT",
    })
    store.modifications[rec["id"]] = rec
    return object_response(serialize.modification(rec), 201)


@bp.route("/modifications/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "Supervisor")
def get_modification(auth, rid):
    rec = lookup.modification(rid)
    return object_response(serialize.modification(rec), 200)


@bp.route("/modifications", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "Supervisor")
def list_modifications(auth):
    so_id = request.args.get("support_order_id")
    items = list(store.modifications.values())
    if so_id is not None:
        items = [m for m in items if m["support_order_id"] == so_id]
    items = sort_by_created(items)
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return array_response([serialize.modification(m) for m in page],
                          limit, offset, total, 200)


@bp.route("/modifications/<rid>/submit", methods=["POST"])
@require_roles("CaseWorker")
def submit_modification(auth, rid):
    rec = lookup.modification(rid)
    if rec["status"] != "DRAFT":
        raise errors.invalid_state()
    # ERR_INVALID_AMOUNT (priority 13): proposed amount must be > 0.
    if rec["proposed_current_support_cents"] <= 0:
        raise errors.invalid_amount()
    rec["status"] = "SUBMITTED"
    touch(rec)
    return object_response(serialize.modification(rec), 200)


@bp.route("/modifications/<rid>/decide", methods=["POST"])
@require_roles("Supervisor")
def decide_modification(auth, rid):
    rec = lookup.modification(rid)
    body = get_body()
    decision = as_enum(body, "decision", DECISIONS)
    # State (priority 7).
    if rec["status"] != "SUBMITTED":
        raise errors.invalid_state()
    if decision == "APPROVE":
        # ERR_ORDER_NOT_ACTIVE (priority 16).
        order = store.support_orders.get(rec["support_order_id"])
        if order is None or order["obligation_status"] != "ACTIVE":
            raise errors.order_not_active()
        rec["status"] = "APPROVED"
    else:  # REJECT
        rec["status"] = "REJECTED"
    touch(rec)
    return object_response(serialize.modification(rec), 200)


@bp.route("/modifications/<rid>/revise", methods=["POST"])
@require_roles("CaseWorker")
def revise_modification(auth, rid):
    rec = lookup.modification(rid)
    if rec["status"] != "REJECTED":
        raise errors.invalid_state()
    rec["status"] = "DRAFT"
    touch(rec)
    return object_response(serialize.modification(rec), 200)


@bp.route("/modifications/<rid>/apply", methods=["POST"])
@require_roles("CaseWorker")
def apply_modification(auth, rid):
    rec = lookup.modification(rid)
    body = get_body()
    # Structural validity (priority 5): OCC field is mandatory for this endpoint
    # (PRD 2.8) and must be a non-negative integer.
    expected = as_int(body, "expected_support_order_version")
    # State (priority 7): modification must be APPROVED.
    if rec["status"] != "APPROVED":
        raise errors.invalid_state()
    order = store.support_orders.get(rec["support_order_id"])
    if order is None:
        raise errors.not_found()
    # OCC (priority 8) before order-state business rule.
    if expected != order["version"]:
        raise errors.stale_version()
    # ERR_ORDER_NOT_ACTIVE (priority 16).
    if order["obligation_status"] != "ACTIVE":
        raise errors.order_not_active()
    # Apply.
    rec["status"] = "APPLIED"
    order["current_support_cents"] = rec["proposed_current_support_cents"]
    order["obligation_status"] = "MODIFIED"
    touch(order)  # bumps version; total_current_support recomputed at read time
    touch(rec)
    return object_response(serialize.modification(rec), 200)
