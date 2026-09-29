"""Markets, artists and venues (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import common
import recompute
import serializers as ser
import store
import validation as v
from envelope import created, list_response, object_response
from errors import ApiError
from store import db, new_entity

bp = Blueprint("core", __name__)

MARKET_POSTURES = ("OPEN", "WATCH", "RESTRICTED", "FROZEN")
ARTIST_TIERS = ("CLUB", "THEATER", "ARENA", "HEADLINE")
VALUATIONS = ("TRAILING_SETTLED", "MARK_TO_MARKET")


# ---------------------------------------------------------------------------
# markets
# ---------------------------------------------------------------------------

@bp.post("/markets")
def create_market():
    common.auth("RiskOfficer")
    body = v.get_body()
    name = v.req_str(body, "name", max_len=120)
    region_code = v.req_str(body, "region_code", max_len=8)
    if len(region_code) < 2 or region_code != region_code.upper():
        v.bad("region_code must be 2 to 8 uppercase characters")
    limit_cents = v.req_cents(body, "guarantee_exposure_limit_cents", minimum=1)

    market = new_entity(
        name=name,
        region_code=region_code,
        guarantee_exposure_limit_cents=limit_cents,
        committed_guarantee_cents=0,
        at_risk_guarantee_cents=0,
        exposure_utilization_pct=Decimal("0.00"),
        risk_posture="OPEN",
        settled_show_count=0,
        performance_index=0,
    )
    db.markets[market["id"]] = market
    return created(ser.market_json(market))


@bp.get("/markets/<market_id>")
def read_market(market_id):
    common.auth(*common.STAFF_ROLES)
    market = common.get_market(market_id)
    return object_response(ser.market_json(market))


@bp.get("/markets")
def list_markets():
    common.auth(*common.STAFF_ROLES)
    posture = common.filter_arg("risk_posture")
    rows = [m for m in db.markets.values()
            if posture is None or m["risk_posture"] == posture]
    page, limit, offset, total = common.listing(rows, ser.market_json)
    return list_response(page, limit, offset, total)


@bp.get("/markets/<market_id>/portfolio-risk")
def portfolio_risk(market_id):
    common.auth(*common.STAFF_ROLES)
    market = common.get_market(market_id)
    valuation = common.filter_arg("valuation") or "TRAILING_SETTLED"
    if valuation not in VALUATIONS:
        v.bad("valuation must be TRAILING_SETTLED or MARK_TO_MARKET")
    figures = recompute.market_figures(market)
    figures["performance_index"] = recompute.performance_index(market, valuation)
    return object_response(ser.market_json(market, overrides=figures))


# ---------------------------------------------------------------------------
# artists
# ---------------------------------------------------------------------------

@bp.post("/artists")
def create_artist():
    common.auth("TalentBuyer")
    body = v.get_body()
    name = v.req_str(body, "name", max_len=120)
    agency = v.req_str(body, "agency", max_len=120)
    tier = v.req_enum(body, "tier", ARTIST_TIERS)
    sellthrough = v.req_pct(body, "historical_sellthrough_pct", 0, 100)
    withholding = v.opt_pct(body, "withholding_pct", 0, 40, default=0)

    artist = new_entity(
        name=name,
        agency=agency,
        tier=tier,
        historical_sellthrough_pct=sellthrough,
        withholding_pct=withholding,
        confirmed_show_count=0,
    )
    db.artists[artist["id"]] = artist
    return created(ser.artist_json(artist))


@bp.get("/artists/<artist_id>")
def read_artist(artist_id):
    common.auth("TalentBuyer", "TourAccountant", "RiskOfficer", "ArtistRep")
    artist = common.get_artist(artist_id)
    return object_response(ser.artist_json(artist))


@bp.get("/artists")
def list_artists():
    common.auth(*common.STAFF_ROLES)
    tier = common.filter_arg("tier")
    rows = [a for a in db.artists.values() if tier is None or a["tier"] == tier]
    page, limit, offset, total = common.listing(rows, ser.artist_json)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# venues
# ---------------------------------------------------------------------------

@bp.post("/venues")
def create_venue():
    common.auth("TalentBuyer")
    body = v.get_body()
    market_id = v.req_str(body, "market_id")
    name = v.req_str(body, "name", max_len=120)
    capacity = v.req_int(body, "gross_capacity", minimum=1)
    facility_fee = v.req_cents(body, "facility_fee_cents_per_ticket", minimum=0)
    tax_pct = v.req_pct(body, "ticket_tax_pct", 0, 25)

    common.get_market(market_id)

    venue = new_entity(
        market_id=market_id,
        name=name,
        gross_capacity=capacity,
        facility_fee_cents_per_ticket=facility_fee,
        ticket_tax_pct=tax_pct,
    )
    db.venues[venue["id"]] = venue
    return created(ser.venue_json(venue))


@bp.get("/venues/<venue_id>")
def read_venue(venue_id):
    common.auth("TalentBuyer", "TourAccountant", "RiskOfficer", "VenueOperator")
    venue = common.get_venue(venue_id)
    return object_response(ser.venue_json(venue))


@bp.get("/venues")
def list_venues():
    common.auth("TalentBuyer", "TourAccountant", "RiskOfficer", "VenueOperator")
    market_id = common.filter_fk("market_id", common.get_market)
    rows = [x for x in db.venues.values()
            if market_id is None or x["market_id"] == market_id]
    page, limit, offset, total = common.listing(rows, ser.venue_json)
    return list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# operational endpoints
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    common.auth(*common.ALL_ROLES)
    body = v.get_body()
    instant = v.req_ts(body, "current_utc")
    db.clock = instant
    return object_response({})


@bp.post("/_ops/run")
def ops_run():
    common.auth(*common.STAFF_ROLES)
    v.get_body()
    now = store.now()

    expired_offers = 0
    for offer in store.by_seq(list(db.offers.values())):
        if offer["status"] != "SUBMITTED":
            continue
        expires_at = offer["expires_at"]
        if expires_at is not None and now >= expires_at:
            offer["status"] = "EXPIRED"
            store.touch(offer)
            expired_offers += 1

    expired_holds = 0
    touched_tiers = []
    touched_shows = []
    for hold in store.by_seq(list(db.ticket_holds.values())):
        if hold["status"] != "HELD":
            continue
        expires_at = hold["expires_at"]
        if expires_at is None or now < expires_at:
            continue
        hold["status"] = "EXPIRED"
        store.touch(hold)
        expired_holds += 1
        tier = db.ticket_tiers.get(hold["ticket_tier_id"])
        if tier is not None and tier["id"] not in [t["id"] for t in touched_tiers]:
            touched_tiers.append(tier)
        show = common.show_of_tier(tier) if tier else None
        if show is not None and show["id"] not in [s["id"] for s in touched_shows]:
            touched_shows.append(show)

    for tier in touched_tiers:
        recompute.recompute_tier(tier)
        store.touch(tier)
    for show in touched_shows:
        recompute.cascade(show, bump_show=True, bump_market=False)

    return object_response({})
