"""Location reads, NAP replacement, compliance hold, certify, dashboard, alerts."""

from flask import Blueprint

import calc
import store
import validation as v
from auth import endpoint, resolve_location
from envelope import created, ok, paginate
from errors import err
from services import (ALERT_TYPES, assert_not_frozen, recompute_location,
                      suppress_queued_requests, touch)

bp = Blueprint("locations", __name__)


@bp.get("/reputation/locations/<location_id>")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager", "ResponseAgent", "ComplianceOfficer"])
def get_location(location_id):
    loc = resolve_location(location_id)
    return ok(store.location_out(loc))


@bp.put("/reputation/locations/<location_id>/nap")
@endpoint(["PlatformAdmin", "BusinessOwner"])
def replace_nap(location_id):
    loc = resolve_location(location_id)
    data = v.body()
    nap_name = v.req_str(data, "nap_name")
    nap_address = v.req_str(data, "nap_address")
    nap_phone = v.req_str(data, "nap_phone")

    assert_not_frozen(loc)

    loc["nap_name"] = nap_name
    loc["nap_address"] = nap_address
    loc["nap_phone"] = nap_phone

    # Every CONNECTED listing falls back to PENDING_SYNC; the sites' published
    # copies are deliberately left untouched, so their match counts drop.
    for li in store.listings.values():
        if li["location_id"] == loc["id"] and li["sync_state"] == "CONNECTED":
            li["sync_state"] = "PENDING_SYNC"
            touch(li)

    touch(loc)
    recompute_location(loc)
    return ok(store.location_out(loc))


@bp.post("/reputation/locations/<location_id>/compliance-hold")
@endpoint(["PlatformAdmin"])
def compliance_hold(location_id):
    loc = resolve_location(location_id)
    data = v.body()
    on_hold = v.req_bool(data, "on_hold")

    if on_hold == loc["compliance_hold"]:
        raise err("ERR_INVALID_STATE")

    loc["compliance_hold"] = on_hold
    touch(loc)

    if on_hold:
        # recompute_location drives posture to FROZEN, appends POSTURE_CHANGED
        # and system-pauses every RUNNING campaign (emptying its queue).
        recompute_location(loc)
        for w in store.widgets.values():
            if w["location_id"] == loc["id"] and w["status"] == "PUBLISHED":
                w["status"] = "DRAFT"
                w["published_at"] = None
                touch(w)
    else:
        recompute_location(loc)

    return ok(store.location_out(loc))


@bp.post("/reputation/locations/<location_id>/certify")
@endpoint(["PlatformAdmin", "BusinessOwner"])
def certify(location_id):
    loc = resolve_location(location_id)
    assert_not_frozen(loc)

    loc["reputation_score_certified"] = calc.reputation_score_certified(loc)
    loc["certified_at"] = store.now()
    touch(loc)
    return ok(store.location_out(loc))


@bp.get("/reputation/locations/<location_id>/dashboard")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def dashboard(location_id):
    loc = resolve_location(location_id)
    bench = calc.competitor_benchmark(loc)
    return ok({
        "posture": loc["posture"],
        "review_count": loc["review_count"],
        "avg_rating": store.num(loc["avg_rating"]),
        "sentiment_positive_count": loc["sentiment_positive_count"],
        "sentiment_neutral_count": loc["sentiment_neutral_count"],
        "sentiment_negative_count": loc["sentiment_negative_count"],
        "reputation_score_provisional": store.num(loc["reputation_score_provisional"]),
        "reputation_score_certified": store.num(loc["reputation_score_certified"]),
        "listing_health_score": store.num(loc["listing_health_score"]),
        "nps_score": store.num(loc["nps_score"]),
        "open_escalation_count": loc["open_escalation_count"],
        "responded_review_count": loc["responded_review_count"],
        "competitor_avg_rating": store.num(bench["competitor_avg_rating"]),
        "rating_delta": store.num(bench["rating_delta"]),
        "review_volume_delta": bench["review_volume_delta"],
    })


@bp.get("/reputation/locations/<location_id>/alerts")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def list_alerts(location_id):
    resolve_location(location_id)
    alert_type = v.enum_filter("alert_type", ALERT_TYPES)
    rows = [a for a in store.alerts.values() if a["location_id"] == location_id]
    if alert_type is not None:
        rows = [a for a in rows if a["alert_type"] == alert_type]
    return paginate(store.by_created(rows), store.alert_out)


@bp.post("/reputation/locations/<location_id>/competitors")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def create_competitor(location_id):
    loc = resolve_location(location_id)
    data = v.body()
    name = v.req_str(data, "name")
    site = v.req_enum(data, "site", v.SITES)
    avg_rating = v.req_decimal(data, "avg_rating", minimum=1, maximum=5)
    review_count = v.req_int(data, "review_count", minimum=0)

    assert_not_frozen(loc)

    rec = store.base_record(with_version=False)
    rec.update({
        "location_id": location_id,
        "name": name,
        "site": site,
        "avg_rating": avg_rating,
        "review_count": review_count,
    })
    store.competitors[rec["id"]] = rec
    return created(store.competitor_out(rec))


@bp.get("/reputation/locations/<location_id>/competitors")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def list_competitors(location_id):
    resolve_location(location_id)
    rows = [c for c in store.competitors.values() if c["location_id"] == location_id]
    return paginate(store.by_created(rows), store.competitor_out)
