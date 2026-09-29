"""Ticket endpoints (PRD 3.2, 3.3, 3.8)."""

from flask import Blueprint

from db import db, public, sort_created_asc, touch
from errors import ApiError
from middleware import ANY_ROLE, auth, f_bool, f_enum, f_int, f_str, get_body, q
from response import ok
from services import calc
from services.domain import (
    append_audit,
    create_ticket_record,
    get_or_404,
    listings_of_ticket,
    recompute_fraud_score,
    recompute_zone_posture,
)
from routes._common import filter_eq, paginated

bp = Blueprint("tickets", __name__)

TICKET_TYPES = ("PAID", "COMP", "WILL_CALL", "CREDENTIAL")


@bp.route("/tickets", methods=["POST"])
def issue_ticket():
    auth(("BoxOfficeAgent",))
    body = get_body()
    event_id = f_str(body, "event_id", allow_empty=False)
    access_zone_id = f_str(body, "access_zone_id", allow_empty=False)
    holder_patron_id = f_str(body, "holder_patron_id", allow_empty=False)
    ticket_type = f_enum(body, "ticket_type", TICKET_TYPES)
    face_value_cents = f_int(body, "face_value_cents", minimum=0)

    event = get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    zone = get_or_404(db.zones, access_zone_id, "ERR_ZONE_NOT_FOUND")
    patron = get_or_404(db.patrons, holder_patron_id, "ERR_PATRON_NOT_FOUND")
    if zone["event_id"] != event_id:
        raise ApiError("ERR_CROSS_EVENT_REFERENCE")
    if event["status"] not in ("ON_SALE", "DOORS_OPEN"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")

    ticket = create_ticket_record(
        event_id, access_zone_id, patron["id"], ticket_type, face_value_cents
    )

    zone["issued_entitlement_count"] += 1
    recompute_zone_posture(zone)
    touch(zone)

    event["entitlements_outstanding"] += 1
    if ticket_type == "PAID":
        event["settlement_pool_cents"] += face_value_cents
    touch(event)

    return ok(public(ticket), 201)


@bp.route("/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    auth(ANY_ROLE)
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    return ok(public(ticket))


@bp.route("/tickets", methods=["GET"])
def list_tickets():
    auth(ANY_ROLE)
    rows = sort_created_asc(list(db.tickets.values()))
    rows = filter_eq(rows, "event_id", q("event_id"))
    rows = filter_eq(rows, "access_zone_id", q("access_zone_id"))
    rows = filter_eq(rows, "holder_patron_id", q("holder_patron_id"))
    rows = filter_eq(rows, "credential_request_id", q("credential_request_id"))
    rows = filter_eq(rows, "lifecycle_status", q("lifecycle_status"))
    rows = filter_eq(rows, "admission_status", q("admission_status"))
    return paginated(rows)


@bp.route("/tickets/<ticket_id>/barcode", methods=["GET"])
def read_barcode(ticket_id):
    auth(("Patron", "BoxOfficeAgent", "GateOperator", "VenueAdmin"))
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    event = db.events[ticket["event_id"]]
    index = calc.epoch_index(event["_anchor_dt"], db.clock)
    return ok({
        "ticket_id": ticket["id"],
        "barcode_seed": ticket["barcode_seed"],
        "barcode_epoch_index": index,
        "current_barcode": calc.current_barcode(ticket["barcode_seed"], index),
        "accepted_epoch_floor": index - calc.SKEW_TOLERANCE_EPOCHS,
    })


@bp.route("/tickets/<ticket_id>/device-binding", methods=["POST"])
def bind_device(ticket_id):
    user_id, _role = auth(("Patron",))
    body = get_body()
    fingerprint = f_str(body, "device_fingerprint", allow_empty=False)
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    if ticket["holder_patron_id"] != user_id:
        raise ApiError("ERR_NOT_TICKET_HOLDER")
    if ticket["lifecycle_status"] == "VOIDED":
        raise ApiError("ERR_TICKET_VOIDED")

    rebinding = ticket["device_binding_status"] in ("BOUND", "RELEASED")
    ticket["bound_device_fingerprint"] = fingerprint
    ticket["device_binding_status"] = "BOUND"
    touch(ticket)

    if rebinding:
        patron = db.patrons.get(ticket["holder_patron_id"])
        if patron is not None:
            patron["device_rebind_count"] += 1
            recompute_fraud_score(patron, "PROVISIONAL")
            touch(patron)
    return ok(public(ticket))


@bp.route("/tickets/<ticket_id>/device-binding/release", methods=["POST"])
def release_device(ticket_id):
    user_id, _role = auth(("Patron",))
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    if ticket["holder_patron_id"] != user_id:
        raise ApiError("ERR_NOT_TICKET_HOLDER")
    if ticket["device_binding_status"] != "BOUND":
        raise ApiError("ERR_INVALID_STATE", "The ticket has no active device binding.")
    ticket["bound_device_fingerprint"] = None
    ticket["device_binding_status"] = "RELEASED"
    touch(ticket)
    return ok(public(ticket))


@bp.route("/tickets/<ticket_id>/void", methods=["POST"])
def void_ticket(ticket_id):
    user_id, role = auth(("SecurityInvestigator",))
    body = get_body()
    reason = f_str(body, "reason", allow_empty=False)
    refund = f_bool(body, "refund_to_holder")
    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    if ticket["lifecycle_status"] == "VOIDED":
        raise ApiError("ERR_INVALID_STATE", "The ticket is already VOIDED.")

    event = db.events[ticket["event_id"]]
    zone = db.zones[ticket["access_zone_id"]]
    holder = db.patrons.get(ticket["holder_patron_id"])
    was_listed = ticket["lifecycle_status"] == "LISTED"

    ticket["lifecycle_status"] = "VOIDED"
    touch(ticket)

    if was_listed:
        for listing in listings_of_ticket(ticket["id"]):
            if listing["status"] == "LISTED":
                listing["status"] = "SUSPENDED"
                touch(listing)
                append_audit(
                    event["id"], "RESALE_LISTING", listing["id"],
                    "RESALE_LISTING_SUSPENDED", role, user_id,
                    "Resale listing %s suspended because ticket %s was voided."
                    % (listing["id"], ticket["id"]),
                )

    zone["issued_entitlement_count"] = max(zone["issued_entitlement_count"] - 1, 0)
    recompute_zone_posture(zone)
    touch(zone)

    event["entitlements_outstanding"] = max(event["entitlements_outstanding"] - 1, 0)
    refunded = 0
    if refund and ticket["ticket_type"] == "PAID":
        refunded = ticket["face_value_cents"]
        event["settlement_pool_cents"] -= refunded
        if holder is not None:
            holder["remediation_credit_cents"] += refunded
            touch(holder)
    touch(event)

    append_audit(
        event["id"], "TICKET", ticket["id"], "TICKET_VOIDED", role, user_id,
        "Ticket %s voided (%s); refund %d cents; lifecycle_status -> VOIDED."
        % (ticket["id"], reason, refunded),
    )
    return ok(public(ticket))
