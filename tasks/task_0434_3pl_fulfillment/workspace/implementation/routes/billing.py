"""Storage accrual + BillingCharge read endpoints (PRD §3.11)."""
from flask import Blueprint, request

from db import store, new_id, stamp_create_charge, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import (
    get_client, get_charge,
    get_json_body, parse_pagination, paginate,
)
from serializers import serialize_charge

bp = Blueprint("billing", __name__)

READ_ROLES = {"BillingClerk", "ClientUser"}


def _occupied_pallet_bins_for_client(client_id):
    """Count PALLET bins with occupied_cc > 0 holding >= 1 lot of this client.

    A qualifying pallet bin counts once for the client regardless of lot count.
    """
    qualifying = set()
    for lot in store.inventory_lots.values():
        if lot["client_id"] != client_id or lot["on_hand_qty"] <= 0:
            continue
        bin_rec = store.bins.get(lot["bin_id"])
        if bin_rec is None or bin_rec["bin_type"] != "PALLET":
            continue
        qualifying.add(bin_rec["id"])
    return len(qualifying)


@bp.route("/clients/<client_id>/storage/accrue", methods=["POST"])
def accrue_storage(client_id):
    _, role = get_auth()
    require_roles(role, {"BillingClerk"})
    client = get_client(client_id)
    body = get_json_body()

    days = body.get("days")
    if isinstance(days, bool) or not isinstance(days, int):
        raise err("ERR_INVALID_REQUEST", "days must be an integer")
    if days < 1:
        raise err("ERR_INVALID_REQUEST", "days must be >= 1")

    occupied_pallets = _occupied_pallet_bins_for_client(client_id)
    amount = occupied_pallets * client["storage_rate_per_pallet_cents"] * days

    charge = stamp_create_charge({
        "id": new_id(),
        "client_id": client_id,
        "charge_type": "STORAGE",
        "amount_cents": amount,
        "source_order_id": None,
        "posted": True,
    })
    store.billing_charges[charge["id"]] = charge
    client["storage_balance_cents"] += amount
    touch(client)
    return success(serialize_charge(charge), status=201)


def _filter_charges(items):
    for key in ("client_id", "source_order_id", "charge_type"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return items


@bp.route("/billing-charges", methods=["GET"])
def list_charges_flat():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = _filter_charges(list(store.billing_charges.values()))
    page, meta = paginate(items, limit, offset)
    return success([serialize_charge(r) for r in page], pagination=meta)


@bp.route("/billing-charges/<charge_id>", methods=["GET"])
def get_one_charge_flat(charge_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_charge(charge_id)
    return success(serialize_charge(rec))


@bp.route("/clients/<client_id>/billing-charges", methods=["GET"])
def list_client_charges(client_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    get_client(client_id)
    limit, offset = parse_pagination()
    items = [c for c in store.billing_charges.values() if c["client_id"] == client_id]
    val = request.args.get("source_order_id")
    if val is not None:
        items = [c for c in items if c.get("source_order_id") == val]
    val = request.args.get("charge_type")
    if val is not None:
        items = [c for c in items if c.get("charge_type") == val]
    page, meta = paginate(items, limit, offset)
    return success([serialize_charge(r) for r in page], pagination=meta)


@bp.route("/clients/<client_id>/billing-charges/<charge_id>", methods=["GET"])
def get_client_charge(client_id, charge_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    get_client(client_id)
    rec = get_charge(charge_id)
    if rec["client_id"] != client_id:
        raise err("ERR_CHARGE_NOT_FOUND", "Billing charge not found for client")
    return success(serialize_charge(rec))
