"""ChangeOrder endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_tenant_ownership, get_project_tenant_ownership
from response import success_object, success_created, success_list
from errors import (
    not_found, invalid_request, invalid_state, stale_version, APIError,
    ERR_PROJECT_NOT_OPEN, ERR_INVOICE_ALREADY_ISSUED,
)
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_int, is_str,
)
from services import calc

bp = Blueprint("change_orders", __name__)


def _get_co_or_404(cid):
    co = store.change_orders.get(cid)
    if not co:
        raise not_found("ChangeOrder not found")
    return co


def _next_co_number(project_id):
    existing = [
        co for co in store.change_orders.values() if co["project_id"] == project_id
    ]
    return len(existing) + 1


def _validate_lines(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        raise invalid_request("lines must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            raise invalid_request("Each line must be an object")
        if "description" not in line or "amount_cents" not in line:
            raise invalid_request("Each line requires description and amount_cents")
        if not is_str(line["description"]):
            raise invalid_request("line.description must be a string")
        if not is_int(line["amount_cents"]) or line["amount_cents"] <= 0:
            raise invalid_request("line.amount_cents must be integer > 0")


@bp.route("/api/ti-projects/<id>/change-orders", methods=["POST"])
def create_change_order(id):
    user_id, role = require_roles("ContractorRep", "TenantRep")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["description", "lines", "expected_ti_project_version"])
    if not is_str(body["description"]):
        raise invalid_request("description must be a string")
    _validate_lines(body["lines"])
    if not is_int(body["expected_ti_project_version"]):
        raise invalid_request("expected_ti_project_version must be an integer")

    # TenantRep scope check
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])

    # OCC check (last in funnel per §2.8)
    if body["expected_ti_project_version"] != proj["version"]:
        raise stale_version("TIProject version has advanced")

    rec = make_common_fields()
    rec.update({
        "project_id": id,
        "co_number": _next_co_number(id),
        "description": body["description"],
        "lines": body["lines"],
        "submitted_by": None,
        "total_cost_cents": 0,
        "markup_cents": 0,
        "total_with_markup_cents": 0,
        "tenant_overage_share_cents": 0,
        "approved_by_user_id": None,
        "approved_at": None,
        "status": "DRAFT",
    })
    store.change_orders[rec["id"]] = rec

    # Creating the draft advances the project's version
    bump_version(proj)
    return success_created(rec)


@bp.route("/api/ti-projects/<id>/change-orders", methods=["GET"])
def list_change_orders(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "TenantRep", "ContractorRep"
    )
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])
    limit, offset = get_pagination_params()
    items = [co for co in store.change_orders.values() if co["project_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/change-orders/<id>", methods=["GET"])
def get_change_order(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "TenantRep", "ContractorRep"
    )
    co = _get_co_or_404(id)
    if role == "TenantRep":
        get_project_tenant_ownership(user_id, co["project_id"])
    return success_object(co)


@bp.route("/api/change-orders/<id>/submit", methods=["POST"])
def submit_change_order(id):
    user_id, role = require_roles("ContractorRep", "TenantRep")
    co = _get_co_or_404(id)
    if co["status"] != "DRAFT":
        raise invalid_state("ChangeOrder must be in DRAFT to submit")

    proj = store.ti_projects.get(co["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] not in ("PRE_CONSTRUCTION", "CONSTRUCTION", "PUNCH"):
        raise invalid_state("Project must be in PRE_CONSTRUCTION, CONSTRUCTION, or PUNCH")
    if proj["posture"] != "OPEN":
        raise APIError(ERR_PROJECT_NOT_OPEN, 422,
                       "Project posture is not OPEN")

    co["submitted_by"] = "CONTRACTOR" if role == "ContractorRep" else "TENANT"
    co["status"] = "SUBMITTED"
    bump_version(co)
    return success_object(co)


@bp.route("/api/change-orders/<id>/approve", methods=["POST"])
def approve_change_order(id):
    user_id, role = require_roles("LandlordApprover")
    co = _get_co_or_404(id)
    if co["status"] != "SUBMITTED":
        raise invalid_state("ChangeOrder must be in SUBMITTED to approve")

    proj = store.ti_projects.get(co["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] not in ("PRE_CONSTRUCTION", "CONSTRUCTION", "PUNCH"):
        raise invalid_state("Project must be in PRE_CONSTRUCTION, CONSTRUCTION, or PUNCH")

    # Run markup calc
    total_cost, markup, total_with_markup = calc.compute_change_order_markup(co["lines"])
    co["total_cost_cents"] = total_cost
    co["markup_cents"] = markup
    co["total_with_markup_cents"] = total_with_markup

    # Run overage share sweep
    co["tenant_overage_share_cents"] = calc.compute_overage_share(proj, co)

    # Stamp approval
    co["approved_by_user_id"] = user_id
    co["approved_at"] = store.now()
    co["status"] = "APPROVED"
    bump_version(co)

    # Recompute project aggregates
    calc.recompute_total_cost(proj)
    calc.recompute_posture(proj)
    bump_version(proj)

    return success_object(co)


@bp.route("/api/change-orders/<id>/reject", methods=["POST"])
def reject_change_order(id):
    require_roles("LandlordApprover")
    co = _get_co_or_404(id)
    if co["status"] != "SUBMITTED":
        raise invalid_state("ChangeOrder must be in SUBMITTED to reject")
    co["status"] = "REJECTED"
    bump_version(co)
    return success_object(co)


@bp.route("/api/change-orders/<id>/void", methods=["POST"])
def void_change_order(id):
    require_roles("LandlordApprover")
    co = _get_co_or_404(id)
    if co["status"] != "APPROVED":
        raise invalid_state("ChangeOrder must be in APPROVED to void")

    # Blocked once any ISSUED or PAID invoice includes this CO.
    # An invoice "includes" a CO if the CO's share contributed to line_total_cents.
    # We track this by checking whether the CO has been swept into any non-DRAFT, non-VOID invoice.
    # Per scaffold: "No OverageInvoice in status ISSUED or PAID of the same project includes this ChangeOrder"
    # Implementation: when an invoice is drafted, it snapshots the sum of uninvoiced CO shares.
    # We need to track which COs are included in which invoices. We do this implicitly:
    # a CO is "invoiced" once an invoice has been created that covers it.
    # Since we snapshot at creation, we mark COs as invoiced when the invoice is created.
    # But the scaffold says blocked by ISSUED or PAID — meaning DRAFT invoices don't block.
    # We track invoiced status on the CO record.
    if co.get("_invoiced_in_issued_or_paid"):
        raise APIError(ERR_INVOICE_ALREADY_ISSUED, 422,
                       "An ISSUED or PAID invoice already includes this ChangeOrder")

    proj = store.ti_projects.get(co["project_id"])
    if not proj:
        raise not_found("TIProject not found")

    co["status"] = "VOIDED"
    bump_version(co)

    # Compensation: back out total_with_markup from project
    calc.recompute_total_cost(proj)
    calc.recompute_posture(proj)
    bump_version(proj)

    return success_object(co)
