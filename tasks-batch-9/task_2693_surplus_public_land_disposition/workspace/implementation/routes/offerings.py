"""Disposition offerings, sealed bids, grading, award and rescission
(PRD 3.8).  The bidding window is HALF-OPEN, so adjacency is legal.
"""

from flask import Blueprint, g

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import (AGENCY_REP, BIDDER, CLERK, FINANCE, MONITOR, RPO, SYSADMIN,
                        authorize)
from services import calc, cascade, derive

bp = Blueprint("offerings", __name__)

OFFERING_TYPES = ("COMPETITIVE_SALE", "NEGOTIATED_SALE", "EXCHANGE")
OFFERING_STATUSES = ("DRAFT", "OPEN", "EVALUATION", "AWARDED", "FAILED_NO_QUALIFYING_BID",
                     "CANCELLED", "CLOSED_CONVEYED")
PRICE_VARIANTS = ("MARKET_FLOOR", "AFFORDABLE_HOUSING_PREFERENCE")
QUALIFICATION_STATUSES = ("SUBMITTED", "QUALIFIED", "DISQUALIFIED", "WITHDRAWN", "WINNING",
                          "BACKUP")
DEPOSIT_STATUSES = ("HELD", "RELEASED", "APPLIED")
READ_ROLES = (RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, BIDDER, SYSADMIN)
BID_READ_ROLES = (RPO, CLERK, MONITOR, FINANCE, BIDDER, SYSADMIN)


def _offering_state(offering, *from_states):
    if offering["status"] not in from_states:
        fail("ERR_INVALID_OFFERING_STATE",
             "An offering that is %s cannot take this action." % offering["status"])


def _parcel_of(offering):
    declaration = db.get("declarations", offering["declaration_id"])
    if declaration is None:
        return None
    return db.get("parcels", declaration["parcel_id"])


@bp.post("/offerings")
@authorize(RPO)
def create_offering():
    payload = shape.body()
    offering_type = shape.req_enum(payload, "offering_type", OFFERING_TYPES)
    open_at, open_raw = shape.req_instant(payload, "bid_open_at")
    close_at, close_raw = shape.req_instant(payload, "bid_close_at")
    expected_version = shape.req_int(payload, "expected_declaration_version")
    declaration_id = payload.get("declaration_id")
    if declaration_id is None:
        fail("ERR_INVALID_REQUEST", "declaration_id is required.")
    bidder_leg = payload.get("counterparty_bidder_id")
    agency_leg = payload.get("counterparty_agency_id")
    if offering_type == "COMPETITIVE_SALE" and (bidder_leg is not None
                                                or agency_leg is not None):
        fail("ERR_INVALID_REQUEST",
             "A competitive sale carries no counterparty leg.")

    declaration = lookup.must_fk("declarations", declaration_id)
    counterparty_bidder = None
    counterparty_agency = None
    if bidder_leg is not None:
        counterparty_bidder = lookup.must_fk("bidders", bidder_leg)
    if agency_leg is not None:
        counterparty_agency = lookup.must_fk("agencies", agency_leg)

    if expected_version != declaration["version"]:
        fail("ERR_STALE_DECLARATION_VERSION",
             "expected_declaration_version %s does not match the declaration's current "
             "version %s." % (expected_version, declaration["version"]))
    if declaration["status"] != "OFFERING_AUTHORIZED":
        fail("ERR_INVALID_DECLARATION_STATE",
             "An offering requires the declaration to be OFFERING_AUTHORIZED.")

    if offering_type != declaration.get("authorized_disposition_type"):
        fail("ERR_OFFERING_TYPE_AUTHORITY_MISMATCH",
             "The board authorized %s, not %s."
             % (declaration.get("authorized_disposition_type"), offering_type))

    parcel = db.get("parcels", declaration["parcel_id"])
    appraisal = derive.accepted_appraisal(parcel["id"]) if parcel is not None else None
    if appraisal is None:
        fail("ERR_NO_ACCEPTED_APPRAISAL",
             "The parcel carries no ACCEPTED appraisal, so the offering cannot be priced.")
    if clockmod.now() >= appraisal["expires_on"]:
        # The observed expiry is performed before the refusal is issued, and it persists.
        appraisal["status"] = "EXPIRED"
        db.touch(appraisal)
        fail("ERR_APPRAISAL_EXPIRED",
             "The governing appraisal has passed its validity window.")

    if not close_at > open_at:
        fail("ERR_OFFERING_WINDOW_INVALID", "bid_close_at must be strictly after bid_open_at.")
    if calc.offering_window_conflict(parcel["id"], open_at, close_at):
        fail("ERR_OFFERING_WINDOW_CONFLICT",
             "A live offering on this parcel already holds an intersecting window.")
    if not derive.disposition_ready(parcel):
        fail("ERR_PARCEL_NOT_DISPOSITION_READY", "The parcel is not disposition-ready.")

    if offering_type == "NEGOTIATED_SALE":
        legs = [leg for leg in (counterparty_bidder, counterparty_agency) if leg is not None]
        if len(legs) != 1:
            fail("ERR_NEGOTIATED_BUYER_REQUIRED",
                 "A negotiated sale supplies exactly one counterparty leg.")
        if declaration.get("_authorized_from") == "NEGOTIATION_AGREED":
            agreed = calc.agreed_ah_offer(declaration["id"])
            expected_agency = agreed["offeror_agency_id"] if agreed is not None else None
            if counterparty_agency is None or counterparty_agency["id"] != expected_agency:
                fail("ERR_NEGOTIATED_BUYER_REQUIRED",
                     "The counterparty must be the agency whose preference offer was AGREED.")
    elif offering_type == "EXCHANGE":
        if counterparty_agency is None or counterparty_bidder is not None:
            fail("ERR_EXCHANGE_COUNTERPARTY_REQUIRED",
                 "An exchange supplies counterparty_agency_id and no bidder leg.")

    variant = calc.offering_price_variant(declaration, offering_type)
    minimum_price = calc.minimum_price(parcel, declaration, variant)
    row = db.insert("offerings", {
        "declaration_id": declaration["id"],
        "offering_type": offering_type,
        "counterparty_bidder_id": counterparty_bidder["id"] if counterparty_bidder else None,
        "counterparty_agency_id": counterparty_agency["id"] if counterparty_agency else None,
        "bid_open_at": open_at,
        "bid_close_at": close_at,
        "minimum_price_cents": minimum_price,
        "minimum_price_variant": variant,
        "required_deposit_cents": calc.required_bid_deposit(minimum_price),
        "status": "DRAFT",
        "winning_bid_amount_cents": None,
        "awarded_at": None,
        "awarded_by_user_id": None,
        "rescind_count": 0,
        "cancellation_reason": None,
    })
    db.set_raw(row, "bid_open_at", open_raw)
    db.set_raw(row, "bid_close_at", close_raw)
    db.touch(declaration)
    return response.object_response(derive.offering_out(row), 201)


@bp.get("/offerings/<row_id>")
@authorize(*READ_ROLES)
def get_offering(row_id):
    row = lookup.must("offerings", row_id)
    return response.object_response(derive.offering_out(row))


@bp.get("/offerings")
@authorize(*READ_ROLES)
def list_offerings():
    limit, offset = listing.bounds()
    declaration_id = shape.query_str("declaration_id")
    bidder_id = shape.query_str("counterparty_bidder_id")
    agency_id = shape.query_str("counterparty_agency_id")
    offering_type = shape.query_enum("offering_type", OFFERING_TYPES)
    status = shape.query_enum("status", OFFERING_STATUSES)
    variant = shape.query_enum("minimum_price_variant", PRICE_VARIANTS)
    rows = db.all_rows("offerings")
    if declaration_id is not None:
        rows = [r for r in rows if r["declaration_id"] == declaration_id]
    if bidder_id is not None:
        rows = [r for r in rows if r.get("counterparty_bidder_id") == bidder_id]
    if agency_id is not None:
        rows = [r for r in rows if r.get("counterparty_agency_id") == agency_id]
    if offering_type is not None:
        rows = [r for r in rows if r["offering_type"] == offering_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if variant is not None:
        rows = [r for r in rows if r["minimum_price_variant"] == variant]
    return listing.respond(rows, derive.offering_out, limit, offset, listing.by_created_at)


@bp.post("/offerings/<row_id>/publish")
@authorize(RPO)
def publish_offering(row_id):
    row = lookup.must("offerings", row_id)
    if row["status"] != "DRAFT" or clockmod.now() >= row["bid_close_at"]:
        fail("ERR_INVALID_OFFERING_STATE",
             "Publication requires a DRAFT offering whose window has not run out.")
    row["status"] = "OPEN"
    db.touch(row)
    return response.object_response(derive.offering_out(row))


# --------------------------------------------------------------------------
# Sealed bids (PRD 3.8)
# --------------------------------------------------------------------------

@bp.post("/offerings/<row_id>/bids")
@authorize(BIDDER)
def submit_bid(row_id):
    payload = shape.body()
    amount = shape.req_cents(payload, "amount_cents")
    deposit = shape.req_cents(payload, "deposit_amount_cents")
    intended_use = shape.opt_str(payload, "intended_use", 1)
    offering = lookup.must("offerings", row_id)
    bidder = g.actor

    _offering_state(offering, "OPEN")
    if offering["offering_type"] != "COMPETITIVE_SALE":
        fail("ERR_COMPETITIVE_BID_NOT_ALLOWED",
             "A %s never receives bids." % offering["offering_type"])
    now = clockmod.now()
    if now < offering["bid_open_at"] or now >= offering["bid_close_at"]:
        fail("ERR_BIDDING_CLOSED", "The bidding window is not live.")
    if bidder["debarment_status"] != "CLEAR":
        fail("ERR_BIDDER_DEBARRED", "A debarred bidder may not bid.")
    for other in db.all_rows("bids"):
        if (other["offering_id"] == offering["id"] and other["bidder_id"] == bidder["id"]
                and other["qualification_status"] in derive.LIVE_BID_STATUSES):
            fail("ERR_DUPLICATE_BID", "This bidder already holds a live bid on the offering.")
    if amount < offering["minimum_price_cents"]:
        fail("ERR_BID_BELOW_MINIMUM",
             "amount_cents must be at least %d." % offering["minimum_price_cents"])
    if deposit < offering["required_deposit_cents"]:
        fail("ERR_DEPOSIT_INSUFFICIENT",
             "deposit_amount_cents must be at least %d." % offering["required_deposit_cents"])
    if bidder["available_funds_cents"] < deposit:
        fail("ERR_INSUFFICIENT_BIDDER_FUNDS",
             "The bidder's available funds do not cover the deposit.")

    row = db.insert("bids", {
        "offering_id": offering["id"],
        "bidder_id": bidder["id"],
        "amount_cents": amount,
        "deposit_amount_cents": deposit,
        "intended_use": intended_use,
        "submitted_at": now,
        "qualification_status": "SUBMITTED",
        "deposit_status": "HELD",
        "award_rank": None,
        "disqualification_reason": None,
    })
    calc.hold_deposit(bidder, deposit)
    return response.object_response(derive.bid_out(row), 201)


@bp.get("/bids/<row_id>")
@authorize(*BID_READ_ROLES)
def get_bid(row_id):
    row = lookup.must("bids", row_id)
    return response.object_response(derive.bid_out(row))


@bp.get("/bids")
@authorize(*BID_READ_ROLES)
def list_bids():
    limit, offset = listing.bounds()
    offering_id = shape.query_str("offering_id")
    bidder_id = shape.query_str("bidder_id")
    qualification_status = shape.query_enum("qualification_status", QUALIFICATION_STATUSES)
    deposit_status = shape.query_enum("deposit_status", DEPOSIT_STATUSES)
    rows = db.all_rows("bids")
    if offering_id is not None:
        rows = [r for r in rows if r["offering_id"] == offering_id]
    if bidder_id is not None:
        rows = [r for r in rows if r["bidder_id"] == bidder_id]
    if qualification_status is not None:
        rows = [r for r in rows if r["qualification_status"] == qualification_status]
    if deposit_status is not None:
        rows = [r for r in rows if r["deposit_status"] == deposit_status]
    return listing.respond(rows, derive.bid_out, limit, offset, listing.by_created_at)


@bp.post("/bids/<row_id>/withdraw")
@authorize(BIDDER)
def withdraw_bid(row_id):
    row = lookup.must("bids", row_id)
    if row["bidder_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "A bidder may withdraw only its own bid.")
    if row["qualification_status"] != "SUBMITTED" or row["deposit_status"] != "HELD":
        fail("ERR_INVALID_BID_STATE",
             "Withdrawal requires a SUBMITTED bid whose deposit is still HELD.")
    offering = db.get("offerings", row["offering_id"])
    if offering is not None and clockmod.now() >= offering["bid_close_at"]:
        fail("ERR_BIDDING_CLOSED", "Bidding has closed on this offering.")
    row["qualification_status"] = "WITHDRAWN"
    calc.release_bid_deposit(row)
    db.touch(row)
    return response.object_response(derive.bid_out(row))


# --------------------------------------------------------------------------
# Grading, award and rescission (PRD 3.8, 3.9)
# --------------------------------------------------------------------------

@bp.post("/offerings/<row_id>/close-bidding")
@authorize(RPO)
def close_bidding(row_id):
    row = lookup.must("offerings", row_id)
    if row["status"] != "OPEN" or row["offering_type"] != "COMPETITIVE_SALE":
        fail("ERR_INVALID_OFFERING_STATE",
             "Closing bidding requires an OPEN competitive sale.")
    if clockmod.now() < row["bid_close_at"]:
        fail("ERR_BIDDING_STILL_OPEN", "The bidding window is still live.")

    qualified = 0
    for bid in db.all_rows("bids"):
        if bid["offering_id"] != row["id"] or bid["qualification_status"] != "SUBMITTED":
            continue
        bidder = db.get("bidders", bid["bidder_id"])
        if bidder is not None and bidder["debarment_status"] == "DEBARRED":
            bid["qualification_status"] = "DISQUALIFIED"
            bid["disqualification_reason"] = "bidder debarred"
            calc.release_bid_deposit(bid)
        else:
            bid["qualification_status"] = "QUALIFIED"
            qualified += 1
        db.touch(bid)

    if qualified == 0:
        cascade.unsuccessful_cascade(row)
        return response.object_response(derive.offering_out(row))
    row["status"] = "EVALUATION"
    db.touch(row)
    return response.object_response(derive.offering_out(row))


@bp.post("/offerings/<row_id>/award")
@authorize(CLERK)
def award_offering(row_id):
    row = lookup.must("offerings", row_id)
    if row["rescind_count"] > 0 and row.get("awarded_by_user_id") == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The clerk whose award was rescinded may not award this offering again.")

    if row["offering_type"] == "COMPETITIVE_SALE":
        _offering_state(row, "EVALUATION")
        candidates = calc.award_candidates(row)
        if not candidates:
            fail("ERR_NO_QUALIFYING_BID", "No bid survives the award eligibility filter.")
        for index, bid in enumerate(candidates):
            bid["award_rank"] = index + 1
            bid["qualification_status"] = "WINNING" if index == 0 else "BACKUP"
            db.touch(bid)
        row["winning_bid_amount_cents"] = candidates[0]["amount_cents"]
    else:
        _offering_state(row, "OPEN")
        declaration = db.get("declarations", row["declaration_id"])
        agreed = calc.agreed_ah_offer(declaration["id"]) if declaration is not None else None
        if agreed is not None and agreed.get("agreed_price_cents") is not None:
            row["winning_bid_amount_cents"] = agreed["agreed_price_cents"]
        else:
            row["winning_bid_amount_cents"] = row["minimum_price_cents"]

    row["awarded_at"] = clockmod.now()
    row["awarded_by_user_id"] = g.user_id
    row["status"] = "AWARDED"
    db.touch(row)
    return response.object_response(derive.offering_out(row))


@bp.post("/offerings/<row_id>/rescind-award")
@authorize(CLERK)
def rescind_award(row_id):
    payload = shape.body()
    reason = shape.req_str(payload, "cancellation_reason", 1)
    row = lookup.must("offerings", row_id)
    _offering_state(row, "AWARDED")
    for conveyance in cascade.offering_conveyances(row["id"]):
        if conveyance["recording_status"] == "RECORDED":
            fail("ERR_INVALID_CONVEYANCE_STATE",
                 "A recorded conveyance cannot be unwound by rescinding the award.")

    if row["offering_type"] == "COMPETITIVE_SALE":
        for bid in db.all_rows("bids"):
            if bid["offering_id"] != row["id"]:
                continue
            if bid["qualification_status"] == "WINNING":
                bid["qualification_status"] = "DISQUALIFIED"
                bid["disqualification_reason"] = reason
                bid["award_rank"] = None
                calc.release_bid_deposit(bid)
                db.touch(bid)
            elif bid["qualification_status"] == "BACKUP":
                bid["qualification_status"] = "QUALIFIED"
                bid["award_rank"] = None
                db.touch(bid)
        row["winning_bid_amount_cents"] = None
        row["rescind_count"] += 1
        row["status"] = "EVALUATION"
    else:
        row["cancellation_reason"] = reason
        row["status"] = "CANCELLED"
    db.touch(row)
    cascade.rescind_conveyances(row)
    return response.object_response(derive.offering_out(row))
