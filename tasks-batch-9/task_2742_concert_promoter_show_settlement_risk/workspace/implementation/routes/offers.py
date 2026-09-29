"""Offers: drafting, the negotiation cycle and acceptance (PRD 3.2, 3.3)."""

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

bp = Blueprint("offers", __name__)

DEAL_STRUCTURES = ("FLAT_GUARANTEE", "VERSUS", "GUARANTEE_PLUS_BACKEND")
LIVE_OFFER_STATUSES = ("SUBMITTED", "COUNTERED")


def _incoherent(message):
    raise ApiError("ERR_DEAL_TERMS_INCOHERENT", message)


def _check_deal_terms(deal_structure, guarantee, deposit, expense_cap,
                      versus_pct, backend_pct):
    if deal_structure == "FLAT_GUARANTEE":
        if versus_pct not in (0, None) or backend_pct not in (0, None):
            _incoherent("FLAT_GUARANTEE forbids versus_pct and "
                        "backend_split_artist_pct")
    elif deal_structure == "VERSUS":
        if versus_pct is None or versus_pct <= 0:
            _incoherent("VERSUS requires versus_pct greater than 0")
        if backend_pct not in (0, None):
            _incoherent("VERSUS forbids backend_split_artist_pct")
    elif deal_structure == "GUARANTEE_PLUS_BACKEND":
        if backend_pct is None or backend_pct <= 0:
            _incoherent("GUARANTEE_PLUS_BACKEND requires "
                        "backend_split_artist_pct greater than 0")
        if versus_pct not in (0, None):
            _incoherent("GUARANTEE_PLUS_BACKEND forbids versus_pct")
    if deposit is not None and guarantee is not None and deposit > guarantee:
        _incoherent("deposit_cents may not exceed guarantee_cents")
    if expense_cap is not None and expense_cap <= 0:
        _incoherent("expense_cap_cents must be greater than 0")


def _supersede_siblings(show_id, keep_offer_id):
    for sibling in store.offers_of_show(show_id):
        if sibling["id"] == keep_offer_id:
            continue
        if sibling["status"] in LIVE_OFFER_STATUSES:
            sibling["status"] = "SUPERSEDED"
            store.touch(sibling)


@bp.post("/offers")
def create_offer():
    common.auth("TalentBuyer")
    body = v.get_body()
    show_id = v.req_str(body, "show_id")
    expected_version = v.req_int(body, "expected_show_version")
    deal_structure = v.req_enum(body, "deal_structure", DEAL_STRUCTURES)
    guarantee = v.req_cents(body, "guarantee_cents", minimum=1)
    deposit = v.req_cents(body, "deposit_cents", minimum=0)
    expense_cap = v.req_cents(body, "expense_cap_cents", minimum=0)
    versus_pct = v.opt_pct(body, "versus_pct", 0, 100, default=0)
    backend_pct = v.opt_pct(body, "backend_split_artist_pct", 0, 100, default=0)

    show = common.get_show(show_id)
    common.check_show_version(show, expected_version)
    common.state_guard(show["show_status"], ("PLANNED",),
                       common.TERMINAL_SHOW_STATUS)
    _check_deal_terms(deal_structure, guarantee, deposit, expense_cap,
                      versus_pct, backend_pct)

    offer = new_entity(
        show_id=show_id,
        deal_structure=deal_structure,
        guarantee_cents=guarantee,
        deposit_cents=deposit,
        expense_cap_cents=expense_cap,
        versus_pct=versus_pct,
        backend_split_artist_pct=backend_pct,
        status="DRAFT",
        round_index=1,
        submitted_at=None,
        expires_at=None,
        counter_guarantee_cents=None,
        counter_versus_pct=None,
        counter_backend_split_artist_pct=None,
        counter_note=None,
        accepted_by_user_id=None,
    )
    db.offers[offer["id"]] = offer
    _supersede_siblings(show_id, offer["id"])
    store.touch(show)
    return created(ser.offer_json(offer))


@bp.get("/offers/<offer_id>")
def read_offer(offer_id):
    common.auth("TalentBuyer", "TourAccountant", "RiskOfficer", "ArtistRep")
    offer = common.get_offer(offer_id)
    return object_response(ser.offer_json(offer))


@bp.get("/offers")
def list_offers():
    common.auth("TalentBuyer", "TourAccountant", "RiskOfficer", "ArtistRep")
    show_id = common.filter_fk("show_id", common.get_show)
    status = common.filter_arg("status")
    deal_structure = common.filter_arg("deal_structure")
    rows = []
    for offer in db.offers.values():
        if show_id is not None and offer["show_id"] != show_id:
            continue
        if status is not None and offer["status"] != status:
            continue
        if deal_structure is not None and offer["deal_structure"] != deal_structure:
            continue
        rows.append(offer)
    page, limit, offset, total = common.listing(rows, ser.offer_json)
    return list_response(page, limit, offset, total)


@bp.post("/offers/<offer_id>/submit")
def submit_offer(offer_id):
    common.auth("TalentBuyer")
    body = v.get_body()
    guarantee = v.opt_cents(body, "guarantee_cents", minimum=1, default=None)
    versus_pct = v.opt_pct(body, "versus_pct", 0, 100, default=None)
    backend_pct = v.opt_pct(body, "backend_split_artist_pct", 0, 100, default=None)

    offer = common.get_offer(offer_id)
    common.state_guard(offer["status"], ("DRAFT", "COUNTERED"),
                       common.TERMINAL_OFFER)
    show = common.get_show(offer["show_id"])
    common.require(show["show_status"] == "PLANNED",
                   "the show is no longer PLANNED")

    resubmission = offer["status"] == "COUNTERED"
    if resubmission and offer["round_index"] >= calc.NEGOTIATION_ROUND_LIMIT:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                       "negotiation is capped at three rounds")

    if guarantee is not None:
        offer["guarantee_cents"] = guarantee
    if versus_pct is not None:
        offer["versus_pct"] = versus_pct
    if backend_pct is not None:
        offer["backend_split_artist_pct"] = backend_pct

    stamp = store.now()
    offer["status"] = "SUBMITTED"
    offer["submitted_at"] = stamp
    offer["expires_at"] = stamp + timedelta(hours=calc.OFFER_TTL_HOURS)
    if resubmission:
        offer["round_index"] += 1
    store.touch(offer)
    return object_response(ser.offer_json(offer))


@bp.post("/offers/<offer_id>/counter")
def counter_offer(offer_id):
    user_id, role = common.auth("ArtistRep")
    body = v.get_body()
    counter_guarantee = v.req_cents(body, "counter_guarantee_cents", minimum=1)
    counter_versus = v.opt_pct(body, "counter_versus_pct", 0, 100, default=None)
    counter_backend = v.opt_pct(body, "counter_backend_split_artist_pct",
                                0, 100, default=None)
    counter_note = v.req_str(body, "counter_note", max_len=500)

    offer = common.get_offer(offer_id)
    show = common.get_show(offer["show_id"])
    common.require_show_owner(show, user_id, role)
    common.state_guard(offer["status"], ("SUBMITTED",), common.TERMINAL_OFFER)
    common.require(show["show_status"] == "PLANNED",
                   "the show is no longer PLANNED")

    effective_versus = (counter_versus if counter_versus is not None
                        else offer["versus_pct"])
    effective_backend = (counter_backend if counter_backend is not None
                         else offer["backend_split_artist_pct"])
    _check_deal_terms(offer["deal_structure"], counter_guarantee,
                      offer["deposit_cents"], offer["expense_cap_cents"],
                      effective_versus, effective_backend)

    if offer["round_index"] >= calc.NEGOTIATION_ROUND_LIMIT:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                       "negotiation is capped at three rounds")
    if offer["expires_at"] is not None and store.now() >= offer["expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", "the offer has expired")

    offer["counter_guarantee_cents"] = counter_guarantee
    if counter_versus is not None:
        offer["counter_versus_pct"] = counter_versus
    if counter_backend is not None:
        offer["counter_backend_split_artist_pct"] = counter_backend
    offer["counter_note"] = counter_note
    offer["status"] = "COUNTERED"
    offer["expires_at"] = None
    store.touch(offer)
    return object_response(ser.offer_json(offer))


@bp.post("/offers/<offer_id>/accept")
def accept_offer(offer_id):
    user_id, role = common.auth("ArtistRep")
    v.get_body()
    offer = common.get_offer(offer_id)
    show = common.get_show(offer["show_id"])
    common.require_show_owner(show, user_id, role)
    common.state_guard(offer["status"], ("SUBMITTED",), common.TERMINAL_OFFER)
    common.require(show["show_status"] == "PLANNED",
                   "the show is no longer PLANNED")

    # artist routing: 36 hours of rest either side, POSTPONED shows included
    buffer_seconds = calc.ARTIST_REST_BUFFER_HOURS * 3600
    for other in store.shows_of_artist(show["artist_id"]):
        if other["id"] == show["id"]:
            continue
        if other["show_status"] not in recompute.ROUTING_IN_SCOPE:
            continue
        gap = abs((other["event_at"] - show["event_at"]).total_seconds())
        if gap < buffer_seconds:
            raise ApiError("ERR_ARTIST_ROUTING_CONFLICT",
                           "the act needs 36 hours between shows")

    if offer["expires_at"] is not None and store.now() >= offer["expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", "the offer has expired")

    market = common.market_of(show)
    if market["risk_posture"] == "FROZEN":
        raise ApiError("ERR_MARKET_POSTURE_FROZEN",
                       "the market is frozen to new guarantees")
    ceiling = (show["exposure_override_limit_cents"]
               if show["exposure_override_limit_cents"] is not None
               else market["guarantee_exposure_limit_cents"])
    if market["committed_guarantee_cents"] + offer["guarantee_cents"] > ceiling:
        raise ApiError("ERR_MARKET_EXPOSURE_EXCEEDED",
                       "the guarantee would breach the exposure ceiling")

    offer["status"] = "ACCEPTED"
    offer["accepted_by_user_id"] = user_id
    store.touch(offer)
    _supersede_siblings(show["id"], offer["id"])

    show["show_status"] = "CONFIRMED"
    recompute.recompute_show(show)
    store.touch(show)

    artist = common.artist_of(show)
    recompute.recompute_artist(artist)
    store.touch(artist)

    recompute.recompute_market(market)
    store.touch(market)
    return object_response(ser.offer_json(offer))


@bp.post("/offers/<offer_id>/withdraw")
def withdraw_offer(offer_id):
    common.auth("TalentBuyer")
    body = v.get_body()
    v.req_str(body, "reason", max_len=200)
    offer = common.get_offer(offer_id)
    common.state_guard(offer["status"], ("DRAFT", "SUBMITTED", "COUNTERED"),
                       common.TERMINAL_OFFER)
    offer["status"] = "WITHDRAWN"
    store.touch(offer)
    return object_response(ser.offer_json(offer))
