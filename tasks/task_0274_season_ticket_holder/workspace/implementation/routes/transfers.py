"""TicketTransfer: create, forward, list, complete-sale, cancel, fetch, list."""
from flask import Blueprint, request

import db
import calculations as calc
from errors import err
from helpers import (
    get_json_body,
    get_or_404,
    paginate,
    require_enum,
    require_str,
    ticket_transfer_view,
)
from middleware import get_auth, require_role
from response import success, success_list

bp = Blueprint("transfers", __name__)

TRANSFER_TERMINAL = {"FORWARDED", "SOLD", "CANCELLED"}


def _owning_account_of_assignment(sa):
    sub = db.subscriptions.get(sa["subscription_id"])
    if sub is None:
        return None, None
    return sub["account_id"], sub


@bp.route("/ticket-transfers", methods=["POST"])
def create_transfer():
    user_id, role = get_auth()
    require_role(role, {"AccountHolder"})
    body = get_json_body()
    seat_assignment_id = require_str(body, "seat_assignment_id")
    with db.lock:
        sa = db.seat_assignments.get(seat_assignment_id)
        if sa is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "seat_assignment_id not found")
        transfer_type = require_enum(body, "transfer_type", {"FORWARD", "RESALE"})

        recipient_account_id = body.get("recipient_account_id")
        listing_price_cents = body.get("listing_price_cents")

        # FK existence for recipient_account_id when provided.
        if recipient_account_id is not None:
            if not isinstance(recipient_account_id, str):
                raise err("ERR_INVALID_REQUEST", "recipient_account_id must be a string")
            if recipient_account_id not in db.accounts:
                raise err(
                    "ERR_REFERENCED_RESOURCE_NOT_FOUND", "recipient_account_id not found"
                )

        # Type/range checks for listing_price_cents when provided.
        if listing_price_cents is not None:
            if isinstance(listing_price_cents, bool) or not isinstance(
                listing_price_cents, int
            ):
                raise err("ERR_INVALID_REQUEST", "listing_price_cents must be an integer")
            if listing_price_cents < 0:
                raise err("ERR_INVALID_REQUEST", "listing_price_cents must be >= 0")

        # FORWARD requires recipient_account_id at creation.
        if transfer_type == "FORWARD" and recipient_account_id is None:
            raise err("ERR_INVALID_REQUEST", "recipient_account_id required for FORWARD")

        # Ownership: holder must own the assignment's subscription.
        owner_account_id, sub = _owning_account_of_assignment(sa)
        if owner_account_id != user_id:
            raise err("ERR_SECTION_MISMATCH", "Holder does not own this seat assignment")

        # Eligibility (ERR_TRANSFER_NOT_ELIGIBLE):
        #  - RESALE requires listing_price_cents present; FORWARD forbids it.
        #  - assignment must be ASSIGNED; subscription must be ACTIVE.
        if transfer_type == "RESALE" and listing_price_cents is None:
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "listing_price_cents required for RESALE")
        if transfer_type == "FORWARD" and listing_price_cents is not None:
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "listing_price_cents forbidden for FORWARD")
        if sa["status"] != "ASSIGNED":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Seat assignment is not ASSIGNED")
        if sub is None or sub["status"] != "ACTIVE":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Subscription is not ACTIVE")

        row = db.new_common()
        row.update(
            {
                "seat_assignment_id": seat_assignment_id,
                "transfer_type": transfer_type,
                "recipient_account_id": recipient_account_id,
                "listing_price_cents": listing_price_cents,
                "payout_cents": 0,
                "status": "PENDING",
            }
        )
        db.ticket_transfers[row["id"]] = row
        return success(ticket_transfer_view(row), 201)


@bp.route("/ticket-transfers/<rid>", methods=["GET"])
def get_transfer(rid):
    _, role = get_auth()
    require_role(role, {"AccountHolder", "BoxOfficeAgent"})
    with db.lock:
        row = get_or_404(db.ticket_transfers, rid)
        return success(ticket_transfer_view(row))


@bp.route("/ticket-transfers", methods=["GET"])
def list_transfers():
    _, role = get_auth()
    require_role(role, {"AccountHolder", "BoxOfficeAgent"})
    seat_assignment_id = request.args.get("seat_assignment_id")
    recipient_account_id = request.args.get("recipient_account_id")
    status = request.args.get("status")
    transfer_type = request.args.get("transfer_type")
    with db.lock:
        rows = [
            t
            for t in db.ticket_transfers.values()
            if (seat_assignment_id is None or t["seat_assignment_id"] == seat_assignment_id)
            and (
                recipient_account_id is None
                or t["recipient_account_id"] == recipient_account_id
            )
            and (status is None or t["status"] == status)
            and (transfer_type is None or t["transfer_type"] == transfer_type)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([ticket_transfer_view(r) for r in page], limit, offset, total)


def _holder_owns_transfer(transfer, user_id):
    sa = db.seat_assignments.get(transfer["seat_assignment_id"])
    if sa is None:
        return False
    sub = db.subscriptions.get(sa["subscription_id"])
    if sub is None:
        return False
    return sub["account_id"] == user_id


@bp.route("/ticket-transfers/<rid>/forward", methods=["POST"])
def forward_transfer(rid):
    user_id, role = get_auth()
    require_role(role, {"AccountHolder"})
    with db.lock:
        transfer = get_or_404(db.ticket_transfers, rid)
        # Priority order (PRD §2.8): state (6) before ownership (8).
        if transfer["status"] != "PENDING":
            _transfer_state_error(transfer["status"])
        if not _holder_owns_transfer(transfer, user_id):
            raise err("ERR_NOT_RESOURCE_OWNER", "Holder does not own this transfer")
        if transfer["transfer_type"] != "FORWARD":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Transfer is not a FORWARD")

        sa = db.seat_assignments[transfer["seat_assignment_id"]]
        sub = db.subscriptions[sa["subscription_id"]]
        if sa["status"] != "ASSIGNED":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Seat assignment is not ASSIGNED")
        if sub["status"] != "ACTIVE":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Subscription is not ACTIVE")
        recipient = db.accounts.get(transfer["recipient_account_id"])
        if recipient is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "recipient not found")
        if recipient["status"] != "ACTIVE":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Recipient account is not ACTIVE")

        # Reassign the seat assignment to the recipient's active subscription
        # context. The recipient's active subscription receives the seat.
        recipient_sub = _recipient_active_subscription(recipient["id"])
        if recipient_sub is not None:
            sa["subscription_id"] = recipient_sub["id"]
            db.touch(sa)
            db.touch(recipient_sub)
            db.touch(sub)

        transfer["status"] = "FORWARDED"
        transfer["payout_cents"] = 0
        db.touch(transfer)
        return success(ticket_transfer_view(transfer))


@bp.route("/ticket-transfers/<rid>/list", methods=["POST"])
def list_transfer_action(rid):
    user_id, role = get_auth()
    require_role(role, {"AccountHolder"})
    with db.lock:
        transfer = get_or_404(db.ticket_transfers, rid)
        # Priority order (PRD §2.8): state (6) before ownership (8).
        if transfer["status"] != "PENDING":
            _transfer_state_error(transfer["status"])
        if not _holder_owns_transfer(transfer, user_id):
            raise err("ERR_NOT_RESOURCE_OWNER", "Holder does not own this transfer")
        if transfer["transfer_type"] != "RESALE":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Transfer is not a RESALE")
        sa = db.seat_assignments[transfer["seat_assignment_id"]]
        sub = db.subscriptions[sa["subscription_id"]]
        if sa["status"] != "ASSIGNED":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Seat assignment is not ASSIGNED")
        if sub["status"] != "ACTIVE":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Subscription is not ACTIVE")
        if transfer["listing_price_cents"] is None or transfer["listing_price_cents"] < 0:
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "listing_price_cents missing")

        transfer["status"] = "LISTED"
        db.touch(transfer)
        return success(ticket_transfer_view(transfer))


@bp.route("/ticket-transfers/<rid>/complete-sale", methods=["POST"])
def complete_sale(rid):
    _, role = get_auth()
    require_role(role, {"BoxOfficeAgent"})
    body = get_json_body()
    recipient_account_id = require_str(body, "recipient_account_id")
    with db.lock:
        transfer = get_or_404(db.ticket_transfers, rid)
        recipient = db.accounts.get(recipient_account_id)
        if recipient is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "recipient_account_id not found")
        if transfer["status"] != "LISTED":
            _transfer_state_error(transfer["status"])
        if recipient["status"] != "ACTIVE":
            raise err("ERR_TRANSFER_NOT_ELIGIBLE", "Recipient account is not ACTIVE")

        gross = transfer["listing_price_cents"]
        payout = calc.resale_payout(gross)
        transfer["payout_cents"] = payout
        transfer["recipient_account_id"] = recipient_account_id

        sa = db.seat_assignments[transfer["seat_assignment_id"]]
        sa["status"] = "REASSIGNED"
        db.touch(sa)
        sub = db.subscriptions.get(sa["subscription_id"])
        if sub is not None:
            db.touch(sub)

        transfer["status"] = "SOLD"
        db.touch(transfer)
        return success(ticket_transfer_view(transfer))


@bp.route("/ticket-transfers/<rid>/cancel", methods=["POST"])
def cancel_transfer(rid):
    user_id, role = get_auth()
    require_role(role, {"AccountHolder"})
    with db.lock:
        transfer = get_or_404(db.ticket_transfers, rid)
        # Priority order (PRD §2.8): state (6) before ownership (8).
        if transfer["status"] not in ("PENDING", "LISTED"):
            _transfer_state_error(transfer["status"])
        if not _holder_owns_transfer(transfer, user_id):
            raise err("ERR_NOT_RESOURCE_OWNER", "Holder does not own this transfer")
        transfer["status"] = "CANCELLED"
        db.touch(transfer)
        return success(ticket_transfer_view(transfer))


def _transfer_state_error(current):
    if current in TRANSFER_TERMINAL:
        raise err("ERR_VALIDATION_FROM_TERMINAL", "Transfer is in terminal state %s" % current)
    raise err("ERR_INVALID_STATE", "Illegal transition from %s" % current)


def _recipient_active_subscription(account_id):
    for sub in db.subscriptions.values():
        if sub["account_id"] == account_id and sub["status"] == "ACTIVE":
            return sub
    return None
