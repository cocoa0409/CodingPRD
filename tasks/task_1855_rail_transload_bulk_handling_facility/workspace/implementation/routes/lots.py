"""Inventory lot endpoints: create (stamps SIT config), get, list, close with
the final storage-in-transit charge."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public, now_iso
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_LOT_NOT_EMPTY, ERR_LOT_HAS_ACTIVE_CARS,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated
from util import dec
from validate import body, req_str, req_pos_int, opt_nonneg_int

bp = Blueprint("lots", __name__)


def _get_lot_or_404(lot_id):
    lot = STORE.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_NOT_FOUND, "lot id does not exist")
    return lot


@bp.route("/transload/lots", methods=["POST"])
def create_lot():
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    data = body()
    # Priority 3: body FK ids resolve.
    for field, table, label in (
        ("customer_id", STORE.customers, "customer"),
        ("product_id", STORE.products, "product"),
    ):
        raw = data.get(field)
        if isinstance(raw, str) and raw not in table:
            raise_err(ERR_NOT_FOUND, "%s id does not exist" % label)
    customer_id = req_str(data, "customer_id")
    product_id = req_str(data, "product_id")
    sit_daily_rate_cents = req_pos_int(data, "sit_daily_rate_cents")
    sit_free_days = opt_nonneg_int(
        data, "sit_free_days", domain.facility_config()["sit_free_days"]
    )
    cust = STORE.customers[customer_id]
    lot = new_entity(STORE.lots, {
        "customer_id": customer_id,
        "product_id": product_id,
        "status": "ACTIVE",
        "quantity_received_tons": 0.0,
        "quantity_shipped_tons": 0.0,
        "quantity_rejected_tons": 0.0,
        "sit_start_timestamp": now_iso(),
        "sit_free_days": sit_free_days,
        "sit_day_basis": cust["sit_day_basis"],
        "sit_daily_rate_cents": sit_daily_rate_cents,
        "close_timestamp": None,
    })
    return ok(domain.lot_view(lot), status=201)


@bp.route("/transload/lots/<lid>", methods=["GET"])
def get_lot(lid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    lot = _get_lot_or_404(lid)
    return ok(domain.lot_view(lot))


@bp.route("/transload/lots", methods=["GET"])
def list_lots():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    customer_id = request.args.get("customer_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = sorted(STORE.lots.values(), key=lambda l: (l["created_at"], l["_seq"]))
    if customer_id is not None:
        items = [l for l in items if l["customer_id"] == customer_id]
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, meta = paginated(items)
    return ok([domain.lot_view(l) for l in page], pagination=meta)


@bp.route("/transload/lots/<lid>/close", methods=["POST"])
def close_lot(lid):
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    lot = _get_lot_or_404(lid)
    if lot["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "lot is not ACTIVE")
    if dec(domain.lot_on_hand(lot)) != 0:
        raise_err(ERR_LOT_NOT_EMPTY, "lot quantity_on_hand_tons is not zero")
    for car in STORE.railcars.values():
        if car["lot_id"] == lid and car["placement_status"] not in ("RELEASED", "DEPARTED"):
            raise_err(ERR_LOT_HAS_ACTIVE_CARS, "lot has a linked railcar not yet released")
    lot["close_timestamp"] = now_iso()
    days, cents = domain.sit_accrual(lot)
    # The final SIT charge is created even when the amount is zero.
    domain.make_charge(lot["customer_id"], None, "STORAGE_IN_TRANSIT", days, cents)
    lot["status"] = "CLOSED"
    touch(lot)
    return ok(domain.lot_view(lot))
