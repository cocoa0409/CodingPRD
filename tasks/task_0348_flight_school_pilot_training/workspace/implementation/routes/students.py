"""Student, deposit, and deposit-transaction routes."""

from flask import Blueprint

import errors
from db import db, new_common, public, sorted_by_created
from errors import err
from middleware import (as_int, as_str, get_body, get_user_context,
                        parse_pagination, require_fields, require_role)
from response import list_success, success
from services import ledger
from services.common import find_or_404

bp = Blueprint("students", __name__)


def _serialize(student):
    return public(student)


@bp.post("/flight-school/students")
def create_student():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    require_fields(body, ["full_name", "email"])
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")

    record = new_common()
    record.update({
        "full_name": full_name,
        "email": email,
        "deposit_balance_cents": 0,
        "deposit_held_cents": 0,
        "deposit_consumed_cents": 0,
        "no_show_strikes": 0,
        "status": "ACTIVE",
    })
    db.students[record["id"]] = record
    return success(_serialize(record), status=201)


@bp.get("/flight-school/students")
def list_students():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher"})
    from flask import request
    limit, offset = parse_pagination()
    items = list(db.students.values())
    email = request.args.get("email")
    if email is not None:
        items = [s for s in items if s["email"] == email]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([_serialize(s) for s in page], limit, offset, total)


@bp.get("/flight-school/students/<student_id>")
def get_student(student_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student"})
    record = find_or_404(db.students, student_id)
    return success(_serialize(record))


@bp.post("/flight-school/students/<student_id>/deposits")
def add_deposit(student_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    student = find_or_404(db.students, student_id)
    body = get_body()
    require_fields(body, ["amount_cents"])
    amount = as_int(body, "amount_cents")
    if amount <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "amount_cents must be > 0.")
    memo = body.get("memo")
    if memo is not None and not isinstance(memo, str):
        raise err(errors.ERR_INVALID_REQUEST, "memo must be a string.")
    txn = ledger.deposit(student, amount, memo=memo)
    return success(public(txn), status=201)


@bp.get("/flight-school/deposit-transactions")
def list_deposit_transactions():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student"})
    from flask import request
    limit, offset = parse_pagination()
    items = list(db.deposit_transactions.values())
    for field in ("student_id", "booking_id", "flight_log_id"):
        val = request.args.get(field)
        if val is not None:
            items = [t for t in items if t.get(field) == val]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(t) for t in page], limit, offset, total)


@bp.get("/flight-school/deposit-transactions/<txn_id>")
def get_deposit_transaction(txn_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student"})
    record = find_or_404(db.deposit_transactions, txn_id)
    return success(public(record))
