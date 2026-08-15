from datetime import timedelta

from flask import Blueprint

from core import (ApiError, body, db, new_resource, now, ok,
                  opt_int, req_str, require_roles, touch)
from logic import cell_touch
from serializers import ser_run

bp = Blueprint("refresh", __name__)


def get_run_or_404(run_id):
    r = db.runs.get(run_id)
    if r is None:
        raise ApiError("ERR_REFRESH_RUN_NOT_FOUND", 404, "Refresh run not found")
    return r


def _grace_expired_lapsed(grace_days):
    cutoff = now() - timedelta(days=grace_days)
    out = [p for p in db.panelists.values()
           if p["status"] == "LAPSED" and p["lapsed_at"] is not None
           and p["lapsed_at"] <= cutoff]
    out.sort(key=lambda p: p["_seq"])
    return out


@bp.post("/feedback-panel/refresh-runs")
@require_roles("PanelManager")
def create_run():
    data = body()
    run_label = req_str(data, "run_label")
    grace = opt_int(data, "attrition_grace_days", 30)
    run = new_resource()
    run.update({
        "run_label": run_label,
        "attrition_grace_days": grace,
        "planned_attrition_count": len(_grace_expired_lapsed(grace)),
        "applied_attrition_count": None,
        "applied_forfeit_count": None,
        "status": "OPEN",
    })
    db.runs[run["id"]] = run
    return ok(ser_run(run), 201)


@bp.get("/feedback-panel/refresh-runs/<run_id>")
@require_roles("PanelManager")
def get_run(run_id):
    return ok(ser_run(get_run_or_404(run_id)))


@bp.post("/feedback-panel/refresh-runs/<run_id>/apply")
@require_roles("PanelManager")
def apply_run(run_id):
    run = get_run_or_404(run_id)
    if run["status"] != "OPEN":
        raise ApiError("ERR_REFRESH_RUN_NOT_OPEN", 409,
                       "Apply requires refresh run status OPEN")
    attrited = 0
    forfeited = 0
    for p in _grace_expired_lapsed(run["attrition_grace_days"]):
        p["status"] = "ATTRITED"
        touch(p)
        attrited += 1
        cell = db.cells.get(p["home_cell_id"])
        if cell is not None:
            cell["active_count"] -= 1
            cell_touch(cell)
        for a in db.awards.values():
            if a["_panelist_id"] == p["id"] and a["payout_status"] == "AUTHORIZED":
                a["payout_status"] = "FORFEITED"
                touch(a)
                forfeited += 1
                wave = db.waves[a["wave_id"]]
                wave["incentive_pool_reserved_cents"] -= a["amount_cents"]
                wave["incentive_pool_available_cents"] += a["amount_cents"]
                touch(wave)
    run["applied_attrition_count"] = attrited
    run["applied_forfeit_count"] = forfeited
    run["status"] = "APPLIED"
    touch(run)
    return ok(ser_run(run))


@bp.post("/feedback-panel/refresh-runs/<run_id>/abort")
@require_roles("PanelManager")
def abort_run(run_id):
    run = get_run_or_404(run_id)
    if run["status"] != "OPEN":
        raise ApiError("ERR_REFRESH_RUN_NOT_OPEN", 409,
                       "Abort requires refresh run status OPEN")
    run["status"] = "ABORTED"
    touch(run)
    return ok(ser_run(run))
