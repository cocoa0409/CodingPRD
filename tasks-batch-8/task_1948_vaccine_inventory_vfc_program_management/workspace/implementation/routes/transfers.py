"""Short-date transfers (PRD §3.8)."""

from flask import Blueprint, request

import db
from errors import (
    invalid_state, ApiError,
    ERR_LOT_NOT_AVAILABLE, ERR_INSUFFICIENT_STOCK, ERR_UNIT_SITE_MISMATCH,
    ERR_STORAGE_UNIT_QUARANTINED,
)
from middleware import get_auth, ALL_ROLES, ROLE_VACCINE_MANAGER
from response import success_object, paginate
from services.ledger import recompute_accountability_balance
from services.validate import (
    require_body, require_string, require_int, get_or_404,
)

bp = Blueprint("transfers", __name__)


def serialize_transfer(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "provider_site_id": t["provider_site_id"],
        "from_lot_id": t["from_lot_id"],
        "destination_site_id": t["destination_site_id"],
        "destination_storage_unit_id": t["destination_storage_unit_id"],
        "quantity_doses": t["quantity_doses"],
        "reason": t["reason"],
        "status": t["status"],
        "new_lot_id": t["new_lot_id"],
    }


@bp.route("/provider-sites/<site_id>/short-date-transfers", methods=["POST"])
def create_transfer(site_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    body = require_body(request.get_json(silent=True))
    from_lot_id = require_string(body, "from_lot_id")
    destination_site_id = require_string(body, "destination_site_id")
    destination_storage_unit_id = require_string(body, "destination_storage_unit_id")
    quantity_doses = require_int(body, "quantity_doses", minimum=1)
    reason = require_string(body, "reason")

    from_lot = get_or_404(db.lots, from_lot_id, "lot")
    dest_site = get_or_404(db.provider_sites, destination_site_id, "provider site")
    dest_unit = get_or_404(db.storage_units, destination_storage_unit_id, "storage unit")

    # Source lot must be AVAILABLE with sufficient stock at initiation
    if from_lot["status"] != "AVAILABLE":
        raise ApiError(ERR_LOT_NOT_AVAILABLE, "Lot is not AVAILABLE", 409)
    if from_lot["quantity_on_hand"] < quantity_doses:
        raise ApiError(ERR_INSUFFICIENT_STOCK, "Lot quantity_on_hand < requested doses", 422)

    now = db.now_ts()
    transfer = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "from_lot_id": from_lot["id"],
        "destination_site_id": dest_site["id"],
        "destination_storage_unit_id": dest_unit["id"],
        "quantity_doses": quantity_doses,
        "reason": reason,
        "status": "INITIATED",
        "new_lot_id": None,
    }
    db.short_date_transfers[transfer["id"]] = transfer

    # PRD §2.7: the provisional ledger counts transfers that have been
    # initiated but not yet shipped — initiation touches the transferred-out
    # term, so recompute for public stock.
    if from_lot["stock_type"] == "PUBLIC_VFC":
        recompute_accountability_balance(site["id"])

    return success_object(serialize_transfer(transfer), 201)


def _filter_transfers(items, args):
    f_site = args.get("provider_site_id")
    f_from = args.get("from_lot_id")
    f_dest_site = args.get("destination_site_id")
    f_dest_unit = args.get("destination_storage_unit_id")
    f_new_lot = args.get("new_lot_id")
    f_status = args.get("status")
    if f_site is not None:
        items = [t for t in items if t["provider_site_id"] == f_site]
    if f_from is not None:
        items = [t for t in items if t["from_lot_id"] == f_from]
    if f_dest_site is not None:
        items = [t for t in items if t["destination_site_id"] == f_dest_site]
    if f_dest_unit is not None:
        items = [t for t in items if t["destination_storage_unit_id"] == f_dest_unit]
    if f_new_lot is not None:
        items = [t for t in items if t["new_lot_id"] == f_new_lot]
    if f_status is not None:
        items = [t for t in items if t["status"] == f_status]
    return items


@bp.route("/provider-sites/<site_id>/short-date-transfers", methods=["GET"])
def list_transfers(site_id):
    get_auth(ALL_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    items = [t for t in db.short_date_transfers.values() if t["provider_site_id"] == site["id"]]
    items = _filter_transfers(items, request.args)
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    return paginate([serialize_transfer(t) for t in items], request.args)


@bp.route("/short-date-transfers", methods=["GET"])
def list_transfers_global():
    get_auth(ALL_ROLES)
    items = list(db.short_date_transfers.values())
    items = _filter_transfers(items, request.args)
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    return paginate([serialize_transfer(t) for t in items], request.args)


@bp.route("/short-date-transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    get_auth(ALL_ROLES)
    transfer = get_or_404(db.short_date_transfers, transfer_id, "short-date transfer")
    return success_object(serialize_transfer(transfer))


def _get_site_transfer(site_id, transfer_id):
    site = get_or_404(db.provider_sites, site_id, "provider site")
    transfer = get_or_404(db.short_date_transfers, transfer_id, "short-date transfer")
    if transfer["provider_site_id"] != site["id"]:
        from errors import not_found
        raise not_found("short-date transfer")
    return site, transfer


@bp.route("/provider-sites/<site_id>/short-date-transfers/<transfer_id>/ship", methods=["POST"])
def ship_transfer(site_id, transfer_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site, transfer = _get_site_transfer(site_id, transfer_id)
    if transfer["status"] != "INITIATED":
        raise invalid_state("Transfer must be INITIATED to ship")
    from_lot = db.lots[transfer["from_lot_id"]]
    if from_lot["status"] != "AVAILABLE":
        raise ApiError(ERR_LOT_NOT_AVAILABLE, "Lot is not AVAILABLE", 409)
    if from_lot["quantity_on_hand"] < transfer["quantity_doses"]:
        raise ApiError(ERR_INSUFFICIENT_STOCK, "Lot quantity_on_hand < requested doses", 422)

    from_lot["quantity_on_hand"] -= transfer["quantity_doses"]
    from_lot["updated_at"] = db.now_ts()
    from_lot["version"] += 1
    if from_lot["quantity_on_hand"] == 0:
        from_lot["status"] = "DEPLETED"

    transfer["status"] = "IN_TRANSIT"
    transfer["updated_at"] = db.now_ts()
    transfer["version"] += 1

    if from_lot["stock_type"] == "PUBLIC_VFC":
        recompute_accountability_balance(site["id"])

    return success_object(serialize_transfer(transfer))


@bp.route("/provider-sites/<site_id>/short-date-transfers/<transfer_id>/receive", methods=["POST"])
def receive_transfer(site_id, transfer_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site, transfer = _get_site_transfer(site_id, transfer_id)
    if transfer["status"] != "IN_TRANSIT":
        raise invalid_state("Transfer must be IN_TRANSIT to receive")

    dest_unit = db.storage_units.get(transfer["destination_storage_unit_id"])
    if dest_unit is None:
        from errors import not_found
        raise not_found("storage unit")

    # destination unit must belong to destination site (p12) and not be quarantined (p6)
    if dest_unit["provider_site_id"] != transfer["destination_site_id"]:
        raise ApiError(ERR_UNIT_SITE_MISMATCH,
                       "Storage unit does not belong to the destination provider site", 422)
    if dest_unit["active_excursion_id"] is not None:
        raise ApiError(ERR_STORAGE_UNIT_QUARANTINED, "Storage unit has an active excursion", 409)

    from_lot = db.lots[transfer["from_lot_id"]]

    # Merge into an existing destination lot when one matches lot_number + stock_type
    # + vaccine_product_id and is AVAILABLE; otherwise create a successor lot.
    existing = None
    for lot in db.lots.values():
        if (
            lot["provider_site_id"] == transfer["destination_site_id"]
            and lot["lot_number"] == from_lot["lot_number"]
            and lot["stock_type"] == from_lot["stock_type"]
            and lot["vaccine_product_id"] == from_lot["vaccine_product_id"]
            and lot["status"] == "AVAILABLE"
        ):
            existing = lot
            break

    now = db.now_ts()
    if existing is not None:
        existing["quantity_on_hand"] += transfer["quantity_doses"]
        existing["updated_at"] = now
        existing["version"] += 1
        transfer["new_lot_id"] = existing["id"]
    else:
        new_lot = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "provider_site_id": transfer["destination_site_id"],
            "storage_unit_id": transfer["destination_storage_unit_id"],
            "vaccine_product_id": from_lot["vaccine_product_id"],
            "lot_number": from_lot["lot_number"],
            "stock_type": from_lot["stock_type"],
            "quantity_on_hand": transfer["quantity_doses"],
            "quantity_borrowed_in": 0,
            "expires_on": from_lot["expires_on"],
            "_expires_on_date": from_lot["_expires_on_date"],
            "status": "AVAILABLE",
            "received_via_order_id": None,
            "expired_written_off_doses": 0,
        }
        db.lots[new_lot["id"]] = new_lot
        transfer["new_lot_id"] = new_lot["id"]

    transfer["status"] = "RECEIVED"
    transfer["updated_at"] = db.now_ts()
    transfer["version"] += 1

    return success_object(serialize_transfer(transfer))


@bp.route("/provider-sites/<site_id>/short-date-transfers/<transfer_id>/cancel", methods=["POST"])
def cancel_transfer(site_id, transfer_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site, transfer = _get_site_transfer(site_id, transfer_id)
    if transfer["status"] != "INITIATED":
        raise invalid_state("Transfer must be INITIATED to cancel")
    transfer["status"] = "CANCELLED"
    transfer["updated_at"] = db.now_ts()
    transfer["version"] += 1

    # PRD §2.7: a cancelled transfer no longer counts as initiated-but-unshipped
    # in the provisional ledger — recompute for public stock.
    from_lot = db.lots.get(transfer["from_lot_id"])
    if from_lot is not None and from_lot["stock_type"] == "PUBLIC_VFC":
        recompute_accountability_balance(site["id"])

    return success_object(serialize_transfer(transfer))
