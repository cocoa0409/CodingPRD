"""Core: in-memory store, logical clock, envelope helpers, money/date helpers,
serializers, and the ApiError type for the Home-Equity Investment API."""

import calendar
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from fractions import Fraction

# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
ROLES = {
    "Homeowner",
    "InvestmentAnalyst",
    "Appraiser",
    "ClosingAgent",
    "Inspector",
    "ComplianceOfficer",
}
ALL_ROLES = list(ROLES)

# --------------------------------------------------------------------------
# In-memory store (starts empty on every boot — no seeding)
# --------------------------------------------------------------------------
DB = {
    "funds": {},
    "homeowners": {},
    "applications": {},
    "valuations": {},
    "appraisers": {},
    "appointments": {},
    "offers": {},
    "agreements": {},
    "liens": {},
    "inspectors": {},
    "inspections": {},
    "settlements": {},
    "disputes": {},
}

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Logical clock (default 2026-07-01T00:00:00Z, never wall-clock)
# --------------------------------------------------------------------------
_clock = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.
    Returns None if unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_format(dt):
    """ISO-8601 UTC string with exactly three fractional (millisecond) digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso_format(get_clock())


def add_months(dt, n):
    """Add n calendar months to dt, clamping the day to the target month length."""
    month_index = dt.month - 1 + n
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def whole_calendar_months(start, end):
    """Number of whole calendar months elapsed from start to end (floor)."""
    approx = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, approx) > end:
        approx -= 1
    return max(0, approx)


# --------------------------------------------------------------------------
# Money helpers
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to the nearest whole cent, half up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_cents(value):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def D(value):
    return Decimal(str(value))


# --------------------------------------------------------------------------
# ApiError
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(
        random.choices(string.ascii_letters + string.digits, k=20)
    )


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    return {"meta": _meta(), "response_type": "object", "data": data}, status


def success_array(items, limit, offset, total_count, status=200):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return (
        {"meta": _meta(meta_extra), "response_type": "array", "data": items},
        status,
    )


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# Common record scaffolding
# --------------------------------------------------------------------------
def base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec, bump_version=False):
    rec["updated_at"] = now_iso()
    if bump_version:
        rec["version"] += 1


# --------------------------------------------------------------------------
# Fund capital reconciliation (computed on read)
# --------------------------------------------------------------------------
AGREEMENT_COMMITTING_STATES = {
    "FUNDED",
    "ACTIVE",
    "EXIT_INITIATED",
    "SETTLEMENT_PROPOSED",
    "DISPUTED",
}


def fund_committed(fund_id):
    total = 0
    for o in DB["offers"].values():
        if o["fund_id"] == fund_id and o["status"] == "PRESENTED":
            total += o["investment_amount_cents"]
    for a in DB["agreements"].values():
        if a["fund_id"] == fund_id and a["status"] in AGREEMENT_COMMITTING_STATES:
            total += a["investment_amount_cents"]
    return total


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
_COMMON = ("id", "created_at", "updated_at", "version")


def _pick(rec, fields):
    return {k: rec[k] for k in fields}


def ser_fund(r):
    committed = fund_committed(r["id"])
    out = _pick(r, _COMMON)
    out.update(
        {
            "name": r["name"],
            "total_capital_cents": r["total_capital_cents"],
            "committed_capital_cents": committed,
            "available_capital_cents": r["total_capital_cents"] - committed,
        }
    )
    return out


def ser_homeowner(r):
    out = _pick(r, _COMMON)
    out.update({"email": r["email"], "full_name": r["full_name"]})
    return out


def ser_application(r):
    out = _pick(r, _COMMON)
    for k in (
        "homeowner_id",
        "fund_id",
        "property_address",
        "property_type",
        "homeowner_estimated_value_cents",
        "existing_mortgage_balance_cents",
        "requested_investment_cents",
        "status",
        "combined_ltv",
        "risk_band",
    ):
        out[k] = r[k]
    return out


def ser_valuation(r):
    out = _pick(r, _COMMON)
    for k in (
        "application_id",
        "method",
        "valued_amount_cents",
        "confidence_score",
        "source_appointment_id",
        "status",
    ):
        out[k] = r[k]
    return out


def ser_appraiser(r):
    out = _pick(r, _COMMON)
    out.update({"full_name": r["full_name"], "region_code": r["region_code"]})
    return out


def ser_appointment(r):
    out = _pick(r, _COMMON)
    for k in (
        "appraiser_id",
        "valuation_id",
        "region_code",
        "scheduled_start",
        "scheduled_end",
        "status",
    ):
        out[k] = r[k]
    return out


def ser_offer(r):
    out = _pick(r, _COMMON)
    for k in (
        "application_id",
        "fund_id",
        "valuation_id",
        "investment_amount_cents",
        "option_percentage",
        "risk_adjustment_pct",
        "term_months",
        "capped_annual_rate",
        "expires_at",
        "adjusted_start_value_cents",
        "status",
        "counter_notes",
    ):
        out[k] = r[k]
    return out


def ser_agreement(r):
    out = _pick(r, _COMMON)
    for k in (
        "offer_id",
        "application_id",
        "fund_id",
        "investment_amount_cents",
        "option_percentage",
        "adjusted_start_value_cents",
        "term_months",
        "capped_annual_rate",
        "funded_at",
        "maturity_at",
        "status",
        "covenant_status",
    ):
        out[k] = r[k]
    return out


def ser_lien(r):
    out = _pick(r, _COMMON)
    for k in ("agreement_id", "title_status", "lien_position", "status"):
        out[k] = r[k]
    return out


def ser_inspector(r):
    out = _pick(r, _COMMON)
    out.update({"full_name": r["full_name"], "region_code": r["region_code"]})
    return out


def ser_inspection(r):
    out = _pick(r, _COMMON)
    for k in (
        "agreement_id",
        "inspector_id",
        "scheduled_date",
        "status",
        "condition_score",
    ):
        out[k] = r[k]
    return out


def ser_settlement(r):
    out = _pick(r, _COMMON)
    for k in (
        "agreement_id",
        "settlement_type",
        "sale_price_cents",
        "current_appraised_value_cents",
        "mortgage_payoff_cents",
        "ending_value_cents",
        "elapsed_months",
        "appreciation_share_cents",
        "settlement_fee_cents",
        "net_proceeds_cents",
        "homeowner_payout_cents",
        "status",
        "proposed_by_user_id",
    ):
        out[k] = r[k]
    return out


def ser_dispute(r):
    out = _pick(r, _COMMON)
    for k in (
        "settlement_id",
        "agreement_id",
        "reason",
        "disputed_value_cents",
        "resolved_value_cents",
        "status",
        "resolved_by_user_id",
    ):
        out[k] = r[k]
    return out
