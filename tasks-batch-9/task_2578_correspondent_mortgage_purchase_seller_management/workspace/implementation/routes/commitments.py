"""Lock desk: commitments, pair-off, the expiry sweep and loan delivery."""

from flask import Blueprint

import calc
import validate as v
from auth import (endpoint, is_seller_user, require_scope, scope_seller_filter,
                  user_id)
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import (assess_administrative_flat, datetime_field,
                     need_commitment, need_seller, recompute_available,
                     release_exposure, seller_commitments)
from store import (base_record, date_start, db, now, parse_date, public,
                   public_list, touch)

commitments_bp = Blueprint("commitments", __name__)

COMMITMENT_TYPES = ("MANDATORY", "BEST_EFFORTS")
COMMITMENT_STATUSES = ("LOCKED", "PARTIALLY_FULFILLED", "FULFILLED",
                       "PAIRED_OFF", "EXPIRED", "CANCELLED")
OCCUPANCIES = ("PRIMARY", "SECOND_HOME", "INVESTMENT")
SERVICING_ELECTIONS = ("RETAINED", "RELEASED")
OPEN_STATUSES = ("LOCKED", "PARTIALLY_FULFILLED")


def _windows_overlap(a_start, a_expiry, b_start, b_expiry):
    """Half-open [start, expiry) intervals; merely touching is not overlapping."""
    return a_start < b_expiry and b_start < a_expiry


# --------------------------------------------------------------------------
# lock a commitment
# --------------------------------------------------------------------------

@commitments_bp.route("/commitments", methods=["POST"])
@endpoint("LockDeskTrader", "SellerUser")
def create_commitment():
    body = v.body()
    seller_id = v.req_str(body, "seller_id", min_len=1)
    product_id = v.req_str(body, "product_id", min_len=1)
    commitment_type = v.req_enum(body, "commitment_type", COMMITMENT_TYPES)
    notional_amount_cents = v.req_int(body, "notional_amount_cents",
                                      minimum=1000000)
    window_start, start_date = v.req_date(body, "delivery_window_start")
    expiry, expiry_date = v.req_date(body, "delivery_expiry_date")
    reference_fico = v.req_int(body, "reference_fico", minimum=300, maximum=850)
    reference_ltv_pct = v.req_num(body, "reference_ltv_pct", minimum="0.1",
                                  maximum="100.0")
    if expiry_date <= start_date:
        v.bad("Field 'delivery_expiry_date' must fall after "
              "'delivery_window_start'.")
    lock_term_days = (expiry_date - start_date).days
    if lock_term_days > calc.MAX_LOCK_TERM_DAYS:
        v.bad("The delivery window may not exceed 60 days.")

    seller = db.sellers.get(seller_id)
    if seller is None:
        v.bad("Field 'seller_id' does not resolve to a seller.")
    product = db.products.get(product_id)
    if product is None:
        v.bad("Field 'product_id' does not resolve to a product.")

    require_scope(seller["id"])

    if seller["approval_status"] != "APPROVED":
        raise ApiError("ERR_SELLER_NOT_APPROVED")
    if seller["delivery_standing"] not in ("GOOD_STANDING", "WATCH"):
        raise ApiError("ERR_SELLER_DELIVERY_SUSPENDED")

    if product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_NOT_ELIGIBLE")
    if commitment_type not in product["allowed_commitment_types"]:
        raise ApiError("ERR_COMMITMENT_TYPE_NOT_ALLOWED")

    if commitment_type == "MANDATORY":
        for other in seller_commitments(seller["id"]):
            if other["commitment_type"] != "MANDATORY":
                continue
            if other["product_id"] != product["id"]:
                continue
            if other["status"] not in OPEN_STATUSES:
                continue
            if _windows_overlap(start_date, expiry_date,
                                parse_date(other["delivery_window_start"]),
                                parse_date(other["delivery_expiry_date"])):
                raise ApiError("ERR_DELIVERY_WINDOW_OVERLAP")

        if (seller["open_mandatory_exposure_cents"] + notional_amount_cents
                > seller["mandatory_exposure_limit_cents"]):
            raise ApiError("ERR_MANDATORY_EXPOSURE_LIMIT_EXCEEDED")

    price, term_bps, llpa = calc.commitment_price_pct(
        product, commitment_type, lock_term_days, reference_fico,
        reference_ltv_pct)

    record = base_record()
    record.update({
        "seller_id": seller["id"],
        "product_id": product["id"],
        "commitment_type": commitment_type,
        "notional_amount_cents": notional_amount_cents,
        "delivery_window_start": window_start,
        "delivery_expiry_date": expiry,
        "reference_fico": reference_fico,
        "reference_ltv_pct": reference_ltv_pct,
        "lock_term_days": lock_term_days,
        "llpa_bps_applied": llpa,
        "commitment_price_pct": price,
        "status": "LOCKED",
        "allocated_amount_cents": 0,
        "fulfilled_amount_cents": 0,
        "paired_off_amount_cents": 0,
        "cancelled_amount_cents": 0,
        "available_amount_cents": notional_amount_cents,
        "tolerance_cents": calc.tolerance_cents(notional_amount_cents),
        "pair_off_fee_cents": 0,
        "pair_off_market_price_pct": None,
        "pair_off_method": None,
        "locked_by_user_id": user_id(),
    })
    db.commitments[record["id"]] = record

    if commitment_type == "MANDATORY":
        seller["open_mandatory_exposure_cents"] += notional_amount_cents
        touch(seller)

    return created(public(record))


@commitments_bp.route("/commitments", methods=["GET"])
@endpoint("LockDeskTrader", "CounterpartyAnalyst", "PurchaseReviewer",
          "PlatformAdmin", "SellerUser")
def list_commitments():
    limit, offset = v.pagination()
    seller_id = scope_seller_filter(v.arg("seller_id"))
    product_id = v.arg("product_id")
    commitment_type = v.arg("commitment_type")
    status = v.arg("status")
    rows = list(db.commitments.values())
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if commitment_type is not None:
        rows = [r for r in rows if r["commitment_type"] == commitment_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@commitments_bp.route("/commitments/<cid>", methods=["GET"])
@endpoint("LockDeskTrader", "CounterpartyAnalyst", "PurchaseReviewer",
          "PlatformAdmin", "SellerUser")
def read_commitment(cid):
    commitment = need_commitment(cid)
    require_scope(commitment["seller_id"])
    return ok(public(commitment))


# --------------------------------------------------------------------------
# explicit pair-off
# --------------------------------------------------------------------------

@commitments_bp.route("/commitments/<cid>/pair-off", methods=["POST"])
@endpoint("LockDeskTrader")
def pair_off(cid):
    commitment = need_commitment(cid)
    body = v.body()
    market_price_pct = v.req_num(body, "pair_off_market_price_pct",
                                 minimum="0.000")

    if commitment["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_COMMITMENT_NOT_OPEN")
    if commitment["allocated_amount_cents"] != 0:
        raise ApiError("ERR_ALLOCATION_OUTSTANDING")

    variant = ("MANDATORY_MARK_TO_MARKET"
               if commitment["commitment_type"] == "MANDATORY"
               else "BEST_EFFORTS_ADMIN_ONLY")
    fee, method = calc.pair_off_fee(commitment, variant, market_price_pct)

    commitment["paired_off_amount_cents"] += commitment["available_amount_cents"]
    recompute_available(commitment)
    commitment["pair_off_market_price_pct"] = market_price_pct
    commitment["pair_off_fee_cents"] = fee
    commitment["pair_off_method"] = method
    commitment["status"] = "PAIRED_OFF"

    seller = db.sellers.get(commitment["seller_id"])
    if seller is not None:
        seller["fee_receivable_cents"] += fee
        touch(seller)
    release_exposure(commitment)
    touch(commitment)
    return ok(public(commitment))


# --------------------------------------------------------------------------
# expiry sweep
# --------------------------------------------------------------------------

@commitments_bp.route("/commitments/expire-due", methods=["POST"])
@endpoint("LockDeskTrader", "PlatformAdmin")
def expire_due():
    body = v.body()
    seller_id = v.req_str(body, "seller_id", min_len=1, required=False)
    if seller_id is None:
        seller_id = v.arg("seller_id")
    if seller_id is not None and seller_id not in db.sellers:
        v.bad("Field 'seller_id' does not resolve to a seller.")

    instant = now()
    rows = [c for c in db.commitments.values() if c["status"] in OPEN_STATUSES]
    if seller_id is not None:
        rows = [c for c in rows if c["seller_id"] == seller_id]
    rows = [c for c in rows if c["allocated_amount_cents"] == 0]
    rows = [c for c in rows
            if instant >= date_start(c["delivery_expiry_date"])]
    rows.sort(key=lambda c: c["_seq"])

    expired_ids = []
    total_fee = 0
    for commitment in rows:
        seller = db.sellers.get(commitment["seller_id"])
        commitment["status"] = "EXPIRED"
        total_fee += assess_administrative_flat(commitment, seller)
        expired_ids.append(commitment["id"])

    return ok({
        "expired_count": len(expired_ids),
        "expired_commitment_ids": expired_ids,
        "total_pair_off_fee_cents": total_fee,
    })


# --------------------------------------------------------------------------
# loan delivery
# --------------------------------------------------------------------------

@commitments_bp.route("/commitments/<cid>/loans", methods=["POST"])
@endpoint("SellerUser", "LockDeskTrader")
def deliver_loan(cid):
    commitment = need_commitment(cid)
    body = v.body()
    expected_version = v.req_int(body, "expected_commitment_version", minimum=1)
    seller_loan_number = v.req_str(body, "seller_loan_number", min_len=1,
                                   max_len=32)
    note_amount_cents = v.req_int(body, "note_amount_cents", minimum=1)
    note_rate_pct = v.req_num(body, "note_rate_pct", minimum="0.001",
                              maximum="25.000")
    fico = v.req_int(body, "fico", minimum=300, maximum=850)
    ltv_pct = v.req_num(body, "ltv_pct", minimum="0.1", maximum="150.0")
    occupancy = v.req_enum(body, "occupancy", OCCUPANCIES)
    servicing_election = v.req_enum(body, "servicing_election",
                                    SERVICING_ELECTIONS)
    closing_date, closing = v.req_date(body, "closing_date")
    first_due, first_due_date = v.req_date(body, "first_payment_due_date")
    escrow_balance_cents = v.req_int(body, "escrow_balance_cents", minimum=0,
                                     required=False, default=0)
    if first_due_date <= closing:
        v.bad("Field 'first_payment_due_date' must fall after 'closing_date'.")

    require_scope(commitment["seller_id"])

    # group 7: optimistic concurrency on the commitment's capacity view
    if expected_version != commitment["version"]:
        raise ApiError("ERR_STALE_COMMITMENT_VERSION")

    # group 8: commitment lifecycle
    if commitment["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_COMMITMENT_NOT_OPEN")

    seller = db.sellers.get(commitment["seller_id"])
    product = db.products.get(commitment["product_id"])

    # group 9: seller standing
    if seller["delivery_standing"] not in ("GOOD_STANDING", "WATCH"):
        raise ApiError("ERR_SELLER_DELIVERY_SUSPENDED")

    # group 10: product eligibility matrix, every bound inclusive
    if (product["status"] != "ACTIVE"
            or fico < product["min_fico"]
            or ltv_pct > calc.dec(product["max_ltv_pct"])
            or note_amount_cents > product["max_loan_amount_cents"]
            or occupancy not in product["allowed_occupancies"]):
        raise ApiError("ERR_PRODUCT_NOT_ELIGIBLE")
    if servicing_election == "RETAINED" and not seller["servicing_retained_eligible"]:
        raise ApiError("ERR_SERVICING_RETAINED_NOT_ELIGIBLE")

    # group 11: the half-open delivery window
    instant = now()
    if not (date_start(commitment["delivery_window_start"]) <= instant
            < date_start(commitment["delivery_expiry_date"])):
        raise ApiError("ERR_COMMITMENT_EXPIRED")

    # group 12: seller-scoped uniqueness
    for other in db.loans.values():
        if (other["seller_id"] == commitment["seller_id"]
                and other["seller_loan_number"] == seller_loan_number):
            raise ApiError("ERR_DUPLICATE_SELLER_LOAN_NUMBER")

    # group 13: conserved capacity
    if note_amount_cents > commitment["available_amount_cents"]:
        raise ApiError("ERR_COMMITMENT_CAPACITY_EXCEEDED")

    record = base_record()
    record.update({
        "commitment_id": commitment["id"],
        "seller_id": commitment["seller_id"],
        "product_id": commitment["product_id"],
        "seller_loan_number": seller_loan_number,
        "note_amount_cents": note_amount_cents,
        "note_rate_pct": note_rate_pct,
        "fico": fico,
        "ltv_pct": ltv_pct,
        "occupancy": occupancy,
        "servicing_election": servicing_election,
        "escrow_balance_cents": escrow_balance_cents,
        "closing_date": closing_date,
        "first_payment_due_date": first_due,
        "first_payment_status": "PENDING",
        "purchase_status": "DELIVERED",
        "review_cycle_count": 0,
        "open_defect_count": 0,
        "non_curable_defect_count": 0,
        "open_suspense_count": 0,
        "advice_count": 0,
        "purchased_at": None,
    })
    datetime_field(record, "delivered_at", instant)
    db.loans[record["id"]] = record

    commitment["allocated_amount_cents"] += note_amount_cents
    recompute_available(commitment)
    touch(commitment)

    return created(public(record))
