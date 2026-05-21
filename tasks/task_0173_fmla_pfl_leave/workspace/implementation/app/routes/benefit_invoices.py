"""BenefitInvoice routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import ensure_employee_owns, require_roles
from ..common import strip_internal
from ..errors import err_invoice_not_payable, err_not_found
from ..response import make_object_envelope
from ..store import get_store


bp_benefit_invoices = Blueprint("benefit_invoices", __name__)


@bp_benefit_invoices.route("/benefit-invoices/<invoice_id>/pay", methods=["POST"])
@require_roles("Employee", "HRSpecialist")
def pay_invoice(user_id: str, role: str, invoice_id: str):
    store = get_store()
    inv = store.benefit_invoices.get(invoice_id)
    if inv is None:
        raise err_not_found("BenefitInvoice not found.")
    case = store.leave_cases.get(inv["leave_case_id"])
    if case is None:
        raise err_not_found("Owning case not found.")
    ensure_employee_owns(user_id, role, case["employee_id"])
    if inv["invoice_status"] not in {"ISSUED", "GRACE"}:
        raise err_invoice_not_payable()
    inv["invoice_status"] = "PAID"
    return jsonify(make_object_envelope(strip_internal(inv))), 200
