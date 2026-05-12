"""Statistics endpoints."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

import db
from config import (
    DEFECT_CLOSED, DEFECT_NON_TERMINAL, ROLE_ANY, SEVERITIES,
)
from errors import AppError, ERR_INVALID_MODULE_KLOC, ERR_INVALID_REQUEST
from middleware import require_role
from response import success
from services.calculations import (
    compute_density, compute_rate_4dp, density_per_defect_contribution,
)
from services.validators import find_module_or_404, find_project_or_404

bp = Blueprint("statistics", __name__)


def _parse_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise AppError(ERR_INVALID_REQUEST, f"{name} must be integer", 400)


def _require_int(name):
    v = _parse_int(name)
    if v is None:
        raise AppError(ERR_INVALID_REQUEST, f"Missing query param: {name}", 400)
    return v


@bp.get("/statistics/distribution")
def distribution_report():
    require_role(ROLE_ANY)
    project_id = request.args.get("project_id")
    if not project_id:
        raise AppError(ERR_INVALID_REQUEST, "Missing project_id", 400)
    group_by = request.args.get("group_by")
    if group_by not in ("module", "severity", "assignee", "period"):
        raise AppError(ERR_INVALID_REQUEST,
                       "group_by must be one of module|severity|assignee|period", 400)
    period_start = _parse_int("period_start")
    period_end = _parse_int("period_end")
    find_project_or_404(project_id)

    defects = [d for d in db.all_rows("defects") if d["project_id"] == project_id]
    if period_start is not None and period_end is not None:
        defects = [d for d in defects
                   if period_start <= d["report_clock_minute"] < period_end]

    counts: dict = {}
    if group_by == "module":
        for d in defects:
            counts[d["module_id"]] = counts.get(d["module_id"], 0) + 1
    elif group_by == "severity":
        for sev in SEVERITIES:
            counts[sev] = 0
        for d in defects:
            counts[d["effective_severity"]] = counts.get(d["effective_severity"], 0) + 1
    elif group_by == "assignee":
        for d in defects:
            key = d.get("assignee_id") or "UNASSIGNED"
            counts[key] = counts.get(key, 0) + 1
    elif group_by == "period":
        for d in defects:
            key = str(d["report_clock_minute"])
            counts[key] = counts.get(key, 0) + 1

    return success({
        "project_id": project_id,
        "group_by": group_by,
        "period_start": period_start,
        "period_end": period_end,
        "counts": counts,
        "total": len(defects),
    })


@bp.get("/statistics/density")
def density_report():
    require_role(ROLE_ANY)
    module_id = request.args.get("module_id")
    mode = request.args.get("mode")
    if not module_id:
        raise AppError(ERR_INVALID_REQUEST, "Missing module_id", 400)
    if mode not in ("provisional", "final"):
        raise AppError(ERR_INVALID_REQUEST, "mode must be provisional|final", 400)

    module = find_module_or_404(module_id)
    if module["kloc"] is None or float(module["kloc"]) <= 0:
        raise AppError(ERR_INVALID_MODULE_KLOC, "Module.kloc must be > 0", 400)

    if mode == "provisional":
        eligible = [d for d in db.all_rows("defects")
                    if d["module_id"] == module_id
                    and d["status"] in DEFECT_NON_TERMINAL
                    and not d.get("canonical_defect_id")]
        contributions = [density_per_defect_contribution(d["effective_severity"]) for d in eligible]
        value = compute_density(contributions, float(module["kloc"]))
        return success({
            "module_id": module_id,
            "mode": "provisional",
            "kloc": float(module["kloc"]),
            "eligible_count": len(eligible),
            "density": value,
        })
    else:
        period_start = _require_int("period_start")
        period_end = _require_int("period_end")
        all_def = db.all_rows("defects")
        eligible = []
        for d in all_def:
            if d["module_id"] != module_id:
                continue
            if d["status"] != DEFECT_CLOSED:
                continue
            ffm = d.get("first_fixed_at_minute")
            if ffm is None:
                continue
            if not (period_start <= ffm < period_end):
                continue
            # Duplicates: include only if canonical is also CLOSED in the same window
            if d.get("canonical_defect_id"):
                canon = db.find_by_id("defects", d["canonical_defect_id"])
                if not canon or canon["status"] != DEFECT_CLOSED:
                    continue
                c_ffm = canon.get("first_fixed_at_minute")
                if c_ffm is None or not (period_start <= c_ffm < period_end):
                    continue
            eligible.append(d)
        contributions = [density_per_defect_contribution(d["effective_severity"]) for d in eligible]
        value = compute_density(contributions, float(module["kloc"]))
        return success({
            "module_id": module_id,
            "mode": "final",
            "period_start": period_start,
            "period_end": period_end,
            "kloc": float(module["kloc"]),
            "eligible_count": len(eligible),
            "density": value,
        })


@bp.get("/statistics/reopen-rate")
def reopen_rate_report():
    require_role(ROLE_ANY)
    module_id = request.args.get("module_id")
    if not module_id:
        raise AppError(ERR_INVALID_REQUEST, "Missing module_id", 400)
    period_start = _require_int("period_start")
    period_end = _require_int("period_end")
    find_module_or_404(module_id)

    eligible = [d for d in db.all_rows("defects")
                if d["module_id"] == module_id
                and d["status"] == DEFECT_CLOSED
                and d.get("first_fixed_at_minute") is not None
                and period_start <= d["first_fixed_at_minute"] < period_end]
    if not eligible:
        return success({
            "module_id": module_id,
            "period_start": period_start,
            "period_end": period_end,
            "eligible_count": 0,
            "reopened_count": 0,
            "rate": 0.0,
        })
    reopened = sum(1 for d in eligible if d.get("reopen_count", 0) > 0)
    rate = compute_rate_4dp(reopened, len(eligible))
    return success({
        "module_id": module_id,
        "period_start": period_start,
        "period_end": period_end,
        "eligible_count": len(eligible),
        "reopened_count": reopened,
        "rate": rate,
    })


@bp.get("/statistics/removal-rate")
def removal_rate_report():
    require_role(ROLE_ANY)
    module_id = request.args.get("module_id")
    if not module_id:
        raise AppError(ERR_INVALID_REQUEST, "Missing module_id", 400)
    period_start = _require_int("period_start")
    period_end = _require_int("period_end")
    find_module_or_404(module_id)

    discovered = [d for d in db.all_rows("defects")
                  if d["module_id"] == module_id
                  and period_start <= d["report_clock_minute"] < period_end]
    removed = [d for d in db.all_rows("defects")
               if d["module_id"] == module_id
               and d["status"] == DEFECT_CLOSED
               and d.get("first_fixed_at_minute") is not None
               and period_start <= d["first_fixed_at_minute"] < period_end]
    if not discovered:
        rate = 0.0
    else:
        rate = compute_rate_4dp(len(removed), len(discovered))
    return success({
        "module_id": module_id,
        "period_start": period_start,
        "period_end": period_end,
        "discovered_count": len(discovered),
        "removed_count": len(removed),
        "rate": rate,
    })


@bp.get("/statistics/sla-performance")
def sla_performance_report():
    require_role(ROLE_ANY)
    project_id = request.args.get("project_id")
    if not project_id:
        raise AppError(ERR_INVALID_REQUEST, "Missing project_id", 400)
    period_start = _parse_int("period_start")
    period_end = _parse_int("period_end")
    project = find_project_or_404(project_id)

    defects = [d for d in db.all_rows("defects") if d["project_id"] == project_id]
    if period_start is not None and period_end is not None:
        defects = [d for d in defects
                   if period_start <= d["report_clock_minute"] < period_end]

    by_sev = {sev: {"breached": 0, "on_time": 0} for sev in SEVERITIES}
    clock = project["clock_minute"]
    for d in defects:
        sev = d["effective_severity"]
        adjusted_now = clock - d.get("total_paused_minutes", 0)
        breached = adjusted_now > d["resolution_due_minute"]
        if breached:
            by_sev[sev]["breached"] += 1
        else:
            by_sev[sev]["on_time"] += 1

    return success({
        "project_id": project_id,
        "period_start": period_start,
        "period_end": period_end,
        "by_severity": by_sev,
        "total": len(defects),
    })
