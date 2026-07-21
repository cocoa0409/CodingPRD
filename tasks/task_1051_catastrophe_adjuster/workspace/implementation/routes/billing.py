from decimal import Decimal

from flask import Blueprint, request

from core import (
    require_ctx, ALL_ROLES, get_body, require_fields, require_enum, require_str,
    require_int, respond_object, list_response, fetch, base_record, touch, DB,
    current_clock, iso, floor_dec, ApiError,
)

bp = Blueprint("billing", __name__)

CAT_PERILS = {"HURRICANE", "FLOOD", "WILDFIRE", "TORNADO"}
BILLING_METHODS = {"FEE_SCHEDULE", "TIME_AND_EXPENSE"}
PAYMENT_METHODS = {"ACH", "CHECK"}

FEE_SCHEDULE_INT_FIELDS = [
    "tier1_max_rcv_cents", "tier2_max_rcv_cents", "tier1_flat_fee_cents",
    "tier2_flat_fee_cents", "tier3_flat_fee_cents", "rcv_pct_bps",
    "pct_cap_cents", "hourly_rate_cents", "cat_peril_multiplier_bps",
]


# ---------------------------------------------------------------------------
# FeeSchedule
# ---------------------------------------------------------------------------
@bp.route("/fee-schedules", methods=["POST"])
def create_fee_schedule():
    require_ctx({"BillingManager"})
    body = get_body()
    require_fields(body, ["name"] + FEE_SCHEDULE_INT_FIELDS)
    require_str(body["name"], "name")
    for f in FEE_SCHEDULE_INT_FIELDS:
        require_int(body[f], f, minimum=0)
    rec = base_record()
    rec["name"] = body["name"]
    for f in FEE_SCHEDULE_INT_FIELDS:
        rec[f] = body[f]
    DB["fee_schedules"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/fee-schedules", methods=["GET"])
def list_fee_schedules():
    require_ctx(ALL_ROLES)
    return list_response("fee_schedules")


@bp.route("/fee-schedules/<rid>", methods=["GET"])
def get_fee_schedule(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("fee_schedules", rid, "ERR_FEE_SCHEDULE_NOT_FOUND"))


# ---------------------------------------------------------------------------
# FeeBill
# ---------------------------------------------------------------------------
def _assignment_time_entries(assignment_id):
    return [t for t in DB["time_entries"].values() if t["assignment_id"] == assignment_id]


def _compute_fee_bill(billing_method, claim, fs, assignment_id):
    if billing_method == "FEE_SCHEDULE":
        rcv = claim["rcv_cents"]
        if rcv <= fs["tier1_max_rcv_cents"]:
            flat = fs["tier1_flat_fee_cents"]
        elif rcv <= fs["tier2_max_rcv_cents"]:
            flat = fs["tier2_flat_fee_cents"]
        else:
            flat = fs["tier3_flat_fee_cents"]
        capped = min(rcv, fs["pct_cap_cents"])
        pct_component = (fs["rcv_pct_bps"] * capped) // 10000
        base = flat + pct_component
        if claim["peril_type"] in CAT_PERILS:
            subtotal = (base * fs["cat_peril_multiplier_bps"]) // 10000
        else:
            subtotal = base
        total = subtotal
        return subtotal, total
    # TIME_AND_EXPENSE
    entries = _assignment_time_entries(assignment_id)
    sum_hours = sum((Decimal(str(t["hours"])) for t in entries), Decimal(0))
    labor = floor_dec(sum_hours * Decimal(fs["hourly_rate_cents"]))
    subtotal = labor
    total = labor + sum(t["expense_cents"] for t in entries)
    return subtotal, total


def _supersede_prior_bills(assignment_id, claim):
    """Void any prior non-PAID (non-terminal) bill for the assignment,
    compensating the reserve/billing dimension if it had debited."""
    for fb in DB["fee_bills"].values():
        if fb["assignment_id"] != assignment_id:
            continue
        if fb["status"] in {"DRAFT", "SUBMITTED", "APPROVED"}:
            if fb["status"] in {"SUBMITTED", "APPROVED"}:
                claim["reserve_consumed_cents"] -= fb["total_cents"]
                touch(claim)
                DB["assignments"][assignment_id]["billing_status"] = "NOT_BILLED"
            fb["status"] = "VOID"
            touch(fb)


@bp.route("/fee-bills", methods=["POST"])
def create_fee_bill():
    require_ctx({"FieldAdjuster"})
    body = get_body()
    require_fields(body, ["assignment_id", "claim_id", "fee_schedule_id",
                          "billing_method", "expected_assignment_version"])
    asn = fetch("assignments", body["assignment_id"], "ERR_ASSIGNMENT_NOT_FOUND")
    claim = fetch("claims", body["claim_id"], "ERR_CLAIM_NOT_FOUND")
    fs = fetch("fee_schedules", body["fee_schedule_id"], "ERR_FEE_SCHEDULE_NOT_FOUND")
    # OCC (priority 6) before business logic.
    expected = body["expected_assignment_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid expected_assignment_version")
    if expected != asn["version"]:
        raise ApiError("ERR_STALE_ASSIGNMENT_VERSION", 412)
    require_enum(body["billing_method"], BILLING_METHODS, "billing_method")
    billing_method = body["billing_method"]
    if billing_method == "TIME_AND_EXPENSE" and len(_assignment_time_entries(asn["id"])) == 0:
        raise ApiError("ERR_NO_TIME_ENTRIES", 422)

    old_version = asn["version"]
    _supersede_prior_bills(asn["id"], claim)
    # create mints a fresh DRAFT bill and increments Assignment.version by 1
    asn["version"] = old_version + 1
    asn["updated_at"] = iso(current_clock())

    subtotal, total = _compute_fee_bill(billing_method, claim, fs, asn["id"])
    rec = base_record()
    rec.update({
        "assignment_id": body["assignment_id"],
        "claim_id": body["claim_id"],
        "fee_schedule_id": body["fee_schedule_id"],
        "billing_method": billing_method,
        "expected_assignment_version": expected,
        "subtotal_cents": subtotal,
        "total_cents": total,
        "status": "DRAFT",
    })
    DB["fee_bills"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/fee-bills", methods=["GET"])
def list_fee_bills():
    require_ctx(ALL_ROLES)
    return list_response("fee_bills", {
        "assignment_id": request.args.get("assignment_id"),
        "claim_id": request.args.get("claim_id"),
        "fee_schedule_id": request.args.get("fee_schedule_id"),
        "status": request.args.get("status"),
    })


@bp.route("/fee-bills/<rid>", methods=["GET"])
def get_fee_bill(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("fee_bills", rid, "ERR_FEE_BILL_NOT_FOUND"))


@bp.route("/fee-bills/<rid>/submit", methods=["POST"])
def submit_fee_bill(rid):
    uid, role = require_ctx({"FieldAdjuster"})
    fb = fetch("fee_bills", rid, "ERR_FEE_BILL_NOT_FOUND")
    asn = DB["assignments"][fb["assignment_id"]]
    if uid != asn["adjuster_id"]:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER", 403)
    if fb["status"] != "DRAFT":
        raise ApiError("ERR_FEE_BILL_NOT_DRAFT", 409)
    if asn["work_status"] != "WORK_COMPLETE":
        raise ApiError("ERR_ASSIGNMENT_NOT_WORK_COMPLETE", 409)
    fb["status"] = "SUBMITTED"
    touch(fb)
    asn["billing_status"] = "BILLED"
    touch(asn)
    claim = DB["claims"][fb["claim_id"]]
    claim["reserve_consumed_cents"] += fb["total_cents"]
    touch(claim)
    return respond_object(fb)


@bp.route("/fee-bills/<rid>/approve", methods=["POST"])
def approve_fee_bill(rid):
    require_ctx({"BillingManager"})
    fb = fetch("fee_bills", rid, "ERR_FEE_BILL_NOT_FOUND")
    if fb["status"] != "SUBMITTED":
        raise ApiError("ERR_FEE_BILL_NOT_SUBMITTED", 409)
    fb["status"] = "APPROVED"
    touch(fb)
    return respond_object(fb)


def _reverse_reserve(fb):
    asn = DB["assignments"][fb["assignment_id"]]
    asn["billing_status"] = "NOT_BILLED"
    touch(asn)
    claim = DB["claims"][fb["claim_id"]]
    claim["reserve_consumed_cents"] -= fb["total_cents"]
    touch(claim)


@bp.route("/fee-bills/<rid>/reject", methods=["POST"])
def reject_fee_bill(rid):
    require_ctx({"BillingManager"})
    fb = fetch("fee_bills", rid, "ERR_FEE_BILL_NOT_FOUND")
    if fb["status"] != "SUBMITTED":
        raise ApiError("ERR_FEE_BILL_NOT_SUBMITTED", 409)
    fb["status"] = "REJECTED"
    touch(fb)
    _reverse_reserve(fb)
    return respond_object(fb)


@bp.route("/fee-bills/<rid>/void", methods=["POST"])
def void_fee_bill(rid):
    require_ctx({"BillingManager"})
    fb = fetch("fee_bills", rid, "ERR_FEE_BILL_NOT_FOUND")
    if fb["status"] not in {"DRAFT", "SUBMITTED", "APPROVED"}:
        raise ApiError("ERR_FEE_BILL_NOT_VOIDABLE", 409)
    had_debited = fb["status"] in {"SUBMITTED", "APPROVED"}
    fb["status"] = "VOID"
    touch(fb)
    if had_debited:
        _reverse_reserve(fb)
    return respond_object(fb)


@bp.route("/fee-bills/<rid>/pay", methods=["POST"])
def pay_fee_bill(rid):
    require_ctx({"BillingManager"})
    fb = fetch("fee_bills", rid, "ERR_FEE_BILL_NOT_FOUND")
    if fb["status"] != "APPROVED":
        raise ApiError("ERR_FEE_BILL_NOT_APPROVED", 409)
    body = get_body()
    method = body.get("method")
    require_enum(method, PAYMENT_METHODS, "method")
    fb["status"] = "PAID"
    touch(fb)
    # create immutable payment ledger row
    pay = base_record(with_version=False)
    pay.update({
        "fee_bill_id": fb["id"],
        "amount_cents": fb["total_cents"],
        "method": method,
        "paid_at": iso(current_clock()),
    })
    DB["payments"][pay["id"]] = pay
    # cascade hop 1: assignment billing BILLED -> PAID
    asn = DB["assignments"][fb["assignment_id"]]
    asn["billing_status"] = "PAID"
    touch(asn)
    # cascade hop 2: claim SETTLED -> CLOSED when all non-declined assignments PAID
    claim = DB["claims"][fb["claim_id"]]
    if claim["status"] == "SETTLED":
        relevant = [a for a in DB["assignments"].values()
                    if a["claim_id"] == claim["id"] and a["work_status"] != "DECLINED"]
        if relevant and all(a["billing_status"] == "PAID" for a in relevant):
            claim["status"] = "CLOSED"
            touch(claim)
    return respond_object(fb)


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
@bp.route("/payments", methods=["GET"])
def list_payments():
    require_ctx(ALL_ROLES)
    return list_response("payments", {
        "fee_bill_id": request.args.get("fee_bill_id"),
    })


@bp.route("/payments/<rid>", methods=["GET"])
def get_payment(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("payments", rid, "ERR_PAYMENT_NOT_FOUND"))
