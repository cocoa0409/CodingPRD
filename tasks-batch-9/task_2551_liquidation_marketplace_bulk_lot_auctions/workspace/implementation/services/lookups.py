"""Existence lookups: band 3 (path, left to right) and band 6 (body FKs)."""

import db
from errors import ApiError


def _get(store, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    row = store.get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def seller(identifier):
    return _get(db.sellers, identifier, "ERR_SELLER_NOT_FOUND")


def buyer(identifier):
    return _get(db.buyers, identifier, "ERR_BUYER_NOT_FOUND")


def warehouse(identifier):
    return _get(db.warehouses, identifier, "ERR_WAREHOUSE_NOT_FOUND")


def carrier(identifier):
    return _get(db.carriers, identifier, "ERR_CARRIER_NOT_FOUND")


def brand_policy(identifier):
    return _get(db.brand_policies, identifier, "ERR_BRAND_POLICY_NOT_FOUND")


def lot(identifier):
    return _get(db.lots, identifier, "ERR_LOT_NOT_FOUND")


def manifest_line(identifier):
    return _get(db.manifest_lines, identifier, "ERR_MANIFEST_LINE_NOT_FOUND")


def listing(identifier):
    return _get(db.listings, identifier, "ERR_LISTING_NOT_FOUND")


def bid(identifier):
    return _get(db.bids, identifier, "ERR_NOT_FOUND")


def negotiation(identifier):
    return _get(db.negotiations, identifier, "ERR_NEGOTIATION_NOT_FOUND")


def offer(identifier):
    return _get(db.offers, identifier, "ERR_OFFER_NOT_FOUND")


def sale_order(identifier):
    return _get(db.sale_orders, identifier, "ERR_SALE_ORDER_NOT_FOUND")


def appointment(identifier):
    return _get(db.appointments, identifier, "ERR_APPOINTMENT_NOT_FOUND")


def claim(identifier):
    return _get(db.claims, identifier, "ERR_CLAIM_NOT_FOUND")


# ---------------------------------------------------------------- derivations

def lot_of_listing(listing_row):
    return db.lots.get(listing_row["lot_id"])


def listing_of_order(order_row):
    return db.listings.get(order_row["listing_id"])


def lot_of_order(order_row):
    listing_row = db.listings.get(order_row["listing_id"])
    if listing_row is None:
        return None
    return db.lots.get(listing_row["lot_id"])


def seller_of_lot(lot_row):
    return db.sellers.get(lot_row["seller_id"])


def seller_of_listing(listing_row):
    lot_row = lot_of_listing(listing_row)
    return db.sellers.get(lot_row["seller_id"]) if lot_row else None


def seller_of_order(order_row):
    lot_row = lot_of_order(order_row)
    return db.sellers.get(lot_row["seller_id"]) if lot_row else None


def policy_of_lot(lot_row):
    if not lot_row.get("brand_policy_id"):
        return None
    return db.brand_policies.get(lot_row["brand_policy_id"])


def order_of_claim(claim_row):
    return db.sale_orders.get(claim_row["sale_order_id"])


def order_of_appointment(appointment_row):
    return db.sale_orders.get(appointment_row["sale_order_id"])


def lines_of_lot(lot_id, active_only=False):
    rows = [
        row for row in db.manifest_lines.values()
        if row["lot_id"] == lot_id and (not active_only or row["line_status"] == "ACTIVE")
    ]
    return db.ordered(rows)


def listings_of_lot(lot_id):
    return db.ordered([r for r in db.listings.values() if r["lot_id"] == lot_id])


def bids_of_listing(listing_id):
    return db.ordered([r for r in db.bids.values() if r["listing_id"] == listing_id])


def bids_of_buyer(buyer_id):
    return db.ordered([r for r in db.bids.values() if r["buyer_id"] == buyer_id])


def negotiations_of_listing(listing_id):
    return db.ordered(
        [r for r in db.negotiations.values() if r["listing_id"] == listing_id]
    )


def offers_of_negotiation(negotiation_id):
    rows = [r for r in db.offers.values() if r["negotiation_id"] == negotiation_id]
    return sorted(rows, key=lambda row: (row["round_number"], row["_seq"]))


def orders_of_buyer(buyer_id):
    return db.ordered([r for r in db.sale_orders.values() if r["buyer_id"] == buyer_id])


def orders_of_seller(seller_id):
    rows = []
    for order_row in db.sale_orders.values():
        lot_row = lot_of_order(order_row)
        if lot_row is not None and lot_row["seller_id"] == seller_id:
            rows.append(order_row)
    return db.ordered(rows)


def lots_of_seller(seller_id):
    return db.ordered([r for r in db.lots.values() if r["seller_id"] == seller_id])


def claims_of_order(order_id):
    return db.ordered([r for r in db.claims.values() if r["sale_order_id"] == order_id])


def claims_of_line(line_id):
    return db.ordered(
        [r for r in db.claims.values() if r["manifest_line_id"] == line_id]
    )


def claims_of_lot(lot_id):
    line_ids = {row["id"] for row in db.manifest_lines.values() if row["lot_id"] == lot_id}
    return db.ordered(
        [r for r in db.claims.values() if r["manifest_line_id"] in line_ids]
    )


def appointments_of_order(order_id):
    return db.ordered(
        [r for r in db.appointments.values() if r["sale_order_id"] == order_id]
    )
