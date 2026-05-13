"""MonthlyBill lifecycle: create, finalize, refund cascade, settle."""
from __future__ import annotations

import re
import threading

import db
from clock import iso, now
from errors import err
from services.audit import append_audit
from services.util import parse_dt, utc_month_start, utc_month_end_exclusive


_BILLING_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
_create_lock = threading.Lock()


def _bill_period(bill: dict):
    m = bill["billing_month"]
    y = int(m[0:4]); mo = int(m[5:7])
    return utc_month_start(y, mo), utc_month_end_exclusive(y, mo)


def _in_scope_reservations(bill: dict, include_cancelled: bool = False):
    """Return reservations in scope. By default excludes CANCELLED (which is the
    gross-aggregation rule). Set include_cancelled=True for terminal-state checks."""
    start, end_excl = _bill_period(bill)
    payer_scope = bill["payer_scope"]
    payer_id = bill["payer_id"]
    results = []
    for r in db.reservations.values():
        rs = db.run_sheets.get(r.get("run_sheet_id"))
        if not rs:
            continue
        sd = parse_dt(rs["scheduled_date"])
        if not (start <= sd < end_excl):
            continue
        if payer_scope == "EMPLOYEE":
            if r.get("employee_id") != payer_id:
                continue
            if r.get("payer_mode") != "SELF_PAY":
                continue
        else:  # DEPARTMENT
            if r.get("department_code") != payer_id:
                continue
            if r.get("payer_mode") != "DEPARTMENT_PAID":
                continue
        if not include_cancelled and r.get("status") not in ("COMPLETED", "NO_SHOW"):
            continue
        results.append(r)
    return results


def _all_in_scope_reservations_for_terminal_check(bill: dict):
    """Same as scope filter but returns ALL statuses; used to enforce
    BILL_HAS_OPEN_RESERVATIONS check."""
    start, end_excl = _bill_period(bill)
    payer_scope = bill["payer_scope"]
    payer_id = bill["payer_id"]
    results = []
    for r in db.reservations.values():
        rs = db.run_sheets.get(r.get("run_sheet_id"))
        if not rs:
            continue
        sd = parse_dt(rs["scheduled_date"])
        if not (start <= sd < end_excl):
            continue
        if payer_scope == "EMPLOYEE":
            if r.get("employee_id") != payer_id:
                continue
            if r.get("payer_mode") != "SELF_PAY":
                continue
        else:
            if r.get("department_code") != payer_id:
                continue
            if r.get("payer_mode") != "DEPARTMENT_PAID":
                continue
        results.append(r)
    return results


def create_bill(body: dict, actor_role: str, actor_id: str) -> dict:
    bm = body.get("billing_month")
    scope = body.get("payer_scope")
    pid = body.get("payer_id")

    if not isinstance(bm, str) or not _BILLING_MONTH_RE.match(bm):
        raise err("ERR_VALIDATION", "billing_month must be YYYY-MM")
    if scope not in ("EMPLOYEE", "DEPARTMENT"):
        raise err("ERR_VALIDATION", "payer_scope must be EMPLOYEE|DEPARTMENT")
    if not isinstance(pid, str) or not pid.strip():
        raise err("ERR_VALIDATION", "payer_id is required")

    with _create_lock:
        for b in db.monthly_bills.values():
            if b.get("payer_scope") == scope and b.get("payer_id") == pid \
                    and b.get("billing_month") == bm:
                raise err("ERR_BILL_ALREADY_EXISTS",
                          "Bill already exists for this (payer_scope, payer_id, billing_month)")

        bill = {
            "billing_month": bm,
            "payer_scope": scope,
            "payer_id": pid,
            "status": "DRAFT",
            "gross_cents": None,
            "refund_cents": 0,
            "net_cents": None,
            "line_count": None,
            "finalized_at": None,
        }
        db.stamp_create(bill)
        db.monthly_bills[bill["id"]] = bill
        return bill


def finalize_bill(bill: dict, actor_role: str, actor_id: str) -> dict:
    if bill.get("status") != "DRAFT":
        raise err("ERR_INVALID_STATE",
                  f"Cannot finalize a {bill.get('status')} bill")

    # billing_month strictly before current UTC month
    n = now()
    cur_month_start = utc_month_start(n.year, n.month)
    bill_start, _ = _bill_period(bill)
    if not (bill_start < cur_month_start):
        raise err("ERR_BILLING_MONTH_NOT_COMPLETE",
                  "billing_month must be strictly before the current UTC month")

    # All in-scope reservations must be terminal
    all_scope = _all_in_scope_reservations_for_terminal_check(bill)
    terminal = {"COMPLETED", "NO_SHOW", "CANCELLED"}
    for r in all_scope:
        if r.get("status") not in terminal:
            raise err("ERR_BILL_HAS_OPEN_RESERVATIONS",
                      f"Reservation {r['id']} is in non-terminal state {r.get('status')}")

    # Aggregate gross_cents and line_count
    in_scope = _in_scope_reservations(bill)
    gross = sum(int(r.get("fare_cents") or 0) for r in in_scope)
    bill["gross_cents"] = gross
    bill["line_count"] = len(in_scope)
    bill["finalized_at"] = iso(n)
    bill["status"] = "FINALIZED"
    db.stamp_update(bill)
    return bill


def refund_for_cancelled_reservation(res: dict, actor_role: str, actor_id: str) -> None:
    """If the cancelled reservation has already been rolled into a FINALIZED bill,
    increment refund_cents and transition to REFUNDED."""
    if res.get("status") != "CANCELLED":
        return
    if res.get("payer_mode") not in ("SELF_PAY", "DEPARTMENT_PAID"):
        return

    rs = db.run_sheets.get(res.get("run_sheet_id"))
    if not rs:
        return
    sd = parse_dt(rs["scheduled_date"])
    bm = f"{sd.year:04d}-{sd.month:02d}"
    payer_scope = "EMPLOYEE" if res["payer_mode"] == "SELF_PAY" else "DEPARTMENT"
    payer_id = res["employee_id"] if payer_scope == "EMPLOYEE" else res.get("department_code")
    if not payer_id:
        return

    bill = None
    for b in db.monthly_bills.values():
        if b.get("billing_month") == bm and b.get("payer_scope") == payer_scope \
                and b.get("payer_id") == payer_id:
            bill = b
            break
    if not bill:
        return
    if bill.get("status") not in ("FINALIZED", "REFUNDED"):
        return

    fare = int(res.get("fare_cents") or 0)
    bill["refund_cents"] = int(bill.get("refund_cents") or 0) + fare
    bill["status"] = "REFUNDED"
    db.stamp_update(bill)

    append_audit(
        event_type="BILL_REFUNDED",
        subject_type="MonthlyBill",
        subject_id=bill["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"reservation_id": res["id"], "refund_cents": fare},
    )


def settle_bill(bill: dict, actor_role: str, actor_id: str) -> dict:
    if bill.get("status") not in ("FINALIZED", "REFUNDED"):
        raise err("ERR_INVALID_STATE",
                  f"Cannot settle a {bill.get('status')} bill")
    bill["net_cents"] = int(bill.get("gross_cents") or 0) - int(bill.get("refund_cents") or 0)
    bill["status"] = "SETTLED"
    db.stamp_update(bill)
    return bill
