"""FundingAllocation endpoints: propose, get, list, approve (OCC), reject, close."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success_object, success_list
from services import ledger

bp = Blueprint("funding_allocations", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")
CATEGORIES = ("INSTRUCTION", "EQUIPMENT", "ADMIN")


def allocation_view(a):
    return {
        "id": a["id"],
        "trust_fund_id": a["trust_fund_id"],
        "category": a["category"],
        "fiscal_year": a["fiscal_year"],
        "amount_cents": a["amount_cents"],
        "encumbered_cents": a["encumbered_cents"],
        "spent_cents": a["spent_cents"],
        "remaining_cents": a["remaining_cents"],
        "proposed_by_user_id": a["proposed_by_user_id"],
        "approved_by_user_id": a["approved_by_user_id"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def get_allocation_or_404(aid):
    a = db.funding_allocations.get(aid)
    if a is None:
        raise errors.err_allocation_not_found()
    return a


@bp.route("/funding-allocations", methods=["POST"])
def create_allocation():
    user_id, _ = mw.require_roles("TrustAdmin")
    body = mw.get_body()
    mw.require_fields(body, ["trust_fund_id", "category", "fiscal_year", "amount_cents"])
    if not mw.is_str(body["trust_fund_id"]):
        raise errors.err_invalid_request("trust_fund_id must be a string")
    if body["trust_fund_id"] not in db.trust_funds:
        raise errors.err_fund_not_found()
    if body["category"] not in CATEGORIES:
        raise errors.err_invalid_request("category must be INSTRUCTION, EQUIPMENT, or ADMIN")
    fy = body["fiscal_year"]
    if not mw.is_int(fy):
        raise errors.err_invalid_request("fiscal_year must be an integer")
    amount = body["amount_cents"]
    if not mw.is_int(amount) or amount < 1:
        raise errors.err_invalid_request("amount_cents must be an integer >= 1")

    aid = db.new_id()
    now = db.now_iso()
    a = {
        "id": aid,
        "trust_fund_id": body["trust_fund_id"],
        "category": body["category"],
        "fiscal_year": fy,
        "amount_cents": amount,
        "encumbered_cents": 0,
        "spent_cents": 0,
        "remaining_cents": amount,
        "proposed_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.funding_allocations[aid] = a
    return success_object(allocation_view(a), 201)


@bp.route("/funding-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    mw.require_roles(*ALL_ROLES)
    a = get_allocation_or_404(aid)
    ledger.recompute_allocation(a)
    return success_object(allocation_view(a), 200)


@bp.route("/funding-allocations", methods=["GET"])
def list_allocations():
    mw.require_roles(*ALL_ROLES)
    limit, offset = mw.parse_pagination(request.args)
    tf = request.args.get("trust_fund_id")
    cat = request.args.get("category")
    status = request.args.get("status")
    items = list(db.funding_allocations.values())
    if tf is not None:
        items = [a for a in items if a["trust_fund_id"] == tf]
    if cat is not None:
        items = [a for a in items if a["category"] == cat]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    for a in items:
        ledger.recompute_allocation(a)
    items.sort(key=lambda a: (db._parse_iso(a["created_at"]), a["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([allocation_view(a) for a in page], limit, offset, total)


@bp.route("/funding-allocations/<aid>/approve", methods=["POST"])
def approve_allocation(aid):
    user_id, _ = mw.require_roles("CommitteeMember")
    a = get_allocation_or_404(aid)
    body = mw.get_body()
    mw.require_fields(body, ["expected_trust_fund_version"])
    expected = body["expected_trust_fund_version"]
    if not mw.is_int(expected):
        raise errors.err_invalid_request("expected_trust_fund_version must be an integer")

    # State tier (§2.10): state preconditions incl. OCC version match
    if a["status"] != "PROPOSED":
        raise errors.err_allocation_not_activable()
    fund = db.trust_funds[a["trust_fund_id"]]
    ledger.recompute_fund(fund)
    if expected != fund["version"]:
        raise errors.err_stale_version()
    # Compliance tier: posture, then SoD
    if fund["posture"] != "OPERATING":
        raise errors.err_fund_on_compliance_hold()
    if user_id == a["proposed_by_user_id"]:
        raise errors.err_self_approval()
    # Fiscal tier
    if a["amount_cents"] > fund["available_cents"]:
        raise errors.err_insufficient_fund()

    a["status"] = "ACTIVE"
    a["approved_by_user_id"] = user_id
    ledger.touch(a)
    ledger.recompute_fund(fund, bump_version=True)
    return success_object(allocation_view(a), 200)


@bp.route("/funding-allocations/<aid>/reject", methods=["POST"])
def reject_allocation(aid):
    mw.require_roles("CommitteeMember")
    a = get_allocation_or_404(aid)
    if a["status"] != "PROPOSED":
        raise errors.err_allocation_not_activable()
    a["status"] = "REJECTED"
    ledger.touch(a)
    return success_object(allocation_view(a), 200)


@bp.route("/funding-allocations/<aid>/close", methods=["POST"])
def close_allocation(aid):
    mw.require_roles("TrustAdmin")
    a = get_allocation_or_404(aid)
    if a["status"] != "ACTIVE":
        raise errors.err_invalid_state("close requires an ACTIVE allocation")
    # Refused while any purchase is REQUESTED or APPROVED
    for p in db.equipment_purchases.values():
        if p["allocation_id"] == a["id"] and p["status"] in ("REQUESTED", "APPROVED"):
            raise errors.err_invalid_state(
                "allocation has open purchases and cannot be closed")
    ledger.recompute_allocation(a)
    a["status"] = "CLOSED"
    ledger.touch(a)
    fund = db.trust_funds[a["trust_fund_id"]]
    ledger.recompute_fund(fund, bump_version=True)
    return success_object(allocation_view(a), 200)
