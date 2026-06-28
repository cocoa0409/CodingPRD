"""Shared helpers: body parsing, field validation, pagination, lookups."""
from flask import request

import errors
import response
from db import db


# ---------------------------------------------------------------------------
# Response envelope wrappers (thin re-exports of response.py helpers)
# ---------------------------------------------------------------------------
def object_response(data):
    return response.object_response(data, 200)


def object_response_201(data):
    return response.object_response(data, 201)


def array_response(items, limit, offset, total):
    return response.array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON -> 400."""
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        # Body present but unparseable, or non-JSON content.
        if (request.data or b"").strip():
            errors.fail(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        errors.fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Field validation (priority 5: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def require_str(body, field, allow_empty=False):
    val = body.get(field)
    if not isinstance(val, str) or (not allow_empty and not val.strip()):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string." % field)
    return val


def optional_str(body, field):
    if field not in body or body.get(field) is None:
        return None
    val = body.get(field)
    if not isinstance(val, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a string." % field)
    return val


def require_int_nonneg(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer." % field)
    if val < 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be non-negative." % field)
    return val


def require_int_min(body, field, minimum):
    val = require_int_nonneg(body, field)
    if val < minimum:
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %d." % (field, minimum))
    return val


def optional_int_nonneg(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    return require_int_nonneg(body, field)


def require_bool_optional(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % field)
    return val


def require_enum(body, field, choices):
    val = body.get(field)
    if not isinstance(val, str) or val not in choices:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "Field '%s' must be one of %s." % (field, sorted(choices)))
    return val


def optional_enum(body, field, choices, default):
    if field not in body or body.get(field) is None:
        return default
    return require_enum(body, field, choices)


def require_str_array(body, field):
    val = body.get(field)
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an array of strings." % field)
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10 min 1 max 100; offset default 0.
# ---------------------------------------------------------------------------
def get_pagination():
    limit = _parse_query_int("limit", 10)
    offset = _parse_query_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def paginate(items, limit, offset):
    """items pre-sorted by created_at asc. Return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(records):
    # PRD 2.3: list results sorted by created_at ascending.
    return sorted(records, key=lambda r: (r.get("created_at"), r.get("id")))


# ---------------------------------------------------------------------------
# Path-existence lookups (priority 3 / 4) — resource-specific not-found.
# ---------------------------------------------------------------------------
def get_or_404(collection, rid, err_spec):
    rec = collection.get(rid)
    if rec is None:
        errors.fail(err_spec, "Resource not found.")
    return rec


def find_panel(rid):
    return get_or_404(db.test_panels, rid, errors.ERR_PANEL_NOT_FOUND)


def find_partner(rid):
    return get_or_404(db.lab_partners, rid, errors.ERR_LAB_PARTNER_NOT_FOUND)


def find_phlebotomist(rid):
    return get_or_404(db.phlebotomists, rid, errors.ERR_PHLEBOTOMIST_NOT_FOUND)


def find_route_day(rid):
    return get_or_404(db.route_days, rid, errors.ERR_ROUTE_DAY_NOT_FOUND)


def find_order(rid):
    return get_or_404(db.lab_orders, rid, errors.ERR_ORDER_NOT_FOUND)


def find_appointment(rid):
    return get_or_404(db.appointments, rid, errors.ERR_APPOINTMENT_NOT_FOUND)


def find_specimen(rid):
    return get_or_404(db.specimens, rid, errors.ERR_SPECIMEN_NOT_FOUND)


def find_custody_event(rid):
    return get_or_404(db.custody_events, rid, errors.ERR_CUSTODY_EVENT_NOT_FOUND)


def find_manifest(rid):
    return get_or_404(db.courier_manifests, rid, errors.ERR_MANIFEST_NOT_FOUND)


def find_invoice(rid):
    return get_or_404(db.invoices, rid, errors.ERR_INVOICE_NOT_FOUND)


def find_result(rid):
    # No dedicated not-found error in catalog for lab results; reuse order-scoped
    # semantics is not appropriate, so 404 with the closest resource error.
    rec = db.lab_results.get(rid)
    if rec is None:
        errors.fail(errors.ERR_ORDER_NOT_FOUND, "Lab result not found.")
    return rec


def find_panel_by_code(panel_code):
    for p in db.test_panels.values():
        if p["panel_code"] == panel_code:
            return p
    return None
