"""RenewalInvoice endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, new_entity, touch, serialize, list_page,
)
from response import success_obj, success_list
from errors import (
    err_duplicate, err_invalid_state, err_stale_version, err_invalid_request,
    err_fiscal,
)
from timeutil import today
from services import fee_components, payable_total_cents

bp = Blueprint("renewals", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "FinanceClerk", "Regulator")


def invoice_out(inv):
    return serialize(inv, {"payable_total_cents": payable_total_cents(inv, today())})


@bp.post("/registration-desk/renewal-invoices")
def create_invoice():
    auth("FinanceClerk")
    data = body()
    req = fk_or_404(store.registration_requests, data.get("registration_request_id"))
    # Priority 4: at most one invoice per (registration_request_id, cycle_year).
    cy = data.get("cycle_year")
    if (
        data.get("registration_request_id") is not None
        and isinstance(cy, int)
        and not isinstance(cy, bool)
        and any(
            inv["registration_request_id"] == data["registration_request_id"]
            and inv["cycle_year"] == cy
            for inv in store.renewal_invoices.values()
        )
    ):
        raise err_duplicate("an invoice already exists for this registration request and cycle year")
    # Priority 9: field shape.
    required(data, "registration_request_id")
    cy = required(data, "cycle_year")
    if not isinstance(cy, int) or isinstance(cy, bool) or cy < 2026 or cy > 2100:
        raise err_invalid_request("cycle_year must be an integer between 2026 and 2100")
    # Priority 12: the registration must be ACTIVE.
    if req["status"] != "ACTIVE":
        raise err_fiscal("renewal invoices may be issued only for an ACTIVE registration")
    j, base, surcharge, total = fee_components(req, cy, today())
    inv = new_entity()
    inv.update({
        "registration_request_id": req["id"],
        "cycle_year": cy,
        "jurisdiction_fee_cents": j,
        "base_fee_cents": base,
        "late_surcharge_cents": surcharge,
        "total_cents": total,
        "status": "ISSUED",
    })
    store.renewal_invoices[inv["id"]] = inv
    return success_obj(invoice_out(inv), 201)


@bp.get("/registration-desk/renewal-invoices")
def list_invoices():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.renewal_invoices,
        (
            ("registration_request_id", "registration_request_id", str),
            ("status", "status", str),
            ("cycle_year", "cycle_year", int),
        ),
    )
    return success_list([invoice_out(i) for i in page], limit, offset, total)


@bp.get("/registration-desk/renewal-invoices/<id>")
def get_invoice(id):
    auth(*READ_ROLES)
    inv = get_or_404(store.renewal_invoices, id)
    return success_obj(invoice_out(inv), 200)


@bp.post("/registration-desk/renewal-invoices/<id>/pay")
def pay_invoice(id):
    auth("FinanceClerk")
    inv = get_or_404(store.renewal_invoices, id)
    # Priority 5: invoice must be ISSUED.
    if inv["status"] != "ISSUED":
        raise err_invalid_state("only an ISSUED invoice may be paid")
    # Priority 6: OCC on expected_renewal_invoice_version.
    data = body()
    expected = data.get("expected_renewal_invoice_version")
    if expected is None:
        raise err_invalid_request("expected_renewal_invoice_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected != inv["version"]:
        raise err_stale_version()
    # Priority 12: parent registration still ACTIVE and payable amount never negative.
    req = get_or_404(store.registration_requests, inv["registration_request_id"])
    if req["status"] != "ACTIVE":
        raise err_fiscal("the parent registration must be ACTIVE at payment time")
    if payable_total_cents(inv, today()) < 0:
        raise err_fiscal("payable amount must never be negative")
    inv["status"] = "PAID"
    touch(inv)
    return success_obj(invoice_out(inv), 200)


@bp.post("/registration-desk/renewal-invoices/<id>/void")
def void_invoice(id):
    auth("FinanceClerk")
    inv = get_or_404(store.renewal_invoices, id)
    if inv["status"] != "ISSUED":
        raise err_invalid_state("only an ISSUED invoice may be voided")
    inv["status"] = "VOID"
    touch(inv)
    return success_obj(invoice_out(inv), 200)
