"""Shared validation, lookup, touch, and pagination helpers."""

import re
from datetime import date as _date

from flask import request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_PROJECT_NOT_FOUND,
    ERR_SUBMITTAL_NOT_FOUND,
    ERR_SITE_VISIT_NOT_FOUND,
    ERR_FIELD_REPORT_NOT_FOUND,
    ERR_RFI_NOT_FOUND,
    ERR_CLARIFICATION_DRAWING_NOT_FOUND,
    ERR_PAYMENT_APPLICATION_NOT_FOUND,
    ERR_CHANGE_ORDER_NOT_FOUND,
    ERR_PUNCH_ITEM_NOT_FOUND,
    ERR_RECORD_DOCUMENT_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


# ---------- type / shape validators ----------

def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_str(v) -> bool:
    return isinstance(v, str)


def is_bool(v) -> bool:
    return isinstance(v, bool)


def is_date_str(v) -> bool:
    if not isinstance(v, str) or not _DATE_RE.match(v):
        return False
    try:
        _date.fromisoformat(v)
        return True
    except ValueError:
        return False


def is_ts_str(v) -> bool:
    if not isinstance(v, str) or not _TS_RE.match(v):
        return False
    try:
        db.LogicalClock._parse(v)
        return True
    except (ValueError, TypeError):
        return False


def invalid(msg: str):
    raise ApiError(ERR_INVALID_REQUEST, msg, 400)


def req_field(body: dict, name: str):
    if name not in body or body[name] is None:
        invalid(f"Missing required field: {name}")
    return body[name]


def req_str(body: dict, name: str) -> str:
    v = req_field(body, name)
    if not is_str(v):
        invalid(f"Field {name} must be a string")
    return v


def req_int(body: dict, name: str) -> int:
    v = req_field(body, name)
    if not is_int(v):
        invalid(f"Field {name} must be an integer")
    return v


def req_date(body: dict, name: str) -> str:
    v = req_field(body, name)
    if not is_date_str(v):
        invalid(f"Field {name} must be a YYYY-MM-DD calendar date")
    return v


def opt_str(body: dict, name: str, default=None):
    v = body.get(name, default)
    if v is not None and not is_str(v):
        invalid(f"Field {name} must be a string")
    return v


def opt_int(body: dict, name: str, default=None):
    v = body.get(name, default)
    if v is not None and not is_int(v):
        invalid(f"Field {name} must be an integer")
    return v


def opt_bool(body: dict, name: str, default=False) -> bool:
    v = body.get(name, default)
    if not is_bool(v):
        invalid(f"Field {name} must be a boolean")
    return v


def opt_enum(body: dict, name: str, choices, default=None):
    v = body.get(name, default)
    if v is None:
        invalid(f"Missing required field: {name}")
    if v not in choices:
        invalid(f"Field {name} must be one of {sorted(choices)}")
    return v


# ---------- resource lookups ----------

def _lookup(store: dict, rid, error_id: str, label: str):
    if not is_str(rid) or rid not in store:
        raise ApiError(error_id, f"No {label} with the given id", 404)
    return store[rid]


def get_project(rid):
    return _lookup(db.projects, rid, ERR_PROJECT_NOT_FOUND, "CaProject")


def get_submittal(rid):
    return _lookup(db.submittals, rid, ERR_SUBMITTAL_NOT_FOUND, "Submittal")


def get_site_visit(rid):
    return _lookup(db.site_visits, rid, ERR_SITE_VISIT_NOT_FOUND, "SiteVisit")


def get_field_report(rid):
    return _lookup(db.field_reports, rid, ERR_FIELD_REPORT_NOT_FOUND, "FieldReport")


def get_rfi(rid):
    return _lookup(db.rfis, rid, ERR_RFI_NOT_FOUND, "Rfi")


def get_drawing(rid):
    return _lookup(db.clarification_drawings, rid, ERR_CLARIFICATION_DRAWING_NOT_FOUND, "ClarificationDrawing")


def get_payment_application(rid):
    return _lookup(db.payment_applications, rid, ERR_PAYMENT_APPLICATION_NOT_FOUND, "PaymentApplication")


def get_change_order(rid):
    return _lookup(db.change_orders, rid, ERR_CHANGE_ORDER_NOT_FOUND, "ChangeOrder")


def get_punch_item(rid):
    return _lookup(db.punch_list_items, rid, ERR_PUNCH_ITEM_NOT_FOUND, "PunchListItem")


def get_record_document(rid):
    return _lookup(db.record_documents, rid, ERR_RECORD_DOCUMENT_NOT_FOUND, "RecordDocument")


def get_invoice(rid):
    return _lookup(db.invoices, rid, ERR_INVOICE_NOT_FOUND, "AdditionalServiceInvoice")


# ---------- mutation bookkeeping ----------

def touch(entity: dict):
    entity["updated_at"] = db.now_iso()
    entity["version"] += 1


def base_entity() -> dict:
    ts = db.now_iso()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts, "version": 1}


# ---------- pagination / list rendering ----------

def paginate(items: list):
    """Sort by created_at ASC and apply limit/offset from the query string."""
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
