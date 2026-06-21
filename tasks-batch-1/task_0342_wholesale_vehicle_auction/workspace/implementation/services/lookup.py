"""Existence lookups raising the entity-specific not-found error (PRD §2.5)."""
import db
from errors import ApiError


def _get(collection, rid, err):
    if rid is None:
        raise ApiError(err, "Referenced resource not found.")
    rec = collection.get(rid)
    if rec is None:
        raise ApiError(err, "Referenced resource not found.")
    return rec


def get_sale(rid):
    return _get(db.sales, rid, "ERR_SALE_NOT_FOUND")


def get_lane(rid):
    return _get(db.lanes, rid, "ERR_LANE_NOT_FOUND")


def get_seller(rid):
    return _get(db.sellers, rid, "ERR_SELLER_NOT_FOUND")


def get_buyer(rid):
    return _get(db.buyers, rid, "ERR_BUYER_NOT_FOUND")


def get_consignment(rid):
    return _get(db.consignments, rid, "ERR_CONSIGNMENT_NOT_FOUND")


def get_condition_report(rid):
    return _get(db.condition_reports, rid, "ERR_CONDITION_REPORT_NOT_FOUND")


def get_lot(rid):
    return _get(db.lots, rid, "ERR_LOT_NOT_FOUND")


def get_bid(rid):
    return _get(db.bids, rid, "ERR_BID_NOT_FOUND")


def get_claim(rid):
    return _get(db.arbitration_claims, rid, "ERR_CLAIM_NOT_FOUND")


def get_settlement(rid):
    return _get(db.settlements, rid, "ERR_SETTLEMENT_NOT_FOUND")


def get_gate_pass(rid):
    return _get(db.gate_passes, rid, "ERR_GATE_PASS_NOT_FOUND")


def get_carrier(rid):
    return _get(db.carriers, rid, "ERR_CARRIER_NOT_FOUND")


def get_transport_order(rid):
    return _get(db.transport_orders, rid, "ERR_TRANSPORT_NOT_FOUND")
