"""Transportation providers, markets and weekly capacity (PRD §3.4)."""

from datetime import timedelta

from flask import Blueprint

from db import base_record, by_seq, db, mark_fresh, touch
from errors import ApiError
from middleware import (
    ROLE_CLAIMS_EXAMINER,
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_TSP_COORDINATOR,
    endpoint,
)
from paging import list_response
from response import created, ok
from serializers import serialize
from services import calculations as calc
from services import ledger
from validation import (
    MARKET_CODE_RE,
    SCAC_RE,
    bad,
    get_body,
    opt_float,
    req_dt,
    req_int,
    req_list,
    req_pattern,
    req_str,
)

bp = Blueprint("tsps", __name__)


@bp.post("/tsps")
@endpoint([ROLE_PROGRAM_ADMIN])
def onboard_tsp():
    body = get_body()
    name = req_str(body, "name")
    scac_code = req_str(body, "scac_code")
    if not SCAC_RE.match(scac_code):
        raise bad("Field 'scac_code' must be exactly four uppercase letters.")
    markets = req_list(body, "markets")
    if not markets:
        raise bad("Field 'markets' must be non-empty.")
    for market in markets:
        if not isinstance(market, str) or not MARKET_CODE_RE.match(market):
            raise bad("Every market code must match ^MKT-[A-Z]{3}$.")
    for existing in db.tsps.values():
        if existing["scac_code"] == scac_code:
            raise bad("Field 'scac_code' must be unique across providers.")

    record = base_record()
    record.update(
        {
            "name": name,
            "scac_code": scac_code,
            "markets": list(markets),
            "settled_claim_count": 0,
            "claim_settlement_total_usd": calc.ZERO,
            "performance_score": calc.money("100.00"),
            "status": "ACTIVE",
        }
    )
    mark_fresh(record)
    db.tsps[record["id"]] = record
    return created(serialize(record))


@bp.get("/tsps/<tsp_id>")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_CLAIMS_EXAMINER, ROLE_PROGRAM_ADMIN])
def read_tsp(tsp_id):
    return ok(serialize(ledger.get_tsp(tsp_id)))


@bp.get("/tsps/<tsp_id>/capacity-blocks")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_tsp_blocks(tsp_id):
    tsp = ledger.get_tsp(tsp_id)
    records = by_seq([b for b in db.capacity_blocks.values() if b["tsp_id"] == tsp["id"]])
    return list_response(records)


@bp.get("/tsps/<tsp_id>/shipments")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_tsp_shipments(tsp_id):
    tsp = ledger.get_tsp(tsp_id)
    records = by_seq([s for s in db.shipments.values() if s["tsp_id"] == tsp["id"]])
    return list_response(records)


# --------------------------------------------------------------- capacity blocks


@bp.post("/capacity-blocks")
@endpoint([ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def publish_capacity_block():
    body = get_body()
    tsp_id = req_str(body, "tsp_id")
    market_code = req_pattern(body, "market_code", MARKET_CODE_RE, "match ^MKT-[A-Z]{3}$")
    week_start = req_dt(body, "week_start_date")
    if week_start.weekday() != 0 or (
        week_start.hour,
        week_start.minute,
        week_start.second,
        week_start.microsecond,
    ) != (0, 0, 0, 0):
        raise bad("Field 'week_start_date' must be a Monday at midnight UTC.")
    total_capacity = req_int(body, "total_capacity_lbs", minimum=1)
    reserve_pct = opt_float(body, "short_notice_reserve_pct", default=0.15, minimum=0, maximum=0.5)

    tsp = ledger.get_tsp(tsp_id)

    if market_code not in tsp["markets"]:
        raise ApiError("ERR_MARKET_NOT_SERVED", "This provider does not serve that market.")

    week_end = week_start + timedelta(days=7)
    for existing in db.capacity_blocks.values():
        if existing["tsp_id"] != tsp["id"] or existing["market_code"] != market_code:
            continue
        if week_start < existing["week_end_date"] and existing["week_start_date"] < week_end:
            raise ApiError(
                "ERR_CAPACITY_BLOCK_OVERLAP", "Another block already covers part of that week."
            )

    peak_season = calc.in_peak_window(week_start)
    effective_pct, general_pool, short_notice_pool = calc.capacity_pools(
        total_capacity, reserve_pct, peak_season
    )

    record = base_record()
    record.update(
        {
            "tsp_id": tsp["id"],
            "market_code": market_code,
            "week_start_date": week_start,
            "week_end_date": week_end,
            "total_capacity_lbs": total_capacity,
            "short_notice_reserve_pct": reserve_pct,
            "effective_reserve_pct": effective_pct,
            "general_pool_lbs": general_pool,
            "short_notice_pool_lbs": short_notice_pool,
            "committed_general_lbs": 0,
            "committed_short_notice_lbs": 0,
            "committed_lbs": 0,
            "peak_season": peak_season,
            "status": "OPEN",
        }
    )
    record["status"] = ledger.derive_block_status(record)
    mark_fresh(record)
    db.capacity_blocks[record["id"]] = record
    return created(serialize(record))


@bp.get("/capacity-blocks/<block_id>")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def read_capacity_block(block_id):
    return ok(serialize(ledger.get_block(block_id)))


@bp.post("/capacity-blocks/<block_id>/awards")
@endpoint([ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def award_capacity(block_id):
    body = get_body()
    shipment_id = req_str(body, "shipment_id")
    expected_version = req_int(body, "expected_capacity_block_version")

    block = ledger.get_block(block_id)
    shipment = ledger.get_shipment(shipment_id)

    if shipment["movement_status"] not in ("AWARDED", "SURVEYED"):
        raise ApiError(
            "ERR_INVALID_SHIPMENT_MOVEMENT_STATE",
            "Capacity may only be awarded before the goods are packed.",
        )

    entitlement = db.entitlements.get(shipment["entitlement_id"])
    if entitlement is not None and entitlement["status"] == "SUSPENDED":
        raise ApiError("ERR_ENTITLEMENT_SUSPENDED", "The owning entitlement is suspended.")

    if expected_version != block["version"]:
        raise ApiError(
            "ERR_STALE_CAPACITY_BLOCK_VERSION", "The capacity block has been modified since it was read."
        )

    tsp = db.tsps[block["tsp_id"]]
    if tsp["status"] == "SUSPENDED":
        raise ApiError("ERR_TSP_NOT_ACTIVE", "This provider takes no new work.")

    if (
        shipment["origin_market_code"] not in tsp["markets"]
        or shipment["origin_market_code"] != block["market_code"]
    ):
        raise ApiError("ERR_MARKET_NOT_SERVED", "The shipment's origin market is not served here.")

    if shipment["tsp_id"] != block["tsp_id"]:
        raise ApiError("ERR_SHIPMENT_TSP_MISMATCH", "The shipment belongs to another provider.")

    if block["status"] == "CLOSED" or (
        block["status"] == "RESTRICTED" and not shipment["is_short_notice"]
    ):
        raise ApiError("ERR_CAPACITY_BLOCK_NOT_OPEN", "This block is not accepting that award.")

    if shipment["billable_basis"] == "NONE":
        raise ApiError("ERR_WEIGHT_BASIS_MISSING", "The shipment has no weight of record yet.")

    pounds = shipment["billable_weight_lbs"]
    remaining_total = block["total_capacity_lbs"] - block["committed_lbs"]
    if shipment["is_short_notice"]:
        if pounds > remaining_total:
            raise ApiError("ERR_CAPACITY_EXCEEDED", "The block cannot absorb those pounds.")
    else:
        remaining_general = block["general_pool_lbs"] - block["committed_general_lbs"]
        if pounds > remaining_general:
            if pounds <= remaining_total:
                raise ApiError(
                    "ERR_SHORT_NOTICE_RESERVE_PROTECTED",
                    "Only the short-notice reserve could absorb those pounds.",
                )
            raise ApiError("ERR_CAPACITY_EXCEEDED", "The block cannot absorb those pounds.")

    shipment["capacity_block_id"] = block["id"]
    touch(shipment)
    ledger.recompute_capacity_block(block, force_touch=True)
    return ok(serialize(shipment))


@bp.post("/capacity-blocks/<block_id>/release-award")
@endpoint([ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def release_award(block_id):
    body = get_body()
    shipment_id = req_str(body, "shipment_id")
    req_str(body, "release_reason")

    block = ledger.get_block(block_id)
    shipment = ledger.get_shipment(shipment_id)

    if shipment["tsp_id"] != block["tsp_id"]:
        raise ApiError("ERR_SHIPMENT_TSP_MISMATCH", "The shipment belongs to another provider.")
    if shipment["capacity_block_id"] != block["id"]:
        raise ApiError("ERR_AWARD_NOT_FOUND", "The shipment holds no award on this block.")

    shipment["capacity_block_id"] = None
    touch(shipment)
    ledger.recompute_capacity_block(block, force_touch=True)
    return ok(serialize(shipment))


@bp.get("/capacity-blocks/<block_id>/shipments")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_block_shipments(block_id):
    block = ledger.get_block(block_id)
    records = by_seq(
        [s for s in db.shipments.values() if s["capacity_block_id"] == block["id"]]
    )
    return list_response(records)
