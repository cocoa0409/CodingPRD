"""The sale floor and the proceeds waterfall (PRD sections 3.6, 3.7)."""

from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from errors import ApiError
from services import calc, domain

bp = Blueprint("lots", __name__)

LOT_STATUSES = {"LISTED", "SOLD", "NO_SALE", "VOIDED", "WITHDRAWN"}
READ_ROLES = ("AuctionManager", "ProgramAdmin", "FinanceOfficer")


def _same_day_lot_count(venue_id):
    today = db.now().date()
    count = 0
    for lot in db.auction_lots.values():
        if lot["venue_id"] != venue_id or lot["status"] == "WITHDRAWN":
            continue
        listed = lot.get("listed_at_utc")
        if listed is not None and listed.date() == today:
            count += 1
    return count


def _require_venue_capacity(venue_id):
    if _same_day_lot_count(venue_id) >= db.VENUE_DAILY_LOT_CAPACITY:
        raise ApiError(
            "ERR_VENUE_CAPACITY_EXCEEDED", "This venue is at its daily lot capacity."
        )


@bp.post("/api/auction-lots")
def create_lot():
    mw.auth("AuctionManager")
    data = mw.body()
    donation_id = mw.req_string(data, "donation_id")
    venue_id = mw.req_string(data, "venue_id")
    lot_number = mw.req_string(data, "lot_number")
    reserve = mw.req_int(data, "reserve_price_cents", minimum=0)

    donation = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")
    venue = mw.resolve(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")

    if donation["status"] != "IN_CUSTODY":
        raise ApiError(
            "ERR_INVALID_DONATION_STATE", "Only a donation in custody may be listed."
        )
    if venue["status"] != "ACTIVE":
        raise ApiError("ERR_VENUE_SUSPENDED", "This sales venue is suspended.")
    _require_venue_capacity(venue_id)

    rec = db.new_record()
    rec["donation_id"] = donation_id
    rec["venue_id"] = venue_id
    rec["lot_number"] = lot_number
    rec["reserve_price_cents"] = reserve
    rec["status"] = "LISTED"
    rec["listed_at_utc"] = db.now()
    rec["sale_price_cents"] = None
    rec["sold_at_utc"] = None
    rec["relist_count"] = 0
    rec["void_reason"] = None
    db.auction_lots[rec["id"]] = rec
    return resp.created(rec)


@bp.get("/api/auction-lots/<lot_id>")
def get_lot(lot_id):
    mw.auth(*READ_ROLES)
    rec = mw.resolve(db.auction_lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
    return resp.ok(rec)


@bp.get("/api/auction-lots")
def list_lots():
    mw.auth(*READ_ROLES)
    donation_filter = request.args.get("donation_id")
    venue_filter = request.args.get("venue_id")
    status = mw.query_enum("status", LOT_STATUSES)
    limit, offset = mw.pagination()
    rows = []
    for rec in db.auction_lots.values():
        if donation_filter is not None and rec["donation_id"] != donation_filter:
            continue
        if venue_filter is not None and rec["venue_id"] != venue_filter:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    return resp.listing(db.ordered(rows), limit, offset)


@bp.post("/api/auction-lots/<lot_id>/record-sale")
def record_sale(lot_id):
    mw.auth("AuctionManager")
    rec = mw.resolve(db.auction_lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = mw.body()
    sale_price = mw.req_int(data, "sale_price_cents", minimum=0)
    expected_version = mw.req_int(data, "expected_donation_version")

    donation = db.donations.get(rec["donation_id"])
    if donation is None:
        raise ApiError("ERR_DONATION_NOT_FOUND", "The lot's donation is missing.")
    if expected_version != donation["version"]:
        raise ApiError(
            "ERR_STALE_DONATION_VERSION", "The donation has advanced since it was read."
        )
    if rec["status"] != "LISTED":
        raise ApiError("ERR_INVALID_LOT_STATE", "Only a listed lot may record a sale.")
    if donation["status"] != "IN_CUSTODY":
        raise ApiError("ERR_INVALID_DONATION_STATE", "The donation is not in custody.")

    venue = db.venues.get(rec["venue_id"])
    if venue is not None and venue["status"] != "ACTIVE":
        raise ApiError("ERR_VENUE_SUSPENDED", "This sales venue is suspended.")

    title = domain.title_for_donation(donation["id"])
    if title is None or title["state"] != "CLEARED":
        raise ApiError("ERR_TITLE_NOT_CLEARED", "The donation's title is not cleared.")

    if sale_price < rec["reserve_price_cents"]:
        raise ApiError("ERR_RESERVE_NOT_MET", "The hammer price is below the reserve.")

    rec["status"] = "SOLD"
    rec["sale_price_cents"] = sale_price
    rec["sold_at_utc"] = db.now()
    db.touch(rec)

    completed = domain.completed_pickup(donation["id"])
    billed = completed["actual_tow_cost_cents"] if completed else 0
    figures = calc.donation_net_proceeds(sale_price, billed)
    donation.update(figures)
    donation["status"] = "SOLD"

    accrue = donation["net_to_charity_cents"] > 0
    if accrue:
        donation["payout_status"] = "ACCRUED"
    db.touch(donation)

    if accrue:
        charity = db.charities.get(donation["charity_id"])
        if charity is not None:
            domain.accrue_proceeds(donation, charity)
    return resp.ok(rec)


@bp.post("/api/auction-lots/<lot_id>/record-no-sale")
def record_no_sale(lot_id):
    mw.auth("AuctionManager")
    rec = mw.resolve(db.auction_lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = mw.body()
    mw.opt_string(data, "reason", None)

    if rec["status"] != "LISTED":
        raise ApiError("ERR_INVALID_LOT_STATE", "Only a listed lot may record a no-sale.")
    donation = db.donations.get(rec["donation_id"])
    if donation is None or donation["status"] != "IN_CUSTODY":
        raise ApiError("ERR_INVALID_DONATION_STATE", "The donation is not in custody.")

    rec["status"] = "NO_SALE"
    db.touch(rec)
    donation["status"] = "UNSOLD"
    db.touch(donation)
    return resp.ok(rec)


@bp.post("/api/auction-lots/<lot_id>/relist")
def relist_lot(lot_id):
    mw.auth("AuctionManager")
    rec = mw.resolve(db.auction_lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = mw.body()
    reserve = mw.req_int(data, "reserve_price_cents", minimum=0)

    if rec["status"] not in ("NO_SALE", "VOIDED"):
        raise ApiError("ERR_INVALID_LOT_STATE", "Only an unsold or voided lot may relist.")
    donation = db.donations.get(rec["donation_id"])
    if donation is None or donation["status"] != "UNSOLD":
        raise ApiError("ERR_INVALID_DONATION_STATE", "The donation is not unsold.")

    venue = db.venues.get(rec["venue_id"])
    if venue is not None and venue["status"] != "ACTIVE":
        raise ApiError("ERR_VENUE_SUSPENDED", "This sales venue is suspended.")
    _require_venue_capacity(rec["venue_id"])

    rec["status"] = "LISTED"
    rec["reserve_price_cents"] = reserve
    rec["listed_at_utc"] = db.now()
    rec["relist_count"] += 1
    db.touch(rec)

    donation["status"] = "IN_CUSTODY"
    db.touch(donation)
    return resp.ok(rec)


@bp.post("/api/auction-lots/<lot_id>/void-sale")
def void_sale(lot_id):
    mw.auth("AuctionManager")
    rec = mw.resolve(db.auction_lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = mw.body()
    void_reason = mw.req_string(data, "void_reason")

    if rec["status"] != "SOLD":
        raise ApiError("ERR_INVALID_LOT_STATE", "Only a sold lot may be voided.")
    donation = db.donations.get(rec["donation_id"])
    if donation is None or donation["status"] != "SOLD":
        raise ApiError("ERR_INVALID_DONATION_STATE", "The donation is not in the sold state.")
    if donation["payout_status"] != "ACCRUED":
        raise ApiError("ERR_INVALID_PAYOUT_STATE", "The donation has no live accrual.")
    if domain.is_settled(donation["id"]):
        raise ApiError(
            "ERR_DONATION_SETTLED", "This donation is frozen into a settled batch."
        )

    rec["status"] = "VOIDED"
    rec["void_reason"] = void_reason
    rec["sale_price_cents"] = None
    rec["sold_at_utc"] = None
    db.touch(rec)

    charity = db.charities.get(donation["charity_id"])
    if charity is not None:
        domain.reverse_accrual(donation, charity, "sale voided")

    donation["gross_proceeds_cents"] = 0
    donation["program_fee_cents"] = 0
    donation["tow_allowance_cents"] = 0
    donation["net_to_charity_cents"] = 0
    donation["payout_status"] = "PENDING"
    donation["status"] = "UNSOLD"
    db.touch(donation)
    return resp.ok(rec)


@bp.post("/api/auction-lots/<lot_id>/withdraw")
def withdraw_lot(lot_id):
    mw.auth("AuctionManager")
    rec = mw.resolve(db.auction_lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = mw.body()
    mw.req_string(data, "reason")

    if rec["status"] not in ("LISTED", "NO_SALE"):
        raise ApiError("ERR_INVALID_LOT_STATE", "This lot may not be withdrawn.")

    was_listed = rec["status"] == "LISTED"
    rec["status"] = "WITHDRAWN"
    db.touch(rec)

    if was_listed:
        donation = db.donations.get(rec["donation_id"])
        if donation is not None and donation["status"] == "IN_CUSTODY":
            donation["status"] = "UNSOLD"
            db.touch(donation)
    return resp.ok(rec)
