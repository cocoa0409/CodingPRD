"""Recomputation chain, cascades and shared state-machine side effects."""

from decimal import Decimal

from flask import g

import calc
import store
from errors import err
from store import rhu

D0 = Decimal("0")

ALERT_SEVERITY = {
    "NEGATIVE_REVIEW": "WARNING",
    "LISTING_SYNC_FAILED": "WARNING",
    "NPS_DETRACTOR": "WARNING",
    "POSTURE_CHANGED": "CRITICAL",
    "SEND_CAP_REACHED": "INFO",
}

ALERT_TYPES = tuple(ALERT_SEVERITY)


# --- mutation bookkeeping --------------------------------------------------
def touch(record):
    """Bump version + updated_at once per request for this record."""
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if record["id"] in touched:
        return
    touched.add(record["id"])
    record["version"] += 1
    record["updated_at"] = store.now()


def add_alert(location_id, alert_type, message, payload_ref_id):
    rec = store.base_record(with_version=False)
    rec.update({
        "location_id": location_id,
        "alert_type": alert_type,
        "severity": ALERT_SEVERITY[alert_type],
        "message": message,
        "payload_ref_id": payload_ref_id,
    })
    store.alerts[rec["id"]] = rec
    return rec


# --- posture gates ---------------------------------------------------------
def assert_not_frozen(location):
    if location["posture"] == "FROZEN":
        raise err("ERR_LOCATION_FROZEN")


def assert_open(location):
    if location["posture"] == "FROZEN":
        raise err("ERR_LOCATION_FROZEN")
    if location["posture"] == "RESTRICTED":
        raise err("ERR_LOCATION_RESTRICTED")


# --- the recomputation chain (PRD 2.6) -------------------------------------
DERIVED_FIELDS = (
    "review_count", "avg_rating", "responded_review_count",
    "sentiment_positive_count", "sentiment_neutral_count", "sentiment_negative_count",
    "open_escalation_count", "listing_health_score", "reputation_score_provisional",
    "nps_score", "posture",
)


def _snapshot(location):
    return tuple(location[f] for f in DERIVED_FIELDS)


def _refresh_counters(location):
    reviews = calc.location_reviews(location)
    active = [r for r in reviews if r["moderation_state"] in ("UNVERIFIED", "VERIFIED")]
    location["review_count"] = len(active)
    if active:
        total = sum((Decimal(r["rating"]) for r in active), D0)
        location["avg_rating"] = rhu(total / Decimal(len(active)), 2)
    else:
        location["avg_rating"] = Decimal("0.00")
    location["responded_review_count"] = sum(1 for r in active if r["response_state"] == "RESPONDED")
    location["sentiment_positive_count"] = sum(1 for r in active if r["sentiment"] == "POSITIVE")
    location["sentiment_neutral_count"] = sum(1 for r in active if r["sentiment"] == "NEUTRAL")
    location["sentiment_negative_count"] = sum(1 for r in active if r["sentiment"] == "NEGATIVE")

    review_ids = {r["id"] for r in reviews}
    location["open_escalation_count"] = sum(
        1 for e in store.escalations.values()
        if e["review_id"] in review_ids and e["state"] in ("OPEN", "ACKNOWLEDGED")
    )


def recompute_location(location):
    """Counters -> listing_health_score -> reputation_score_provisional -> posture."""
    before = _snapshot(location)
    old_posture = location["posture"]

    _refresh_counters(location)
    location["listing_health_score"] = calc.listing_health_score(location)
    location["reputation_score_provisional"] = calc.reputation_score_provisional(location)
    location["nps_score"] = calc.location_nps_score(location)

    new_posture = calc.derive_posture(location)
    location["posture"] = new_posture

    if new_posture != old_posture:
        add_alert(location["id"], "POSTURE_CHANGED",
                  "posture %s -> %s" % (old_posture, new_posture), location["id"])

    if new_posture != "OPEN":
        system_pause_campaigns(location)

    if _snapshot(location) != before:
        touch(location)


def recompute_nps(location):
    """Survey submission only feeds nps_score; posture inputs are untouched."""
    before = location["nps_score"]
    location["nps_score"] = calc.location_nps_score(location)
    if location["nps_score"] != before:
        touch(location)


# --- cascades --------------------------------------------------------------
def suppress_queued_requests(campaign):
    """Every QUEUED request -> SUPPRESSED; each releases its reserved credit."""
    for req in calc.campaign_requests(campaign):
        if req["status"] != "QUEUED":
            continue
        req["status"] = "SUPPRESSED"
        touch(req)
        campaign["credits_reserved"] -= 1
        campaign["credits_released"] += 1
    touch(campaign)


def system_pause_campaigns(location):
    """Posture left OPEN: RUNNING campaigns are paused AND their queues emptied."""
    for campaign in store.campaigns.values():
        if campaign["location_id"] != location["id"]:
            continue
        if campaign["status"] != "RUNNING":
            continue
        campaign["status"] = "PAUSED"
        touch(campaign)
        suppress_queued_requests(campaign)


def open_escalation(review):
    rec = store.base_record()
    rec.update({
        "review_id": review["id"],
        "reason": "NEGATIVE_SENTIMENT",
        "state": "OPEN",
        "acknowledged_by_user_id": None,
        "resolved_at": None,
    })
    store.escalations[rec["id"]] = rec
    return rec


def review_escalations(review):
    return store.by_created([e for e in store.escalations.values()
                             if e["review_id"] == review["id"]])


def cancel_open_escalations(review):
    for e in review_escalations(review):
        if e["state"] in ("OPEN", "ACKNOWLEDGED"):
            e["state"] = "CANCELLED"
            touch(e)


def resolve_open_escalations(review):
    for e in review_escalations(review):
        if e["state"] in ("OPEN", "ACKNOWLEDGED"):
            e["state"] = "RESOLVED"
            e["resolved_at"] = store.now()
            touch(e)


# --- campaign billing refresh ---------------------------------------------
def refresh_campaign_billing(campaign):
    campaign["sent_count"] = len(calc.billable_requests(campaign))
    campaign["billing_cost"] = calc.campaign_billing_cost(campaign)


def business_of_location(location):
    return store.businesses[location["business_id"]]
