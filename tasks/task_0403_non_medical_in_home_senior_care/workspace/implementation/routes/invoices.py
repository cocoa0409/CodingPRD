"""Invoice endpoints: open, finalize, lifecycle (PRD §3.9, §3.10)."""
from flask import Blueprint, request

import db
import errors
from clock import _format_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success, list_success
from services import requtil
from services.calc import compute_invoice_lines
from services.lookup import get_agency, get_caregiver, get_client, get_invoice

bp = Blueprint("invoices", __name__)

READ_ROLES = {"AgencyAdmin", "Scheduler", "BillingClerk", "Caregiver"}


def _public_invoice(invoice):
    return db.public(invoice)


@bp.post("/invoices")
def create_invoice():
    _, role = get_auth()
    require_roles(role, {"BillingClerk", "AgencyAdmin"})
    body = requtil.get_body()
    agency_id = requtil.require_str(body, "agency_id")
    caregiver_id = requtil.require_str(body, "caregiver_id")
    client_id = requtil.require_str(body, "client_id")
    # Existence left-to-right: agency, caregiver, client.
    get_agency(agency_id)
    get_caregiver(caregiver_id)
    get_client(client_id)

    period_start = requtil.require_datetime(body, "period_start")
    period_end = requtil.require_datetime(body, "period_end")
    if not (period_end > period_start):
        raise requtil.invalid("period_end must be after period_start")

    invoice = {
        "agency_id": agency_id,
        "caregiver_id": caregiver_id,
        "client_id": client_id,
        "period_start": _format_iso(period_start),
        "period_end": _format_iso(period_end),
        "_period_start_dt": period_start,
        "_period_end_dt": period_end,
        "labor_total": 0,
        "mileage_total": 0,
        "invoice_total": 0,
        "client_responsible_amount": 0,
        "lines": [],
        "status": "DRAFT",
    }
    db.stamp_new(invoice)
    db.invoices[invoice["id"]] = invoice
    return success(_public_invoice(invoice), status=201)


@bp.get("/invoices")
def list_invoices():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler", "BillingClerk"})
    limit, offset = requtil.pagination()
    items = list(db.invoices.values())
    for key in ("caregiver_id", "client_id", "agency_id"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v[key] == val]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([_public_invoice(v) for v in page], limit, offset, total)


@bp.get("/invoices/<iid>")
def get_invoice_route(iid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    invoice = get_invoice(iid)
    return success(_public_invoice(invoice))


@bp.post("/invoices/<iid>/finalize")
def finalize_invoice(iid):
    _, role = get_auth()
    require_roles(role, {"BillingClerk", "AgencyAdmin"})
    invoice = get_invoice(iid)

    if invoice["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVOICE_NOT_DRAFT, 409, "finalize requires DRAFT")

    agency = db.agencies.get(invoice["agency_id"])
    lines, labor_total, mileage_total = compute_invoice_lines(invoice, agency)

    # At least one COMPLETED visit in window (a LIVE_IN/HOURLY line means a billable visit).
    has_visit_line = any(l["line_type"] in ("REGULAR", "OVERTIME", "LIVE_IN") for l in lines)
    if not has_visit_line:
        raise ApiError(errors.ERR_NO_BILLABLE_VISITS, 409, "no COMPLETED visits in window")

    invoice["lines"] = lines
    invoice["labor_total"] = labor_total
    invoice["mileage_total"] = mileage_total
    from money import round_half_up
    invoice_total = round_half_up(labor_total + mileage_total)
    invoice["invoice_total"] = invoice_total
    invoice["client_responsible_amount"] = invoice_total
    invoice["status"] = "ISSUED"
    db.touch(invoice)
    return success(_public_invoice(invoice))


@bp.post("/invoices/<iid>/transition")
def transition_invoice(iid):
    _, role = get_auth()
    require_roles(role, {"BillingClerk", "AgencyAdmin"})
    invoice = get_invoice(iid)
    body = requtil.get_body()
    action = requtil.require_enum(body, "action", {"DISPUTE", "REOPEN", "MARK_PAID", "VOID"})

    if action == "DISPUTE":
        if invoice["status"] != "ISSUED":
            raise ApiError(errors.ERR_INVOICE_NOT_ISSUED, 409, "DISPUTE requires ISSUED")
        invoice["status"] = "DISPUTED"
        # Cascade: SUBMITTED/APPROVED claims -> DENIED; covered_amount=0; restore CRA.
        for claim in db.ltc_claims.values():
            if claim["invoice_id"] == invoice["id"] and claim["status"] in ("SUBMITTED", "APPROVED"):
                claim["status"] = "DENIED"
                claim["covered_amount"] = 0
                db.touch(claim)
        invoice["client_responsible_amount"] = invoice["invoice_total"]
        db.touch(invoice)

    elif action == "REOPEN":
        if invoice["status"] != "DISPUTED":
            raise ApiError(errors.ERR_INVOICE_NOT_DISPUTED, 409, "REOPEN requires DISPUTED")
        invoice["lines"] = []
        invoice["labor_total"] = 0
        invoice["mileage_total"] = 0
        invoice["invoice_total"] = 0
        invoice["client_responsible_amount"] = 0
        invoice["status"] = "DRAFT"
        db.touch(invoice)

    elif action == "MARK_PAID":
        if invoice["status"] != "ISSUED":
            raise ApiError(errors.ERR_INVOICE_NOT_ISSUED, 409, "MARK_PAID requires ISSUED")
        assigned = [c for c in db.ltc_claims.values() if c["invoice_id"] == invoice["id"]]
        for claim in assigned:
            if claim["status"] not in ("APPROVED", "PAID"):
                raise ApiError(errors.ERR_CLAIM_NOT_RESOLVED, 409,
                               "assigned claim not APPROVED/PAID")
        invoice["status"] = "PAID"
        for claim in assigned:
            if claim["status"] == "APPROVED":
                claim["status"] = "PAID"
                db.touch(claim)
        db.touch(invoice)

    elif action == "VOID":
        if invoice["status"] != "DRAFT":
            raise ApiError(errors.ERR_INVOICE_NOT_DRAFT, 409, "VOID requires DRAFT")
        invoice["status"] = "VOID"
        db.touch(invoice)

    return success(_public_invoice(invoice))
