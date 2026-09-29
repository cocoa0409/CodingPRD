"""Shared lookup, listing and guard helpers used by every route module."""
import auth
import calc
import cascade
import clock
import response
import store
import validate
from errors import ApiError
from store import created_key, db

NOT_FOUND = {
    "markets": "ERR_MARKET_NOT_FOUND",
    "suppliers": "ERR_SUPPLIER_NOT_FOUND",
    "model_agreements": "ERR_AGREEMENT_NOT_FOUND",
    "certifications": "ERR_CERTIFICATION_NOT_FOUND",
    "rate_plans": "ERR_RATE_PLAN_NOT_FOUND",
    "offers": "ERR_OFFER_NOT_FOUND",
    "observations": "ERR_OBSERVATION_NOT_FOUND",
    "parity_cases": "ERR_PARITY_CASE_NOT_FOUND",
    "overrides": "ERR_OVERRIDE_NOT_FOUND",
    "placements": "ERR_PLACEMENT_NOT_FOUND",
    "ranking_runs": "ERR_RANKING_RUN_NOT_FOUND",
    "ranking_entries": "ERR_RANKING_ENTRY_NOT_FOUND",
    "packages": "ERR_PACKAGE_NOT_FOUND",
    "components": "ERR_PACKAGE_COMPONENT_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "disputes": "ERR_DISPUTE_NOT_FOUND",
    "scorecards": "ERR_SCORECARD_NOT_FOUND",
}


def find(collection, row_id):
    row = db[collection].get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def paged(rows, key=None, reverse=False):
    limit, offset = validate.pagination()
    if key is None:
        key = created_key
    rows = sorted(rows, key=key, reverse=reverse)
    return response.collection(rows, limit, offset)


def by_created(row):
    return created_key(row)


def guard_offboarded(supplier):
    """PRD §2.11: OFFBOARDED is terminal for the supplier and everything beneath it."""
    if supplier is not None and supplier["visibility_status"] == "OFFBOARDED":
        raise ApiError("ERR_SUPPLIER_OFFBOARDED")


def plan_supplier(plan):
    return db["suppliers"].get(plan["supplier_id"])


def offer_plan(offer):
    return db["rate_plans"].get(offer["rate_plan_id"])


def offer_supplier(offer):
    plan = offer_plan(offer)
    return plan_supplier(plan) if plan else None


def booking_components(booking):
    """Every offer the booking consumed, in attachment order."""
    if booking["offer_id"]:
        offer = db["offers"].get(booking["offer_id"])
        return [offer] if offer else []
    offers = []
    for component in sorted(db["components"].values(), key=lambda r: r["_seq"]):
        if component["package_id"] != booking["package_id"]:
            continue
        offer = db["offers"].get(component["offer_id"])
        if offer is not None:
            offers.append(offer)
    return offers


def booking_governing_offer(booking):
    """The offer whose rate plan governs cancellation policy and collection model.
    For a package booking that is the HOTEL leg (PRD §3.8)."""
    if booking["offer_id"]:
        return db["offers"].get(booking["offer_id"])
    hotel = None
    first = None
    for component in sorted(db["components"].values(), key=lambda r: r["_seq"]):
        if component["package_id"] != booking["package_id"]:
            continue
        offer = db["offers"].get(component["offer_id"])
        if offer is None:
            continue
        if first is None:
            first = offer
        if component["component_type"] == "HOTEL" and hotel is None:
            hotel = offer
    return hotel or first


def booking_supplier_ids(booking):
    ids = []
    for offer in booking_components(booking):
        supplier = offer_supplier(offer)
        if supplier is not None and supplier["id"] not in ids:
            ids.append(supplier["id"])
    return ids


def booking_supplier(booking):
    offer = booking_governing_offer(booking)
    return offer_supplier(offer) if offer else None
