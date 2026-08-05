"""Routes: invoices, payments, fee-adjustment."""
from datetime import timedelta

from flask import Blueprint, g

import helpers as h
import domain as d
from state import S, clock_date, clock_dt

bp = Blueprint("billing", __name__)

_METHODS = {"CARD", "ACH", "CASH"}


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@bp.post("/co-living/invoices")
def create_invoice():
    h.authorize("FinanceAdmin")
    b = h.body()
    membership_id = h.req_str(b, "membership_id")
    period_start = h.req_date(b, "period_start")
    period_end = h.req_date(b, "period_end")
    # Priority 6: FK
    m = h.find_or_404(S.memberships, membership_id, "ERR_MEMBERSHIP_NOT_FOUND")
    # Priority 12: tenancy gate
    if m["tenancy_status"] not in ("ACTIVE", "NOTICE_GIVEN"):
        raise h.ApiError("ERR_INVALID_MEMBERSHIP_STATE", "tenancy cannot be billed")
    # Priority 18: date range
    if period_end < period_start:
        raise h.ApiError("ERR_INVALID_DATE_RANGE", "period_end precedes period_start")
    # Priority 22: period length
    if (period_end - period_start).days + 1 != m["period_days"]:
        raise h.ApiError("ERR_INVALID_PERIOD_LENGTH", "period length mismatch")
    # Priority 23: non-overlap with existing invoices of same membership
    for inv in S.invoices.values():
        if inv["membership_id"] != membership_id:
            continue
        ps = h.parse_date(inv["period_start"])
        pe = h.parse_date(inv["period_end"])
        if period_start <= pe and ps <= period_end:
            raise h.ApiError("ERR_INVOICE_PERIOD_OVERLAP", "period overlaps an existing invoice")

    subtotal, occ, base, util = d.period_subtotal_cents(m, period_start)
    invoice = h.new_common()
    invoice.update({
        "membership_id": membership_id,
        "period_start": b["period_start"],
        "period_end": b["period_end"],
        "due_date": b["period_start"],
        "occupied_rooms_at_period_start": occ,
        "base_rent_cents": base,
        "utility_share_cents": util,
        "subtotal_cents": subtotal,
        "proration_adjustment_cents": 0,
        "late_fee_cents": 0,
        "total_amount_cents": subtotal,
        "amount_paid_cents": 0,
        "status": "OPEN",
    })
    S.invoices[invoice["id"]] = invoice
    d.recompute_balance(m)
    return h.ok(d.serialize(invoice), 201)


@bp.get("/co-living/invoices/<iid>")
def get_invoice(iid):
    h.authorize(*h.ROLES)
    inv = h.find_or_404(S.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    return h.ok(d.serialize(inv), 200)


@bp.get("/co-living/invoices")
def list_invoices():
    h.authorize(*h.ROLES)
    limit, offset = h.parse_pagination()
    membership_id = h.query_val("membership_id")
    status = h.query_val("status")
    rows = []
    for inv in S.invoices.values():
        if membership_id is not None and inv["membership_id"] != membership_id:
            continue
        if status is not None and inv["status"] != status:
            continue
        rows.append(inv)
    rows = h.sort_created(rows)
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def _auto_rescind(m):
    """NONPAYMENT notice auto-rescind: NOTICE_GIVEN -> ACTIVE and room back OCCUPIED."""
    m["notice_reason"] = None
    m["scheduled_move_out_date"] = None
    m["provisional_final_charge_cents"] = None
    m["effective_end_date"] = None
    m["tenancy_status"] = "ACTIVE"
    h.touch(m)
    room = S.rooms[m["room_id"]]
    room["occupancy_state"] = "OCCUPIED"
    room["available_from_date"] = None
    h.touch(room)
    d.eval_posture(S.houses[m["house_id"]])


@bp.post("/co-living/invoices/<iid>/payments")
def create_payment(iid):
    h.authorize("Member", "FinanceAdmin")
    inv = h.find_or_404(S.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    m = S.memberships[inv["membership_id"]]
    # Priority 4: ownership for Member
    if g.role == "Member" and m["member_id"] != g.user_id:
        raise h.ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own the tenancy")
    b = h.body()
    amount = h.req_int_pos(b, "amount_cents")
    method = h.req_enum(b, "method", _METHODS)
    # Priority 10: invoice payable
    if inv["status"] == "PAID":
        raise h.ApiError("ERR_INVOICE_NOT_PAYABLE", "invoice already PAID")
    # Priority 32: overpayment
    remainder = inv["total_amount_cents"] - inv["amount_paid_cents"]
    if amount > remainder:
        raise h.ApiError("ERR_OVERPAYMENT", "amount exceeds outstanding remainder")

    payment = h.new_ledger()
    payment.update({
        "invoice_id": iid,
        "amount_cents": amount,
        "method": method,
        "applied_at": h.fmt_instant(clock_dt()),
        "recorded_by_user_id": g.user_id,
    })
    S.payments[payment["id"]] = payment

    inv["amount_paid_cents"] += amount
    if amount == remainder:
        inv["status"] = "PAID"
    elif inv["status"] == "OPEN":
        inv["status"] = "PARTIAL"
    h.touch(inv)

    balance = d.recompute_balance(m)
    if m["billing_status"] == "PAST_DUE" and balance == 0:
        if m["tenancy_status"] == "MOVED_OUT":
            m["billing_status"] = "SETTLED"
            h.touch(m)
        else:
            m["billing_status"] = "CURRENT"
            h.touch(m)
            if m["tenancy_status"] == "NOTICE_GIVEN" and m["notice_reason"] == "NONPAYMENT":
                _auto_rescind(m)
        member = S.members.get(m["member_id"])
        if member is not None:
            d.recompute_member_standing(member)
    return h.ok(d.serialize(payment), 201)


@bp.get("/co-living/invoices/<iid>/payments")
def list_payments(iid):
    h.authorize(*h.ROLES)
    h.find_or_404(S.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    limit, offset = h.parse_pagination()
    rows = [p for p in S.payments.values() if p["invoice_id"] == iid]
    rows = sorted(rows, key=lambda p: (p["applied_at"], p["created_at"], p["_seq"]))
    page, pag = h.paginate(rows, limit, offset)
    return h.ok([d.serialize(x) for x in page], 200, "array", pag)


# ---------------------------------------------------------------------------
# Fee adjustment
# ---------------------------------------------------------------------------
@bp.post("/co-living/invoices/<iid>/fee-adjustment")
def fee_adjustment(iid):
    h.authorize("FinanceAdmin")
    inv = h.find_or_404(S.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    m = S.memberships[inv["membership_id"]]
    b = h.body()
    action = h.req_enum(b, "action", {"ASSESS", "WAIVE"})

    if action == "ASSESS":
        # Priority 25: grace window expired
        if clock_date() <= h.parse_date(inv["due_date"]) + timedelta(days=d.GRACE_DAYS):
            raise h.ApiError("ERR_LATE_FEE_NOT_DUE", "grace window not yet expired")
        # Priority 30: coherence
        if inv["late_fee_cents"] > 0:
            raise h.ApiError("ERR_LATE_FEE_ALREADY_ASSESSED", "late fee already assessed")
        if inv["status"] not in ("OPEN", "PARTIAL"):
            raise h.ApiError("ERR_LATE_FEE_ALREADY_ASSESSED", "invoice not assessable")
        fee = d.late_fee_for_subtotal(inv["subtotal_cents"])
        inv["late_fee_cents"] = fee
        inv["total_amount_cents"] += fee
        inv["status"] = "PAST_DUE"
        h.touch(inv)
        if m["billing_status"] != "SETTLED":
            m["billing_status"] = "PAST_DUE"
            h.touch(m)
        d.recompute_balance(m)
        return h.ok(d.serialize(inv), 200)

    # action == WAIVE
    # Priority 30: coherence
    if inv["late_fee_cents"] == 0:
        raise h.ApiError("ERR_NO_LATE_FEE_TO_WAIVE", "no late fee to waive")
    inv["total_amount_cents"] -= inv["late_fee_cents"]
    inv["late_fee_cents"] = 0
    # status stays PAST_DUE
    h.touch(inv)
    d.recompute_balance(m)
    return h.ok(d.serialize(inv), 200)
