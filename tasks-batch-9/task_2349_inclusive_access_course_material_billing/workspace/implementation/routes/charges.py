"""StudentCharge and LedgerEntry reads."""

from flask import Blueprint

from auth import (ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_PROGRAM_ADMIN,
                  ROLE_REGISTRAR, ROLE_STUDENT, authenticate)
from domain import (charge_json, get_charge, get_ledger_entry, ledger_json,
                    ledger_of_charge, opt_out_json, opt_outs_of_charge)
from errors import fail
from response import apply_filters, object_response, paginate
from store import db, in_order

bp = Blueprint("charges", __name__)


def _owned(actor, charge):
    if actor.role == ROLE_STUDENT and actor.user_id != charge["student_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")


@bp.get("/charges/<charge_id>")
def read_charge(charge_id):
    actor = authenticate(ROLE_PROGRAM_ADMIN, ROLE_REGISTRAR, ROLE_BURSAR,
                         ROLE_COMPLIANCE, ROLE_STUDENT)
    charge = get_charge(charge_id)
    _owned(actor, charge)
    return object_response(charge_json(charge))


@bp.get("/charges")
def list_charges():
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_REGISTRAR, ROLE_BURSAR, ROLE_COMPLIANCE)
    items = apply_filters(in_order(db.charges.values()), [
        ("enrollment_id", "enrollment_id"),
        ("adoption_id", "adoption_id"),
        ("student_id", "student_id"),
        ("billing_status", "billing_status"),
        ("access_status", "access_status"),
    ])
    return paginate(items, charge_json)


@bp.get("/charges/<charge_id>/ledger-entries")
def list_charge_ledger(charge_id):
    actor = authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_STUDENT)
    charge = get_charge(charge_id)
    _owned(actor, charge)
    items = apply_filters(ledger_of_charge(charge["id"]), [("entry_type", "entry_type")])
    return paginate(items, ledger_json)


@bp.get("/charges/<charge_id>/opt-out-requests")
def list_charge_opt_outs(charge_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_STUDENT)
    charge = get_charge(charge_id)
    items = apply_filters(opt_outs_of_charge(charge["id"]), [("status", "status")])
    return paginate(items, opt_out_json)


@bp.get("/ledger-entries/<entry_id>")
def read_ledger_entry(entry_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE)
    return object_response(ledger_json(get_ledger_entry(entry_id)))


@bp.get("/ledger-entries")
def list_ledger_entries():
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE)
    items = apply_filters(in_order(db.ledger_entries.values()), [
        ("charge_id", "charge_id"),
        ("student_id", "student_id"),
        ("entry_type", "entry_type"),
        ("reason_code", "reason_code"),
    ])
    return paginate(items, ledger_json)
