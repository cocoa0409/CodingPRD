"""I9Document CRUD."""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Dict, Optional

from ..audit import append_audit
from ..clock import format_date, format_datetime_ms, get_clock, parse_iso_date
from ..errors import err_not_found, err_validation
from ..store import get_store, new_id


_VALID_CATEGORY = {"LIST_A", "LIST_B", "LIST_C"}
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_iso_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        raise err_validation(f"{field} must be ISO-8601 date YYYY-MM-DD.")
    try:
        parse_iso_date(value)
    except Exception:
        raise err_validation(f"{field} is not a valid date.")
    return value


def create_document(emp_id: str, body: Dict[str, Any], actor_user_id: str, actor_role: str) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")
    store = get_store()
    clock = get_clock()
    with store.lock:
        emp = store.employees.get(emp_id)
        if emp is None:
            raise err_not_found("Employee not found.")

        category = body.get("category")
        if category not in _VALID_CATEGORY:
            raise err_validation("category must be one of LIST_A, LIST_B, LIST_C.")
        title = body.get("document_title")
        if not isinstance(title, str) or not title.strip():
            raise err_validation("document_title required.")
        number = body.get("document_number")
        if not isinstance(number, str) or not number.strip():
            raise err_validation("document_number required.")
        authority = body.get("issuing_authority")
        if not isinstance(authority, str) or not authority.strip():
            raise err_validation("issuing_authority required.")

        expiration_date = body.get("expiration_date")
        if expiration_date is not None:
            _validate_iso_date(expiration_date, "expiration_date")

        receipt = bool(body.get("receipt", False))
        receipt_resolution_due = None
        if receipt:
            start_date = parse_iso_date(emp["start_date"])
            receipt_resolution_due = format_date(start_date + timedelta(days=90))

        now_iso = format_datetime_ms(clock.get())
        doc_id = new_id()
        row = {
            "id": doc_id,
            "employee_id": emp_id,
            "category": category,
            "document_title": title.strip(),
            "document_number": number.strip(),
            "issuing_authority": authority.strip(),
            "expiration_date": expiration_date,
            "receipt": receipt,
            "receipt_resolution_due": receipt_resolution_due,
            "created_at": now_iso,
            "_seq": store.next_seq(),
        }
        store.i9_documents[doc_id] = row

        append_audit(
            subject_employee_id=emp_id,
            subject_entity="I9_DOCUMENT",
            subject_entity_id=doc_id,
            action="DOC_REGISTERED",
            actor_role=actor_role,
            actor_user_id=actor_user_id,
        )

    return row


def list_documents(emp_id: str, filters: Dict[str, Any]) -> list:
    store = get_store()
    if emp_id not in store.employees:
        raise err_not_found("Employee not found.")
    items = [d for d in store.i9_documents.values() if d["employee_id"] == emp_id]
    cat = filters.get("category")
    if cat is not None:
        if cat not in _VALID_CATEGORY:
            items = []
        else:
            items = [d for d in items if d["category"] == cat]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return items
