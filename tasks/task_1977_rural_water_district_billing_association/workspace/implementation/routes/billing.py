"""Billing cycles, meter readings, invoices, payments, reserve entries."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import (ALL_ROLES, body, get_district, get_scoped, opt_enum,
                        req_dt, req_int, req_str, require_roles)
from response import ok_list, ok_object, paginate
from services import (delinquency_cascade, escalate_invoice, final_loss,
                      invoice_amounts, invoice_dpd, monthly_deposit_cents,
                      new_common, new_ledger, post_reserve_entry,
                      provisional_loss, recompute_reserve, ser_cycle,
                      ser_invoice, ser_master, ser_payment, ser_reading,
                      ser_reserve_entry, touch, bump_district,
                      NOTICE_DAY_THRESHOLD)

bp = Blueprint("billing", __name__)

READING_TYPES = ["ACTUAL", "ESTIMATED", "FINAL_OFF"]
BILLABLE_TAP = ("INSTALLED", "RECONNECTED")


def get_cycle(district_id, cycle_id):
    return get_scoped(db.billing_cycles, cycle_id, district_id, "ERR_CYCLE_NOT_FOUND", "BillingCycle")


def get_invoice(district_id, invoice_id):
    return get_scoped(db.invoices, invoice_id, district_id, "ERR_INVOICE_NOT_FOUND", "Invoice")


def latest_reading(tap_id):
    rs = [r for r in db.readings.values() if r["tap_id"] == tap_id]
    if not rs:
        return None
    rs.sort(key=lambda r: r["_seq"])
    return rs[-1]


def regular_reading(tap_id, cycle_id):
    """The tap's accepted non-FINAL_OFF reading for the cycle, if any."""
    for r in db.readings.values():
        if r["tap_id"] == tap_id and r["cycle_id"] == cycle_id and r["reading_type"] != "FINAL_OFF":
            return r
    return None


def any_reading(tap_id, cycle_id):
    for r in db.readings.values():
        if r["tap_id"] == tap_id and r["cycle_id"] == cycle_id:
            return r
    return None


# ----------------------------------------------------------- billing cycles

@bp.post("/districts/<district_id>/billing-cycles")
@require_roles(["BillingClerk"])
def create_cycle(user_id, role, district_id):
    b = body()
    ps_raw, ps = req_dt(b, "period_start_utc")
    pe_raw, pe = req_dt(b, "period_end_utc")
    dd_raw, dd = req_dt(b, "due_date_utc")
    d = get_district(district_id)
    valid = pe > ps and dd >= pe
    if valid:
        closed_ends = [c["_pe_dt"] for c in db.billing_cycles.values()
                       if c["district_id"] == d["id"] and c["status"] == "CLOSED"]
        if closed_ends and ps < max(closed_ends):
            valid = False
    if not valid:
        raise ApiError("ERR_CYCLE_WINDOW_INVALID", 422,
                       "Cycle window malformed or overlapping a prior CLOSED cycle")
    c = new_common()
    c.update({
        "district_id": d["id"],
        "cycle_index": d["current_billing_epoch"] + 1,
        "period_start_utc": ps_raw,
        "period_end_utc": pe_raw,
        "due_date_utc": dd_raw,
        "status": "OPEN",
        "provisional_loss_pct": None,
        "final_loss_pct": None,
        "_ps_dt": ps, "_pe_dt": pe, "_due_dt": dd,
        "_billed_by": None,
    })
    db.billing_cycles[c["id"]] = c
    return ok_object(ser_cycle(c), 201)


@bp.get("/districts/<district_id>/billing-cycles")
@require_roles(ALL_ROLES)
def list_cycles(user_id, role, district_id):
    d = get_district(district_id)
    items = [c for c in db.billing_cycles.values() if c["district_id"] == d["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_cycle(c) for c in page], limit, offset, total)


@bp.get("/districts/<district_id>/billing-cycles/<cycle_id>")
@require_roles(ALL_ROLES)
def get_cycle_by_id(user_id, role, district_id, cycle_id):
    d = get_district(district_id)
    return ok_object(ser_cycle(get_cycle(d["id"], cycle_id)))


@bp.post("/districts/<district_id>/billing-cycles/<cycle_id>/mark-readings-complete")
@require_roles(["BillingClerk"])
def mark_readings_complete(user_id, role, district_id, cycle_id):
    d = get_district(district_id)
    c = get_cycle(d["id"], cycle_id)
    if c["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, "Operation requires the cycle to be OPEN")
    for t in db.taps.values():
        if t["district_id"] == d["id"] and t["status"] in BILLABLE_TAP:
            if regular_reading(t["id"], c["id"]) is None:
                raise ApiError("ERR_MISSING_METER_READINGS", 409,
                               "Some INSTALLED/RECONNECTED tap lacks a reading this cycle")
    c["status"] = "READINGS_COMPLETE"
    touch(c)
    return ok_object(ser_cycle(c))


@bp.post("/districts/<district_id>/billing-cycles/<cycle_id>/bill")
@require_roles(["BillingClerk"])
def bill_cycle(user_id, role, district_id, cycle_id):
    d = get_district(district_id)
    c = get_cycle(d["id"], cycle_id)
    if c["status"] != "READINGS_COMPLETE":
        raise ApiError("ERR_CYCLE_NOT_READINGS_COMPLETE", 409,
                       "Billing requires the cycle to be READINGS_COMPLETE")
    if d.get("active_rate_schedule_id") is None:
        raise ApiError("ERR_NO_ACTIVE_RATE_SCHEDULE", 409,
                       "Billing requires an ADOPTED rate schedule")
    sched = db.rate_schedules[d["active_rate_schedule_id"]]
    # One invoice per tapped member: every INSTALLED/RECONNECTED tap bills from
    # its accepted reading; a DISCONNECTED tap bills the minimum only when a
    # reading was accepted for it this cycle.
    for t in db.taps.values():
        if t["district_id"] != d["id"]:
            continue
        if t["status"] in BILLABLE_TAP:
            reading = regular_reading(t["id"], c["id"]) or any_reading(t["id"], c["id"])
            if reading is None:
                continue
            usage = reading["usage_gallons"]
            reconnect = sched["reconnect_fee_cents"] if t.get("_pending_reconnect_fee") else 0
            usage_charge, minimum, reconnect, total = invoice_amounts(usage, sched, reconnect)
            t["_pending_reconnect_fee"] = False
        elif t["status"] == "DISCONNECTED":
            reading = any_reading(t["id"], c["id"])
            if reading is None:
                continue
            usage = reading["usage_gallons"]
            usage_charge, minimum, reconnect, total = 0, sched["base_minimum_cents"], 0, sched["base_minimum_cents"]
        else:
            continue
        inv = new_common()
        inv.update({
            "district_id": d["id"],
            "member_id": t["member_id"],
            "tap_id": t["id"],
            "cycle_id": c["id"],
            "rate_schedule_id": sched["id"],
            "usage_gallons": usage,
            "usage_charge_cents": usage_charge,
            "minimum_charge_cents": minimum,
            "reconnect_fee_cents": reconnect,
            "total_cents": total,
            "amount_paid_cents": 0,
            "billing_status": "ISSUED",
            "collection_status": "CURRENT",
            "_dpd_frozen": None,
            "_paid_at_dt": None,
            "_notice_issued": False,
        })
        db.invoices[inv["id"]] = inv
    c["provisional_loss_pct"] = provisional_loss(c["id"])
    c["status"] = "BILLED"
    c["_billed_by"] = user_id
    touch(c)
    # Delinquency aging: every still-unpaid invoice from prior cycles advances
    # per the escalation rules against the logical clock.
    delinquency_cascade(d["id"], exclude_cycle_id=c["id"])
    bump_district(d)
    return ok_object(ser_cycle(c))


@bp.post("/districts/<district_id>/billing-cycles/<cycle_id>/close")
@require_roles(["Treasurer"])
def close_cycle(user_id, role, district_id, cycle_id):
    b = body()
    expected = b.get("expected_district_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field 'expected_district_version' is required and must be an integer")
    d = get_district(district_id)
    c = get_cycle(d["id"], cycle_id)
    if c["status"] != "BILLED":
        raise ApiError("ERR_CYCLE_NOT_BILLED", 409, "Close requires the cycle to be BILLED")
    if expected != d["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_district_version does not match the district's current version")
    masters = [m for m in db.master_readings.values() if m["cycle_id"] == c["id"]]
    if len(masters) != 1:
        raise ApiError("ERR_MASTER_READING_REQUIRED", 409,
                       "Cycle close requires exactly one MasterMeterReading")
    # Final reconciliation loss (chronological; FINAL_OFF replaces earlier).
    c["final_loss_pct"], _sold = final_loss(c["id"], masters[0]["master_gallons"])
    # Monthly reserve deposit: ceil(annual debt service / 120).
    post_reserve_entry(d["id"], "MONTHLY_DEPOSIT", monthly_deposit_cents(d), c["id"])
    # Forfeited member credits surface as positive ANNUAL_TRUE_UP entries.
    forfeited = d.pop("_forfeited_credits", [])
    for amount in forfeited:
        post_reserve_entry(d["id"], "ANNUAL_TRUE_UP", amount, c["id"])
    recompute_reserve(d)
    d["current_billing_epoch"] += 1
    # Walk members: reset the streak when this cycle's invoice(s) were fully
    # paid by the due date; otherwise increment.
    member_invoices = {}
    for inv in db.invoices.values():
        if inv["district_id"] == d["id"] and inv["cycle_id"] == c["id"] and inv["billing_status"] != "VOID":
            member_invoices.setdefault(inv["member_id"], []).append(inv)
    for mid, invs in member_invoices.items():
        m = db.members.get(mid)
        if m is None:
            continue
        ok_all = all(
            inv["billing_status"] == "PAID"
            and inv.get("_paid_at_dt") is not None
            and inv["_paid_at_dt"] <= c["_due_dt"]
            for inv in invs
        )
        m["consecutive_delinquent_cycles"] = 0 if ok_all else m["consecutive_delinquent_cycles"] + 1
        touch(m)
    c["status"] = "CLOSED"
    touch(c)
    bump_district(d)
    return ok_object(ser_cycle(c))


# ------------------------------------------------------------ meter readings

@bp.post("/districts/<district_id>/meter-readings")
@require_roles(["FieldOperator"])
def create_reading(user_id, role, district_id):
    b = body()
    tap_id = req_str(b, "tap_id")
    cycle_id = req_str(b, "cycle_id")
    gallons = req_int(b, "reading_gallons", minimum=0)
    rtype = opt_enum(b, "reading_type", READING_TYPES, "ACTUAL")
    d = get_district(district_id)
    t = get_scoped(db.taps, tap_id, d["id"], "ERR_TAP_NOT_FOUND", "TapConnection")
    c = get_scoped(db.billing_cycles, cycle_id, d["id"], "ERR_CYCLE_NOT_FOUND", "BillingCycle")
    prior = latest_reading(t["id"])
    if prior is not None and gallons < prior["reading_gallons"]:
        raise ApiError("ERR_READING_REGRESSION", 422,
                       "reading_gallons is below the tap's latest accepted cumulative register")
    existing = [r for r in db.readings.values()
                if r["tap_id"] == t["id"] and r["cycle_id"] == c["id"]]
    if rtype == "FINAL_OFF":
        # A FINAL_OFF reading may land between bill and close and replaces the
        # tap's earlier reading for the cycle; a second FINAL_OFF duplicates.
        if any(r["reading_type"] == "FINAL_OFF" for r in existing):
            raise ApiError("ERR_DUPLICATE_READING", 409,
                           "Tap already has an accepted reading for this cycle")
    elif existing:
        raise ApiError("ERR_DUPLICATE_READING", 409,
                       "Tap already has an accepted reading for this cycle")
    usage = gallons - (prior["reading_gallons"] if prior else 0)
    r = new_ledger()
    r.update({
        "district_id": d["id"],
        "tap_id": t["id"],
        "cycle_id": c["id"],
        "reading_gallons": gallons,
        "reading_type": rtype,
        "usage_gallons": usage,
    })
    db.readings[r["id"]] = r
    return ok_object(ser_reading(r), 201)


@bp.get("/districts/<district_id>/meter-readings")
@require_roles(ALL_ROLES)
def list_readings(user_id, role, district_id):
    d = get_district(district_id)
    items = [r for r in db.readings.values() if r["district_id"] == d["id"]]
    tid = request.args.get("tap_id")
    if tid is not None:
        items = [r for r in items if r["tap_id"] == tid]
    cid = request.args.get("cycle_id")
    if cid is not None:
        items = [r for r in items if r["cycle_id"] == cid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_reading(r) for r in page], limit, offset, total)


# --------------------------------------------------------- master readings

@bp.post("/districts/<district_id>/master-meter-readings")
@require_roles(["FieldOperator"])
def create_master(user_id, role, district_id):
    b = body()
    cycle_id = req_str(b, "cycle_id")
    gallons = req_int(b, "master_gallons", minimum=0)
    d = get_district(district_id)
    c = get_scoped(db.billing_cycles, cycle_id, d["id"], "ERR_CYCLE_NOT_FOUND", "BillingCycle")
    r = new_ledger()
    r.update({
        "district_id": d["id"],
        "cycle_id": c["id"],
        "master_gallons": gallons,
    })
    db.master_readings[r["id"]] = r
    return ok_object(ser_master(r), 201)


@bp.get("/districts/<district_id>/master-meter-readings")
@require_roles(ALL_ROLES)
def list_masters(user_id, role, district_id):
    d = get_district(district_id)
    items = [r for r in db.master_readings.values() if r["district_id"] == d["id"]]
    cid = request.args.get("cycle_id")
    if cid is not None:
        items = [r for r in items if r["cycle_id"] == cid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_master(r) for r in page], limit, offset, total)


# ----------------------------------------------------------------- invoices

@bp.get("/districts/<district_id>/invoices")
@require_roles(ALL_ROLES)
def list_invoices(user_id, role, district_id):
    d = get_district(district_id)
    items = [i for i in db.invoices.values() if i["district_id"] == d["id"]]
    mid = request.args.get("member_id")
    if mid is not None:
        items = [i for i in items if i["member_id"] == mid]
    cid = request.args.get("cycle_id")
    if cid is not None:
        items = [i for i in items if i["cycle_id"] == cid]
    bs = request.args.get("billing_status")
    if bs is not None:
        items = [i for i in items if i["billing_status"] == bs]
    cs = request.args.get("collection_status")
    if cs is not None:
        items = [i for i in items if i["collection_status"] == cs]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_invoice(i) for i in page], limit, offset, total)


@bp.get("/districts/<district_id>/invoices/<invoice_id>")
@require_roles(ALL_ROLES)
def get_invoice_by_id(user_id, role, district_id, invoice_id):
    d = get_district(district_id)
    return ok_object(ser_invoice(get_invoice(d["id"], invoice_id)))


@bp.post("/districts/<district_id>/invoices/<invoice_id>/issue-notice")
@require_roles(["BillingClerk"])
def issue_notice(user_id, role, district_id, invoice_id):
    d = get_district(district_id)
    inv = get_invoice(d["id"], invoice_id)
    # Explicit notice issuance re-evaluates escalation against the clock.
    escalate_invoice(inv, db.now_dt())
    dpd = invoice_dpd(inv)
    if inv["collection_status"] == "DELINQUENT" and dpd >= NOTICE_DAY_THRESHOLD:
        inv["collection_status"] = "NOTICED"
        inv["_notice_issued"] = True
        touch(inv)
        return ok_object(ser_invoice(inv))
    raise ApiError("ERR_INVALID_STATE", 409,
                   "Issue-notice requires a DELINQUENT invoice at least 10 days past due")


# ----------------------------------------------------------------- payments

@bp.post("/districts/<district_id>/payments")
@require_roles(["Treasurer"])
def create_payment(user_id, role, district_id):
    b = body()
    member_id = req_str(b, "member_id")
    invoice_id = req_str(b, "invoice_id")
    amount = req_int(b, "amount_cents", strict_minimum=1)
    d = get_district(district_id)
    m = get_scoped(db.members, member_id, d["id"], "ERR_MEMBER_NOT_FOUND", "Member")
    inv = get_invoice(d["id"], invoice_id)
    # Segregation of duties: the operator who billed the cycle may not collect
    # against its invoices.
    cycle = db.billing_cycles.get(inv["cycle_id"])
    if cycle is not None and cycle.get("_billed_by") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The same operator may not both bill a cycle and post a payment against its invoices")
    # Pinned waterfall: pre-existing credit absorbs first, then the tender.
    outstanding = inv["total_cents"] - inv["amount_paid_cents"]
    absorb = 0
    if m["credit_balance_cents"] > 0 and outstanding > 0:
        absorb = min(m["credit_balance_cents"], outstanding)
        m["credit_balance_cents"] -= absorb
    tender_applied = min(amount, outstanding - absorb)
    overpay = amount - tender_applied
    if overpay > 0:
        m["credit_balance_cents"] += overpay
    inv["amount_paid_cents"] += absorb + tender_applied
    if absorb > 0 or overpay > 0:
        touch(m)
    _update_invoice_after_payment(inv)
    p = new_common()
    p.update({
        "district_id": d["id"],
        "member_id": m["id"],
        "invoice_id": inv["id"],
        "amount_cents": amount,
        # PRD 3.7: applied_cents records the tender portion applied; the credit
        # absorb grows the invoice's applied total but is not part of it.
        "applied_cents": tender_applied,
        "status": "POSTED",
        "_absorb_cents": absorb,
        "_overpay_cents": overpay,
    })
    db.payments[p["id"]] = p
    return ok_object(ser_payment(p), 201)


def _update_invoice_after_payment(inv):
    if inv["amount_paid_cents"] >= inv["total_cents"]:
        was_unpaid = inv["billing_status"] != "PAID"
        inv["billing_status"] = "PAID"
        # Paying in full cures collection status from any non-terminal state.
        if inv["collection_status"] != "CURRENT":
            inv["collection_status"] = "CURRENT"
        if was_unpaid:
            inv["_paid_at_dt"] = db.now_dt()
            if inv["_dpd_frozen"] is None:
                inv["_dpd_frozen"] = invoice_dpd(inv)
    elif inv["amount_paid_cents"] > 0:
        inv["billing_status"] = "PARTIALLY_PAID"
    touch(inv)


@bp.get("/districts/<district_id>/payments")
@require_roles(ALL_ROLES)
def list_payments(user_id, role, district_id):
    d = get_district(district_id)
    items = [p for p in db.payments.values() if p["district_id"] == d["id"]]
    mid = request.args.get("member_id")
    if mid is not None:
        items = [p for p in items if p["member_id"] == mid]
    iid = request.args.get("invoice_id")
    if iid is not None:
        items = [p for p in items if p["invoice_id"] == iid]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_payment(p) for p in page], limit, offset, total)


@bp.post("/districts/<district_id>/payments/<payment_id>/reverse")
@require_roles(["Treasurer"])
def reverse_payment(user_id, role, district_id, payment_id):
    d = get_district(district_id)
    p = get_scoped(db.payments, payment_id, d["id"], "ERR_PAYMENT_NOT_FOUND", "Payment")
    if p["status"] != "POSTED":
        raise ApiError("ERR_PAYMENT_ALREADY_REVERSED", 409, "Payment has already been reversed")
    inv = db.invoices.get(p["invoice_id"])
    m = db.members.get(p["member_id"])
    if inv is not None:
        # The invoice's applied total grew by the credit absorb plus the tender
        # portion; reversal debits both legs back off.
        inv["amount_paid_cents"] -= p["applied_cents"] + p.get("_absorb_cents", 0)
        # Recompute billing status from what remains.
        if inv["amount_paid_cents"] >= inv["total_cents"]:
            inv["billing_status"] = "PAID"
        elif inv["amount_paid_cents"] > 0:
            inv["billing_status"] = "PARTIALLY_PAID"
            inv["_paid_at_dt"] = None
        else:
            inv["billing_status"] = "ISSUED"
            inv["_paid_at_dt"] = None
        if inv["billing_status"] != "PAID":
            inv["_dpd_frozen"] = None if inv["collection_status"] != "DISCONNECTED" else inv["_dpd_frozen"]
        touch(inv)
    if m is not None and p["_overpay_cents"] > 0:
        m["credit_balance_cents"] -= p["_overpay_cents"]
        touch(m)
    p["status"] = "REVERSED"
    touch(p)
    return ok_object(ser_payment(p))


# ------------------------------------------------------------ reserve ledger

@bp.get("/districts/<district_id>/reserve-entries")
@require_roles(["SystemAdmin", "BillingClerk", "Treasurer", "BoardDirector"])
def list_reserve_entries(user_id, role, district_id):
    d = get_district(district_id)
    items = [e for e in db.reserve_entries.values() if e["district_id"] == d["id"]]
    et = request.args.get("entry_type")
    if et is not None:
        items = [e for e in items if e["entry_type"] == et]
    cid = request.args.get("cycle_id")
    if cid is not None:
        items = [e for e in items if e["cycle_id"] == cid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_reserve_entry(e) for e in page], limit, offset, total)
