"""Invoice lifecycle (PRD 3.6): provisional creation, recomputation, the final
variants at completion/no-show/cancellation, voiding, and deposit forfeits."""

import db
from constants import (
    NO_SHOW_FLAT_FEE_CENTS,
    ORDER_FINAL_CHARGE_STATUSES,
    ORDER_PROVISIONAL_CHARGE_STATUSES,
    RATE_FIELD,
)
from services import pricing
from services.intervals import billable_interval


def orders_of_event(event):
    return [o for o in db.all_of(db.service_orders) if o.get("event_id") == event["id"]]


def invoices_of_event(event):
    return [i for i in db.all_of(db.invoices) if i.get("event_id") == event["id"]]


def provisional_invoice(event):
    """The event's live PROVISIONAL invoice (at most one at a time)."""
    for invoice in invoices_of_event(event):
        if invoice.get("status") == "PROVISIONAL":
            return invoice
    return None


def current_invoice(event):
    """The event's latest live invoice (not VOIDED, not REFUNDED)."""
    for invoice in reversed(invoices_of_event(event)):
        if invoice.get("status") not in ("VOIDED", "REFUNDED"):
            return invoice
    return None


def _recompute_total(invoice):
    invoice["total_cents"] = (
        invoice.get("room_charge_cents", 0)
        + invoice.get("service_charge_cents", 0)
        + invoice.get("insurance_surcharge_cents", 0)
        + invoice.get("cancellation_fee_cents", 0)
        + invoice.get("no_show_fee_cents", 0)
        + invoice.get("deposit_charge_cents", 0)
    )


def create_provisional_invoice(event, org):
    """Born PROVISIONAL at approval or rebooking: room charge from pinned rates,
    forward-looking service charge, EXTERNAL insurance surcharge."""
    billable_start, billable_end = billable_interval(event)
    room_charge = pricing.room_charge_cents(
        billable_start,
        billable_end,
        event["pinned_hourly_rate_cents"],
        event["pinned_peak_multiplier_bps"],
    )
    service_charge = sum(
        (o.get("quoted_total_cents") or 0)
        for o in orders_of_event(event)
        if o.get("status") in ORDER_PROVISIONAL_CHARGE_STATUSES
    )
    surcharge = pricing.insurance_surcharge_cents(room_charge + service_charge, org["org_type"])
    invoice = db.new_row(
        db.invoices,
        event_id=event["id"],
        org_id=event["requester_org_id"],
        status="PROVISIONAL",
        room_charge_cents=room_charge,
        service_charge_cents=service_charge,
        insurance_surcharge_cents=surcharge,
        cancellation_fee_cents=0,
        no_show_fee_cents=0,
        deposit_charge_cents=0,
        total_cents=room_charge + service_charge + surcharge,
        paid_cents=0,
        waived_cents=0,
        refunded_cents=0,
    )
    return invoice


def recompute_provisional(event):
    """Every quote, re-quote, approval, revision request and order cancellation
    recomputes the parent provisional invoice's service charge (the
    forward-looking variant)."""
    invoice = provisional_invoice(event)
    if invoice is None:
        return
    service_charge = sum(
        (o.get("quoted_total_cents") or 0)
        for o in orders_of_event(event)
        if o.get("status") in ORDER_PROVISIONAL_CHARGE_STATUSES
    )
    org = db.organizations.get(event.get("requester_org_id"))
    org_type = org["org_type"] if org else None
    surcharge = pricing.insurance_surcharge_cents(
        invoice["room_charge_cents"] + service_charge, org_type
    )
    total = (
        invoice["room_charge_cents"]
        + service_charge
        + surcharge
        + invoice.get("cancellation_fee_cents", 0)
        + invoice.get("no_show_fee_cents", 0)
        + invoice.get("deposit_charge_cents", 0)
    )
    db.set_fields(
        invoice,
        service_charge_cents=service_charge,
        insurance_surcharge_cents=surcharge,
        total_cents=total,
    )


def finalize_invoice(event, kind):
    """The final variant at completion, no-show, or cancellation-with-charges.

    COMPLETED: FULFILLED/INVOICED service only, surcharge recomputed on the
      final base for EXTERNAL, deposit charges included.
    NO_SHOW: room at 100%, final service, flat 5000 no-show fee, deposits, no
      surcharge.
    CANCELLED: cancellation fee + final service + deposits; room line excluded;
      no surcharge.

    Fulfilled orders lock into the final invoice (FULFILLED -> INVOICED).
    """
    invoice = current_invoice(event)
    if invoice is None:
        return
    final_service = sum(
        (o.get("quoted_total_cents") or 0)
        for o in orders_of_event(event)
        if o.get("status") in ORDER_FINAL_CHARGE_STATUSES
    )
    org = db.organizations.get(event.get("requester_org_id"))
    org_type = org["org_type"] if org else None
    fields = {"service_charge_cents": final_service}
    if kind == "COMPLETED":
        fields["insurance_surcharge_cents"] = pricing.insurance_surcharge_cents(
            invoice["room_charge_cents"] + final_service, org_type
        )
        fields["cancellation_fee_cents"] = 0
        fields["no_show_fee_cents"] = 0
    elif kind == "NO_SHOW":
        fields["insurance_surcharge_cents"] = 0
        fields["cancellation_fee_cents"] = 0
        fields["no_show_fee_cents"] = NO_SHOW_FLAT_FEE_CENTS
    elif kind == "CANCELLED":
        fields["room_charge_cents"] = 0
        fields["insurance_surcharge_cents"] = 0
        fields["no_show_fee_cents"] = 0
        fields["cancellation_fee_cents"] = event.get("cancellation_fee_cents") or 0
    for name, value in fields.items():
        invoice[name] = value
    _recompute_total(invoice)
    if invoice.get("status") == "PROVISIONAL":
        invoice["status"] = "FINALIZED"
    db.touch(invoice)
    for order in orders_of_event(event):
        if order.get("status") == "FULFILLED":
            db.set_fields(order, status="INVOICED")


def void_provisional(event):
    """Void the event's PROVISIONAL invoice, if one exists (bump, approval
    expiry, free cancellation, suspension)."""
    invoice = provisional_invoice(event)
    if invoice is None:
        return None
    db.set_fields(invoice, status="VOIDED")
    return invoice


def add_deposit_forfeit(event, forfeit_cents):
    """Deposit forfeits accrue into deposit_charge_cents and totals are
    recomputed - even on an already-FINALIZED invoice."""
    if forfeit_cents <= 0:
        return
    invoice = current_invoice(event)
    if invoice is None:
        return
    invoice["deposit_charge_cents"] = invoice.get("deposit_charge_cents", 0) + forfeit_cents
    _recompute_total(invoice)
    db.touch(invoice)
