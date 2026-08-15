"""Borrow tickets (PRD §3.7)."""

from flask import Blueprint, request

import db
from errors import (
    invalid_state, invalid_request, stale_version, ApiError,
    ERR_LOT_NOT_AVAILABLE, ERR_INSUFFICIENT_STOCK, ERR_SAME_STOCK_BORROW,
    ERR_PAYBACK_EXCEEDS_BORROWED, ERR_TICKET_HAS_PAYBACK, ERR_BORROWED_DOSES_CONSUMED,
)
from middleware import get_auth, ALL_ROLES, ROLE_VACCINE_MANAGER
from response import success_object, paginate
from services.ledger import recompute_private_lending_balance
from services.validate import (
    require_body, require_string, require_int, require_enum, get_or_404,
    ENUM_BORROW_DIRECTION, ENUM_REASON_CODE,
)

bp = Blueprint("borrow_tickets", __name__)


def serialize_ticket(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "provider_site_id": t["provider_site_id"],
        "from_lot_id": t["from_lot_id"],
        "to_lot_id": t["to_lot_id"],
        "direction": t["direction"],
        "borrowed_quantity": t["borrowed_quantity"],
        "paid_back_quantity": t["paid_back_quantity"],
        "status": t["status"],
        "opened_by_user_id": t["opened_by_user_id"],
        "reason_code": t["reason_code"],
    }


@bp.route("/provider-sites/<site_id>/borrow-tickets", methods=["POST"])
def create_borrow_ticket(site_id):
    user_id = get_auth([ROLE_VACCINE_MANAGER])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    body = require_body(request.get_json(silent=True))
    from_lot_id = require_string(body, "from_lot_id")
    to_lot_id = require_string(body, "to_lot_id")
    direction = require_enum(body, "direction", ENUM_BORROW_DIRECTION)
    borrowed_quantity = require_int(body, "borrowed_quantity", minimum=1)
    reason_code = require_enum(body, "reason_code", ENUM_REASON_CODE)

    from_lot = get_or_404(db.lots, from_lot_id, "lot")
    to_lot = get_or_404(db.lots, to_lot_id, "lot")

    # Direction must be across stocks and consistent with the two lots' stock types.
    if from_lot["stock_type"] == to_lot["stock_type"]:
        raise ApiError(ERR_SAME_STOCK_BORROW,
                       "BorrowTicket direction inconsistent with lot stock_types or same-stock borrow",
                       422)
    if direction == "PUBLIC_FROM_PRIVATE":
        # VFC-eligible dose administered from PRIVATE stock: from_lot is the PRIVATE
        # lender, to_lot is the PUBLIC borrower.
        if from_lot["stock_type"] != "PRIVATE" or to_lot["stock_type"] != "PUBLIC_VFC":
            raise ApiError(ERR_SAME_STOCK_BORROW,
                           "PUBLIC_FROM_PRIVATE requires from_lot PRIVATE and to_lot PUBLIC_VFC",
                           422)
    else:  # PRIVATE_FROM_PUBLIC
        if from_lot["stock_type"] != "PUBLIC_VFC" or to_lot["stock_type"] != "PRIVATE":
            raise ApiError(ERR_SAME_STOCK_BORROW,
                           "PRIVATE_FROM_PUBLIC requires from_lot PUBLIC_VFC and to_lot PRIVATE",
                           422)

    # Lender lot must be AVAILABLE with sufficient stock
    if from_lot["status"] != "AVAILABLE":
        raise ApiError(ERR_LOT_NOT_AVAILABLE, "Lot is not AVAILABLE", 409)
    if from_lot["quantity_on_hand"] < borrowed_quantity:
        raise ApiError(ERR_INSUFFICIENT_STOCK, "Lot quantity_on_hand < requested doses", 422)

    # Apply effects
    from_lot["quantity_on_hand"] -= borrowed_quantity
    from_lot["updated_at"] = db.now_ts()
    from_lot["version"] += 1
    if from_lot["quantity_on_hand"] == 0:
        from_lot["status"] = "DEPLETED"

    to_lot["quantity_borrowed_in"] += borrowed_quantity
    to_lot["updated_at"] = db.now_ts()
    to_lot["version"] += 1

    now = db.now_ts()
    ticket = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "from_lot_id": from_lot["id"],
        "to_lot_id": to_lot["id"],
        "direction": direction,
        "borrowed_quantity": borrowed_quantity,
        "paid_back_quantity": 0,
        "status": "OPEN",
        "opened_by_user_id": user_id,
        "reason_code": reason_code,
    }
    db.borrow_tickets[ticket["id"]] = ticket

    recompute_private_lending_balance(site["id"])

    return success_object(serialize_ticket(ticket), 201)


def _filter_tickets(items, args):
    f_site = args.get("provider_site_id")
    f_from = args.get("from_lot_id")
    f_to = args.get("to_lot_id")
    f_status = args.get("status")
    f_direction = args.get("direction")
    if f_site is not None:
        items = [t for t in items if t["provider_site_id"] == f_site]
    if f_from is not None:
        items = [t for t in items if t["from_lot_id"] == f_from]
    if f_to is not None:
        items = [t for t in items if t["to_lot_id"] == f_to]
    if f_status is not None:
        items = [t for t in items if t["status"] == f_status]
    if f_direction is not None:
        items = [t for t in items if t["direction"] == f_direction]
    return items


@bp.route("/provider-sites/<site_id>/borrow-tickets", methods=["GET"])
def list_borrow_tickets(site_id):
    get_auth(ALL_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    items = [t for t in db.borrow_tickets.values() if t["provider_site_id"] == site["id"]]
    items = _filter_tickets(items, request.args)
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    return paginate([serialize_ticket(t) for t in items], request.args)


@bp.route("/borrow-tickets", methods=["GET"])
def list_borrow_tickets_global():
    get_auth(ALL_ROLES)
    items = list(db.borrow_tickets.values())
    items = _filter_tickets(items, request.args)
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    return paginate([serialize_ticket(t) for t in items], request.args)


@bp.route("/borrow-tickets/<ticket_id>", methods=["GET"])
def get_borrow_ticket(ticket_id):
    get_auth(ALL_ROLES)
    ticket = get_or_404(db.borrow_tickets, ticket_id, "borrow ticket")
    return success_object(serialize_ticket(ticket))


def _get_site_ticket(site_id, ticket_id):
    site = get_or_404(db.provider_sites, site_id, "provider site")
    ticket = get_or_404(db.borrow_tickets, ticket_id, "borrow ticket")
    if ticket["provider_site_id"] != site["id"]:
        from errors import not_found
        raise not_found("borrow ticket")
    return site, ticket


@bp.route("/provider-sites/<site_id>/borrow-tickets/<ticket_id>/record-payback", methods=["POST"])
def record_payback(site_id, ticket_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site, ticket = _get_site_ticket(site_id, ticket_id)
    body = require_body(request.get_json(silent=True))

    if "expected_borrow_ticket_version" not in body or body["expected_borrow_ticket_version"] is None:
        raise invalid_request("Missing required field: expected_borrow_ticket_version")
    expected_version = body["expected_borrow_ticket_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise invalid_request("Field expected_borrow_ticket_version must be an integer")

    payback_quantity = require_int(body, "payback_quantity")  # range checked below
    paying_lot_id = require_string(body, "paying_lot_id")

    # Existence of paying lot
    paying_lot = get_or_404(db.lots, paying_lot_id, "lot")

    # Priority 4: OCC
    if expected_version != ticket["version"]:
        raise stale_version()

    # Priority 5: state
    if ticket["status"] not in ("OPEN", "PARTIALLY_REPAID"):
        raise invalid_state("Ticket must be OPEN or PARTIALLY_REPAID")

    # Business checks in scaffold order
    if payback_quantity < 1:
        raise invalid_request("payback_quantity must be >= 1")

    remaining = ticket["borrowed_quantity"] - ticket["paid_back_quantity"]
    if payback_quantity > remaining:
        raise ApiError(ERR_PAYBACK_EXCEEDS_BORROWED,
                       "paid_back_quantity + payback_quantity > borrowed_quantity", 422)

    to_lot = db.lots[ticket["to_lot_id"]]
    from_lot = db.lots[ticket["from_lot_id"]]

    # Paying lot stock_type must match the BORROWER's (to_lot) stock_type
    if paying_lot["stock_type"] != to_lot["stock_type"]:
        raise ApiError(ERR_SAME_STOCK_BORROW,
                       "Paying lot stock_type must match the borrower lot's stock_type", 422)

    if paying_lot["status"] != "AVAILABLE":
        raise ApiError(ERR_LOT_NOT_AVAILABLE, "Lot is not AVAILABLE", 409)
    if paying_lot["quantity_on_hand"] < payback_quantity:
        raise ApiError(ERR_INSUFFICIENT_STOCK, "Lot quantity_on_hand < requested doses", 422)

    # Apply effects
    ticket["paid_back_quantity"] += payback_quantity
    paying_lot["quantity_on_hand"] -= payback_quantity
    paying_lot["updated_at"] = db.now_ts()
    paying_lot["version"] += 1
    if paying_lot["quantity_on_hand"] == 0:
        paying_lot["status"] = "DEPLETED"

    from_lot["quantity_on_hand"] += payback_quantity
    from_lot["updated_at"] = db.now_ts()
    from_lot["version"] += 1
    # Note: returning doses to the lender lot does not resurrect a non-AVAILABLE
    # status; per the state machine, transitions out of DEPLETED/EXPIRED/etc. are
    # not defined, so only the quantity is restored.

    to_lot["quantity_borrowed_in"] -= payback_quantity
    to_lot["updated_at"] = db.now_ts()
    to_lot["version"] += 1

    if ticket["paid_back_quantity"] == ticket["borrowed_quantity"]:
        ticket["status"] = "REPAID"
    else:
        ticket["status"] = "PARTIALLY_REPAID"
    ticket["updated_at"] = db.now_ts()
    ticket["version"] += 1

    recompute_private_lending_balance(site["id"])

    return success_object(serialize_ticket(ticket))


@bp.route("/provider-sites/<site_id>/borrow-tickets/<ticket_id>/void", methods=["POST"])
def void_ticket(site_id, ticket_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site, ticket = _get_site_ticket(site_id, ticket_id)
    if ticket["status"] != "OPEN":
        raise invalid_state("Ticket must be OPEN to void")
    if ticket["paid_back_quantity"] != 0:
        raise ApiError(ERR_TICKET_HAS_PAYBACK,
                       "Attempted to void a ticket that already has paid_back_quantity > 0", 409)
    to_lot = db.lots[ticket["to_lot_id"]]
    from_lot = db.lots[ticket["from_lot_id"]]
    if to_lot["quantity_borrowed_in"] < ticket["borrowed_quantity"]:
        raise ApiError(ERR_BORROWED_DOSES_CONSUMED,
                       "Borrowed IOU is no longer intact; doses already consumed", 409)

    to_lot["quantity_borrowed_in"] -= ticket["borrowed_quantity"]
    to_lot["updated_at"] = db.now_ts()
    to_lot["version"] += 1

    from_lot["quantity_on_hand"] += ticket["borrowed_quantity"]
    from_lot["updated_at"] = db.now_ts()
    from_lot["version"] += 1

    ticket["status"] = "VOIDED"
    ticket["updated_at"] = db.now_ts()
    ticket["version"] += 1

    recompute_private_lending_balance(site["id"])

    return success_object(serialize_ticket(ticket))
