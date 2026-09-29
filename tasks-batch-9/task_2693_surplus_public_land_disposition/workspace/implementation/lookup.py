"""Path and body foreign-key resolution with the per-entity 404 codes (PRD 2.9)."""

import db
from errors import fail

NOT_FOUND = {
    "agencies": "ERR_AGENCY_NOT_FOUND",
    "parcels": "ERR_PARCEL_NOT_FOUND",
    "declarations": "ERR_DECLARATION_NOT_FOUND",
    "notices": "ERR_NOTICE_NOT_FOUND",
    "preference_offers": "ERR_PREFERENCE_OFFER_NOT_FOUND",
    "appraisers": "ERR_APPRAISER_NOT_FOUND",
    "appraisals": "ERR_APPRAISAL_NOT_FOUND",
    "appraisal_challenges": "ERR_CHALLENGE_NOT_FOUND",
    "environmental_reviews": "ERR_ENV_REVIEW_NOT_FOUND",
    "title_items": "ERR_TITLE_ITEM_NOT_FOUND",
    "offerings": "ERR_OFFERING_NOT_FOUND",
    "bidders": "ERR_BIDDER_NOT_FOUND",
    "bids": "ERR_BID_NOT_FOUND",
    "conveyances": "ERR_CONVEYANCE_NOT_FOUND",
    "funds": "ERR_FUND_NOT_FOUND",
}


def must(collection, row_id):
    row = db.get(collection, row_id)
    if row is None:
        fail(NOT_FOUND[collection], "No such %s: %s" % (collection[:-1], row_id))
    return row


def must_fk(collection, row_id):
    """A body foreign key: it must be a string naming an existing row."""
    if not isinstance(row_id, str) or not row_id:
        fail("ERR_INVALID_REQUEST", "A foreign key must be a non-empty string.")
    return must(collection, row_id)
