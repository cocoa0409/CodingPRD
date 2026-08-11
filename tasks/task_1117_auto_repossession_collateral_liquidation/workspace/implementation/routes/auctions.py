"""Auction houses, consignments, sale records (PRD §3.6)."""
from flask import Blueprint

from db import store, base_fields, touch, get_or_404, sorted_all, now
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_CASE_STATE,
    ERR_INVALID_CONSIGNMENT_STATE, ERR_INVALID_SALE_STATE,
    ERR_FORBIDDEN_OWNERSHIP, ERR_SEGREGATION_OF_DUTIES,
    ERR_AUCTION_WINDOW_OVERLAP, ERR_BID_BELOW_RESERVE,
)
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import auction_house_out, consignment_out, sale_out
from services import calc
from util import validate_body

bp = Blueprint("auctions", __name__)


@bp.post("/auction-houses")
def create_auction_house():
    require_roles("RecoveryManager")
    body = validate_body({
        "name": ("str", True, None),
        "fee_bps": ("nonneg_int", True, None),
        "transport_fee_cents": ("nonneg_int", True, None),
    })
    house = base_fields()
    house.update({
        "name": body["name"],
        "fee_bps": body["fee_bps"],
        "transport_fee_cents": body["transport_fee_cents"],
        "_seq": store.next_seq(),
    })
    store.auction_houses[house["id"]] = house
    return object_response(auction_house_out(house), 201)


@bp.get("/auction-houses/<hid>")
def get_auction_house(hid):
    require_roles(*ALL_ROLES)
    house = get_or_404(store.auction_houses, hid, "AuctionHouse")
    return object_response(auction_house_out(house))


@bp.get("/auction-houses/<hid>/consignments")
def list_house_consignments(hid):
    require_roles(*ALL_ROLES)
    get_or_404(store.auction_houses, hid, "AuctionHouse")
    rows = [c for c in sorted_all(store.consignments)
            if c["auction_house_id"] == hid]
    return list_response(rows, consignment_out)


@bp.post("/recovery-cases/<cid>/consignments")
def create_consignment(cid):
    require_roles("RecoveryManager")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    body = validate_body({
        "auction_house_id": ("str", True, None),
    })
    if body["auction_house_id"] not in store.auction_houses:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "auction_house_id does not reference an existing auction house")
    if case["status"] != "CONSIGNMENT_PENDING" or case["condition_grade"] is None:
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit consignment")
    loan = store.loan_accounts[case["loan_account_id"]]
    seq = len(calc.case_consignments(case["id"])) + 1
    consignment = base_fields()
    consignment.update({
        "recovery_case_id": case["id"],
        "auction_house_id": body["auction_house_id"],
        "status": "DRAFT",
        "reserve_price_cents": calc.reserve_price(case, loan),
        "listing_start": None,
        "listing_end": None,
        "relist_count": 0,
        "consignment_seq": seq,
        "_seq": store.next_seq(),
    })
    store.consignments[consignment["id"]] = consignment
    return object_response(consignment_out(consignment), 201)


@bp.get("/recovery-cases/<cid>/consignments")
def list_case_consignments(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.recovery_cases, cid, "RecoveryCase")
    return list_response(calc.case_consignments(cid), consignment_out)


@bp.get("/consignments/<cid>")
def get_consignment(cid):
    require_roles(*ALL_ROLES)
    consignment = get_or_404(store.consignments, cid, "Consignment")
    return object_response(consignment_out(consignment))


def _owned_consignment(cid, user_id):
    consignment = get_or_404(store.consignments, cid, "Consignment")
    if consignment["auction_house_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Consignment belongs to a different auction house")
    return consignment


def _check_window_overlap(consignment, start, end):
    """Closed-interval windows at one venue may not touch or overlap."""
    for other in store.consignments.values():
        if other["id"] == consignment["id"]:
            continue
        if other["auction_house_id"] != consignment["auction_house_id"]:
            continue
        if other["status"] != "LISTED":
            continue
        if calc.overlaps_closed(start, end,
                                other["listing_start"], other["listing_end"]):
            raise ApiError(ERR_AUCTION_WINDOW_OVERLAP, 409,
                           "Listing window touches or overlaps a LISTED window "
                           "at the same auction house")


def _list_common(cid, from_status):
    """Shared list/relist checks in validation-priority order."""
    user_id, _role = require_roles("Auctioneer")
    consignment = get_or_404(store.consignments, cid, "Consignment")
    if consignment["auction_house_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Consignment belongs to a different auction house")
    body = validate_body({
        "listing_start": ("datetime", True, None),
        "listing_end": ("datetime", True, None),
    })
    if consignment["status"] != from_status:
        raise ApiError(ERR_INVALID_CONSIGNMENT_STATE, 409,
                       f"Consignment status {consignment['status']} does not permit this listing")
    case = store.recovery_cases[consignment["recovery_case_id"]]
    if case["status"] != "CONSIGNMENT_PENDING":
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit listing")
    _check_window_overlap(consignment, body["listing_start"], body["listing_end"])
    return consignment, case, body


@bp.post("/consignments/<cid>/list")
def list_consignment(cid):
    consignment, case, body = _list_common(cid, "DRAFT")
    consignment["listing_start"] = body["listing_start"]
    consignment["listing_end"] = body["listing_end"]
    consignment["status"] = "LISTED"
    touch(consignment)
    case["status"] = "IN_AUCTION"
    touch(case)
    return object_response(consignment_out(consignment))


@bp.post("/consignments/<cid>/relist")
def relist_consignment(cid):
    consignment, case, body = _list_common(cid, "UNSOLD")
    # Markdown is computed BEFORE the transition commits.
    consignment["reserve_price_cents"] = calc.relist_reserve(
        consignment["reserve_price_cents"])
    consignment["relist_count"] += 1
    consignment["listing_start"] = body["listing_start"]
    consignment["listing_end"] = body["listing_end"]
    consignment["status"] = "LISTED"
    touch(consignment)
    case["status"] = "IN_AUCTION"
    touch(case)
    return object_response(consignment_out(consignment))


def _live_sale(consignment_id):
    for s in store.sale_records.values():
        if s["consignment_id"] == consignment_id and s["status"] != "VOID":
            return s
    return None


@bp.post("/consignments/<cid>/report-sale")
def report_sale(cid):
    user_id, _role = require_roles("Auctioneer")
    consignment = _owned_consignment(cid, user_id)
    body = validate_body({
        "gross_sale_cents": ("pos_int", True, None),
    })
    if consignment["status"] != "LISTED" or _live_sale(cid) is not None:
        raise ApiError(ERR_INVALID_CONSIGNMENT_STATE, 409,
                       "Consignment status does not permit report-sale")
    if body["gross_sale_cents"] < consignment["reserve_price_cents"]:
        raise ApiError(ERR_BID_BELOW_RESERVE, 422,
                       "Gross sale is below the reserve price")
    house = store.auction_houses[consignment["auction_house_id"]]
    auction_fee, transport_fee, net = calc.sale_fee_lines(
        house, body["gross_sale_cents"])
    sale = base_fields()
    sale.update({
        "consignment_id": consignment["id"],
        "gross_sale_cents": body["gross_sale_cents"],
        "auction_fee_cents": auction_fee,
        "transport_fee_cents": transport_fee,
        "net_proceeds_cents": net,
        "status": "PENDING_CERTIFICATION",
        "_seq": store.next_seq(),
    })
    store.sale_records[sale["id"]] = sale
    # The consignment stays LISTED until certification.
    return object_response(sale_out(sale), 201)


@bp.post("/consignments/<cid>/report-unsold")
def report_unsold(cid):
    user_id, _role = require_roles("Auctioneer")
    consignment = _owned_consignment(cid, user_id)
    validate_body({})
    if consignment["status"] != "LISTED" or _live_sale(cid) is not None:
        raise ApiError(ERR_INVALID_CONSIGNMENT_STATE, 409,
                       f"Consignment status {consignment['status']} does not permit report-unsold")
    consignment["status"] = "UNSOLD"
    touch(consignment)
    case = store.recovery_cases[consignment["recovery_case_id"]]
    case["status"] = "CONSIGNMENT_PENDING"
    touch(case)
    return object_response(consignment_out(consignment))


@bp.get("/consignments/<cid>/sale-records")
def list_sale_records(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.consignments, cid, "Consignment")
    rows = [s for s in sorted_all(store.sale_records)
            if s["consignment_id"] == cid]
    return list_response(rows, sale_out)


@bp.post("/sale-records/<sid>/certify")
def certify_sale(sid):
    user_id, _role = require_roles("ComplianceOfficer")
    sale = get_or_404(store.sale_records, sid, "SaleRecord")
    validate_body({})
    if sale["status"] != "PENDING_CERTIFICATION":
        raise ApiError(ERR_INVALID_SALE_STATE, 409,
                       f"SaleRecord status {sale['status']} does not permit certify")
    consignment = store.consignments[sale["consignment_id"]]
    case = store.recovery_cases[consignment["recovery_case_id"]]
    if case["status"] != "IN_AUCTION":
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit certification")
    if user_id == case["opened_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The case opener may not certify its sale")
    sale["status"] = "CERTIFIED"
    touch(sale)
    consignment["status"] = "SOLD"
    touch(consignment)
    case["status"] = "SALE_CONFIRMED"
    case["sold_at"] = now()
    touch(case)
    return object_response(sale_out(sale))
