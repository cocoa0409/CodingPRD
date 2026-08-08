"""Core: in-memory store, logical clock, response envelope, errors, calculations."""
import random
import string
import uuid
import threading
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Constants (from PRD / SCAFFOLD)
# ---------------------------------------------------------------------------
COI_MIN_COVERAGE_CENTS = 5000000
DAYS_PER_MONTH_CONVENTION = 30
FEE_RATE_TIER1 = Decimal("0.12")   # 30..59 days
FEE_RATE_TIER2 = Decimal("0.10")   # 60..89 days
FEE_RATE_TIER3 = Decimal("0.08")   # >=90 days
UTILITIES_SURCHARGE_RATE = Decimal("0.02")
MIN_FEE_CENTS = 5000
MAX_FEE_CENTS = 200000
TAX_EXEMPT_MIN_DAYS = 30
OCCUPANCY_TAX_RATE = Decimal("0.14")

CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

KNOWN_ROLES = {"Anonymous", "Host", "Tenant", "ComplianceReviewer", "PlatformAdmin"}

# Pagination
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.tables = {
            "hosts": {},
            "tenants": {},
            "verifications": {},
            "units": {},
            "bookings": {},
            "extensions": {},
            "deposits": {},
            "damage_claims": {},
            "coi_policies": {},
            "turnovers": {},
            "payouts": {},
            "tax_assessments": {},
        }
        self._seq = 0
        self.clock = _parse_iso(CLOCK_DEFAULT_ISO)

    def next_seq(self):
        self._seq += 1
        return self._seq


# ---------------------------------------------------------------------------
# Timestamps / ids
# ---------------------------------------------------------------------------
def now_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_uuid():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_record(fields):
    ts = now_ts()
    rec = {
        "id": new_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Logical clock helpers
# ---------------------------------------------------------------------------
def _parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("bad iso")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a YYYY-MM-DD date string; raise ValueError on failure."""
    if not isinstance(s, str):
        raise ValueError("bad date")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def date_midnight_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def clock_reached(date_str):
    """True if logical clock >= midnight-UTC of the given YYYY-MM-DD date."""
    d = parse_date(date_str)
    return DB.clock >= date_midnight_utc(d)


# Instantiate the store once the clock helpers it depends on are defined.
DB = Store()


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal to a whole integer using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def days_between(start_str, end_str):
    return (parse_date(end_str) - parse_date(start_str)).days


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def provisional_rent_cents(monthly_rate_cents, term_days):
    return round_half_up(Decimal(monthly_rate_cents) * Decimal(term_days) / Decimal(DAYS_PER_MONTH_CONVENTION))


def _days_in_month(year, month):
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def final_rent_cents(monthly_rate_cents, start_str, end_str):
    """Calendar per-month proration, round each month then sum (half-open window)."""
    start = parse_date(start_str)
    end = parse_date(end_str)  # exclusive
    total = 0
    cur = start
    while cur < end:
        y, m = cur.year, cur.month
        dim = _days_in_month(y, m)
        # first day of next month
        if m == 12:
            month_end = date(y + 1, 1, 1)
        else:
            month_end = date(y, m + 1, 1)
        seg_end = min(end, month_end)
        covered = (seg_end - cur).days
        total += round_half_up(Decimal(monthly_rate_cents) * Decimal(covered) / Decimal(dim))
        cur = month_end
    return total


def cleaning_charge_cents(unit):
    return 0 if unit.get("cleaning_included") else int(unit.get("cleaning_fee_cents") or 0)


def platform_fee_cents(gross_rent_cents, term_days, utilities_included):
    if term_days >= 90:
        base_rate = FEE_RATE_TIER3
    elif term_days >= 60:
        base_rate = FEE_RATE_TIER2
    else:
        base_rate = FEE_RATE_TIER1
    surcharge = UTILITIES_SURCHARGE_RATE if utilities_included else Decimal("0")
    effective_rate = base_rate + surcharge
    raw_fee = round_half_up(Decimal(gross_rent_cents) * effective_rate)
    return min(MAX_FEE_CENTS, max(MIN_FEE_CENTS, raw_fee))


def occupancy_tax(assessed_term_days, gross_rent_cents):
    if assessed_term_days >= TAX_EXEMPT_MIN_DAYS:
        return {"taxable": False, "occupancy_tax_cents": 0, "exempt_reason": "MID_TERM_30_DAY"}
    return {
        "taxable": True,
        "occupancy_tax_cents": round_half_up(Decimal(gross_rent_cents) * OCCUPANCY_TAX_RATE),
        "exempt_reason": "NONE",
    }


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_ts()}
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    return {"meta": _meta(), "response_type": "object", "data": data}, status


def success_array(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return body, status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
