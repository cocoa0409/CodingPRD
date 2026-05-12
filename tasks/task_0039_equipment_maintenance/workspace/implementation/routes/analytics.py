"""Reliability analytics: MTTR, MTBF, fault recurrence, availability."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, parse_iso
from errors import ERR_BAD_REQUEST, ERR_NOT_FOUND, raise_err
from middleware import require_role
from response import success_object
from services.calculations import round_half_up
from services.common import get_site_or_404

bp = Blueprint("analytics", __name__)

FAILURE_DRIVEN = {"ALARM", "PLAN_TRIGGER", "AD_HOC"}
VALID_SCOPES = {"EQUIPMENT", "CATEGORY", "SITE"}


def _parse_window():
    ws = request.args.get("window_start")
    we = request.args.get("window_end")
    if not ws or not we:
        raise_err(ERR_BAD_REQUEST, "window_start and window_end required")
    try:
        wsd = parse_iso(ws)
        wed = parse_iso(we)
    except Exception:
        raise_err(ERR_BAD_REQUEST, "invalid window datetimes")
    if wed <= wsd:
        raise_err(ERR_BAD_REQUEST, "window_end must be > window_start")
    return wsd, wed


def _filter_scope(work_orders, scope, scope_id, site_id):
    """Filter for scope: EQUIPMENT (scope_id is equipment id), CATEGORY (scope_id is category), SITE."""
    if scope == "EQUIPMENT":
        if not scope_id:
            raise_err(ERR_BAD_REQUEST, "scope_id required for EQUIPMENT scope")
        eq = db.equipment.get(scope_id)
        if eq is None or eq["site_id"] != site_id:
            raise_err(ERR_NOT_FOUND, "equipment not found")
        return [w for w in work_orders if w["equipment_id"] == scope_id]
    if scope == "CATEGORY":
        if not scope_id:
            raise_err(ERR_BAD_REQUEST, "scope_id required for CATEGORY scope")
        ids = {e["id"] for e in db.equipment_for_site(site_id) if e["category"] == scope_id}
        return [w for w in work_orders if w["equipment_id"] in ids]
    return work_orders  # SITE


@bp.route("/sites/<site_id>/analytics/mttr", methods=["GET"])
def mttr(site_id):
    require_role(["SiteManager", "Dispatcher"])
    get_site_or_404(site_id)
    scope = request.args.get("scope")
    if scope not in VALID_SCOPES:
        raise_err(ERR_BAD_REQUEST, "invalid scope")
    scope_id = request.args.get("scope_id")
    ws, we = _parse_window()
    mode = request.args.get("mode", "active")
    if mode not in {"active", "wallclock"}:
        raise_err(ERR_BAD_REQUEST, "invalid mode")

    pool = [
        w for w in db.work_orders_for_site(site_id)
        if w.get("completed_at") is not None
        and ws <= w["completed_at"] < we
        and w["source"] in FAILURE_DRIVEN
    ]
    pool = _filter_scope(pool, scope, scope_id, site_id)

    if not pool:
        return success_object({"mttr_minutes": None, "sample_size": 0})

    if mode == "wallclock":
        values = [(w["completed_at"] - w["started_at"]).total_seconds() / 60.0 for w in pool]
    else:
        values = [w["total_active_minutes"] for w in pool]

    mean = sum(values) / len(values)
    return success_object({
        "mttr_minutes": round_half_up(mean, 2),
        "sample_size": len(pool),
    })


@bp.route("/sites/<site_id>/analytics/mtbf", methods=["GET"])
def mtbf(site_id):
    require_role(["SiteManager", "Dispatcher"])
    get_site_or_404(site_id)
    scope = request.args.get("scope")
    if scope not in VALID_SCOPES:
        raise_err(ERR_BAD_REQUEST, "invalid scope")
    scope_id = request.args.get("scope_id")
    ws, we = _parse_window()

    base_pool = [
        w for w in db.work_orders_for_site(site_id)
        if w.get("completed_at") is not None
        and ws <= w["completed_at"] < we
        and w["source"] in FAILURE_DRIVEN
    ]
    base_pool = _filter_scope(base_pool, scope, scope_id, site_id)

    # Group by equipment
    by_eq = {}
    for w in base_pool:
        by_eq.setdefault(w["equipment_id"], []).append(w)

    # Determine equipment in scope (so empty-set equipment can be skipped)
    if scope == "EQUIPMENT":
        eq_ids = [scope_id] if scope_id in by_eq else []
        # If specific equipment but no completions: result null, gap_count 0
        if scope_id not in by_eq:
            return success_object({"mtbf_hours": None, "gap_count": 0})
    elif scope == "CATEGORY":
        eq_ids = [eid for eid in by_eq.keys()]
    else:
        eq_ids = [eid for eid in by_eq.keys()]

    per_eq_values = []
    per_eq_counts = []
    total_gaps = 0
    for eid in eq_ids:
        ws_list = sorted(by_eq.get(eid, []), key=lambda x: (x["completed_at"], x["id"]))
        gaps = []
        for i in range(1, len(ws_list)):
            curr = ws_list[i]
            prev = ws_list[i - 1]
            if curr.get("started_at") is None:
                continue
            gap = (curr["started_at"] - prev["completed_at"]).total_seconds()
            if gap > 0:
                gaps.append(gap)
        if not gaps:
            continue
        per_eq_values.append(sum(gaps) / len(gaps) / 3600.0)
        per_eq_counts.append(len(gaps))
        total_gaps += len(gaps)

    if not per_eq_values:
        return success_object({"mtbf_hours": None, "gap_count": 0})

    if scope == "EQUIPMENT":
        result = per_eq_values[0]
    else:
        # Weighted mean by gap count
        numer = sum(v * c for v, c in zip(per_eq_values, per_eq_counts))
        denom = sum(per_eq_counts)
        result = numer / denom if denom else None

    return success_object({
        "mtbf_hours": round_half_up(result, 2),
        "gap_count": total_gaps,
    })


@bp.route("/sites/<site_id>/analytics/fault-recurrence", methods=["GET"])
def fault_recurrence(site_id):
    require_role(["SiteManager", "Dispatcher"])
    get_site_or_404(site_id)
    look_back_days = request.args.get("look_back_days", "30")
    try:
        look_back_days = int(look_back_days)
    except (ValueError, TypeError):
        raise_err(ERR_BAD_REQUEST, "look_back_days must be integer")
    if look_back_days <= 0:
        raise_err(ERR_BAD_REQUEST, "look_back_days must be positive")

    site_clock = db.site_clock(site_id)
    window_start = site_clock - timedelta(seconds=look_back_days * 86400)

    items = []
    for eq in db.equipment_for_site(site_id):
        completions = [
            w for w in db.work_orders_for_equipment(eq["id"])
            if w.get("completed_at") is not None
            and w["source"] in FAILURE_DRIVEN
            and window_start <= w["completed_at"] < site_clock
        ]
        completions.sort(key=lambda w: (w["completed_at"], w["id"]))
        recurrences = 0
        for i in range(1, len(completions)):
            curr = completions[i]
            prev = completions[i - 1]
            if curr.get("started_at") is None:
                continue
            gap = (curr["started_at"] - prev["completed_at"]).total_seconds()
            if 0 < gap <= 7 * 86400:
                recurrences += 1
        denom = max(len(completions) - 1, 1)
        rate = recurrences / denom if denom else 0
        items.append({
            "equipment_id": eq["id"],
            "recurrence_rate": round_half_up(rate, 4),
            "completion_count": len(completions),
        })
    return success_object({"items": items})


@bp.route("/sites/<site_id>/analytics/availability", methods=["GET"])
def availability(site_id):
    require_role(["SiteManager", "Dispatcher"])
    get_site_or_404(site_id)
    equipment_id = request.args.get("equipment_id")
    if not equipment_id:
        raise_err(ERR_BAD_REQUEST, "equipment_id required")
    eq = db.equipment.get(equipment_id)
    if eq is None or eq["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "equipment not found")
    ws, we = _parse_window()
    mode = request.args.get("mode", "provisional")
    if mode not in {"provisional", "final"}:
        raise_err(ERR_BAD_REQUEST, "invalid mode")

    site_clock = db.site_clock(site_id)
    window_seconds = (we - ws).total_seconds()
    downtime = 0.0

    for w in db.work_orders_for_equipment(equipment_id):
        if w["source"] not in FAILURE_DRIVEN:
            continue
        if w.get("started_at") is None:
            continue
        if w["started_at"] >= we:
            continue
        completed = w.get("completed_at")
        if mode == "final":
            if completed is None:
                continue
            end = completed
        else:  # provisional
            end = completed if completed is not None else site_clock
        if end <= ws:
            continue
        # Overlap
        seg_start = max(w["started_at"], ws)
        seg_end = min(end, we)
        if seg_end > seg_start:
            downtime += (seg_end - seg_start).total_seconds()

    avail = (window_seconds - downtime) / window_seconds if window_seconds > 0 else 0
    return success_object({
        "availability": round_half_up(avail, 4),
        "downtime_seconds": int(downtime),
    })
