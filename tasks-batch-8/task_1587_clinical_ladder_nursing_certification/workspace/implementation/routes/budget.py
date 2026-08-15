"""BudgetLine and RetentionSnapshot read endpoints."""

from flask import Blueprint, request

from clock import clock
from db import db
from errors import err_invalid_request, err_not_found, err_stale_version
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from serializers import budget_line_view, snapshot_view
from services.budget import calc_budget_commitment, calc_budget_forecast
from util import require_fields, require_int

bp = Blueprint("budget", __name__)


@bp.route("/clinical-ladder/budget-lines", methods=["POST"])
def create_budget_line():
    require_roles("ProgramAdmin")
    payload = request.get_json(silent=True)
    require_fields(payload, ["unit", "fiscal_year", "allocated_cents"])
    unit = payload.get("unit")
    if not isinstance(unit, str) or not unit:
        raise err_invalid_request("unit must be a non-empty string")
    fiscal_year = require_int(payload, "fiscal_year")
    allocated = require_int(payload, "allocated_cents")
    if allocated < 0:
        raise err_invalid_request("allocated_cents must be >= 0")

    for line in db.budget_lines.values():
        if line["unit"] == unit and line["fiscal_year"] == fiscal_year:
            raise err_invalid_request("One BudgetLine per (unit, fiscal_year)")

    now = clock.now()
    line = {
        "id": db.new_id(),
        "unit": unit,
        "fiscal_year": fiscal_year,
        "allocated_cents": allocated,
        "committed_cents": 0,
        "forecast_cents": 0,
        "forecast_variant": "PROVISIONAL",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.budget_lines[line["id"]] = line
    # Creation immediately initializes commitment and forecast
    line["committed_cents"] = calc_budget_commitment(line)
    line["forecast_cents"] = calc_budget_forecast(line)
    return success_object(budget_line_view(line), status=201)


@bp.route("/clinical-ladder/budget-lines", methods=["GET"])
def list_budget_lines():
    require_roles("ProgramAdmin", "PayrollOfficer")
    limit, offset = parse_pagination(request.args)
    unit = request.args.get("unit")
    fiscal_year = request.args.get("fiscal_year")
    rows = sorted(db.budget_lines.values(), key=lambda b: b["created_at"])
    if unit is not None:
        rows = [b for b in rows if b["unit"] == unit]
    if fiscal_year is not None:
        try:
            fy = int(fiscal_year)
        except ValueError:
            raise err_invalid_request("fiscal_year must be an integer")
        rows = [b for b in rows if b["fiscal_year"] == fy]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([budget_line_view(b) for b in page], limit, offset, total)


@bp.route("/clinical-ladder/budget-lines/<bid>", methods=["GET"])
def get_budget_line(bid):
    require_roles("ProgramAdmin", "PayrollOfficer")
    line = db.budget_lines.get(bid)
    if line is None:
        raise err_not_found("BudgetLine not found")
    return success_object(budget_line_view(line))


@bp.route("/clinical-ladder/budget-lines/<bid>", methods=["PUT"])
def update_budget_line(bid):
    require_roles("ProgramAdmin")
    line = db.budget_lines.get(bid)
    if line is None:
        raise err_not_found("BudgetLine not found")
    payload = request.get_json(silent=True)
    require_fields(payload, ["allocated_cents", "expected_budget_line_version"])
    allocated = require_int(payload, "allocated_cents")
    expected_version = require_int(payload, "expected_budget_line_version")
    if allocated < 0:
        raise err_invalid_request("allocated_cents must be >= 0")
    if expected_version != line["version"]:
        raise err_stale_version()

    line["allocated_cents"] = allocated
    line["version"] += 1
    line["updated_at"] = clock.now()
    line["forecast_cents"] = calc_budget_forecast(line)
    return success_object(budget_line_view(line))


@bp.route("/clinical-ladder/retention-snapshots", methods=["GET"])
def list_snapshots():
    require_roles("RetentionAnalyst", "ProgramAdmin")
    limit, offset = parse_pagination(request.args)
    unit = request.args.get("unit")
    rows = sorted(db.retention_snapshots.values(), key=lambda s: s["created_at"])
    if unit is not None:
        rows = [s for s in rows if s["unit"] == unit]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([snapshot_view(s) for s in page], limit, offset, total)
