"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted before each test, so nothing carries over). Setup
calls use get_success_data() so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: SalesConsultant and SalonBuyer are entity-backed roles
(PRD §2.1), so salon onboarding uses make_sales_consultant_headers(<id>) and
all order/credit/promotion calls use make_salon_buyer_headers(<salon id>) —
never the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_brand_payload,
    create_bundle_promotion_payload,
    create_consultant_payload,
    create_diversion_case_payload,
    create_license_payload,
    create_order_payload,
    create_product_payload,
    create_route_plan_payload,
    create_route_stop_payload,
    create_salon_payload,
    create_sample_promotion_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_sales_consultant_headers,
    make_salon_buyer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-call wrappers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def run_sweep() -> dict:
    return get_success_data(api_client.run_daily_sweep(ADMIN))


def make_consultant(full_name=None, territory_codes=("CA",),
                    commission_model="STRAIGHT") -> dict:
    return get_success_data(api_client.create_sales_consultant(
        create_consultant_payload(
            full_name=full_name or "Consultant",
            territory_codes=list(territory_codes),
            commission_model=commission_model),
        ADMIN))


def make_brand(name=None) -> dict:
    payload = create_brand_payload()
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_brand(payload, ADMIN))


def make_product(brand_id, variant_type="RETAIL", hazmat_class="NONE",
                 base_price_cents=TEST_DEFAULTS["BASE_PRICE_CENTS"],
                 weight_grams=TEST_DEFAULTS["WEIGHT_GRAMS"], name=None) -> dict:
    payload = create_product_payload(
        variant_type=variant_type, hazmat_class=hazmat_class,
        base_price_cents=base_price_cents, weight_grams=weight_grams)
    if name is not None:
        payload["name"] = name
    payload["brand_id"] = brand_id
    return get_success_data(api_client.create_product(payload, ADMIN))


def make_salon(territory_code="CA", legal_name=None, consultant=None,
               assigned_consultant_id=None) -> dict:
    """Create a PENDING_VERIFICATION salon. A consultant is created when the
    caller does not supply one (the opener role must resolve to a real
    consultant). Returns the salon dict."""
    if consultant is None:
        consultant = make_consultant(territory_codes=[territory_code])
    payload = create_salon_payload(
        legal_name=legal_name or "Salon", territory_code=territory_code)
    consultant_id = assigned_consultant_id
    if consultant_id is None and consultant is not None:
        consultant_id = consultant["id"]
    if consultant_id is not None:
        payload["assigned_consultant_id"] = consultant_id
    salon = get_success_data(api_client.create_salon_account(
        payload, make_sales_consultant_headers(consultant["id"])))
    return salon


def submit_license(salon_id, valid_until=TEST_DEFAULTS["LICENSE_VALID_UNTIL"],
                   license_type="COSMETOLOGY", issuing_state=None) -> dict:
    payload = create_license_payload(
        license_type=license_type, valid_until=valid_until)
    if issuing_state is not None:
        payload["issuing_state"] = issuing_state
    return get_success_data(api_client.create_license(
        salon_id, payload, make_salon_buyer_headers(salon_id)))


def verify_license(license_id, officer_id="officer-verify-1") -> dict:
    return get_success_data(api_client.verify_license(
        license_id, make_compliance_officer_headers(officer_id)))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_active_salon(territory_code="CA", legal_name=None, consultant=None,
                        valid_until=TEST_DEFAULTS["LICENSE_VALID_UNTIL"],
                        tier=None):
    """Create consultant (if absent) + salon + license, verify the license so
    the salon flips to ACTIVE, optionally pin a tier override.
    Returns (salon_dict, consultant_dict)."""
    if consultant is None:
        consultant = make_consultant(territory_codes=[territory_code])
    salon = make_salon(territory_code=territory_code, legal_name=legal_name,
                       consultant=consultant)
    license_row = submit_license(salon["id"], valid_until=valid_until)
    verify_license(license_row["id"])
    if tier is not None:
        salon = override_salon_tier(salon["id"], tier)
    else:
        salon = get_success_data(api_client.get_salon_account(salon["id"], ADMIN))
    return salon, consultant


def override_salon_tier(salon_id, tier) -> dict:
    """OCC-guarded tier override: reads the current version, then pins `tier`."""
    current = get_success_data(api_client.get_salon_account(salon_id, ADMIN))
    return get_success_data(api_client.tier_override_salon(
        salon_id,
        {"tier": tier, "expected_salon_account_version": current["version"]},
        ADMIN))


def get_salon(salon_id) -> dict:
    return get_success_data(api_client.get_salon_account(salon_id, ADMIN))


def get_order(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_promotion(promotion_id) -> dict:
    return get_success_data(api_client.get_promotion(promotion_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: order assembly
# ---------------------------------------------------------------------------

def create_draft_order(salon_id, items) -> dict:
    """items: list of {"product_id": ..., "quantity": ...}."""
    return get_success_data(api_client.create_order(
        create_order_payload(salon_account_id=salon_id, items=list(items)),
        make_salon_buyer_headers(salon_id)))


def list_order_line_items(order_id) -> list:
    """All line items of an order (defensively re-filtered client-side)."""
    data = get_success_data(api_client.list_order_items(
        ADMIN, params={"order_id": order_id, "limit": 100}))
    return [it for it in data if it.get("order_id") == order_id]


def add_order_item(order_id, product_id, quantity, expected_order_version) -> dict:
    return get_success_data(api_client.add_order_item(
        order_id,
        {"product_id": product_id, "quantity": quantity,
         "expected_order_version": expected_order_version},
        make_salon_buyer_headers(get_order(order_id)["salon_account_id"])))


def submit_order(order_id, salon_id) -> dict:
    return get_success_data(api_client.submit_order(
        order_id, make_salon_buyer_headers(salon_id)))


def approve_order(order_id) -> dict:
    return get_success_data(api_client.approve_order(order_id, ADMIN))


def redeem_credits(order_id, salon_id, points) -> dict:
    return get_success_data(api_client.redeem_credits(
        order_id, {"points": points}, make_salon_buyer_headers(salon_id)))


def redeem_promotion(order_id, salon_id, code) -> dict:
    return get_success_data(api_client.redeem_promotion(
        order_id, {"code": code}, make_salon_buyer_headers(salon_id)))


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_shipment_for_whole_order(order_id, method="GROUND") -> dict:
    """One shipment covering every line of the order at full quantity."""
    items = list_order_line_items(order_id)
    ship_items = [{"order_item_id": it["id"], "quantity": it["quantity"]}
                  for it in items]
    return get_success_data(api_client.create_shipment(
        order_id, {"method": method, "items": ship_items}, WAREHOUSE))


def deliver_shipment_fully(shipment_id) -> dict:
    """PLANNED -> LABEL_CREATED -> IN_TRANSIT -> DELIVERED."""
    get_success_data(api_client.create_shipment_label(shipment_id, WAREHOUSE))
    get_success_data(api_client.ship_shipment(shipment_id, WAREHOUSE))
    return get_success_data(api_client.deliver_shipment(shipment_id, WAREHOUSE))


def deliver_order_fully(order_id, method="GROUND") -> dict:
    """Single-shipment delivery of every line; returns the refreshed order."""
    shipment = create_shipment_for_whole_order(order_id, method=method)
    deliver_shipment_fully(shipment["id"])
    return get_order(order_id)


def create_delivered_order(salon_id, items, method="GROUND") -> dict:
    """Create -> submit -> approve -> ship -> deliver. Returns refreshed order."""
    order = create_draft_order(salon_id, items)
    submit_order(order["id"], salon_id)
    approve_order(order["id"])
    return deliver_order_fully(order["id"], method=method)


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_salon_with_credit_points(points, territory_code="CA",
                                   consultant=None, valid_until=None):
    """ACTIVE SILVER salon that has earned exactly `points` education-credit
    points, via a delivered single-line order whose net merchandise equals
    points * 1000 cents (SILVER multiplier 1; provisional == final, delta 0).
    Returns (salon, consultant, product)."""
    kwargs = {}
    if valid_until is not None:
        kwargs["valid_until"] = valid_until
    salon, consultant = create_active_salon(
        territory_code=territory_code, consultant=consultant, **kwargs)
    brand = make_brand()
    product = make_product(brand["id"], base_price_cents=points * 1000)
    create_delivered_order(
        salon["id"], [{"product_id": product["id"], "quantity": 1}])
    return get_salon(salon["id"]), consultant, product


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------

def create_sample_promotion(sample_product_id, code=None, budget_units=5,
                            per_salon_cap=5, sample_units_per_redemption=1,
                            eligible_tiers=("SILVER",),
                            starts_at=TEST_DEFAULTS["PROMO_STARTS_AT"],
                            ends_at=TEST_DEFAULTS["PROMO_ENDS_AT"],
                            activate=True) -> dict:
    payload = create_sample_promotion_payload(
        sample_product_id=sample_product_id,
        budget_units=budget_units, per_salon_cap=per_salon_cap,
        sample_units_per_redemption=sample_units_per_redemption,
        eligible_tiers=list(eligible_tiers),
        starts_at=starts_at, ends_at=ends_at)
    if code is not None:
        payload["code"] = code
    promo = get_success_data(api_client.create_promotion(payload, ADMIN))
    if activate:
        promo = get_success_data(api_client.activate_promotion(promo["id"], ADMIN))
    return promo


def create_bundle_promotion(required_product_id, required_qty,
                            free_product_id, free_qty, code=None,
                            budget_units=10, per_salon_cap=5,
                            eligible_tiers=("SILVER",),
                            starts_at=TEST_DEFAULTS["PROMO_STARTS_AT"],
                            ends_at=TEST_DEFAULTS["PROMO_ENDS_AT"],
                            activate=True) -> dict:
    payload = create_bundle_promotion_payload(
        required_product_id=required_product_id, required_qty=required_qty,
        free_product_id=free_product_id, free_qty=free_qty,
        budget_units=budget_units, per_salon_cap=per_salon_cap,
        eligible_tiers=list(eligible_tiers),
        starts_at=starts_at, ends_at=ends_at)
    if code is not None:
        payload["code"] = code
    promo = get_success_data(api_client.create_promotion(payload, ADMIN))
    if activate:
        promo = get_success_data(api_client.activate_promotion(promo["id"], ADMIN))
    return promo


# ---------------------------------------------------------------------------
# Route operations
# ---------------------------------------------------------------------------

def create_route_plan(consultant_id, name=None) -> dict:
    payload = create_route_plan_payload(sales_consultant_id=consultant_id)
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_route_plan(
        payload, make_sales_consultant_headers(consultant_id)))


def add_route_stop(plan_id, salon_id, start_at, end_at, consultant_id) -> dict:
    return get_success_data(api_client.add_route_stop(
        plan_id,
        create_route_stop_payload(
            salon_account_id=salon_id, start_at=start_at, end_at=end_at),
        make_sales_consultant_headers(consultant_id)))


def create_published_plan(consultant_id, stops):
    """stops: list of (salon_id, start_at, end_at). Returns (plan, [stop...])."""
    plan = create_route_plan(consultant_id)
    created = [add_route_stop(plan["id"], s, start, end, consultant_id)
               for (s, start, end) in stops]
    plan = get_success_data(api_client.publish_route_plan(
        plan["id"], make_sales_consultant_headers(consultant_id)))
    return plan, created


# ---------------------------------------------------------------------------
# Diversion cases
# ---------------------------------------------------------------------------

def file_diversion_case(salon_id, product_id, severity="MINOR",
                        evidence_note="unauthorized retail listing observed",
                        hold_shipments=False, filer_consultant_id=None,
                        filer_officer_id=None) -> dict:
    """File an OPEN diversion case. Exactly one of filer_consultant_id /
    filer_officer_id selects the filing identity (default: a consultant header
    is unusable without a real consultant, so officer is the default)."""
    payload = create_diversion_case_payload(
        salon_account_id=salon_id, product_id=product_id, severity=severity,
        evidence_note=evidence_note, hold_shipments=hold_shipments)
    if filer_consultant_id is not None:
        headers = make_sales_consultant_headers(filer_consultant_id)
    else:
        headers = make_compliance_officer_headers(filer_officer_id or "officer-file-1")
    return get_success_data(api_client.create_diversion_case(payload, headers))


# ---------------------------------------------------------------------------
# Credit ledger reads
# ---------------------------------------------------------------------------

def list_credit_ledger(salon_id) -> list:
    return get_success_data(api_client.list_credit_ledger(
        salon_id, ADMIN, params={"limit": 100}))


def list_redemptions(params=None) -> list:
    return get_success_data(api_client.list_promotion_redemptions(
        ADMIN, params=params or {"limit": 100}))
