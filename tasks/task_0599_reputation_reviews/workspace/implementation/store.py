"""In-memory data store, logical clock and serialization helpers.

Everything lives in plain Python dicts keyed by id.  The store starts EMPTY on
every boot: no entity is ever seeded, preloaded or hardcoded here.
"""

import itertools
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- logical clock ---------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": CLOCK_EPOCH}
_seq = itertools.count(1)


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt
    return dt


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


# --- datetime helpers ------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def real_now_iso():
    dt = datetime.now(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


# --- numeric helpers -------------------------------------------------------
TWO = Decimal("0.01")
ZERO2 = Decimal("0.00")


def rhu(value, places=2):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def num(value):
    """Serialize a Decimal money/score value as a JSON number."""
    if value is None:
        return None
    return float(value)


# --- tables ----------------------------------------------------------------
businesses = {}
locations = {}
listings = {}
competitors = {}
contacts = {}
templates = {}
campaigns = {}
review_requests = {}
reviews = {}
review_responses = {}
escalations = {}
surveys = {}
widgets = {}
alerts = {}

ALL_TABLES = (
    businesses, locations, listings, competitors, contacts, templates,
    campaigns, review_requests, reviews, review_responses, escalations,
    surveys, widgets, alerts,
)


def base_record(with_version=True):
    rec = {
        "id": new_id(),
        "created_at": now(),
        "_seq": next_seq(),
    }
    if with_version:
        rec["updated_at"] = now()
        rec["version"] = 1
    return rec


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def by_created(records):
    return sorted(records, key=sort_key)


# --- serializers -----------------------------------------------------------
def _common(rec, with_version=True):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if with_version:
        out["updated_at"] = iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def business_out(b):
    out = _common(b)
    out.update({
        "name": b["name"],
        "plan_tier": b["plan_tier"],
        "default_frequency_cap_days": b["default_frequency_cap_days"],
        "location_count": b["location_count"],
    })
    return out


def location_out(l):
    out = _common(l)
    out.update({
        "business_id": l["business_id"],
        "name": l["name"],
        "nap_name": l["nap_name"],
        "nap_address": l["nap_address"],
        "nap_phone": l["nap_phone"],
        "compliance_hold": l["compliance_hold"],
        "posture": l["posture"],
        "review_count": l["review_count"],
        "avg_rating": num(l["avg_rating"]),
        "responded_review_count": l["responded_review_count"],
        "sentiment_positive_count": l["sentiment_positive_count"],
        "sentiment_neutral_count": l["sentiment_neutral_count"],
        "sentiment_negative_count": l["sentiment_negative_count"],
        "reputation_score_provisional": num(l["reputation_score_provisional"]),
        "reputation_score_certified": num(l["reputation_score_certified"]),
        "certified_at": iso(l["certified_at"]),
        "listing_health_score": num(l["listing_health_score"]),
        "nps_score": num(l["nps_score"]),
        "open_escalation_count": l["open_escalation_count"],
    })
    return out


def listing_out(li):
    out = _common(li)
    out.update({
        "location_id": li["location_id"],
        "site": li["site"],
        "external_listing_id": li["external_listing_id"],
        "listed_nap_name": li["listed_nap_name"],
        "listed_nap_address": li["listed_nap_address"],
        "listed_nap_phone": li["listed_nap_phone"],
        "sync_state": li["sync_state"],
        "sync_failure_count": li["sync_failure_count"],
        "last_synced_at": iso(li["last_synced_at"]),
        "nap_match_count": nap_match_count(li),
    })
    return out


def nap_match_count(li):
    loc = locations.get(li["location_id"])
    if loc is None:
        return 0
    return (
        (1 if li["listed_nap_name"] == loc["nap_name"] else 0)
        + (1 if li["listed_nap_address"] == loc["nap_address"] else 0)
        + (1 if li["listed_nap_phone"] == loc["nap_phone"] else 0)
    )


def competitor_out(c):
    out = _common(c, with_version=False)
    out.update({
        "location_id": c["location_id"],
        "name": c["name"],
        "site": c["site"],
        "avg_rating": num(c["avg_rating"]),
        "review_count": c["review_count"],
    })
    return out


def contact_out(c):
    out = _common(c)
    out.update({
        "business_id": c["business_id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "phone": c["phone"],
        "sms_consent": c["sms_consent"],
        "email_consent": c["email_consent"],
        "opted_out": c["opted_out"],
        "last_requested_at": iso(c["last_requested_at"]),
        "request_count": c["request_count"],
    })
    return out


def template_out(t):
    out = _common(t)
    out.update({
        "business_id": t["business_id"],
        "name": t["name"],
        "body": t["body"],
        "min_rating": t["min_rating"],
        "max_rating": t["max_rating"],
        "requires_approval": t["requires_approval"],
    })
    return out


def campaign_out(c):
    out = _common(c)
    out.update({
        "location_id": c["location_id"],
        "name": c["name"],
        "channel": c["channel"],
        "message_body": c["message_body"],
        "send_window_start": c["send_window_start"],
        "send_window_end": c["send_window_end"],
        "daily_send_cap": c["daily_send_cap"],
        "credits_allocated": c["credits_allocated"],
        "credits_reserved": c["credits_reserved"],
        "credits_consumed": c["credits_consumed"],
        "credits_released": c["credits_released"],
        "status": c["status"],
        "activated_at": iso(c["activated_at"]),
        "sent_count": c["sent_count"],
        "billing_cost": num(c["billing_cost"]),
    })
    return out


def request_out(r):
    out = _common(r)
    out.update({
        "campaign_id": r["campaign_id"],
        "contact_id": r["contact_id"],
        "channel": r["channel"],
        "status": r["status"],
        "send_index": r["send_index"],
        "unit_cost": num(r["unit_cost"]),
        "sent_at": iso(r["sent_at"]),
        "converted_review_id": r["converted_review_id"],
    })
    return out


def review_out(r):
    out = _common(r)
    out.update({
        "location_id": r["location_id"],
        "review_request_id": r["review_request_id"],
        "site": r["site"],
        "external_review_id": r["external_review_id"],
        "author_name": r["author_name"],
        "text": r["text"],
        "rating": r["rating"],
        "posted_at": iso(r["posted_at"]),
        "sentiment": r["sentiment"],
        "moderation_state": r["moderation_state"],
        "response_state": r["response_state"],
    })
    return out


def response_out(r):
    out = _common(r)
    out.update({
        "review_id": r["review_id"],
        "template_id": r["template_id"],
        "body": r["body"],
        "state": r["state"],
        "drafted_by_user_id": r["drafted_by_user_id"],
        "approved_by_user_id": r["approved_by_user_id"],
        "rejection_reason": r["rejection_reason"],
        "revision_count": r["revision_count"],
        "published_at": iso(r["published_at"]),
    })
    return out


def escalation_out(e):
    out = _common(e)
    out.update({
        "review_id": e["review_id"],
        "reason": e["reason"],
        "state": e["state"],
        "acknowledged_by_user_id": e["acknowledged_by_user_id"],
        "resolved_at": iso(e["resolved_at"]),
    })
    return out


def survey_out(s):
    out = _common(s)
    out.update({
        "location_id": s["location_id"],
        "contact_id": s["contact_id"],
        "status": s["status"],
        "nps_score": s["nps_score"],
        "nps_category": s["nps_category"],
        "comment": s["comment"],
        "submitted_at": iso(s["submitted_at"]),
        "expires_at": iso(s["expires_at"]),
    })
    return out


def widget_out(w):
    out = _common(w)
    out.update({
        "location_id": w["location_id"],
        "min_rating": w["min_rating"],
        "max_reviews": w["max_reviews"],
        "status": w["status"],
        "embed_token": w["embed_token"],
        "published_at": iso(w["published_at"]),
    })
    return out


def alert_out(a):
    out = _common(a, with_version=False)
    out.update({
        "location_id": a["location_id"],
        "alert_type": a["alert_type"],
        "severity": a["severity"],
        "message": a["message"],
        "payload_ref_id": a["payload_ref_id"],
    })
    return out
