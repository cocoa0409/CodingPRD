"""Sellers, monitored listings, infringement claims and test buys."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import constants as C
import db
import entities
import ledger
import validation as V
from errors import fail
from middleware import ALL_ROLES, ENFORCEMENT_ANALYST, authenticate
from response import created, ok, public
from versioning import touch

bp = Blueprint("monitor", __name__)

COOLING_PERIOD = timedelta(days=7)


# ----------------------------------------------------------------- sellers ---

@bp.route("/brand-protection/sellers", methods=["POST"])
def create_seller():
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    marketplace_code = V.enum_field(payload, "marketplace_code",
                                    C.MARKETPLACE_CODES)
    seller_ref = V.string_field(payload, "seller_ref", 1, 40)
    legal_name = V.string_field(payload, "legal_name", 1, 160)
    jurisdiction = V.jurisdiction_field(payload, "jurisdiction", required=False)
    for existing in db.values("sellers"):
        if (existing["marketplace_code"] == marketplace_code
                and existing["seller_ref"] == seller_ref):
            fail("ERR_INVALID_REQUEST",
                 "seller_ref is already registered on this marketplace.")
    row = entities.new_seller(marketplace_code, seller_ref, legal_name,
                              jurisdiction)
    return created(public(row))


@bp.route("/brand-protection/sellers/<seller_id>", methods=["GET"])
def read_seller(seller_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("sellers", seller_id)))


@bp.route("/brand-protection/sellers", methods=["GET"])
def list_sellers():
    authenticate(ALL_ROLES)
    return V.collection("sellers", {
        "canonical_seller_id": None,
        "marketplace_code": C.MARKETPLACE_CODES,
        "status": C.SELLER_STATUSES,
    })


@bp.route("/brand-protection/sellers/<seller_id>/link-alias", methods=["POST"])
def link_alias(seller_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    canonical_id = V.id_field(payload, "canonical_seller_id")
    expected = V.int_field(payload, "expected_canonical_seller_version",
                           minimum=None)
    alias = V.must_exist("sellers", seller_id)
    canonical = V.must_exist("sellers", canonical_id)
    if expected != canonical["version"]:
        fail("ERR_STALE_SELLER_VERSION")
    if alias["canonical_seller_id"] is not None:
        fail("ERR_ALIAS_CHAIN_NOT_ALLOWED")
    if canonical["canonical_seller_id"] is not None:
        fail("ERR_ALIAS_CHAIN_NOT_ALLOWED")
    if alias["id"] == canonical["id"]:
        fail("ERR_ALIAS_CHAIN_NOT_ALLOWED")
    alias["canonical_seller_id"] = canonical["id"]
    touch(alias)
    touch(canonical)
    ledger.recompute_sellers([canonical["id"]])
    return ok(public(alias))


# ------------------------------------------------------- monitored listings ---

@bp.route("/brand-protection/listings", methods=["POST"])
def create_listing():
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    brand_id = V.id_field(payload, "brand_id")
    seller_id = V.id_field(payload, "seller_id")
    marketplace_code = V.enum_field(payload, "marketplace_code",
                                    C.MARKETPLACE_CODES)
    listing_ref = V.string_field(payload, "listing_ref", 1, 40)
    title_text = V.string_field(payload, "title_text", 1, 300)
    image_hash = V.string_field(payload, "image_hash", 1, 80)
    price_cents = V.int_field(payload, "price_cents", minimum=0)
    nice_class = V.int_field(payload, "nice_class", minimum=1, maximum=45)
    brand = V.must_exist("brands", brand_id)
    seller = V.must_exist("sellers", seller_id)
    for existing in db.values("listings"):
        if (existing["marketplace_code"] == marketplace_code
                and existing["listing_ref"] == listing_ref):
            fail("ERR_INVALID_REQUEST",
                 "listing_ref is already monitored on this marketplace.")
    row = entities.new_listing(brand["id"], seller["id"], marketplace_code,
                               listing_ref, title_text, image_hash, price_cents,
                               nice_class)
    return created(public(row))


@bp.route("/brand-protection/listings/<listing_id>", methods=["GET"])
def read_listing(listing_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("listings", listing_id)))


@bp.route("/brand-protection/listings", methods=["GET"])
def list_listings():
    authenticate(ALL_ROLES)
    return V.collection("listings", {
        "brand_id": None,
        "seller_id": None,
        "marketplace_code": C.MARKETPLACE_CODES,
        "monitor_status": C.MONITOR_STATUSES,
        "enforcement_status": C.ENFORCEMENT_STATUSES,
        "violation_type": C.VIOLATION_TYPES,
    })


@bp.route("/brand-protection/listings/<listing_id>/screen", methods=["POST"])
def screen_listing(listing_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    image_score = V.unit_decimal_field(payload, "image_match_score")
    text_score = V.unit_decimal_field(payload, "text_match_score")
    listing = V.must_exist("listings", listing_id)
    if listing["enforcement_status"] == "TAKEDOWN_PENDING":
        fail("ERR_INVALID_STATE")
    brand = db.get("brands", listing["brand_id"])
    seller = db.get("sellers", listing["seller_id"])
    derived = calc.screen(listing, brand, seller, calc.q4(image_score),
                          calc.q4(text_score))
    listing.update(derived)
    touch(listing)
    return ok(public(listing))


# ----------------------------------------------------- infringement claims ---

@bp.route("/brand-protection/claims", methods=["POST"])
def create_claim():
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    brand_id = V.id_field(payload, "brand_id")
    listing_id = V.id_field(payload, "listing_id")
    registration_id = V.id_field(payload, "asserted_registration_id")
    claimed_violation_type = V.enum_field(payload, "claimed_violation_type",
                                          C.CLAIMED_VIOLATION_TYPES)
    brand = V.must_exist("brands", brand_id)
    listing = V.must_exist("listings", listing_id)
    registration = V.must_exist("registrations", registration_id)
    for claim in db.values("claims"):
        if (claim["listing_id"] == listing["id"]
                and claim["status"] in ("DRAFT", "SUBSTANTIATED", "ENFORCED")):
            fail("ERR_INVALID_STATE")
    if listing["monitor_status"] != "FLAGGED":
        fail("ERR_LISTING_NOT_FLAGGED")
    seller = db.get("sellers", listing["seller_id"])
    strength = calc.registration_strength(registration, listing)
    base = calc.substantiation_base(listing["match_score"], strength,
                                    seller["standalone_strike_points"])
    row = entities.new_claim(brand["id"], listing["id"], registration["id"],
                             claimed_violation_type, strength,
                             calc.preliminary_score(base))
    if listing["enforcement_status"] == "NONE":
        listing["enforcement_status"] = "CLAIM_OPEN"
        touch(listing)
    return created(public(row))


@bp.route("/brand-protection/claims/<claim_id>", methods=["GET"])
def read_claim(claim_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("claims", claim_id)))


@bp.route("/brand-protection/claims", methods=["GET"])
def list_claims():
    authenticate(ALL_ROLES)
    return V.collection("claims", {
        "brand_id": None,
        "listing_id": None,
        "asserted_registration_id": None,
        "status": C.CLAIM_STATUSES,
        "claimed_violation_type": C.CLAIMED_VIOLATION_TYPES,
    })


@bp.route("/brand-protection/claims/<claim_id>/substantiate", methods=["POST"])
def substantiate_claim(claim_id):
    authenticate(ENFORCEMENT_ANALYST)
    V.body()
    claim = V.must_exist("claims", claim_id)
    if claim["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    score, strength = calc.recompute_full_substantiation(claim)
    if score < calc.SUBSTANTIATION_THRESHOLD:
        # Nothing is persisted - not the score, not updated_at, not version.
        fail("ERR_CLAIM_NOT_SUBSTANTIATED")
    claim["registration_strength"] = strength
    claim["substantiation_score"] = score
    claim["status"] = "SUBSTANTIATED"
    touch(claim)
    return ok(public(claim))


@bp.route("/brand-protection/claims/<claim_id>/dismiss", methods=["POST"])
def dismiss_claim(claim_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    V.string_field(payload, "reason_code", 1, 80)
    claim = V.must_exist("claims", claim_id)
    if claim["status"] not in ("DRAFT", "SUBSTANTIATED"):
        fail("ERR_INVALID_STATE")
    if ledger.claim_has_takedown_in(
            claim["id"], ("SUBMITTED", "APPROVED_REMOVED", "COUNTER_NOTICED")):
        fail("ERR_DECISION_WINDOW_OPEN")
    claim["status"] = "DISMISSED"
    claim["dismissal_reason_code"] = "ANALYST_WITHDRAWN"
    touch(claim)
    ledger.rederive_listing_enforcement_after_claim_close(
        db.get("listings", claim["listing_id"]))
    ledger.withdraw_claim_packages(claim["id"])
    return ok(public(claim))


# --------------------------------------------------------------- test buys ---

@bp.route("/brand-protection/claims/<claim_id>/test-buys", methods=["POST"])
def order_test_buy(claim_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    order_ref = V.string_field(payload, "order_ref", 1, 40)
    purchase = V.int_field(payload, "purchase_price_cents", minimum=0)
    shipping = V.int_field(payload, "shipping_cents", minimum=0)
    lab_fee = V.int_field(payload, "lab_fee_cents", minimum=0)
    claim = V.must_exist("claims", claim_id)
    if claim["status"] == "DISMISSED":
        fail("ERR_INVALID_STATE")
    listing = db.get("listings", claim["listing_id"])
    seller_id = listing["seller_id"]
    ordered_at = db.now()
    for existing in db.values("test_buys"):
        if existing["seller_id"] != seller_id:
            continue
        if existing["status"] == "CANCELLED":
            continue
        gap = ordered_at - existing["ordered_at"]
        if abs(gap) <= COOLING_PERIOD:
            fail("ERR_TEST_BUY_COOLING_PERIOD")
    pricing = calc.test_buy_pricing(purchase, shipping, lab_fee)
    brand = db.get("brands", claim["brand_id"])
    if (brand["enforcement_spend_cents"] + pricing["billable_total_cents"]
            > brand["enforcement_budget_cents"]):
        fail("ERR_TEST_BUY_BUDGET_EXCEEDED")
    row = entities.new_test_buy(claim["id"], seller_id, order_ref, purchase,
                                shipping, lab_fee, pricing, ordered_at)
    brand["enforcement_spend_cents"] += pricing["billable_total_cents"]
    touch(brand)
    return created(public(row))


@bp.route("/brand-protection/test-buys/<test_buy_id>", methods=["GET"])
def read_test_buy(test_buy_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("test_buys", test_buy_id)))


@bp.route("/brand-protection/test-buys", methods=["GET"])
def list_test_buys():
    authenticate(ALL_ROLES)
    return V.collection("test_buys", {
        "claim_id": None,
        "seller_id": None,
        "status": C.TEST_BUY_STATUSES,
    })


@bp.route("/brand-protection/test-buys/<test_buy_id>/receive", methods=["POST"])
def receive_test_buy(test_buy_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    lot_code = V.string_field(payload, "lot_code", 1, 40)
    custody = V.string_field(payload, "chain_of_custody_ref", 1, 80,
                             required=False)
    buy = V.must_exist("test_buys", test_buy_id)
    if buy["status"] != "ORDERED":
        fail("ERR_INVALID_STATE")
    buy["status"] = "RECEIVED"
    buy["received_at"] = db.now()
    buy["lot_code"] = lot_code
    buy["chain_of_custody_ref"] = custody
    touch(buy)
    return ok(public(buy))


@bp.route("/brand-protection/test-buys/<test_buy_id>/authenticate",
          methods=["POST"])
def authenticate_test_buy(test_buy_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    result = V.enum_field(payload, "authentication_result",
                          C.AUTHENTICATION_RESULTS)
    lab_ref = V.string_field(payload, "lab_ref", 1, 80)
    buy = V.must_exist("test_buys", test_buy_id)
    if buy["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE")
    if buy["chain_of_custody_ref"] is None:
        fail("ERR_CHAIN_OF_CUSTODY_INCOMPLETE")
    buy["authentication_result"] = result
    buy["lab_ref"] = lab_ref
    claim = db.get("claims", buy["claim_id"])
    if result == "COUNTERFEIT":
        buy["status"] = "AUTHENTICATED_COUNTERFEIT"
        touch(buy)
        score, strength = calc.recompute_full_substantiation(claim)
        if (Decimal(claim["substantiation_score"]) != score
                or Decimal(claim["registration_strength"]) != strength):
            claim["substantiation_score"] = score
            claim["registration_strength"] = strength
            touch(claim)
    else:
        buy["status"] = "AUTHENTICATED_AUTHENTIC"
        touch(buy)
        if claim["status"] != "DISMISSED":
            claim["status"] = "DISMISSED"
            claim["dismissal_reason_code"] = "TEST_BUY_AUTHENTIC"
            touch(claim)
        listing = db.get("listings", claim["listing_id"])
        if listing is not None:
            if (listing["enforcement_status"] != "NONE"
                    or listing["monitor_status"] != "CLEARED"
                    or listing["violation_type"] != "NONE"):
                listing["enforcement_status"] = "NONE"
                listing["monitor_status"] = "CLEARED"
                listing["violation_type"] = "NONE"
                touch(listing)
        ledger.withdraw_claim_packages(claim["id"])
    return ok(public(buy))


@bp.route("/brand-protection/test-buys/<test_buy_id>/cancel", methods=["POST"])
def cancel_test_buy(test_buy_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    V.string_field(payload, "reason_code", 1, 80)
    buy = V.must_exist("test_buys", test_buy_id)
    if buy["status"] != "ORDERED":
        fail("ERR_INVALID_STATE")
    buy["status"] = "CANCELLED"
    touch(buy)
    claim = db.get("claims", buy["claim_id"])
    brand = db.get("brands", claim["brand_id"]) if claim else None
    if brand is not None:
        brand["enforcement_spend_cents"] -= buy["billable_total_cents"]
        touch(brand)
    return ok(public(buy))
