"""Draining alert creation and the exposure snapshot (PRD 3.7)."""
import db as dbm
from db import db
from services import cards as card_svc

ALERT_STATES = ("OPEN", "TRIAGED", "CONFIRMED", "DISMISSED")
DETECTION_BASES = ("INQUIRY_VELOCITY", "REDEMPTION_PATTERN", "RESELLER_SIGNAL",
                   "MANUAL_REVIEW")
RESOLUTIONS = ("CONFIRM", "DISMISS")


def exposure_snapshot(card):
    """current_balance_cents + total_redeemed_cents, frozen at creation."""
    return card["current_balance_cents"] + card["total_redeemed_cents"]


def create_alert(card, detection_basis, note=None, basis_velocity_count=0):
    card_svc.recompute(card)
    rec = dbm.record({
        "card_id": card["id"],
        "detection_basis": detection_basis,
        "state": "OPEN",
        "exposure_cents": exposure_snapshot(card),
        "basis_velocity_count": basis_velocity_count,
        "basis_drain_score": 0,
        "note": note,
        "redemption_pattern_reviewed": None,
        "triaged_by_user_id": None,
        "triage_note": None,
        "resolution": None,
        "resolved_by_user_id": None,
        "resolution_note": None,
        "reopen_count": 0,
    })
    db.alerts[rec["id"]] = rec
    return rec


def has_open_velocity_alert(card_id):
    for alert in db.alerts.values():
        if (alert["card_id"] == card_id
                and alert["detection_basis"] == "INQUIRY_VELOCITY"
                and alert["state"] in ("OPEN", "TRIAGED")):
            return True
    return False


def card_has_live_alert(card_id, ignore_alert_id=None):
    for alert in db.alerts.values():
        if ignore_alert_id is not None and alert["id"] == ignore_alert_id:
            continue
        if alert["card_id"] == card_id and alert["state"] in ("OPEN", "TRIAGED"):
            return True
    return False
