"""Property endpoints + offer issuance/re-issue + withdraw (PRD §3.1-§3.3)."""

import datetime

from flask import Blueprint, request

from calculations import (
    compute_avm,
    compute_estimated_concession,
    compute_preliminary_net_proceeds,
    compute_service_fee,
)
from constants import (
    DEFAULT_SERVICE_FEE_PCT,
    MIN_OFFER_VALUE,
    OFFER_TTL_DAYS,
)
from db import store
from errors import err
from helpers import (
    get_property_or_404,
    get_seller_or_404,
    pagination_params,
    paginate,
    require_property_owner,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response
from validators import as_int, as_number, as_string, get_body, require

bp = Blueprint("properties", __name__)


@bp.route("/properties", methods=["POST"])
def create_property():
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst"})

    body = get_body(request)
    seller_id = as_string(require(body, "seller_id"), "seller_id")
    address_line = as_string(require(body, "address_line"), "address_line")
    zip_code = as_string(require(body, "zip_code"), "zip_code")
    bedrooms = as_int(require(body, "bedrooms"), "bedrooms", minimum=0)
    living_area_sqft = as_int(require(body, "living_area_sqft"), "living_area_sqft", minimum=1)
    comp_median_value = as_number(require(body, "comp_median_value"), "comp_median_value", minimum=0)

    market_trend_pct = 0.0
    if body.get("market_trend_pct") is not None:
        market_trend_pct = as_number(
            body["market_trend_pct"], "market_trend_pct", minimum=-0.50, maximum=0.50
        )

    # FK existence (priority 3)
    get_seller_or_404(seller_id)

    avm_value = compute_avm(comp_median_value, market_trend_pct)

    rec = {
        "seller_id": seller_id,
        "address_line": address_line,
        "zip_code": zip_code,
        "bedrooms": bedrooms,
        "living_area_sqft": living_area_sqft,
        "comp_median_value": comp_median_value,
        "market_trend_pct": market_trend_pct,
        "avm_value": avm_value,
        "revised_avm_value": None,
        "condition_score": None,
        "status": "VALUED",
        "active_offer_id": None,
    }
    stamp_create(rec)
    store.properties[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/properties", methods=["GET"])
def list_properties():
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})

    seller_filter = request.args.get("seller_id")
    status_filter = request.args.get("status")
    records = list(store.properties.values())
    if seller_filter is not None:
        records = [r for r in records if r["seller_id"] == seller_filter]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]

    limit, offset = pagination_params()
    page, total = paginate(records, limit, offset)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/properties/<prop_id>", methods=["GET"])
def get_property(prop_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    rec = get_property_or_404(prop_id)
    return object_response(serialize(rec), 200)


@bp.route("/properties/<prop_id>/offers", methods=["POST"])
def create_offer(prop_id):
    _uid, role = authenticate()
    require_role(role, {"PricingAnalyst"})

    prop = get_property_or_404(prop_id)
    body = get_body(request)

    service_fee_pct = DEFAULT_SERVICE_FEE_PCT
    if body.get("service_fee_pct") is not None:
        service_fee_pct = as_number(
            body["service_fee_pct"], "service_fee_pct", minimum=0, maximum=0.15
        )

    # An offer-POST is a re-issue whenever the property already has an active offer
    # bound (PRD §3.2: a re-issue "replaces the offer"). A property with a non-null
    # active_offer_id whose active offer is ACCEPTED/SUPERSEDED is precisely the case
    # the PRD's re-issuability check (ERR_OFFER_NOT_REISSUABLE) governs, even though
    # the property has by then advanced to IN_TRANSACTION; routing on active_offer_id
    # keeps that PRD sentence reachable. A first issuance is one with no active offer.
    is_reissue = prop["active_offer_id"] is not None

    if not is_reissue:
        # First issuance: must be VALUED with no active offer (priority 5 state)
        if prop["status"] != "VALUED":
            raise err("ERR_INVALID_STATE", "Property is not in VALUED state for first offer")
        # Min offerable value (priority 8)
        if prop["avm_value"] < MIN_OFFER_VALUE:
            raise err("ERR_PROPERTY_BELOW_MIN_VALUE", "Property AVM below minimum offerable value")
        prior_offer = None
    else:
        # Re-issue path.
        active = store.offers.get(prop["active_offer_id"])
        # Re-issuability check (priority 14) — active offer must be ISSUED/EXPIRED/DECLINED.
        if active is None or active["status"] not in ("ISSUED", "EXPIRED", "DECLINED"):
            raise err("ERR_OFFER_NOT_REISSUABLE", "Active offer cannot be superseded by a re-issue")
        # OCC on Property.version (priority 15)
        expected = body.get("expected_property_version")
        if expected is None or expected != prop["version"]:
            raise err("ERR_STALE_VERSION", "expected_property_version does not match Property.version")
        prior_offer = active

    avm_snapshot = prop["avm_value"]
    service_fee = compute_service_fee(avm_snapshot, service_fee_pct)
    estimated_concession = compute_estimated_concession(avm_snapshot)
    preliminary = compute_preliminary_net_proceeds(avm_snapshot, service_fee, estimated_concession)

    issued_at = store.now()
    expires_at = issued_at + datetime.timedelta(days=OFFER_TTL_DAYS)

    offer = {
        "property_id": prop["id"],
        "avm_value_snapshot": avm_snapshot,
        "service_fee_pct": service_fee_pct,
        "service_fee": service_fee,
        "estimated_concession": estimated_concession,
        "preliminary_net_proceeds": preliminary,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "status": "ISSUED",
    }
    stamp_create(offer)
    store.offers[offer["id"]] = offer

    if is_reissue:
        prior_offer["status"] = "SUPERSEDED"
        touch(prior_offer)
        prop["active_offer_id"] = offer["id"]
        prop["version"] += 1            # explicit per spec; also bump updated_at
        prop["updated_at"] = store.now()
        # property stays UNDER_OFFER
    else:
        prop["status"] = "UNDER_OFFER"
        prop["active_offer_id"] = offer["id"]
        touch(prop)

    return object_response(serialize(offer), 201)


@bp.route("/properties/<prop_id>/offers", methods=["GET"])
def list_property_offers(prop_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    get_property_or_404(prop_id)
    records = [o for o in store.offers.values() if o["property_id"] == prop_id]
    limit, offset = pagination_params()
    page, total = paginate(records, limit, offset)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/properties/<prop_id>/withdraw", methods=["POST"])
def withdraw_property(prop_id):
    uid, role = authenticate()
    require_role(role, {"Seller"})
    prop = get_property_or_404(prop_id)
    require_property_owner(prop, role, uid)

    # Blocked once a transaction advanced past PENDING_ASSESSMENT (PRD §3.3:
    # "Withdrawal is blocked once a transaction has advanced past `PENDING_ASSESSMENT`;
    # an attempt to withdraw while such a transaction is in flight is rejected with
    # `ERR_PROPERTY_LOCKED`."). A transaction past PENDING_ASSESSMENT means the property
    # has left UNDER_OFFER for IN_TRANSACTION, so this PRD-named outcome is evaluated
    # before the generic UNDER_OFFER state rejection — otherwise it would be unreachable.
    for tx in store.transactions.values():
        if tx["property_id"] == prop_id and tx["status"] in ("SCHEDULED", "INSPECTION"):
            raise err("ERR_PROPERTY_LOCKED", "A transaction is past PENDING_ASSESSMENT")

    # State: must be UNDER_OFFER (priority 5)
    if prop["status"] != "UNDER_OFFER":
        raise err("ERR_INVALID_STATE", "Property is not UNDER_OFFER")

    active = store.offers.get(prop["active_offer_id"])
    if active is not None:
        active["status"] = "DECLINED"
        touch(active)
    prop["active_offer_id"] = None
    prop["status"] = "WITHDRAWN"
    touch(prop)
    return object_response(serialize(prop), 200)
