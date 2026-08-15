"""ProgramYear endpoints: CRUD, OCC-guarded config update, lifecycle."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from db import base_fields, now_iso, store
from errors import ApiError
from lookups import get_program_year
from respond import respond_list, success
from serialize import program_year_out
from services import (
    CLOSE_BLOCKING_STATUSES,
    compute_adjusted_and_goal,
    recompute_eval,
    touch,
)
from validate import get_body, opt_int, req_int, req_str

bp = Blueprint("program_years", __name__)


@bp.post("/program-years")
@require_roles("ProgramAdministrator")
def create_program_year():
    body = get_body()
    program_code = req_str(body, "program_code")
    program_year_label = req_str(body, "program_year_label")
    budget_cap_cents = req_int(body, "budget_cap_cents", minimum=1)
    savings_goal_kwh = req_int(body, "savings_goal_kwh", minimum=1)
    for existing in store.program_years.values():
        if existing["program_code"] == program_code:
            raise ApiError(
                "ERR_DUPLICATE_UNIQUE_FIELD",
                409,
                "program_code '%s' is already in use" % program_code,
            )
    rec = base_fields()
    rec.update(
        {
            "program_code": program_code,
            "program_year_label": program_year_label,
            "budget_cap_cents": budget_cap_cents,
            "savings_goal_kwh": savings_goal_kwh,
            "committed_cents": 0,
            "paid_cents": 0,
            "reported_kwh": 0,
            "adjusted_kwh": 0,
            "goal_attainment_pct": 0,
            "status": "DRAFT",
            "opened_at": None,
        }
    )
    store.program_years[rec["id"]] = rec
    return success(program_year_out(rec), "object", 201)


@bp.get("/program-years")
@require_roles(*ALL_ROLES)
def list_program_years():
    status = request.args.get("status")
    rows = list(store.program_years.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond_list(rows, program_year_out)


@bp.get("/program-years/<rid>")
@require_roles(*ALL_ROLES)
def get_program_year_route(rid):
    return success(program_year_out(get_program_year(rid)), "object", 200)


@bp.put("/program-years/<rid>")
@require_roles("ProgramAdministrator")
def update_program_year(rid):
    py = get_program_year(rid)
    body = get_body()
    expected = req_int(body, "expected_program_year_version")
    budget_cap_cents = opt_int(body, "budget_cap_cents", minimum=1)
    savings_goal_kwh = opt_int(body, "savings_goal_kwh", minimum=1)
    if expected != py["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_program_year_version %s does not match current version %s"
            % (expected, py["version"]),
        )
    if budget_cap_cents is not None:
        py["budget_cap_cents"] = budget_cap_cents
    if savings_goal_kwh is not None:
        py["savings_goal_kwh"] = savings_goal_kwh
    # Derived fields stay reconciled against the (possibly new) configuration.
    recompute_eval(py)
    touch(py)
    return success(program_year_out(py), "object", 200)


@bp.post("/program-years/<rid>/open")
@require_roles("ProgramAdministrator")
def open_program_year(rid):
    py = get_program_year(rid)
    if py["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "ProgramYear.status is %s; open requires DRAFT" % py["status"],
        )
    has_active_measure = any(
        m for m in store.measures.values()
        if m["program_year_id"] == py["id"] and m["is_active"]
    )
    if not has_active_measure:
        raise ApiError(
            "ERR_NO_ACTIVE_MEASURES",
            422,
            "ProgramYear has no active measure in its catalog",
        )
    py["status"] = "OPEN"
    py["opened_at"] = now_iso()
    touch(py)
    return success(program_year_out(py), "object", 200)


@bp.post("/program-years/<rid>/close")
@require_roles("ProgramAdministrator")
def close_program_year(rid):
    py = get_program_year(rid)
    if py["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "ProgramYear.status is %s; close requires OPEN" % py["status"],
        )
    blockers = [
        a for a in store.applications.values()
        if a["program_year_id"] == py["id"] and a["status"] in CLOSE_BLOCKING_STATUSES
    ]
    if blockers:
        raise ApiError(
            "ERR_OPEN_APPLICATIONS_REMAIN",
            409,
            "ProgramYear still has %d application(s) in an open pipeline state"
            % len(blockers),
        )
    # Auto-settle every still-APPROVED application, created_at ascending.
    approved = sorted(
        (
            a for a in store.applications.values()
            if a["program_year_id"] == py["id"] and a["status"] == "APPROVED"
        ),
        key=lambda a: (a["created_at"], a["_seq"]),
    )
    for app in approved:
        app["status"] = "PAID"
        touch(app)
        # Each cascaded payment is a first-class program-year mutation.
        py["committed_cents"] -= app["incentive_total_cents"]
        py["paid_cents"] += app["incentive_total_cents"]
        touch(py)
    py["status"] = "CLOSED"
    touch(py)
    return success(program_year_out(py), "object", 200)


@bp.post("/program-years/<rid>/report")
@require_roles("RegulatorAnalyst")
def report_program_year(rid):
    py = get_program_year(rid)
    if py["status"] != "CLOSED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "ProgramYear.status is %s; report requires CLOSED" % py["status"],
        )
    has_adjustment = any(
        a for a in store.adjustments.values() if a["program_year_id"] == py["id"]
    )
    if not has_adjustment:
        raise ApiError(
            "ERR_NO_EVALUATION_ADJUSTMENT",
            422,
            "REPORTED transition requires at least one EvaluationAdjustment",
        )
    adjusted, goal_pct = compute_adjusted_and_goal(py)
    py["adjusted_kwh"] = adjusted
    py["goal_attainment_pct"] = goal_pct
    py["status"] = "REPORTED"
    touch(py)
    return success(program_year_out(py), "object", 200)
