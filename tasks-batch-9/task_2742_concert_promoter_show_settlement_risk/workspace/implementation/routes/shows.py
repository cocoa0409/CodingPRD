"""Shows: booking, the two status dimensions and the provisional projection."""

from datetime import timedelta

from flask import Blueprint

import calc
import common
import recompute
import serializers as ser
import store
import validation as v
from envelope import created, list_response, object_response
from errors import ApiError
from store import db, new_entity

bp = Blueprint("shows", __name__)

ARRANGEMENTS = ("RENTAL", "CO_PROMOTE")
SHOW_STATUSES = ("PLANNED", "CONFIRMED", "ON_SALE", "PERFORMED", "SETTLED",
                 "CANCELLED", "POSTPONED", "RESCHEDULED")
SALES_STATUSES = ("PRE_SALE", "SELLING", "PAUSED", "CLOSED")
CATEGORY_PCT_FIELDS = ("venue_expense_pct_production",
                       "venue_expense_pct_marketing",
                       "venue_expense_pct_staffing",
                       "venue_expense_pct_hospitality")
OCCUPANCY_EXCLUDED = ("CANCELLED", "RESCHEDULED")


@bp.post("/shows")
def create_show():
    common.auth("TalentBuyer")
    body = v.get_body()
    artist_id = v.req_str(body, "artist_id")
    venue_id = v.req_str(body, "venue_id")
    event_at = v.req_ts(body, "event_at")
    load_in_at = v.req_ts(body, "load_in_at")
    load_out_at = v.req_ts(body, "load_out_at")
    announce_at = v.req_ts(body, "announce_at")
    arrangement = v.req_enum(body, "venue_arrangement", ARRANGEMENTS)
    rental_fee = v.opt_cents(body, "rental_fee_cents", minimum=0, default=0)
    copromote_pct = v.opt_pct(body, "copromote_venue_share_pct", 0, 50, default=0)
    category_pcts = {}
    for field in CATEGORY_PCT_FIELDS:
        category_pcts[field] = v.opt_pct(body, field, 0, 100, default=0)
    rescheduled_from = v.opt_str(body, "rescheduled_from_show_id")

    # A payload that contradicts its own venue_arrangement is malformed.
    if arrangement == "RENTAL":
        if rental_fee <= 0:
            v.bad("rental_fee_cents must be greater than 0 under RENTAL")
        if copromote_pct != 0 or any(value != 0 for value in category_pcts.values()):
            v.bad("RENTAL shows carry no venue share or reimbursement percentages")
    else:
        if copromote_pct <= 0:
            v.bad("copromote_venue_share_pct must be greater than 0 under CO_PROMOTE")
        if rental_fee != 0:
            v.bad("rental_fee_cents must be 0 under CO_PROMOTE")

    artist = common.get_artist(artist_id)
    venue = common.get_venue(venue_id)
    if rescheduled_from is not None:
        common.get_show(rescheduled_from)

    if not (load_in_at < event_at and event_at < load_out_at
            and announce_at <= event_at):
        raise ApiError("ERR_INVALID_SHOW_WINDOW",
                       "load_in_at < event_at < load_out_at and announce_at <= event_at")
    if event_at <= store.now():
        raise ApiError("ERR_EVENT_DATE_IN_PAST", "event_at must be in the future")
    for other in db.shows.values():
        if other["venue_id"] != venue_id:
            continue
        if other["show_status"] in OCCUPANCY_EXCLUDED:
            continue
        if load_in_at < other["load_out_at"] and other["load_in_at"] < load_out_at:
            raise ApiError("ERR_VENUE_WINDOW_CONFLICT",
                           "venue is already occupied for that interval")

    show = new_entity(
        artist_id=artist_id,
        venue_id=venue_id,
        market_id=venue["market_id"],
        rescheduled_from_show_id=rescheduled_from,
        event_at=event_at,
        load_in_at=load_in_at,
        load_out_at=load_out_at,
        announce_at=announce_at,
        show_status="PLANNED",
        sales_status="PRE_SALE",
        venue_arrangement=arrangement,
        rental_fee_cents=rental_fee,
        copromote_venue_share_pct=copromote_pct,
        exposure_override_limit_cents=None,
        exposure_override_justification=None,
        exposure_override_by_user_id=None,
        committed_guarantee_cents=0,
        gross_sold_cents=0,
        paid_tickets_sold=0,
        comp_tickets_issued=0,
        held_tickets=0,
        transferred_in_gross_cents=0,
        transferred_in_paid_tickets=0,
        adjusted_gross_cents=0,
        total_budgeted_expense_cents=0,
        total_actual_expense_cents=0,
        breakeven_cents=0,
        projected_adjusted_gross_cents=0,
        projected_promoter_net_cents=0,
        budget_posture="ON_BUDGET",
        refund_liability_cents=0,
        **category_pcts
    )
    db.shows[show["id"]] = show
    recompute.recompute_show(show)
    return created(ser.show_json(show))


@bp.get("/shows/<show_id>")
def read_show(show_id):
    common.auth(*common.ALL_ROLES)
    show = common.get_show(show_id)
    return object_response(ser.show_json(show))


@bp.get("/shows")
def list_shows():
    common.auth(*common.ALL_ROLES)
    market_id = common.filter_fk("market_id", common.get_market)
    artist_id = common.filter_fk("artist_id", common.get_artist)
    venue_id = common.filter_fk("venue_id", common.get_venue)
    from_show_id = common.filter_fk("rescheduled_from_show_id", common.get_show)
    show_status = common.filter_arg("show_status")
    sales_status = common.filter_arg("sales_status")

    rows = []
    for show in db.shows.values():
        if market_id is not None and show["market_id"] != market_id:
            continue
        if artist_id is not None and show["artist_id"] != artist_id:
            continue
        if venue_id is not None and show["venue_id"] != venue_id:
            continue
        if from_show_id is not None and show["rescheduled_from_show_id"] != from_show_id:
            continue
        if show_status is not None and show["show_status"] != show_status:
            continue
        if sales_status is not None and show["sales_status"] != sales_status:
            continue
        rows.append(show)
    page, limit, offset, total = common.listing(rows, ser.show_json)
    return list_response(page, limit, offset, total)


@bp.get("/shows/<show_id>/settlement-projection")
def settlement_projection(show_id):
    common.auth(*common.STAFF_ROLES)
    show = common.get_show(show_id)
    venue = common.venue_of(show)
    artist = common.artist_of(show)
    offer = store.accepted_offer(show["id"])
    lines = store.live_lines_of_show(show["id"])

    gross, tickets = recompute._projection_inputs(show)
    figures = calc.settlement_figures(show, venue, artist, offer, lines,
                                      gross, tickets, "budgeted_cents")
    return object_response(ser.projection_json(show["id"], figures))


def _cascade_tiers(show, from_statuses, to_status):
    touched = []
    for tier in store.tiers_of_show(show["id"]):
        if tier["status"] in from_statuses:
            tier["status"] = to_status
            recompute.recompute_tier(tier)
            store.touch(tier)
            touched.append(tier)
    return touched


@bp.post("/shows/<show_id>/on-sale")
def on_sale(show_id):
    common.auth("TalentBuyer")
    show = common.get_show(show_id)
    common.state_guard(show["show_status"], ("CONFIRMED",),
                       common.TERMINAL_SHOW_STATUS)
    common.require(show["sales_status"] == "PRE_SALE",
                   "sales_status must be PRE_SALE")

    if store.now() < show["announce_at"]:
        raise ApiError("ERR_ANNOUNCE_DATE_NOT_REACHED",
                       "the announce date has not been reached")
    if not store.tiers_of_show(show["id"]):
        raise ApiError("ERR_NO_TICKET_TIERS", "the show has no ticket tiers")

    show["show_status"] = "ON_SALE"
    show["sales_status"] = "SELLING"
    _cascade_tiers(show, ("DRAFT",), "ON_SALE")
    recompute.recompute_show(show)
    store.touch(show)
    recompute.recompute_market(common.market_of(show))
    return object_response(ser.show_json(show))


@bp.post("/shows/<show_id>/pause-sales")
def pause_sales(show_id):
    common.auth("TalentBuyer", "RiskOfficer")
    body = v.get_body()
    v.req_str(body, "reason", max_len=200)
    show = common.get_show(show_id)
    common.state_guard(show["sales_status"], ("SELLING",),
                       common.TERMINAL_SALES_STATUS)

    show["sales_status"] = "PAUSED"
    _cascade_tiers(show, ("ON_SALE",), "PAUSED")
    recompute.recompute_show(show)
    store.touch(show)
    recompute.recompute_market(common.market_of(show))
    return object_response(ser.show_json(show))


@bp.post("/shows/<show_id>/resume-sales")
def resume_sales(show_id):
    common.auth("TalentBuyer")
    show = common.get_show(show_id)
    common.state_guard(show["sales_status"], ("PAUSED",),
                       common.TERMINAL_SALES_STATUS)
    common.require(show["show_status"] == "ON_SALE",
                   "show_status must be ON_SALE")

    show["sales_status"] = "SELLING"
    _cascade_tiers(show, ("PAUSED",), "ON_SALE")
    recompute.recompute_show(show)
    store.touch(show)
    recompute.recompute_market(common.market_of(show))
    return object_response(ser.show_json(show))


@bp.post("/shows/<show_id>/perform")
def perform(show_id):
    common.auth("TalentBuyer", "TourAccountant")
    show = common.get_show(show_id)
    common.state_guard(show["show_status"], ("ON_SALE",),
                       common.TERMINAL_SHOW_STATUS)
    if store.now() < show["event_at"]:
        raise ApiError("ERR_SHOW_NOT_YET_OCCURRED",
                       "event_at has not been reached")

    show["show_status"] = "PERFORMED"
    show["sales_status"] = "CLOSED"
    _cascade_tiers(show, ("DRAFT", "ON_SALE", "PAUSED"), "CLOSED")
    recompute.recompute_show(show)
    store.touch(show)
    recompute.recompute_market(common.market_of(show))
    return object_response(ser.show_json(show))


@bp.post("/shows/<show_id>/exposure-override")
def exposure_override(show_id):
    user_id, _role = common.auth("RiskOfficer")
    body = v.get_body()
    limit_cents = v.req_cents(body, "exposure_override_limit_cents", minimum=1)
    justification = v.raw_str(body, "exposure_override_justification", max_len=500)
    show = common.get_show(show_id)
    if show["show_status"] in common.TERMINAL_SHOW_STATUS:
        common.already_terminal(show["show_status"])

    market = common.market_of(show)
    ceiling = (market["guarantee_exposure_limit_cents"]
               * calc.EXPOSURE_OVERRIDE_MULTIPLIER)
    if not justification.strip() or limit_cents > ceiling:
        raise ApiError("ERR_EXPOSURE_OVERRIDE_INVALID",
                       "override must carry a justification and stay within "
                       "twice the market limit")

    show["exposure_override_limit_cents"] = limit_cents
    show["exposure_override_justification"] = justification
    show["exposure_override_by_user_id"] = user_id
    recompute.recompute_show(show)
    store.touch(show)
    recompute.recompute_market(market)
    return object_response(ser.show_json(show))
