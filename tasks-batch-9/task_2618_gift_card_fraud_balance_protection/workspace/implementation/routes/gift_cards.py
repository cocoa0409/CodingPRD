"""Gift cards, balance inquiries, redemptions, holds and posture overrides
(PRD 3.2, 3.4, 3.5, 3.6)."""
from flask import Blueprint

import clock
import db as dbm
import response
import validate
from db import db
from errors import fail
from middleware import scope_body_store
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_card, require_hold, require_rack, require_store,
                           scope_record)
from services import alerts as alert_svc
from services import cards as card_svc
from services import listings as listing_svc
from services import scoring
from services import stores as store_svc
from services.cards import ACTIVATION_STATES, CHANNELS, POSTURES
from services.holds import DISPOSITIONS, HOLD_STATES, capacity_exceeded
from services.listings import LISTING_STATES
from services.scoring import INQUIRY_CHANNELS

bp = Blueprint("gift_cards", __name__)


@bp.post("/gift-cards")
def stock_card():
    caller = authenticate(["PosAssociate", "StoreManager"])
    scope_body_store(caller)
    body = validate.body()
    store_id = validate.string(body, "store_id", min_len=1)
    rack_id = validate.string(body, "rack_id", min_len=1)
    masked = validate.string(body, "card_number_masked", required=False,
                             pattern=validate.MASKED_PAN_RE)
    require_store(store_id)
    rack = require_rack(rack_id)
    if rack["tamper_state"] != "INTACT":
        fail("ERR_RACK_TAMPERED")
    if masked is not None:
        for existing in db.cards.values():
            if existing.get("card_number_masked") == masked:
                fail("ERR_INVALID_REQUEST", "card_number_masked is already in use.")
    card = card_svc.new_card("PHYSICAL", store_id=store_id, rack_id=rack_id,
                             card_number_masked=masked)
    return response.created(card)


@bp.get("/gift-cards")
def list_cards():
    authenticate(READ_ROLES)
    store_id = validate.query_str("store_id")
    rack_id = validate.query_str("rack_id")
    reissued_from = validate.query_str("reissued_from_card_id")
    activation_state = validate.query_enum("activation_state", ACTIVATION_STATES)
    risk_posture = validate.query_enum("risk_posture", POSTURES)
    channel = validate.query_enum("channel", CHANNELS)
    rows = list(db.cards.values())
    rows = filter_by(rows, "store_id", store_id)
    rows = filter_by(rows, "rack_id", rack_id)
    rows = filter_by(rows, "reissued_from_card_id", reissued_from)
    rows = filter_by(rows, "activation_state", activation_state)
    rows = filter_by(rows, "risk_posture", risk_posture)
    rows = filter_by(rows, "channel", channel)
    return listing_response(rows)


@bp.get("/gift-cards/<card_id>")
def get_card(card_id):
    caller = authenticate(READ_ROLES)
    scope_record(caller, db.cards.get(card_id))
    return response.ok(require_card(card_id))


@bp.post("/gift-cards/<card_id>/balance-inquiries")
def create_inquiry(card_id):
    caller = authenticate(["PosAssociate", "FraudAnalyst", "ResellerPartner"])
    body = validate.body()
    channel = validate.enum(body, "channel", INQUIRY_CHANNELS)
    ip_hash = validate.string(body, "requester_ip_hash", min_len=1, max_len=128)
    card = require_card(card_id)
    policy = dbm.policy()

    # Permitted in ANY funding state and ANY posture.
    card_svc.recompute(card)
    inquiry = dbm.audit_record({
        "card_id": card["id"],
        "channel": channel,
        "requester_ip_hash": ip_hash,
        "occurred_at": clock.now(),
        "velocity_count_at_inquiry": 0,
        "drain_score_at_inquiry": 0,
        "balance_disclosed_cents": card["current_balance_cents"],
    })
    db.inquiries[inquiry["id"]] = inquiry

    # Velocity is evaluated AFTER the append, so this row counts itself.
    velocity_count = scoring.inquiry_velocity_count(card["id"], policy)
    inquiry["velocity_count_at_inquiry"] = velocity_count
    breach = velocity_count >= policy["inquiry_velocity_threshold"]

    score = scoring.inquiry_weighted_score(card, velocity_count)
    card["drain_risk_score_inquiry"] = score
    inquiry["drain_score_at_inquiry"] = score

    store_touched = False
    if breach and not alert_svc.has_open_velocity_alert(card["id"]):
        alert_svc.create_alert(card, "INQUIRY_VELOCITY",
                               basis_velocity_count=velocity_count)
        store_touched = True

    card_svc.escalate_posture(card, card_svc.posture_target(score, policy, breach))
    dbm.touch(card)
    if store_touched:
        store_svc.touch_store_for_card(card)
    return response.created(inquiry)


@bp.get("/gift-cards/<card_id>/balance-inquiries")
def list_inquiries(card_id):
    caller = authenticate(["StoreManager", "FraudAnalyst", "RiskManager",
                           "PlatformAdmin"])
    scope_record(caller, db.cards.get(card_id))
    channel = validate.query_enum("channel", INQUIRY_CHANNELS)
    card = require_card(card_id)
    rows = [i for i in db.inquiries.values() if i["card_id"] == card["id"]]
    rows = filter_by(rows, "channel", channel)
    return listing_response(rows, order_keys=["occurred_at"])


@bp.post("/gift-cards/<card_id>/redemptions")
def redeem(card_id):
    caller = authenticate(["PosAssociate"])
    body = validate.body()
    amount = validate.integer(body, "amount_cents", minimum=1)
    merchant_store_id = validate.string(body, "merchant_store_id", min_len=1)
    pos_terminal_id = validate.string(body, "pos_terminal_id", required=False,
                                      min_len=None)
    memo = validate.string(body, "memo", required=False, min_len=None)
    # Store references resolve before the path card (PRD 2.8 tier 5).
    merchant_store = require_store(merchant_store_id)
    card = require_card(card_id)

    if card["activation_state"] != "ACTIVE":
        fail("ERR_CARD_NOT_ACTIVE")
    if card["risk_posture"] == "FROZEN":
        fail("ERR_CARD_FROZEN")
    if merchant_store["floor_posture"] == "SUSPENDED":
        fail("ERR_STORE_FLOOR_SUSPENDED")

    card_svc.recompute(card)
    if amount > card["available_balance_cents"]:
        fail("ERR_INSUFFICIENT_BALANCE")

    event = card_svc.append_event(
        card, "REDEMPTION", amount, caller.user_id,
        merchant_store_id=merchant_store_id, pos_terminal_id=pos_terminal_id,
        memo=memo,
    )
    card_svc.recompute(card)
    card_svc.apply_funding_edges(card)
    dbm.touch(card)
    return response.created(event)


@bp.post("/gift-cards/<card_id>/redemption-holds")
def create_hold(card_id):
    caller = authenticate(["PosAssociate", "RiskManager"])
    body = validate.body()
    amount = validate.integer(body, "amount_cents", minimum=1)
    hold_start = validate.datetime_field(body, "hold_start")
    hold_expires_at = validate.datetime_field(body, "hold_expires_at")
    expected_version = validate.integer(body, "expected_gift_card_version")
    if hold_expires_at <= hold_start:
        fail("ERR_INVALID_REQUEST", "hold_expires_at must be after hold_start.")
    card = require_card(card_id)

    if expected_version != card["version"]:
        fail("ERR_STALE_CARD_VERSION")
    if card["activation_state"] != "ACTIVE":
        fail("ERR_CARD_NOT_ACTIVE")
    if card["risk_posture"] == "FROZEN":
        fail("ERR_CARD_FROZEN")

    card_svc.recompute(card)
    if capacity_exceeded(card, amount, hold_start, hold_expires_at):
        fail("ERR_HOLD_CAPACITY_EXCEEDED")

    hold = dbm.record({
        "card_id": card["id"],
        "amount_cents": amount,
        "hold_start": hold_start,
        "hold_expires_at": hold_expires_at,
        "state": "ACTIVE",
        "disposition": None,
        "settle_note": None,
        "captured_amount_cents": 0,
    })
    db.holds[hold["id"]] = hold
    card_svc.recompute(card)
    dbm.touch(card)
    return response.created(hold)


@bp.get("/gift-cards/<card_id>/redemption-holds")
def list_card_holds(card_id):
    caller = authenticate(READ_ROLES)
    scope_record(caller, db.cards.get(card_id))
    state = validate.query_enum("state", HOLD_STATES)
    card = require_card(card_id)
    rows = [h for h in db.holds.values() if h["card_id"] == card["id"]]
    rows = filter_by(rows, "state", state)
    return listing_response(rows, order_keys=["hold_start"])


@bp.get("/gift-cards/<card_id>/reseller-listings")
def list_card_listings(card_id):
    authenticate(["FraudAnalyst", "RiskManager", "ResellerPartner", "PlatformAdmin"])
    state = validate.query_enum("state", LISTING_STATES)
    card = require_card(card_id)
    rows = [l for l in db.listings.values() if l["card_id"] == card["id"]]
    rows = filter_by(rows, "state", state)
    return listing_response(rows)


@bp.post("/gift-cards/<card_id>/posture")
def override_posture(card_id):
    authenticate(["RiskManager"])
    body = validate.body()
    posture = validate.enum(body, "risk_posture", POSTURES)
    validate.string(body, "reason", min_len=None)
    card = require_card(card_id)
    card["risk_posture"] = posture
    if posture == "FROZEN":
        listing_svc.block_validated_listings(card)
    dbm.touch(card)
    return response.ok(card)


@bp.get("/redemption-holds/<hold_id>")
def get_hold(hold_id):
    authenticate(READ_ROLES)
    return response.ok(require_hold(hold_id))


@bp.post("/redemption-holds/<hold_id>/settle")
def settle_hold(hold_id):
    caller = authenticate(["PosAssociate", "RiskManager"])
    body = validate.body()
    disposition = validate.enum(body, "disposition", DISPOSITIONS)
    merchant_store_id = validate.string(body, "merchant_store_id", required=False,
                                        min_len=1)
    settle_note = validate.string(body, "settle_note", required=False, min_len=None)
    if merchant_store_id is not None:
        require_store(merchant_store_id)
    hold = require_hold(hold_id)
    card = db.cards.get(hold["card_id"])

    if disposition == "CAPTURE" and card is not None:
        if card["activation_state"] != "ACTIVE":
            fail("ERR_CARD_NOT_ACTIVE")
        if card["risk_posture"] == "FROZEN":
            fail("ERR_CARD_FROZEN")
    if hold["state"] != "ACTIVE":
        fail("ERR_INVALID_HOLD_STATE")

    hold["disposition"] = disposition
    hold["settle_note"] = settle_note
    if disposition == "RELEASE":
        hold["state"] = "RELEASED"
        hold["captured_amount_cents"] = 0
    else:
        hold["state"] = "CAPTURED"
        hold["captured_amount_cents"] = hold["amount_cents"]
        card_svc.append_event(
            card, "REDEMPTION", hold["amount_cents"], caller.user_id,
            merchant_store_id=merchant_store_id,
        )
    dbm.touch(hold)
    if card is not None:
        card_svc.recompute(card)
        if disposition == "CAPTURE":
            card_svc.apply_funding_edges(card)
        dbm.touch(card)
    return response.ok(hold)
