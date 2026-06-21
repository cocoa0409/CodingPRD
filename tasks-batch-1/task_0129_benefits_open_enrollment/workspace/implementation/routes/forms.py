"""Form1095C endpoints (PRD §3.10)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import (
    authenticate, authorize,
    BENEFITS_ADMIN, COMPLIANCE_OFFICER,
)
import response
from services import common as C
from services import domain as D
from routes._helpers import get_or_404

bp = Blueprint("forms", __name__)


def _lowest_cost_self_only_medical_tier():
    """The single MEDICAL tier flagged is_lowest_cost_self_only (PRD §3.10)."""
    for tier in db.plan_tiers.values():
        if not tier.get("is_lowest_cost_self_only"):
            continue
        off = D.offering_for_tier(tier)
        if off is not None and off["benefit_type"] == "MEDICAL":
            return tier
    return None


@bp.route("/employees/<emp_id>/form-1095c", methods=["POST"])
def generate_form(emp_id):
    role = authenticate()
    authorize(role, {COMPLIANCE_OFFICER})
    emp = get_or_404(db.employees, emp_id, "Employee")
    body = C.get_body()
    C.require_fields(body, ["tax_year"])
    tax_year = body["tax_year"]
    if not C.is_int(tax_year):
        raise E.invalid_request("tax_year must be an integer")

    tier = _lowest_cost_self_only_medical_tier()
    if tier is None:
        # No benchmark tier configured; affordability cannot be computed.
        raise E.invalid_request("No is_lowest_cost_self_only MEDICAL tier configured")

    lowest_cost, threshold, indicator = D.compute_aca_affordability(emp, tier)

    form = C.new_common_fields()
    form.update({
        "employee_id": emp_id,
        "tax_year": tax_year,
        "lowest_cost_monthly_premium_cents": lowest_cost,
        "affordability_threshold_cents": threshold,
        "affordability_indicator": indicator,
        "status": "GENERATED",
    })
    db.form_1095c[form["id"]] = form
    return response.ok_object(C.serialize(form), 201)


@bp.route("/form-1095c/<form_id>", methods=["GET"])
def get_form(form_id):
    role = authenticate()
    authorize(role, {COMPLIANCE_OFFICER, BENEFITS_ADMIN})
    form = get_or_404(db.form_1095c, form_id, "Form1095C")
    return response.ok_object(C.serialize(form), 200)


@bp.route("/form-1095c", methods=["GET"])
def list_forms():
    role = authenticate()
    authorize(role, {COMPLIANCE_OFFICER, BENEFITS_ADMIN})
    limit, offset = C.parse_pagination()
    args = request.args
    items = list(db.form_1095c.values())
    employee_id = args.get("employee_id")
    status = args.get("status")
    tax_year = args.get("tax_year")
    if employee_id is not None:
        items = [f for f in items if f["employee_id"] == employee_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    if tax_year is not None:
        try:
            ty = int(tax_year)
            items = [f for f in items if f["tax_year"] == ty]
        except (TypeError, ValueError):
            items = []
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/form-1095c/<form_id>/file", methods=["POST"])
def file_form(form_id):
    role = authenticate()
    authorize(role, {COMPLIANCE_OFFICER})
    form = get_or_404(db.form_1095c, form_id, "Form1095C")
    # FILED is terminal and immutable: mutating a FILED form -> ERR_FORM_ALREADY_FILED.
    if form["status"] == "FILED":
        raise E.form_already_filed()
    if form["status"] != "GENERATED":
        raise E.invalid_state("Form1095C must be GENERATED to file")
    form["status"] = "FILED"
    C.touch(form)
    return response.ok_object(C.serialize(form), 200)
