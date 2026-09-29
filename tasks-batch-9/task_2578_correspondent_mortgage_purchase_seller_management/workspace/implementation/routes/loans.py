"""Purchase review: defects, suspense conditions, clearing and funding."""

from flask import Blueprint

import calc
import validate as v
from auth import endpoint, require_scope, scope_seller_filter, user_id
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import (datetime_field, dt_of, loan_advices, loan_conditions,
                     loan_defects, need_advice, need_commitment, need_condition,
                     need_defect, need_loan, on_review_item_added,
                     on_review_item_resolved, recompute_available,
                     release_exposure)
from store import base_record, db, now, plus_days, public, public_list, touch

loans_bp = Blueprint("loans", __name__)

DEFECT_CATEGORIES = ("CREDIT", "INCOME", "COLLATERAL", "COMPLIANCE",
                     "DOCUMENTATION")
DEFECT_SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
PAYMENT_EVENTS = ("FIRST_PAYMENT_PAID", "FIRST_PAYMENT_MISSED")
REVIEWABLE_STATES = ("IN_REVIEW", "SUSPENDED")
# a new review item is also accepted after clearing, which voids the advice
CONDITIONABLE_STATES = ("IN_REVIEW", "SUSPENDED", "CLEARED_FOR_PURCHASE")
DEFECTABLE_STATES = CONDITIONABLE_STATES + ("PURCHASED",)


# --------------------------------------------------------------------------
# loan reads
# --------------------------------------------------------------------------

@loans_bp.route("/loans", methods=["GET"])
@endpoint("PurchaseReviewer", "LockDeskTrader", "CounterpartyAnalyst",
          "PlatformAdmin", "SellerUser")
def list_loans():
    limit, offset = v.pagination()
    seller_id = scope_seller_filter(v.arg("seller_id"))
    commitment_id = v.arg("commitment_id")
    product_id = v.arg("product_id")
    purchase_status = v.arg("purchase_status")
    rows = list(db.loans.values())
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if commitment_id is not None:
        rows = [r for r in rows if r["commitment_id"] == commitment_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if purchase_status is not None:
        rows = [r for r in rows if r["purchase_status"] == purchase_status]
    rows.sort(key=lambda r: r["_seq"])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@loans_bp.route("/loans/<lid>", methods=["GET"])
@endpoint("PurchaseReviewer", "LockDeskTrader", "CounterpartyAnalyst",
          "PlatformAdmin", "SellerUser")
def read_loan(lid):
    loan = need_loan(lid)
    require_scope(loan["seller_id"])
    return ok(public(loan))


@loans_bp.route("/loans/<lid>/review", methods=["POST"])
@endpoint("PurchaseReviewer")
def open_review(lid):
    loan = need_loan(lid)
    body = v.body()
    v.req_str(body, "note", max_len=1000, required=False)

    if loan["purchase_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_LOAN_STATE")

    loan["purchase_status"] = "IN_REVIEW"
    touch(loan)
    return ok(public(loan))


# --------------------------------------------------------------------------
# defects
# --------------------------------------------------------------------------

@loans_bp.route("/loans/<lid>/defects", methods=["POST"])
@endpoint("PurchaseReviewer")
def create_defect(lid):
    loan = need_loan(lid)
    body = v.body()
    defect_code = v.req_str(body, "defect_code", min_len=2, max_len=48)
    category = v.req_enum(body, "category", DEFECT_CATEGORIES)
    severity = v.req_enum(body, "severity", DEFECT_SEVERITIES)

    # a late finding may also land on a cleared file, which voids its advice
    if loan["purchase_status"] not in DEFECTABLE_STATES:
        raise ApiError("ERR_INVALID_LOAN_STATE")

    classification = calc.defect_classification(category, severity)
    record = base_record()
    record.update({
        "loan_id": loan["id"],
        "defect_code": defect_code,
        "category": category,
        "severity": severity,
        "classification": classification,
        "status": "OPEN",
        "cured_at": None,
        "price_adjustment_bps": 0,
        "cure_document_reference": None,
        "identified_by_user_id": user_id(),
    })
    deadline = calc.cure_deadline(classification, severity,
                                 record["_created_dt"])
    datetime_field(record, "cure_deadline_at", deadline)
    db.defects[record["id"]] = record

    loan["open_defect_count"] += 1
    if classification == "NON_CURABLE":
        loan["non_curable_defect_count"] += 1
    on_review_item_added(loan)

    return created(public(record))


@loans_bp.route("/loans/<lid>/defects", methods=["GET"])
@endpoint("PurchaseReviewer", "SellerUser", "CounterpartyAnalyst",
          "PlatformAdmin")
def list_defects(lid):
    loan = need_loan(lid)
    require_scope(loan["seller_id"])
    limit, offset = v.pagination()
    status = v.arg("status")
    classification = v.arg("classification")
    rows = loan_defects(loan["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if classification is not None:
        rows = [r for r in rows if r["classification"] == classification]
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@loans_bp.route("/defects/<did>/cure", methods=["POST"])
@endpoint("SellerUser")
def cure_defect(did):
    defect = need_defect(did)
    body = v.body()
    reference = v.req_str(body, "cure_document_reference", min_len=1,
                          max_len=200)

    loan = db.loans.get(defect["loan_id"])
    require_scope(loan["seller_id"])

    if defect["status"] != "OPEN":
        raise ApiError("ERR_DEFECT_NOT_OPEN")
    deadline = dt_of(defect, "cure_deadline_at")
    if deadline is not None and now() > deadline:
        raise ApiError("ERR_CURE_WINDOW_EXPIRED")
    if defect["classification"] != "CURABLE":
        raise ApiError("ERR_DEFECT_NOT_CURABLE")

    defect["status"] = "CURED"
    defect["cure_document_reference"] = reference
    datetime_field(defect, "cured_at", now())
    touch(defect)

    loan["open_defect_count"] -= 1
    on_review_item_resolved(loan)
    return ok(public(defect))


@loans_bp.route("/defects/<did>/waive", methods=["POST"])
@endpoint("PurchaseReviewer", "PlatformAdmin")
def waive_defect(did):
    defect = need_defect(did)
    body = v.body()
    bps = v.req_int(body, "price_adjustment_bps", minimum=-100, maximum=0)

    if defect["status"] != "OPEN":
        raise ApiError("ERR_DEFECT_NOT_OPEN")
    if defect["classification"] != "CURABLE":
        raise ApiError("ERR_DEFECT_NOT_CURABLE")

    defect["status"] = "WAIVED"
    defect["price_adjustment_bps"] = bps
    touch(defect)

    loan = db.loans.get(defect["loan_id"])
    loan["open_defect_count"] -= 1
    on_review_item_resolved(loan)
    return ok(public(defect))


# --------------------------------------------------------------------------
# suspense conditions
# --------------------------------------------------------------------------

@loans_bp.route("/loans/<lid>/suspense-conditions", methods=["POST"])
@endpoint("PurchaseReviewer")
def create_condition(lid):
    loan = need_loan(lid)
    body = v.body()
    condition_code = v.req_str(body, "condition_code", min_len=2, max_len=48)
    description = v.req_str(body, "description", max_len=1000, required=False)

    if loan["purchase_status"] not in CONDITIONABLE_STATES:
        raise ApiError("ERR_INVALID_LOAN_STATE")

    record = base_record()
    record.update({
        "loan_id": loan["id"],
        "condition_code": condition_code,
        "description": description,
        "status": "OPEN",
        "cleared_at": None,
        "document_reference": None,
    })
    datetime_field(record, "due_at", calc.suspense_due(record["_created_dt"]))
    db.conditions[record["id"]] = record

    loan["open_suspense_count"] += 1
    on_review_item_added(loan)

    return created(public(record))


@loans_bp.route("/loans/<lid>/suspense-conditions", methods=["GET"])
@endpoint("PurchaseReviewer", "SellerUser", "CounterpartyAnalyst",
          "PlatformAdmin")
def list_conditions(lid):
    loan = need_loan(lid)
    require_scope(loan["seller_id"])
    limit, offset = v.pagination()
    status = v.arg("status")
    rows = loan_conditions(loan["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@loans_bp.route("/suspense-conditions/<cid>/clear", methods=["POST"])
@endpoint("PurchaseReviewer")
def clear_condition(cid):
    condition = need_condition(cid)
    body = v.body()
    reference = v.req_str(body, "document_reference", min_len=1, max_len=200)

    if condition["status"] != "OPEN":
        raise ApiError("ERR_CONDITION_NOT_OPEN")
    if now() > dt_of(condition, "due_at"):
        raise ApiError("ERR_SUSPENSE_WINDOW_EXPIRED")

    condition["status"] = "CLEARED"
    condition["document_reference"] = reference
    datetime_field(condition, "cleared_at", now())
    touch(condition)

    loan = db.loans.get(condition["loan_id"])
    loan["open_suspense_count"] -= 1
    on_review_item_resolved(loan)
    return ok(public(condition))


# --------------------------------------------------------------------------
# the per-loan condition sweep
# --------------------------------------------------------------------------

@loans_bp.route("/loans/<lid>/expire-conditions", methods=["POST"])
@endpoint("PurchaseReviewer", "PlatformAdmin")
def expire_conditions(lid):
    loan = need_loan(lid)
    v.body()
    instant = now()

    expired_defects = 0
    for defect in loan_defects(loan["id"]):
        if defect["status"] != "OPEN":
            continue
        if defect["classification"] != "CURABLE":
            continue
        deadline = dt_of(defect, "cure_deadline_at")
        if deadline is None or instant <= deadline:
            continue
        defect["status"] = "EXPIRED"
        touch(defect)
        expired_defects += 1

    expired_conditions = 0
    for condition in loan_conditions(loan["id"]):
        if condition["status"] != "OPEN":
            continue
        if instant <= dt_of(condition, "due_at"):
            continue
        condition["status"] = "EXPIRED"
        touch(condition)
        expired_conditions += 1

    loan["open_defect_count"] -= expired_defects
    loan["open_suspense_count"] -= expired_conditions
    on_review_item_resolved(loan)

    return ok({
        "expired_defect_count": expired_defects,
        "expired_condition_count": expired_conditions,
        "loan_purchase_status": loan["purchase_status"],
    })


# --------------------------------------------------------------------------
# clearing and rejection
# --------------------------------------------------------------------------

@loans_bp.route("/loans/<lid>/clear", methods=["POST"])
@endpoint("PurchaseReviewer")
def clear_loan(lid):
    loan = need_loan(lid)
    body = v.body()
    v.req_str(body, "note", max_len=1000, required=False)

    if loan["purchase_status"] not in REVIEWABLE_STATES:
        raise ApiError("ERR_INVALID_LOAN_STATE")

    # group 9 sits above group 12: the non-curable finding decides the file
    if loan["non_curable_defect_count"] > 0:
        raise ApiError("ERR_NON_CURABLE_DEFECT_PRESENT")
    if loan["open_defect_count"] > 0:
        raise ApiError("ERR_OPEN_DEFECTS_PRESENT")
    if loan["open_suspense_count"] > 0:
        raise ApiError("ERR_OPEN_SUSPENSE_CONDITIONS")

    loan["purchase_status"] = "CLEARED_FOR_PURCHASE"
    touch(loan)
    return ok(public(loan))


@loans_bp.route("/loans/<lid>/reject", methods=["POST"])
@endpoint("PurchaseReviewer")
def reject_loan(lid):
    loan = need_loan(lid)
    body = v.body()
    v.req_str(body, "note", max_len=1000, required=False)

    if loan["purchase_status"] not in REVIEWABLE_STATES:
        raise ApiError("ERR_INVALID_LOAN_STATE")
    if loan["non_curable_defect_count"] < 1:
        raise ApiError("ERR_NO_NON_CURABLE_DEFECT")

    loan["purchase_status"] = "REJECTED"
    touch(loan)

    # COMPENSATION of the delivery; the commitment's status is left untouched
    commitment = db.commitments.get(loan["commitment_id"])
    if commitment is not None:
        commitment["allocated_amount_cents"] -= loan["note_amount_cents"]
        recompute_available(commitment)
        touch(commitment)

    return ok(public(loan))


# --------------------------------------------------------------------------
# purchase advices
# --------------------------------------------------------------------------

@loans_bp.route("/loans/<lid>/purchase-advices", methods=["POST"])
@endpoint("PurchaseReviewer")
def issue_advice(lid):
    loan = need_loan(lid)
    body = v.body()
    expected_version = v.req_int(body, "expected_loan_version", minimum=1)

    # group 7: optimistic concurrency on the loan the pricing was computed from
    if expected_version != loan["version"]:
        raise ApiError("ERR_STALE_LOAN_VERSION")

    # group 8: only a cleared file may be priced
    if loan["purchase_status"] != "CLEARED_FOR_PURCHASE":
        raise ApiError("ERR_INVALID_LOAN_STATE")

    commitment = db.commitments.get(loan["commitment_id"])
    product = db.products.get(loan["product_id"])
    instant = now()

    incentive = calc.volume_incentive_bps(loan["seller_id"], loan["id"], instant)
    final_price = calc.final_purchase_price_pct(
        commitment["commitment_price_pct"], incentive)
    amounts = calc.advice_amounts(loan, product, final_price, instant)

    record = base_record()
    record.update({
        "loan_id": loan["id"],
        "status": "ISSUED",
        "volume_incentive_bps": incentive,
        "final_purchase_price_pct": final_price,
        "funding_reference": None,
        "issued_by_user_id": user_id(),
        "settled_by_user_id": None,
        "settled_at": None,
    })
    record.update(amounts)
    datetime_field(record, "issued_at", instant)

    for prior in loan_advices(loan["id"]):
        if prior["status"] == "ISSUED":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    db.advices[record["id"]] = record

    loan["advice_count"] += 1
    touch(loan)

    return created(public(record))


@loans_bp.route("/loans/<lid>/purchase-advices", methods=["GET"])
@endpoint("PurchaseReviewer", "SellerUser", "CounterpartyAnalyst",
          "PlatformAdmin")
def list_advices(lid):
    loan = need_loan(lid)
    require_scope(loan["seller_id"])
    limit, offset = v.pagination()
    status = v.arg("status")
    rows = loan_advices(loan["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@loans_bp.route("/purchase-advices/<aid>/settle", methods=["POST"])
@endpoint("PurchaseReviewer", "PlatformAdmin")
def settle_advice(aid):
    advice = need_advice(aid)
    body = v.body()
    funding_reference = v.req_str(body, "funding_reference", min_len=1,
                                 max_len=200)

    # group 6 sits above group 8: the wire may never be sent by the issuer
    if advice["issued_by_user_id"] == user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if advice["status"] != "ISSUED":
        raise ApiError("ERR_ADVICE_NOT_SETTLEABLE")

    instant = now()
    loan = db.loans.get(advice["loan_id"])
    commitment = db.commitments.get(loan["commitment_id"])
    seller = db.sellers.get(loan["seller_id"])

    advice["status"] = "SETTLED"
    advice["funding_reference"] = funding_reference
    advice["settled_by_user_id"] = user_id()
    datetime_field(advice, "settled_at", instant)
    touch(advice)

    # 1. the loan is purchased
    loan["purchase_status"] = "PURCHASED"
    datetime_field(loan, "purchased_at", instant)
    touch(loan)

    # 2. a servicing-released loan hands its escrow over
    if loan["servicing_election"] == "RELEASED":
        transfer = base_record()
        transfer.update({
            "loan_id": loan["id"],
            "transfer_amount_cents": loan["escrow_balance_cents"],
            "status": "PENDING",
            "goodbye_letter_reference": None,
            "completed_at": None,
            "reversal_reason": None,
        })
        datetime_field(transfer, "transfer_due_at",
                       plus_days(instant, calc.ESCROW_TRANSFER_DAYS))
        db.transfers[transfer["id"]] = transfer

    # 3. the commitment fills; the allocation converts into fulfilment
    if commitment is not None:
        commitment["allocated_amount_cents"] -= loan["note_amount_cents"]
        commitment["fulfilled_amount_cents"] += loan["note_amount_cents"]
        recompute_available(commitment)
        threshold = (commitment["notional_amount_cents"]
                     - commitment["tolerance_cents"])
        if commitment["fulfilled_amount_cents"] >= threshold:
            commitment["status"] = "FULFILLED"
            # tolerance write-off: never billable
            commitment["cancelled_amount_cents"] += commitment["available_amount_cents"]
            recompute_available(commitment)
            release_exposure(commitment)
        elif commitment["status"] == "LOCKED":
            commitment["status"] = "PARTIALLY_FULFILLED"
        touch(commitment)

    # 4. the seller is funded
    if seller is not None:
        seller["net_funded_cents"] += advice["net_wire_cents"]
        touch(seller)

    return ok(public(advice))


# --------------------------------------------------------------------------
# first-payment outcome
# --------------------------------------------------------------------------

@loans_bp.route("/loans/<lid>/payment-events", methods=["POST"])
@endpoint("PlatformAdmin")
def payment_event(lid):
    loan = need_loan(lid)
    body = v.body()
    event_type = v.req_enum(body, "event_type", PAYMENT_EVENTS)

    loan["first_payment_status"] = ("PAID" if event_type == "FIRST_PAYMENT_PAID"
                                   else "MISSED")
    touch(loan)
    return ok(public(loan))
