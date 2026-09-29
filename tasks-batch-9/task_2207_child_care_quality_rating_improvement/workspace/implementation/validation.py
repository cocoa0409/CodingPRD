"""Body schema and range checking (PRD §2.7 step 6). Every failure is ERR_VALIDATION / 422."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

DOMAIN_CODES = [
    "LEARNING_ENVIRONMENT",
    "STAFF_QUALIFICATIONS",
    "FAMILY_PARTNERSHIP",
    "ADMINISTRATION",
    "CHILD_ASSESSMENT",
]
REGION_CODES = ["URBAN", "RURAL", "FRONTIER"]
ROLE_TYPES = ["DIRECTOR", "LEAD_TEACHER", "ASSISTANT"]
EMPLOYMENT_STATUSES = ["ACTIVE", "SEPARATED"]
REGISTRY_STATUSES = ["UNLINKED", "PENDING", "VERIFIED", "EXPIRED"]
CYCLE_TYPES = ["INITIAL", "RERATING", "REMAND"]
EVIDENCE_TYPES = ["POLICY", "ROSTER", "LESSON_PLAN", "FAMILY_SURVEY", "TRAINING_LOG"]
TOOL_CODES = ["ERS_INFANT_TODDLER", "ERS_EARLY_CHILDHOOD"]
SUBSCALE_CODES = [
    "SPACE_FURNISHINGS",
    "PERSONAL_CARE",
    "LANGUAGE_REASONING",
    "ACTIVITIES",
    "INTERACTION",
    "PROGRAM_STRUCTURE",
]
APPEAL_GROUNDS = ["SCORING_ERROR", "OBSERVER_RELIABILITY", "DOCUMENTATION_OMITTED", "PROCEDURAL"]
DISPUTED_FIELDS = [
    "PUBLISHED_TIER",
    "PUBLISHED_SCORE",
    "DOMAIN_POINTS",
    "LICENSED_CAPACITY",
    "COUNTY_CODE",
]
GRANT_CATEGORIES = ["EQUIPMENT", "PROF_DEV", "FACILITY", "ADMIN"]
FUNDING_SOURCES = ["GRANT", "STATE_BASE"]
AGE_BANDS = ["INFANT", "TODDLER", "PRESCHOOL"]
SCORE_VARIANTS = ["PROVISIONAL", "FINAL"]
CLAIM_VARIANTS = ["INTERIM", "RECONCILED"]

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return data


def present(data, field):
    return field in data and data[field] is not None


def req_field(data, field):
    if not present(data, field):
        fail("ERR_VALIDATION", "%s is required" % field)
    return data[field]


def req_str(data, field):
    value = req_field(data, field)
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_VALIDATION", "%s must be a non-empty string" % field)
    return value


def opt_str(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % field)
    return value


def req_enum(data, field, members):
    value = req_field(data, field)
    if not isinstance(value, str) or value not in members:
        fail("ERR_VALIDATION", "%s must be one of %s" % (field, ", ".join(members)))
    return value


def opt_enum(data, field, members, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, members)


def req_int(data, field, minimum=None, maximum=None):
    value = req_field(data, field)
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s" % (field, maximum))
    return value


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if not present(data, field):
        return default
    return req_int(data, field, minimum, maximum)


def to_decimal(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        fail("ERR_VALIDATION", "%s must be a number" % field)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_VALIDATION", "%s must be a number" % field)


def req_decimal(data, field, minimum=None, maximum=None,
                exclusive_min=False, exclusive_max=False, max_places=None):
    value = to_decimal(req_field(data, field), field)
    _check_decimal(value, field, minimum, maximum, exclusive_min, exclusive_max, max_places)
    return value


def opt_decimal(data, field, minimum=None, maximum=None,
                exclusive_min=False, exclusive_max=False, max_places=None, default=None):
    if not present(data, field):
        return default
    return req_decimal(data, field, minimum, maximum, exclusive_min, exclusive_max, max_places)


def _check_decimal(value, field, minimum, maximum, exclusive_min, exclusive_max, max_places):
    if minimum is not None:
        if exclusive_min and value <= Decimal(str(minimum)):
            fail("ERR_VALIDATION", "%s must be > %s" % (field, minimum))
        if not exclusive_min and value < Decimal(str(minimum)):
            fail("ERR_VALIDATION", "%s must be >= %s" % (field, minimum))
    if maximum is not None:
        if exclusive_max and value >= Decimal(str(maximum)):
            fail("ERR_VALIDATION", "%s must be < %s" % (field, maximum))
        if not exclusive_max and value > Decimal(str(maximum)):
            fail("ERR_VALIDATION", "%s must be <= %s" % (field, maximum))
    if max_places is not None:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > max_places:
            fail("ERR_VALIDATION", "%s must carry at most %d decimal places" % (field, max_places))


def req_object(data, field):
    value = req_field(data, field)
    if not isinstance(value, dict):
        fail("ERR_VALIDATION", "%s must be an object" % field)
    return value


def req_array(data, field, non_empty=False):
    value = req_field(data, field)
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "%s must be an array" % field)
    if non_empty and len(value) == 0:
        fail("ERR_VALIDATION", "%s must not be empty" % field)
    return value


def req_service_month(data, field="service_month"):
    value = req_field(data, field)
    if not isinstance(value, str) or not MONTH_RE.match(value):
        fail("ERR_VALIDATION", "%s must match YYYY-MM" % field)
    return value


def req_subscale_score(data, field="raw_score"):
    value = to_decimal(req_field(data, field), field)
    if value < Decimal("1.0") or value > Decimal("7.0"):
        fail("ERR_VALIDATION", "%s must lie between 1.0 and 7.0 inclusive" % field)
    if (value * 2) != (value * 2).to_integral_value():
        fail("ERR_VALIDATION", "%s must sit exactly on a half-point step" % field)
    return value


def req_child_days(data, field="child_days"):
    value = req_object(data, field)
    for key in value:
        if key not in AGE_BANDS:
            fail("ERR_VALIDATION", "%s may only carry the keys %s" % (field, ", ".join(AGE_BANDS)))
    out = {}
    for band in AGE_BANDS:
        raw = value.get(band, 0)
        if raw is None:
            raw = 0
        if isinstance(raw, bool) or not isinstance(raw, int):
            fail("ERR_VALIDATION", "%s.%s must be an integer" % (field, band))
        if raw < 0:
            fail("ERR_VALIDATION", "%s.%s must be >= 0" % (field, band))
        out[band] = raw
    return out


def req_points_map(data, field, domains_by_code):
    """A claimed/verified points map: all five domain codes, none above its point ceiling."""
    value = req_object(data, field)
    for code in DOMAIN_CODES:
        if code not in value or value[code] is None:
            fail("ERR_VALIDATION", "%s must supply all five domain codes" % field)
    out = {}
    for code, raw in value.items():
        if code not in DOMAIN_CODES:
            fail("ERR_VALIDATION", "%s carries unknown domain code %s" % (field, code))
        if isinstance(raw, bool) or not isinstance(raw, int):
            fail("ERR_VALIDATION", "%s.%s must be an integer" % (field, code))
        if raw < 0:
            fail("ERR_VALIDATION", "%s.%s must be >= 0" % (field, code))
        domain = domains_by_code.get(code)
        if domain is not None and raw > domain["max_points"]:
            fail("ERR_VALIDATION",
                 "%s.%s must not exceed the domain's max_points" % (field, code))
        out[code] = raw
    return out


# ---------------------------------------------------------------- date / time


def parse_instant(value, field):
    """Parse an ISO 8601 date or datetime into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_VALIDATION", "%s must be an ISO 8601 date or datetime string" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            fail("ERR_VALIDATION", "%s must be an ISO 8601 date or datetime string" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_instant(data, field):
    raw = req_field(data, field)
    parse_instant(raw, field)
    return raw


def opt_instant(data, field, default=None):
    if not present(data, field):
        return default
    return req_instant(data, field)


def as_date(value):
    """Calendar date of a stored date/datetime value."""
    if value is None:
        return None
    return parse_instant(value, "value").date()


def as_dt(value):
    if value is None:
        return None
    return parse_instant(value, "value")


def add_months(dt, months):
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = dt.day
    # Effective dates are always the first of a month, so no clamping is needed;
    # clamp defensively anyway.
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def iso_week_key(dt):
    iso = dt.isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])


def day_count(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - datetime(year, month, 1, tzinfo=timezone.utc)).days


def month_first_day(service_month):
    year, month = service_month.split("-")
    return datetime(int(year), int(month), 1, tzinfo=timezone.utc).date()


def days_of_month(service_month):
    year, month = [int(p) for p in service_month.split("-")]
    first = datetime(year, month, 1, tzinfo=timezone.utc).date()
    return [first + timedelta(days=i) for i in range(day_count(year, month))]
