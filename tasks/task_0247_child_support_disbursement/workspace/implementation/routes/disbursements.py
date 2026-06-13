"""Disbursement routes: create (distribution split), send, return, reads."""

from flask import Blueprint, request

import errors
import lookup
from common import (
    stamp_create, touch, get_body, as_enum, fk,
    pagination, paginate, sort_by_created,
)
from db import store
from middleware import require_roles
from response import object_response, array_response
from services import serialize, ledger, calc

bp = Blueprint("disbursements", __name__)

METHODS = {"EFT", "CHECK", "DEBIT_CARD"}


@bp.route("/disbursements", methods=["POST"])
@require_roles("FinanceOfficer")
def create_disbursement(auth):
    body = get_body()
    # Existence (priority 3), left-to-right: order, payee, allocation.
    order = lookup.support_order(fk(body, "support_order_id"))
    cp = lookup.custodial_party(fk(body, "custodial_party_id"))
    alloc = lookup.allocation(fk(body, "allocation_id"))
    # FK compatibility (priority 4): allocation must belong to the named order.
    if alloc["support_order_id"] != order["id"]:
        raise errors.fk_mismatch()
    # Structural validity (priority 5).
    method = as_enum(body, "method", METHODS, required=False, default="EFT")
    # distribution_split keyed on the order's rule.
    family_amount, state_retained = calc.distribution_split(order, alloc)
    # ERR_OVER_DISBURSEMENT (priority 17): the family+state total disbursed from
    # this allocation slice may not exceed the slice's distributable total.
    already = 0
    for d in store.disbursements.values():
        if d["allocation_id"] == alloc["id"] and d["status"] in ("PENDING", "SENT"):
            already += d["family_amount_cents"] + d["state_retained_cents"]
    if already + family_amount + state_retained > alloc["total_applied_cents"]:
        raise errors.over_disbursement()
    rec = stamp_create({
        "support_order_id": order["id"],
        "custodial_party_id": cp["id"],
        "allocation_id": alloc["id"],
        "method": method,
        "family_amount_cents": family_amount,
        "state_retained_cents": state_retained,
        "status": "PENDING",
    })
    store.disbursements[rec["id"]] = rec
    return object_response(serialize.disbursement(rec), 201)


@bp.route("/disbursements/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "CustodialParty")
def get_disbursement(auth, rid):
    rec = lookup.disbursement(rid)
    lookup.require(lookup.owns_disbursement(auth, rec))
    return object_response(serialize.disbursement(rec), 200)


@bp.route("/disbursements", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer", "CustodialParty")
def list_disbursements(auth):
    so_id = request.args.get("support_order_id")
    cp_id = request.args.get("custodial_party_id")
    alloc_id = request.args.get("allocation_id")
    items = list(store.disbursements.values())
    if so_id is not None:
        items = [d for d in items if d["support_order_id"] == so_id]
    if cp_id is not None:
        items = [d for d in items if d["custodial_party_id"] == cp_id]
    if alloc_id is not None:
        items = [d for d in items if d["allocation_id"] == alloc_id]
    if auth.role == "CustodialParty":
        items = [d for d in items if d["custodial_party_id"] == auth.user_id]
    items = sort_by_created(items)
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return array_response([serialize.disbursement(d) for d in page],
                          limit, offset, total, 200)


@bp.route("/disbursements/<rid>/send", methods=["POST"])
@require_roles("FinanceOfficer")
def send_disbursement(auth, rid):
    rec = lookup.disbursement(rid)
    # State (priority 7).
    if rec["status"] != "PENDING":
        raise errors.invalid_state()
    # ERR_PAYEE_ON_HOLD (priority 10).
    cp = store.custodial_parties.get(rec["custodial_party_id"])
    if cp is None or cp["payee_status"] != "ACTIVE":
        raise errors.payee_on_hold()
    rec["status"] = "SENT"
    # Post a DISBURSEMENT row (CURRENT_SUPPORT bucket, -family_amount): audit row
    # for cash leaving to the family. Flagged disbursement_lifecycle so it does
    # NOT move the owed balance. net_disbursed_to_family_cents is derived from
    # SENT/RETURNED disbursement status, not from this row.
    ledger.post_entry(rec["support_order_id"], "DISBURSEMENT", "CURRENT_SUPPORT",
                      -rec["family_amount_cents"], rec["id"],
                      disbursement_lifecycle=True)
    touch(rec)
    return object_response(serialize.disbursement(rec), 200)


@bp.route("/disbursements/<rid>/return", methods=["POST"])
@require_roles("FinanceOfficer")
def return_disbursement(auth, rid):
    rec = lookup.disbursement(rid)
    if rec["status"] != "SENT":
        raise errors.invalid_state()
    rec["status"] = "RETURNED"
    # Compensating ADJUSTMENT (CURRENT_SUPPORT, +family_amount) that exactly
    # negates the send's DISBURSEMENT row. Flagged disbursement_lifecycle so the
    # owed buckets stay unaffected by both the send and the return (PRD 3.7).
    ledger.post_entry(rec["support_order_id"], "ADJUSTMENT", "CURRENT_SUPPORT",
                      rec["family_amount_cents"], rec["id"],
                      disbursement_lifecycle=True)
    touch(rec)
    return object_response(serialize.disbursement(rec), 200)
