"""Byproduct sales/inventory, ops checkpoint, and the logical clock."""
from flask import Blueprint

from db import CLOCK, DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import (
    BYPRODUCTS,
    byproduct_on_hand,
    ledger_stamp,
    refresh_degrade,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_iso_dt,
    as_num,
    as_str,
    body,
    dec,
    parse_ymd,
    required,
    round_cents,
)

bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# Byproduct sales and the computed inventory read
# ---------------------------------------------------------------------------

@bp.post("/api/byproduct-sales")
def create_byproduct_sale():
    auth(["SalesRep"])
    data = body()
    product = as_enum(required(data, "product"), "product", BYPRODUCTS)
    volume_tons = as_num(required(data, "volume_tons"), "volume_tons", positive=True)
    price = as_int(
        required(data, "price_per_ton_cents"), "price_per_ton_cents", positive=True
    )
    buyer_name = as_str(required(data, "buyer_name"), "buyer_name")

    _, _, on_hand = byproduct_on_hand(product)
    if dec(volume_tons) > dec(on_hand):
        raise ApiError(
            "ERR_INSUFFICIENT_BYPRODUCT",
            422,
            "Sale volume exceeds on-hand tons for this product",
        )

    sale = {
        "id": new_id(),
        "product": product,
        "volume_tons": volume_tons,
        "price_per_ton_cents": price,
        "buyer_name": buyer_name,
        "total_cents": round_cents(dec(volume_tons) * dec(price)),
    }
    ledger_stamp(sale)
    DB["byproduct_sales"][sale["id"]] = sale
    return ok(ser_byproduct_sale(sale), 201)


def ser_byproduct_sale(sale):
    return {
        "id": sale["id"],
        "product": sale["product"],
        "volume_tons": sale["volume_tons"],
        "price_per_ton_cents": sale["price_per_ton_cents"],
        "buyer_name": sale["buyer_name"],
        "total_cents": sale["total_cents"],
        "created_at": sale["created_at"],
    }


@bp.get("/api/byproduct-inventory")
def get_byproduct_inventory():
    auth(ALL_ROLES)
    items = []
    for product in BYPRODUCTS:
        produced, sold, on_hand = byproduct_on_hand(product)
        items.append(
            {
                "product": product,
                "produced_tons": produced,
                "sold_tons": sold,
                "on_hand_tons": on_hand,
            }
        )
    return ok({"items": items})


# ---------------------------------------------------------------------------
# Ops checkpoint: contract expiry sweep + deck degrade refresh
# ---------------------------------------------------------------------------

@bp.post("/api/ops/runs")
def ops_run():
    auth(["MillManager"])
    body()
    from db import now_dt

    current_date = now_dt().date()
    expired_contract_ids = []
    for contract in DB["sales_contracts"].values():
        if contract["status"] != "ACTIVE":
            continue
        if current_date > parse_ymd(contract["end_date"]):
            contract["status"] = "EXPIRED"
            touch(contract)
            expired_contract_ids.append(contract["id"])
    degraded_load_ids = []
    for load in DB["log_loads"].values():
        if load["status"] == "DECKED":
            refresh_degrade(load)
            degraded_load_ids.append(load["id"])
    return ok(
        {
            "expired_contract_ids": expired_contract_ids,
            "degraded_load_ids": degraded_load_ids,
        }
    )


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_clock():
    auth(["MillManager"])
    data = body()
    to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    CLOCK.set(to_iso8601)
    return ok({"current_utc": CLOCK.raw})
