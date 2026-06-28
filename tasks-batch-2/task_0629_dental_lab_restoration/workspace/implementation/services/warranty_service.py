"""RemakeRequest, CreditMemo void, Invoice pay (scaffold §1.2, PRD §3.6, §3.9)."""
import db
import errors
import lookups
from errors import err


def open_remake(case, unit, reason):
    """POST /cases/{id}/remake-requests (PRD §3.9).

    ERR_UNIT_NOT_WARRANTABLE: target unit must be PASSED on a DELIVERED case.
    """
    if unit["status"] != "PASSED" or case["status"] != "DELIVERED":
        raise err(errors.ERR_UNIT_NOT_WARRANTABLE,
                  "Unit is not PASSED on a DELIVERED case.")

    req = db.stamp_create({
        "id": db.new_id(),
        "case_id": case["id"],
        "fabrication_unit_id": unit["id"],
        "reason": reason,
        "status": "OPEN",
    })
    db.remake_requests[req["id"]] = req
    return req


def approve_remake(req):
    """POST /remake-requests/{id}/approve — OPEN -> APPROVED (PRD §3.9).

    Spawns a non-billable QUEUED replacement unit; replaced PASSED unit -> REMADE_OUT.
    """
    if req["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Remake request is not OPEN.")

    unit = db.fabrication_units[req["fabrication_unit_id"]]
    case = db.cases[req["case_id"]]

    # Preconditions: parent case DELIVERED, request targets a PASSED unit and is OPEN.
    if case["status"] != "DELIVERED" or unit["status"] != "PASSED":
        raise err(errors.ERR_INVALID_STATE,
                  "Approval requires a DELIVERED case and a PASSED targeted unit.")

    # Replaced unit -> REMADE_OUT.
    unit["status"] = "REMADE_OUT"
    db.touch(unit)

    # Spawn replacement: QUEUED, is_billable=false, remade_from_unit_id=replaced unit.
    replacement = db.stamp_create({
        "id": db.new_id(),
        "restoration_id": unit["restoration_id"],
        "remade_from_unit_id": unit["id"],
        "status": "QUEUED",
        "is_billable": False,
    })
    db.fabrication_units[replacement["id"]] = replacement

    req["status"] = "APPROVED"
    db.touch(req)
    return req


def deny_remake(req):
    """POST /remake-requests/{id}/deny — OPEN -> DENIED (PRD §3.9)."""
    if req["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Remake request is not OPEN.")
    req["status"] = "DENIED"
    db.touch(req)
    return req


def pay_invoice(inv):
    """POST /invoices/{id}/pay — billing_status ISSUED -> PAID (PRD §3.6)."""
    if inv["billing_status"] != "ISSUED":
        raise err(errors.ERR_INVALID_STATE, "Invoice billing_status is not ISSUED.")
    inv["billing_status"] = "PAID"
    db.touch(inv)
    return inv


def void_credit_memo(memo):
    """POST /credit-memos/{id}/void — ISSUED -> VOID; decrement doctor ledger (PRD §3.9)."""
    if memo["status"] != "ISSUED":
        raise err(errors.ERR_INVALID_STATE, "Credit memo is not ISSUED.")

    memo["status"] = "VOID"
    db.touch(memo)

    case = db.cases[memo["case_id"]]
    doctor = db.doctors[case["doctor_id"]]
    doctor["account_credit_cents"] -= memo["amount_cents"]
    db.touch(doctor)
    return memo
