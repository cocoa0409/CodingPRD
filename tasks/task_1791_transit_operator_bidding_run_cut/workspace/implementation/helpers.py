"""Request validation helpers, pagination, and shared domain logic."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db, ser
from errors import (
    ApiError,
    validation,
    not_found,
    reference_not_found,
    ERR_INVALID_RUN_PIECES,
)
from response import ok_list

BASE_RATE_CENTS_PER_MIN = 50
OT_MULTIPLIER = Decimal("1.5")
SPREAD_BREAK_THRESHOLD_MINUTES = 600
VACATION_WEEK_HOURS = 40


# ---------------------------------------------------------------------------
# Body parsing and field validation
# ---------------------------------------------------------------------------

def body_json(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise validation("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise validation("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_field(body, name):
    if name not in body or body[name] is None:
        raise validation(f"Missing required field: {name}")
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or v == "":
        raise validation(f"Field {name} must be a non-empty string")
    return v


def req_int(body, name, lo=None, hi=None):
    v = req_field(body, name)
    if not is_int(v):
        raise validation(f"Field {name} must be an integer")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise validation(f"Field {name} is outside its declared range")
    return v


def opt_int(body, name, default=None, lo=None, hi=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not is_int(v):
        raise validation(f"Field {name} must be an integer")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise validation(f"Field {name} is outside its declared range")
    return v


def req_date(body, name):
    v = req_str(body, name)
    try:
        date.fromisoformat(v)
    except ValueError:
        raise validation(f"Field {name} must be an ISO date (YYYY-MM-DD)")
    # Enforce strict YYYY-MM-DD shape
    parts = v.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise validation(f"Field {name} must be an ISO date (YYYY-MM-DD)")
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        raise validation(f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3): limit default 10 in [1,100]; offset default 0
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("Query parameter limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("Query parameter limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("Query parameter offset must be an integer")
        if offset < 0:
            raise validation("Query parameter offset must be >= 0")
    return limit, offset


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paginated(items):
    """Sort by created_at ascending and paginate; returns a Flask response."""
    limit, offset = pagination_params()
    ordered = sorted_by_created(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([ser(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_period_or_404(pid):
    p = db.sign_up_periods.get(pid)
    if p is None:
        raise not_found("Sign-up period not found")
    return p


def get_run_or_404(rid):
    r = db.runs.get(rid)
    if r is None:
        raise not_found("Run not found")
    return r


def get_operator_or_404(oid):
    o = db.operators.get(oid)
    if o is None:
        raise not_found("Operator not found")
    return o


def get_bid_or_404(bid):
    b = db.bid_entries.get(bid)
    if b is None:
        raise not_found("Bid entry not found")
    return b


def get_assignment_or_404(aid):
    a = db.daily_assignments.get(aid)
    if a is None:
        raise not_found("Daily assignment not found")
    return a


def get_absence_or_404(aid):
    a = db.absence_cases.get(aid)
    if a is None:
        raise not_found("Absence case not found")
    return a


def get_vacation_slot_or_404(vid):
    v = db.vacation_slots.get(vid)
    if v is None:
        raise not_found("Vacation slot not found")
    return v


def get_grievance_or_404(gid):
    g = db.grievance_cases.get(gid)
    if g is None:
        raise not_found("Grievance case not found")
    return g


def ref_operator_or_404(oid):
    o = db.operators.get(oid)
    if o is None:
        raise reference_not_found("Referenced operator_id does not exist")
    return o


def ref_run_or_404(rid):
    r = db.runs.get(rid)
    if r is None:
        raise reference_not_found("Referenced run_id does not exist")
    return r


def ref_period_or_404(pid):
    p = db.sign_up_periods.get(pid)
    if p is None:
        raise reference_not_found("Referenced sign_up_period_id does not exist")
    return p


# ---------------------------------------------------------------------------
# Domain logic
# ---------------------------------------------------------------------------

def recompute_seniority():
    """1 = most senior; over non-RETIRED operators; hire_date ASC, employee_number ASC."""
    eligible = [
        o for o in db.operators.values()
        if o["status"] in ("ACTIVE", "EXTRA_BOARD", "SUSPENDED")
    ]
    eligible.sort(key=lambda o: (o["hire_date"], o["employee_number"]))
    for i, o in enumerate(eligible, 1):
        o["seniority_rank"] = i


def validate_piece_shape(pieces):
    """Shape/type validation -> ERR_VALIDATION (400)."""
    if not isinstance(pieces, list) or len(pieces) == 0:
        raise validation("pieces must be a non-empty list of work pieces")
    for p in pieces:
        if not isinstance(p, dict):
            raise validation("each piece must be an object")
        for key in ("report_minutes", "release_minutes", "platform_minutes"):
            if key not in p or not is_int(p[key]):
                raise validation(f"piece field {key} must be an integer")


def check_piece_geometry(pieces):
    """Geometry validation -> ERR_INVALID_RUN_PIECES (422).

    Within a piece release > report; across the list pieces are
    non-overlapping and ascending.
    """
    prev_release = None
    for p in pieces:
        if p["release_minutes"] <= p["report_minutes"]:
            raise ApiError(
                ERR_INVALID_RUN_PIECES,
                "piece release_minutes must be later than report_minutes",
                422,
            )
        if prev_release is not None and p["report_minutes"] < prev_release:
            raise ApiError(
                ERR_INVALID_RUN_PIECES,
                "pieces must be non-overlapping and ascending",
                422,
            )
        prev_release = p["release_minutes"]


def clean_pieces(pieces):
    return [
        {
            "report_minutes": p["report_minutes"],
            "release_minutes": p["release_minutes"],
            "platform_minutes": p["platform_minutes"],
        }
        for p in pieces
    ]


def compute_run_numbers(period, pieces):
    spread = max(p["release_minutes"] for p in pieces) - min(
        p["report_minutes"] for p in pieces
    )
    platform = sum(p["platform_minutes"] for p in pieces)
    break_credit = (
        period["paid_break_minutes"] if spread >= SPREAD_BREAK_THRESHOLD_MINUTES else 0
    )
    paid = platform + break_credit
    return spread, platform, paid


def ceil_div_100(product):
    """ceil(product / 100) for a non-negative integer product."""
    return -(-product // 100)


# ---------------------------------------------------------------------------
# Pay pricing (PRD section 3.8)
# ---------------------------------------------------------------------------

def iso_week_key(date_str):
    d = date.fromisoformat(date_str)
    iso = d.isocalendar()
    return (iso[0], iso[1])


def prior_final_straight_minutes(operator_id, service_date):
    """Sum of straight_minutes over the operator's FINAL pay records whose
    assignment service dates fall in the same ISO week (computed before this
    record). PROVISIONAL records never count."""
    wk = iso_week_key(service_date)
    total = 0
    for pr in db.pay_records.values():
        if pr["variant"] != "FINAL":
            continue
        a = db.daily_assignments.get(pr["daily_assignment_id"])
        if a is None or a["operator_id"] != operator_id:
            continue
        if iso_week_key(a["service_date"]) != wk:
            continue
        total += pr["straight_minutes"]
    return total


def price_pay(period, operator_id, service_date, basis):
    """Pinned evaluation order: basis -> daily OT split -> weekly OT split -> price."""
    daily_ot = max(0, basis - period["daily_ot_threshold_minutes"])
    straight_after_daily = basis - daily_ot
    prior = prior_final_straight_minutes(operator_id, service_date)
    weekly_remaining = max(0, period["weekly_ot_threshold_minutes"] - prior)
    weekly_ot_extra = max(0, straight_after_daily - weekly_remaining)
    straight_minutes = straight_after_daily - weekly_ot_extra
    overtime_minutes = daily_ot + weekly_ot_extra
    gross = Decimal(straight_minutes * BASE_RATE_CENTS_PER_MIN) + Decimal(
        overtime_minutes * BASE_RATE_CENTS_PER_MIN
    ) * OT_MULTIPLIER
    gross_cents = int(gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return straight_minutes, overtime_minutes, gross_cents
