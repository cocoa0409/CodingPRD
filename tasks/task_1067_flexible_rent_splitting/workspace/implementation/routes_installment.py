from flask import Blueprint
from core import (db, ApiError, auth, caller, body, ok, base_full, touch,
                  as_int, as_enum, clock_iso, add_days_iso)
from domain import append_ledger, cycle_installments, recompute_repaid
import serial
import calc

bp = Blueprint("installment", __name__)

SUCCESS_OUTCOMES = {"SUCCEED", "SUCCESS", "SUCCEEDED", "PAID"}
FAIL_OUTCOMES = {"FAIL", "FAILURE", "FAILED", "DECLINE", "DECLINED"}


def get_installment_or_404(iid):
    i = db.installments.get(iid)
    if i is None:
        raise ApiError("ERR_INSTALLMENT_NOT_FOUND", 404, "Installment not found.")
    return i


def owning_cycle(inst):
    return db.billing_cycles.get(inst["cycle_id"])


def check_owner(inst):
    uid, role = caller()
    if role == "Renter":
        cyc = owning_cycle(inst)
        if cyc is None or cyc["renter_id"] != uid:
            raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your installment.")


@bp.get("/api/installments/<iid>")
@auth("PlatformAdmin", "Renter")
def get_installment(iid):
    i = get_installment_or_404(iid)
    check_owner(i)
    return ok(serial.installment_out(i))


@bp.post("/api/installments/<iid>/charge")
@auth("Renter", "PlatformAdmin")
def charge(iid):
    b = body()
    method = as_enum(b, "method", {"MANUAL", "AUTOPAY"})
    outcome = b.get("outcome")
    i = get_installment_or_404(iid)
    check_owner(i)
    cyc = owning_cycle(i)

    # state
    if cyc["status"] not in ("REMITTED", "DELINQUENT") or i["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Installment cannot be charged.")
    # max attempts
    if i["attempt_count"] >= calc.MAX_ATTEMPTS:
        raise ApiError("ERR_MAX_ATTEMPTS_EXCEEDED", 409, "Attempt ceiling reached.")
    # autopay
    if method == "AUTOPAY":
        active = any(m["renter_id"] == cyc["renter_id"] and m["status"] == "ACTIVE"
                     for m in db.autopay_mandates.values())
        if not active:
            raise ApiError("ERR_AUTOPAY_NOT_ACTIVE", 409, "Autopay mandate not ACTIVE.")

    failed = outcome is not None and str(outcome).upper() in FAIL_OUTCOMES
    i["attempt_count"] += 1
    if failed:
        i["status"] = "FAILED"
        touch(i)
    else:
        i["status"] = "PAID"
        i["paid_at"] = clock_iso()
        touch(i)
        append_ledger(cyc["id"], "REPAYMENT", -i["amount_cents"], "Installment repayment")
        recompute_repaid(cyc)
        touch(cyc)
    return ok(serial.installment_out(i))


@bp.post("/api/installments/<iid>/retry")
@auth("Renter", "PlatformAdmin")
def retry(iid):
    i = get_installment_or_404(iid)
    check_owner(i)
    if i["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Installment is not FAILED.")
    if i["attempt_count"] >= calc.MAX_ATTEMPTS:
        raise ApiError("ERR_MAX_ATTEMPTS_EXCEEDED", 409, "Attempt ceiling reached.")
    i["status"] = "SCHEDULED"
    touch(i)
    return ok(serial.installment_out(i))


@bp.post("/api/installments/<iid>/defer")
@auth("Renter", "PlatformAdmin")
def defer(iid):
    b = body()
    new_offset = as_int(b, "new_due_offset_days")
    i = get_installment_or_404(iid)
    check_owner(i)
    cyc = owning_cycle(i)
    if i["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Installment is not SCHEDULED.")
    if not (1 <= new_offset <= calc.MAX_DEFER_DAYS):
        raise ApiError("ERR_DEFER_WINDOW_EXCEEDED", 422, "defer window exceeded.")

    amount = i["amount_cents"]
    i["status"] = "CANCELLED"
    touch(i)

    max_seq = max((x["sequence_no"] for x in cycle_installments(cyc["id"])), default=0)
    rec = base_full()
    rec.update({
        "cycle_id": cyc["id"],
        "sequence_no": max_seq + 1,
        "due_date": add_days_iso(cyc["cycle_start_date"], new_offset),
        "amount_cents": amount,
        "kind": "DEFERRED",
        "attempt_count": 0,
        "paid_at": None,
        "status": "SCHEDULED",
    })
    db.installments[rec["id"]] = rec
    recompute_repaid(cyc)
    touch(cyc)
    return ok(serial.installment_out(rec))
