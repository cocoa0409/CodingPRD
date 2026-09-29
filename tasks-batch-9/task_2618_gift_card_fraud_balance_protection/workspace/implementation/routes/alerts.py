"""Draining alerts, the confirmation cascade and law-enforcement referrals
(PRD 3.7)."""
import clock
from flask import Blueprint

import db as dbm
import response
import validate
from db import db
from errors import fail
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_alert, require_card, require_referral)
from services import alerts as alert_svc
from services import cards as card_svc
from services import listings as listing_svc
from services import scoring
from services import stores as store_svc
from services.alerts import ALERT_STATES, DETECTION_BASES, RESOLUTIONS

bp = Blueprint("alerts", __name__)


@bp.post("/draining-alerts")
def raise_alert():
    authenticate(["FraudAnalyst", "RiskManager"])
    body = validate.body()
    card_id = validate.string(body, "card_id", min_len=1)
    basis = validate.enum(body, "detection_basis", DETECTION_BASES)
    note = validate.string(body, "note", required=False, min_len=None)
    card = require_card(card_id)
    alert = alert_svc.create_alert(card, basis, note=note)
    # Recompute the store's live alert count and floor posture; a DIGITAL card
    # carries no store, so nothing is touched.
    store_svc.touch_store_for_card(card)
    return response.created(alert)


@bp.get("/draining-alerts")
def list_alerts():
    authenticate(READ_ROLES)
    card_id = validate.query_str("card_id")
    state = validate.query_enum("state", ALERT_STATES)
    basis = validate.query_enum("detection_basis", DETECTION_BASES)
    rows = list(db.alerts.values())
    rows = filter_by(rows, "card_id", card_id)
    rows = filter_by(rows, "state", state)
    rows = filter_by(rows, "detection_basis", basis)
    return listing_response(rows)


@bp.get("/draining-alerts/<alert_id>")
def get_alert(alert_id):
    authenticate(READ_ROLES)
    return response.ok(require_alert(alert_id))


@bp.post("/draining-alerts/<alert_id>/triage")
def triage_alert(alert_id):
    caller = authenticate(["FraudAnalyst"])
    body = validate.body()
    triage_note = validate.string(body, "triage_note", min_len=None)
    reviewed = validate.boolean(body, "redemption_pattern_reviewed")
    alert = require_alert(alert_id)
    if alert["state"] != "OPEN":
        fail("ERR_INVALID_ALERT_STATE")

    policy = dbm.policy()
    card = db.cards.get(alert["card_id"])
    score = 0
    if card is not None:
        card_svc.recompute(card)
        score = scoring.redemption_weighted_score(card)
        card["drain_risk_score_redemption"] = score
        card_svc.escalate_posture(card, card_svc.posture_target(score, policy))
        dbm.touch(card)

    alert["state"] = "TRIAGED"
    alert["triaged_by_user_id"] = caller.user_id
    alert["triage_note"] = triage_note
    alert["redemption_pattern_reviewed"] = reviewed
    alert["basis_drain_score"] = score
    dbm.touch(alert)
    store_svc.touch_store_for_card(card)
    return response.ok(alert)


@bp.post("/draining-alerts/<alert_id>/resolve")
def resolve_alert(alert_id):
    caller = authenticate(["RiskManager"])
    body = validate.body()
    resolution = validate.enum(body, "resolution", RESOLUTIONS)
    resolution_note = validate.string(body, "resolution_note", min_len=None)
    alert = require_alert(alert_id)
    if alert["state"] != "TRIAGED":
        fail("ERR_INVALID_ALERT_STATE")
    if alert["triaged_by_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    card = db.cards.get(alert["card_id"])
    alert["state"] = "CONFIRMED" if resolution == "CONFIRM" else "DISMISSED"
    alert["resolution"] = resolution
    alert["resolved_by_user_id"] = caller.user_id
    alert["resolution_note"] = resolution_note
    dbm.touch(alert)

    if card is not None:
        if resolution == "CONFIRM":
            # HOP 2: forced freeze from whatever rung the card was on.
            card["risk_posture"] = "FROZEN"
            dbm.touch(card)
            # HOP 3: every VALIDATED listing on the card is blocked.
            listing_svc.block_validated_listings(card)
        else:
            if not alert_svc.card_has_live_alert(card["id"],
                                                ignore_alert_id=alert["id"]):
                card["risk_posture"] = "CLEAR"
            dbm.touch(card)
    store_svc.touch_store_for_card(card)
    return response.ok(alert)


@bp.post("/draining-alerts/<alert_id>/reopen")
def reopen_alert(alert_id):
    authenticate(["RiskManager"])
    body = validate.body()
    validate.string(body, "reopen_reason", min_len=None)
    alert = require_alert(alert_id)
    if alert["state"] != "DISMISSED":
        fail("ERR_INVALID_ALERT_STATE")

    alert["state"] = "OPEN"
    alert["resolution"] = None
    alert["resolved_by_user_id"] = None
    alert["resolution_note"] = None
    # triaged_by_user_id is deliberately PRESERVED across the reopen.
    alert["reopen_count"] = alert["reopen_count"] + 1
    dbm.touch(alert)
    card = db.cards.get(alert["card_id"])
    store_svc.touch_store_for_card(card)
    return response.ok(alert)


@bp.get("/draining-alerts/<alert_id>/referrals")
def list_referrals(alert_id):
    authenticate(["FraudAnalyst", "RiskManager", "PlatformAdmin"])
    alert = require_alert(alert_id)
    rows = [r for r in db.referrals.values() if r["alert_id"] == alert["id"]]
    return listing_response(rows)


@bp.post("/law-enforcement-referrals")
def file_referral():
    caller = authenticate(["FraudAnalyst", "RiskManager"])
    body = validate.body()
    alert_id = validate.string(body, "alert_id", min_len=1)
    agency_name = validate.string(body, "agency_name", min_len=1, max_len=120)
    packet_summary = validate.string(body, "packet_summary", min_len=1, max_len=2000)
    case_reference = validate.string(body, "case_reference", required=False,
                                     min_len=None)
    alert = require_alert(alert_id)
    if alert["state"] != "CONFIRMED":
        fail("ERR_ALERT_NOT_CONFIRMED")
    rec = dbm.audit_record({
        "alert_id": alert["id"],
        "agency_name": agency_name,
        "case_reference": case_reference,
        "packet_summary": packet_summary,
        "exposure_snapshot_cents": alert["exposure_cents"],
        "referred_by_user_id": caller.user_id,
        "referred_at": clock.now(),
    })
    db.referrals[rec["id"]] = rec
    return response.created(rec)


@bp.get("/law-enforcement-referrals/<referral_id>")
def get_referral(referral_id):
    authenticate(["FraudAnalyst", "RiskManager", "PlatformAdmin"])
    return response.ok(require_referral(referral_id))
