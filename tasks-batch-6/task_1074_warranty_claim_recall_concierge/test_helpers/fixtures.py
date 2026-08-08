"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion mismatches.

Identity threading follows the PRD (Section 2.1):
  - Anonymous creates households and the first OWNER member.
  - The OWNER Member.id is threaded into HouseholdOwner headers for every
    ownership-gated household call (subscriptions, products, claims, documents,
    match acknowledge/dismiss, withdraw).
  - The Manufacturer.id is threaded into ManufacturerAgent headers for recalls.
  - ConciergeAgent ids are opaque tokens; distinct tokens drive the SoD rule.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_household_payload, create_member_payload, create_subscription_payload,
    create_manufacturer_payload, create_product_payload, create_recall_notice_payload,
    create_claim_payload, create_claim_document_payload,
)
from .test_users import (
    TEST_USERS, make_household_owner_headers, make_manufacturer_agent_headers,
    make_concierge_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ─── Primitive builders ───────────────────────────────────────
def set_clock(to_iso8601: str):
    """Advance the logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(to_iso8601, PLATFORM_ADMIN))


def new_manufacturer(**overrides):
    return get_success_data(
        api_client.create_manufacturer(create_manufacturer_payload(**overrides), PLATFORM_ADMIN))


def new_household(**overrides):
    return get_success_data(
        api_client.create_household(create_household_payload(**overrides), ANONYMOUS))


def new_owner(household_id, **overrides):
    """Create the first OWNER member via Anonymous."""
    return get_success_data(api_client.create_member(
        household_id, create_member_payload(role="OWNER", **overrides), ANONYMOUS))


def new_household_with_owner(**overrides):
    """Create a household and its first OWNER member. Returns (household, owner)."""
    hh = new_household(**overrides.get("household_overrides", {}))
    owner = new_owner(hh["id"], **overrides.get("owner_overrides", {}))
    return hh, owner


def add_member(household_id, owner_id, role="ADULT", **overrides):
    """HouseholdOwner adds an ADULT/MINOR member."""
    return get_success_data(api_client.create_member(
        household_id, create_member_payload(role=role, **overrides),
        make_household_owner_headers(owner_id)))


def new_subscription(household_id, owner_id, tier="BASIC", **overrides):
    return get_success_data(api_client.create_subscription(
        household_id, create_subscription_payload(tier=tier, **overrides),
        make_household_owner_headers(owner_id)))


def new_product(household_id, owner_id, manufacturer_id, **overrides):
    return get_success_data(api_client.create_product(
        create_product_payload(household_id, manufacturer_id, **overrides),
        make_household_owner_headers(owner_id)))


def new_claim(product_id, owner_id, filed_by_member_id=None, **overrides):
    filer = filed_by_member_id or owner_id
    return get_success_data(api_client.create_claim(
        create_claim_payload(product_id, filer, **overrides),
        make_household_owner_headers(owner_id)))


def add_document(claim_id, owner_id, **overrides):
    return get_success_data(api_client.add_claim_document(
        claim_id, create_claim_document_payload(**overrides),
        make_household_owner_headers(owner_id)))


def submit_claim(claim_id, owner_id):
    return get_success_data(api_client.submit_claim(
        claim_id, make_household_owner_headers(owner_id)))


def review_claim(claim_id, concierge_id):
    return get_success_data(api_client.review_claim(
        claim_id, make_concierge_headers(concierge_id)))


def request_docs(claim_id, concierge_id):
    return get_success_data(api_client.request_claim_docs(
        claim_id, make_concierge_headers(concierge_id)))


def approve_claim(claim_id, concierge_id):
    return get_success_data(api_client.approve_claim(
        claim_id, make_concierge_headers(concierge_id)))


def resolution_for_claim(claim_id):
    """Fetch the single Resolution created for an approved claim."""
    data, _ = _paginated(api_client.list_resolutions(PLATFORM_ADMIN, params={"claim_id": claim_id}))
    assert data, f"Setup failed: no resolution found for claim {claim_id}"
    return data[0]


def new_recall_notice(manufacturer_id, **overrides):
    return get_success_data(api_client.create_recall_notice(
        create_recall_notice_payload(manufacturer_id, **overrides),
        make_manufacturer_agent_headers(manufacturer_id)))


def publish_recall(recall_notice_id, manufacturer_id):
    return get_success_data(api_client.publish_recall_notice(
        recall_notice_id, make_manufacturer_agent_headers(manufacturer_id)))


def close_recall(recall_notice_id, manufacturer_id):
    return get_success_data(api_client.close_recall_notice(
        recall_notice_id, make_manufacturer_agent_headers(manufacturer_id)))


def match_for_product(product_id):
    """Fetch the single RecallMatch created for a product by a publish cascade."""
    data, _ = _paginated(api_client.list_recall_matches(PLATFORM_ADMIN, params={"product_id": product_id}))
    assert data, f"Setup failed: no recall match found for product {product_id}"
    return data[0]


def acknowledge_match(match_id, owner_id):
    return get_success_data(api_client.acknowledge_recall_match(
        match_id, make_household_owner_headers(owner_id)))


def _paginated(response):
    """Return (data_list, meta) from a list response, lenient for setup use."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# ─── Composite fixtures ───────────────────────────────────────
def setup_household_with_active_subscription(tier="BASIC", exposure_scoring_mode=None,
                                             period_start="2025-01-01T00:00:00Z",
                                             period_end="2027-01-01T00:00:00Z"):
    """Manufacturer + household + OWNER + ACTIVE subscription of `tier`.

    Returns dict(mfr, hh, owner, sub).
    """
    hh_over = {}
    if exposure_scoring_mode is not None:
        hh_over["exposure_scoring_mode"] = exposure_scoring_mode
    mfr = new_manufacturer()
    hh = new_household(**hh_over)
    owner = new_owner(hh["id"])
    sub = new_subscription(hh["id"], owner["id"], tier=tier,
                           period_start=period_start, period_end=period_end)
    return {"mfr": mfr, "hh": hh, "owner": owner, "sub": sub}


def setup_refund_claim_under_review(tier="BASIC",
                                    purchase_price_cents=100000,
                                    warranty_months=24,
                                    purchase_date="2025-01-01T00:00:00Z",
                                    shipping_cost_cents=None,
                                    resolution_preference="REFUND",
                                    reviewer_id="cx-reviewer",
                                    clock=None,
                                    period_start="2025-01-01T00:00:00Z",
                                    period_end="2027-01-01T00:00:00Z"):
    """Full chain to a claim UNDER_REVIEW: manufacturer, household, OWNER, ACTIVE
    subscription, product, one-document claim, submitted, reviewed by `reviewer_id`.

    If `clock` is given, the logical clock is set before approval-time computation.
    Returns dict(mfr, hh, owner, sub, prod, claim). The test triggers approve
    (with a distinct concierge) itself so the resolution birth is the assertion.
    """
    ctx = setup_household_with_active_subscription(
        tier=tier, period_start=period_start, period_end=period_end)
    mfr, hh, owner = ctx["mfr"], ctx["hh"], ctx["owner"]
    prod = new_product(hh["id"], owner["id"], mfr["id"],
                       purchase_price_cents=purchase_price_cents,
                       warranty_months=warranty_months,
                       purchase_date=purchase_date)
    claim_over = {"resolution_preference": resolution_preference}
    if shipping_cost_cents is not None:
        claim_over["shipping_cost_cents"] = shipping_cost_cents
    claim = new_claim(prod["id"], owner["id"], **claim_over)
    add_document(claim["id"], owner["id"], doc_type="RECEIPT")
    if clock is not None:
        set_clock(clock)
    submit_claim(claim["id"], owner["id"])
    review_claim(claim["id"], reviewer_id)
    return {"mfr": mfr, "hh": hh, "owner": owner, "sub": ctx["sub"],
            "prod": prod, "claim": claim}


def setup_recall_published(exposure_scoring_mode="WEIGHTED",
                           severity="CRITICAL",
                           serials=(1,),
                           serial_range_start=1,
                           serial_range_end=100,
                           model_number="MODEL-1",
                           remedy_type="REPLACE"):
    """Household with N products of one model + a PUBLISHED recall matching the
    given serial range. Returns dict(mfr, hh, owner, products, rn).

    `serials` is a tuple of serial_numbers; one product is created per serial.
    """
    mfr = new_manufacturer()
    hh = new_household(exposure_scoring_mode=exposure_scoring_mode)
    owner = new_owner(hh["id"])
    products = []
    for s in serials:
        products.append(new_product(hh["id"], owner["id"], mfr["id"],
                                    model_number=model_number, serial_number=s,
                                    warranty_months=12))
    rn = new_recall_notice(mfr["id"], affected_model_number=model_number,
                           serial_range_start=serial_range_start,
                           serial_range_end=serial_range_end,
                           severity=severity, remedy_type=remedy_type)
    publish_recall(rn["id"], mfr["id"])
    return {"mfr": mfr, "hh": hh, "owner": owner, "products": products, "rn": rn}


def setup_replacement_resolution_pending(coordination_enabled=True, rma_required=True,
                                         reviewer_id="cx-1", approver_id="cx-2"):
    """A REPLACEMENT claim approved so its Resolution exists in PENDING mode
    REPLACEMENT. Registers a spare replacement product too.

    Returns dict(mfr, hh, owner, sub, prod, replacement, claim, res).
    """
    mfr = new_manufacturer(coordination_enabled=coordination_enabled, rma_required=rma_required)
    hh = new_household()
    owner = new_owner(hh["id"])
    sub = new_subscription(hh["id"], owner["id"], tier="BASIC")
    prod = new_product(hh["id"], owner["id"], mfr["id"], model_number="CO-1",
                       serial_number=1, purchase_price_cents=50000, warranty_months=24)
    replacement = new_product(hh["id"], owner["id"], mfr["id"], model_number="CO-1",
                              serial_number=2, purchase_date="2026-01-01T00:00:00Z",
                              purchase_price_cents=50000, warranty_months=24)
    claim = new_claim(prod["id"], owner["id"], resolution_preference="REPLACEMENT",
                      issue_description="swap")
    add_document(claim["id"], owner["id"], doc_type="PHOTO")
    submit_claim(claim["id"], owner["id"])
    review_claim(claim["id"], reviewer_id)
    approve_claim(claim["id"], approver_id)
    res = resolution_for_claim(claim["id"])
    return {"mfr": mfr, "hh": hh, "owner": owner, "sub": sub, "prod": prod,
            "replacement": replacement, "claim": claim, "res": res}


def setup_basic_draft_claim(price_cents=100, warranty_months=12,
                            resolution_preference="REFUND"):
    """Manufacturer, household, OWNER, product, and a DRAFT claim (no subscription).

    Returns dict(mfr, hh, owner, prod, claim).
    """
    mfr = new_manufacturer()
    hh = new_household()
    owner = new_owner(hh["id"])
    prod = new_product(hh["id"], owner["id"], mfr["id"],
                       purchase_price_cents=price_cents, warranty_months=warranty_months)
    claim = new_claim(prod["id"], owner["id"], resolution_preference=resolution_preference)
    return {"mfr": mfr, "hh": hh, "owner": owner, "prod": prod, "claim": claim}
