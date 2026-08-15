"""EvaluationAdjustment endpoints (RegulatorAnalyst)."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from db import base_fields, store
from errors import ApiError
from lookups import get_adjustment, get_program_year
from respond import respond_list, success
from serialize import adjustment_out
from services import compute_adjusted_and_goal, touch
from validate import get_body, opt_str, req_date, req_int, req_str

bp = Blueprint("evaluation_adjustments", __name__)


@bp.post("/evaluation-adjustments")
@require_roles("RegulatorAnalyst")
def create_adjustment():
    body = get_body()
    program_year_id = req_str(body, "program_year_id")
    realization_rate_pct = req_int(body, "realization_rate_pct", minimum=0, maximum=100)
    effective_on = req_date(body, "effective_on")
    notes = opt_str(body, "notes")
    # Body FK resolution.
    py = get_program_year(program_year_id)
    # Evaluation is recorded once a year has been closed or is already reported.
    if py["status"] not in ("CLOSED", "REPORTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "ProgramYear.status is %s; evaluation adjustments require CLOSED "
            "or REPORTED" % py["status"],
        )
    rec = base_fields()
    rec.update(
        {
            "program_year_id": program_year_id,
            "realization_rate_pct": realization_rate_pct,
            "effective_on": effective_on,
            "notes": notes,
        }
    )
    store.adjustments[rec["id"]] = rec
    # Recompute immediately; this row governs only if it is the latest under
    # the max-effective_on / earliest-created tie-break rule.
    adjusted, goal_pct = compute_adjusted_and_goal(py)
    if adjusted != py["adjusted_kwh"] or goal_pct != py["goal_attainment_pct"]:
        py["adjusted_kwh"] = adjusted
        py["goal_attainment_pct"] = goal_pct
        touch(py)
    return success(adjustment_out(rec), "object", 201)


@bp.get("/evaluation-adjustments")
@require_roles(*ALL_ROLES)
def list_adjustments():
    program_year_id = request.args.get("program_year_id")
    rows = list(store.adjustments.values())
    if program_year_id is not None:
        rows = [r for r in rows if r["program_year_id"] == program_year_id]
    return respond_list(rows, adjustment_out)


@bp.get("/evaluation-adjustments/<rid>")
@require_roles(*ALL_ROLES)
def get_adjustment_route(rid):
    return success(adjustment_out(get_adjustment(rid)), "object", 200)
