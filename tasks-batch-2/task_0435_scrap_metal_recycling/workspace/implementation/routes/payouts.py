"""Payout routes (PRD §3.5): create, settle (1099 ledger), void."""
from flask import Blueprint

import errors
import response
import serializers
from db import db, stamp_create, touch
from helpers import (as_enum, as_string, get_json_body, parse_pagination,
                     paginate, query_arg, require_fields)
from middleware import authenticate, require_roles

bp = Blueprint("payouts", __name__)

METHODS = {"CASH", "CHECK"}
PAYOUT_STATUSES = {"PENDING", "SETTLED", "VOID"}
READ_ROLES = {"PayoutClerk", "ComplianceOfficer", "SettlementAccountant", "YardManager"}

TIN_1099_THRESHOLD_CENTS = 60000


@bp.route("/yard/payouts", methods=["POST"])
def create_payout():
    uid, role = authenticate()
    require_roles(role, {"PayoutClerk"})
    body = get_json_body()
    require_fields(body, ["ticket_id", "method"])
    ticket_id = as_string(body["ticket_id"], "ticket_id")
    method = as_enum(body["method"], "method", METHODS)
    # Existence (priority 3).
    ticket = db.tickets.get(ticket_id)
    if ticket is None:
        raise errors.not_found("Ticket not found.")
    # State (priority 4): ticket must be RELEASED.
    if ticket["status"] != "RELEASED":
        raise errors.invalid_state("Ticket is not RELEASED.")
    # Segregation of duties (priority 5): acting user != theft_hold_released_by.
    if ticket.get("theft_hold_released_by") is not None and \
            uid == ticket["theft_hold_released_by"]:
        raise errors.segregation_of_duties()
    # Duplicate payout (one per ticket).
    for p in db.payouts.values():
        if p["ticket_id"] == ticket_id:
            raise errors.duplicate_payout()

    record = {
        "ticket_id": ticket_id,
        "seller_id": ticket["seller_id"],
        "method": method,
        "amount_cents": ticket["gross_valuation_cents"],
        "form_1099_issued": False,
        "status": "PENDING",
    }
    stamp_create(record)
    db.payouts[record["id"]] = record
    return response.success(serializers.payout(record), 201)


@bp.route("/yard/payouts/<pid>", methods=["GET"])
def get_payout(pid):
    authenticate()
    record = db.payouts.get(pid)
    if not record:
        raise errors.not_found("Payout not found.")
    return response.success(serializers.payout(record), 200)


@bp.route("/yard/payouts", methods=["GET"])
def list_payouts():
    authenticate()
    limit, offset = parse_pagination()
    ticket_id = query_arg("ticket_id")
    seller_id = query_arg("seller_id")
    method = query_arg("method")
    status = query_arg("status")
    if method is not None and method not in METHODS:
        raise errors.invalid_request("method filter is invalid.")
    if status is not None and status not in PAYOUT_STATUSES:
        raise errors.invalid_request("status filter is invalid.")
    rows = list(db.payouts.values())
    if ticket_id is not None:
        rows = [r for r in rows if r["ticket_id"] == ticket_id]
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if method is not None:
        rows = [r for r in rows if r["method"] == method]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.payout(r) for r in page], limit, offset, total)


@bp.route("/yard/payouts/<pid>/settle", methods=["POST"])
def settle_payout(pid):
    _uid, role = authenticate()
    require_roles(role, {"PayoutClerk"})
    payout = db.payouts.get(pid)
    if not payout:
        raise errors.not_found("Payout not found.")
    # State (priority 4).
    if payout["status"] != "PENDING":
        raise errors.invalid_state("Payout is not PENDING.")
    seller = db.sellers.get(payout["seller_id"])
    # Seller-frozen (priority 6): seller must be ACTIVE.
    if seller is None or seller["status"] != "ACTIVE":
        raise errors.seller_frozen("Seller is not ACTIVE.")

    method = payout["method"]
    if method == "CASH":
        prospective = seller["ytd_cash_paid_cents"] + payout["amount_cents"]
        crosses = prospective >= TIN_1099_THRESHOLD_CENTS
        # 1099 TIN gate (priority 12): enforced BEFORE the ledger moves.
        if crosses and not seller.get("tin"):
            raise errors.tin_required_for_1099()
        # Ledger increment.
        seller["ytd_cash_paid_cents"] = prospective
        if crosses:
            seller["requires_1099"] = True
        payout["form_1099_issued"] = bool(crosses and seller.get("tin"))
        touch(seller)
    else:  # CHECK
        payout["form_1099_issued"] = False

    payout["status"] = "SETTLED"
    touch(payout)
    # Cross-entity: ticket RELEASED -> PAID.
    ticket = db.tickets.get(payout["ticket_id"])
    if ticket is not None:
        ticket["status"] = "PAID"
        touch(ticket)
    return response.success(serializers.payout(payout), 200)


@bp.route("/yard/payouts/<pid>/void", methods=["POST"])
def void_payout(pid):
    _uid, role = authenticate()
    require_roles(role, {"PayoutClerk"})
    payout = db.payouts.get(pid)
    if not payout:
        raise errors.not_found("Payout not found.")
    if payout["status"] != "PENDING":
        raise errors.invalid_state("Payout is not PENDING.")
    payout["status"] = "VOID"
    touch(payout)
    return response.success(serializers.payout(payout), 200)
