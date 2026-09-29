"""ResaleListing endpoints (PRD 3.6)."""

from flask import Blueprint

from db import base_record, db, public, sort_created_asc, touch
from errors import ApiError
from middleware import auth, f_enum, f_int, f_str, get_body, q
from response import ok
from services import calc
from services.domain import (
    append_audit,
    get_or_404,
    listings_of_ticket,
    open_denied_entry_incident,
)
from routes._common import filter_eq, paginated

bp = Blueprint("listings", __name__)

LISTING_READERS = ("Patron", "BoxOfficeAgent", "SecurityInvestigator", "VenueAdmin")
MARKETPLACES = ("VERIFIED_PRIMARY", "VERIFIED_PARTNER", "UNVERIFIED")
VERIFIED_CHANNELS = ("VERIFIED_PRIMARY", "VERIFIED_PARTNER")


@bp.route("/resale-listings", methods=["POST"])
def create_listing():
    user_id, role = auth(("Patron",))
    body = get_body()
    ticket_id = f_str(body, "ticket_id", allow_empty=False)
    ask_price_cents = f_int(body, "ask_price_cents", minimum=0)
    marketplace = f_enum(body, "marketplace", MARKETPLACES)
    expected_ticket_version = f_int(body, "expected_ticket_version")

    ticket = get_or_404(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")
    if ticket["holder_patron_id"] != user_id:
        raise ApiError("ERR_NOT_TICKET_HOLDER")
    if expected_ticket_version != ticket["version"]:
        raise ApiError("ERR_STALE_TICKET_VERSION")
    if ticket["lifecycle_status"] == "VOIDED":
        raise ApiError("ERR_TICKET_VOIDED")

    event = db.events[ticket["event_id"]]
    if event["status"] not in ("ON_SALE", "DOORS_OPEN"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")

    seller = db.patrons.get(user_id)
    if seller is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    if seller["fraud_risk_score"] >= calc.FRAUD_BLOCK_THRESHOLD:
        raise ApiError("ERR_PATRON_FRAUD_BLOCKED")
    if not seller["identity_verified"]:
        raise ApiError("ERR_RECIPIENT_NOT_VERIFIED", "The seller's identity is not verified.")
    if ticket["ticket_type"] in ("COMP", "CREDENTIAL"):
        raise ApiError("ERR_TICKET_NOT_TRANSFERABLE")
    if ticket["ticket_type"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", "Only a PAID ticket may be listed for resale.")
    if ticket["admission_status"] != "NOT_ADMITTED":
        raise ApiError("ERR_INVALID_STATE", "An admitted ticket may not be listed for resale.")
    if ticket["lifecycle_status"] not in ("ISSUED", "TRANSFERRED"):
        raise ApiError("ERR_INVALID_STATE", "The ticket's lifecycle_status does not permit listing.")

    if marketplace not in VERIFIED_CHANNELS:
        # The unauthorized-resale signal: no listing row, but evidence is kept.
        open_denied_entry_incident(
            None, ticket, "UNAUTHORIZED_RESALE", event["id"], role, user_id
        )
        raise ApiError("ERR_MARKETPLACE_NOT_VERIFIED")

    cap = calc.resale_price_cap(ticket, event, seller)
    if cap is not None and ask_price_cents > cap:
        raise ApiError("ERR_PRICE_CAP_EXCEEDED")

    superseded = None
    for previous in sort_created_asc(listings_of_ticket(ticket["id"])):
        if previous["status"] in ("DELISTED", "SUSPENDED"):
            superseded = previous["id"]

    rec = base_record()
    rec["ticket_id"] = ticket["id"]
    rec["seller_patron_id"] = user_id
    rec["buyer_patron_id"] = None
    rec["superseded_listing_id"] = superseded
    rec["marketplace"] = marketplace
    rec["ask_price_cents"] = ask_price_cents
    rec["cap_price_cents"] = cap
    rec["status"] = "LISTED"
    rec["platform_fee_cents"] = None
    rec["venue_royalty_cents"] = None
    rec["processing_fee_cents"] = None
    rec["seller_payout_cents"] = None
    db.listings[rec["id"]] = rec

    ticket["lifecycle_status"] = "LISTED"
    touch(ticket)

    append_audit(
        event["id"], "RESALE_LISTING", rec["id"], "RESALE_LISTED", role, user_id,
        "Ticket %s listed on %s at %d cents (cap %s); lifecycle_status -> LISTED."
        % (ticket["id"], marketplace, ask_price_cents, "none" if cap is None else cap),
    )
    return ok(public(rec), 201)


@bp.route("/resale-listings/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    auth(LISTING_READERS)
    listing = get_or_404(db.listings, listing_id, "ERR_LISTING_NOT_FOUND")
    return ok(public(listing))


@bp.route("/resale-listings", methods=["GET"])
def list_listings():
    auth(LISTING_READERS)
    rows = sort_created_asc(list(db.listings.values()))
    rows = filter_eq(rows, "ticket_id", q("ticket_id"))
    rows = filter_eq(rows, "seller_patron_id", q("seller_patron_id"))
    rows = filter_eq(rows, "buyer_patron_id", q("buyer_patron_id"))
    rows = filter_eq(rows, "superseded_listing_id", q("superseded_listing_id"))
    rows = filter_eq(rows, "status", q("status"))
    return paginated(rows)


@bp.route("/resale-listings/<listing_id>/purchase", methods=["POST"])
def purchase_listing(listing_id):
    user_id, role = auth(("Patron",))
    listing = get_or_404(db.listings, listing_id, "ERR_LISTING_NOT_FOUND")
    if listing["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE", "The listing is not on the market.")

    ticket = db.tickets[listing["ticket_id"]]
    event = db.events[ticket["event_id"]]
    if event["status"] not in ("ON_SALE", "DOORS_OPEN"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")
    if listing["marketplace"] not in VERIFIED_CHANNELS:
        raise ApiError("ERR_MARKETPLACE_NOT_VERIFIED")

    buyer = db.patrons.get(user_id)
    if buyer is None:
        raise ApiError("ERR_PATRON_NOT_FOUND")
    if not buyer["identity_verified"]:
        raise ApiError("ERR_RECIPIENT_NOT_VERIFIED", "The buyer's identity is not verified.")
    if listing["seller_patron_id"] == user_id:
        raise ApiError("ERR_SELF_PURCHASE")

    split = calc.resale_settlement_split(listing["ask_price_cents"])
    listing["status"] = "SOLD"
    listing["buyer_patron_id"] = user_id
    listing["platform_fee_cents"] = split["platform_fee_cents"]
    listing["venue_royalty_cents"] = split["venue_royalty_cents"]
    listing["processing_fee_cents"] = split["processing_fee_cents"]
    listing["seller_payout_cents"] = split["seller_payout_cents"]
    touch(listing)

    seller = db.patrons.get(listing["seller_patron_id"])
    if seller is not None:
        seller["payout_balance_cents"] += split["seller_payout_cents"]
        touch(seller)

    event["settlement_pool_cents"] += split["venue_royalty_cents"]
    touch(event)

    ticket["lifecycle_status"] = "RESOLD"
    ticket["holder_patron_id"] = user_id
    ticket["bound_device_fingerprint"] = None
    ticket["device_binding_status"] = "RELEASED"
    touch(ticket)

    append_audit(
        event["id"], "RESALE_LISTING", listing["id"], "RESALE_SOLD", role, user_id,
        "Listing %s sold for %d cents: platform %d, royalty %d, processing %d, payout %d; "
        "ticket lifecycle_status -> RESOLD."
        % (
            listing["id"], listing["ask_price_cents"], split["platform_fee_cents"],
            split["venue_royalty_cents"], split["processing_fee_cents"],
            split["seller_payout_cents"],
        ),
    )
    return ok(public(listing))


@bp.route("/resale-listings/<listing_id>/delist", methods=["POST"])
def delist_listing(listing_id):
    user_id, _role = auth(("Patron",))
    listing = get_or_404(db.listings, listing_id, "ERR_LISTING_NOT_FOUND")
    if listing["seller_patron_id"] != user_id:
        raise ApiError("ERR_NOT_TICKET_HOLDER")
    if listing["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE", "The listing is not on the market.")

    listing["status"] = "DELISTED"
    touch(listing)

    ticket = db.tickets.get(listing["ticket_id"])
    if ticket is not None and ticket["lifecycle_status"] == "LISTED":
        ticket["lifecycle_status"] = "ISSUED"
        touch(ticket)
    return ok(public(listing))
