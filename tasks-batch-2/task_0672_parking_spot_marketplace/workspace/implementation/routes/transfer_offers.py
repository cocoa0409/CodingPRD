"""Transfer offer lifecycle: create, reads, accept, decline, withdraw."""
from flask import Blueprint, request

from clock import clock
from db import db, make_versioned, touch
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE,
    ERR_STALE_BOOKING_VERSION,
    ERR_DRIVER_SUSPENDED,
    ERR_TRANSFER_TO_SELF,
    ERR_INSUFFICIENT_WALLET,
)
from middleware import require_auth, require_role
from response import success, success_list
from serialize import transfer_offer_view
from util import require_body, require_str, require_int, parse_pagination, paginate

bp = Blueprint("transfer_offers", __name__)


@bp.post("/transfer-offers")
def create_transfer_offer():
    caller = require_auth()
    require_role(caller, "Driver")
    data = require_body(request.get_json(silent=True))
    booking_id = require_str(data, "booking_id")
    to_driver_id = require_str(data, "to_driver_id")

    # Existence (priority 3), left-to-right: booking then to_driver.
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    to_driver = db.drivers.get(to_driver_id)
    if to_driver is None:
        raise err(ERR_NOT_FOUND, "Recipient driver not found.")

    # Ownership (priority 4): acting Driver must hold the booking (offeror).
    if booking["driver_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Driver does not hold this booking.")

    # State (priority 10): booking must be RESERVED to be offered.
    if booking["occupancy_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Booking is not RESERVED.")

    # OCC (priority 11): expected_booking_version must match.
    expected_booking_version = require_int(data, "expected_booking_version")
    if expected_booking_version != booking["version"]:
        raise err(ERR_STALE_BOOKING_VERSION, "expected_booking_version does not match booking.")

    # Transfer-to-self (priority 42): recipient must differ from current holder.
    if to_driver_id == booking["driver_id"]:
        raise err(ERR_TRANSFER_TO_SELF, "Cannot transfer to the current holder.")

    rec = make_versioned(
        {
            "booking_id": booking_id,
            "from_driver_id": booking["driver_id"],
            "to_driver_id": to_driver_id,
            "status": "PENDING",
        }
    )
    db.transfer_offers[rec["id"]] = rec
    # Booking version bump on offer creation.
    touch(booking)
    return success(transfer_offer_view(rec), status=201)


@bp.get("/transfer-offers/<offer_id>")
def get_transfer_offer(offer_id):
    caller = require_auth()
    require_role(caller, "Driver", "PlatformAdmin")
    rec = db.transfer_offers.get(offer_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Transfer offer not found.")
    return success(transfer_offer_view(rec))


@bp.get("/transfer-offers")
def list_transfer_offers():
    caller = require_auth()
    require_role(caller, "Driver", "PlatformAdmin")
    limit, offset = parse_pagination(request.args)
    to_driver_id = request.args.get("to_driver_id")
    from_driver_id = request.args.get("from_driver_id")
    booking_id = request.args.get("booking_id")
    items = list(db.transfer_offers.values())
    if to_driver_id is not None:
        items = [t for t in items if t["to_driver_id"] == to_driver_id]
    if from_driver_id is not None:
        items = [t for t in items if t["from_driver_id"] == from_driver_id]
    if booking_id is not None:
        items = [t for t in items if t["booking_id"] == booking_id]
    items.sort(key=lambda t: t["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([transfer_offer_view(t) for t in page], limit, offset, total)


@bp.post("/transfer-offers/<offer_id>/accept")
def accept_transfer_offer(offer_id):
    caller = require_auth()
    require_role(caller, "Driver")
    offer = db.transfer_offers.get(offer_id)
    if offer is None:
        raise err(ERR_NOT_FOUND, "Transfer offer not found.")
    # Ownership (priority 4): acting Driver must be the recipient.
    if offer["to_driver_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Driver is not the recipient.")
    # State (priority 10): offer PENDING and booking RESERVED.
    if offer["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Offer is not PENDING.")
    booking = db.bookings.get(offer["booking_id"])
    if booking is None:
        raise err(ERR_NOT_FOUND, "Booking not found.")
    if booking["occupancy_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Booking is not RESERVED.")

    now = clock.now()
    # Transfer only before the window opens: clock < start_at.
    if now >= booking["_start_at_dt"]:
        raise err(ERR_INVALID_STATE, "Reservation window has already opened.")

    to_driver = db.drivers[offer["to_driver_id"]]
    from_driver = db.drivers[offer["from_driver_id"]]

    # Recipient not suspended (priority 41).
    if to_driver["standing_tier"] == "SUSPENDED":
        raise err(ERR_DRIVER_SUSPENDED, "Recipient is suspended.")

    # Wallet funding (priority 50): recipient must be able to pay the frozen quote.
    quoted = booking["quoted_amount_cents"]
    if to_driver["wallet_balance_cents"] < quoted:
        raise err(ERR_INSUFFICIENT_WALLET, "Recipient cannot cover the quoted amount.")

    # Commit: full make-whole (no tiered refund). Net wallet change is zero.
    to_driver["wallet_balance_cents"] -= quoted
    from_driver["wallet_balance_cents"] += quoted
    touch(to_driver)
    touch(from_driver)

    offer["status"] = "ACCEPTED"
    booking["driver_id"] = offer["to_driver_id"]
    booking["transfer_count"] += 1
    touch(booking)
    touch(offer)
    return success(transfer_offer_view(offer))


@bp.post("/transfer-offers/<offer_id>/decline")
def decline_transfer_offer(offer_id):
    caller = require_auth()
    require_role(caller, "Driver")
    offer = db.transfer_offers.get(offer_id)
    if offer is None:
        raise err(ERR_NOT_FOUND, "Transfer offer not found.")
    if offer["to_driver_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Driver is not the recipient.")
    if offer["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Offer is not PENDING.")
    offer["status"] = "DECLINED"
    touch(offer)
    return success(transfer_offer_view(offer))


@bp.post("/transfer-offers/<offer_id>/withdraw")
def withdraw_transfer_offer(offer_id):
    caller = require_auth()
    require_role(caller, "Driver")
    offer = db.transfer_offers.get(offer_id)
    if offer is None:
        raise err(ERR_NOT_FOUND, "Transfer offer not found.")
    if offer["from_driver_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Driver is not the offeror.")
    if offer["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Offer is not PENDING.")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return success(transfer_offer_view(offer))
