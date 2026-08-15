"""PriceList, SalesContract (OCC-guarded amend), and SalesOrder endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    SPECIES,
    STAMP_GRADES,
    contract_reserved_mbf,
    eligible_pool,
    get_contract,
    get_order,
    maybe_auto_close_contract,
    package_dry_mbf,
    recompute_order_totals,
    ser_contract,
    ser_order,
    spot_unit_price,
    stamp,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_iso_dt,
    as_num,
    as_str,
    as_ymd,
    body,
    dec,
    pagination_args,
    parse_dt,
    parse_ymd,
    required,
    round_cents,
    round_mbf,
)

bp = Blueprint("sales", __name__)


# ---------------------------------------------------------------------------
# PriceList (immutable spot rows)
# ---------------------------------------------------------------------------

@bp.post("/api/price-lists")
def create_price_list():
    auth(["MillManager"])
    data = body()
    species = as_enum(required(data, "species"), "species", SPECIES)
    grade = as_enum(required(data, "grade"), "grade", STAMP_GRADES)
    base = as_int(
        required(data, "base_price_per_mbf_cents"),
        "base_price_per_mbf_cents",
        positive=True,
    )
    effective_from = as_iso_dt(required(data, "effective_from"), "effective_from")
    row = {
        "id": new_id(),
        "species": species,
        "grade": grade,
        "base_price_per_mbf_cents": base,
        "effective_from": effective_from,
        "_effective_from_dt": parse_dt(effective_from),
    }
    stamp(row)
    DB["price_lists"][row["id"]] = row
    return ok(ser_price_list(row), 201)


def ser_price_list(row):
    return {
        "id": row["id"],
        "species": row["species"],
        "grade": row["grade"],
        "base_price_per_mbf_cents": row["base_price_per_mbf_cents"],
        "effective_from": row["effective_from"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------------------
# SalesContract
# ---------------------------------------------------------------------------

@bp.post("/api/sales-contracts")
def create_contract():
    auth(["MillManager"])
    data = body()
    customer_name = as_str(required(data, "customer_name"), "customer_name")
    species = as_enum(required(data, "species"), "species", SPECIES)
    grade = as_enum(required(data, "grade"), "grade", STAMP_GRADES)
    committed_mbf = as_num(
        required(data, "committed_mbf"), "committed_mbf", positive=True
    )
    price = as_int(
        required(data, "contract_price_per_mbf_cents"),
        "contract_price_per_mbf_cents",
        positive=True,
    )
    start_date = as_ymd(required(data, "start_date"), "start_date")
    end_date = as_ymd(required(data, "end_date"), "end_date")
    if parse_ymd(end_date) <= parse_ymd(start_date):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "end_date must be after start_date"
        )
    contract = {
        "id": new_id(),
        "customer_name": customer_name,
        "species": species,
        "grade": grade,
        "committed_mbf": committed_mbf,
        "contract_price_per_mbf_cents": price,
        "start_date": start_date,
        "end_date": end_date,
        "status": "DRAFT",
    }
    stamp(contract)
    DB["sales_contracts"][contract["id"]] = contract
    return ok(ser_contract(contract), 201)


@bp.get("/api/sales-contracts/<cid>")
def get_one_contract(cid):
    auth(ALL_ROLES)
    return ok(ser_contract(get_contract(cid)))


@bp.post("/api/sales-contracts/<cid>/activate")
def activate_contract(cid):
    auth(["MillManager"])
    contract = get_contract(cid)
    body()
    if contract["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a DRAFT contract can be activated"
        )
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(ser_contract(contract))


@bp.put("/api/sales-contracts/<cid>")
def amend_contract(cid):
    auth(["MillManager"])
    contract = get_contract(cid)
    data = body()
    expected = as_int(
        required(data, "expected_contract_version"), "expected_contract_version"
    )
    new_committed = None
    new_price = None
    new_end = None
    if "committed_mbf" in data and data["committed_mbf"] is not None:
        new_committed = as_num(data["committed_mbf"], "committed_mbf", positive=True)
    if (
        "contract_price_per_mbf_cents" in data
        and data["contract_price_per_mbf_cents"] is not None
    ):
        new_price = as_int(
            data["contract_price_per_mbf_cents"],
            "contract_price_per_mbf_cents",
            positive=True,
        )
    if "end_date" in data and data["end_date"] is not None:
        new_end = as_ymd(data["end_date"], "end_date")
        if parse_ymd(new_end) <= parse_ymd(contract["start_date"]):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "end_date must be after start_date"
            )

    # State: amendment is a legitimate, repeatable edit only on DRAFT or ACTIVE.
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a DRAFT or ACTIVE contract can be amended",
        )

    # OCC: the contract's one optimistic-concurrency guard.
    if expected != contract["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_contract_version does not match the contract's current version",
        )

    # Fiscal guard: committed_mbf cannot drop below volume already reserved.
    if new_committed is not None:
        reserved = dec(contract_reserved_mbf(contract))
        if dec(new_committed) < reserved:
            raise ApiError(
                "ERR_CONTRACT_VOLUME_EXCEEDED",
                422,
                "committed_mbf cannot fall below reserved_mbf",
            )

    if new_committed is not None:
        contract["committed_mbf"] = new_committed
    if new_price is not None:
        contract["contract_price_per_mbf_cents"] = new_price
    if new_end is not None:
        contract["end_date"] = new_end
    touch(contract)
    return ok(ser_contract(contract))


# ---------------------------------------------------------------------------
# SalesOrder
# ---------------------------------------------------------------------------

def _parse_length_spec(value):
    """RL (random length) or an exact package length 8 | 10 | 12 | 16."""
    if isinstance(value, str):
        if value == "RL":
            return "RL"
        if value in ("8", "10", "12", "16"):
            return int(value)
    elif isinstance(value, int) and not isinstance(value, bool):
        if value in (8, 10, 12, 16):
            return value
    raise ApiError(
        "ERR_INVALID_REQUEST",
        400,
        "length_spec must be RL or one of 8, 10, 12, 16",
    )


@bp.post("/api/sales-orders")
def create_order():
    auth(["SalesRep"])
    data = body()
    customer_name = as_str(required(data, "customer_name"), "customer_name")
    species = as_enum(required(data, "species"), "species", SPECIES)
    grade = as_enum(required(data, "grade"), "grade", STAMP_GRADES)
    length_spec = _parse_length_spec(required(data, "length_spec"))
    volume_mbf = as_num(required(data, "volume_mbf"), "volume_mbf", positive=True)
    contract_id = data.get("contract_id")
    if contract_id is not None and not isinstance(contract_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "contract_id must be a string")

    contract = None
    if contract_id is not None:
        # Contract rail: the referenced contract must exist and be ACTIVE.
        contract = DB["sales_contracts"].get(contract_id)
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CONTRACT_NOT_ACTIVE",
                409,
                "Referenced contract is not ACTIVE",
            )
        # Referential linkage: species and grade must equal the contract's.
        if contract["species"] != species or contract["grade"] != grade:
            raise ApiError(
                "ERR_PRODUCT_MISMATCH",
                422,
                "Order species/grade must match the referenced contract",
            )
        # Fiscal: order volume must fit the contract's remaining volume.
        remaining = dec(contract["committed_mbf"]) - dec(
            contract_reserved_mbf(contract)
        )
        if dec(volume_mbf) > remaining:
            raise ApiError(
                "ERR_CONTRACT_VOLUME_EXCEEDED",
                422,
                "Order volume exceeds the contract's remaining_mbf",
            )
        pricing_mode = "CONTRACT"
        unit_price_cents = contract["contract_price_per_mbf_cents"]
    else:
        # Spot rail: quote from the effective price list.
        pricing_mode = "SPOT"
        unit_price_cents = spot_unit_price(species, grade, length_spec, volume_mbf)

    order = {
        "id": new_id(),
        "customer_name": customer_name,
        "contract_id": contract_id,
        "species": species,
        "grade": grade,
        "length_spec": length_spec,
        "volume_mbf": volume_mbf,
        "pricing_mode": pricing_mode,
        "unit_price_cents": unit_price_cents,
        "allocated_mbf": 0,
        "total_cents": 0,
        "status": "PLACED",
    }
    stamp(order)
    DB["sales_orders"][order["id"]] = order
    return ok(ser_order(order), 201)


@bp.get("/api/sales-orders")
def list_orders():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    items = list(DB["sales_orders"].values())
    if "contract_id" in request.args:
        v = request.args.get("contract_id")
        items = [o for o in items if o["contract_id"] == v]
    if "status" in request.args:
        v = request.args.get("status")
        items = [o for o in items if o["status"] == v]
    items.sort(key=lambda o: o["_seq"])  # created_at ascending, insertion order
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_order(o) for o in page], total, limit, offset)


@bp.get("/api/sales-orders/<oid>")
def get_one_order(oid):
    auth(ALL_ROLES)
    return ok(ser_order(get_order(oid)))


@bp.post("/api/sales-orders/<oid>/allocate")
def allocate_order(oid):
    auth(["SalesRep"])
    order = get_order(oid)
    body()
    if order["status"] != "PLACED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a PLACED order can be allocated"
        )
    if order["contract_id"] is not None:
        contract = DB["sales_contracts"].get(order["contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError(
                "ERR_CONTRACT_NOT_ACTIVE",
                409,
                "Referenced contract is not ACTIVE",
            )

    pool = eligible_pool(order)
    pool_total = sum(dec(package_dry_mbf(p)) for p in pool) if pool else dec(0)
    if pool_total < dec(order["volume_mbf"]):
        raise ApiError(
            "ERR_INSUFFICIENT_STAMPED_VOLUME",
            422,
            "Eligible STAMPED pool sums below the order volume",
        )

    # FIFO walk: stamped_at ascending, tie-break created_at ascending; whole
    # packages until cumulative dry_mbf reaches volume_mbf; the crossing
    # package is included whole (over-allocation of at most one package).
    pool.sort(key=lambda p: (p["stamped_at"], p["created_at"], p["_seq"]))
    selected = []
    cumulative = dec(0)
    target = dec(order["volume_mbf"])
    for p in pool:
        selected.append(p)
        cumulative += dec(package_dry_mbf(p))
        if cumulative >= target:
            break

    for p in selected:
        p["sales_order_id"] = order["id"]
        p["status"] = "ALLOCATED"
        touch(p)

    order["allocated_mbf"] = round_mbf(cumulative)
    total = 0
    for p in selected:
        total += round_cents(
            dec(package_dry_mbf(p)) * dec(order["unit_price_cents"])
        )
    order["total_cents"] = total
    order["status"] = "ALLOCATED"
    touch(order)
    return ok(ser_order(order))


@bp.post("/api/sales-orders/<oid>/ship")
def ship_order(oid):
    auth(["SalesRep"])
    order = get_order(oid)
    body()
    if order["status"] != "ALLOCATED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an ALLOCATED order can be shipped"
        )
    for p in DB["lumber_packages"].values():
        if p["sales_order_id"] == order["id"] and p["status"] == "ALLOCATED":
            p["status"] = "SHIPPED"
            touch(p)
    order["status"] = "SHIPPED"
    touch(order)
    if order["contract_id"] is not None:
        contract = DB["sales_contracts"].get(order["contract_id"])
        if contract is not None:
            maybe_auto_close_contract(contract)
    return ok(ser_order(order))


@bp.post("/api/sales-orders/<oid>/cancel")
def cancel_order(oid):
    auth(["SalesRep"])
    order = get_order(oid)
    body()
    if order["status"] not in ("PLACED", "ALLOCATED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a PLACED or ALLOCATED order can be cancelled",
        )
    if order["status"] == "ALLOCATED":
        # Compensating release: held wood flips back to STAMPED.
        for p in DB["lumber_packages"].values():
            if p["sales_order_id"] == order["id"] and p["status"] == "ALLOCATED":
                p["sales_order_id"] = None
                p["status"] = "STAMPED"
                touch(p)
        order["allocated_mbf"] = 0
        order["total_cents"] = 0
    order["status"] = "CANCELLED"
    touch(order)
    return ok(ser_order(order))
