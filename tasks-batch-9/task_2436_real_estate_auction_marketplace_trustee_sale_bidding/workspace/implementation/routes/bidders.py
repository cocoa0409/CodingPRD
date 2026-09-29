"""Bidder registration, identity, deposits, exclusions and their reads (PRD §3.4)."""

from flask import Blueprint

import calc
import db
import serial
import services
import validate as v
from auth import authenticate, require_owner
from db import ordered, store, touch
from errors import ApiError
from helpers import body_fk, find
from util import ok, ok_list

bp = Blueprint("bidders", __name__)


@bp.post("/bidders")
def register_bidder():
    authenticate(("Anonymous",))
    data = v.body()
    legal_name = v.req_str(data, "legal_name")
    email = v.req_email(data, "email")
    mailing_address = v.req_str(data, "mailing_address")

    rec = db.new_record(
        legal_name=legal_name,
        email=email,
        mailing_address=mailing_address,
        identity_verification_status="UNVERIFIED",
        identity_verified_at=None,
        registration_status="PENDING_REVIEW",
        deposit_funded_cents=0,
        deposit_available_cents=0,
        deposit_forfeited_cents=0,
        fallout_count=0,
        screen_risk_score=0,
    )
    store.bidders[rec["id"]] = rec
    services.recompute_ledger(rec)
    services.recompute_screen_score(rec)
    return ok(serial.dump("bidder", rec), 201)


@bp.post("/bidders/<rec_id>/identity-verification")
def record_identity(rec_id):
    authenticate(("ComplianceOfficer",))
    bidder = find(store.bidders, rec_id, "ERR_BIDDER_NOT_FOUND")
    data = v.body()
    decision = v.req_enum(data, "decision", calc.VERIFY_DECISIONS)
    v.req_str(data, "document_reference")
    if bidder["identity_verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_BIDDER_NOT_REGISTERED")

    if decision == "VERIFIED":
        bidder["identity_verification_status"] = "VERIFIED"
        bidder["identity_verified_at"] = db.now()
        if bidder["registration_status"] == "PENDING_REVIEW":
            bidder["registration_status"] = "REGISTERED"
    else:
        bidder["identity_verification_status"] = "REJECTED"
        if bidder["registration_status"] == "PENDING_REVIEW":
            bidder["registration_status"] = "REJECTED"
    services.refresh_bidder(bidder, force=True, with_score=True)
    return ok(serial.dump("bidder", bidder))


@bp.post("/bidders/<rec_id>/deposits")
def fund_deposit(rec_id):
    user_id, _role = authenticate(("Bidder",))
    bidder = find(store.bidders, rec_id, "ERR_BIDDER_NOT_FOUND")
    require_owner(user_id, bidder["id"])
    data = v.body()
    amount = v.req_int(data, "amount_cents", minimum=1)
    v.req_str(data, "funding_reference")
    if bidder["registration_status"] == "BARRED":
        raise ApiError("ERR_BIDDER_BARRED")

    bidder["deposit_funded_cents"] = bidder["deposit_funded_cents"] + amount
    services.refresh_bidder(bidder, force=True, with_score=True)
    return ok(serial.dump("bidder", bidder))


@bp.post("/eligibility-exclusions")
def create_exclusion():
    authenticate(("ComplianceOfficer",))
    data = v.body()
    bidder = body_fk(data, "bidder_id", store.bidders, "ERR_BIDDER_NOT_FOUND")
    exclusion_type = v.req_enum(data, "exclusion_type", calc.CLIENT_EXCLUSION_TYPES)
    effective_at = v.req_dt(data, "effective_at")
    county = v.opt_str(data, "county_code", default="ALL")
    if not county.strip():
        v.bad("Field 'county_code' must not be blank.")
    notes = v.opt_str(data, "notes")
    if bidder is None:
        v.bad("Field 'bidder_id' is required.")

    rec = db.new_record(
        bidder_id=bidder["id"],
        exclusion_type=exclusion_type,
        county_code=county,
        effective_at=effective_at,
        status="ACTIVE",
        lifted_at=None,
        notes=notes,
    )
    store.exclusions[rec["id"]] = rec

    if county == "ALL" and effective_at <= db.now() and \
            bidder["registration_status"] == "REGISTERED":
        bidder["registration_status"] = "SUSPENDED"
    services.refresh_bidder(bidder, force=True, with_score=True)
    return ok(serial.dump("exclusion", rec), 201)


@bp.post("/eligibility-exclusions/<rec_id>/lift")
def lift_exclusion(rec_id):
    authenticate(("ComplianceOfficer",))
    exclusion = find(store.exclusions, rec_id, "ERR_EXCLUSION_NOT_FOUND")
    data = v.body()
    notes = v.opt_str(data, "notes")

    exclusion["status"] = "LIFTED"
    exclusion["lifted_at"] = db.now()
    if notes is not None:
        exclusion["notes"] = notes
    touch(exclusion)

    bidder = store.bidders.get(exclusion["bidder_id"])
    if bidder is not None:
        if bidder["registration_status"] == "SUSPENDED" and \
                not services.is_excluded_now(bidder["id"], None):
            bidder["registration_status"] = "REGISTERED"
        services.refresh_bidder(bidder, force=True, with_score=True)
    return ok(serial.dump("exclusion", exclusion))


@bp.get("/bidders/<rec_id>")
def get_bidder(rec_id):
    authenticate(("PlatformAdmin", "ComplianceOfficer", "AuctionOps", "Bidder"))
    bidder = find(store.bidders, rec_id, "ERR_BIDDER_NOT_FOUND")
    return ok(serial.dump("bidder", bidder))


@bp.get("/bidders/<rec_id>/eligibility-exclusions")
def list_bidder_exclusions(rec_id):
    authenticate(("PlatformAdmin", "ComplianceOfficer", "AuctionOps"))
    find(store.bidders, rec_id, "ERR_BIDDER_NOT_FOUND")
    limit, offset = v.pagination()
    status = v.query_enum("status", calc.EXCLUSION_STATUS)
    kind = v.query_enum("exclusion_type", calc.EXCLUSION_TYPES)
    items = [e for e in ordered(store.exclusions.values()) if e["bidder_id"] == rec_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if kind is not None:
        items = [e for e in items if e["exclusion_type"] == kind]
    total = len(items)
    return ok_list(serial.dump_many("exclusion", v.page(items, limit, offset)),
                   limit, offset, total)


@bp.get("/bidders/<rec_id>/eligibility-assessment")
def eligibility_assessment(rec_id):
    user_id, role = authenticate(("PlatformAdmin", "ComplianceOfficer", "Bidder"))
    bidder = find(store.bidders, rec_id, "ERR_BIDDER_NOT_FOUND")
    if role == "Bidder":
        require_owner(user_id, bidder["id"])
    mode = v.query_enum("mode", calc.ASSESSMENT_MODES) or "SCREEN"
    lot_id = v.query_str("auction_lot_id")
    if mode == "AUDIT" and lot_id is None:
        raise ApiError("ERR_AUDIT_MODE_REQUIRES_LOT")

    lot = None
    event = None
    if lot_id is not None:
        lot = store.auction_lots.get(lot_id)
        if lot is None:
            raise ApiError("ERR_AUCTION_LOT_NOT_FOUND")
        event = store.auction_events.get(lot["auction_event_id"])
    return ok(services.risk_assessment(bidder, mode, lot, event))


@bp.get("/bids/<rec_id>")
def get_bid(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Bidder"))
    bid = find(store.bids, rec_id, "ERR_BID_NOT_FOUND")
    return ok(serial.dump("bid", bid))


@bp.get("/bids")
def list_bids():
    authenticate(("PlatformAdmin", "AuctionOps", "Trustee", "Seller", "Bidder"))
    limit, offset = v.pagination()
    lot_id = v.query_str("auction_lot_id")
    bidder_id = v.query_str("bidder_id")
    status = v.query_enum("bid_status", calc.BID_STATUS)
    items = ordered(store.bids.values())
    if lot_id is not None:
        items = [b for b in items if b["auction_lot_id"] == lot_id]
    if bidder_id is not None:
        items = [b for b in items if b["bidder_id"] == bidder_id]
    if status is not None:
        items = [b for b in items if b["bid_status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("bid", v.page(items, limit, offset)),
                   limit, offset, total)


@bp.get("/deposit-holds/<rec_id>")
def get_hold(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "ComplianceOfficer", "Bidder"))
    hold = store.deposit_holds.get(rec_id)
    if hold is None:
        raise ApiError("ERR_DEPOSIT_HOLD_NOT_FOUND",
                       "No deposit hold with that id exists.", 404)
    return ok(serial.dump("deposit_hold", hold))


@bp.get("/deposit-holds")
def list_holds():
    authenticate(("PlatformAdmin", "AuctionOps", "ComplianceOfficer", "Bidder"))
    limit, offset = v.pagination()
    bidder_id = v.query_str("bidder_id")
    lot_id = v.query_str("auction_lot_id")
    status = v.query_enum("status", calc.HOLD_STATUS)
    items = ordered(store.deposit_holds.values())
    if bidder_id is not None:
        items = [h for h in items if h["bidder_id"] == bidder_id]
    if lot_id is not None:
        items = [h for h in items if h["auction_lot_id"] == lot_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("deposit_hold", v.page(items, limit, offset)),
                   limit, offset, total)
