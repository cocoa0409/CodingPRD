"""Ledger entries (PRD 3.5). Audit lines: id + created_at only (PRD 2.4)."""

from flask import Blueprint

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        require_member_ownership, new_audit_fields)
from validation import get_body, as_enum, as_int_range, as_num_range, as_date_str, present
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from services.serialize import ledger_entry_view

bp = Blueprint("ledger_entries", __name__)

ENTRY_KINDS = ("EXPENSE", "INCOME", "HOURS")
EDITABLE_BOOK_STATES = ("DRAFT", "RETURNED")


def _book_of(entry):
    return db.table("record_books").get(entry["record_book_id"])


def _owner_id_of_book(book):
    project = db.table("projects").get(book["project_id"]) if book else None
    return project["member_id"] if project else None


@bp.post("/ledger-entries")
def create_ledger_entry():
    role, user_id = authenticate(["Member"])
    body = get_body()
    # Priority 3: referenced identifiers exist (record_book_id).
    book = None
    if isinstance(body.get("record_book_id"), str):
        book = must_find("record_books", body["record_book_id"], "RecordBook")
    resolve_caller(role, user_id)
    # Priority 4: the member accumulates ledger lines on their own book only.
    if book is not None:
        require_member_ownership(user_id, _owner_id_of_book(book))
    # Priority 5: while the book is in DRAFT -- and again after a return --
    # the member accumulates ledger lines; once the book is under review or
    # beyond, the ledger is frozen (PRD 3.5).
    if book is not None and book["status"] not in EDITABLE_BOOK_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Ledger lines can only be added while the record book is DRAFT or RETURNED")
    # Priority 14: request shape.
    record_book_id = present(body, "record_book_id")
    if not isinstance(record_book_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'record_book_id': must be a string")
    if book is None:
        book = must_find("record_books", record_book_id, "RecordBook")
    entry_kind = as_enum(body, "entry_kind", ENTRY_KINDS)
    amount_cents = as_int_range(body, "amount_cents", lo=0)
    hours = as_num_range(body, "hours", lo=0)
    recorded_on = as_date_str(body, "recorded_on")
    rec = new_audit_fields()
    rec.update({
        "record_book_id": book["id"],
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "hours": hours,
        "entry_status": "POSTED",
        "recorded_on": recorded_on,
    })
    db.table("ledger_entries")[rec["id"]] = rec
    return response.success(ledger_entry_view(rec), status=201)


@bp.post("/ledger-entries/<eid>/void")
def void_ledger_entry(eid):
    role, user_id = authenticate(["Member"])
    rec = must_find("ledger_entries", eid, "LedgerEntry")
    resolve_caller(role, user_id)
    book = _book_of(rec)
    require_member_ownership(user_id, _owner_id_of_book(book))
    # Priority 5: only a POSTED line, and only while its record book is still
    # DRAFT or RETURNED; once the book is under review or beyond, the ledger
    # is frozen.
    if rec["entry_status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a POSTED ledger entry can be voided")
    if book is None or book["status"] not in EDITABLE_BOOK_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Ledger entries can only be voided while the record book is DRAFT or RETURNED")
    rec["entry_status"] = "VOIDED"
    return response.success(ledger_entry_view(rec))
