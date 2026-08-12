"""Shared validation / parsing / domain helpers."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_NOT_FOUND,
    ERR_CHARTER_NOT_FOUND,
    ERR_BASELINE_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_CHANGE_ORDER_NOT_FOUND,
    ERR_RISK_ENTRY_NOT_FOUND,
    ERR_DRAWDOWN_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_STAKEHOLDER_GROUP_NOT_FOUND,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_OCCUPANCY_PLAN_NOT_FOUND,
    ERR_WAVE_NOT_FOUND,
    ERR_CLOSEOUT_ITEM_NOT_FOUND,
)
from response import now_iso

ESCALATION_THRESHOLD_CENTS = 50000000
WATCH_FLOOR_PCT = 30
CRITICAL_FLOOR_PCT = 10
ENGAGEMENT_DAILY_CAP_MINUTES = 360
TURNOVER_BUFFER_HOURS = 2

STORES = {
    "program": (db.programs, ERR_PROGRAM_NOT_FOUND, "program id does not exist"),
    "charter": (db.charters, ERR_CHARTER_NOT_FOUND, "charter id does not exist"),
    "baseline": (db.baselines, ERR_BASELINE_NOT_FOUND, "baseline id does not exist"),
    "contract": (db.contracts, ERR_CONTRACT_NOT_FOUND, "contract id does not exist"),
    "change_order": (db.change_orders, ERR_CHANGE_ORDER_NOT_FOUND, "change order id does not exist"),
    "risk_entry": (db.risk_entries, ERR_RISK_ENTRY_NOT_FOUND, "risk entry id does not exist"),
    "drawdown": (db.drawdowns, ERR_DRAWDOWN_NOT_FOUND, "contingency drawdown id does not exist"),
    "owner_report": (db.owner_reports, ERR_REPORT_NOT_FOUND, "owner report id does not exist"),
    "stakeholder_group": (db.stakeholder_groups, ERR_STAKEHOLDER_GROUP_NOT_FOUND, "stakeholder group id does not exist"),
    "engagement": (db.engagements, ERR_ENGAGEMENT_NOT_FOUND, "engagement id does not exist"),
    "occupancy_plan": (db.occupancy_plans, ERR_OCCUPANCY_PLAN_NOT_FOUND, "occupancy plan id does not exist"),
    "move_in_wave": (db.move_in_waves, ERR_WAVE_NOT_FOUND, "move-in wave id does not exist"),
    "closeout_item": (db.closeout_items, ERR_CLOSEOUT_ITEM_NOT_FOUND, "closeout item id does not exist"),
    "lesson_entry": (db.lesson_entries, None, None),
}


def new_id():
    return str(uuid.uuid4())


def get_or_404(kind, rid):
    store, err_id, msg = STORES[kind]
    ent = store.get(rid)
    if ent is None:
        raise ApiError(err_id, msg, 404)
    return ent


def body():
    from flask import request
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}", 400)
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Invalid field type: {field}", 400)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, field, minimum=None, maximum=None, gt=None):
    v = data.get(field)
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid integer field: {field}", 400)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} below minimum", 400)
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} above maximum", 400)
    if gt is not None and v <= gt:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be positive", 400)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid enum field: {field}", 400)
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def req_date(data, field):
    v = req_str(data, field)
    if not _DATE_RE.match(v):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be YYYY-MM-DD", 400)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be a valid date", 400)
    return v


def req_month(data, field):
    v = req_str(data, field)
    if not _MONTH_RE.match(v):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be YYYY-MM", 400)
    try:
        datetime.strptime(v, "%Y-%m")
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be a valid month", 400)
    return v


def parse_dt(value, field):
    """Parse ISO 8601 datetime; return aware datetime in UTC."""
    if not isinstance(value, str) or not value:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid datetime field: {field}", 400)
    s = value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be ISO 8601 datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_int(numer, denom):
    """round_half_up(numer/denom) for integers -> int."""
    if denom == 0:
        return 0
    d = Decimal(numer) / Decimal(denom)
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(numer, denom):
    """round to 2 decimals half-up -> float with 2dp."""
    if denom == 0:
        return 0.0
    d = (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def touch(ent, with_version=True):
    ent["updated_at"] = now_iso()
    if with_version:
        ent["version"] += 1


def make_common(ent, with_version=True):
    ts = now_iso()
    ent["id"] = new_id()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    return ent


# ---------------------------------------------------------------------------
# Program pool / posture
# ---------------------------------------------------------------------------

def recompute_pool(program):
    pid = program["id"]
    reserved = committed = drawn = 0
    for dd in db.drawdowns.values():
        if dd["program_id"] != pid:
            continue
        if dd["status"] == "RESERVED":
            reserved += dd["amount_cents"]
        elif dd["status"] == "COMMITTED":
            committed += dd["amount_cents"]
        elif dd["status"] == "DRAWN":
            drawn += dd["amount_cents"]
    program["contingency_reserved_cents"] = reserved
    program["contingency_committed_cents"] = committed
    program["contingency_drawn_cents"] = drawn
    program["contingency_available_cents"] = (
        program["contingency_total_cents"] - reserved - committed - drawn
    )
    recompute_posture(program)


def recompute_posture(program):
    total = program["contingency_total_cents"]
    if total == 0:
        program["contingency_posture"] = "CRITICAL"
        return
    avail = program["contingency_available_cents"]
    # exact integer arithmetic: avail*100 >= floor_pct*total
    if avail * 100 >= WATCH_FLOOR_PCT * total:
        program["contingency_posture"] = "NORMAL"
    elif avail * 100 >= CRITICAL_FLOOR_PCT * total:
        program["contingency_posture"] = "WATCH"
    else:
        program["contingency_posture"] = "CRITICAL"


# ---------------------------------------------------------------------------
# OwnerReport forecast recompute
# ---------------------------------------------------------------------------

def compute_forecast(program):
    """Return dict of forecast fields computed from current program state.

    Assumes pool fields and posture on `program` are already recomputed.
    """
    pid = program["id"]
    committed = sum(
        c["current_commitment_cents"] or 0
        for c in db.contracts.values()
        if c["program_id"] == pid and c["status"] == "EXECUTED"
    )
    estimated = 0
    for c in db.contracts.values():
        if c["program_id"] != pid:
            continue
        if c["status"] in ("SOLICITED", "UNDER_NEGOTIATION"):
            estimated += c["solicitation_estimate_cents"]
        elif c["status"] == "COUNTERED":
            estimated += c["latest_counter_amount_cents"] or 0

    risk_set = [
        r for r in db.risk_entries.values()
        if r["program_id"] == pid
        and r["status"] in ("ASSESSED", "MITIGATING", "MONITORING", "ESCALATED")
    ]
    full_exposure = sum(r["exposure_cents"] for r in risk_set)

    multipliers = {
        "ESCALATED": Decimal("1.00"),
        "MONITORING": Decimal("0.50"),
        "MITIGATING": Decimal("0.35"),
        "ASSESSED": Decimal("0.25"),
    }
    weighted = Decimal(0)
    for r in risk_set:
        weighted += Decimal(r["exposure_cents"]) * multipliers[r["status"]]

    pending_co = sum(
        co["amount_cents"]
        for co in db.change_orders.values()
        if co["program_id"] == pid
        and co["status"] in ("UNDER_REVIEW", "RECOMMEND_APPROVAL", "RECOMMEND_REJECTION")
    )

    posture = program["contingency_posture"]
    if posture == "CRITICAL":
        pending_allowance = Decimal(pending_co)
    else:
        pending_allowance = Decimal(pending_co) * Decimal("0.50")

    eac_commitment = committed + estimated + full_exposure
    eac_raw = Decimal(committed) + Decimal(estimated) + weighted + pending_allowance
    eac_trend_dec = eac_raw if eac_raw >= committed else Decimal(committed)
    eac_trend = int(eac_trend_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    budget = program["current_budget_cents"]
    return {
        "eac_commitment_based_cents": eac_commitment,
        "eac_trend_based_cents": eac_trend,
        "budget_variance_commitment_cents": (budget - eac_commitment) if budget is not None else None,
        "budget_variance_trend_cents": (budget - eac_trend) if budget is not None else None,
        "contingency_posture_snapshot": posture,
        "baseline_version_no_snapshot": program["baseline_version_no"],
    }


def refresh_draft_reports(program):
    """Recompute forecast fields of every DRAFT OwnerReport for this program."""
    pid = program["id"]
    drafts = [
        r for r in db.owner_reports.values()
        if r["program_id"] == pid and r["status"] == "DRAFT"
    ]
    if not drafts:
        return
    fields = compute_forecast(program)
    for rep in drafts:
        rep.update(fields)
        touch(rep)


def bump_program(program):
    touch(program)
