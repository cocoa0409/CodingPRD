"""Outcome linkages (PRD §3.8)."""

from flask import Blueprint, request

from db import db, stamp_new_immutable, touch, public, now_iso
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
)
from middleware import (
    require_roles, parse_pagination, paginate, get_json_body, require_fields,
    optional_fields_present, as_non_empty_string, as_enum,
)
from response import success_object, success_list
from services import calculations as calc

bp = Blueprint("outcomes", __name__)

OUTCOME_KINDS = {"ATTRITION", "PERFORMANCE"}
ATTRITION_VALUES = {"VOLUNTARY", "INVOLUNTARY", "NONE"}
PERFORMANCE_VALUES = {"BELOW", "MEETS", "EXCEEDS"}


def _get_employee_or_404(emp_id):
    emp = db.employees.get(emp_id)
    if emp is None:
        raise err(ERR_NOT_FOUND, "employee not found", 404)
    return emp


@bp.post("/engagement/employees/<emp_id>/outcome-linkages")
def create_outcome_linkage(emp_id):
    require_roles("PeopleAnalyst")
    emp = _get_employee_or_404(emp_id)
    body = get_json_body()
    optional_fields_present(body, {"cycle_id", "outcome_kind", "outcome_value"})
    require_fields(body, ["cycle_id", "outcome_kind", "outcome_value"])
    cycle_id = as_non_empty_string(body["cycle_id"], "cycle_id")
    outcome_kind = as_enum(body["outcome_kind"], "outcome_kind", OUTCOME_KINDS)
    outcome_value = body["outcome_value"]
    if outcome_kind == "ATTRITION":
        outcome_value = as_enum(outcome_value, "outcome_value", ATTRITION_VALUES)
    else:
        outcome_value = as_enum(outcome_value, "outcome_value", PERFORMANCE_VALUES)

    if cycle_id not in db.survey_cycles:
        raise err(ERR_REFERENCE_NOT_FOUND, "cycle_id does not exist", 404)

    linkage = stamp_new_immutable({
        "employee_id": emp["id"],
        "cycle_id": cycle_id,
        "outcome_kind": outcome_kind,
        "outcome_value": outcome_value,
        "recorded_at": now_iso(),
    })
    db.outcome_linkages[linkage["id"]] = linkage

    # Attrition linkage refreshes the cycle's attrition_risk (final variant).
    if outcome_kind == "ATTRITION":
        cycle = db.survey_cycles[cycle_id]
        new_risk = calc.compute_attrition_risk(cycle, provisional=False)
        if cycle.get("attrition_risk") != new_risk:
            cycle["attrition_risk"] = new_risk
            touch(cycle)

    return success_object(public(linkage), 201)


@bp.get("/engagement/employees/<emp_id>/outcome-linkages")
def list_employee_outcome_linkages(emp_id):
    require_roles("HRAdmin", "PeopleAnalyst")
    emp = _get_employee_or_404(emp_id)
    limit, offset = parse_pagination({"cycle_id"})
    cycle_id = request.args.get("cycle_id")
    items = [ol for ol in db.outcome_linkages.values() if ol["employee_id"] == emp["id"]]
    if cycle_id is not None:
        items = [ol for ol in items if ol["cycle_id"] == cycle_id]
    page, total = paginate(items, limit, offset)
    return success_list([public(ol) for ol in page], limit, offset, total)


@bp.get("/engagement/outcome-linkages")
def list_outcome_linkages():
    require_roles("HRAdmin", "PeopleAnalyst")
    limit, offset = parse_pagination({"cycle_id", "employee_id", "outcome_kind"})
    cycle_id = request.args.get("cycle_id")
    employee_id = request.args.get("employee_id")
    outcome_kind = request.args.get("outcome_kind")
    items = list(db.outcome_linkages.values())
    if cycle_id is not None:
        items = [ol for ol in items if ol["cycle_id"] == cycle_id]
    if employee_id is not None:
        items = [ol for ol in items if ol["employee_id"] == employee_id]
    if outcome_kind is not None:
        items = [ol for ol in items if ol["outcome_kind"] == outcome_kind]
    page, total = paginate(items, limit, offset)
    return success_list([public(ol) for ol in page], limit, offset, total)


@bp.get("/engagement/outcome-linkages/<linkage_id>")
def get_outcome_linkage(linkage_id):
    require_roles("HRAdmin", "PeopleAnalyst")
    ol = db.outcome_linkages.get(linkage_id)
    if ol is None:
        raise err(ERR_NOT_FOUND, "outcome linkage not found", 404)
    return success_object(public(ol))
