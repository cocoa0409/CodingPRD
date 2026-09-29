"""Price observation capture and advertised-price evaluation (PRD §3.5)."""

from flask import Blueprint

import lookup
from auth import ROLE_MONITORING_ANALYST, STAFF_AND_RESELLER, authenticate, require_owner
from calc import (
    allocate_bundle, effective_advertised_price, governing_permitted_channels,
    resolve_floor, select_governing_policy, violation_points,
)
from envelope import created, ok, ok_list
from errors import fail
from store import days, dt_of, new_row, now_dt, parse_iso, serialize, store, touch
from validate import (
    CHANNELS, body, opt_bool, opt_int, opt_str, req_bundle_components, req_dt, req_enum,
    req_hash, req_int, req_str,
)

bp = Blueprint("observations", __name__)

OBSERVATION_WINDOW_DAYS = 30


@bp.post("/price-observations")
def capture_observation():
    ctx = authenticate([ROLE_MONITORING_ANALYST])
    b = body()
    product_id = req_str(b, "product_id")
    channel = req_enum(b, "channel", CHANNELS)
    seller_display_name = req_str(b, "seller_display_name", 1, None)
    listing_url = req_str(b, "listing_url", 1, None)
    listed_price_cents = req_int(b, "listed_price_cents", 0, None)
    observed_at = req_dt(b, "observed_at")
    evidence_hash = req_hash(b, "evidence_hash")
    marketplace_name = opt_str(b, "marketplace_name", 0, None)
    shipping_cents = opt_int(b, "shipping_cents", 0, None, 0)
    auto_coupon_cents = opt_int(b, "auto_coupon_cents", 0, None, 0)
    promo_code_cents = opt_int(b, "promo_code_cents", 0, None, 0)
    is_bundle = opt_bool(b, "is_bundle", False)
    matched_reseller_id = opt_str(b, "matched_reseller_id", 1, None)

    bundle_total = None
    components = None
    if is_bundle:
        bundle_total = req_int(b, "bundle_total_price_cents", 1, None)
        components = req_bundle_components(b, "bundle_components")

    product = lookup.product(product_id)
    reseller = None
    if matched_reseller_id is not None:
        reseller = lookup.reseller(matched_reseller_id)

    if is_bundle and product["sku"] not in [c["sku"] for c in components]:
        fail("ERR_VALIDATION", "bundle_components must include the observed product's sku.")

    observed_dt = parse_iso(observed_at)
    now = now_dt()
    if observed_dt > now or observed_dt < now - days(OBSERVATION_WINDOW_DAYS):
        fail("ERR_OBSERVATION_STALE",
             "observed_at must lie within the trailing 30 days of the logical clock.")

    if reseller is not None:
        permitted = governing_permitted_channels(reseller["id"])
        if permitted is not None and channel not in permitted:
            fail("ERR_CHANNEL_NOT_PERMITTED",
                 "The observed channel is not permitted for the matched reseller.")

    row = new_row({
        "product_id": product_id,
        "channel": channel,
        "marketplace_name": marketplace_name,
        "seller_display_name": seller_display_name,
        "listing_url": listing_url,
        "listed_price_cents": listed_price_cents,
        "shipping_cents": shipping_cents,
        "auto_coupon_cents": auto_coupon_cents,
        "promo_code_cents": promo_code_cents,
        "is_bundle": is_bundle,
        "bundle_total_price_cents": bundle_total,
        "bundle_components": components,
        "matched_reseller_id": matched_reseller_id,
        "observed_at": observed_at,
        "evidence_hash": evidence_hash,
        "evidence_captured_by_user_id": ctx.user_id,
        "allocated_component_price_cents": None,
        "effective_advertised_price_cents": None,
        "effective_map_floor_cents": None,
        "deviation_cents": None,
        "deviation_pct": None,
        "evaluation_status": "CAPTURED",
        "unauthorized_seller_confirmed": False,
    })
    store.observations[row["id"]] = row
    return created(serialize(row))


@bp.post("/price-observations/<observation_id>/evaluate")
def evaluate_observation(observation_id):
    authenticate([ROLE_MONITORING_ANALYST])
    body()
    observation = lookup.observation(observation_id)
    if observation["evaluation_status"] != "CAPTURED":
        fail("ERR_ALREADY_EVALUATED", "This observation has already been evaluated.")

    observed_dt = dt_of(observation, "observed_at")
    policy = select_governing_policy(observed_dt)
    if policy is None:
        fail("ERR_NO_GOVERNING_POLICY", "No policy governs the observation instant.")

    product = store.products.get(observation["product_id"])
    floor_cents, floor_source, _exception_id = resolve_floor(
        product, observation["channel"], observed_dt, bool(observation.get("is_bundle")))

    if observation.get("is_bundle"):
        observation["allocated_component_price_cents"] = allocate_bundle(
            observation["bundle_components"],
            observation["bundle_total_price_cents"],
            product["sku"],
        )
    advertised = effective_advertised_price(observation, policy)

    violation_id = None
    provisional_points = 0
    if advertised >= floor_cents:
        observation["evaluation_status"] = "EVALUATED_COMPLIANT"
        observation["effective_advertised_price_cents"] = advertised
        observation["effective_map_floor_cents"] = floor_cents
        observation["deviation_cents"] = 0
        observation["deviation_pct"] = 0
    else:
        points, dev_cents, dev_pct = violation_points(
            observation.get("matched_reseller_id"), None, observation["channel"],
            floor_cents, advertised, observed_dt)
        observation["evaluation_status"] = "EVALUATED_BREACH"
        observation["effective_advertised_price_cents"] = advertised
        observation["effective_map_floor_cents"] = floor_cents
        observation["deviation_cents"] = dev_cents
        observation["deviation_pct"] = float(dev_pct)
        provisional_points = points
        if observation.get("matched_reseller_id"):
            violation = new_row({
                "observation_id": observation["id"],
                "reseller_id": observation["matched_reseller_id"],
                "cited_policy_id": policy["id"],
                "status": "DETECTED",
                "provisional_floor_cents": floor_cents,
                "provisional_points": points,
                "assessed_floor_cents": None,
                "assessed_points": None,
                "cure_deadline_at": None,
                "dispute_rounds": 0,
                "dispute_reason": None,
                "resolution_reason": None,
            })
            store.violations[violation["id"]] = violation
            violation_id = violation["id"]
    touch(observation)

    return ok({
        "observation_id": observation["id"],
        "evaluation_status": observation["evaluation_status"],
        "allocated_component_price_cents": observation["allocated_component_price_cents"],
        "effective_advertised_price_cents": observation["effective_advertised_price_cents"],
        "effective_map_floor_cents": observation["effective_map_floor_cents"],
        "floor_source": floor_source,
        "deviation_cents": observation["deviation_cents"],
        "deviation_pct": observation["deviation_pct"],
        "cited_policy_id": policy["id"],
        "violation_id": violation_id,
        "provisional_points": provisional_points,
        "unauthorized_seller_confirmed": observation["unauthorized_seller_confirmed"],
    })


@bp.get("/price-observations/<observation_id>")
def read_observation(observation_id):
    ctx = authenticate(STAFF_AND_RESELLER)
    row = lookup.observation(observation_id)
    require_owner(ctx, row, reseller_field="matched_reseller_id")
    return ok(serialize(row))


@bp.get("/price-observations")
def list_observations():
    authenticate(STAFF_AND_RESELLER)
    rows = lookup.filtered("observations", {
        "product_id": "product_id",
        "matched_reseller_id": "matched_reseller_id",
        "evaluation_status": "evaluation_status",
        "channel": "channel",
    })
    return ok_list(rows)
