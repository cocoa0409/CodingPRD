"""Shared validation and business-logic helpers (PRD §2, §3).

Covers: request-body shape checks (ERR_INVALID_REQUEST), entity lookup
(ERR_NOT_FOUND), common system fields, day-count rollup with the combined
180-day cap (§3.3), read-time projected counts, live TRIR/DART rates (§2.6),
establishment risk score / posture (§2.7), summary rollups (§3.7), the
citation contest deadline (§3.8) and the overdue sweep driven by the logical
clock (§2.4).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import (STORE, now_dt, now_iso, fmt_iso, parse_datetime, parse_date,
                new_id)
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND)

DAY_CAP = 180
HOURS_BASE = 200000


# ---------------------------------------------------------------------------
# Request body shape validation (ERR_INVALID_REQUEST; PRD §2.9 — evaluated
# after authentication/authorization, before any business rule)
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data() or b""
        if raw.strip():
            raise_error(ERR_INVALID_REQUEST, "Malformed JSON request body")
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, non_empty=False):
    if not _present(data, name) or not isinstance(data[name], str):
        raise_error(ERR_INVALID_REQUEST,
                    "Missing or invalid required field: %s" % name)
    if non_empty and not data[name].strip():
        raise_error(ERR_INVALID_REQUEST,
                    "Field must be a non-empty string: %s" % name)
    return data[name]


def opt_str(data, name, non_empty=False):
    if not _present(data, name):
        return None
    if not isinstance(data[name], str):
        raise_error(ERR_INVALID_REQUEST, "Field must be a string: %s" % name)
    if non_empty and not data[name].strip():
        raise_error(ERR_INVALID_REQUEST,
                    "Field must be a non-empty string: %s" % name)
    return data[name]


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    if not isinstance(data[name], bool):
        raise_error(ERR_INVALID_REQUEST, "Field must be a boolean: %s" % name)
    return data[name]


def req_int(data, name, minimum=None):
    v = data.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST,
                    "Missing or invalid required integer field: %s" % name)
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST,
                    "Field %s must be >= %s" % (name, minimum))
    return v


def opt_int(data, name):
    if not _present(data, name):
        return None
    v = data[name]
    if not isinstance(v, int) or isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, "Field must be an integer: %s" % name)
    return v


def req_number(data, name):
    v = data.get(name)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST,
                    "Missing or invalid required numeric field: %s" % name)
    return v


def opt_number(data, name):
    if not _present(data, name):
        return None
    v = data[name]
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, "Field must be a number: %s" % name)
    return v


def req_enum(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST,
                    "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    v = data[name]
    if not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST,
                    "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def req_dt(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST,
                    "Missing or invalid required datetime field: %s" % name)
    try:
        return parse_datetime(v)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST,
                    "Field %s must be an ISO 8601 datetime" % name)


def req_date(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST,
                    "Missing or invalid required date field: %s" % name)
    try:
        return parse_date(v)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST,
                    "Field %s must be an ISO 8601 date (YYYY-MM-DD)" % name)


def req_version(data, name):
    v = data.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST,
                    "Missing or invalid required field: %s" % name)
    return v


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def lookup(collection, rid):
    ent = collection.get(rid)
    if ent is None:
        raise_error(ERR_NOT_FOUND, "Resource not found: %s" % rid)
    return ent


def base_fields():
    """Common system-managed fields (PRD §2.5). version starts at 1."""
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": STORE.next_seq()}


def bump(ent):
    """version += 1 and refresh updated_at (PRD §2.5)."""
    ent["version"] += 1
    ent["updated_at"] = now_iso()


def serialize(ent):
    """Public view: strip internal underscore-prefixed bookkeeping keys."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST,
                    "Query parameter %s must be an integer" % name)


def query_str(name):
    return request.args.get(name)


def paginated(items):
    """PRD §2.3: limit (default 10, min 1, max 100), offset (default 0).

    Lists sort by created_at ascending; creation sequence breaks ties.
    Returns (page_items, limit, offset, total_count).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Day counting (PRD §3.3) — RECORDED stored variant + PROJECTED_FINAL read-time
# ---------------------------------------------------------------------------

def apply_day_cap(days_away, restricted):
    """Combined 180-day ceiling; days away take precedence under the cap."""
    if days_away + restricted <= DAY_CAP:
        return days_away, restricted
    da = min(days_away, DAY_CAP)
    return da, DAY_CAP - da


def rollup_case(case):
    """RECORDED variant: full entry spans, combined-capped. Stored fields."""
    da = re_ = 0
    for e in STORE.day_entries.values():
        if e["case_id"] == case["id"] and e["status"] == "ACTIVE":
            if e["day_type"] == "DAYS_AWAY":
                da += e["calendar_days"]
            else:
                re_ += e["calendar_days"]
    case["days_away_count"], case["restricted_days_count"] = apply_day_cap(da, re_)


def day_count_closed(case):
    """True once entries stop accruing: explicit close, 180-day cap reached,
    employee separated, or case finalized (finalization required closure)."""
    if case["status"] == "FINALIZED" or case["_manual_day_close"]:
        return True
    if case["days_away_count"] + case["restricted_days_count"] >= DAY_CAP:
        return True
    emp = STORE.employees.get(case["employee_id"])
    return bool(emp and emp["employment_status"] == "SEPARATED")


def projected_counts(case):
    """PROJECTED_FINAL variant: ACTIVE entries whose end_date lies strictly
    after the logical clock date are truncated at the clock date; the combined
    cap is applied after truncation. Read-time only, never stored."""
    clock_d = now_dt().date()
    da = re_ = 0
    for e in STORE.day_entries.values():
        if e["case_id"] != case["id"] or e["status"] != "ACTIVE":
            continue
        start = parse_date(e["start_date"])
        end = parse_date(e["end_date"])
        if end > clock_d:
            days = (clock_d - start).days + 1
            if days < 0:
                days = 0
        else:
            days = e["calendar_days"]
        if e["day_type"] == "DAYS_AWAY":
            da += days
        else:
            re_ += days
    return apply_day_cap(da, re_)


def serialize_case(case):
    d = serialize(case)
    d["day_count_closed"] = day_count_closed(case)
    proj_da, proj_re = projected_counts(case)
    d["projected_days_away_count"] = proj_da
    d["projected_restricted_days_count"] = proj_re
    return d


# ---------------------------------------------------------------------------
# Rates (PRD §2.6, §3.7) and establishment risk posture (PRD §2.7)
# ---------------------------------------------------------------------------

def _round1(dec):
    return float(dec.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def rate_1dp(numerator_count, hours):
    return _round1(Decimal(numerator_count * HOURS_BASE) / Decimal(hours))


def live_rates(est_id, year):
    """LIVE variant: recomputed from current data; cases counted by latest
    classification; hours only from APPROVED/LOCKED logs; null rates when the
    year's hours are zero."""
    n_rec = n_dart = 0
    for c in STORE.cases.values():
        if c["establishment_id"] == est_id and c["log_year"] == year:
            if c["is_recordable"]:
                n_rec += 1
            if c["is_dart"]:
                n_dart += 1
    hours = sum(h["hours_worked"] for h in STORE.hour_logs.values()
                if h["establishment_id"] == est_id and h["year"] == year
                and h["status"] in ("APPROVED", "LOCKED"))
    if hours <= 0:
        return None, None, n_rec, n_dart, 0
    return rate_1dp(n_rec, hours), rate_1dp(n_dart, hours), n_rec, n_dart, hours


def citation_establishment_id(citation):
    insp = STORE.inspections.get(citation["inspection_id"])
    return insp["establishment_id"] if insp else None


def recompute_posture(est):
    """Weighted risk score + derived posture (PRD §2.7, inclusive bounds)."""
    est_id = est["id"]
    clock = now_dt()
    trir, dart, _, _, _ = live_rates(est_id, clock.year)
    t = Decimal(str(trir)) if trir is not None else Decimal("0.0")
    d = Decimal(str(dart)) if dart is not None else Decimal("0.0")
    overdue_ca = sum(1 for ca in STORE.corrective_actions.values()
                     if ca["establishment_id"] == est_id
                     and ca["status"] == "OVERDUE")
    overdue_ci = sum(1 for ci in STORE.citations.values()
                     if ci["status"] == "OVERDUE"
                     and citation_establishment_id(ci) == est_id)
    cutoff = clock - timedelta(days=365)
    late_severe = 0
    for r in STORE.severe_reports.values():
        if r["status"] != "LATE":
            continue
        c = STORE.cases.get(r["case_id"])
        if not c or c["establishment_id"] != est_id:
            continue
        filed = parse_datetime(r["reported_to_agency_at"])
        if filed >= cutoff:
            late_severe += 1
    score = (Decimal("2.0") * t + Decimal("3.0") * d
             + Decimal("5.0") * overdue_ca + Decimal("8.0") * overdue_ci
             + Decimal("10.0") * late_severe)
    score = score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    est["risk_score"] = float(score)
    if score >= Decimal("50"):
        est["posture"] = "ELEVATED"
    elif score >= Decimal("25"):
        est["posture"] = "WATCH"
    else:
        est["posture"] = "CLEAR"


def recompute_current_year_hours(est):
    """Sum of APPROVED/LOCKED hour logs for the clock's current year."""
    year = now_dt().year
    est["current_year_hours"] = sum(
        h["hours_worked"] for h in STORE.hour_logs.values()
        if h["establishment_id"] == est["id"] and h["year"] == year
        and h["status"] in ("APPROVED", "LOCKED"))


# ---------------------------------------------------------------------------
# Annual summary rollup and case-mutation side effects (PRD §3.2, §3.7)
# ---------------------------------------------------------------------------

def summary_case_totals(s):
    """Case-derived totals. Per-case counts are capped first, then summed."""
    est_id, year = s["establishment_id"], s["year"]
    n_rec = n_dart = da = re_ = 0
    for c in STORE.cases.values():
        if (c["establishment_id"] == est_id and c["log_year"] == year
                and c["is_recordable"]):
            n_rec += 1
            if c["is_dart"]:
                n_dart += 1
            da += c["days_away_count"]
            re_ += c["restricted_days_count"]
    s["total_recordable_cases"] = n_rec
    s["total_dart_cases"] = n_dart
    s["total_days_away"] = da
    s["total_restricted_days"] = re_


def summary_full_rollup(s):
    """Prepare/amend rollup: case totals + employment average + hours + rates."""
    summary_case_totals(s)
    est_id, year = s["establishment_id"], s["year"]
    logs = [h for h in STORE.hour_logs.values()
            if h["establishment_id"] == est_id and h["year"] == year
            and h["status"] in ("APPROVED", "LOCKED")]
    emp_sum = sum(h["employment_count"] for h in logs)
    s["annual_avg_employment"] = int(
        (Decimal(emp_sum) / Decimal(12)).quantize(Decimal("1"),
                                                  rounding=ROUND_HALF_UP))
    hours = sum(h["hours_worked"] for h in logs)
    s["total_hours_worked"] = hours
    if hours > 0:
        s["trir"] = rate_1dp(s["total_recordable_cases"], hours)
        s["dart_rate"] = rate_1dp(s["total_dart_cases"], hours)
    else:
        s["trir"] = None
        s["dart_rate"] = None


def case_set_pin(est_id, year):
    """Aggregate case-set version for the summary certification pin (§3.7)."""
    return sum(c["version"] for c in STORE.cases.values()
               if c["establishment_id"] == est_id and c["log_year"] == year)


def on_case_mutation(case):
    """Case mutation side effects: recompute DRAFT/PREPARED summary totals,
    bounce PREPARED -> DRAFT (clearing prepared_by and provisional rates,
    advancing version), and mark CERTIFIED summaries amendment-required."""
    est_id, year = case["establishment_id"], case["log_year"]
    for s in STORE.summaries.values():
        if s["establishment_id"] != est_id or s["year"] != year:
            continue
        if s["status"] == "PREPARED":
            s["status"] = "DRAFT"
            s["prepared_by"] = None
            s["trir"] = None
            s["dart_rate"] = None
            s["_prepared_pin"] = None
            summary_case_totals(s)
            bump(s)
        elif s["status"] == "DRAFT":
            summary_case_totals(s)
            bump(s)
        elif s["status"] == "CERTIFIED":
            s["_amendment_required"] = True


# ---------------------------------------------------------------------------
# Citations: 15-working-day contest deadline (PRD §3.8)
# ---------------------------------------------------------------------------

def contest_deadline_for(created_dt):
    """Day 0 is the creation date (following Monday if created on a weekend);
    count 15 working days (Mon-Fri) forward; deadline at 23:59:59Z."""
    d = created_dt.date()
    if d.weekday() == 5:      # Saturday -> following Monday
        d += timedelta(days=2)
    elif d.weekday() == 6:    # Sunday -> following Monday
        d += timedelta(days=1)
    remaining = 15
    cur = d
    while remaining > 0:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            remaining -= 1
    return datetime(cur.year, cur.month, cur.day, 23, 59, 59,
                    tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Logical-clock compliance sweep (PRD §2.4)
# ---------------------------------------------------------------------------

def sweep_overdue():
    """Move due-passed CorrectiveActions (OPEN/REOPENED) and Citations
    (ABATEMENT_PENDING) to OVERDUE; recompute posture and current-year hours."""
    clock_d = now_dt().date()
    affected = set()
    for ca in STORE.corrective_actions.values():
        if (ca["status"] in ("OPEN", "REOPENED")
                and parse_date(ca["due_date"]) < clock_d):
            ca["status"] = "OVERDUE"
            bump(ca)
            affected.add(ca["establishment_id"])
    for ci in STORE.citations.values():
        if (ci["status"] == "ABATEMENT_PENDING"
                and parse_date(ci["abatement_due_date"]) < clock_d):
            ci["status"] = "OVERDUE"
            bump(ci)
            est_id = citation_establishment_id(ci)
            if est_id:
                affected.add(est_id)
    for est in STORE.establishments.values():
        recompute_current_year_hours(est)
    for est_id in affected:
        est = STORE.establishments.get(est_id)
        if est:
            recompute_posture(est)
