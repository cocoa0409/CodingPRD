"""TransferRequest endpoints (PRD 3.5)."""

from flask import Blueprint

from db import base_record, db, public, sort_created_asc, touch
from errors import ApiError
from middleware import auth, f_str, get_body, q
from response import ok
from services import calc
from services.domain import get_or_404
from routes._common import filter_eq, paginated
from util import iso_clock

bp = Blueprint("transfers", __name__)

TRANSFER_READERS = ("Patron", "BoxOfficeAgent", "SecurityInvestigator", "VenueAdmin")


def _transfer_window_open(event):
    return db.clock < event["_transfer_close_dt"] and event["status"] in ("ON_SALE", "DOORS_OPEN")


@bp.route("/transfer-requests", methods=["POST"])
def create_transfer():
    user_id, _role = auth(("Patron",))
    body = get_body()
    ticket_id = f_str(body, "ticket_id", allow_empty=False)
    to_patron_id = f_str(body, "to_patron_id", allow_empty=False)

    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    recipient = get_or_404(db.patrons, to_patron_id, "ERR_PATRON_NOT_FOUND")

    if ticket["holder_patron_id"] != user_id:
        raise ApiError("ERR_NOT_TICKET_HOLDER")
    if ticket["lifecycle_status"] == "VOIDED":
        raise ApiError("ERR_TICKET_VOIDED")

    event = db.events[ticket["event_id"]]
    if not _transfer_window_open(event):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_TRANSFER")

    seller = db.patrons.get(user_id)
    if seller is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    if seller["fraud_risk_score"] >= calc.FRAUD_BLOCK_THRESHOLD:
        raise ApiError("ERR_PATRON_FRAUD_BLOCKED")
    if ticket["transfer_count"] >= event["transfer_limit_per_ticket"]:
        raise ApiError("ERR_TRANSFER_LIMIT_EXCEEDED")
    if not recipient["identity_verified"]:
        raise ApiError("ERR_RECIPIENT_NOT_VERIFIED")
    if ticket["ticket_type"] in ("COMP", "CREDENTIAL"):
        raise ApiError("ERR_TICKET_NOT_TRANSFERABLE")

    rec = base_record()
    rec["ticket_id"] = ticket["id"]
    rec["from_patron_id"] = user_id
    rec["to_patron_id"] = to_patron_id
    rec["status"] = "PENDING"
    rec["decided_at"] = None
    db.transfers[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.route("/transfer-requests/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    auth(TRANSFER_READERS)
    transfer = get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    return ok(public(transfer))


@bp.route("/transfer-requests", methods=["GET"])
def list_transfers():
    auth(TRANSFER_READERS)
    rows = sort_created_asc(list(db.transfers.values()))
    rows = filter_eq(rows, "ticket_id", q("ticket_id"))
    rows = filter_eq(rows, "from_patron_id", q("from_patron_id"))
    rows = filter_eq(rows, "to_patron_id", q("to_patron_id"))
    rows = filter_eq(rows, "status", q("status"))
    return paginated(rows)


@bp.route("/transfer-requests/<transfer_id>/accept", methods=["POST"])
def accept_transfer(transfer_id):
    user_id, _role = auth(("Patron",))
    transfer = get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if transfer["to_patron_id"] != user_id:
        raise ApiError("ERR_NOT_TICKET_HOLDER")
    if transfer["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The transfer request is already decided.")

    ticket = db.tickets[transfer["ticket_id"]]
    event = db.events[ticket["event_id"]]
    if not _transfer_window_open(event):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_TRANSFER")
    if ticket["transfer_count"] >= event["transfer_limit_per_ticket"]:
        raise ApiError("ERR_TRANSFER_LIMIT_EXCEEDED")
    recipient = db.patrons.get(user_id)
    if recipient is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    if not recipient["identity_verified"]:
        raise ApiError("ERR_RECIPIENT_NOT_VERIFIED")
    if ticket["lifecycle_status"] not in ("ISSUED", "TRANSFERRED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "The ticket's lifecycle_status does not permit a handover.",
        )

    decided = iso_clock(db.clock)
    transfer["status"] = "ACCEPTED"
    transfer["decided_at"] = decided
    touch(transfer)

    ticket["holder_patron_id"] = transfer["to_patron_id"]
    ticket["lifecycle_status"] = "TRANSFERRED"
    ticket["transfer_count"] += 1
    ticket["bound_device_fingerprint"] = None
    ticket["device_binding_status"] = "RELEASED"
    touch(ticket)

    for other in sort_created_asc(list(db.transfers.values())):
        if other["id"] != transfer["id"] and other["ticket_id"] == ticket["id"] \
                and other["status"] == "PENDING":
            other["status"] = "DECLINED"
            other["decided_at"] = decided
            touch(other)

    return ok(public(transfer))


@bp.route("/transfer-requests/<transfer_id>/decline", methods=["POST"])
def decline_transfer(transfer_id):
    user_id, _role = auth(("Patron",))
    transfer = get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if user_id not in (transfer["to_patron_id"], transfer["from_patron_id"]):
        raise ApiError("ERR_NOT_TICKET_HOLDER")
    if transfer["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The transfer request is already decided.")
    transfer["status"] = "DECLINED"
    transfer["decided_at"] = iso_clock(db.clock)
    touch(transfer)
    return ok(public(transfer))
