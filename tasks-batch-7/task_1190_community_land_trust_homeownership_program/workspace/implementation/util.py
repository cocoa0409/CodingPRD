"""Shared utilities: time handling, decimal math, ids, response envelope,
request-body validation, pagination, and entity serialization.

Every structural name (envelope fields, pagination params, timestamps) follows
SCAFFOLD `response_envelope` and PRD section 2 exactly:
  success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
            "response_type": "object"|"array", "data": ...}
  error:   {"meta": {"api_request_id", "api_request_timestamp"},
            "response_type": "error", "data": {"error_id", "message"}}
Pagination params: limit (default 10, min 1, max 100), offset (default 0, min 0);
meta fields limit/offset/total_count/has_more. Lists sort by created_at asc.
Timestamps: ISO 8601 UTC with three fractional digits.
"""
import calendar
import secrets
import string
import uuid
from datetime import datetime, timezone

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST

UTC = timezone.utc

_ALPHANUM = string.ascii_letters + string.digits


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Field '%s' must be an ISO 8601 timestamp" % field)
    else:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' must be an ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Calendar-month addition, clamping the day to the target month length."""
    m0 = dt.month - 1 + months
    y = dt.year + m0 // 12
    m = m0 % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Ids and envelope
# ---------------------------------------------------------------------------

def gen_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(24))


def _meta():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": iso(db.get_now()),
    }


def ok_object(obj):
    return {"meta": _meta(), "response_type": "object", "data": obj}


def ok_array(items, limit, offset, total_count):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return {"meta": m, "response_type": "array", "data": items}


def error_envelope(error_id, message, status):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }, status


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------

def new_entity(with_version=True):
    now = db.get_now()
    ent = {"id": gen_id(), "created_at": now}
    if with_version:
        ent["updated_at"] = now
        ent["version"] = 1
    return ent


def bump(ent):
    """Record a mutation: increment version (when present) and updated_at."""
    if "version" in ent:
        ent["version"] += 1
    if "updated_at" in ent:
        ent["updated_at"] = db.get_now()


# ---------------------------------------------------------------------------
# Request body validation helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
    return data[name]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(data, name):
    v = req_field(data, name)
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an integer" % name)
    return v


def opt_int(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an integer" % name)
    return v


def req_num(data, name):
    v = req_field(data, name)
    if not _is_num(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a number" % name)
    return v


def opt_num(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not _is_num(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a number" % name)
    return v


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a non-empty string" % name)
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a string" % name)
    return v


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a boolean" % name)
    return v


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a boolean" % name)
    return v


def req_dt(data, name):
    return parse_dt(req_field(data, name), field=name)


def req_enum(data, name, allowed):
    v = req_str(data, name)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Query parameter 'limit' must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be >= 0")
    return limit, offset


def paginated(items, serializer):
    """Sort by created_at ascending, slice, and wrap in the array envelope."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_array([serializer(e) for e in page], limit, offset, total)


def query_str(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def query_int(name):
    v = request.args.get(name)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Query parameter '%s' must be an integer" % name)


def query_bool(name):
    v = request.args.get(name)
    if v in (None, ""):
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    raise ApiError(ERR_INVALID_REQUEST, 400,
                   "Query parameter '%s' must be a boolean" % name)


# ---------------------------------------------------------------------------
# Serializers (only declared fields are emitted; internal "_"-keys are hidden;
# EducationCompletion and LeaseFee carry no updated_at/version per PRD 2.4)
# ---------------------------------------------------------------------------

def ser_program(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "ami_table_effective_date": iso(p["ami_table_effective_date"]),
        "area_median_income_cents": p["area_median_income_cents"],
        "max_eligibility_ami_pct": p["max_eligibility_ami_pct"],
        "ground_lease_term_years": p["ground_lease_term_years"],
        "ground_lease_base_fee_cents": p["ground_lease_base_fee_cents"],
        "low_income_fee_reduction_pct": p["low_income_fee_reduction_pct"],
        "resale_formula_kind": p["resale_formula_kind"],
        "indexed_annual_appreciation_pct": p["indexed_annual_appreciation_pct"],
        "appraisal_seller_share_pct": p["appraisal_seller_share_pct"],
        "max_refi_ltv_pct": p["max_refi_ltv_pct"],
        "max_equity_withdrawal_cents": p["max_equity_withdrawal_cents"],
        "default_cure_window_days": p["default_cure_window_days"],
        "inspection_cycle_months": p["inspection_cycle_months"],
        "status": p["status"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def ser_household(h):
    return {
        "id": h["id"],
        "program_id": h["program_id"],
        "legal_name": h["legal_name"],
        "household_size": h["household_size"],
        "annual_gross_income_cents": h["annual_gross_income_cents"],
        "ami_pct": h["ami_pct"],
        "eligibility_status": h["eligibility_status"],
        "eligibility_expires_at": iso(h["eligibility_expires_at"]),
        "education_required": h["education_required"],
        "education_completed_at": iso(h["education_completed_at"]),
        "active_lease_id": h["active_lease_id"],
        "waitlist_entry_id": h["waitlist_entry_id"],
        "notes": h["notes"],
        "created_at": iso(h["created_at"]),
        "updated_at": iso(h["updated_at"]),
        "version": h["version"],
    }


def ser_cert(c):
    return {
        "id": c["id"],
        "household_id": c["household_id"],
        "tax_year": c["tax_year"],
        "reported_annual_income_cents": c["reported_annual_income_cents"],
        "verified_annual_income_cents": c["verified_annual_income_cents"],
        "household_size_at_cert": c["household_size_at_cert"],
        "ami_pct_at_cert": c["ami_pct_at_cert"],
        "status": c["status"],
        "rejection_reason": c["rejection_reason"],
        "reviewed_by": c["reviewed_by"],
        "submitted_by": c["submitted_by"],
        "decided_at": iso(c["decided_at"]),
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_course(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "code": c["code"],
        "title": c["title"],
        "credit_hours": c["credit_hours"],
        "is_required": c["is_required"],
        "validity_months": c["validity_months"],
        "status": c["status"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def ser_completion(c):
    return {
        "id": c["id"],
        "household_id": c["household_id"],
        "course_id": c["course_id"],
        "completed_at": iso(c["completed_at"]),
        "expires_at": iso(c["expires_at"]),
        "recorded_by": c["recorded_by"],
        "score_pct": c["score_pct"],
        "created_at": iso(c["created_at"]),
    }


def ser_unit(u):
    return {
        "id": u["id"],
        "program_id": u["program_id"],
        "address": u["address"],
        "bedrooms": u["bedrooms"],
        "original_subsidy_cents": u["original_subsidy_cents"],
        "original_sale_price_cents": u["original_sale_price_cents"],
        "current_lease_id": u["current_lease_id"],
        "occupancy_status": u["occupancy_status"],
        "last_inspection_passed_at": iso(u["last_inspection_passed_at"]),
        "next_inspection_due_at": iso(u["next_inspection_due_at"]),
        "maintenance_flag": u["maintenance_flag"],
        "appraisal_value_cents": u["appraisal_value_cents"],
        "created_at": iso(u["created_at"]),
        "updated_at": iso(u["updated_at"]),
        "version": u["version"],
    }


def ser_lease(l):
    return {
        "id": l["id"],
        "unit_id": l["unit_id"],
        "household_id": l["household_id"],
        "start_date": iso(l["start_date"]),
        "end_date": iso(l["end_date"]),
        "monthly_fee_cents": l["monthly_fee_cents"],
        "subsidy_locked_cents": l["subsidy_locked_cents"],
        "purchase_price_cents": l["purchase_price_cents"],
        "status": l["status"],
        "fee_arrears_cents": l["fee_arrears_cents"],
        "last_fee_charged_at": iso(l["last_fee_charged_at"]),
        "resale_count": l["resale_count"],
        "created_at": iso(l["created_at"]),
        "updated_at": iso(l["updated_at"]),
        "version": l["version"],
    }


def ser_fee(f):
    return {
        "id": f["id"],
        "lease_id": f["lease_id"],
        "period_year": f["period_year"],
        "period_month": f["period_month"],
        "amount_cents": f["amount_cents"],
        "due_date": iso(f["due_date"]),
        "status": f["status"],
        "paid_at": iso(f["paid_at"]),
        "paid_amount_cents": f["paid_amount_cents"],
        "created_at": iso(f["created_at"]),
    }


def ser_notice(n):
    return {
        "id": n["id"],
        "lease_id": n["lease_id"],
        "notice_kind": n["notice_kind"],
        "issued_at": iso(n["issued_at"]),
        "cure_deadline_at": iso(n["cure_deadline_at"]),
        "amount_due_cents": n["amount_due_cents"],
        "status": n["status"],
        "issued_by": n["issued_by"],
        "cured_at": iso(n["cured_at"]),
        "cure_evidence": n["cure_evidence"],
        "created_at": iso(n["created_at"]),
        "updated_at": iso(n["updated_at"]),
        "version": n["version"],
    }


def ser_inspection(i):
    return {
        "id": i["id"],
        "unit_id": i["unit_id"],
        "scheduled_for": iso(i["scheduled_for"]),
        "completed_at": iso(i["completed_at"]),
        "inspector_user_id": i["inspector_user_id"],
        "result": i["result"],
        "findings": i["findings"],
        "follow_up_due_at": iso(i["follow_up_due_at"]),
        "linked_notice_id": i["linked_notice_id"],
        "created_at": iso(i["created_at"]),
        "updated_at": iso(i["updated_at"]),
        "version": i["version"],
    }


def ser_waitlist_entry(e):
    return {
        "id": e["id"],
        "household_id": e["household_id"],
        "desired_bedrooms": e["desired_bedrooms"],
        "max_price_cents": e["max_price_cents"],
        "priority_score": e["priority_score"],
        "status": e["status"],
        "matched_unit_id": e["matched_unit_id"],
        "matched_at": iso(e["matched_at"]),
        "match_rank_at_match": e["match_rank_at_match"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_listing(l):
    return {
        "id": l["id"],
        "unit_id": l["unit_id"],
        "seller_lease_id": l["seller_lease_id"],
        "listed_at": iso(l["listed_at"]),
        "appraisal_at_listing_cents": l["appraisal_at_listing_cents"],
        "asking_price_cents": l["asking_price_cents"],
        "seller_proceeds_cents": l["seller_proceeds_cents"],
        "subsidy_retained_cents": l["subsidy_retained_cents"],
        "affordability_preserved": l["affordability_preserved"],
        "status": l["status"],
        "matched_waitlist_entry_id": l["matched_waitlist_entry_id"],
        "buyer_household_id": l["buyer_household_id"],
        "created_at": iso(l["created_at"]),
        "updated_at": iso(l["updated_at"]),
        "version": l["version"],
    }


def ser_refi(r):
    return {
        "id": r["id"],
        "lease_id": r["lease_id"],
        "lender_name": r["lender_name"],
        "requested_loan_cents": r["requested_loan_cents"],
        "requested_cash_out_cents": r["requested_cash_out_cents"],
        "appraised_value_cents": r["appraised_value_cents"],
        "computed_ltv": r["computed_ltv"],
        "program_max_loan_cents": r["program_max_loan_cents"],
        "status": r["status"],
        "rejection_reason": r["rejection_reason"],
        "submitted_by": r["submitted_by"],
        "reviewed_by": r["reviewed_by"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }
