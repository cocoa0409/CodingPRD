"""Issuance requests: opening, screening and manual decision (PRD 3.2)."""
from flask import Blueprint

import clock
import db as dbm
import response
import validate
from db import db
from errors import fail
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_bulk_order, require_card, require_issuance,
                           require_rack, require_store, scope_record)
from services import cards as card_svc
from services import scoring
from services import stores as store_svc
from services.cards import CHANNELS
from services.scoring import PAYMENT_BANDS

bp = Blueprint("issuance", __name__)

ISSUANCE_STATES = ("SUBMITTED", "HELD_FOR_REVIEW", "APPROVED", "DECLINED")


def _store_of(request_rec):
    store_id = request_rec.get("store_id")
    return db.stores.get(store_id) if store_id else None


def _rack_of(request_rec):
    rack_id = request_rec.get("rack_id")
    return db.racks.get(rack_id) if rack_id else None


def _fund_approved(request_rec, caller):
    """The APPROVED funding path shared by the automatic fork and the manual
    decision: mint for DIGITAL, then INACTIVE -> ACTIVE with the load event."""
    if request_rec["channel"] == "DIGITAL":
        card = card_svc.new_card("DIGITAL")
        request_rec["card_id"] = card["id"]
    else:
        card = db.cards.get(request_rec.get("card_id"))
    if card is None or card["activation_state"] != "INACTIVE":
        return card
    card["activation_state"] = "ACTIVE"
    card["face_value_cents"] = request_rec["face_value_cents"]
    card["activated_at"] = clock.now()
    card["rack_id"] = None
    card_svc.append_event(card, "ACTIVATION_LOAD", request_rec["face_value_cents"],
                          caller.user_id)
    card_svc.recompute(card)
    dbm.touch(card)
    return card


def _record_decline(request_rec, reason):
    request_rec["state"] = "DECLINED"
    request_rec["decline_reason"] = reason
    store = _store_of(request_rec)
    if store is not None:
        store["declined_issuance_count"] = store.get("declined_issuance_count", 0) + 1
        store_svc.touch_store(store)


@bp.post("/issuance-requests")
def open_request():
    caller = authenticate(["PosAssociate"])
    body = validate.body()
    channel = validate.enum(body, "channel", CHANNELS)
    face_value = validate.integer(body, "face_value_cents", minimum=1)
    if face_value < 100 or face_value > 500000:
        fail("ERR_INVALID_REQUEST", "face_value_cents must be between 100 and 500000.")
    bulk_order_id = validate.string(body, "bulk_order_id", required=False, min_len=1)

    if channel == "PHYSICAL":
        store_id = validate.string(body, "store_id", min_len=1)
        rack_id = validate.string(body, "rack_id", min_len=1)
        card_id = validate.string(body, "card_id", min_len=1)
        pos_terminal_id = validate.string(body, "pos_terminal_id", min_len=None)
        seal_intact = validate.boolean(body, "packaging_seal_intact")
        device_score = None
        email_age = None
        payment_band = None
        email_hash = None
    else:
        validate.absent(body, "store_id")
        validate.absent(body, "rack_id")
        validate.absent(body, "card_id")
        store_id = None
        rack_id = None
        card_id = None
        pos_terminal_id = validate.string(body, "pos_terminal_id", required=False,
                                         min_len=None)
        seal_intact = validate.boolean(body, "packaging_seal_intact", required=False)
        device_score = validate.integer(body, "device_reputation_score", minimum=0,
                                        maximum=100)
        email_age = validate.integer(body, "email_age_days", minimum=0)
        payment_band = validate.enum(body, "payment_risk_band", PAYMENT_BANDS)
        email_hash = validate.string(body, "recipient_email_hash", min_len=1)

    store = require_store(store_id) if store_id else None
    rack = require_rack(rack_id) if rack_id else None
    if card_id:
        require_card(card_id)
    if bulk_order_id:
        require_bulk_order(bulk_order_id)

    if channel == "PHYSICAL":
        if seal_intact is not True:
            fail("ERR_PACKAGING_SEAL_BROKEN")
        if rack is not None and rack["tamper_state"] != "INTACT":
            fail("ERR_RACK_TAMPERED")
    if store is not None and store["floor_posture"] == "SUSPENDED":
        fail("ERR_STORE_FLOOR_SUSPENDED")

    rec = dbm.record({
        "channel": channel,
        "store_id": store_id,
        "rack_id": rack_id,
        "card_id": card_id,
        "bulk_order_id": bulk_order_id,
        "pos_terminal_id": pos_terminal_id,
        "packaging_seal_intact": seal_intact,
        "face_value_cents": face_value,
        "device_reputation_score": device_score,
        "email_age_days": email_age,
        "payment_risk_band": payment_band,
        "recipient_email_hash": email_hash,
        "state": "SUBMITTED",
        "screening_score": None,
        "screening_components": None,
        "decline_reason": None,
        "review_note": None,
        "decided_by_user_id": None,
        "screened_at": None,
    })
    db.issuances[rec["id"]] = rec
    return response.created(rec)


@bp.get("/issuance-requests")
def list_requests():
    authenticate(READ_ROLES)
    store_id = validate.query_str("store_id")
    rack_id = validate.query_str("rack_id")
    card_id = validate.query_str("card_id")
    bulk_order_id = validate.query_str("bulk_order_id")
    channel = validate.query_enum("channel", CHANNELS)
    state = validate.query_enum("state", ISSUANCE_STATES)
    rows = list(db.issuances.values())
    rows = filter_by(rows, "store_id", store_id)
    rows = filter_by(rows, "rack_id", rack_id)
    rows = filter_by(rows, "card_id", card_id)
    rows = filter_by(rows, "bulk_order_id", bulk_order_id)
    rows = filter_by(rows, "channel", channel)
    rows = filter_by(rows, "state", state)
    return listing_response(rows)


@bp.get("/issuance-requests/<request_id>")
def get_request(request_id):
    caller = authenticate(READ_ROLES)
    scope_record(caller, db.issuances.get(request_id))
    return response.ok(require_issuance(request_id))


@bp.post("/issuance-requests/<request_id>/screen")
def screen_request(request_id):
    caller = authenticate(["PosAssociate", "StoreManager", "FraudAnalyst",
                           "PlatformAdmin"])
    scope_record(caller, db.issuances.get(request_id))
    request_rec = require_issuance(request_id)
    policy = dbm.policy()

    if request_rec["state"] != "SUBMITTED":
        fail("ERR_INVALID_ISSUANCE_STATE")

    store = _store_of(request_rec)
    rack = _rack_of(request_rec)
    if request_rec["channel"] == "PHYSICAL":
        if request_rec.get("packaging_seal_intact") is not True:
            fail("ERR_PACKAGING_SEAL_BROKEN")
        if rack is not None and rack["tamper_state"] != "INTACT":
            fail("ERR_RACK_TAMPERED")
    if store is not None and store["floor_posture"] == "SUSPENDED":
        fail("ERR_STORE_FLOOR_SUSPENDED")

    if request_rec["channel"] == "PHYSICAL":
        outcome = "APPROVED" if store is not None and store["floor_posture"] == "OPEN" \
            else "HELD_FOR_REVIEW"
    else:
        score, components = scoring.digital_screening(request_rec)
        request_rec["screening_score"] = score
        request_rec["screening_components"] = components
        outcome = scoring.digital_disposition(score, policy)

    request_rec["state"] = outcome
    request_rec["screened_at"] = clock.now()

    if outcome == "APPROVED":
        _fund_approved(request_rec, caller)
    elif outcome == "HELD_FOR_REVIEW":
        if request_rec["channel"] == "PHYSICAL":
            card = db.cards.get(request_rec.get("card_id"))
            if card is not None and card_svc.escalate_posture(card, "WATCH"):
                dbm.touch(card)
    else:
        _record_decline(request_rec, "DIGITAL_RISK_SCORE")

    dbm.touch(request_rec)
    return response.ok(request_rec)


@bp.post("/issuance-requests/<request_id>/decide")
def decide_request(request_id):
    caller = authenticate(["StoreManager", "RiskManager"])
    scope_record(caller, db.issuances.get(request_id))
    body = validate.body()
    decision = validate.enum(body, "decision", ("APPROVE", "DECLINE"))
    review_note = validate.string(body, "review_note", required=False, min_len=None)
    request_rec = require_issuance(request_id)

    if request_rec["state"] not in ("SUBMITTED", "HELD_FOR_REVIEW"):
        fail("ERR_INVALID_ISSUANCE_STATE")

    store = _store_of(request_rec)
    rack = _rack_of(request_rec)
    if decision == "APPROVE":
        if request_rec["channel"] == "PHYSICAL" and rack is not None \
                and rack["tamper_state"] != "INTACT":
            fail("ERR_RACK_TAMPERED")
        # A HEIGHTENED floor is tolerated here; only SUSPENDED blocks.
        if store is not None and store["floor_posture"] == "SUSPENDED":
            fail("ERR_STORE_FLOOR_SUSPENDED")
        request_rec["state"] = "APPROVED"
        request_rec["decline_reason"] = None
        request_rec["decided_by_user_id"] = caller.user_id
        request_rec["review_note"] = review_note
        _fund_approved(request_rec, caller)
    else:
        request_rec["decided_by_user_id"] = caller.user_id
        request_rec["review_note"] = review_note
        _record_decline(request_rec, "MANUAL_DECLINE")

    dbm.touch(request_rec)
    return response.ok(request_rec)
