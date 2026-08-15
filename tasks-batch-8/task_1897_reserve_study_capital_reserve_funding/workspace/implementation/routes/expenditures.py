"""Expenditure endpoints."""

from flask import request, Blueprint
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from errors import (
    make_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_NO_ADOPTED_STUDY, ERR_COMPONENT_NOT_CURRENT, ERR_CASH_INSUFFICIENT,
    ERR_REVERSAL_WINDOW_CLOSED,
)
from services.fiscal import fiscal_year_for_date
from services.calculations import (
    find_adopted_study, find_chronological_anchor,
    compute_expenditure_planned, compute_variance, compute_tolerance,
    compute_forward_variance, recompute_study_totals,
)
from services.calculations import reevaluate_compliance

bp = Blueprint("expenditures", __name__)

VALID_KINDS = {"PLANNED_REPLACEMENT", "UNPLANNED_REPAIR"}


def serialize_expenditure(exp):
    # Forward-looking variance recomputed live on every read
    planned_fwd, variance_fwd = compute_forward_variance(exp)
    return {
        "id": exp["id"],
        "created_at": exp["created_at"],
        "updated_at": exp["updated_at"],
        "version": exp["version"],
        "association_id": exp["association_id"],
        "component_id": exp["component_id"],
        "amount_cents": exp["amount_cents"],
        "incurred_date": exp["incurred_date"],
        "kind": exp["kind"],
        "fiscal_year": exp["fiscal_year"],
        "approval_status": exp["approval_status"],
        "reconciliation_status": exp["reconciliation_status"],
        "planned_chronological_cents": exp.get("planned_chronological_cents"),
        "variance_chronological_cents": exp.get("variance_chronological_cents"),
        "planned_forward_cents": planned_fwd,
        "variance_forward_cents": variance_fwd,
        "component_rul_before_years": exp.get("component_rul_before_years"),
        "approved_at": exp.get("approved_at"),
    }


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


@bp.route("/expenditures", methods=["POST"])
def create_expenditure():
    require_roles("AssociationManager")
    body = request.get_json(force=True, silent=True) or {}

    required = ["association_id", "component_id", "amount_cents", "incurred_date", "kind"]
    allowed = set(required)
    for field in required:
        if field not in body:
            raise make_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    for key in body:
        if key not in allowed:
            raise make_error(ERR_INVALID_REQUEST, f"Unknown field: {key}")

    assoc_id = body["association_id"]
    comp_id = body["component_id"]
    amount = body["amount_cents"]
    incurred = body["incurred_date"]
    kind = body["kind"]

    # Existence checks
    assoc = store.associations.get(assoc_id)
    if not assoc:
        raise make_error(ERR_NOT_FOUND, f"Association {assoc_id} not found")
    comp = store.components.get(comp_id)
    if not comp:
        raise make_error(ERR_NOT_FOUND, f"Component {comp_id} not found")

    # Shape validation
    if not isinstance(amount, int) or amount <= 0:
        raise make_error(ERR_INVALID_REQUEST, "amount_cents must be a positive integer")
    from datetime import date
    try:
        date.fromisoformat(incurred)
    except (ValueError, TypeError):
        raise make_error(ERR_INVALID_REQUEST, "incurred_date must be YYYY-MM-DD")
    if kind not in VALID_KINDS:
        raise make_error(ERR_INVALID_REQUEST, f"Invalid kind: {kind}")

    # Must have current ADOPTED study
    adopted = find_adopted_study(assoc_id)
    if adopted is None:
        raise make_error(ERR_NO_ADOPTED_STUDY, "Association has no current ADOPTED study")

    # Component must belong to that study and be ACTIVE
    if comp["study_id"] != adopted["id"] or comp["status"] != "ACTIVE":
        raise make_error(ERR_COMPONENT_NOT_CURRENT, "Component does not belong to current ADOPTED study or is not ACTIVE")

    # Derive fiscal year
    fy = fiscal_year_for_date(incurred, assoc["fiscal_year_end_month"])

    exp = store.make_common_fields()
    exp.update({
        "association_id": assoc_id,
        "component_id": comp_id,
        "amount_cents": amount,
        "incurred_date": incurred,
        "kind": kind,
        "fiscal_year": fy,
        "approval_status": "SUBMITTED",
        "reconciliation_status": "UNRECONCILED",
        "planned_chronological_cents": None,
        "variance_chronological_cents": None,
        "component_rul_before_years": None,
        "approved_at": None,
    })
    store.expenditures[exp["id"]] = exp
    return success_object(serialize_expenditure(exp), 201)


@bp.route("/expenditures/<id>", methods=["GET"])
def get_expenditure(id):
    require_roles(*ANY_ROLE)
    exp = store.expenditures.get(id)
    if not exp:
        raise make_error(ERR_NOT_FOUND, f"Expenditure {id} not found")
    return success_object(serialize_expenditure(exp))


@bp.route("/expenditures", methods=["GET"])
def list_expenditures():
    require_roles(*ANY_ROLE)
    exps = list(store.expenditures.values())

    assoc_filter = request.args.get("association_id")
    if assoc_filter:
        exps = [e for e in exps if e["association_id"] == assoc_filter]

    comp_filter = request.args.get("component_id")
    if comp_filter:
        exps = [e for e in exps if e["component_id"] == comp_filter]

    approval_filter = request.args.get("approval_status")
    if approval_filter:
        exps = [e for e in exps if e["approval_status"] == approval_filter]

    recon_filter = request.args.get("reconciliation_status")
    if recon_filter:
        exps = [e for e in exps if e["reconciliation_status"] == recon_filter]

    exps.sort(key=lambda e: e["created_at"])
    limit, offset = _parse_pagination()
    total = len(exps)
    page = exps[offset:offset + limit]
    return success_list([serialize_expenditure(e) for e in page], total, limit, offset)


@bp.route("/expenditures/<id>/approve", methods=["POST"])
def approve_expenditure(id):
    require_roles("BoardMember")
    exp = store.expenditures.get(id)
    if not exp:
        raise make_error(ERR_NOT_FOUND, f"Expenditure {id} not found")

    if exp["approval_status"] != "SUBMITTED":
        raise make_error(ERR_INVALID_STATE, f"Expenditure is {exp['approval_status']}, not SUBMITTED")

    assoc = store.associations[exp["association_id"]]
    comp = store.components[exp["component_id"]]

    # Re-verify component is current
    adopted = find_adopted_study(exp["association_id"])
    if adopted is None or comp["study_id"] != adopted["id"] or comp["status"] != "ACTIVE":
        raise make_error(ERR_COMPONENT_NOT_CURRENT, "Component not in current ADOPTED study or not ACTIVE")

    # Cash sufficiency
    if assoc["reserve_cash_balance_cents"] < exp["amount_cents"]:
        raise make_error(ERR_CASH_INSUFFICIENT, "Reserve cash insufficient")

    # Approve
    exp["approval_status"] = "APPROVED"
    exp["approved_at"] = store.now_iso()
    store.touch(exp)

    # Debit cash
    assoc["reserve_cash_balance_cents"] -= exp["amount_cents"]
    store.touch(assoc)

    # Update component actuals
    comp["actual_expenditure_cents"] = comp.get("actual_expenditure_cents", 0) + exp["amount_cents"]

    if exp["kind"] == "PLANNED_REPLACEMENT":
        exp["component_rul_before_years"] = comp["remaining_useful_life_years"]
        comp["remaining_useful_life_years"] = comp["useful_life_years"]
        comp["last_replaced_fiscal_year"] = exp["fiscal_year"]

    store.touch(comp)

    # Chronological reconciliation
    anchor = find_chronological_anchor(exp["association_id"], exp["fiscal_year"])
    if anchor:
        planned = compute_expenditure_planned(anchor, comp["current_replacement_cost_cents"], exp["fiscal_year"])
        exp["planned_chronological_cents"] = planned
        variance = compute_variance(exp["amount_cents"], planned)
        exp["variance_chronological_cents"] = variance
        tolerance = compute_tolerance(planned)
        if abs(variance) <= tolerance:
            exp["reconciliation_status"] = "MATCHED"

    # Recompute study totals
    recompute_study_totals(adopted)

    # Re-evaluate compliance
    reevaluate_compliance(assoc)

    return success_object(serialize_expenditure(exp))


@bp.route("/expenditures/<id>/reject", methods=["POST"])
def reject_expenditure(id):
    require_roles("BoardMember")
    exp = store.expenditures.get(id)
    if not exp:
        raise make_error(ERR_NOT_FOUND, f"Expenditure {id} not found")

    if exp["approval_status"] != "SUBMITTED":
        raise make_error(ERR_INVALID_STATE, f"Expenditure is {exp['approval_status']}, not SUBMITTED")

    exp["approval_status"] = "REJECTED"
    exp["reconciliation_status"] = "NOT_APPLICABLE"
    store.touch(exp)
    return success_object(serialize_expenditure(exp))


@bp.route("/expenditures/<id>/reverse", methods=["POST"])
def reverse_expenditure(id):
    require_roles("BoardMember")
    exp = store.expenditures.get(id)
    if not exp:
        raise make_error(ERR_NOT_FOUND, f"Expenditure {id} not found")

    if exp["approval_status"] != "APPROVED":
        raise make_error(ERR_INVALID_STATE, f"Expenditure is {exp['approval_status']}, not APPROVED")

    assoc = store.associations[exp["association_id"]]
    comp = store.components[exp["component_id"]]

    # Reversal window: current fiscal year must equal expenditure's fiscal_year
    current_fy = fiscal_year_for_date(store.now_date(), assoc["fiscal_year_end_month"])
    if current_fy != exp["fiscal_year"]:
        raise make_error(ERR_REVERSAL_WINDOW_CLOSED, "Current fiscal year differs from expenditure's fiscal year")

    # Reverse
    exp["approval_status"] = "REVERSED"
    exp["reconciliation_status"] = "NOT_APPLICABLE"
    store.touch(exp)

    # Credit cash back
    assoc["reserve_cash_balance_cents"] += exp["amount_cents"]
    store.touch(assoc)

    # Restore component
    comp["actual_expenditure_cents"] = comp.get("actual_expenditure_cents", 0) - exp["amount_cents"]
    if exp["kind"] == "PLANNED_REPLACEMENT":
        if exp.get("component_rul_before_years") is not None:
            comp["remaining_useful_life_years"] = exp["component_rul_before_years"]
        # Recompute last_replaced_fiscal_year from other APPROVED PLANNED_REPLACEMENT expenditures
        other_approved = [
            e for e in store.expenditures.values()
            if e["component_id"] == comp["id"]
            and e["id"] != exp["id"]
            and e["approval_status"] == "APPROVED"
            and e["kind"] == "PLANNED_REPLACEMENT"
        ]
        if other_approved:
            comp["last_replaced_fiscal_year"] = max(e["fiscal_year"] for e in other_approved)
        else:
            comp["last_replaced_fiscal_year"] = None

    store.touch(comp)

    # Recompute study totals
    adopted = find_adopted_study(exp["association_id"])
    if adopted:
        recompute_study_totals(adopted)

    # Re-evaluate compliance
    reevaluate_compliance(assoc)

    return success_object(serialize_expenditure(exp))


@bp.route("/expenditures/<id>/accept-variance", methods=["POST"])
def accept_variance(id):
    require_roles("ReserveSpecialist")
    exp = store.expenditures.get(id)
    if not exp:
        raise make_error(ERR_NOT_FOUND, f"Expenditure {id} not found")

    if exp["reconciliation_status"] != "UNRECONCILED":
        raise make_error(ERR_INVALID_STATE, f"Reconciliation status is {exp['reconciliation_status']}, not UNRECONCILED")

    body = request.get_json(force=True, silent=True) or {}

    exp["reconciliation_status"] = "VARIANCE_ACCEPTED"
    store.touch(exp)
    return success_object(serialize_expenditure(exp))
