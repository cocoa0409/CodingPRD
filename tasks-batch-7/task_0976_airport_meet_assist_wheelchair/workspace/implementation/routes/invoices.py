"""Invoices and settlement lifecycle."""
from flask import Blueprint

import db
from errors import (bad_request, invoice_state, segregation_of_duties,
                    stale_version)
from middleware import require_roles
from response import success_object
from routes.util import (get_or_404, json_body, list_response, require_enum,
                         require_fields, serialize_invoice)
from services import pricing

bp = Blueprint("invoices", __name__)

INVOICE_GET_ROLES = ("PlatformAdmin", "OpsManager", "BillingClerk", "Requester")
INVOICE_LIST_ROLES = ("PlatformAdmin", "OpsManager", "BillingClerk")


@bp.get("/maa/invoices/<iid>")
def get_invoice(iid):
    require_roles(*INVOICE_GET_ROLES)
    invoice = get_or_404(db.invoices, iid, "Invoice")
    return success_object(serialize_invoice(invoice))


@bp.get("/maa/invoices/<iid>/adjustments")
def list_invoice_adjustments(iid):
    require_roles(*INVOICE_LIST_ROLES)
    invoice = get_or_404(db.invoices, iid, "Invoice")
    items = [i for i in db.invoices.values()
             if i.get("supersedes_invoice_id") == invoice["id"]
             and i["invoice_kind"] == "ADJUSTMENT"]
    return list_response(items, serialize_invoice)


@bp.post("/maa/invoices/<iid>/events")
def invoice_event(iid):
    user_id, _ = require_roles("BillingClerk")
    invoice = get_or_404(db.invoices, iid, "Invoice")
    body = json_body()
    require_fields(body, ["event_type"])
    event_type = require_enum(
        body["event_type"],
        {"MARK_PAID", "DISPUTE", "RESOLVE_PAID", "WRITE_OFF"},
        "event_type")
    expected = body.get("expected_invoice_version")
    if expected is None:
        raise bad_request("expected_invoice_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("expected_invoice_version must be an integer")
    if expected != invoice["version"]:
        raise stale_version("expected_invoice_version does not match current version")

    request = db.assist_requests[invoice["assist_request_id"]]

    if event_type == "MARK_PAID":
        if invoice["invoice_kind"] != "FINAL":
            raise invoice_state("Only FINAL invoices may be marked paid")
        if invoice["status"] != "OPEN":
            raise invoice_state("Invoice must be OPEN to mark paid")
        invoice["status"] = "PAID"
        request["billing_status"] = "PAID"
        db.touch(invoice)
        db.touch(request)

    elif event_type == "DISPUTE":
        if invoice["status"] != "OPEN":
            raise invoice_state("Only OPEN invoices may be disputed")
        invoice["status"] = "DISPUTED"
        request["billing_status"] = "DISPUTED"
        db.touch(invoice)
        db.touch(request)

    elif event_type == "RESOLVE_PAID":
        if invoice["status"] != "DISPUTED":
            raise invoice_state("Only DISPUTED invoices may be resolve-paid")
        invoice["status"] = "PAID"
        request["billing_status"] = "PAID"
        db.touch(invoice)
        db.touch(request)

    else:  # WRITE_OFF
        if invoice["status"] != "DISPUTED":
            raise invoice_state("Only DISPUTED invoices may be written off")
        if invoice["bill_to"] == "AIRLINE":
            # Segregation-of-duties vs provisional invoice creator
            prov_creator = None
            for inv in db.invoices.values():
                if (inv["assist_request_id"] == invoice["assist_request_id"]
                        and inv["invoice_kind"] == "PROVISIONAL"):
                    prov_creator = inv.get("created_by_user_id")
                    break
            if prov_creator is not None and prov_creator == user_id:
                raise segregation_of_duties(
                    "Write-off clerk must differ from provisional-invoice creator")
        # Write-off baseline: recompute final leg charge with posture forced NORMAL
        baseline = 0
        for leg in db.legs.values():
            if leg["assist_request_id"] != invoice["assist_request_id"]:
                continue
            if leg["status"] == "CANCELLED":
                continue
            segment = db.segments[leg["segment_id"]]
            airport = db.airports[segment["airport_id"]]
            baseline += pricing.final_leg_charge(
                leg, request, airport, segment, force_normal_posture=True)
        invoice["writeoff_baseline_cents"] = baseline
        invoice["status"] = "WRITTEN_OFF"
        request["billing_status"] = "WRITTEN_OFF"
        db.touch(invoice)
        db.touch(request)

    return success_object(serialize_invoice(invoice))
