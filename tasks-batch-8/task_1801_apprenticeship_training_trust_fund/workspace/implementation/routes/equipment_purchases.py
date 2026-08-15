"""EquipmentPurchase endpoints: request, get, list, approve, deny, cancel, mark-purchased."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success_object, success_list
from services import ledger

bp = Blueprint("equipment_purchases", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")


def purchase_view(p):
    return {
        "id": p["id"],
        "allocation_id": p["allocation_id"],
        "description": p["description"],
        "amount_cents": p["amount_cents"],
        "requested_by_user_id": p["requested_by_user_id"],
        "decided_by_user_id": p["decided_by_user_id"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def get_purchase_or_404(pid):
    p = db.equipment_purchases.get(pid)
    if p is None:
        raise errors.err_purchase_not_found()
    return p


@bp.route("/equipment-purchases", methods=["POST"])
def create_purchase():
    user_id, _ = mw.require_roles("TrustAdmin")
    body = mw.get_body()
    mw.require_fields(body, ["allocation_id", "description", "amount_cents"])
    if not mw.is_str(body["allocation_id"]):
        raise errors.err_invalid_request("allocation_id must be a string")
    alloc = db.funding_allocations.get(body["allocation_id"])
    if alloc is None:
        raise errors.err_allocation_not_found()
    if not mw.is_str(body["description"]):
        raise errors.err_invalid_request("description must be a string")
    amount = body["amount_cents"]
    if not mw.is_int(amount) or amount < 1:
        raise errors.err_invalid_request("amount_cents must be an integer >= 1")
    if alloc["status"] != "ACTIVE":
        raise errors.err_allocation_not_active()

    pid = db.new_id()
    now = db.now_iso()
    p = {
        "id": pid,
        "allocation_id": alloc["id"],
        "description": body["description"],
        "amount_cents": amount,
        "requested_by_user_id": user_id,
        "decided_by_user_id": None,
        "status": "REQUESTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.equipment_purchases[pid] = p
    return success_object(purchase_view(p), 201)


@bp.route("/equipment-purchases/<pid>", methods=["GET"])
def get_purchase(pid):
    mw.require_roles(*ALL_ROLES)
    return success_object(purchase_view(get_purchase_or_404(pid)), 200)


@bp.route("/equipment-purchases", methods=["GET"])
def list_purchases():
    mw.require_roles(*ALL_ROLES)
    limit, offset = mw.parse_pagination(request.args)
    aid = request.args.get("allocation_id")
    status = request.args.get("status")
    items = list(db.equipment_purchases.values())
    if aid is not None:
        items = [p for p in items if p["allocation_id"] == aid]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (db._parse_iso(p["created_at"]), p["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([purchase_view(p) for p in page], limit, offset, total)


@bp.route("/equipment-purchases/<pid>/approve", methods=["POST"])
def approve_purchase(pid):
    user_id, _ = mw.require_roles("CommitteeMember")
    p = get_purchase_or_404(pid)
    if p["status"] != "REQUESTED":
        raise errors.err_purchase_not_requested()
    alloc = db.funding_allocations[p["allocation_id"]]
    fund = db.trust_funds[alloc["trust_fund_id"]]
    ledger.recompute_fund_posture(fund)
    # Compliance tier: posture, then SoD
    if fund["posture"] != "OPERATING":
        raise errors.err_fund_on_compliance_hold()
    if user_id == p["requested_by_user_id"]:
        raise errors.err_self_approval()
    # Allocation still ACTIVE at decision time
    if alloc["status"] != "ACTIVE":
        raise errors.err_invalid_state("allocation is not ACTIVE at decision time")
    # Fiscal tier
    ledger.recompute_allocation(alloc)
    if p["amount_cents"] > alloc["remaining_cents"]:
        raise errors.err_insufficient_allocation()

    p["status"] = "APPROVED"
    p["decided_by_user_id"] = user_id
    ledger.touch(p)
    ledger.recompute_allocation(alloc)
    return success_object(purchase_view(p), 200)


@bp.route("/equipment-purchases/<pid>/deny", methods=["POST"])
def deny_purchase(pid):
    user_id, _ = mw.require_roles("CommitteeMember")
    p = get_purchase_or_404(pid)
    if p["status"] != "REQUESTED":
        raise errors.err_purchase_not_requested()
    p["status"] = "DENIED"
    p["decided_by_user_id"] = user_id
    ledger.touch(p)
    return success_object(purchase_view(p), 200)


@bp.route("/equipment-purchases/<pid>/cancel", methods=["POST"])
def cancel_purchase(pid):
    mw.require_roles("TrustAdmin")
    p = get_purchase_or_404(pid)
    if p["status"] not in ("REQUESTED", "APPROVED"):
        raise errors.err_invalid_state("cancel requires REQUESTED or APPROVED")
    was_approved = p["status"] == "APPROVED"
    p["status"] = "CANCELLED"
    ledger.touch(p)
    if was_approved:
        alloc = db.funding_allocations[p["allocation_id"]]
        ledger.recompute_allocation(alloc)
    return success_object(purchase_view(p), 200)


@bp.route("/equipment-purchases/<pid>/mark-purchased", methods=["POST"])
def mark_purchased(pid):
    mw.require_roles("TrustAdmin")
    p = get_purchase_or_404(pid)
    if p["status"] != "APPROVED":
        raise errors.err_purchase_not_approved()
    p["status"] = "PURCHASED"
    ledger.touch(p)
    alloc = db.funding_allocations[p["allocation_id"]]
    ledger.recompute_allocation(alloc)
    fund = db.trust_funds[alloc["trust_fund_id"]]
    ledger.recompute_fund(fund, bump_version=True)
    return success_object(purchase_view(p), 200)
