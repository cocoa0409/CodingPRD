"""Source-quality analytics (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_role
import services as svc
from util import check_enum, respond_object, parse_dt, round_half_up_decimal

bp = Blueprint("analytics", __name__)


def _rate(numerator, denominator):
    """Decimal fraction rounded half-up to 6 decimal places, as a JSON number."""
    if denominator == 0:
        return 0.0
    q = round_half_up_decimal(Decimal(numerator) / Decimal(denominator), 6)
    return float(q)


@bp.get("/erp/analytics/source-quality")
def source_quality():
    group_by = request.args.get("group_by")
    if group_by is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required query parameter: group_by")
    check_enum(group_by, svc.GROUP_BY_DIMS, "group_by")
    require_role("TalentAdmin", "Recruiter")

    raw_start = request.args.get("window_start")
    raw_end = request.args.get("window_end")
    window_start = None
    window_end = None
    if raw_start is not None:
        window_start = parse_dt(raw_start)
        if window_start is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Unparseable window_start")
    if raw_end is not None:
        window_end = parse_dt(raw_end)
        if window_end is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Unparseable window_end")
    # Defaults: from the beginning of time up to the logical now; both ends
    # inclusive.
    if window_end is None:
        window_end = store.clock

    groups = {}
    for r in svc.sort_by_created(store.referrals.values()):
        submitted = r["submitted_at"]
        if window_start is not None and submitted < window_start:
            continue
        if submitted > window_end:
            continue
        if group_by == "REFERRER_LEVEL":
            referrer = store.employees.get(r["referrer_id"])
            key = referrer["job_level"] if referrer is not None else None
        elif group_by == "REQ_DEPARTMENT":
            req = store.requisitions.get(r["job_requisition_id"])
            key = req["department"] if req is not None else None
        else:  # CAMPAIGN: attached or not
            key = "ATTACHED" if r["campaign_id"] else "NOT_ATTACHED"
        if key is None:
            continue
        g = groups.setdefault(key, {
            "group": key,
            "submissions": 0,
            "hires": 0,
            "retention_met": 0,
            "total_bonus_paid_cents": 0,
        })
        g["submissions"] += 1
        # Hires: referrals that ever reached HIRED (hire_date is stamped at hire).
        if r["hire_date"] is not None:
            g["hires"] += 1
        if r["status"] == "COMPLETED":
            g["retention_met"] += 1
        for m in svc.milestones_of(r["id"]):
            if m["status"] == "PAID":
                g["total_bonus_paid_cents"] += m["amount_cents"]

    out = []
    for key in sorted(groups.keys()):
        g = groups[key]
        if g["submissions"] == 0:
            continue
        out.append({
            "group": g["group"],
            "submissions": g["submissions"],
            "hires": g["hires"],
            "retention_met": g["retention_met"],
            "hire_rate_raw": _rate(g["hires"], g["submissions"]),
            "hire_rate_adjusted": _rate(g["hires"] + 5, g["submissions"] + 10),
            "low_confidence": g["submissions"] < 10,
            "total_bonus_paid_cents": g["total_bonus_paid_cents"],
        })
    return respond_object({"groups": out})
