"""The rejection-memo cycle: dispute, counter, arbitration and aging
(PRD section 3.8)."""

from flask import Blueprint

import calculations as C
from calculations import (MEMO_RAISE_WINDOW_DAYS, recompute_net_position,
                          refresh_memo_aging, round_half_up)
from errors import ApiError
from responses import ok, ok_list
from store import db, fmt_dt, must_find, new_row, serialize, touch
import validation as V

bp = Blueprint("memos", __name__)


def _serialize_memo(memo):
    refresh_memo_aging(memo)
    return serialize(memo)


def _whole_days_since(anchor):
    if anchor is None:
        return None
    return int((db.clock - anchor).total_seconds()) // 86400


def _resolution_cascade(memo, invoice, terminal_status):
    """Hops 1-5, shared by memo acceptance and an UPHELD arbitration ruling."""
    # Hop 1 — the memo itself resolves.
    memo["status"] = terminal_status
    memo["resolved_at"] = fmt_dt(db.clock)
    memo["_resolved_at"] = db.clock
    refresh_memo_aging(memo)
    touch(memo)

    amount = memo["amount_minor"]

    # Hop 2 — the invoice moves, and the fork is decided.
    rejected_before = invoice["rejected_amount_minor"]
    invoice["rejected_amount_minor"] = rejected_before + amount
    invoice["disputed_amount_minor"] -= amount
    invoice["net_billed_minor"] = (invoice["total_claim_minor"]
                                   - invoice["rejected_amount_minor"])
    impact = round_half_up(amount * invoice["fixed_rate_scaled"], C.RATE_SCALE)
    memo["settlement_impact_minor"] = impact

    billing_carrier = db.carriers.get(invoice["billing_carrier_id"])
    billed_carrier = db.carriers.get(invoice["billed_carrier_id"])
    if billing_carrier is not None:
        billing_carrier["settled_receivable_minor"] -= impact
        recompute_net_position(billing_carrier)
        touch(billing_carrier)
    if billed_carrier is not None:
        billed_carrier["settled_payable_minor"] -= impact
        recompute_net_position(billed_carrier)
        touch(billed_carrier)

    if rejected_before + amount < invoice["total_claim_minor"]:
        invoice["status"] = "PARTIALLY_REJECTED"
    else:
        invoice["status"] = "FULLY_REJECTED"
    touch(invoice)

    # Hop 3 — the contested coupon is adjusted.
    coupon = db.coupons.get(memo["coupon_id"])
    ticket = None
    if coupon is not None:
        coupon["allocated_amount_minor"] -= amount
        coupon["adjusted_amount_minor"] += amount
        coupon["coupon_status"] = "ADJUSTED"
        touch(coupon)
        ticket = db.tickets.get(coupon["ticket_id"])
        if ticket is not None:
            ticket["unallocated_residual_minor"] += amount

    # Hop 4 — the owning ticket enters reproration and dispute.
    if ticket is not None:
        ticket["proration_status"] = "REPRORATION_REQUIRED"
        ticket["billing_status"] = "DISPUTED"
        touch(ticket)

        # Hop 5 — the validating carrier's reproration counter advances.
        validating = db.carriers.get(ticket["validating_carrier_id"])
        if validating is not None:
            validating["open_reproration_count"] += 1
            if validating["open_reproration_count"] >= 3:
                validating["audit_flag"] = True
            touch(validating)


@bp.route("/interline/rejection-memos", methods=["POST"])
def raise_memo():
    user_id, role = V.require([V.ROLE_BILLING])
    data = V.body()
    invoice_id = V.req_str(data, "invoice_id")
    coupon_id = V.req_str(data, "coupon_id")
    amount_minor = V.req_int(data, "amount_minor", minimum=1)
    reason_code = V.req_enum(data, "reason_code", V.REASON_CODES)
    expected_version = V.req_int(data, "expected_invoice_version")

    invoice = must_find("invoice", invoice_id)
    coupon = must_find("coupon", coupon_id)

    V.require_ownership(user_id, role, invoice["billed_carrier_id"])

    if invoice["status"] not in ("CLEARED", "PARTIALLY_REJECTED"):
        raise ApiError("ERR_INVOICE_NOT_CLEARED")

    billed_carrier = db.carriers.get(invoice["billed_carrier_id"])
    if billed_carrier is None or billed_carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")

    age = _whole_days_since(invoice.get("_cleared_at"))
    if age is None or age > MEMO_RAISE_WINDOW_DAYS:
        raise ApiError("ERR_MEMO_WINDOW_EXPIRED")

    if coupon.get("billing_invoice_id") != invoice["id"]:
        raise ApiError("ERR_COUPON_NOT_ON_INVOICE")

    if amount_minor > coupon["allocated_amount_minor"]:
        raise ApiError("ERR_MEMO_AMOUNT_EXCEEDS_COUPON")

    if (invoice["disputed_amount_minor"] + invoice["rejected_amount_minor"]
            + amount_minor) > invoice["total_claim_minor"]:
        raise ApiError("ERR_MEMO_AMOUNT_EXCEEDS_INVOICE")

    if expected_version != invoice["version"]:
        raise ApiError("ERR_STALE_INVOICE_VERSION")

    memo = new_row({
        "invoice_id": invoice["id"],
        "coupon_id": coupon["id"],
        "raised_by_carrier_id": invoice["billed_carrier_id"],
        "stage": 1,
        "amount_minor": amount_minor,
        "reason_code": reason_code,
        "status": "RAISED",
        "counter_amount_minor": 0,
        "counter_reason": None,
        "raised_at": fmt_dt(db.clock),
        "resolved_at": None,
        "age_days": 0,
        "aging_bucket": "CURRENT",
        "settlement_impact_minor": 0,
    })
    memo["_raised_at"] = db.clock
    memo["_resolved_at"] = None
    db.memos[memo["id"]] = memo

    invoice["disputed_amount_minor"] += amount_minor
    touch(invoice)

    return ok(_serialize_memo(memo), 201)


@bp.route("/interline/rejection-memos/<memo_id>", methods=["GET"])
def get_memo(memo_id):
    V.require(V.ALL_ROLES)
    memo = must_find("memo", memo_id)
    return ok(_serialize_memo(memo))


@bp.route("/interline/rejection-memos", methods=["GET"])
def list_memos():
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    invoice_id = V.filter_str("invoice_id")
    coupon_id = V.filter_str("coupon_id")
    raised_by = V.filter_str("raised_by_carrier_id")
    status = V.filter_enum("status", V.MEMO_STATUSES)
    aging_bucket = V.filter_enum("aging_bucket", V.AGING_BUCKETS)

    rows = list(db.memos.values())
    for memo in rows:
        refresh_memo_aging(memo)
    if invoice_id is not None:
        rows = [r for r in rows if r["invoice_id"] == invoice_id]
    if coupon_id is not None:
        rows = [r for r in rows if r["coupon_id"] == coupon_id]
    if raised_by is not None:
        rows = [r for r in rows if r["raised_by_carrier_id"] == raised_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if aging_bucket is not None:
        rows = [r for r in rows if r["aging_bucket"] == aging_bucket]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/rejection-memos/<memo_id>/counter", methods=["POST"])
def counter_memo(memo_id):
    user_id, role = V.require([V.ROLE_BILLING])
    data = V.body()
    counter_amount = V.req_int(data, "counter_amount_minor", minimum=0)
    counter_reason = V.req_str(data, "counter_reason")

    memo = must_find("memo", memo_id)
    invoice = db.invoices.get(memo["invoice_id"])

    V.require_ownership(user_id, role,
                        invoice["billing_carrier_id"] if invoice else None)

    if memo["status"] != "RAISED":
        raise ApiError("ERR_MEMO_STATE_INVALID")

    if counter_amount > memo["amount_minor"]:
        V.bad("counter_amount_minor may not exceed the memo's amount_minor.")

    memo["status"] = "COUNTERED"
    memo["counter_amount_minor"] = counter_amount
    memo["counter_reason"] = counter_reason
    touch(memo)
    return ok(_serialize_memo(memo))


@bp.route("/interline/rejection-memos/<memo_id>/re-reject", methods=["POST"])
def re_reject_memo(memo_id):
    user_id, role = V.require([V.ROLE_BILLING])
    data = V.body()
    amount_minor = V.req_int(data, "amount_minor", minimum=1)
    reason_code = V.req_enum(data, "reason_code", V.REASON_CODES)
    expected_version = V.req_int(data, "expected_invoice_version")

    memo = must_find("memo", memo_id)
    invoice = db.invoices.get(memo["invoice_id"])

    V.require_ownership(user_id, role,
                        invoice["billed_carrier_id"] if invoice else None)

    if memo["status"] != "COUNTERED":
        raise ApiError("ERR_MEMO_STATE_INVALID")

    billed_carrier = db.carriers.get(invoice["billed_carrier_id"])
    if billed_carrier is None or billed_carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")

    age = _whole_days_since(invoice.get("_cleared_at"))
    if age is None or age > MEMO_RAISE_WINDOW_DAYS:
        raise ApiError("ERR_MEMO_WINDOW_EXPIRED")

    if memo["stage"] >= 3:
        raise ApiError("ERR_MEMO_STAGE_EXHAUSTED")

    coupon = db.coupons.get(memo["coupon_id"])
    if coupon is None or amount_minor > coupon["allocated_amount_minor"]:
        raise ApiError("ERR_MEMO_AMOUNT_EXCEEDS_COUPON")

    disputed_without_self = invoice["disputed_amount_minor"] - memo["amount_minor"]
    if (disputed_without_self + invoice["rejected_amount_minor"]
            + amount_minor) > invoice["total_claim_minor"]:
        raise ApiError("ERR_MEMO_AMOUNT_EXCEEDS_INVOICE")

    if expected_version != invoice["version"]:
        raise ApiError("ERR_STALE_INVOICE_VERSION")

    invoice["disputed_amount_minor"] += amount_minor - memo["amount_minor"]
    memo["status"] = "RAISED"
    memo["stage"] += 1
    memo["amount_minor"] = amount_minor
    memo["reason_code"] = reason_code
    memo["counter_amount_minor"] = 0
    touch(memo)
    touch(invoice)
    return ok(_serialize_memo(memo))


@bp.route("/interline/rejection-memos/<memo_id>/accept", methods=["POST"])
def accept_memo(memo_id):
    user_id, role = V.require([V.ROLE_BILLING])
    data = V.body()
    expected_version = V.req_int(data, "expected_invoice_version")

    memo = must_find("memo", memo_id)
    invoice = db.invoices.get(memo["invoice_id"])

    V.require_ownership(user_id, role,
                        invoice["billing_carrier_id"] if invoice else None)

    if memo["status"] != "RAISED":
        raise ApiError("ERR_MEMO_STATE_INVALID")

    if expected_version != invoice["version"]:
        raise ApiError("ERR_STALE_INVOICE_VERSION")

    _resolution_cascade(memo, invoice, "ACCEPTED")
    return ok(_serialize_memo(memo))


@bp.route("/interline/rejection-memos/<memo_id>/withdraw", methods=["POST"])
def withdraw_memo(memo_id):
    user_id, role = V.require([V.ROLE_BILLING])
    data = V.body()
    expected_version = V.req_int(data, "expected_invoice_version")

    memo = must_find("memo", memo_id)
    invoice = db.invoices.get(memo["invoice_id"])

    V.require_ownership(user_id, role,
                        invoice["billed_carrier_id"] if invoice else None)

    if memo["status"] not in ("RAISED", "COUNTERED"):
        raise ApiError("ERR_MEMO_STATE_INVALID")

    if expected_version != invoice["version"]:
        raise ApiError("ERR_STALE_INVOICE_VERSION")

    memo["status"] = "WITHDRAWN"
    memo["resolved_at"] = fmt_dt(db.clock)
    memo["_resolved_at"] = db.clock
    refresh_memo_aging(memo)
    touch(memo)

    invoice["disputed_amount_minor"] -= memo["amount_minor"]
    touch(invoice)
    return ok(_serialize_memo(memo))


@bp.route("/interline/rejection-memos/<memo_id>/escalate", methods=["POST"])
def escalate_memo(memo_id):
    user_id, role = V.require([V.ROLE_BILLING])
    V.body()
    memo = must_find("memo", memo_id)
    invoice = db.invoices.get(memo["invoice_id"])

    owners = []
    if invoice is not None:
        owners = [invoice["billed_carrier_id"], invoice["billing_carrier_id"]]
    V.require_ownership(user_id, role, owners)

    if memo["status"] not in ("RAISED", "COUNTERED"):
        raise ApiError("ERR_MEMO_STATE_INVALID")

    refresh_memo_aging(memo)
    if not (memo["stage"] == 3 or memo["age_days"] >= C.ARBITRATION_MIN_AGE_DAYS):
        raise ApiError("ERR_ARBITRATION_NOT_ELIGIBLE")

    memo["status"] = "ARBITRATION"
    touch(memo)
    return ok(_serialize_memo(memo))


@bp.route("/interline/rejection-memos/<memo_id>/arbitrate", methods=["POST"])
def arbitrate_memo(memo_id):
    V.require([V.ROLE_OPERATOR])
    data = V.body()
    ruling = V.req_enum(data, "ruling", ("UPHELD", "DENIED"))

    memo = must_find("memo", memo_id)
    invoice = db.invoices.get(memo["invoice_id"])

    if memo["status"] != "ARBITRATION":
        raise ApiError("ERR_MEMO_STATE_INVALID")

    if ruling == "UPHELD":
        _resolution_cascade(memo, invoice, "RESOLVED_UPHELD")
    else:
        memo["status"] = "RESOLVED_DENIED"
        memo["resolved_at"] = fmt_dt(db.clock)
        memo["_resolved_at"] = db.clock
        refresh_memo_aging(memo)
        touch(memo)
        invoice["disputed_amount_minor"] -= memo["amount_minor"]
        touch(invoice)
    return ok(_serialize_memo(memo))
