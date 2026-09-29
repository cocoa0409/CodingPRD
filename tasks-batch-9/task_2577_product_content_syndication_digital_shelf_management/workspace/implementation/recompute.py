"""Derived-field recomputation, cascade helpers and alert plumbing.

Derived (score / ledger / projection) writes do not advance a row's `version`;
only genuine state or reference writes do, exactly where the PRD says so.
"""
from decimal import Decimal

import calc
from store import base_row, db, now, touch


# ------------------------------------------------------------------ listing
def recompute_listing_completeness(listing):
    detail = calc.completeness_detail(listing)
    listing["completeness_score_declared"] = detail["declared_score"]
    listing["completeness_score_certified"] = detail["certified_score"]
    recompute_listing_readiness(listing)
    return detail


def recompute_listing_declared(listing):
    detail = calc.completeness_detail(listing)
    listing["completeness_score_declared"] = detail["declared_score"]
    return detail


def recompute_listing_readiness(listing):
    listing["readiness_score"] = calc.readiness_score(listing)
    return listing["readiness_score"]


def recompute_listing_blocking(listing):
    listing["open_blocking_error_count"] = calc.open_blocking_error_count(listing["id"])
    return listing["open_blocking_error_count"]


def recompute_listing_projection(listing):
    """calculations.listing_shelf_projection -- latest by (observed_at, created_at)."""
    rows = calc.observations_of_listing(listing["id"])
    if not rows:
        return None
    latest = sorted(rows, key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]))[-1]
    listing["search_rank_latest"] = latest["search_rank"]
    listing["content_accuracy_pct"] = latest["content_accuracy_pct"]
    listing["rating_avg"] = latest["rating_avg"]
    listing["in_stock"] = latest["in_stock"]
    return latest


def set_syndication_state(listing, state):
    if listing.get("syndication_state") == state:
        return False
    listing["syndication_state"] = state
    touch(listing)
    return True


def set_shelf_state(listing, state):
    if listing.get("shelf_state") == state:
        return False
    listing["shelf_state"] = state
    touch(listing)
    return True


def settle_syndication_state_after_release(listing):
    """Where a listing loses its last holding job (cancel / invalidate)."""
    recompute_listing_blocking(listing)
    holding = [j for j in calc.jobs_of_listing(listing["id"])
               if j["state"] in calc.HOLDING_JOB_STATES]
    if int(listing["open_blocking_error_count"]) > 0:
        set_syndication_state(listing, "ERROR_HOLD")
    elif not holding:
        set_syndication_state(listing, "NOT_SYNDICATED")


# ------------------------------------------------------------------ retailer
def recompute_retailer_slots(retailer):
    retailer["feed_slots_reserved"] = calc.feed_slots_reserved(retailer["id"])
    return retailer["feed_slots_reserved"]


def bump_retailer_ledger(retailer):
    """A job state write: recompute the ledger and advance the retailer version."""
    recompute_retailer_slots(retailer)
    touch(retailer)


# ------------------------------------------------------------ content version
def recompute_pin_count(content_version):
    if content_version is None:
        return None
    content_version["pin_count"] = calc.pin_count(content_version["id"])
    return content_version["pin_count"]


# ------------------------------------------------------------------- product
def recompute_product_health(product):
    index, _ = calc.shelf_health(product["id"])
    product["shelf_health_index"] = index
    return index


def recompute_product_lift(product):
    lift, _, _ = calc.conversion_lift(product, "post_pin_window")
    product["conversion_lift_pct"] = lift
    return lift


def recompute_product_alerts(product):
    """calculations.alert_rollup -- pinned governance_flag precedence."""
    open_alerts = []
    for listing in calc.listings_of_product(product["id"]):
        for alert in calc.alerts_of_listing(listing["id"]):
            if alert["state"] in calc.OPEN_ALERT_STATES:
                open_alerts.append(alert)
    product["open_alert_count"] = len(open_alerts)
    if any(a["alert_type"] == "UNAUTHORIZED_LISTING" for a in open_alerts):
        product["governance_flag"] = "LISTING_RISK"
    elif len(open_alerts) >= 1:
        product["governance_flag"] = "CONTENT_AT_RISK"
    else:
        product["governance_flag"] = "NONE"
    return product["open_alert_count"]


def recompute_product_scores_for_retailer(retailer_id):
    """PATCH retailer / requirement declaration fan-out."""
    touched_products = []
    for listing in calc.listings_of_retailer(retailer_id):
        recompute_listing_completeness(listing)
        if listing["product_id"] not in touched_products:
            touched_products.append(listing["product_id"])
    for product_id in touched_products:
        product = db.products.get(product_id)
        if product is not None:
            recompute_product_health(product)


def recompute_product_listings_completeness(product_id):
    for listing in calc.listings_of_product(product_id):
        recompute_listing_completeness(listing)


# -------------------------------------------------------------------- alerts
ALERT_SEVERITY = {
    "OUT_OF_STOCK": "MEDIUM",
    "UNAUTHORIZED_LISTING": "HIGH",
    "CONTENT_DRIFT": "LOW",
    "HEALTH_DEGRADED": "MEDIUM",
}


def has_open_alert(listing_id, alert_type):
    for alert in calc.alerts_of_listing(listing_id):
        if alert["alert_type"] == alert_type and alert["state"] in calc.OPEN_ALERT_STATES:
            return True
    return False


def raise_alert(listing, alert_type, source_observation_id=None):
    """De-duplicated against OPEN/ACKNOWLEDGED alerts of the same type."""
    if has_open_alert(listing["id"], alert_type):
        return None
    alert = base_row()
    alert.update({
        "retailer_listing_id": listing["id"],
        "source_observation_id": source_observation_id,
        "alert_type": alert_type,
        "severity": ALERT_SEVERITY[alert_type],
        "state": "OPEN",
        "assigned_account_team_user_id": listing.get("account_team_user_id"),
        "acknowledged_by_user_id": None,
        "resolution_note": None,
        "resolved_at": None,
    })
    db.alerts[alert["id"]] = alert
    return alert


def auto_resolve_alerts(listing, alert_type, note):
    closed = []
    for alert in calc.alerts_of_listing(listing["id"]):
        if alert["alert_type"] != alert_type:
            continue
        if alert["state"] not in calc.OPEN_ALERT_STATES:
            continue
        alert["state"] = "RESOLVED"
        alert["resolution_note"] = note
        alert["resolved_at"] = now()
        touch(alert)
        closed.append(alert)
    return closed


def maybe_health_degraded(listing, product):
    """Only when the listing is inside the product's health input set."""
    if listing.get("syndication_state") not in calc.HEALTH_SYNDICATION_STATES:
        return None
    index = calc.dec(product.get("shelf_health_index") or 0)
    if index >= calc.HEALTH_ALERT_THRESHOLD:
        return None
    return raise_alert(listing, "HEALTH_DEGRADED", None)
