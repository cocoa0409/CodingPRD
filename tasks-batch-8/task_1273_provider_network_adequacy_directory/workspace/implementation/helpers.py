"""Shared helpers: serialization, pagination, validation, dates, clock."""

import re
import uuid
from datetime import datetime, date, timezone, timedelta

from flask import request

import db
import errors

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

GEO_CLASSES = {"URBAN", "SUBURBAN", "RURAL"}
SPECIALTIES = {"PRIMARY_CARE", "CARDIOLOGY", "DERMATOLOGY", "BEHAVIORAL_HEALTH"}
PANEL_STATUSES = {"OPEN", "CLOSED"}
LISTING_SPECIALTIES = SPECIALTIES
SUPPRESS_REASONS = {"NONE", "MANUAL", "ATTESTATION_FAILURE", "GHOST_CONFIRMED", "PROVIDER_SUSPENDED"}
PROBE_TYPES = {"ROUTINE", "URGENT"}
PROBE_OUTCOMES = {"KEPT", "UNREACHABLE", "NO_APPOINTMENT_OFFERED"}
ERROR_TYPES = {"WRONG_PHONE", "WRONG_ADDRESS", "NOT_ACCEPTING", "NO_APPOINTMENT", "OTHER"}
COMPLAINT_ADJUDICATE_OUTCOMES = {"CONFIRMED_ERROR", "UNFOUNDED"}
DECISIONS = {"APPROVED", "DENIED"}
CORRECTION_MUTABLE_FIELDS = {"display_name", "phone", "accepts_new_patients", "office_hours_note"}

# ---------------------------------------------------------------------------
# Clock / timestamps
# ---------------------------------------------------------------------------

_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def now_iso() -> str:
    """Logical clock timestamp with three fractional digits."""
    return _dt_to_iso(db.clock_now)


def _dt_to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_date() -> date:
    return db.clock_now.date()


def parse_iso_datetime(s):
    """Parse an ISO 8601 UTC datetime string (with optional fractional digits)."""
    if not isinstance(s, str) or not _ISO_Z_RE.match(s):
        raise errors.err_invalid(f"Invalid ISO 8601 UTC timestamp: {s!r}")
    body = s[:-1]
    if "." in body:
        base, frac = body.split(".", 1)
        frac = (frac + "000000")[:6]
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(microsecond=int(frac), tzinfo=timezone.utc)
    return datetime.strptime(body, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def parse_date(s, field="date") -> date:
    if not isinstance(s, str):
        raise errors.err_invalid(f"{field} must be an ISO date string")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise errors.err_invalid(f"{field} must be a valid ISO date (YYYY-MM-DD)")


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------

def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise errors.err_invalid("Request body must be a JSON object")
    return body


def req_field(body, name):
    val = body.get(name)
    if val is None:
        raise errors.err_invalid(f"Missing required field: {name}")
    return val


def req_str(body, name):
    val = req_field(body, name)
    if not isinstance(val, str) or val == "":
        raise errors.err_invalid(f"Field {name} must be a non-empty string")
    return val


def req_int(body, name):
    val = req_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err_invalid(f"Field {name} must be an integer")
    return val


def req_bool(body, name):
    val = req_field(body, name)
    if not isinstance(val, bool):
        raise errors.err_invalid(f"Field {name} must be a boolean")
    return val


def req_enum(body, name, allowed):
    val = req_str(body, name)
    if val not in allowed:
        raise errors.err_invalid(f"Field {name} must be one of {sorted(allowed)}")
    return val


def opt_enum(body, name, allowed, default=None):
    val = body.get(name)
    if val is None:
        return default
    if not isinstance(val, str) or val not in allowed:
        raise errors.err_invalid(f"Field {name} must be one of {sorted(allowed)}")
    return val


def opt_int(body, name):
    val = body.get(name)
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err_invalid(f"Field {name} must be an integer")
    return val


def opt_str(body, name):
    val = body.get(name)
    if val is None:
        return None
    if not isinstance(val, str):
        raise errors.err_invalid(f"Field {name} must be a string")
    return val


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def query_enum(name, allowed):
    val = request.args.get(name)
    if val is None:
        return None
    if val not in allowed:
        raise errors.err_invalid(f"Query parameter {name} must be one of {sorted(allowed)}")
    return val


def query_str(name):
    return request.args.get(name)


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.err_invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err_invalid("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.err_invalid("offset must be an integer")
        if offset < 0:
            raise errors.err_invalid("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (stable: creation order), then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------

def stamp_new(record, with_version=True):
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version (mutation)."""
    record["updated_at"] = now_iso()
    record["version"] += 1


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_region(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
        "county_fips": r["county_fips"], "name": r["name"], "geo_class": r["geo_class"],
        "enrolled_member_count": r["enrolled_member_count"],
    }


def ser_standard(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
        "specialty": s["specialty"], "geo_class": s["geo_class"],
        "max_members_per_provider": s["max_members_per_provider"],
        "max_travel_minutes": s["max_travel_minutes"],
        "max_travel_miles": s["max_travel_miles"],
        "max_wait_days_routine": s["max_wait_days_routine"],
        "max_wait_days_urgent": s["max_wait_days_urgent"],
    }


def ser_provider(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
        "npi": p["npi"], "legal_name": p["legal_name"], "specialty": p["specialty"],
        "contract_effective_date": p["contract_effective_date"],
        "status": p["status"], "terminated_at": p["terminated_at"],
    }


def ser_location(l):
    return {
        "id": l["id"], "created_at": l["created_at"], "updated_at": l["updated_at"],
        "version": l["version"],
        "provider_id": l["provider_id"], "region_id": l["region_id"],
        "address_line": l["address_line"], "panel_status": l["panel_status"],
        "avg_travel_minutes": l["avg_travel_minutes"], "avg_travel_miles": l["avg_travel_miles"],
    }


def ser_listing(l):
    return {
        "id": l["id"], "created_at": l["created_at"], "updated_at": l["updated_at"],
        "version": l["version"],
        "provider_id": l["provider_id"], "location_id": l["location_id"],
        "specialty": l["specialty"], "display_name": l["display_name"],
        "phone": l["phone"], "accepts_new_patients": l["accepts_new_patients"],
        "office_hours_note": l.get("office_hours_note"),
        "status": l["status"], "suppress_reason": l["suppress_reason"],
        "ghost_strike_count": l["ghost_strike_count"],
        "has_confirmed_data_error": l["has_confirmed_data_error"],
        "listed_at": l["listed_at"], "suppressed_at": l["suppressed_at"],
    }


def ser_member(m):
    return {
        "id": m["id"], "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"],
        "region_id": m["region_id"], "member_ref": m["member_ref"],
        "full_name": m["full_name"], "enrolled_on": m["enrolled_on"],
        "status": m["status"], "disenrolled_at": m["disenrolled_at"],
    }


def _cycle_rates(c):
    """Attestation response rates (strict / lenient), 4dp round-half-up; 0/0 -> null."""
    from decimal import Decimal, ROUND_HALF_UP
    total = c["total_records"]
    if total == 0:
        return None, None
    attested = 0
    responded = 0
    for rec in db.records.values():
        if rec["cycle_id"] == c["id"] and rec["status"] != "CANCELLED":
            if rec["status"] == "ATTESTED":
                attested += 1
            if rec["status"] in ("ATTESTED", "CORRECTION_REQUESTED"):
                responded += 1
    strict = float((Decimal(attested) / Decimal(total)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    lenient = float((Decimal(responded) / Decimal(total)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    return strict, lenient


def ser_cycle(c):
    strict, lenient = _cycle_rates(c)
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "cycle_label": c["cycle_label"], "open_date": c["open_date"],
        "due_date": c["due_date"], "outreach_close_date": c["outreach_close_date"],
        "status": c["status"],
        "total_records": c["total_records"], "pending_count": c["pending_count"],
        "responded_count": c["responded_count"], "non_responsive_count": c["non_responsive_count"],
        "response_rate": strict, "response_rate_strict": strict, "response_rate_lenient": lenient,
    }


def ser_record(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
        "cycle_id": r["cycle_id"], "listing_id": r["listing_id"],
        "status": r["status"], "outreach_attempts": r["outreach_attempts"],
        "responded_at": r["responded_at"],
    }


def ser_probe(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
        "listing_id": p["listing_id"], "probe_type": p["probe_type"],
        "requested_date": p["requested_date"], "status": p["status"],
        "outcome": p["outcome"], "offered_appointment_date": p["offered_appointment_date"],
        "days_to_appointment": p["days_to_appointment"], "result": p["result"],
        "recorded_at": p["recorded_at"],
    }


def ser_evaluation(e):
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
        "measurement_period": e["measurement_period"],
        "period_start_date": e["period_start_date"], "period_end_date": e["period_end_date"],
        "status": e["status"], "total_penalty_cents": e["total_penalty_cents"],
        "finalized_at": e["finalized_at"],
    }


def ser_result(r):
    # RegionSpecialtyResult: no updated_at, no version (immutable snapshot)
    return {
        "id": r["id"], "created_at": r["created_at"],
        "evaluation_id": r["evaluation_id"], "region_id": r["region_id"],
        "specialty": r["specialty"], "member_count": r["member_count"],
        "provider_count": r["provider_count"], "listing_count": r["listing_count"],
        "ratio_members_per_provider": r["ratio_members_per_provider"],
        "ratio_ok": r["ratio_ok"],
        "counted_location_count": r["counted_location_count"],
        "compliant_location_count": r["compliant_location_count"],
        "time_distance_compliant": r["time_distance_compliant"],
        "probed_listing_count": r["probed_listing_count"],
        "mean_wait_days": r["mean_wait_days"], "p90_wait_days": r["p90_wait_days"],
        "wait_time_compliant": r["wait_time_compliant"],
        "overall_status": r["overall_status"],
    }


def ser_deficiency(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
        "evaluation_id": d["evaluation_id"], "region_id": d["region_id"],
        "specialty": d["specialty"], "status": d["status"],
        "opened_date": d["opened_date"], "closed_date": d["closed_date"],
        "prior_closure_count": d["prior_closure_count"],
        "accrual_window_start": d["accrual_window_start"],
        "accrual_window_end": d["accrual_window_end"],
        "last_accrual_cents": d["last_accrual_cents"],
        "accrued_penalty_cents": d["accrued_penalty_cents"],
        "reversed_penalty_cents": d["reversed_penalty_cents"],
        "outstanding_penalty_cents": d["accrued_penalty_cents"] - d["reversed_penalty_cents"],
    }


def ser_apr(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
        "deficiency_id": a["deficiency_id"], "remedy_summary": a["remedy_summary"],
        "excuse_start_date": a["excuse_start_date"], "excuse_through_date": a["excuse_through_date"],
        "status": a["status"], "submission_seq": a["submission_seq"],
        "decided_at": a["decided_at"], "decision_notes": a["decision_notes"],
    }


def ser_complaint(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "member_id": c["member_id"], "listing_id": c["listing_id"],
        "error_type": c["error_type"], "error_observed_date": c["error_observed_date"],
        "description": c["description"], "status": c["status"],
        "filed_at": c["filed_at"], "confirmed_at": c["confirmed_at"],
        "notes": c.get("notes"),
    }


def ser_correction(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
        "listing_id": c["listing_id"], "complaint_id": c["complaint_id"],
        "changes": c["changes"], "submitted_by_user_id": c["submitted_by_user_id"],
        "sla_due_at": c["sla_due_at"], "is_late": c["is_late"],
        "status": c["status"], "verified_at": c["verified_at"],
        "verified_by_user_id": c["verified_by_user_id"],
    }
