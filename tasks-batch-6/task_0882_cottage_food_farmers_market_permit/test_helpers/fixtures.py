"""Composite setup helpers.

Every test runs against a fresh, empty database (the runner restarts the server
before each test). These helpers build the multi-step preconditions each test
needs from PRD-declared endpoints only, threading entity_backed identities:
Producer calls use the producer's own id; MarketManager calls use the managed
market's id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_producer_headers,
    make_market_manager_headers,
)
from .factories import (
    create_producer_payload,
    create_policy_payload,
    create_product_payload,
    create_permit_payload,
    create_inspection_payload,
    create_market_payload,
    create_manifest_payload,
    create_sales_record_payload,
)

INSPECTOR = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["admin_headers"]
PRODUCER_SHARED = TEST_USERS["producer_headers"]


# --------------------------------------------------------------------------
# Atomic builders
# --------------------------------------------------------------------------
def create_policy(api=api_client, **overrides) -> dict:
    """Create an allowed-food policy (HealthAdmin)."""
    return get_success_data(api.create_policy(create_policy_payload(**overrides), ADMIN))


def register_producer(api=api_client, **overrides) -> dict:
    """Register a producer; returns the PENDING_VERIFICATION producer."""
    return get_success_data(api.create_producer(create_producer_payload(**overrides), PRODUCER_SHARED))


def create_registered_producer(api=api_client, **overrides) -> dict:
    """Register + verify; returns the REGISTERED producer (re-fetched)."""
    producer = register_producer(api, **overrides)
    pid = producer["id"]
    headers = make_producer_headers(pid)
    get_success_data(api.verify_producer(pid, {"verification_token": producer["verification_token"]}, headers))
    return get_success_data(api.get_producer(pid, headers))


def create_class_a_issued_permit(api=api_client, producer_id=None) -> dict:
    """DRAFT -> SUBMITTED -> ISSUED CLASS_A permit. Returns issued permit."""
    ph = make_producer_headers(producer_id)
    permit = get_success_data(api.create_permit(create_permit_payload(producer_id, "CLASS_A"), ph))
    pid = permit["id"]
    get_success_data(api.submit_permit(pid, ph))
    return get_success_data(api.issue_permit(pid, INSPECTOR))


def create_class_b_issued_permit(api=api_client, producer_id=None, inspection_type="ROUTINE") -> dict:
    """CLASS_B permit through SUBMITTED -> UNDER_INSPECTION -> PASSED inspection -> ISSUED."""
    ph = make_producer_headers(producer_id)
    permit = get_success_data(api.create_permit(create_permit_payload(producer_id, "CLASS_B"), ph))
    pid = permit["id"]
    get_success_data(api.submit_permit(pid, ph))
    insp = get_success_data(api.create_inspection(create_inspection_payload(pid, inspection_type), INSPECTOR))
    get_success_data(api.close_inspection(insp["id"], {"result": "PASS", "violation_count": 0}, INSPECTOR))
    return get_success_data(api.issue_permit(pid, INSPECTOR))


def declare_product(api=api_client, producer_id=None, **overrides) -> dict:
    """Declare a product (DECLARED / LABEL_DRAFT)."""
    ph = make_producer_headers(producer_id)
    return get_success_data(api.create_product(create_product_payload(producer_id, **overrides), ph))


def create_approved_product(api=api_client, producer_id=None, **overrides) -> dict:
    """Declare + review-food APPROVE + review-label APPROVE. Returns re-fetched product."""
    product = declare_product(api, producer_id, **overrides)
    prid = product["id"]
    get_success_data(api.review_food(prid, {"decision": "APPROVE"}, INSPECTOR))
    get_success_data(api.review_label(prid, {"decision": "APPROVE"}, INSPECTOR))
    return get_success_data(api.get_product(prid, INSPECTOR))


def create_market(api=api_client, **overrides) -> dict:
    """Create a farmers market (HealthAdmin)."""
    return get_success_data(api.create_market(create_market_payload(**overrides), ADMIN))


def create_draft_manifest(api=api_client, producer_id=None, market_id=None, permit_id=None,
                          product_ids=None, event_date="2026-06-15") -> dict:
    ph = make_producer_headers(producer_id)
    payload = create_manifest_payload(producer_id, market_id, permit_id, product_ids or [], event_date)
    return get_success_data(api.create_manifest(payload, ph))


def submit_manifest(api=api_client, producer_id=None, manifest_id=None) -> dict:
    return get_success_data(api.submit_manifest(manifest_id, make_producer_headers(producer_id)))


def approve_manifest_fresh(api=api_client, market_id=None, manifest_id=None) -> dict:
    """Read the current market version, then approve. Returns the approved manifest."""
    market = get_success_data(api.get_market(market_id, ADMIN))
    mh = make_market_manager_headers(market_id)
    return get_success_data(api.approve_manifest(manifest_id, {"expected_market_version": market["version"]}, mh))


def record_sale(api=api_client, producer_id=None, manifest_id=None, gross_amount_cents=0) -> dict:
    ph = make_producer_headers(producer_id)
    return get_success_data(api.create_sales_record(
        create_sales_record_payload(manifest_id, gross_amount_cents), ph))


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_approved_manifest(api=api_client, event_date="2026-06-15", max_vendors_per_day=5,
                            allowed_classes=None, unit_price_cents=800, food_category="BAKED_GOODS"):
    """Full chain to an APPROVED manifest ready for sales.

    policy -> registered producer -> issued CLASS_A permit -> approved product ->
    market -> draft manifest -> submitted -> approved.

    Returns dict with: producer, permit, product, market, manifest (approved).
    """
    if allowed_classes is None:
        allowed_classes = ["CLASS_A"]
    create_policy(api, food_category=food_category)
    producer = create_registered_producer(api)
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = create_approved_product(api, pid, food_category=food_category, unit_price_cents=unit_price_cents)
    market = create_market(api, max_vendors_per_day=max_vendors_per_day, allowed_classes=allowed_classes)
    manifest = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], event_date)
    submit_manifest(api, pid, manifest["id"])
    manifest = approve_manifest_fresh(api, market["id"], manifest["id"])
    return {
        "producer": producer,
        "permit": permit,
        "product": product,
        "market": market,
        "manifest": manifest,
    }


def setup_registered_producer_with_approved_product(api=api_client, unit_price_cents=800,
                                                     food_category="BAKED_GOODS", need_policy=True):
    """policy -> registered producer -> issued CLASS_A permit -> approved product.

    Returns dict with: producer, permit, product.
    """
    if need_policy:
        create_policy(api, food_category=food_category)
    producer = create_registered_producer(api)
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = create_approved_product(api, pid, food_category=food_category, unit_price_cents=unit_price_cents)
    return {"producer": producer, "permit": permit, "product": product}


def add_approved_vendor(api=api_client, market=None, event_date="2026-06-15",
                        unit_price_cents=500):
    """Add a second registered producer + issued permit + approved product, then a
    submitted manifest at the given market/date. Returns dict with producer, permit,
    product, manifest (SUBMITTED). Assumes a BAKED_GOODS policy already exists.
    """
    producer = create_registered_producer(api)
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = create_approved_product(api, pid, unit_price_cents=unit_price_cents)
    manifest = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], event_date)
    submit_manifest(api, pid, manifest["id"])
    return {"producer": producer, "permit": permit, "product": product, "manifest": manifest}
