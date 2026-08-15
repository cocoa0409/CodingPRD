"""Association endpoints."""

from flask import request, Blueprint
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from errors import (
    make_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STATE_RULE_MISSING,
    ERR_NO_ADOPTED_STUDY, ERR_ANNUAL_UPDATE_ALREADY_RUN,
)
from services.fiscal import fiscal_year_for_date
from services.calculations import (
    recompute_study_totals, find_adopted_study, compute_percent_funded, compute_ffb,
    reevaluate_compliance, find_state_rule,
)
from datetime import timedelta

bp = Blueprint("associations", __name__)


def serialize_association(assoc):
    # Compute derived fields on read
    state_rule = _find_state_rule(assoc["state_code"])
    next_visit_due = _compute_next_site_visit_due(assoc["id"], state_rule)
    annual_update_overdue = _compute_annual_update_overdue(assoc, state_rule)

    return {
        "id": assoc["id"],
        "created_at": assoc["created_at"],
        "updated_at": assoc["updated_at"],
        "version": assoc["version"],
        "name": assoc["name"],
        "state_code": assoc["state_code"],
        "fiscal_year_end_month": assoc["fiscal_year_end_month"],
        "reserve_cash_balance_cents": assoc["reserve_cash_balance_cents"],
        "current_annual_contribution_cents": assoc.get("current_annual_contribution_cents", 0),
        "last_annual_update_fiscal_year": assoc.get("last_annual_update_fiscal_year"),
        "statutory_compliance_status": assoc["statutory_compliance_status"],
        "next_site_visit_due_date": next_visit_due,
        "annual_update_overdue": annual_update_overdue,
    }


def _find_state_rule(state_code):
    for r in store.state_reserve_rules.values():
        if r["state_code"] == state_code:
            return r
    return None


def _compute_next_site_visit_due(association_id, state_rule):
    """Latest COMPLETED visit_date + 365 * site_visit_interval_years days."""
    completed = [
        v for v in store.site_visits.values()
        if v["association_id"] == association_id and v["status"] == "COMPLETED"
    ]
    if not completed or not state_rule:
        return None
    completed.sort(key=lambda v: v["visit_date"], reverse=True)
    latest = completed[0]
    from datetime import date
    visit_date = date.fromisoformat(latest["visit_date"])
    days = 365 * state_rule["site_visit_interval_years"]
    due = visit_date + timedelta(days=days)
    return due.isoformat()


def _compute_annual_update_overdue(assoc, state_rule):
    if not state_rule or not state_rule.get("annual_update_required", False):
        return False
    current_fy = fiscal_year_for_date(store.now_date(), assoc["fiscal_year_end_month"])
    last_fy = assoc.get("last_annual_update_fiscal_year")
    if last_fy is None or last_fy < current_fy:
        return True
    return False


@bp.route("/associations", methods=["POST"])
def create_association():
    require_roles("ReserveSpecialist")
    body = request.get_json(force=True, silent=True) or {}

    required = ["name", "state_code", "fiscal_year_end_month", "reserve_cash_balance_cents"]
    allowed = set(required) | {"current_annual_contribution_cents"}
    for field in required:
        if field not in body:
            raise make_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    for key in body:
        if key not in allowed:
            raise make_error(ERR_INVALID_REQUEST, f"Unknown field: {key}")

    # Validate types
    if not isinstance(body["name"], str):
        raise make_error(ERR_INVALID_REQUEST, "name must be a string")
    if not isinstance(body["state_code"], str):
        raise make_error(ERR_INVALID_REQUEST, "state_code must be a string")
    if not isinstance(body["fiscal_year_end_month"], int) or not (1 <= body["fiscal_year_end_month"] <= 12):
        raise make_error(ERR_INVALID_REQUEST, "fiscal_year_end_month must be 1-12")
    if not isinstance(body["reserve_cash_balance_cents"], int) or body["reserve_cash_balance_cents"] < 0:
        raise make_error(ERR_INVALID_REQUEST, "reserve_cash_balance_cents must be a non-negative integer")
    if "current_annual_contribution_cents" in body:
        if not isinstance(body["current_annual_contribution_cents"], int) or body["current_annual_contribution_cents"] < 0:
            raise make_error(ERR_INVALID_REQUEST, "current_annual_contribution_cents must be a non-negative integer")

    # Check state rule exists
    state_rule = _find_state_rule(body["state_code"])
    if not state_rule:
        raise make_error(ERR_STATE_RULE_MISSING, f"No state rule for {body['state_code']}")

    assoc = store.make_common_fields()
    assoc.update({
        "name": body["name"],
        "state_code": body["state_code"],
        "fiscal_year_end_month": body["fiscal_year_end_month"],
        "reserve_cash_balance_cents": body["reserve_cash_balance_cents"],
        "current_annual_contribution_cents": body.get("current_annual_contribution_cents", 0),
        "last_annual_update_fiscal_year": None,
        "statutory_compliance_status": "COMPLIANCE_UNKNOWN",
    })
    store.associations[assoc["id"]] = assoc
    return success_object(serialize_association(assoc), 201)


@bp.route("/associations/<id>", methods=["GET"])
def get_association(id):
    require_roles(*ANY_ROLE)
    assoc = store.associations.get(id)
    if not assoc:
        raise make_error(ERR_NOT_FOUND, f"Association {id} not found")
    return success_object(serialize_association(assoc))


@bp.route("/associations/<id>/annual-update", methods=["POST"])
def annual_update(id):
    require_roles("ReserveSpecialist")
    assoc = store.associations.get(id)
    if not assoc:
        raise make_error(ERR_NOT_FOUND, f"Association {id} not found")

    # Must have current ADOPTED study
    adopted = find_adopted_study(id)
    if adopted is None:
        raise make_error(ERR_NO_ADOPTED_STUDY, "Association has no current ADOPTED study")

    # Check not already run this fiscal year
    current_fy = fiscal_year_for_date(store.now_date(), assoc["fiscal_year_end_month"])
    last_fy = assoc.get("last_annual_update_fiscal_year")
    if last_fy is not None and current_fy <= last_fy:
        raise make_error(ERR_ANNUAL_UPDATE_ALREADY_RUN, "Annual update already ran for this fiscal year")

    # 1) Roll down ACTIVE components of the adopted study
    components = [
        c for c in store.components.values()
        if c["study_id"] == adopted["id"] and c["status"] == "ACTIVE"
    ]
    for c in components:
        c["remaining_useful_life_years"] = max(0, c["remaining_useful_life_years"] - 1)
        store.touch(c)

    # 2) Recompute study totals
    recompute_study_totals(adopted)

    # 3) Create ANNUAL_STATEMENT disclosure
    state_rule = _find_state_rule(assoc["state_code"])
    disclosure_days = state_rule["disclosure_deadline_days"] if state_rule else 0
    from datetime import datetime, timezone, timedelta
    due_date = (store.get_clock() + timedelta(days=disclosure_days)).strftime("%Y-%m-%d")

    disclosure = store.make_common_fields()
    disclosure.update({
        "study_id": adopted["id"],
        "disclosure_type": "ANNUAL_STATEMENT",
        "status": "PENDING",
        "due_date": due_date,
        "distributed_at": None,
    })
    store.disclosures[disclosure["id"]] = disclosure

    # 4) Stamp last_annual_update_fiscal_year
    assoc["last_annual_update_fiscal_year"] = current_fy
    store.touch(assoc)

    # 5) Re-evaluate compliance
    reevaluate_compliance(assoc)

    return success_object(serialize_association(assoc))
