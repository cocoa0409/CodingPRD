"""Clock, yards, load-out bays and consignors."""
from datetime import timedelta

from routes.common import (
    ANY_ROLE, ApiError, Blueprint, C, collection_response, db, endpoint,
    field_bool, field_country, field_currency, field_dt, field_enum, field_int,
    field_str, fetch, invalid_state, json_body, new_entity, object_response,
    pagination, query_bool, query_enum, require_owner, touch,
)
from response import fmt_dt
from services.derive import recompute_consignor

bp = Blueprint("reference", __name__)


# --------------------------------------------------------------------------
# logical clock (PRD 2.4)
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint("PlatformAdmin")
def set_clock(actor):
    body = json_body()
    value = field_dt(body, "current_utc", required=True)
    db.current_utc = value
    # PRD 2.5: the capability "accepts a single `current_utc` instant and echoes
    # back `{ current_utc }`" — the accepted instant is echoed as supplied.
    supplied = body.get("current_utc")
    return object_response(
        {"current_utc": supplied if isinstance(supplied, str) else fmt_dt(value)})


# --------------------------------------------------------------------------
# yards
# --------------------------------------------------------------------------
@bp.post("/yards")
@endpoint("PlatformAdmin")
def create_yard(actor):
    body = json_body()
    code = field_str(body, "code", required=True, min_len=3, max_len=32)
    country_code = field_country(body, "country_code", required=True)
    teardown = field_int(body, "teardown_buffer_minutes", min_value=0,
                         max_value=2880, default=120)
    deadline_days = field_int(body, "loadout_deadline_days", min_value=1,
                              max_value=60, default=10)
    currency = field_currency(body, "currency_code", default="USD")

    yard = new_entity()
    yard.update({
        "code": code,
        "country_code": country_code,
        "teardown_buffer_minutes": teardown,
        "loadout_deadline_days": deadline_days,
        "currency_code": currency,
    })
    db.yards[yard["id"]] = yard
    return object_response(yard, 201)


@bp.get("/yards/<yard_id>")
@endpoint(*ANY_ROLE)
def get_yard(actor, yard_id):
    return object_response(fetch(db.yards, yard_id, "ERR_YARD_NOT_FOUND"))


@bp.get("/yards")
@endpoint(*ANY_ROLE)
def list_yards(actor):
    limit, offset = pagination()
    return collection_response(list(db.yards.values()), limit, offset)


@bp.get("/yards/<yard_id>/auctions")
@endpoint(*ANY_ROLE)
def list_yard_auctions(actor, yard_id):
    limit, offset = pagination()
    status = query_enum("status", C.AUCTION_STATUSES)
    yard = fetch(db.yards, yard_id, "ERR_YARD_NOT_FOUND")
    rows = [a for a in db.auctions.values() if a["yard_id"] == yard["id"]]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return collection_response(rows, limit, offset)


@bp.get("/yards/<yard_id>/loadout-bays")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def list_yard_bays(actor, yard_id):
    limit, offset = pagination()
    is_active = query_bool("is_active")
    yard = fetch(db.yards, yard_id, "ERR_YARD_NOT_FOUND")
    rows = [b for b in db.loadout_bays.values() if b["yard_id"] == yard["id"]]
    if is_active is not None:
        rows = [b for b in rows if b["is_active"] == is_active]
    return collection_response(rows, limit, offset)


# --------------------------------------------------------------------------
# load-out bays
# --------------------------------------------------------------------------
@bp.post("/loadout-bays")
@endpoint("PlatformAdmin")
def create_bay(actor):
    body = json_body()
    yard_id = field_str(body, "yard_id", required=True)
    bay_number = field_int(body, "bay_number", required=True, min_value=1,
                           max_value=99)
    capacity = field_int(body, "crane_capacity_kg", required=True,
                         min_value=1000, max_value=500000)
    is_active = field_bool(body, "is_active", default=True)

    yard = fetch(db.yards, yard_id, "ERR_YARD_NOT_FOUND")

    bay = new_entity()
    bay.update({
        "yard_id": yard["id"],
        "bay_number": bay_number,
        "crane_capacity_kg": capacity,
        "is_active": is_active,
        "reserved_tonnage_kg": 0,
    })
    db.loadout_bays[bay["id"]] = bay
    return object_response(bay, 201)


@bp.get("/loadout-bays/<bay_id>")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def get_bay(actor, bay_id):
    return object_response(
        fetch(db.loadout_bays, bay_id, "ERR_LOADOUT_BAY_NOT_FOUND"))


@bp.patch("/loadout-bays/<bay_id>")
@endpoint("PlatformAdmin")
def patch_bay(actor, bay_id):
    body = json_body()
    is_active = field_bool(body, "is_active", required=True)
    bay = fetch(db.loadout_bays, bay_id, "ERR_LOADOUT_BAY_NOT_FOUND")
    bay["is_active"] = is_active
    touch(bay)
    return object_response(bay)


# --------------------------------------------------------------------------
# consignors
# --------------------------------------------------------------------------
@bp.post("/consignors")
@endpoint("PlatformAdmin")
def create_consignor(actor):
    body = json_body()
    legal_name = field_str(body, "legal_name", required=True, min_len=2,
                           max_len=120)
    country_code = field_country(body, "country_code", required=True)
    seller_type = field_enum(body, "seller_type", C.SELLER_TYPES, required=True)
    ack = field_bool(body, "unreserved_policy_ack", default=False)

    consignor = new_entity()
    consignor.update({
        "legal_name": legal_name,
        "country_code": country_code,
        "seller_type": seller_type,
        "unreserved_policy_ack": ack,
        "open_consignment_count": 0,
        "lifetime_net_proceeds_cents": 0,
    })
    db.consignors[consignor["id"]] = consignor
    return object_response(consignor, 201)


@bp.get("/consignors/<consignor_id>")
@endpoint("PlatformAdmin", "Consignor", "AuctionOperator", "SettlementOfficer")
def get_consignor(actor, consignor_id):
    return object_response(
        fetch(db.consignors, consignor_id, "ERR_CONSIGNOR_NOT_FOUND"))


@bp.get("/consignors")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer")
def list_consignors(actor):
    limit, offset = pagination()
    seller_type = query_enum("seller_type", C.SELLER_TYPES)
    rows = list(db.consignors.values())
    if seller_type is not None:
        rows = [c for c in rows if c["seller_type"] == seller_type]
    return collection_response(rows, limit, offset)


@bp.post("/consignors/<consignor_id>/policy-ack")
@endpoint("Consignor")
def policy_ack(actor, consignor_id):
    body = json_body()
    ack = field_bool(body, "unreserved_policy_ack", required=True)
    consignor = fetch(db.consignors, consignor_id, "ERR_CONSIGNOR_NOT_FOUND")
    require_owner(actor, consignor["id"])
    consignor["unreserved_policy_ack"] = ack
    touch(consignor)
    return object_response(consignor)


@bp.get("/consignors/<consignor_id>/consignments")
@endpoint("PlatformAdmin", "Consignor", "AuctionOperator", "SettlementOfficer")
def list_consignor_consignments(actor, consignor_id):
    limit, offset = pagination()
    status = query_enum("status", C.CONSIGNMENT_STATUSES)
    consignor = fetch(db.consignors, consignor_id, "ERR_CONSIGNOR_NOT_FOUND")
    rows = [c for c in db.consignments.values()
            if c["consignor_id"] == consignor["id"]]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return collection_response(rows, limit, offset)
