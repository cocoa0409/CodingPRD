"""Tax Lien Certificate API — Flask entry point.

Implements the PRD end to end: county config, parcels, investors/escrow, sales,
listings, bids, the close award cascade, certificates, subsequent taxes,
redemption, assignment, deed application/award/cancel, and surplus distribution.

Storage is in-memory only (db.py) and starts empty on every boot. The logical
clock (clock.py) is the sole source of business "now".
"""
import os

from flask import Flask, request

import calculations as calc
import clock
import db
import services as svc
from auth import get_caller, require_role
from errors import (
    ApiError,
    ERR_BID_BELOW_MINIMUM,
    ERR_CROSS_COUNTY_REFERENCE,
    ERR_DEED_ALREADY_AWARDED,
    ERR_DUPLICATE_SUB_TAX,
    ERR_INSUFFICIENT_ESCROW,
    ERR_INVALID_BID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_CERTIFICATE_HOLDER,
    ERR_NOT_FOUND,
    ERR_REDEMPTION_PERIOD_OPEN,
    ERR_SALE_EMPTY,
    ERR_SALE_NOT_DUE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
    fail,
)
from helpers import (
    get_body,
    new_record,
    opt_bool,
    paginate,
    require_fields,
    require_int,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from response import error_response, success_array, success_object

app = Flask(__name__)
app.url_map.strict_slashes = False

ALL_ROLES = ("CountyTreasurer", "Investor", "Auditor")


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_uncaught(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return error_response("ERR_INVALID_REQUEST", str(exc), 400)


# ===========================================================================
# Lookup helpers (left-to-right existence — PRD §2.9)
# ===========================================================================
def get_county(county_id):
    c = db.counties.get(county_id)
    if c is None:
        fail(ERR_NOT_FOUND, "County not found")
    return c


def get_in(collection, _id, label):
    rec = collection.get(_id)
    if rec is None:
        fail(ERR_NOT_FOUND, "%s not found" % label)
    return rec


def get_parcel_scoped(county_id, parcel_id):
    p = get_in(db.parcels, parcel_id, "Parcel")
    if p["county_id"] != county_id:
        fail(ERR_NOT_FOUND, "Parcel not found")
    return p


def get_sale_scoped(county_id, sale_id):
    s = get_in(db.sales, sale_id, "Sale")
    if s["county_id"] != county_id:
        fail(ERR_NOT_FOUND, "Sale not found")
    return s


def get_listing_scoped(sale_id, listing_id):
    l = get_in(db.listings, listing_id, "Listing")
    if l["sale_id"] != sale_id:
        fail(ERR_NOT_FOUND, "Listing not found")
    return l


def get_bid_scoped(listing_id, bid_id):
    b = get_in(db.bids, bid_id, "Bid")
    if b["listing_id"] != listing_id:
        fail(ERR_NOT_FOUND, "Bid not found")
    return b


def get_certificate_scoped(county_id, certificate_id):
    cert = get_in(db.certificates, certificate_id, "Certificate")
    if cert["county_id"] != county_id:
        fail(ERR_NOT_FOUND, "Certificate not found")
    return cert


def get_deed_scoped(county_id, deed_id):
    deed = get_in(db.deed_applications, deed_id, "Deed application")
    cert = db.certificates.get(deed["certificate_id"])
    if cert is None or cert["county_id"] != county_id:
        fail(ERR_NOT_FOUND, "Deed application not found")
    return deed


# ===========================================================================
# OCC helper (PRD §2.7 / §2.10 priority 6)
# ===========================================================================
def check_occ(body, field, parent):
    """expected_<parent>_version must be present (priority 5) and match (priority 6)."""
    if field not in body or body[field] is None:
        fail(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        fail(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if val != parent["version"]:
        fail(ERR_STALE_VERSION, "Stale %s" % field)


# ===========================================================================
# Generic list serialization
# ===========================================================================
def list_response(records, code=200):
    ordered = sort_by_created(records)
    page, pagination = paginate(ordered)
    return success_array([serialize(r) for r in page], pagination, code)


def filter_eq(records, field, value):
    if value is None:
        return records
    return [r for r in records if str(r.get(field)) == str(value)]


# ===========================================================================
# Clock (test-driving) — PRD §2.4
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        new_dt = clock.set_current(body["to_iso8601"])
    except Exception:
        fail(ERR_INVALID_REQUEST, "Invalid to_iso8601")
    return success_object({"current_utc": clock.format_iso(new_dt)}, 200)


# ===========================================================================
# County — PRD §3.1
# ===========================================================================
@app.route("/counties", methods=["POST"])
def create_county():
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    body = get_body()
    require_fields(body, [
        "name", "state_code", "max_interest_rate_bps", "bid_down_increment_bps",
        "redemption_period_days", "sub_tax_interest_rate_bps",
    ])
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    max_rate = require_int(body, "max_interest_rate_bps", minimum=None)
    bid_down = require_int(body, "bid_down_increment_bps", minimum=None)
    redemption_days = require_int(body, "redemption_period_days", minimum=None)
    sub_tax_rate = require_int(body, "sub_tax_interest_rate_bps", minimum=None)
    penalty_rate = require_int(body, "penalty_rate_bps", minimum=None) if body.get("penalty_rate_bps") is not None else 0
    premium_enabled = opt_bool(body, "premium_bidding_enabled", False)
    premium_earns = opt_bool(body, "premium_earns_interest", False)
    day_count = body.get("day_count_basis")
    if day_count is None:
        day_count = 365
    else:
        day_count = require_int(body, "day_count_basis", minimum=None)

    # Semantic constraints (PRD §3.1).
    if not (1 <= max_rate <= 5000):
        fail(ERR_VALIDATION, "max_interest_rate_bps must be 1..5000")
    if bid_down < 1:
        fail(ERR_VALIDATION, "bid_down_increment_bps must be >= 1")
    if max_rate % bid_down != 0:
        fail(ERR_VALIDATION, "max_interest_rate_bps must be a multiple of bid_down_increment_bps")
    if redemption_days < 1:
        fail(ERR_VALIDATION, "redemption_period_days must be >= 1")
    if penalty_rate < 0:
        fail(ERR_VALIDATION, "penalty_rate_bps must be >= 0")
    if not (1 <= sub_tax_rate <= 5000):
        fail(ERR_VALIDATION, "sub_tax_interest_rate_bps must be 1..5000")
    if day_count not in (360, 365):
        fail(ERR_VALIDATION, "day_count_basis must be 360 or 365")

    rec = new_record({
        "name": name,
        "state_code": state_code,
        "max_interest_rate_bps": max_rate,
        "bid_down_increment_bps": bid_down,
        "redemption_period_days": redemption_days,
        "penalty_rate_bps": penalty_rate,
        "sub_tax_interest_rate_bps": sub_tax_rate,
        "premium_bidding_enabled": premium_enabled,
        "premium_earns_interest": premium_earns,
        "day_count_basis": day_count,
    })
    db.counties[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/counties/<county_id>", methods=["GET"])
def get_county_ep(county_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_county(county_id)), 200)


# ===========================================================================
# Parcel — PRD §3.1
# ===========================================================================
@app.route("/counties/<county_id>/parcels", methods=["POST"])
def create_parcel(county_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    county = get_county(county_id)
    body = get_body()
    require_fields(body, ["apn", "owner_name", "assessed_value_cents", "base_tax_due_cents"])
    apn = require_str(body, "apn")
    owner_name = require_str(body, "owner_name")
    assessed = require_int(body, "assessed_value_cents", minimum=None)
    base_tax = require_int(body, "base_tax_due_cents", minimum=None)
    if assessed < 0:
        fail(ERR_VALIDATION, "assessed_value_cents must be >= 0")
    if base_tax < 1:
        fail(ERR_VALIDATION, "base_tax_due_cents must be >= 1")

    rec = new_record({
        "county_id": county_id,
        "apn": apn,
        "owner_name": owner_name,
        "assessed_value_cents": assessed,
        "base_tax_due_cents": base_tax,
        "status": "DELINQUENT",
        "active_certificate_id": None,
    })
    db.parcels[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/counties/<county_id>/parcels/<parcel_id>", methods=["GET"])
def get_parcel_ep(county_id, parcel_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    return success_object(serialize(get_parcel_scoped(county_id, parcel_id)), 200)


@app.route("/counties/<county_id>/parcels", methods=["GET"])
def list_parcels(county_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    rows = [p for p in db.parcels.values() if p["county_id"] == county_id]
    rows = filter_eq(rows, "status", request.args.get("status"))
    if request.args.get("county_id"):
        rows = filter_eq(rows, "county_id", request.args.get("county_id"))
    return list_response(rows)


# ===========================================================================
# Investor — PRD §3.2
# ===========================================================================
@app.route("/investors", methods=["POST"])
def create_investor():
    _, role = get_caller()
    require_role(role, ("Investor", "CountyTreasurer"))
    body = get_body()
    require_fields(body, ["legal_name", "tax_id"])
    legal_name = require_str(body, "legal_name")
    tax_id = require_str(body, "tax_id")
    rec = new_record({
        "legal_name": legal_name,
        "tax_id": tax_id,
        "escrow_balance_cents": 0,
        "deposit_total_cents": 0,
        "registered": False,
    })
    db.investors[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/investors/<investor_id>", methods=["GET"])
def get_investor_ep(investor_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_in(db.investors, investor_id, "Investor")), 200)


@app.route("/investors/<investor_id>/deposits", methods=["POST"])
def create_deposit(investor_id):
    _, role = get_caller()
    require_role(role, ("Investor", "CountyTreasurer"))
    investor = get_in(db.investors, investor_id, "Investor")
    body = get_body()
    require_fields(body, ["amount_cents"])
    amount = require_int(body, "amount_cents", minimum=None)
    if amount < 1:
        fail(ERR_VALIDATION, "amount_cents must be >= 1")
    investor["escrow_balance_cents"] += amount
    investor["deposit_total_cents"] += amount
    investor["registered"] = True
    touch(investor)
    return success_object(serialize(investor), 201)


# ===========================================================================
# TaxSale — PRD §3.3
# ===========================================================================
@app.route("/counties/<county_id>/sales", methods=["POST"])
def create_sale(county_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    county = get_county(county_id)
    body = get_body()
    require_fields(body, ["sale_name", "scheduled_at"])
    sale_name = require_str(body, "sale_name")
    scheduled_raw = body["scheduled_at"]
    try:
        scheduled_dt = clock.parse_iso(scheduled_raw)
    except Exception:
        fail(ERR_INVALID_REQUEST, "Invalid scheduled_at")

    sale_type = "PREMIUM" if county["premium_bidding_enabled"] else "RATE_BID_DOWN"
    rec = new_record({
        "county_id": county_id,
        "sale_name": sale_name,
        "sale_type": sale_type,
        "scheduled_at": clock.format_iso(scheduled_dt),
        "scheduled_at_dt": scheduled_dt,
        "status": "DRAFT",
        "listing_count": 0,
    })
    db.sales[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@app.route("/counties/<county_id>/sales/<sale_id>", methods=["GET"])
def get_sale_ep(county_id, sale_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    return success_object(serialize(get_sale_scoped(county_id, sale_id)), 200)


@app.route("/counties/<county_id>/sales", methods=["GET"])
def list_sales(county_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    rows = [s for s in db.sales.values() if s["county_id"] == county_id]
    rows = filter_eq(rows, "status", request.args.get("status"))
    return list_response(rows)


@app.route("/counties/<county_id>/sales/<sale_id>/open", methods=["POST"])
def open_sale(county_id, sale_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    get_county(county_id)
    sale = get_sale_scoped(county_id, sale_id)
    if sale["status"] != "DRAFT":
        fail(ERR_INVALID_STATE, "Sale is not DRAFT")
    if clock.now() < sale["scheduled_at_dt"]:
        fail(ERR_SALE_NOT_DUE, "Sale not yet due")
    if sale["listing_count"] < 1:
        fail(ERR_SALE_EMPTY, "Sale has no listings")
    sale["status"] = "OPEN"
    touch(sale)
    return success_object(serialize(sale), 200)


@app.route("/counties/<county_id>/sales/<sale_id>/close", methods=["POST"])
def close_sale(county_id, sale_id):
    user_id, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    county = get_county(county_id)
    sale = get_sale_scoped(county_id, sale_id)
    if sale["status"] != "OPEN":
        fail(ERR_INVALID_STATE, "Sale is not OPEN")

    # Segregation of duties (PRD §2.11 / §3.5): the treasurer running the close
    # must not be acting as the X-User-ID of any winning bidder. Pre-compute the
    # winners before committing.
    winners = _projected_winners(county, sale)
    for bid in winners:
        if bid["investor_id"] == user_id:
            fail(ERR_SEGREGATION_OF_DUTIES,
                 "Treasurer may not award a sale containing their own winning bid")

    svc.run_close_cascade(county, sale)
    sale["status"] = "CLOSED"
    touch(sale)
    return success_object(serialize(sale), 200)


def _projected_winners(county, sale):
    """Winners that the close cascade would select, without mutating state."""
    winners = []
    listings = [l for l in db.listings.values()
                if l["sale_id"] == sale["id"] and l["status"] == "LISTED"]
    for listing in listings:
        placed = [b for b in db.bids.values()
                  if b["listing_id"] == listing["id"] and b["status"] == "PLACED"]
        if not placed:
            continue
        if sale["sale_type"] == "RATE_BID_DOWN":
            winner = min(placed, key=lambda b: (b["rate_bps"], b["_seq"]))
        else:
            winner = max(placed, key=lambda b: (b["premium_cents"], -b["_seq"]))
        winners.append(winner)
    return winners


@app.route("/counties/<county_id>/sales/<sale_id>/settle", methods=["POST"])
def settle_sale(county_id, sale_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    get_county(county_id)
    sale = get_sale_scoped(county_id, sale_id)
    if sale["status"] != "CLOSED":
        fail(ERR_INVALID_STATE, "Sale is not CLOSED")
    sale["status"] = "SETTLED"
    touch(sale)
    return success_object(serialize(sale), 200)


# ===========================================================================
# SaleListing — PRD §3.3
# ===========================================================================
@app.route("/counties/<county_id>/sales/<sale_id>/listings", methods=["POST"])
def create_listing(county_id, sale_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    county = get_county(county_id)
    sale = get_sale_scoped(county_id, sale_id)
    body = get_body()
    require_fields(body, ["parcel_id"])
    parcel_id = body["parcel_id"]
    if not isinstance(parcel_id, str):
        fail(ERR_INVALID_REQUEST, "parcel_id must be a string")

    # Cross-county referential integrity (PRD §2.9, priority 4).
    parcel = db.parcels.get(parcel_id)
    if parcel is None or parcel["county_id"] != county_id:
        fail(ERR_CROSS_COUNTY_REFERENCE, "Parcel not in this county")

    # State (PRD §3.3, priority 7): a listing attaches a *delinquent* parcel and
    # "moves the referenced parcel from DELINQUENT to ON_SALE". A parcel that is
    # not DELINQUENT (e.g. already ON_SALE) has no defined transition here, so the
    # attach is rejected with ERR_INVALID_STATE (PRD §2.10).
    if parcel["status"] != "DELINQUENT":
        fail(ERR_INVALID_STATE, "Parcel is not DELINQUENT")

    rec = new_record({
        "sale_id": sale_id,
        "parcel_id": parcel_id,
        "opening_rate_bps": county["max_interest_rate_bps"],
        "status": "LISTED",
        "winning_bid_id": None,
        "certificate_id": None,
    })
    db.listings[rec["id"]] = rec

    parcel["status"] = "ON_SALE"
    touch(parcel)
    sale["listing_count"] += 1
    touch(sale)
    return success_object(serialize(rec), 201)


@app.route("/counties/<county_id>/sales/<sale_id>/listings/<listing_id>", methods=["GET"])
def get_listing_ep(county_id, sale_id, listing_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    get_sale_scoped(county_id, sale_id)
    return success_object(serialize(get_listing_scoped(sale_id, listing_id)), 200)


@app.route("/counties/<county_id>/sales/<sale_id>/listings", methods=["GET"])
def list_listings(county_id, sale_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    get_sale_scoped(county_id, sale_id)
    rows = [l for l in db.listings.values() if l["sale_id"] == sale_id]
    rows = filter_eq(rows, "parcel_id", request.args.get("parcel_id"))
    rows = filter_eq(rows, "status", request.args.get("status"))
    return list_response(rows)


@app.route("/counties/<county_id>/sales/<sale_id>/listings/<listing_id>/withdraw", methods=["POST"])
def withdraw_listing_ep(county_id, sale_id, listing_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    get_county(county_id)
    sale = get_sale_scoped(county_id, sale_id)
    listing = get_listing_scoped(sale_id, listing_id)
    if listing["status"] != "LISTED" or sale["status"] not in ("DRAFT", "OPEN"):
        fail(ERR_INVALID_STATE, "Listing cannot be withdrawn")
    svc.withdraw_listing(listing)
    return success_object(serialize(listing), 200)


# ===========================================================================
# Bid — PRD §3.4
# ===========================================================================
@app.route("/counties/<county_id>/sales/<sale_id>/listings/<listing_id>/bids", methods=["POST"])
def place_bid(county_id, sale_id, listing_id):
    user_id, role = get_caller()
    require_role(role, ("Investor",))
    county = get_county(county_id)
    sale = get_sale_scoped(county_id, sale_id)
    listing = get_listing_scoped(sale_id, listing_id)
    body = get_body()

    # Cross-county referential integrity (priority 4): investor must exist.
    investor_id = body.get("investor_id")
    if investor_id is None:
        fail(ERR_INVALID_REQUEST, "Missing required field: investor_id")
    investor = db.investors.get(investor_id)
    if investor is None:
        fail(ERR_CROSS_COUNTY_REFERENCE, "Investor not found")

    # Body shape (priority 5): OCC field must be present.
    check_occ(body, "expected_listing_version", listing)

    # State (priority 7): sale must be OPEN and listing LISTED.
    if sale["status"] != "OPEN" or listing["status"] != "LISTED":
        fail(ERR_INVALID_STATE, "Listing not open for bidding")

    # Segregation of duties (priority 8): investor identity must match caller.
    if investor_id != user_id:
        fail(ERR_SEGREGATION_OF_DUTIES, "Bidder must be the acting investor")

    parcel = db.parcels[listing["parcel_id"]]

    # Bid shape (priority 12).
    if sale["sale_type"] == "RATE_BID_DOWN":
        rate_bps = body.get("rate_bps")
        if rate_bps is None or isinstance(rate_bps, bool) or not isinstance(rate_bps, int):
            fail(ERR_INVALID_REQUEST, "rate_bps required for RATE_BID_DOWN")
        if rate_bps > listing["opening_rate_bps"] or rate_bps <= 0 \
                or rate_bps % county["bid_down_increment_bps"] != 0:
            fail(ERR_INVALID_BID, "Invalid rate_bps")
        premium_cents = 0
        hold = parcel["base_tax_due_cents"]
    else:  # PREMIUM
        premium_cents = body.get("premium_cents")
        if premium_cents is None:
            premium_cents = 0
        if isinstance(premium_cents, bool) or not isinstance(premium_cents, int):
            fail(ERR_INVALID_REQUEST, "premium_cents must be an integer")
        if premium_cents < 0:
            fail(ERR_INVALID_BID, "premium_cents must be >= 0")
        rate_bps = None
        hold = parcel["base_tax_due_cents"] + premium_cents

    # Escrow sufficiency (priority 14).
    if investor["escrow_balance_cents"] - hold < 0:
        fail(ERR_INSUFFICIENT_ESCROW, "Insufficient escrow for bid hold")

    rec = new_record({
        "listing_id": listing_id,
        "investor_id": investor_id,
        "rate_bps": rate_bps,
        "premium_cents": premium_cents,
        "status": "PLACED",
    })
    db.bids[rec["id"]] = rec

    # Hold escrow and bump the listing version.
    investor["escrow_balance_cents"] -= hold
    touch(investor)
    touch(listing)
    return success_object(serialize(rec), 201)


@app.route("/counties/<county_id>/sales/<sale_id>/listings/<listing_id>/bids/<bid_id>", methods=["GET"])
def get_bid_ep(county_id, sale_id, listing_id, bid_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    get_sale_scoped(county_id, sale_id)
    get_listing_scoped(sale_id, listing_id)
    return success_object(serialize(get_bid_scoped(listing_id, bid_id)), 200)


@app.route("/counties/<county_id>/sales/<sale_id>/listings/<listing_id>/bids", methods=["GET"])
def list_bids(county_id, sale_id, listing_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    get_sale_scoped(county_id, sale_id)
    get_listing_scoped(sale_id, listing_id)
    rows = [b for b in db.bids.values() if b["listing_id"] == listing_id]
    rows = filter_eq(rows, "investor_id", request.args.get("investor_id"))
    rows = filter_eq(rows, "status", request.args.get("status"))
    return list_response(rows)


# ===========================================================================
# Certificate — PRD §3.6
# ===========================================================================
@app.route("/counties/<county_id>/certificates/<certificate_id>", methods=["GET"])
def get_certificate_ep(county_id, certificate_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    return success_object(serialize(get_certificate_scoped(county_id, certificate_id)), 200)


@app.route("/counties/<county_id>/certificates", methods=["GET"])
def list_certificates(county_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    rows = [c for c in db.certificates.values() if c["county_id"] == county_id]
    rows = filter_eq(rows, "parcel_id", request.args.get("parcel_id"))
    rows = filter_eq(rows, "listing_id", request.args.get("listing_id"))
    rows = filter_eq(rows, "holder_investor_id", request.args.get("holder_investor_id"))
    rows = filter_eq(rows, "status", request.args.get("status"))
    return list_response(rows)


@app.route("/counties/<county_id>/certificates/<certificate_id>/payoff-quote", methods=["GET"])
def payoff_quote(county_id, certificate_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    county = get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    now = clock.now()
    posted = svc.posted_sub_taxes_for(cert["id"])
    filed_cost = 0
    if cert["status"] == "FORECLOSURE_PENDING":
        filed = _filed_deed_for(cert["id"])
        if filed is not None:
            filed_cost = filed["deed_cost_cents"]
    payoff = calc.compute_payoff(county, cert, posted, now, filed_cost)
    data = {
        "face_payoff_cents": payoff["face_payoff_cents"],
        "face_interest_cents": payoff["face_interest_cents"],
        "penalty_cents": payoff["penalty_cents"],
        "sub_tax_payoff_cents": payoff["sub_tax_payoff_cents"],
        "sub_tax_interest_cents": payoff["sub_tax_interest_cents"],
        "premium_refund_cents": payoff["premium_refund_cents"],
        "total_payoff_cents": payoff["total_payoff_cents"],
        "as_of": clock.format_iso(now),
    }
    return success_object(data, 200)


def _filed_deed_for(certificate_id):
    rows = [d for d in db.deed_applications.values()
            if d["certificate_id"] == certificate_id and d["status"] == "FILED"]
    rows.sort(key=lambda d: d["_seq"])
    return rows[-1] if rows else None


@app.route("/counties/<county_id>/certificates/<certificate_id>/redeem", methods=["POST"])
def redeem_certificate(county_id, certificate_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    county = get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)

    if cert["status"] not in ("ACTIVE", "FORECLOSURE_PENDING"):
        fail(ERR_INVALID_STATE, "Certificate cannot be redeemed")

    filed_deed = None
    if cert["status"] == "FORECLOSURE_PENDING":
        filed_deed = _filed_deed_for(cert["id"])
        # If the pending deed already advanced to awarded, reject.
        if filed_deed is None:
            fail(ERR_DEED_ALREADY_AWARDED, "Deed already awarded")

    redemption = svc.process_redemption(county, cert, filed_deed)
    return success_object(serialize(redemption), 201)


# ===========================================================================
# SubsequentTax — PRD §3.7
# ===========================================================================
@app.route("/counties/<county_id>/certificates/<certificate_id>/sub-taxes", methods=["POST"])
def add_sub_tax(county_id, certificate_id):
    user_id, role = get_caller()
    require_role(role, ("Investor",))
    get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    body = get_body()

    # Referential (priority 4): payer investor must exist.
    investor_id = body.get("investor_id")
    if investor_id is None:
        fail(ERR_INVALID_REQUEST, "Missing required field: investor_id")
    investor = db.investors.get(investor_id)
    if investor is None:
        fail(ERR_CROSS_COUNTY_REFERENCE, "Investor not found")

    # Body shape (priority 5): required fields + OCC present.
    tax_year = require_int(body, "tax_year", minimum=None)
    principal = require_int(body, "principal_cents", minimum=None)
    check_occ(body, "expected_certificate_version", cert)

    # State (priority 7): certificate must be ACTIVE.
    if cert["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Certificate not ACTIVE")

    # Holder identity (priority 11).
    if investor_id != cert["holder_investor_id"]:
        fail(ERR_NOT_CERTIFICATE_HOLDER, "Payer is not the current holder")

    # Duplicate tax_year (priority 13).
    for s in db.sub_taxes.values():
        if s["certificate_id"] == cert["id"] and s["tax_year"] == tax_year:
            fail(ERR_DUPLICATE_SUB_TAX, "tax_year already paid")

    # Semantic principal constraint.
    if principal < 1:
        fail(ERR_VALIDATION, "principal_cents must be >= 1")

    # Escrow sufficiency (priority 14).
    if investor["escrow_balance_cents"] - principal < 0:
        fail(ERR_INSUFFICIENT_ESCROW, "Insufficient escrow for sub-tax")

    now = clock.now()
    rec = new_record({
        "certificate_id": cert["id"],
        "investor_id": investor_id,
        "tax_year": tax_year,
        "principal_cents": principal,
        "posted_at": clock.format_iso(now),
        "posted_at_dt": now,
        "status": "POSTED",
    })
    db.sub_taxes[rec["id"]] = rec

    investor["escrow_balance_cents"] -= principal
    touch(investor)
    svc.recompute_sub_tax_total(cert)
    touch(cert)
    return success_object(serialize(rec), 201)


@app.route("/counties/<county_id>/certificates/<certificate_id>/sub-taxes", methods=["GET"])
def list_sub_taxes(county_id, certificate_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    rows = [s for s in db.sub_taxes.values() if s["certificate_id"] == cert["id"]]
    rows = filter_eq(rows, "investor_id", request.args.get("investor_id"))
    rows = filter_eq(rows, "status", request.args.get("status"))
    return list_response(rows)


# ===========================================================================
# Redemption (list) — PRD §3.9
# ===========================================================================
@app.route("/counties/<county_id>/certificates/<certificate_id>/redemptions", methods=["GET"])
def list_redemptions(county_id, certificate_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    rows = [r for r in db.redemptions.values() if r["certificate_id"] == cert["id"]]
    return list_response(rows)


# ===========================================================================
# Assignment — PRD §3.8
# ===========================================================================
@app.route("/counties/<county_id>/certificates/<certificate_id>/assignments", methods=["POST"])
def record_assignment(county_id, certificate_id):
    user_id, role = get_caller()
    require_role(role, ("Investor",))
    get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    body = get_body()

    # Referential (priority 4): both investors must exist.
    from_id = body.get("from_investor_id")
    to_id = body.get("to_investor_id")
    if from_id is None:
        fail(ERR_INVALID_REQUEST, "Missing required field: from_investor_id")
    if to_id is None:
        fail(ERR_INVALID_REQUEST, "Missing required field: to_investor_id")
    if db.investors.get(from_id) is None or db.investors.get(to_id) is None:
        fail(ERR_CROSS_COUNTY_REFERENCE, "Investor not found")

    # Body shape (priority 5): consideration + OCC present.
    consideration = require_int(body, "consideration_cents", minimum=None)
    check_occ(body, "expected_certificate_version", cert)

    # State (priority 7): assignable while ACTIVE or FORECLOSURE_PENDING (a
    # certificate remains a transferable asset until terminal). The PRD ties
    # assignment to "the current holder"; terminal certs have no live holder.
    if cert["status"] not in ("ACTIVE", "FORECLOSURE_PENDING"):
        fail(ERR_INVALID_STATE, "Certificate not assignable")

    # Holder identity (priority 11).
    if from_id != cert["holder_investor_id"]:
        fail(ERR_NOT_CERTIFICATE_HOLDER, "Assignor is not the current holder")

    # Semantic (priority 13): assignee must differ from assignor.
    if to_id == from_id:
        fail(ERR_DUPLICATE_SUB_TAX, "to_investor_id must differ from from_investor_id")
    if consideration < 0:
        fail(ERR_VALIDATION, "consideration_cents must be >= 0")

    seq = cert["assignment_seq"] + 1
    rec = new_record({
        "certificate_id": cert["id"],
        "from_investor_id": from_id,
        "to_investor_id": to_id,
        "consideration_cents": consideration,
        "seq": seq,
        "status": "RECORDED",
    })
    db.assignments[rec["id"]] = rec

    cert["holder_investor_id"] = to_id
    cert["assignment_seq"] = seq
    touch(cert)
    return success_object(serialize(rec), 201)


@app.route("/counties/<county_id>/certificates/<certificate_id>/assignments", methods=["GET"])
def list_assignments(county_id, certificate_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    rows = [a for a in db.assignments.values() if a["certificate_id"] == cert["id"]]
    rows = filter_eq(rows, "from_investor_id", request.args.get("from_investor_id"))
    # Assignments list in ascending seq order (PRD §2.3 exception).
    rows = sorted(rows, key=lambda a: a["seq"])
    page, pagination = paginate(rows)
    return success_array([serialize(r) for r in page], pagination, 200)


# ===========================================================================
# DeedApplication — PRD §3.10
# ===========================================================================
@app.route("/counties/<county_id>/certificates/<certificate_id>/deed-applications", methods=["POST"])
def file_deed(county_id, certificate_id):
    user_id, role = get_caller()
    require_role(role, ("Investor",))
    county = get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    body = get_body()

    # Referential (priority 4): applicant must exist.
    applicant_id = body.get("applicant_investor_id")
    if applicant_id is None:
        fail(ERR_INVALID_REQUEST, "Missing required field: applicant_investor_id")
    if db.investors.get(applicant_id) is None:
        fail(ERR_CROSS_COUNTY_REFERENCE, "Investor not found")

    # Body shape (priority 5).
    deed_cost = require_int(body, "deed_cost_cents", minimum=None)

    # State (priority 7): certificate must be ACTIVE.
    if cert["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Certificate not ACTIVE")

    # Temporal (priority 10): redemption period must have elapsed.
    if clock.now() < cert["redeem_deadline_at_dt"]:
        fail(ERR_REDEMPTION_PERIOD_OPEN, "Redemption period still open")

    # Holder identity (priority 11).
    if applicant_id != cert["holder_investor_id"]:
        fail(ERR_NOT_CERTIFICATE_HOLDER, "Applicant is not the current holder")

    if deed_cost < 0:
        fail(ERR_VALIDATION, "deed_cost_cents must be >= 0")

    # Escrow sufficiency (priority 14).
    holder = db.investors[cert["holder_investor_id"]]
    if holder["escrow_balance_cents"] - deed_cost < 0:
        fail(ERR_INSUFFICIENT_ESCROW, "Insufficient escrow for deed cost")

    deed = svc.file_deed_application(county, cert, applicant_id, deed_cost)
    return success_object(serialize(deed), 201)


@app.route("/counties/<county_id>/deed-applications/<deed_id>", methods=["GET"])
def get_deed_ep(county_id, deed_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    return success_object(serialize(get_deed_scoped(county_id, deed_id)), 200)


@app.route("/counties/<county_id>/certificates/<certificate_id>/deed-applications", methods=["GET"])
def list_deeds(county_id, certificate_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    rows = [d for d in db.deed_applications.values() if d["certificate_id"] == cert["id"]]
    rows = filter_eq(rows, "status", request.args.get("status"))
    rows = filter_eq(rows, "applicant_investor_id", request.args.get("applicant_investor_id"))
    return list_response(rows)


@app.route("/counties/<county_id>/deed-applications/<deed_id>/award", methods=["POST"])
def award_deed_ep(county_id, deed_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    county = get_county(county_id)
    deed = get_deed_scoped(county_id, deed_id)
    cert = db.certificates[deed["certificate_id"]]
    body = get_body()
    sale_price = require_int(body, "sale_price_cents", minimum=None)

    if deed["status"] != "FILED" or cert["status"] != "FORECLOSURE_PENDING":
        fail(ERR_INVALID_STATE, "Deed not in a state to award")
    if sale_price < 0:
        fail(ERR_VALIDATION, "sale_price_cents must be >= 0")
    if sale_price < deed["minimum_bid_cents"]:
        fail(ERR_BID_BELOW_MINIMUM, "Sale price below minimum bid")

    svc.award_deed(county, cert, deed, sale_price)
    return success_object(serialize(deed), 200)


@app.route("/counties/<county_id>/deed-applications/<deed_id>/cancel", methods=["POST"])
def cancel_deed_ep(county_id, deed_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    get_county(county_id)
    deed = get_deed_scoped(county_id, deed_id)
    cert = db.certificates[deed["certificate_id"]]
    if deed["status"] != "FILED" or cert["status"] != "FORECLOSURE_PENDING":
        fail(ERR_INVALID_STATE, "Deed not in a state to cancel")
    svc.cancel_deed(cert, deed)
    return success_object(serialize(deed), 200)


# ===========================================================================
# SurplusDistribution — PRD §3.11
# ===========================================================================
@app.route("/counties/<county_id>/deed-applications/<deed_id>/surplus", methods=["GET"])
def list_surplus_by_deed(county_id, deed_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    deed = get_deed_scoped(county_id, deed_id)
    rows = [s for s in db.surplus_distributions.values()
            if s["deed_application_id"] == deed["id"]]
    return list_response(rows)


@app.route("/counties/<county_id>/certificates/<certificate_id>/surplus", methods=["GET"])
def list_surplus_by_cert(county_id, certificate_id):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    get_county(county_id)
    cert = get_certificate_scoped(county_id, certificate_id)
    rows = [s for s in db.surplus_distributions.values()
            if s["certificate_id"] == cert["id"]]
    return list_response(rows)


@app.route("/counties/<county_id>/deed-applications/<deed_id>/surplus/<surplus_id>/claim", methods=["POST"])
def claim_surplus(county_id, deed_id, surplus_id):
    _, role = get_caller()
    require_role(role, ("CountyTreasurer",))
    get_county(county_id)
    deed = get_deed_scoped(county_id, deed_id)
    surplus = db.surplus_distributions.get(surplus_id)
    if surplus is None or surplus["deed_application_id"] != deed["id"]:
        fail(ERR_NOT_FOUND, "Surplus distribution not found")
    surplus["claimed"] = True
    touch(surplus)
    return success_object(serialize(surplus), 200)


# ===========================================================================
# Flat reverse-reachability GET surface (PRD §4 / scaffold §1.5)
# ===========================================================================
def _flat_get(collection, _id, label):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    return success_object(serialize(get_in(collection, _id, label)), 200)


def _flat_list(collection, filters):
    _, role = get_caller()
    require_role(role, ALL_ROLES)
    rows = list(collection.values())
    for field in filters:
        rows = filter_eq(rows, field, request.args.get(field))
    if request.args.get("status") is not None and "status" not in filters:
        rows = filter_eq(rows, "status", request.args.get("status"))
    return list_response(rows)


@app.route("/counties/parcels/<parcel_id>", methods=["GET"])
def flat_get_parcel(parcel_id):
    return _flat_get(db.parcels, parcel_id, "Parcel")


@app.route("/counties/parcels", methods=["GET"])
def flat_list_parcels():
    return _flat_list(db.parcels, ["county_id", "status"])


@app.route("/counties/sales/<sale_id>", methods=["GET"])
def flat_get_sale(sale_id):
    return _flat_get(db.sales, sale_id, "Sale")


@app.route("/counties/sales", methods=["GET"])
def flat_list_sales():
    return _flat_list(db.sales, ["county_id", "status"])


@app.route("/counties/listings/<listing_id>", methods=["GET"])
def flat_get_listing(listing_id):
    return _flat_get(db.listings, listing_id, "Listing")


@app.route("/counties/listings", methods=["GET"])
def flat_list_listings():
    return _flat_list(db.listings, ["sale_id", "parcel_id", "winning_bid_id", "certificate_id", "status"])


@app.route("/counties/bids/<bid_id>", methods=["GET"])
def flat_get_bid(bid_id):
    return _flat_get(db.bids, bid_id, "Bid")


@app.route("/counties/bids", methods=["GET"])
def flat_list_bids():
    return _flat_list(db.bids, ["listing_id", "investor_id", "status"])


@app.route("/counties/certificates/<certificate_id>", methods=["GET"])
def flat_get_certificate(certificate_id):
    return _flat_get(db.certificates, certificate_id, "Certificate")


@app.route("/counties/certificates", methods=["GET"])
def flat_list_certificates():
    return _flat_list(db.certificates, ["county_id", "parcel_id", "listing_id", "holder_investor_id", "status"])


@app.route("/counties/sub-taxes/<sub_tax_id>", methods=["GET"])
def flat_get_sub_tax(sub_tax_id):
    return _flat_get(db.sub_taxes, sub_tax_id, "Subsequent tax")


@app.route("/counties/sub-taxes", methods=["GET"])
def flat_list_sub_taxes():
    return _flat_list(db.sub_taxes, ["certificate_id", "investor_id", "status"])


@app.route("/counties/redemptions/<redemption_id>", methods=["GET"])
def flat_get_redemption(redemption_id):
    return _flat_get(db.redemptions, redemption_id, "Redemption")


@app.route("/counties/redemptions", methods=["GET"])
def flat_list_redemptions():
    return _flat_list(db.redemptions, ["certificate_id"])


@app.route("/counties/assignments/<assignment_id>", methods=["GET"])
def flat_get_assignment(assignment_id):
    return _flat_get(db.assignments, assignment_id, "Assignment")


@app.route("/counties/assignments", methods=["GET"])
def flat_list_assignments():
    return _flat_list(db.assignments, ["certificate_id", "from_investor_id", "to_investor_id"])


@app.route("/counties/deed-applications/<deed_id>", methods=["GET"])
def flat_get_deed(deed_id):
    return _flat_get(db.deed_applications, deed_id, "Deed application")


@app.route("/counties/deed-applications", methods=["GET"])
def flat_list_deeds():
    return _flat_list(db.deed_applications, ["certificate_id", "applicant_investor_id", "status"])


@app.route("/counties/surplus/<surplus_id>", methods=["GET"])
def flat_get_surplus(surplus_id):
    return _flat_get(db.surplus_distributions, surplus_id, "Surplus distribution")


@app.route("/counties/surplus", methods=["GET"])
def flat_list_surplus():
    return _flat_list(db.surplus_distributions, ["deed_application_id", "certificate_id"])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
