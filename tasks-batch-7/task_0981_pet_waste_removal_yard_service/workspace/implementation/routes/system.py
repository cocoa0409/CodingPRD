"""Test-driving endpoints: logical clock and scheduled-action runners."""
from flask import Blueprint

import services as svc
from clock import now, set_now, iso
from errors import ApiError
from middleware import auth, get_body, require
from response import ok_object

bp = Blueprint("system", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    auth("OperationsManager")
    data = get_body()
    target = None
    raw = require(data, "to_iso8601", str)
    from clock import parse_dt
    try:
        target = parse_dt(raw)
    except ValueError:
        from errors import err_invalid_request
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 datetime")
    set_now(target)
    svc.apply_pending_plan_changes()
    return ok_object({"current_utc": iso(now())})


@bp.post("/api/_system/vacation-window-applier/run")
def run_vacation_window_applier():
    auth("OperationsManager")
    applied = []
    current = now()
    due = sorted(
        (
            w
            for w in svc.vacation_windows.values()
            if w["window_status"] == "SCHEDULED" and w["start_date"] <= current
        ),
        key=lambda w: w["_seq"],
    )
    for w in due:
        sub = svc.subscriptions.get(w["subscription_id"])
        if sub is None or sub["status"] not in ("ACTIVE", "PAUSED"):
            continue
        w["window_status"] = "APPLIED"
        svc.bump(w)
        start_d = w["start_date"].date()
        end_d = w["end_date"].date()
        for v in list(svc.visits.values()):
            if (
                v["subscription_id"] == sub["id"]
                and v["status"] == "SCHEDULED"
                and start_d <= v["scheduled_date"].date() <= end_d
            ):
                svc.finalize_visit_skip(
                    v,
                    "VACATION",
                    sub,
                    post_credit=True,
                    credit_line_type="VACATION_CREDIT",
                )
        applied.append(w["id"])
    return ok_object({"applied_window_ids": applied})


@bp.post("/api/_system/end-of-day-sweep/run")
def run_end_of_day_sweep():
    auth("OperationsManager")
    missed = []
    current = now()
    due = sorted(
        (
            v
            for v in svc.visits.values()
            if v["status"] == "SCHEDULED" and current > v["scheduled_window_end"]
        ),
        key=lambda v: v["_seq"],
    )
    for v in due:
        v["status"] = "MISSED"
        v["skip_source"] = "OTHER"
        v["final_visit_charge_cents"] = 0
        svc.bump(v)
        route = svc.visit_route(v)
        if route is not None:
            svc.recompute_route(route)
            svc.maybe_auto_close_route(route)
        sub = svc.subscriptions.get(v["subscription_id"])
        if sub is not None:
            inv = svc.charge_target_invoice(sub["customer_id"], v["scheduled_date"])
            svc.post_line(
                inv,
                "SATISFACTION_CREDIT",
                "Good-will credit (missed visit)",
                1,
                0,
                visit_id=v["id"],
            )
        missed.append(v["id"])
    return ok_object({"missed_visit_ids": missed})
