"""The regulated cancellation flow and its save offers (PRD 3.8)."""
from datetime import timedelta

import config
from clock import clock, parse_date
from db import db
from response import touch
from services.derive import subscription_holds
from services.holds import create_hold, release_holds_after_access_end
from services.pricing import recompute_next_price


def save_offers_of(request_id):
    return [
        o for o in db.save_offers.values() if o.get("cancellation_request_id") == request_id
    ]


def save_offer_tier(projection):
    if projection >= config.SAVE_OFFER_TIER_RICH_AT:
        return "RICH"
    if projection >= config.SAVE_OFFER_TIER_STANDARD_AT:
        return "STANDARD"
    return "MINIMAL"


def expire_presented_offers(request_id):
    for offer in save_offers_of(request_id):
        if offer["status"] == "PRESENTED":
            offer["status"] = "EXPIRED"
            touch(offer)


def confirm(req, sub, plan):
    """The four-hop confirm chain."""
    today = clock.date().isoformat()
    paid_through = sub.get("paid_through_on")

    # hop 1
    req["status"] = "CONFIRMED"
    req["confirmed_on"] = today
    req["effective_on"] = paid_through
    touch(req)
    expire_presented_offers(req["id"])

    # hop 2
    sub["lifecycle_status"] = "CANCEL_SCHEDULED"
    sub["access_until"] = paid_through
    sub["cancel_effective_on"] = paid_through
    if sub["print_fulfillment_status"] in ("SCHEDULED", "HELD", "INTERRUPTED"):
        sub["print_fulfillment_status"] = "STOPPED_AT_CYCLE_END"

    # hop 3
    release_holds_after_access_end(sub, paid_through)

    # hop 4: pending_credit_cents falls by exactly the released holds' credit
    recompute_next_price(sub, plan)
    touch(sub)

    reader = db.readers.get(sub["reader_id"])
    if reader is not None:
        touch(reader)


def accept_offer(offer, req, sub, plan):
    today = clock.date().isoformat()
    offer["status"] = "ACCEPTED"
    offer["decided_on"] = today
    touch(offer)

    req["status"] = "SAVE_OFFER_ACCEPTED"
    req["retained"] = True
    touch(req)

    if offer["offer_type"] in ("RETENTION_DISCOUNT", "DOWNGRADE"):
        sub["retention_discount_pct"] = offer["discount_pct"]
        sub["retention_discount_cycles_remaining"] = offer["duration_cycles"]
    elif offer["offer_type"] == "PAUSE":
        start = sub.get("paid_through_on") or sub["cycle_start_on"]
        start_date = parse_date(start)
        end_date = start_date + timedelta(days=offer["pause_days"] - 1)
        create_hold(
            sub,
            "PAUSE_BILLING",
            start_date.isoformat(),
            end_date.isoformat(),
            0,
            0,
            "SCHEDULED",
        )
    recompute_next_price(sub, plan)
    touch(sub)


def decline_offer(offer, req):
    offer["status"] = "DECLINED"
    offer["decided_on"] = clock.date().isoformat()
    touch(offer)
    req["status"] = "INITIATED"
    touch(req)


def abandon(req):
    req["status"] = "ABANDONED"
    touch(req)
    expire_presented_offers(req["id"])


def complete(req):
    req["status"] = "COMPLETED"
    touch(req)


def requests_of(subscription_id):
    return [
        r for r in db.cancellation_requests.values() if r.get("subscription_id") == subscription_id
    ]


def holds_of(subscription_id):
    return subscription_holds(subscription_id)
