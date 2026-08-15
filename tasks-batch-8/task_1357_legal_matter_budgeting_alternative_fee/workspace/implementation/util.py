"""Shared helpers: ids, timestamps, body parsing, validation, pagination,
period arithmetic, and hierarchical path lookups.
"""
import uuid

from flask import request

import clock
import db
from errors import ApiError, err_not_found, err_invalid_request


# ---------------------------------------------------------------------------
# Identity / timestamps
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


# Monotonic sequence counter: guarantees a strict creation ordering between
# resources even when several are created within the same logical-clock instant
# (the logical clock only moves when tests set it, but ordering-sensitive rules
# like the write-down waterfall rely on created_at ASC). The sequence rides in
# an internal `_seq` field so created_at/updated_at stay clean ISO 8601
# (PRD §2.4); `_seq` is stripped from serialized responses (response.py).
_timestamp_seq = [0]


def _next_seq():
    _timestamp_seq[0] += 1
    return _timestamp_seq[0]


def _next_timestamp():
    _next_seq()
    return clock.now_iso()


def new_resource():
    """Return the common system-managed scaffold for a fresh resource."""
    ts = _next_timestamp()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": _timestamp_seq[0]}


def touch(resource):
    """Refresh updated_at and increment version (PRD §2.4)."""
    resource["updated_at"] = _next_timestamp()
    resource["_seq"] = _timestamp_seq[0]
    resource["version"] = int(resource.get("version", 1)) + 1


def order_key(resource):
    """Deterministic ascending creation order: created_at ASC, ties broken by
    the internal monotonic sequence (equal instants order by creation)."""
    return (resource.get("created_at", ""), resource.get("_seq", 0),
            resource.get("id", ""))


# ---------------------------------------------------------------------------
# Request body parsing and field validation
# ---------------------------------------------------------------------------

def body():
    """Return the JSON request body as a dict ({} when absent)."""
    raw = request.get_data(cache=True)
    if raw is None or raw == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Tolerate JSON payloads sent with a non-JSON content type.
        import json as _json
        try:
            data = _json.loads(raw.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            raise err_invalid_request("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def missing(val):
    return val is None


def is_int(val):
    return isinstance(val, int) and not isinstance(val, bool)


def is_bool(val):
    return isinstance(val, bool)


def require_fields(data, fields):
    for f in fields:
        if data.get(f) is None:
            raise err_invalid_request(f"Missing required field: {f}")


def check_string(data, field):
    val = data.get(field)
    if not isinstance(val, str) or not val.strip():
        raise err_invalid_request(f"Field {field} must be a non-empty string")
    return val


def check_int(data, field, minimum=None, maximum=None):
    val = data.get(field)
    if not is_int(val):
        raise err_invalid_request(f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err_invalid_request(f"Field {field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err_invalid_request(f"Field {field} must be <= {maximum}")
    return val


def check_optional_int(data, field, minimum=None, maximum=None):
    if data.get(field) is None:
        return None
    return check_int(data, field, minimum, maximum)


def check_enum(data, field, allowed):
    val = data.get(field)
    if val not in allowed:
        raise err_invalid_request(
            f"Field {field} must be one of {sorted(allowed)}"
        )
    return val


def check_optional_enum(data, field, allowed):
    if data.get(field) is None:
        return None
    return check_enum(data, field, allowed)


def check_bool(data, field, default=False):
    val = data.get(field)
    if val is None:
        return default
    if not is_bool(val):
        raise err_invalid_request(f"Field {field} must be a boolean")
    return val


def parse_iso_date(value, field="entry_date"):
    """Parse an ISO-8601 date/datetime string; returns (y, m, d)."""
    if not isinstance(value, str) or not value.strip():
        raise err_invalid_request(f"Field {field} must be an ISO-8601 date string")
    s = value.strip()
    try:
        if "T" in s:
            from datetime import datetime
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.year, dt.month, dt.day
        from datetime import date
        d = date.fromisoformat(s)
        return d.year, d.month, d.day
    except ValueError:
        raise err_invalid_request(f"Field {field} must be a valid ISO-8601 date")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit/offset, defaults 10/0, limit in [1, 100]
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at ASC (stable) and apply limit/offset window."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=order_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return window, meta


def query_filters(allowed):
    """Extract recognized query-string filters; unknown names are ignored."""
    filters = {}
    for name in allowed:
        if name in request.args:
            filters[name] = request.args.get(name)
    return filters


def apply_filters(items, filters):
    out = []
    for item in items:
        ok = True
        for key, raw in filters.items():
            cur = item.get(key)
            if is_int(cur):
                try:
                    wanted = int(raw)
                except (TypeError, ValueError):
                    ok = False
                    break
                if cur != wanted:
                    ok = False
                    break
            elif is_bool(cur):
                if raw.lower() not in ("true", "false"):
                    ok = False
                    break
                if cur != (raw.lower() == "true"):
                    ok = False
                    break
            else:
                if cur != raw:
                    ok = False
                    break
        if ok:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# Fiscal period arithmetic (PRD §2.6)
# ---------------------------------------------------------------------------

def period_index_for_date(firm, year, month, day):
    """Fiscal period containing a date: monthly periods anchored so that
    period 0 is the fiscal month containing the startup instant 2026-08-01 —
    coherent with the firm's `current_period_index` initializing to 0 at
    creation while the logical clock reads 2026-08-01 (PRD §2.6). Fiscal
    periods are calendar months; `fiscal_year_start_month` groups them into
    years but does not shift month boundaries."""
    return (year - 2026) * 12 + (month - 8)


def fiscal_year_for_period(firm, period_index):
    """Calendar fiscal-year label of the fiscal year containing the period.

    Anchored so that the fiscal year containing the startup instant is
    labeled 2026 (matching the `fiscal_year_index: 2026` arrangements drafted
    while the logical clock reads 2026-08). A fiscal year labeled Y runs from
    (Y, fiscal_year_start_month, 1) to (Y+1, fiscal_year_start_month, 1)."""
    start = int(firm.get("fiscal_year_start_month", 1))
    # Calendar month of the period: 2026-08 plus `period_index` months.
    y = 2026 + (7 + period_index) // 12
    m = (7 + period_index) % 12 + 1
    return y if m >= start else y - 1


def current_fiscal_year_index(firm):
    """Fiscal-year label containing the firm's current period."""
    return fiscal_year_for_period(firm, int(firm.get("current_period_index", 0)))


def fiscal_year_ended(firm, fiscal_year_index):
    """Whether the fiscal year labeled `fiscal_year_index` has ended.

    A firm's fiscal year Y runs from (Y, fiscal_year_start_month, 1) to
    (Y+1, fiscal_year_start_month, 1); it has ended once the logical clock
    reaches the first day of the following fiscal year.
    """
    import clock as _clock
    start = int(firm.get("fiscal_year_start_month", 1))
    end_year = int(fiscal_year_index) + 1
    n = _clock.now()
    return (n.year, n.month, n.day) >= (end_year, start, 1)


# ---------------------------------------------------------------------------
# Hierarchical lookups (PRD §2.11): validate left to right within firm scope
# ---------------------------------------------------------------------------

def get_firm(firm_id):
    firm = db.firms.get(firm_id)
    if firm is None:
        raise err_not_found(f"Firm {firm_id} not found")
    return firm


def get_client_scoped(firm_id, client_id):
    get_firm(firm_id)
    client = db.clients.get(client_id)
    if client is None or client.get("firm_id") != firm_id:
        raise err_not_found(f"Client {client_id} not found")
    return client


def get_client_flat(client_id):
    client = db.clients.get(client_id)
    if client is None:
        raise err_not_found(f"Client {client_id} not found")
    return client


def get_matter_scoped(firm_id, matter_id):
    get_firm(firm_id)
    matter = db.matters.get(matter_id)
    if matter is None or matter.get("firm_id") != firm_id:
        raise err_not_found(f"Matter {matter_id} not found")
    return matter


def get_matter_flat(matter_id):
    matter = db.matters.get(matter_id)
    if matter is None:
        raise err_not_found(f"Matter {matter_id} not found")
    return matter


def get_arrangement_scoped(firm_id, arrangement_id):
    get_firm(firm_id)
    obj = db.fee_arrangements.get(arrangement_id)
    if obj is None or obj.get("firm_id") != firm_id:
        raise err_not_found(f"FeeArrangement {arrangement_id} not found")
    return obj


def get_arrangement_flat(arrangement_id):
    obj = db.fee_arrangements.get(arrangement_id)
    if obj is None:
        raise err_not_found(f"FeeArrangement {arrangement_id} not found")
    return obj


def get_phase_scoped(firm_id, phase_id):
    get_firm(firm_id)
    obj = db.phase_budgets.get(phase_id)
    if obj is None or obj.get("firm_id") != firm_id:
        raise err_not_found(f"PhaseBudget {phase_id} not found")
    return obj


def get_phase_flat(phase_id):
    obj = db.phase_budgets.get(phase_id)
    if obj is None:
        raise err_not_found(f"PhaseBudget {phase_id} not found")
    return obj


def get_entry_scoped(firm_id, entry_id):
    get_firm(firm_id)
    obj = db.time_entries.get(entry_id)
    if obj is None or obj.get("firm_id") != firm_id:
        raise err_not_found(f"TimeEntry {entry_id} not found")
    return obj


def get_entry_flat(entry_id):
    obj = db.time_entries.get(entry_id)
    if obj is None:
        raise err_not_found(f"TimeEntry {entry_id} not found")
    return obj


def get_timekeeper_flat(timekeeper_id):
    obj = db.timekeepers.get(timekeeper_id)
    if obj is None:
        raise err_not_found(f"Timekeeper {timekeeper_id} not found")
    return obj


def get_write_down_scoped(firm_id, request_id):
    get_firm(firm_id)
    obj = db.write_down_requests.get(request_id)
    if obj is None or obj.get("firm_id") != firm_id:
        raise err_not_found(f"WriteDownRequest {request_id} not found")
    return obj


def get_write_down_flat(request_id):
    obj = db.write_down_requests.get(request_id)
    if obj is None:
        raise err_not_found(f"WriteDownRequest {request_id} not found")
    return obj


def get_amendment_scoped(firm_id, amendment_id):
    get_firm(firm_id)
    obj = db.budget_amendments.get(amendment_id)
    if obj is None or obj.get("firm_id") != firm_id:
        raise err_not_found(f"BudgetAmendment {amendment_id} not found")
    return obj


def get_amendment_flat(amendment_id):
    obj = db.budget_amendments.get(amendment_id)
    if obj is None:
        raise err_not_found(f"BudgetAmendment {amendment_id} not found")
    return obj


def get_report_scoped(firm_id, report_id):
    get_firm(firm_id)
    obj = db.accrual_reports.get(report_id)
    if obj is None or obj.get("firm_id") != firm_id:
        raise err_not_found(f"AccrualReport {report_id} not found")
    return obj


def get_report_flat(report_id):
    obj = db.accrual_reports.get(report_id)
    if obj is None:
        raise err_not_found(f"AccrualReport {report_id} not found")
    return obj


def get_true_up_scoped(firm_id, true_up_id):
    get_firm(firm_id)
    obj = db.collar_true_ups.get(true_up_id)
    if obj is None or obj.get("firm_id") != firm_id:
        raise err_not_found(f"CollarTrueUp {true_up_id} not found")
    return obj


def get_true_up_flat(true_up_id):
    obj = db.collar_true_ups.get(true_up_id)
    if obj is None:
        raise err_not_found(f"CollarTrueUp {true_up_id} not found")
    return obj
