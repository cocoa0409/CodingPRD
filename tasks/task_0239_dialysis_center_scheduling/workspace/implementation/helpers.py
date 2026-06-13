"""Shared helpers: request parsing, pagination, dates, calculations, adherence."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db
from errors import ApiError

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
MODALITY_BASE_CENTS = {"HEMODIALYSIS": 28500, "HEMODIAFILTRATION": 34000, "PERITONEAL": 22000}
EPO_BLOCK_CENTS = 1200
IRON_DOSE_CENTS = 4500
CONTRACTED_PCT = Decimal("0.82")
STANDARD_PCT = Decimal("1.00")

BASE_FLAG_CENTS = 800
SHARED_MULT = Decimal("0.75")
WHEELCHAIR_CENTS = 1500
CROSS_COUNTY_CENTS = 500

ROLLING_WINDOW = 8

AT_RISK_THRESHOLD = 3
SUSPEND_THRESHOLD = 5
WINDOW_DAYS = 30
MISSED_FEE_CENTS = 7500

MODALITIES = {"HEMODIALYSIS", "HEMODIAFILTRATION", "PERITONEAL"}
DAY_PATTERNS = {"MWF", "TTHS"}
PATIENT_KINDS = {"RESIDENT", "TRANSIENT"}
PAYER_CLASSES = {"CONTRACTED", "STANDARD"}
PANELS = {"MONTHLY_CHEM", "CBC", "IRON_STUDIES"}
DIRECTIONS = {"INBOUND", "OUTBOUND"}

# MWF -> Mon(0)/Wed(2)/Fri(4) ; TTHS -> Tue(1)/Thu(3)/Sat(5)
PATTERN_WEEKDAYS = {"MWF": {0, 2, 4}, "TTHS": {1, 3, 5}}


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    """Round a Decimal/number to whole cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body parsing / field validation (priority 16: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body():
    if request.data and len(request.data) > 0:
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        if not isinstance(body, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return body
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % f)


def check_string(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return val


def check_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
        return default
    val = body[field]
    if val not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' has invalid value '%s'." % (field, val))
    return val


def check_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return val


def check_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (field, maximum))
    return val


def check_number(body, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (field, maximum))
    return val


def check_iso_date(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
        return default
    val = body[field]
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO date string." % field)
    try:
        datetime.strptime(val, "%Y-%m-%d")
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % field)
    return val


def check_iso_month(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
        return None
    val = body[field]
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM month string." % field)
    try:
        datetime.strptime(val, "%Y-%m")
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM month." % field)
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be >= 1.")
        if limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be <= 100.")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(records):
    """Sort by created_at asc, apply limit/offset; return (page, pagination_meta)."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# Clinic clock
# ---------------------------------------------------------------------------
def clock_now_date():
    """Return the current clinic-clock date (a datetime.date)."""
    if db.clock_now is None:
        return datetime.now(timezone.utc).date()
    return _parse_instant(db.clock_now).date()


def _parse_instant(value):
    """Parse an ISO 8601 instant (with optional trailing Z) to a datetime."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # fall back to date-only
        return datetime.strptime(value[:10], "%Y-%m-%d")


def parse_service_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def session_charge(order, patient):
    base = MODALITY_BASE_CENTS[order["modality"]]
    epo_add = (order["epo_units"] // 1000) * EPO_BLOCK_CENTS
    iron_add = IRON_DOSE_CENTS if order["iron_ordered"] else 0
    gross = base + epo_add + iron_add
    pct = CONTRACTED_PCT if patient["payer_class"] == "CONTRACTED" else STANDARD_PCT
    return round_half_up_cents(Decimal(gross) * pct)


def coinsurance_cents(billed_amount_cents, patient):
    pct = Decimal(str(patient["coinsurance_pct"]))
    return round_half_up_cents(Decimal(billed_amount_cents) * pct)


def transport_fare(miles, cross_county, wheelchair, shared_ride):
    m = Decimal(0)
    miles_d = Decimal(str(miles))
    t1 = min(miles_d, Decimal(5))
    m += t1 * Decimal(250)
    rem = miles_d - t1
    t2 = min(rem, Decimal(10))
    m += t2 * Decimal(200)
    rem = rem - t2
    m += rem * Decimal(150)
    sub = Decimal(BASE_FLAG_CENTS) + m
    mult = SHARED_MULT if shared_ride else Decimal(1)
    sub2 = round_half_up_cents(sub * mult)
    fare = sub2 + (WHEELCHAIR_CENTS if wheelchair else 0) + (CROSS_COUNTY_CENTS if cross_county else 0)
    return fare


# ---------------------------------------------------------------------------
# No-show window + adherence (SCAFFOLD §1.3 no_show_window_rollup, PRD §3.7)
# ---------------------------------------------------------------------------
def recompute_no_show_window(patient):
    """Recompute no_show_count_window from MISSED sessions in the trailing 30-day window."""
    now = clock_now_date()
    window_start = now - timedelta(days=WINDOW_DAYS)
    count = 0
    for s in db.sessions.values():
        if s["patient_id"] != patient["id"]:
            continue
        if s["clinical_status"] != "MISSED":
            continue
        try:
            sd = parse_service_date(s["service_date"])
        except (ValueError, TypeError):
            continue
        if window_start <= sd <= now:
            count += 1
    patient["no_show_count_window"] = count
    return count


def apply_adherence_from_count(patient):
    """Drive adherence_status from no_show_count_window.

    A manual reactivate sets GOOD_STANDING without clearing the count; but a
    subsequent recompute (mark-missed / clock set) re-derives from thresholds.
    """
    count = patient["no_show_count_window"]
    if count >= SUSPEND_THRESHOLD:
        patient["adherence_status"] = "SUSPENDED"
    elif count >= AT_RISK_THRESHOLD:
        patient["adherence_status"] = "AT_RISK"
    else:
        patient["adherence_status"] = "GOOD_STANDING"


def recompute_adherence(patient):
    recompute_no_show_window(patient)
    apply_adherence_from_count(patient)


def adherence_scores(patient):
    """Compute cumulative + rolling adherence scores (PRD §3.7)."""
    qualifying = []
    for s in db.sessions.values():
        if s["patient_id"] != patient["id"]:
            continue
        if s["clinical_status"] in ("COMPLETED", "MISSED"):
            qualifying.append(s)
    qualifying.sort(key=lambda s: (s.get("service_date", ""), s.get("created_at", "")))

    def score(seq):
        c = sum(1 for s in seq if s["clinical_status"] == "COMPLETED")
        m = sum(1 for s in seq if s["clinical_status"] == "MISSED")
        denom = c + m
        if denom == 0:
            return None
        return round_half_up_1dp(Decimal(100) * Decimal(c) / Decimal(denom))

    cumulative = score(qualifying)
    rolling = score(qualifying[-ROLLING_WINDOW:])
    return {
        "cumulative_score": cumulative,
        "rolling_score": rolling,
        "no_show_count_window": patient["no_show_count_window"],
        "adherence_status": patient["adherence_status"],
    }
