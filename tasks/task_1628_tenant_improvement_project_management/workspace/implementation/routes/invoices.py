"""OverageInvoice endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_tenant_ownership, get_project_tenant_ownership
from response import success_object, success_created, success_list
from errors import (
    not_found, invalid_request, invalid_state, APIError,
    ERR_NO_OVERAGE_OUTSTANDING,
)
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_int, is_str, logical_clock_dt, to_iso_z,
)
from services import calc

bp = Blueprint("invoices", __name__)


def _get_inv_or_404(iid):
    inv = store.overage_invoices.get(iid)
    if not inv:
        raise not_found("OverageInvoice not found")
    return inv


def _next_invoice_number(project_id):
    existing = [
        i for i in store.overage_invoices.values() if i["project_id"] == project_id
    ]
    return len(existing) + 1


def _uninvoiced_approved_cos_with_share(project_id):
    """Find APPROVED COs with share > 0 not yet included in any non-VOID invoice."""
    # Collect CO ids already included in any non-VOID invoice
    invoiced_co_ids = set()
    for inv in store.overage_invoices.values():
        if inv["project_id"] == project_id and inv["status"] != "VOID":
            for co_id in inv.get("_included_co_ids", []):
                invoiced_co_ids.add(co_id)

    return [
        co for co in store.change_orders.values()
        if co["project_id"] == project_id
        and co["status"] == "APPROVED"
        and co["tenant_overage_share_cents"] > 0
        and co["id"] not in invoiced_co_ids
    ]


@bp.route("/api/ti-projects/<id>/overage-invoices", methods=["POST"])
def create_overage_invoice(id):
    require_roles("LandlordPM")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")

    qualifying = _uninvoiced_approved_cos_with_share(id)
    if not qualifying:
        raise APIError(ERR_NO_OVERAGE_OUTSTANDING, 422,
                       "No uninvoiced APPROVED change orders with positive tenant share")

    line_total = sum(co["tenant_overage_share_cents"] for co in qualifying)

    rec = make_common_fields()
    rec.update({
        "project_id": id,
        "invoice_number": _next_invoice_number(id),
        "line_total_cents": line_total,
        "due_date": None,
        "status": "DRAFT",
        "_included_co_ids": [co["id"] for co in qualifying],
    })
    store.overage_invoices[rec["id"]] = rec

    return success_created(_serialize_invoice(rec))


@bp.route("/api/ti-projects/<id>/overage-invoices", methods=["GET"])
def list_overage_invoices(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])
    limit, offset = get_pagination_params()
    items = [i for i in store.overage_invoices.values() if i["project_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list([_serialize_invoice(i) for i in page], limit, offset, total)


@bp.route("/api/overage-invoices/<id>", methods=["GET"])
def get_overage_invoice(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    inv = _get_inv_or_404(id)
    if role == "TenantRep":
        get_project_tenant_ownership(user_id, inv["project_id"])
    return success_object(_serialize_invoice(inv))


@bp.route("/api/overage-invoices/<id>/issue", methods=["POST"])
def issue_invoice(id):
    require_roles("LandlordPM")
    inv = _get_inv_or_404(id)
    if inv["status"] != "DRAFT":
        raise invalid_state("OverageInvoice must be in DRAFT to issue")

    proj = store.ti_projects.get(inv["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] not in ("CONSTRUCTION", "PUNCH", "CLOSEOUT"):
        raise invalid_state("Project must be in CONSTRUCTION, PUNCH, or CLOSEOUT")

    inv["status"] = "ISSUED"
    inv["due_date"] = calc.compute_invoice_due_date(store.clock_iso())

    # Mark included COs as invoiced-in-issued for void blocking
    for co_id in inv.get("_included_co_ids", []):
        co = store.change_orders.get(co_id)
        if co:
            co["_invoiced_in_issued_or_paid"] = True

    bump_version(inv)
    return success_object(_serialize_invoice(inv))


@bp.route("/api/overage-invoices/<id>/pay", methods=["POST"])
def pay_invoice(id):
    user_id, role = require_roles("TenantRep")
    inv = _get_inv_or_404(id)
    get_project_tenant_ownership(user_id, inv["project_id"])
    if inv["status"] != "ISSUED":
        raise invalid_state("OverageInvoice must be in ISSUED to pay")
    inv["status"] = "PAID"

    # Update the invoiced flag for CO void blocking
    for co_id in inv.get("_included_co_ids", []):
        co = store.change_orders.get(co_id)
        if co:
            co["_invoiced_in_issued_or_paid"] = True

    bump_version(inv)
    return success_object(_serialize_invoice(inv))


@bp.route("/api/overage-invoices/<id>/dispute", methods=["POST"])
def dispute_invoice(id):
    user_id, role = require_roles("TenantRep")
    inv = _get_inv_or_404(id)
    get_project_tenant_ownership(user_id, inv["project_id"])
    if inv["status"] != "ISSUED":
        raise invalid_state("OverageInvoice must be in ISSUED to dispute")
    inv["status"] = "DISPUTED"
    bump_version(inv)
    return success_object(_serialize_invoice(inv))


@bp.route("/api/overage-invoices/<id>/reissue", methods=["POST"])
def reissue_invoice(id):
    require_roles("LandlordPM")
    inv = _get_inv_or_404(id)
    if inv["status"] != "DISPUTED":
        raise invalid_state("OverageInvoice must be in DISPUTED to reissue")
    inv["status"] = "ISSUED"
    bump_version(inv)
    return success_object(_serialize_invoice(inv))


@bp.route("/api/overage-invoices/<id>/void", methods=["POST"])
def void_invoice(id):
    require_roles("LandlordPM")
    inv = _get_inv_or_404(id)
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise invalid_state("OverageInvoice must be in DRAFT or ISSUED to void")

    # Clear the invoiced flag on included COs so they can be re-invoiced
    for co_id in inv.get("_included_co_ids", []):
        co = store.change_orders.get(co_id)
        if co:
            co["_invoiced_in_issued_or_paid"] = False

    inv["status"] = "VOID"
    bump_version(inv)
    return success_object(_serialize_invoice(inv))


def _serialize_invoice(inv):
    """Strip internal tracking fields from the response."""
    result = {k: v for k, v in inv.items() if not k.startswith("_")}
    return result
