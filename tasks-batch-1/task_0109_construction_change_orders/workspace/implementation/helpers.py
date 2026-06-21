"""Shared request-parsing, validation, pagination, and serialization helpers."""
from datetime import datetime

from flask import request

from errors import err, ERR_INVALID_REQUEST
import db

# Pagination defaults (PRD §2.3 / scaffold response_envelope.pagination_defaults).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_json():
    """Return the request JSON body as a dict (empty dict if none)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def as_int(value, field, *, minimum=None, maximum=None, allow_negative=True):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    if not allow_negative and value < 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= 0." % field)
    if minimum is not None and value < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s." % (field, maximum))
    return value


def as_number(value, field, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number." % field)
    if minimum is not None and value < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s." % (field, maximum))
    return value


def as_nonempty_string(value, field):
    if not isinstance(value, str) or value.strip() == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return value


def as_string(value, field):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a string." % field)
    return value


def as_enum(value, field, choices):
    if value not in choices:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s." % (field, sorted(choices)))
    return value


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime string into a comparable datetime.

    Datetimes are only ever compared to each other (window overlap, buffer
    gaps); we keep the original string for storage and use the parsed value for
    comparisons.
    """
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime string." % field)
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Field %s is not a valid ISO 8601 datetime." % field)


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Out-of-range -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err(ERR_INVALID_REQUEST,
                      "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (ties broken by insertion seq), then slice.

    Returns (page_records, pagination_meta).
    """
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Serializers — expose exactly the fields the PRD declares per entity.
# ---------------------------------------------------------------------------

def _common(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def project_out(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "owner_user_id": r["owner_user_id"],
        "original_contract_sum_cents": r["original_contract_sum_cents"],
        "default_retainage_pct": r["default_retainage_pct"],
        "revised_contract_sum_cents": r["revised_contract_sum_cents"],
        "total_completed_and_stored_cents": r["total_completed_and_stored_cents"],
        "retainage_held_cents": r["retainage_held_cents"],
        "status": r["status"],
    })
    return out


def sov_line_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "item_no": r["item_no"],
        "description": r["description"],
        "scheduled_value_cents": r["scheduled_value_cents"],
        "retainage_pct": r["retainage_pct"],
        "work_completed_to_date_cents": r["work_completed_to_date_cents"],
        "materials_stored_cents": r["materials_stored_cents"],
        "retainage_withheld_to_date_cents": r["retainage_withheld_to_date_cents"],
        "status": r["status"],
    })
    return out


def change_order_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "co_number": r["co_number"],
        "change_order_amount_cents": r["change_order_amount_cents"],
        "line_edits": r["line_edits"],
        "status": r["status"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "approved_by_user_id": r["approved_by_user_id"],
    })
    return out


def pay_application_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "application_number": r["application_number"],
        "period_from": r["period_from"],
        "period_to": r["period_to"],
        "total_completed_and_stored_cents": r["total_completed_and_stored_cents"],
        "total_retainage_cents": r["total_retainage_cents"],
        "current_payment_due_cents": r["current_payment_due_cents"],
        "status": r["status"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "certified_by_user_id": r["certified_by_user_id"],
    })
    return out


def pay_app_line_out(r):
    # No common fields beyond id + created_at (PRD §2.4).
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "pay_app_id": r["pay_app_id"],
        "sov_line_id": r["sov_line_id"],
        "work_completed_this_period_cents": r["work_completed_this_period_cents"],
        "materials_stored_cents": r["materials_stored_cents"],
        "work_completed_previous_cents": r["work_completed_previous_cents"],
        "line_retainage_cents": r["line_retainage_cents"],
    }


def subcontractor_commitment_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "subcontractor_name": r["subcontractor_name"],
        "committed_amount_cents": r["committed_amount_cents"],
        "invoiced_to_date_cents": r["invoiced_to_date_cents"],
        "status": r["status"],
    })
    return out


def rfi_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "subject": r["subject"],
        "question": r["question"],
        "ball_in_court": r["ball_in_court"],
        "status": r["status"],
        "answer": r["answer"],
    })
    return out


def submittal_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "spec_section": r["spec_section"],
        "title": r["title"],
        "revision": r["revision"],
        "status": r["status"],
    })
    return out


def lien_waiver_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "pay_app_id": r["pay_app_id"],
        "waiver_type": r["waiver_type"],
        "through_date": r["through_date"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return out


def punch_item_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "location": r["location"],
        "description": r["description"],
        "severity": r["severity"],
        "status": r["status"],
    })
    return out


def inspection_window_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "inspector_name": r["inspector_name"],
        "scheduled_start": r["scheduled_start"],
        "scheduled_end": r["scheduled_end"],
        "buffer_minutes": r["buffer_minutes"],
        "status": r["status"],
    })
    return out


def retention_release_out(r):
    out = _common(r)
    out.update({
        "project_id": r["project_id"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
        "approved_by_user_id": r["approved_by_user_id"],
    })
    return out
