"""Stats: satisfaction index, breach rate, trend."""

from decimal import Decimal, ROUND_HALF_UP

from errors import AppError, ERR_VALIDATION, ERROR_STATUS
import db
import clock


def _round_half_up(value: float, decimals: int) -> float:
    q = Decimal(10) ** (-decimals)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def _filter_period(rows, ps, pe, ts_key="registered_at"):
    if ps is not None:
        ps_dt = clock.parse_iso(ps)
        rows = [r for r in rows if r.get(ts_key) and clock.parse_iso(r[ts_key]) >= ps_dt]
    if pe is not None:
        pe_dt = clock.parse_iso(pe)
        rows = [r for r in rows if r.get(ts_key) and clock.parse_iso(r[ts_key]) < pe_dt]
    return rows


def _latest_survey(wo_id: str):
    surveys = [s for s in db.all_rows("satisfaction_surveys") if s["work_order_id"] == wo_id]
    if not surveys:
        return None
    # tie-break: higher id when dispatched_at ties
    surveys.sort(key=lambda s: (s["dispatched_at"], s["id"]))
    return surveys[-1]


def _lead_assignment_active(wo_id: str):
    leads = [
        a for a in db.all_rows("department_assignments")
        if a["work_order_id"] == wo_id and a["role"] == "LEAD"
    ]
    leads = [a for a in leads if a["stage_status"] != "REASSIGNED"]
    if not leads:
        return None
    leads.sort(key=lambda a: a["dispatched_at"])
    return leads[-1]


def satisfaction_index(group_by=None, period_start=None, period_end=None,
                       department_id=None, handler_id=None) -> dict:
    if group_by is not None and group_by not in ("department", "handler"):
        raise AppError(ERR_VALIDATION, "group_by must be department or handler",
                       ERROR_STATUS[ERR_VALIDATION])

    universe = [
        w for w in db.all_rows("work_orders")
        if w["status"] in ("FOLLOWED_UP", "CLOSED", "REOPENED")
    ]
    universe = _filter_period(universe, period_start, period_end, "registered_at")
    if department_id is not None:
        universe = [w for w in universe if w.get("lead_department_id") == department_id]
    if handler_id is not None:
        kept = []
        for w in universe:
            la = _lead_assignment_active(w["id"])
            if la and la.get("handler_id") == handler_id:
                kept.append(w)
        universe = kept

    def _index_for(rows):
        if not rows:
            return 0.0
        contributions = 0
        for w in rows:
            s = _latest_survey(w["id"])
            if s is None:
                contributions += 3
            elif s["status"] == "RESPONDED":
                contributions += int(s["score"])
            elif s["status"] == "EXPIRED":
                contributions += 3
            else:
                # Still DISPATCHED: not yet expired; treat as no response → 3.
                contributions += 3
        raw = contributions / len(rows)
        return _round_half_up(raw, 2)

    if group_by is None:
        return {"satisfaction_index": _index_for(universe), "count": len(universe)}

    if group_by == "department":
        groups: dict[str, list] = {}
        for w in universe:
            key = w.get("lead_department_id") or ""
            groups.setdefault(key, []).append(w)
        result = []
        for key, rows in groups.items():
            result.append({
                "department_id": key,
                "satisfaction_index": _index_for(rows),
                "count": len(rows),
            })
        return {"group_by": "department", "groups": result}

    # group_by == handler
    groups: dict[str, list] = {}
    for w in universe:
        la = _lead_assignment_active(w["id"])
        hid = la.get("handler_id") if la else None
        if hid is None:
            continue
        groups.setdefault(hid, []).append(w)
    result = []
    for key, rows in groups.items():
        result.append({
            "handler_id": key,
            "satisfaction_index": _index_for(rows),
            "count": len(rows),
        })
    return {"group_by": "handler", "groups": result}


def breach_rate(group_by=None, period_start=None, period_end=None,
                department_id=None, category_code=None) -> dict:
    if group_by is not None and group_by not in ("department", "category"):
        raise AppError(ERR_VALIDATION, "group_by must be department or category",
                       ERROR_STATUS[ERR_VALIDATION])

    universe = [
        w for w in db.all_rows("work_orders")
        if w["status"] in ("RESOLVED", "FOLLOWED_UP", "CLOSED", "REOPENED")
    ]
    universe = _filter_period(universe, period_start, period_end, "registered_at")
    if department_id is not None:
        universe = [w for w in universe if w.get("lead_department_id") == department_id]
    if category_code is not None:
        universe = [w for w in universe if w["category_code"] == category_code]

    def _actual_resolved_at(wo_id):
        rows = [r for r in db.all_rows("audit_logs")
                if r.get("work_order_id") == wo_id and r.get("action") == "RESOLVE"]
        if not rows:
            return None
        return max(r["occurred_at"] for r in rows)

    def _rates(rows):
        if not rows:
            return {"statutory_breach_rate": 0.0, "committed_breach_rate": 0.0, "count": 0}
        stat_breaches = 0
        com_breaches = 0
        for w in rows:
            ar = _actual_resolved_at(w["id"])
            if ar is None:
                continue
            ar_dt = clock.parse_iso(ar)
            if w.get("statutory_deadline_at") and clock.parse_iso(w["statutory_deadline_at"]) < ar_dt:
                stat_breaches += 1
            if w.get("committed_deadline_at") and clock.parse_iso(w["committed_deadline_at"]) < ar_dt:
                com_breaches += 1
        # 4-decimal fraction then *100 then 2 decimals.
        stat_frac = _round_half_up(stat_breaches / len(rows), 4)
        com_frac = _round_half_up(com_breaches / len(rows), 4)
        return {
            "statutory_breach_rate": _round_half_up(stat_frac * 100, 2),
            "committed_breach_rate": _round_half_up(com_frac * 100, 2),
            "count": len(rows),
        }

    if group_by is None:
        return _rates(universe)

    if group_by == "department":
        groups: dict[str, list] = {}
        for w in universe:
            key = w.get("lead_department_id") or ""
            groups.setdefault(key, []).append(w)
        result = []
        for key, rows in groups.items():
            r = _rates(rows)
            r["department_id"] = key
            result.append(r)
        return {"group_by": "department", "groups": result}

    # group_by == category
    groups: dict[str, list] = {}
    for w in universe:
        key = w["category_code"]
        groups.setdefault(key, []).append(w)
    result = []
    for key, rows in groups.items():
        r = _rates(rows)
        r["category_code"] = key
        result.append(r)
    return {"group_by": "category", "groups": result}


def trend(period_start: str, period_end: str, bucket: str) -> dict:
    """Returns counts of REGISTERED, RESOLVED, CLOSED, REOPENED grouped by time bucket.

    bucket is 'day' | 'week' | 'month'. We use the audit log for RESOLVE/CLOSE/REOPEN events
    and WorkOrder.registered_at for REGISTERED.
    """
    if bucket not in ("day", "week", "month"):
        raise AppError(ERR_VALIDATION, "bucket must be day/week/month",
                       ERROR_STATUS[ERR_VALIDATION])
    if period_start is None or period_end is None:
        raise AppError(ERR_VALIDATION, "period_start and period_end required",
                       ERROR_STATUS[ERR_VALIDATION])
    ps = clock.parse_iso(period_start)
    pe = clock.parse_iso(period_end)

    def _bucket_key(dt_str: str) -> str:
        dt = clock.parse_iso(dt_str)
        if bucket == "day":
            return dt.strftime("%Y-%m-%d")
        if bucket == "week":
            iso = dt.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        return dt.strftime("%Y-%m")

    series: dict[str, dict[str, int]] = {}

    def _add(event: str, ts: str):
        if not ts:
            return
        dt = clock.parse_iso(ts)
        if dt < ps or dt >= pe:
            return
        k = _bucket_key(ts)
        series.setdefault(k, {"REGISTERED": 0, "RESOLVED": 0, "CLOSED": 0, "REOPENED": 0})
        series[k][event] = series[k].get(event, 0) + 1

    for w in db.all_rows("work_orders"):
        _add("REGISTERED", w.get("registered_at"))
    for r in db.all_rows("audit_logs"):
        action = r.get("action")
        if action in ("RESOLVE", "CLOSE", "REOPEN"):
            event = {"RESOLVE": "RESOLVED", "CLOSE": "CLOSED", "REOPEN": "REOPENED"}[action]
            _add(event, r.get("occurred_at"))

    buckets = sorted(series.keys())
    return {
        "bucket": bucket,
        "period_start": period_start,
        "period_end": period_end,
        "series": [{"bucket": k, **series[k]} for k in buckets],
    }
