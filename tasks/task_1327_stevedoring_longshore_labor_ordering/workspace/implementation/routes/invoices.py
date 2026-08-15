"""Invoice endpoints (PRD §3.9)."""
from flask import Blueprint, request

import errors
import services
from db import all_of, get, new_resource, pub, save, touch
from middleware import list_response, req_field, req_str, require_roles, require_version
from response import get_body, ok

bp = Blueprint("invoices", __name__)

READ_ROLES = ("StevedoreAdmin", "StevedoreSuperintendent", "BillingClerk")


@bp.post("/api/invoices")
def create_invoice():
    require_roles("BillingClerk")
    body = get_body()
    # existence (3)
    vessel_call_id = req_field(body, "vessel_call_id")
    vessel = get("vessel_calls", vessel_call_id)
    if vessel is None:
        raise errors.not_found("Vessel call not found")
    # state (6): BERTHED or later; exactly one invoice per vessel call
    if vessel["status"] not in ("BERTHED", "WORKING", "COMPLETED"):
        raise errors.invalid_state("Invoice creation requires the vessel to be BERTHED or later")
    for inv in all_of("invoices"):
        if inv["vessel_call_id"] == vessel_call_id:
            raise errors.invalid_state("A vessel call carries exactly one invoice")
    lines = services.compute_invoice_lines(vessel, "PROVISIONAL")
    rec = new_resource("invoices")
    rec.update({
        "vessel_call_id": vessel_call_id,
        "status": "DRAFT",
        "rate_variant": "PROVISIONAL",
        **lines,
        "adjustment_total_cents": 0,
        "amount_paid_cents": 0,
        "dispute_reason": None,
    })
    services.recompute_invoice_totals(rec)
    save("invoices", rec)
    return ok(pub(rec), 201)


@bp.get("/api/invoices")
def list_invoices():
    require_roles(*READ_ROLES)
    return list_response("invoices", {
        "vessel_call_id": request.args.get("vessel_call_id"),
        "status": request.args.get("status"),
    })


def _get_invoice(iid):
    inv = get("invoices", iid)
    if inv is None:
        raise errors.not_found("Invoice not found")
    return inv


@bp.get("/api/invoices/<iid>")
def get_invoice(iid):
    require_roles(*READ_ROLES)
    return ok(pub(_get_invoice(iid)))


@bp.patch("/api/invoices/<iid>")
def adjust_invoice(iid):
    require_roles("BillingClerk")
    inv = _get_invoice(iid)
    body = get_body()
    # schema (4)
    adjustment_cents = req_field(body, "adjustment_cents")
    if not isinstance(adjustment_cents, int) or isinstance(adjustment_cents, bool):
        raise errors.validation("adjustment_cents must be an integer")
    req_str(body, "reason")
    # concurrency (5) before state (6)
    require_version(body, "expected_invoice_version", inv["version"],
                    errors.stale_invoice)
    if inv["status"] not in ("DRAFT", "DISPUTED"):
        raise errors.invalid_state("Adjustments apply only to DRAFT or DISPUTED invoices")
    inv["adjustment_total_cents"] += adjustment_cents
    services.recompute_invoice_totals(inv)
    if inv["status"] == "DISPUTED":
        inv["status"] = "FINALIZED"
    touch(inv)  # every accepted adjustment increments version by one
    return ok(pub(inv))


@bp.post("/api/invoices/<iid>/finalize")
def finalize_invoice(iid):
    require_roles("BillingClerk")
    inv = _get_invoice(iid)
    if inv["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT invoice can be finalized")
    vessel = get("vessel_calls", inv["vessel_call_id"])
    if vessel["status"] != "COMPLETED":
        raise errors.invoice_not_finalizable()
    lines = services.compute_invoice_lines(vessel, "FINAL")
    inv.update(lines)
    inv["rate_variant"] = "FINAL"
    inv["status"] = "FINALIZED"
    services.recompute_invoice_totals(inv)
    touch(inv)
    return ok(pub(inv))


@bp.post("/api/invoices/<iid>/issue")
def issue_invoice(iid):
    require_roles("BillingClerk")
    inv = _get_invoice(iid)
    if inv["status"] != "FINALIZED":
        raise errors.invalid_state("Only a FINALIZED invoice can be issued")
    vessel = get("vessel_calls", inv["vessel_call_id"])
    # fiscal limit (11)
    if inv["total_cents"] > vessel["credit_limit_cents"]:
        raise errors.invoice_credit_limit()
    inv["status"] = "ISSUED"
    touch(inv)
    return ok(pub(inv))


@bp.post("/api/invoices/<iid>/record-payment")
def record_payment(iid):
    require_roles("BillingClerk")
    inv = _get_invoice(iid)
    body = get_body()
    # schema (4)
    amount_cents = req_field(body, "amount_cents")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents <= 0:
        raise errors.validation("amount_cents must be a positive integer")
    # state (6)
    if inv["status"] != "ISSUED":
        raise errors.invalid_state("Payments can only be recorded against an ISSUED invoice")
    # fiscal (11)
    if amount_cents > inv["remaining_balance_cents"]:
        raise errors.payment_exceeds_balance()
    inv["amount_paid_cents"] += amount_cents
    inv["remaining_balance_cents"] = inv["total_cents"] - inv["amount_paid_cents"]
    if inv["remaining_balance_cents"] == 0:
        inv["status"] = "PAID"
    touch(inv)
    return ok(pub(inv))


@bp.post("/api/invoices/<iid>/dispute")
def dispute_invoice(iid):
    require_roles("BillingClerk")
    inv = _get_invoice(iid)
    body = get_body()
    # schema (4)
    reason = req_str(body, "dispute_reason")
    # state (6)
    if inv["status"] != "ISSUED":
        raise errors.invalid_state("Only an ISSUED invoice can be disputed")
    inv["status"] = "DISPUTED"
    inv["dispute_reason"] = reason
    touch(inv)
    return ok(pub(inv))
