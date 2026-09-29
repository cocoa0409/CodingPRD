"""Authentication, RBAC and patient scoping (PRD 2.1, priorities 1, 2, 4, 5, 6)."""

from flask import request

import db
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate(allowed_roles):
    """Priority 1 then priority 2.  Returns (user_id, role)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if role is None or (isinstance(role, str) and role.strip() == ""):
        # The scaffold's auth rules name the role header; tolerate the shorter
        # spelling as a fallback while the PRD spelling stays authoritative.
        fallback = request.headers.get("X-Role")
        if fallback is not None and fallback.strip() != "":
            role = fallback
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# ------------------------------------------------------------------- existence

_NOT_FOUND = {
    "insurance_plan": "ERR_INSURANCE_PLAN_NOT_FOUND",
    "patient": "ERR_PATIENT_NOT_FOUND",
    "prescription": "ERR_PRESCRIPTION_NOT_FOUND",
    "fill_cycle": "ERR_FILL_CYCLE_NOT_FOUND",
    "cycle_line": "ERR_CYCLE_LINE_NOT_FOUND",
    "pouch_roll": "ERR_POUCH_ROLL_NOT_FOUND",
    "pouch": "ERR_POUCH_NOT_FOUND",
    "shipment": "ERR_SHIPMENT_NOT_FOUND",
    "refill_authorization": "ERR_REFILL_AUTHORIZATION_NOT_FOUND",
    "vacation_exception": "ERR_VACATION_EXCEPTION_NOT_FOUND",
    "credit_memo": "ERR_CREDIT_MEMO_NOT_FOUND",
    "adherence_event": "ERR_ADHERENCE_EVENT_NOT_FOUND",
}

_TABLES = {
    "insurance_plan": db.insurance_plans,
    "patient": db.patients,
    "prescription": db.prescriptions,
    "fill_cycle": db.fill_cycles,
    "cycle_line": db.cycle_lines,
    "pouch_roll": db.pouch_rolls,
    "pouch": db.pouches,
    "shipment": db.shipments,
    "refill_authorization": db.refill_authorizations,
    "vacation_exception": db.vacation_exceptions,
    "credit_memo": db.credit_memos,
    "adherence_event": db.adherence_events,
}


def not_found(kind):
    return ApiError(_NOT_FOUND[kind])


def lookup(kind, row_id):
    table = _TABLES[kind]
    if not isinstance(row_id, str) or row_id not in table:
        raise not_found(kind)
    return table[row_id]


# --------------------------------------------------------------------- scoping

def owning_patient_id(kind, row):
    """Walk the ownership edges to the owning patient identifier."""
    if kind == "patient":
        return row["id"]
    if kind in ("prescription", "fill_cycle", "vacation_exception", "credit_memo"):
        return row["patient_id"]
    if kind == "cycle_line":
        return db.fill_cycles[row["cycle_id"]]["patient_id"]
    if kind == "pouch_roll":
        return db.fill_cycles[row["cycle_id"]]["patient_id"]
    if kind == "pouch":
        roll = db.pouch_rolls[row["roll_id"]]
        return db.fill_cycles[roll["cycle_id"]]["patient_id"]
    if kind == "shipment":
        return db.fill_cycles[row["cycle_id"]]["patient_id"]
    if kind == "adherence_event":
        cycle = db.fill_cycles.get(row["cycle_id"])
        return cycle["patient_id"] if cycle else None
    if kind == "refill_authorization":
        return db.prescriptions[row["prescription_id"]]["patient_id"]
    return None


def enforce_scope(role, user_id, kind, row):
    """Priority 6.  Only meaningful for the Patient role."""
    if role != "Patient":
        return
    if owning_patient_id(kind, row) != user_id:
        raise ApiError("ERR_PATIENT_SCOPE_VIOLATION")


def enforce_patient_id_scope(role, user_id, patient_id):
    if role == "Patient" and patient_id != user_id:
        raise ApiError("ERR_PATIENT_SCOPE_VIOLATION")
