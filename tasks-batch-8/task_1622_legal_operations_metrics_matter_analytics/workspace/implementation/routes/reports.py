import math
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_roles
from response import rows_response
from validation import pagination_params

bp = Blueprint("reports", __name__, url_prefix="/legal-ops/reports")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


def _period_arg():
    fp_id = request.args.get("fiscal_period_id")
    if fp_id is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "fiscal_period_id query parameter is required")
    period = store.fiscal_periods.get(fp_id)
    if period is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Referenced fiscal period does not exist")
    return period


def _posted_lines(period_id):
    return [
        l for l in store.spend_lines.values()
        if l["fiscal_period_id"] == period_id and l["source_status"] == "POSTED"
    ]


def _rows_page(rows):
    limit, offset = pagination_params()
    total = len(rows)
    return rows_response(rows[offset:offset + limit], total, limit, offset)


@bp.get("/spend-by-practice-area")
@require_roles(*ALL)
def spend_by_practice_area(user_id, role):
    period = _period_arg()
    totals = {}
    for l in _posted_lines(period["id"]):
        m = store.matters.get(l["matter_id"])
        if m is None:
            continue
        totals[m["practice_area_id"]] = totals.get(m["practice_area_id"], 0) + l["amount_cents"]
    rows = []
    for pa_id, total in totals.items():
        pa = store.practice_areas.get(pa_id)
        rows.append({
            "practice_area_id": pa_id,
            "code": pa["code"] if pa else None,
            "display_name": pa["display_name"] if pa else None,
            "total_spend_cents": total,
        })
    rows.sort(key=lambda r: (-r["total_spend_cents"], r["code"] or ""))
    return _rows_page(rows)


@bp.get("/spend-by-firm")
@require_roles(*ALL)
def spend_by_firm(user_id, role):
    period = _period_arg()
    totals = {}
    for l in _posted_lines(period["id"]):
        totals[l["firm_id"]] = totals.get(l["firm_id"], 0) + l["amount_cents"]
    rows = []
    for firm_id, total in totals.items():
        f = store.firms.get(firm_id)
        rows.append({
            "firm_id": firm_id,
            "name": f["name"] if f else None,
            "tier": f["tier"] if f else None,
            "total_spend_cents": total,
        })
    rows.sort(key=lambda r: (-r["total_spend_cents"], r["name"] or ""))
    return _rows_page(rows)


def _nearest_rank(sorted_vals, pct):
    if not sorted_vals:
        return None
    rank = max(1, math.ceil(pct * len(sorted_vals) / 100))
    return sorted_vals[rank - 1]


@bp.get("/cycle-time-benchmark")
@require_roles(*ALL)
def cycle_time_benchmark(user_id, role):
    period = _period_arg()
    by_type = {}
    for m in store.matters.values():
        if m["fiscal_period_id"] != period["id"]:
            continue
        if m["status"] != "CLOSED" or m["cycle_days"] is None:
            continue
        by_type.setdefault(m["matter_type_id"], []).append(m["cycle_days"])
    rows = []
    for mt_id, cycles in by_type.items():
        mt = store.matter_types.get(mt_id)
        vals = sorted(cycles)
        mean = float(
            (Decimal(sum(vals)) / Decimal(len(vals))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        rows.append({
            "matter_type_id": mt_id,
            "code": mt["code"] if mt else None,
            "display_name": mt["display_name"] if mt else None,
            "closed_count": len(vals),
            "mean_cycle_days": mean,
            "p50_cycle_days": _nearest_rank(vals, 50),
            "p90_cycle_days": _nearest_rank(vals, 90),
        })
    rows.sort(key=lambda r: (r["code"] or ""))
    return _rows_page(rows)
