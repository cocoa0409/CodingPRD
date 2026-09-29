"""Bidders, registrations, deposits, exposure and bids (PRD 3.6, 3.7)."""
from routes.common import (
    ANY_ROLE, ApiError, Blueprint, C, collection_response, db, endpoint,
    field_bool, field_int, field_str, fetch, invalid_state, json_body,
    new_entity, object_response, ordered, pagination, query_enum,
    query_str, require_owner, touch,
)
from middleware import query_required
from services.calculations import (
    base_headroom, country_tier, derive_payment_terms, live_chronological_cap,
    registration_forecast_cap,
)
from services.derive import (
    recompute_bidder, recompute_lot_high_bid, recompute_registration_cap,
    refresh_registration_money,
)

bp = Blueprint("bidding", __name__)


def _release_hold(bidder, registration):
    hold = registration["deposit_hold_cents"] or 0
    released = min(hold, bidder["deposit_held_cents"])
    bidder["deposit_held_cents"] -= released
    bidder["deposit_available_cents"] += released
    recompute_bidder(bidder)
    touch(bidder)


# --------------------------------------------------------------------------
# bidders
# --------------------------------------------------------------------------
@bp.post("/bidders")
@endpoint("PlatformAdmin")
def create_bidder(actor):
    body = json_body()
    legal_name = field_str(body, "legal_name", required=True, min_len=2,
                           max_len=120)
    country_code = field_str(body, "country_code", required=True, min_len=2,
                             max_len=2, pattern=r"^[A-Z]{2}$")
    tax_id = field_str(body, "tax_id", nullable=True, default=None)

    bidder = new_entity()
    bidder.update({
        "legal_name": legal_name,
        "country_code": country_code,
        "tax_id": tax_id,
        "country_tier": country_tier(country_code),
        "deposit_total_cents": 0,
        "deposit_held_cents": 0,
        "deposit_available_cents": 0,
        "deposit_forfeited_cents": 0,
        "open_exposure_cents": 0,
        "default_strike_count": 0,
        "lifetime_purchase_cents": 0,
    })
    db.bidders[bidder["id"]] = bidder
    return object_response(bidder, 201)


@bp.get("/bidders/<bidder_id>")
@endpoint("PlatformAdmin", "ComplianceOfficer", "AuctionOperator",
          "SettlementOfficer", "Bidder")
def get_bidder(actor, bidder_id):
    return object_response(fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND"))


@bp.get("/bidders")
@endpoint("PlatformAdmin", "ComplianceOfficer", "AuctionOperator",
          "SettlementOfficer")
def list_bidders(actor):
    limit, offset = pagination()
    country_code = query_str("country_code")
    tier = query_enum("country_tier", C.COUNTRY_TIERS)
    rows = list(db.bidders.values())
    if country_code is not None:
        rows = [b for b in rows if b["country_code"] == country_code]
    if tier is not None:
        rows = [b for b in rows if b["country_tier"] == tier]
    return collection_response(rows, limit, offset)


@bp.post("/bidders/<bidder_id>/deposits")
@endpoint("SettlementOfficer")
def record_deposit(actor, bidder_id):
    body = json_body()
    amount = field_int(body, "amount_cents", required=True, min_value=1)
    field_str(body, "reference", required=True)
    bidder = fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND")
    bidder["deposit_available_cents"] += amount
    recompute_bidder(bidder)
    touch(bidder)
    return object_response(bidder)


def _registration_for(bidder, auction):
    rows = ordered([r for r in db.bidder_registrations.values()
                    if r["bidder_id"] == bidder["id"]
                    and r["auction_id"] == auction["id"]])
    if not rows:
        return None
    live = [r for r in rows
            if r["status"] in ("REQUESTED", "APPROVED", "SUSPENDED")]
    return live[-1] if live else rows[-1]


@bp.get("/bidders/<bidder_id>/exposure")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def bidder_exposure(actor, bidder_id):
    auction_id = query_required("auction_id")
    variant = query_required("variant")
    if variant not in C.EXPOSURE_VARIANTS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "variant must be one of %s" % ", ".join(C.EXPOSURE_VARIANTS))

    bidder = fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND")
    auction = fetch(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    registration = _registration_for(bidder, auction)
    if registration is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND")

    base = base_headroom(registration)
    if variant == "REGISTRATION_FORECAST":
        cap, exposure = registration_forecast_cap(registration)
        breached = None
    else:
        cap, exposure, breached = live_chronological_cap(registration)

    return object_response({
        "bidder_id": bidder["id"],
        "auction_id": auction["id"],
        "registration_id": registration["id"],
        "variant": variant,
        "base_headroom_cents": base,
        "exposure_cents": exposure,
        "bid_cap_cents": cap,
        "breached_at_sale_id": breached,
    })


# --------------------------------------------------------------------------
# bidder registrations
# --------------------------------------------------------------------------
@bp.post("/bidder-registrations")
@endpoint("Bidder")
def create_registration(actor):
    body = json_body()
    bidder_id = field_str(body, "bidder_id", required=True)
    auction_id = field_str(body, "auction_id", required=True)
    deposit_hold = field_int(body, "deposit_hold_cents", required=True,
                             min_value=1, max_value=1000000000)
    financing_requested = field_bool(body, "financing_requested", default=False)

    bidder = fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND")
    auction = fetch(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")

    # rung 17 — duplicate registration
    for existing in db.bidder_registrations.values():
        if (existing["bidder_id"] == bidder["id"]
                and existing["auction_id"] == auction["id"]
                and existing["status"] in ("REQUESTED", "APPROVED", "SUSPENDED")):
            raise ApiError("ERR_DUPLICATE_REGISTRATION")

    # rung 18 / 19 — eligibility
    if bidder["country_code"] in C.EMBARGOED_COUNTRY_CODES:
        raise ApiError("ERR_COUNTRY_EMBARGOED")
    if bidder["default_strike_count"] >= C.MAX_DEFAULT_STRIKES:
        raise ApiError("ERR_BIDDER_SUSPENDED")

    # rung 36 — deposit rules
    minimum = C.MIN_DEPOSIT_BY_TIER[bidder["country_tier"]]
    if deposit_hold < minimum:
        raise ApiError("ERR_DEPOSIT_BELOW_MINIMUM")
    if deposit_hold > bidder["deposit_available_cents"]:
        raise ApiError("ERR_DEPOSIT_UNAVAILABLE")

    paddle = C.FIRST_PADDLE_NUMBER
    for existing in db.bidder_registrations.values():
        if existing["auction_id"] == auction["id"]:
            if existing["paddle_number"] + 1 > paddle:
                paddle = existing["paddle_number"] + 1

    registration = new_entity()
    registration.update({
        "bidder_id": bidder["id"],
        "auction_id": auction["id"],
        "deposit_hold_cents": deposit_hold,
        "financing_requested": financing_requested,
        "paddle_number": paddle,
        "approved_credit_limit_cents": 0,
        "financing_approved": False,
        "payment_terms_code": None,
        "leverage_multiplier": None,
        "bid_cap_cents": 0,
        "credit_approved_by_user_id": None,
        "decline_reason": None,
        "deposit_applied_total_cents": 0,
        "status": "REQUESTED",
    })
    db.bidder_registrations[registration["id"]] = registration

    bidder["deposit_available_cents"] -= deposit_hold
    bidder["deposit_held_cents"] += deposit_hold
    recompute_bidder(bidder)
    touch(bidder)
    return object_response(registration, 201)


@bp.get("/bidder-registrations/<registration_id>")
@endpoint("PlatformAdmin", "ComplianceOfficer", "AuctionOperator",
          "SettlementOfficer", "Bidder")
def get_registration(actor, registration_id):
    return object_response(
        fetch(db.bidder_registrations, registration_id,
              "ERR_REGISTRATION_NOT_FOUND"))


@bp.get("/bidder-registrations")
@endpoint("PlatformAdmin", "ComplianceOfficer", "AuctionOperator",
          "SettlementOfficer", "Bidder")
def list_registrations(actor):
    limit, offset = pagination()
    bidder_id = query_str("bidder_id")
    auction_id = query_str("auction_id")
    status = query_enum("status", C.REGISTRATION_STATUSES)
    rows = list(db.bidder_registrations.values())
    if bidder_id is not None:
        rows = [r for r in rows if r["bidder_id"] == bidder_id]
    if auction_id is not None:
        rows = [r for r in rows if r["auction_id"] == auction_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection_response(rows, limit, offset)


@bp.post("/bidder-registrations/<registration_id>/credit-decision")
@endpoint("SettlementOfficer")
def credit_decision(actor, registration_id):
    body = json_body()
    decision = field_str(body, "decision", required=True)
    if decision not in ("APPROVE", "DECLINE"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "decision must be APPROVE or DECLINE.")
    credit_limit = field_int(body, "approved_credit_limit_cents", min_value=0,
                             default=None)
    decline_reason = field_str(body, "decline_reason", nullable=True, default=None)

    registration = fetch(db.bidder_registrations, registration_id,
                         "ERR_REGISTRATION_NOT_FOUND")
    bidder = db.bidders[registration["bidder_id"]]
    auction = db.auctions[registration["auction_id"]]

    if registration["status"] != "REQUESTED":
        raise invalid_state("Only a REQUESTED registration may be decided.")
    if decision == "APPROVE" and auction["status"] not in ("SCHEDULED", "OPEN"):
        raise invalid_state("The auction is no longer taking approvals.")
    if decision == "DECLINE" and not decline_reason:
        raise invalid_state("A DECLINE decision requires a decline_reason.")

    if bidder["country_code"] in C.EMBARGOED_COUNTRY_CODES:
        raise ApiError("ERR_COUNTRY_EMBARGOED")
    if bidder["default_strike_count"] >= C.MAX_DEFAULT_STRIKES:
        raise ApiError("ERR_BIDDER_SUSPENDED")

    if decision == "DECLINE":
        registration["status"] = "DECLINED"
        registration["decline_reason"] = decline_reason
        touch(registration)
        _release_hold(bidder, registration)
        return object_response(registration)

    limit_value = credit_limit if credit_limit is not None else 0
    financing_approved = bool(registration["financing_requested"]) and limit_value > 0
    registration["approved_credit_limit_cents"] = limit_value
    registration["financing_approved"] = financing_approved
    registration["payment_terms_code"] = derive_payment_terms(
        financing_approved, bidder["country_tier"])
    registration["leverage_multiplier"] = C.LEVERAGE_BY_TIER[bidder["country_tier"]]
    registration["credit_approved_by_user_id"] = actor.user_id
    registration["status"] = "APPROVED"
    recompute_registration_cap(registration)
    touch(registration)
    return object_response(registration)


@bp.post("/bidder-registrations/<registration_id>/cancel")
@endpoint("Bidder")
def cancel_registration(actor, registration_id):
    json_body()
    registration = fetch(db.bidder_registrations, registration_id,
                         "ERR_REGISTRATION_NOT_FOUND")
    require_owner(actor, registration["bidder_id"])
    if registration["status"] not in ("REQUESTED", "APPROVED"):
        raise invalid_state("This registration may no longer be cancelled.")
    for bid in db.bids.values():
        if (bid["registration_id"] == registration["id"]
                and bid["status"] in ("ACTIVE", "WINNING")):
            raise invalid_state("A registration with live bids may not be cancelled.")
    registration["status"] = "CANCELLED"
    registration["bid_cap_cents"] = 0
    touch(registration)
    _release_hold(db.bidders[registration["bidder_id"]], registration)
    return object_response(registration)


# --------------------------------------------------------------------------
# bids
# --------------------------------------------------------------------------
@bp.post("/bids")
@endpoint("Bidder")
def create_bid(actor):
    body = json_body()
    registration_id = field_str(body, "registration_id", required=True)
    lot_id = field_str(body, "lot_id", required=True)
    amount = field_int(body, "amount_cents", required=True, min_value=1,
                       max_value=1000000000)

    registration = fetch(db.bidder_registrations, registration_id,
                         "ERR_REGISTRATION_NOT_FOUND")
    lot = fetch(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    require_owner(actor, registration["bidder_id"])
    bidder = db.bidders[registration["bidder_id"]]

    auction = db.auctions.get(lot["auction_id"]) if lot["auction_id"] else None
    if auction is None or auction["status"] != "OPEN":
        raise ApiError("ERR_AUCTION_NOT_OPEN")
    if registration["status"] != "APPROVED":
        raise ApiError("ERR_REGISTRATION_NOT_APPROVED")
    if bidder["default_strike_count"] >= C.MAX_DEFAULT_STRIKES:
        raise ApiError("ERR_BIDDER_SUSPENDED")

    cap, _consumed, _breached = live_chronological_cap(registration)
    if amount > cap:
        raise ApiError("ERR_BID_CAP_EXCEEDED")

    existing = [b for b in db.bids.values() if b["lot_id"] == lot["id"]]
    if not existing:
        if amount < C.MIN_OPENING_BID_CENTS:
            raise ApiError("ERR_BID_NOT_HIGHER")
    elif amount <= (lot["high_bid_cents"] or 0):
        raise ApiError("ERR_BID_NOT_HIGHER")

    bid = new_entity(versioned=False)
    bid.update({
        "registration_id": registration["id"],
        "lot_id": lot["id"],
        "amount_cents": amount,
        "placed_at": db.now(),
        "status": "ACTIVE",
    })
    db.bids[bid["id"]] = bid
    recompute_lot_high_bid(lot)
    return object_response(bid, 201)


@bp.get("/bids/<bid_id>")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def get_bid(actor, bid_id):
    return object_response(fetch(db.bids, bid_id, "ERR_BID_NOT_FOUND"))


@bp.get("/bids")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def list_bids(actor):
    limit, offset = pagination()
    registration_id = query_str("registration_id")
    lot_id = query_str("lot_id")
    status = query_enum("status", C.BID_STATUSES)
    rows = list(db.bids.values())
    if registration_id is not None:
        rows = [b for b in rows if b["registration_id"] == registration_id]
    if lot_id is not None:
        rows = [b for b in rows if b["lot_id"] == lot_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    return collection_response(rows, limit, offset)
