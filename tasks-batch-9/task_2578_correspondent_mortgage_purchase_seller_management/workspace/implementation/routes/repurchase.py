"""Repurchase demands, appeals, satisfaction and the escrow transfer."""

from flask import Blueprint

import calc
import validate as v
from auth import endpoint, require_scope, scope_seller_filter, user_id
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import (datetime_field, dt_of, loan_advices, loan_demands,
                     loan_transfers, need_demand, need_loan, need_transfer,
                     settled_advice)
from store import (base_record, date_start, db, now, plus_days, public,
                   public_list, touch)

repurchase_bp = Blueprint("repurchase", __name__)

DEMAND_REASONS = ("EPD", "DEFECT", "MISREPRESENTATION")
DEMAND_DECISIONS = ("UPHOLD", "RESCIND")
EVIDENCE_SEVERITIES = ("HIGH", "CRITICAL")
EVIDENCE_STATUSES = ("WAIVED", "EXPIRED")


# --------------------------------------------------------------------------
# issuing a demand
# --------------------------------------------------------------------------

@repurchase_bp.route("/loans/<lid>/repurchase-demands", methods=["POST"])
@endpoint("PurchaseReviewer", "CounterpartyAnalyst")
def create_demand(lid):
    loan = need_loan(lid)
    body = v.body()
    reason = v.req_enum(body, "reason", DEMAND_REASONS)
    letter = v.req_str(body, "demand_letter_reference", min_len=1, max_len=64)
    source_defect_id = v.req_str(body, "source_defect_id", min_len=1,
                                 required=False)
    defect = None
    if source_defect_id is not None:
        if reason == "EPD":
            v.bad("Field 'source_defect_id' must be null for an EPD demand.")
        defect = db.defects.get(source_defect_id)
        if defect is None:
            v.bad("Field 'source_defect_id' does not resolve to a defect.")

    # group 8: only a purchased loan can be demanded back
    if loan["purchase_status"] != "PURCHASED":
        raise ApiError("ERR_INVALID_LOAN_STATE")

    instant = now()

    if reason == "EPD":
        # group 11 precedes group 12: the window closes before the evidence
        deadline = plus_days(date_start(loan["first_payment_due_date"]),
                             calc.EPD_DEMAND_WINDOW_DAYS)
        if instant > deadline:
            raise ApiError("ERR_EPD_WINDOW_EXPIRED")
        if loan["first_payment_status"] != "MISSED":
            raise ApiError("ERR_EPD_NOT_ESTABLISHED")
    else:
        if (defect is None
                or defect["loan_id"] != loan["id"]
                or defect["severity"] not in EVIDENCE_SEVERITIES
                or defect["status"] not in EVIDENCE_STATUSES):
            raise ApiError("ERR_DEFECT_EVIDENCE_REQUIRED")

    advice = settled_advice(loan["id"])
    funding_recovery = advice["net_wire_cents"] if advice is not None else 0
    price, admin_fee = calc.repurchase_price(funding_recovery)

    record = base_record()
    record.update({
        "loan_id": loan["id"],
        "seller_id": loan["seller_id"],
        "source_defect_id": source_defect_id,
        "reason": reason,
        "status": "ISSUED",
        "demand_letter_reference": letter,
        "appeal_reason": None,
        "funding_recovery_cents": funding_recovery,
        "admin_fee_cents": admin_fee,
        "repurchase_price_cents": price,
        "remittance_reference": None,
        "issued_by_user_id": user_id(),
        "decided_by_user_id": None,
        "satisfied_at": None,
    })
    datetime_field(record, "appeal_deadline_at",
                   plus_days(instant, calc.APPEAL_WINDOW_DAYS))
    db.demands[record["id"]] = record

    loan["purchase_status"] = "REPURCHASE_DEMANDED"
    touch(loan)

    return created(public(record))


@repurchase_bp.route("/loans/<lid>/repurchase-demands", methods=["GET"])
@endpoint("PurchaseReviewer", "SellerUser", "CounterpartyAnalyst",
          "PlatformAdmin")
def list_loan_demands(lid):
    loan = need_loan(lid)
    require_scope(loan["seller_id"])
    limit, offset = v.pagination()
    status = v.arg("status")
    rows = loan_demands(loan["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@repurchase_bp.route("/repurchase-demands", methods=["GET"])
@endpoint("PurchaseReviewer", "CounterpartyAnalyst", "PlatformAdmin",
          "SellerUser")
def list_demands():
    limit, offset = v.pagination()
    seller_id = scope_seller_filter(v.arg("seller_id"))
    source_defect_id = v.arg("source_defect_id")
    reason = v.arg("reason")
    status = v.arg("status")
    rows = list(db.demands.values())
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if source_defect_id is not None:
        rows = [r for r in rows if r["source_defect_id"] == source_defect_id]
    if reason is not None:
        rows = [r for r in rows if r["reason"] == reason]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@repurchase_bp.route("/repurchase-demands/<did>", methods=["GET"])
@endpoint("PurchaseReviewer", "CounterpartyAnalyst", "PlatformAdmin",
          "SellerUser")
def read_demand(did):
    demand = need_demand(did)
    require_scope(demand["seller_id"])
    return ok(public(demand))


# --------------------------------------------------------------------------
# appeal, decision, satisfaction
# --------------------------------------------------------------------------

@repurchase_bp.route("/repurchase-demands/<did>/appeal", methods=["POST"])
@endpoint("SellerUser")
def appeal_demand(did):
    demand = need_demand(did)
    body = v.body()
    appeal_reason = v.req_str(body, "appeal_reason", min_len=1, max_len=2000)

    require_scope(demand["seller_id"])

    if demand["status"] != "ISSUED":
        raise ApiError("ERR_DEMAND_NOT_ACTIONABLE")
    if now() > dt_of(demand, "appeal_deadline_at"):
        raise ApiError("ERR_APPEAL_WINDOW_EXPIRED")

    demand["status"] = "APPEALED"
    demand["appeal_reason"] = appeal_reason
    touch(demand)
    return ok(public(demand))


@repurchase_bp.route("/repurchase-demands/<did>/decision", methods=["POST"])
@endpoint("PurchaseReviewer")
def decide_demand(did):
    demand = need_demand(did)
    body = v.body()
    decision = v.req_enum(body, "decision", DEMAND_DECISIONS)
    v.req_str(body, "note", max_len=1000, required=False)

    # group 6 sits above group 8: the issuer may never decide its own demand
    if demand["issued_by_user_id"] == user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "UPHOLD":
        if demand["status"] != "APPEALED":
            raise ApiError("ERR_DEMAND_NOT_ACTIONABLE")
        demand["status"] = "UPHELD"
        demand["decided_by_user_id"] = user_id()
        touch(demand)
        return ok(public(demand))

    if demand["status"] not in ("ISSUED", "APPEALED"):
        raise ApiError("ERR_DEMAND_NOT_ACTIONABLE")
    demand["status"] = "RESCINDED"
    demand["decided_by_user_id"] = user_id()
    touch(demand)

    loan = db.loans.get(demand["loan_id"])
    if loan is not None and loan["purchase_status"] == "REPURCHASE_DEMANDED":
        loan["purchase_status"] = "PURCHASED"
        touch(loan)

    return ok(public(demand))


@repurchase_bp.route("/repurchase-demands/<did>/settle", methods=["POST"])
@endpoint("SellerUser")
def settle_demand(did):
    demand = need_demand(did)
    body = v.body()
    remittance = v.req_str(body, "remittance_reference", min_len=1, max_len=200)

    require_scope(demand["seller_id"])

    # deliberately no segregation of duties here: the payer is the seller
    if demand["status"] not in ("ISSUED", "UPHELD"):
        raise ApiError("ERR_DEMAND_NOT_SETTLEABLE")

    instant = now()
    demand["status"] = "SATISFIED"
    demand["remittance_reference"] = remittance
    datetime_field(demand, "satisfied_at", instant)
    touch(demand)

    loan = db.loans.get(demand["loan_id"])
    if loan is not None:
        loan["purchase_status"] = "REPURCHASED"
        touch(loan)

        for advice in loan_advices(loan["id"]):
            if advice["status"] == "SETTLED":
                advice["status"] = "REVERSED"
                touch(advice)

        for transfer in loan_transfers(loan["id"]):
            if transfer["status"] in ("PENDING", "COMPLETED"):
                transfer["status"] = "REVERSED"
                transfer["reversal_reason"] = "REPURCHASE_SATISFIED"
                touch(transfer)

    seller = db.sellers.get(demand["seller_id"])
    if seller is not None:
        seller["net_funded_cents"] -= demand["funding_recovery_cents"]
        seller["fee_receivable_cents"] += demand["admin_fee_cents"]
        touch(seller)

    # the parent commitment is deliberately left exactly as it stands
    return ok(public(demand))


# --------------------------------------------------------------------------
# escrow transfers
# --------------------------------------------------------------------------

@repurchase_bp.route("/loans/<lid>/escrow-transfers", methods=["GET"])
@endpoint("PurchaseReviewer", "PlatformAdmin", "SellerUser")
def list_transfers(lid):
    loan = need_loan(lid)
    require_scope(loan["seller_id"])
    limit, offset = v.pagination()
    status = v.arg("status")
    rows = loan_transfers(loan["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@repurchase_bp.route("/escrow-transfers/<tid>/complete", methods=["POST"])
@endpoint("PurchaseReviewer", "PlatformAdmin")
def complete_transfer(tid):
    transfer = need_transfer(tid)
    body = v.body()
    letter = v.req_str(body, "goodbye_letter_reference", min_len=1, max_len=200)

    if transfer["status"] != "PENDING":
        raise ApiError("ERR_TRANSFER_NOT_PENDING")

    loan = db.loans.get(transfer["loan_id"])
    if loan is not None and loan["purchase_status"] in ("REPURCHASE_DEMANDED",
                                                        "REPURCHASED"):
        raise ApiError("ERR_LOAN_UNDER_REPURCHASE")

    if now() > dt_of(transfer, "transfer_due_at"):
        raise ApiError("ERR_ESCROW_TRANSFER_OVERDUE")

    transfer["status"] = "COMPLETED"
    transfer["goodbye_letter_reference"] = letter
    datetime_field(transfer, "completed_at", now())
    touch(transfer)
    return ok(public(transfer))
