"""Cascades (PRD 3.1, 3.4): the bump cascade, the suspension cascade, and the
shared order-cancellation / grant-revocation sweeps."""

import db
from constants import GRANT_OUTSTANDING_STATUSES, ORDER_NONTERMINAL_STATUSES
from services import invoices as invoice_service


def grants_of_event(event):
    return [g for g in db.all_of(db.access_grants) if g.get("event_id") == event["id"]]


def revoke_requested_grants(event):
    """The system revokes grants still in REQUESTED whenever the underlying
    event is bumped, cancelled, declined, or caught in a suspension cascade."""
    for grant in grants_of_event(event):
        if grant.get("status") == "REQUESTED":
            db.set_fields(grant, status="REVOKED")


def cancel_nonterminal_orders(event, fee_waived):
    """Move every non-terminal, non-FULFILLED order to CANCELLED.  fee_waived is
    true only for system cascades (bump, admin/suspension cancel, completion);
    false for requester cancels and for orders swept aside by a no-show."""
    for order in invoice_service.orders_of_event(event):
        if order.get("status") in ORDER_NONTERMINAL_STATUSES:
            db.set_fields(order, status="CANCELLED", fee_waived=fee_waived)


def bump_event(event):
    """The full bump cascade (PRD 3.4): room_id cleared, the PROVISIONAL invoice
    voided in a full waiver, every non-terminal service order cancelled with
    fee_waived true, and REQUESTED access grants revoked."""
    invoice_service.void_provisional(event)
    for order in invoice_service.orders_of_event(event):
        if order.get("status") in ORDER_NONTERMINAL_STATUSES or order.get("status") == "FULFILLED":
            db.set_fields(order, status="CANCELLED", fee_waived=True)
    revoke_requested_grants(event)
    event["room_id"] = None
    event["status"] = "BUMPED"
    db.touch(event)


def suspension_cascade(org):
    """PRD 3.1: on suspension the org's REQUESTED events are DECLINED
    (decline_reason ORG_SUSPENDED), its APPROVED events are CANCELLED
    (cancel_reason ORG_SUSPENDED, fee 0, provisional invoice voided), and its
    access grants still in REQUESTED are revoked.  CONFIRMED and IN_PROGRESS
    events are deliberately not touched."""
    for event in db.all_of(db.event_reservations):
        if event.get("requester_org_id") != org["id"]:
            continue
        status = event.get("status")
        if status == "REQUESTED":
            db.set_fields(event, status="DECLINED", decline_reason="ORG_SUSPENDED")
        elif status == "APPROVED":
            invoice_service.void_provisional(event)
            for order in invoice_service.orders_of_event(event):
                if order.get("status") in ORDER_NONTERMINAL_STATUSES or order.get("status") == "FULFILLED":
                    db.set_fields(order, status="CANCELLED", fee_waived=True)
            db.set_fields(
                event,
                status="CANCELLED",
                cancel_reason="ORG_SUSPENDED",
                cancellation_fee_cents=0,
            )
    for grant in db.all_of(db.access_grants):
        if grant.get("status") != "REQUESTED":
            continue
        event = db.event_reservations.get(grant.get("event_id"))
        if event is not None and event.get("requester_org_id") == org["id"]:
            db.set_fields(grant, status="REVOKED")
