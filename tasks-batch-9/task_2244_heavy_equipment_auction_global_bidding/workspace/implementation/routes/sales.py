"""Reserve outcomes, the consignor negotiation loop and seller settlements."""
from routes.common import (
    ApiError, Blueprint, C, collection_response, db, endpoint, field_enum,
    field_int, field_str, fetch, invalid_state, json_body, object_response,
    pagination, query_enum, query_str, require_owner, touch,
)
from services.derive import (
    create_invoice_for_sale, post_settlement, recompute_auction,
    recompute_bidder, recompute_consignment, refresh_registration_money,
)

bp = Blueprint("sales", __name__)


def _consignor_id_of_sale(sale):
    lot = db.lots[sale["lot_id"]]
    consignment = db.consignments[lot["consignment_id"]]
    return consignment["consignor_id"]


def _no_sale(sale):
    lot = db.lots[sale["lot_id"]]
    sale["status"] = "NO_SALE"
    if lot["lifecycle_status"] == "HAMMERED":
        lot["lifecycle_status"] = "UNSOLD"
        touch(lot)
    if sale["winning_bid_id"]:
        bid = db.bids.get(sale["winning_bid_id"])
        if bid and bid["status"] == "WINNING":
            bid["status"] = "LOSING"
    recompute_consignment(db.consignments[lot["consignment_id"]])
    auction = db.auctions.get(sale["auction_id"])
    if auction:
        recompute_auction(auction)


@bp.get("/sales/<sale_id>")
@endpoint("PlatformAdmin", "Consignor", "AuctionOperator", "SettlementOfficer",
          "Bidder")
def get_sale(actor, sale_id):
    return object_response(fetch(db.sales, sale_id, "ERR_SALE_NOT_FOUND"))


@bp.get("/sales")
@endpoint("PlatformAdmin", "Consignor", "AuctionOperator", "SettlementOfficer",
          "Bidder")
def list_sales(actor):
    limit, offset = pagination()
    auction_id = query_str("auction_id")
    lot_id = query_str("lot_id")
    winning_bid_id = query_str("winning_bid_id")
    registration_id = query_str("registration_id")
    status = query_enum("status", C.SALE_STATUSES)
    rows = list(db.sales.values())
    if auction_id is not None:
        rows = [s for s in rows if s["auction_id"] == auction_id]
    if lot_id is not None:
        rows = [s for s in rows if s["lot_id"] == lot_id]
    if winning_bid_id is not None:
        rows = [s for s in rows if s["winning_bid_id"] == winning_bid_id]
    if registration_id is not None:
        rows = [s for s in rows if s["registration_id"] == registration_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return collection_response(rows, limit, offset)


@bp.post("/sales/<sale_id>/counteroffer")
@endpoint("Consignor")
def counteroffer(actor, sale_id):
    body = json_body()
    expected_version = field_int(body, "expected_sale_version", required=True,
                                 min_value=0)
    counter_price = field_int(body, "counter_price_cents", required=True,
                              min_value=1, max_value=1000000000)

    sale = fetch(db.sales, sale_id, "ERR_SALE_NOT_FOUND")
    require_owner(actor, _consignor_id_of_sale(sale))

    if expected_version != sale["version"]:
        raise ApiError("ERR_STALE_SALE_VERSION")

    if sale["status"] != "PROVISIONAL" or sale["reserve_met"]:
        raise invalid_state(
            "Only a PROVISIONAL sale that missed its reserve may be countered.")

    if sale["counter_round"] >= C.MAX_COUNTER_ROUNDS:
        raise ApiError("ERR_MAX_COUNTER_ROUNDS_EXCEEDED")

    lot = db.lots[sale["lot_id"]]
    reserve = lot["reserve_price_cents"]
    if counter_price < (sale["hammer_price_cents"] or 0):
        raise ApiError("ERR_COUNTER_PRICE_NOT_MONOTONIC")
    if reserve is not None and counter_price > reserve:
        raise ApiError("ERR_COUNTER_PRICE_NOT_MONOTONIC")
    if sale["counter_round"] > 0 and sale["counter_price_cents"] is not None:
        if counter_price > sale["counter_price_cents"]:
            raise ApiError("ERR_COUNTER_PRICE_NOT_MONOTONIC")

    sale["status"] = "CONSIGNOR_COUNTERED"
    sale["counter_round"] += 1
    sale["counter_price_cents"] = counter_price
    touch(sale)
    auction = db.auctions.get(sale["auction_id"])
    if auction:
        recompute_auction(auction)
    return object_response(sale)


@bp.post("/sales/<sale_id>/counter-response")
@endpoint("Bidder")
def counter_response(actor, sale_id):
    body = json_body()
    decision = field_enum(body, "decision", ("ACCEPT", "DECLINE"), required=True)

    sale = fetch(db.sales, sale_id, "ERR_SALE_NOT_FOUND")
    registration = db.bidder_registrations[sale["registration_id"]]
    require_owner(actor, registration["bidder_id"])

    if sale["status"] != "CONSIGNOR_COUNTERED":
        raise invalid_state("This sale has no open counteroffer.")
    if registration["status"] != "APPROVED":
        raise ApiError("ERR_REGISTRATION_NOT_APPROVED")

    if decision == "ACCEPT":
        if (sale["counter_price_cents"] or 0) > (registration["bid_cap_cents"] or 0):
            raise ApiError("ERR_BID_CAP_EXCEEDED")
        sale["hammer_price_cents"] = sale["counter_price_cents"]
        sale["reserve_met"] = True
        sale["status"] = "CONFIRMED"
        touch(sale)
        create_invoice_for_sale(sale)
        auction = db.auctions.get(sale["auction_id"])
        if auction:
            recompute_auction(auction)
        refresh_registration_money(registration)
        return object_response(sale)

    if sale["counter_round"] >= C.MAX_COUNTER_ROUNDS:
        _no_sale(sale)
    else:
        sale["status"] = "PROVISIONAL"
        auction = db.auctions.get(sale["auction_id"])
        if auction:
            recompute_auction(auction)
    touch(sale)
    return object_response(sale)


@bp.post("/sales/<sale_id>/reject")
@endpoint("Consignor")
def reject_sale(actor, sale_id):
    body = json_body()
    reason = field_str(body, "reject_reason", default=None)
    if reason is None:
        reason = field_str(body, "reason", default=None)
    if not reason:
        raise ApiError("ERR_INVALID_REQUEST", "reject_reason is required.")

    sale = fetch(db.sales, sale_id, "ERR_SALE_NOT_FOUND")
    require_owner(actor, _consignor_id_of_sale(sale))
    if sale["status"] != "PROVISIONAL" or sale["reserve_met"]:
        raise invalid_state(
            "Only a PROVISIONAL sale that missed its reserve may be rejected.")
    sale["reject_reason"] = reason
    _no_sale(sale)
    touch(sale)
    return object_response(sale)


@bp.get("/sales/<sale_id>/consignor-settlements")
@endpoint("PlatformAdmin", "Consignor", "AuctionOperator", "SettlementOfficer")
def list_sale_settlements(actor, sale_id):
    limit, offset = pagination()
    sale = fetch(db.sales, sale_id, "ERR_SALE_NOT_FOUND")
    rows = [s for s in db.consignor_settlements.values()
            if s["sale_id"] == sale["id"]]
    return collection_response(rows, limit, offset)


# --------------------------------------------------------------------------
# consignor settlements
# --------------------------------------------------------------------------
@bp.post("/consignor-settlements")
@endpoint("SettlementOfficer")
def create_consignor_settlement(actor):
    body = json_body()
    sale_id = field_str(body, "sale_id", required=True)
    sale = fetch(db.sales, sale_id, "ERR_SALE_NOT_FOUND")
    # PRD 3.9 / ladder rung 17: "a replay is refused with
    # ERR_DUPLICATE_SETTLEMENT" — the replay is reported as the duplicate
    # conflict, not as the SETTLED state the first posting moved the sale into.
    for existing in db.consignor_settlements.values():
        if existing["sale_id"] == sale["id"] and existing["status"] == "POSTED":
            raise ApiError("ERR_DUPLICATE_SETTLEMENT")
    if sale["status"] != "CONFIRMED":
        raise invalid_state("Only a CONFIRMED sale may be settled with the seller.")
    settlement = post_settlement(sale)
    return object_response(settlement, 201)


@bp.get("/consignor-settlements/<settlement_id>")
@endpoint("PlatformAdmin", "Consignor", "AuctionOperator", "SettlementOfficer")
def get_consignor_settlement(actor, settlement_id):
    return object_response(
        fetch(db.consignor_settlements, settlement_id, "ERR_SETTLEMENT_NOT_FOUND"))
