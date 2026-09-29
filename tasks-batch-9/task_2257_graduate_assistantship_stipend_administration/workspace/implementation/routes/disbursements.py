"""Stipend disbursements: payment, reversal and the ledger movements they cause."""
from flask import Blueprint

import serialize
import validate as v
from db import db, update, force_update, now_iso
from errors import ApiError
from middleware import authenticate
from response import ok, ok_list
from services import effects, queries

bp = Blueprint("disbursements", __name__)

DISBURSEMENT_STATUSES = ("SCHEDULED", "PAID", "VOIDED", "REVERSED")

READ_ROLES = ["GradSchoolAdmin", "DepartmentAdmin", "GrantAccountant"]


def _period_of(disbursement):
    return db.pay_periods.get(disbursement["pay_period_id"])


def _sequence_key(disbursement):
    period = _period_of(disbursement)
    sequence = period["sequence_no"] if period else 0
    return (sequence, disbursement["_seq"])


@bp.get("/stipend-disbursements/<disbursement_id>")
def read_disbursement(disbursement_id):
    authenticate(READ_ROLES)
    disbursement = queries.disbursement_or_404(disbursement_id)
    return ok(serialize.disbursement(disbursement))


@bp.get("/stipend-disbursements")
def list_disbursements():
    authenticate(READ_ROLES)
    appointment_id = v.query_str("appointment_id")
    pay_period_id = v.query_str("pay_period_id")
    status = v.query_enum("status", DISBURSEMENT_STATUSES)
    rows = list(db.stipend_disbursements.values())
    if appointment_id:
        rows = [r for r in rows if r["appointment_id"] == appointment_id]
    if pay_period_id:
        rows = [r for r in rows if r["pay_period_id"] == pay_period_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, meta = v.paginate(sorted(rows, key=_sequence_key))
    return ok_list([serialize.disbursement(r) for r in page], meta)


@bp.post("/stipend-disbursements/<disbursement_id>/pay")
def pay_disbursement(disbursement_id):
    authenticate(["GradSchoolAdmin"])
    disbursement = queries.disbursement_or_404(disbursement_id)

    if disbursement["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_DISBURSEMENT_STATE",
                       "Only a SCHEDULED disbursement may be paid, not %s"
                       % disbursement["status"])
    period = _period_of(disbursement)
    if period is None or period["status"] != "LOCKED":
        raise ApiError("ERR_PAY_PERIOD_NOT_LOCKED",
                       "The disbursement's pay period must be LOCKED to pay")
    appointment = db.appointments.get(disbursement["appointment_id"])
    if appointment is None or appointment["payroll_status"] not in (
            "SCHEDULED", "PARTIALLY_DISBURSED"):
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                       "The appointment's payroll_status does not permit payment")

    update(disbursement, status="PAID", paid_at=now_iso())

    touched = []
    for element in disbursement["allocation_split"]:
        allocation = db.funding_allocations.get(element["funding_allocation_id"])
        if allocation is None:
            continue
        update(allocation,
               disbursed_amount_cents=(allocation["disbursed_amount_cents"]
                                       + element["amount_cents"]))
        touched.append(allocation["funding_source_id"])
    effects.recompute_source_balances(touched)

    remaining = [d for d in queries.disbursements_of_appointment(appointment["id"])
                 if d["status"] == "SCHEDULED"]
    force_update(appointment,
                 payroll_status="PARTIALLY_DISBURSED" if remaining else "FULLY_DISBURSED")
    return ok(serialize.disbursement(disbursement))


@bp.post("/stipend-disbursements/<disbursement_id>/reverse")
def reverse_disbursement(disbursement_id):
    authenticate(["GradSchoolAdmin"])
    disbursement = queries.disbursement_or_404(disbursement_id)
    body = v.body_dict()
    reversal_reason = v.field_str(body, "reversal_reason")

    if disbursement["status"] != "PAID":
        raise ApiError("ERR_INVALID_DISBURSEMENT_STATE",
                       "Only a PAID disbursement may be reversed, not %s"
                       % disbursement["status"])
    period = _period_of(disbursement)
    term = db.academic_terms.get(period["term_id"]) if period else None
    if term is None or term["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_TERM_STATE",
                       "A disbursement cannot be reversed once the term is CLOSED")

    update(disbursement, status="REVERSED", reversed_at=now_iso(),
           reversal_reason=reversal_reason)

    touched = []
    for element in disbursement["allocation_split"]:
        allocation = db.funding_allocations.get(element["funding_allocation_id"])
        if allocation is None:
            continue
        update(allocation,
               disbursed_amount_cents=(allocation["disbursed_amount_cents"]
                                       - element["amount_cents"]))
        touched.append(allocation["funding_source_id"])
    effects.recompute_source_balances(touched)

    appointment = db.appointments.get(disbursement["appointment_id"])
    if appointment is not None:
        paid = [d for d in queries.disbursements_of_appointment(appointment["id"])
                if d["status"] == "PAID"]
        force_update(appointment,
                     payroll_status="PARTIALLY_DISBURSED" if paid else "SCHEDULED")
    return ok(serialize.disbursement(disbursement))
