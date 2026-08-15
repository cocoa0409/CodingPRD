"""AdditionalServiceInvoice endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVOICE_INVALID_STATE,
    ERR_INVOICE_PERIOD_OVERLAP,
    ERR_NO_BILLABLE_EXTENSION,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services import calcs
from services.helpers import (
    base_entity, touch, paginate, get_project, get_invoice,
    req_str, req_date, opt_enum, invalid,
)
from services.lifecycle import require_project_active, check_counterparty

bp = Blueprint("invoices", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")


@bp.post("/ca/additional-service-invoices")
def create_invoice():
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    body = get_body(required=True)
    project_id = req_str(body, "project_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if period_start >= period_end:
        invalid("period_start must be strictly before period_end")

    project = get_project(project_id)
    # Invoices allow ACTIVE or SUBSTANTIAL_COMPLETION_ACHIEVED.
    require_project_active(project, allow_substantial=True)

    # Period overlap: start < other.period_end AND other.period_start < end
    # over non-CANCELLED invoices; adjacency (shared endpoint date) is allowed.
    for other in db.invoices.values():
        if other["project_id"] != project_id or other["status"] == "CANCELLED":
            continue
        if period_start < other["period_end"] and other["period_start"] < period_end:
            raise ApiError(
                ERR_INVOICE_PERIOD_OVERLAP,
                "Requested invoice period overlaps a non-CANCELLED invoice period on the project",
                409,
            )

    fields = calcs.compute_invoice_fields(project, period_start, period_end)
    if fields["billable_days"] == 0:
        raise ApiError(
            ERR_NO_BILLABLE_EXTENSION,
            "Requested invoice period yields 0 billable days under the current billing horizon",
            422,
        )

    inv = base_entity()
    inv.update({
        "project_id": project_id,
        "period_start": period_start,
        "period_end": period_end,
        "horizon_start_date": fields["horizon_start_date"],
        "horizon_end_date": fields["horizon_end_date"],
        "billable_days": fields["billable_days"],
        "amount_cents": fields["amount_cents"],
        "status": "DRAFT",
    })
    db.invoices[inv["id"]] = inv
    return success_object(inv, 201)


@bp.get("/ca/additional-service-invoices")
def list_invoices():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.invoices.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [i for i in items if i["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/additional-service-invoices/<iid>")
def get_one_invoice(iid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_invoice(iid))


@bp.post("/ca/additional-service-invoices/<iid>/issue")
def issue_invoice(iid):
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    inv = get_invoice(iid)
    if inv["status"] != "DRAFT":
        raise ApiError(ERR_INVOICE_INVALID_STATE, "invoice issue requires DRAFT", 409)
    inv["status"] = "ISSUED"
    touch(inv)
    return success_object(inv)


@bp.post("/ca/additional-service-invoices/<iid>/owner-decision")
def owner_decision_invoice(iid):
    user_id, role = get_user_context()
    require_role(role, ("Owner",))
    body = get_body(required=True)
    decision = opt_enum(body, "decision", ("APPROVE", "DISPUTE"))
    inv = get_invoice(iid)
    project = db.projects[inv["project_id"]]
    check_counterparty(role, user_id, project)
    if inv["status"] != "ISSUED":
        raise ApiError(ERR_INVOICE_INVALID_STATE, "owner-decision requires ISSUED", 409)
    inv["status"] = "OWNER_APPROVED" if decision == "APPROVE" else "DISPUTED"
    touch(inv)
    return success_object(inv)


@bp.post("/ca/additional-service-invoices/<iid>/record-payment")
def record_payment_invoice(iid):
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    inv = get_invoice(iid)
    if inv["status"] != "OWNER_APPROVED":
        raise ApiError(ERR_INVOICE_INVALID_STATE, "record-payment requires OWNER_APPROVED", 409)
    inv["status"] = "PAID"
    touch(inv)
    return success_object(inv)


@bp.post("/ca/additional-service-invoices/<iid>/cancel")
def cancel_invoice(iid):
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    inv = get_invoice(iid)
    if inv["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError(ERR_INVOICE_INVALID_STATE, "invoice cancel requires DRAFT or DISPUTED", 409)
    inv["status"] = "CANCELLED"
    touch(inv)
    return success_object(inv)
