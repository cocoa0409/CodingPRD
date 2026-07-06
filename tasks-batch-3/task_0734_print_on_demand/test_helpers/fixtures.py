"""Composite setup helpers — multi-step preambles reused across many tests.

Every fixture creates its own entities from scratch (each test starts against
an empty DB after server relaunch). Use `get_success_data` internally so setup
failures surface as clear 'Setup failed' errors.

Identity threading: after a fixture creates an entity_backed:Creator or
entity_backed:FulfillmentPartner entity, ownership-gated calls in the same
fixture (and any consumer fixture) MUST use make_creator_headers(creator["id"])
or make_fulfillment_partner_headers(partner["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    creator_register_payload,
    creator_verify_payload,
    storefront_payload,
    product_payload,
    variant_payload,
    design_payload,
    listing_payload,
    order_payload,
    fulfillment_partner_payload,
    reprint_request_payload,
    payout_cycle_payload,
    clock_set_payload,
)
from .test_users import (
    make_creator_headers,
    make_fulfillment_partner_headers,
    make_anonymous_headers,
    make_platform_admin_headers,
)


# =============================================================================
# Tier 0: Utility — logical clock (PRD §2.10)
# =============================================================================

def set_clock(iso8601: str) -> None:
    """Advance the logical clock via the admin test-driving endpoint."""
    get_success_data(api_client.set_clock(
        clock_set_payload(iso8601),
        make_platform_admin_headers(),
    ))


# =============================================================================
# Tier 1: State-progression helpers
# =============================================================================

def create_creator(email: str, display_name: str = "Test C", country: str = "US") -> dict:
    """Register a Creator (does not verify). Returns the Creator dict."""
    resp = api_client.register_creator(
        creator_register_payload(email=email, display_name=display_name, payout_country_code=country),
        make_anonymous_headers(),
    )
    return get_success_data(resp)


def verify_creator(creator_id: str, outcome: str = "VERIFIED") -> dict:
    """Verify a Creator through the admin endpoint."""
    resp = api_client.verify_creator(
        creator_id,
        creator_verify_payload(outcome=outcome),
        make_platform_admin_headers(),
    )
    return get_success_data(resp)


def create_verified_creator(email: str, display_name: str = "Test C") -> dict:
    """Register + verify a Creator. Returns the verified Creator dict."""
    creator = create_creator(email=email, display_name=display_name)
    verify_creator(creator["id"])
    return creator


def create_active_partner(
    name: str = "US Print A",
    country_code: str = "US",
    cost_multiplier_bps: int = 10000,
    max_backlog_hours: int = 168,
) -> dict:
    """Create an ACTIVE FulfillmentPartner."""
    resp = api_client.create_fulfillment_partner(
        fulfillment_partner_payload(
            name=name,
            country_code=country_code,
            cost_multiplier_bps=cost_multiplier_bps,
            max_backlog_hours=max_backlog_hours,
        ),
        make_platform_admin_headers(),
    )
    return get_success_data(resp)


def create_product_and_variant(
    sku: str = "T-DEFAULT",
    category: str = "APPAREL",
    base_cost_cents: int = 2000,
    color: str = "BLACK",
    size: str = "M",
    base_cost_delta_cents: int = 0,
) -> tuple:
    """Admin creates a Product and one Variant under it. Returns (product, variant)."""
    prod_resp = api_client.create_product(
        product_payload(sku=sku, category=category, base_cost_cents=base_cost_cents),
        make_platform_admin_headers(),
    )
    product = get_success_data(prod_resp)
    var_payload = variant_payload(color=color, size=size)
    if base_cost_delta_cents:
        var_payload["base_cost_delta_cents"] = base_cost_delta_cents
    var_resp = api_client.create_variant(
        product["id"], var_payload, make_platform_admin_headers(),
    )
    variant = get_success_data(var_resp)
    return product, variant


def create_storefront(
    creator_id: str,
    slug: str = "test-sf",
    integration_channel: str = "NATIVE",
    markup_bps: int = 5000,
) -> dict:
    """Create a Storefront. Uses ownership-threaded headers."""
    resp = api_client.create_storefront(
        storefront_payload(
            creator_id=creator_id,
            slug=slug,
            integration_channel=integration_channel,
            markup_bps=markup_bps,
        ),
        make_creator_headers(creator_id),
    )
    return get_success_data(resp)


def upload_and_approve_design(creator_id: str, file_hash: str) -> dict:
    """Upload a Design, generate mockup, approve. Returns the APPROVED Design."""
    up_resp = api_client.upload_design(
        creator_id, design_payload(file_hash=file_hash),
        make_creator_headers(creator_id),
    )
    design = get_success_data(up_resp)
    get_success_data(api_client.generate_mockup(
        design["id"], make_creator_headers(creator_id),
    ))
    approved_resp = api_client.approve_design(
        design["id"], make_platform_admin_headers(),
    )
    return get_success_data(approved_resp)


def upload_mockup_ready_design(creator_id: str, file_hash: str) -> dict:
    """Upload + generate mockup only (no approve). Returns the MOCKUP_READY Design."""
    up_resp = api_client.upload_design(
        creator_id, design_payload(file_hash=file_hash),
        make_creator_headers(creator_id),
    )
    design = get_success_data(up_resp)
    mockup_resp = api_client.generate_mockup(
        design["id"], make_creator_headers(creator_id),
    )
    return get_success_data(mockup_resp)


def create_and_publish_listing(
    storefront_id: str,
    design_id: str,
    variant_id: str,
    creator_id: str,
    title: str = "Test Tee",
) -> dict:
    """Create a listing under a storefront and publish it. Returns the PUBLISHED Listing."""
    ln_resp = api_client.create_listing(
        listing_payload(storefront_id, design_id, variant_id, title=title),
        make_creator_headers(creator_id),
    )
    listing = get_success_data(ln_resp)
    pub_resp = api_client.publish_listing(
        listing["id"], make_creator_headers(creator_id),
    )
    return get_success_data(pub_resp)


# =============================================================================
# Tier 2: Composite hierarchy fixtures
# =============================================================================

def setup_basic_scenario(
    creator_email: str = "creator@example.com",
    display_name: str = "Test Creator",
    slug: str = "test-sf",
    integration_channel: str = "NATIVE",
    markup_bps: int = 5000,
    sku: str = "T-DEFAULT",
    category: str = "APPAREL",
    base_cost_cents: int = 2000,
    base_cost_delta_cents: int = 0,
    file_hash: str = "hash_default_1",
    listing_title: str = "Test Tee",
    partner_country: str = "US",
    partner_cost_multiplier_bps: int = 10000,
    partner_max_backlog_hours: int = 168,
    clock_iso: str = "2026-06-01T00:00:00Z",
    verify_creator_flag: bool = True,
    publish_listing_flag: bool = True,
) -> dict:
    """Complete baseline scenario: clock set + partner + product + variant +
    creator (verified) + storefront + approved design + (optionally) published listing.

    Returns a dict with keys:
      clock_iso, partner, product, variant, creator, storefront, design, listing
    """
    set_clock(clock_iso)
    partner = create_active_partner(
        country_code=partner_country,
        cost_multiplier_bps=partner_cost_multiplier_bps,
        max_backlog_hours=partner_max_backlog_hours,
    )
    product, variant = create_product_and_variant(
        sku=sku, category=category, base_cost_cents=base_cost_cents,
        base_cost_delta_cents=base_cost_delta_cents,
    )
    if verify_creator_flag:
        creator = create_verified_creator(email=creator_email, display_name=display_name)
    else:
        creator = create_creator(email=creator_email, display_name=display_name)
    storefront = create_storefront(
        creator_id=creator["id"], slug=slug,
        integration_channel=integration_channel, markup_bps=markup_bps,
    )
    design = upload_and_approve_design(creator["id"], file_hash=file_hash)

    listing = None
    if publish_listing_flag:
        listing = create_and_publish_listing(
            storefront_id=storefront["id"],
            design_id=design["id"],
            variant_id=variant["id"],
            creator_id=creator["id"],
            title=listing_title,
        )
    else:
        # Create in DRAFT (no publish)
        ln_resp = api_client.create_listing(
            listing_payload(storefront["id"], design["id"], variant["id"], title=listing_title),
            make_creator_headers(creator["id"]),
        )
        listing = get_success_data(ln_resp)

    return {
        "clock_iso": clock_iso,
        "partner": partner,
        "product": product,
        "variant": variant,
        "creator": creator,
        "storefront": storefront,
        "design": design,
        "listing": listing,
    }


# =============================================================================
# Tier 3: Full-lifecycle shortcuts
# =============================================================================

def create_order_and_authorize(
    scenario: dict,
    item_count: int = 1,
    is_sample: bool = False,
    buyer_email: str = "buyer@example.com",
    ship_country_code: str = "US",
) -> dict:
    """Create an Order against the scenario's PUBLISHED Listing and authorize it.
    Returns the Order dict (payment_status=AUTHORIZED, fulfillment_status=PENDING)."""
    # Anonymous acts as buyer for non-sample orders; Creator acts for sample orders.
    creator_id = scenario["creator"]["id"]
    if is_sample:
        headers = make_creator_headers(creator_id)
    else:
        headers = make_anonymous_headers()
    ord_resp = api_client.create_order(
        order_payload(
            storefront_id=scenario["storefront"]["id"],
            listing_id=scenario["listing"]["id"],
            buyer_email=buyer_email,
            ship_country_code=ship_country_code,
            item_count=item_count,
            is_sample=is_sample,
        ),
        headers,
    )
    order = get_success_data(ord_resp)
    auth_resp = api_client.authorize_order(order["id"], make_platform_admin_headers())
    return get_success_data(auth_resp)


def create_and_capture_order(
    scenario: dict,
    item_count: int = 1,
    is_sample: bool = False,
    buyer_email: str = "buyer@example.com",
    ship_country_code: str = "US",
) -> tuple:
    """Create + authorize + capture. Returns (order, job).
    After capture, order.payment_status=CAPTURED, fulfillment_status=ROUTED."""
    order = create_order_and_authorize(
        scenario, item_count=item_count, is_sample=is_sample,
        buyer_email=buyer_email, ship_country_code=ship_country_code,
    )
    cap_resp = api_client.capture_order(order["id"], make_platform_admin_headers())
    order_after = get_success_data(cap_resp)
    # Find the job for this order
    job = _find_job_for_order(order_after["id"])
    return order_after, job


def _find_job_for_order(order_id: str) -> dict:
    """Fetch the FulfillmentJob belonging to the given order via the list endpoint."""
    resp = api_client.list_fulfillment_jobs(
        make_platform_admin_headers(),
        params={"order_id": order_id},
    )
    data = get_success_data(resp)
    # Framework's get_success_data returns the data payload; for list endpoints
    # the payload is the list of records.
    if isinstance(data, list):
        jobs = data
    else:
        jobs = data
    assert jobs, f"Setup failed: no FulfillmentJob exists for order {order_id}"
    return jobs[0]


def advance_order_to_shipped(scenario: dict, order: dict) -> tuple:
    """mark-in-print then mark-shipped. Returns (order, job) updated."""
    partner_id = scenario["partner"]["id"]
    partner_headers = make_fulfillment_partner_headers(partner_id)
    get_success_data(api_client.mark_in_print(order["id"], partner_headers))
    shipped_resp = api_client.mark_shipped(order["id"], partner_headers)
    order_after = get_success_data(shipped_resp)
    job = _find_job_for_order(order["id"])
    return order_after, job


def advance_order_to_delivered(scenario: dict, order: dict) -> tuple:
    """Full IN_PRINT -> SHIPPED -> DELIVERED. Returns (order, job)."""
    order_after, _job = advance_order_to_shipped(scenario, order)
    partner_headers = make_fulfillment_partner_headers(scenario["partner"]["id"])
    del_resp = api_client.mark_delivered(order_after["id"], partner_headers)
    order_final = get_success_data(del_resp)
    job = _find_job_for_order(order_final["id"])
    return order_final, job


def fail_shipped_job(scenario: dict, job: dict) -> dict:
    """Mark a SHIPPED job as FAILED. Returns the updated job."""
    partner_headers = make_fulfillment_partner_headers(scenario["partner"]["id"])
    resp = api_client.mark_job_failed(job["id"], partner_headers)
    return get_success_data(resp)


def open_reprint_on_failed_job(
    job: dict,
    fault_category: str = "CONSUMER_FAULT",
    reason_code: str = "DAMAGED",
) -> dict:
    """Admin opens a ReprintRequest on a FAILED job. Returns the ReprintRequest."""
    resp = api_client.open_reprint_request(
        job["id"],
        reprint_request_payload(fault_category=fault_category, reason_code=reason_code),
        make_platform_admin_headers(),
    )
    return get_success_data(resp)


def setup_shipped_order_with_open_reprint(
    scenario: dict,
    item_count: int = 1,
    fault_category: str = "CONSUMER_FAULT",
    reason_code: str = "DAMAGED",
    buyer_email: str = "buyer@example.com",
) -> tuple:
    """Full lifecycle: create -> auth -> capture -> ship -> fail -> open reprint.
    Returns (order, job, reprint_request)."""
    order, _job = create_and_capture_order(
        scenario, item_count=item_count, buyer_email=buyer_email,
    )
    order, job = advance_order_to_shipped(scenario, order)
    fail_shipped_job(scenario, job)
    # Re-fetch job to get FAILED status
    job = _find_job_for_order(order["id"])
    reprint = open_reprint_on_failed_job(
        job, fault_category=fault_category, reason_code=reason_code,
    )
    # Re-fetch job again (FAILED -> REPRINT_REQUESTED)
    job = _find_job_for_order(order["id"])
    return order, job, reprint


# =============================================================================
# Tier 4: Payout / wallet setups
# =============================================================================

def setup_delivered_order_scenario(
    creator_email: str = "payout@example.com",
    slug: str = "payout-sf",
    file_hash: str = "hash_payout_1",
    sku: str = "T-PAYOUT",
    markup_bps: int = 5000,
    item_count: int = 1,
    clock_iso: str = "2026-06-15T00:00:00Z",
) -> dict:
    """Scenario + one DELIVERED, non-sample Order. Returns dict adding
    order and job to scenario keys."""
    scenario = setup_basic_scenario(
        creator_email=creator_email, slug=slug, file_hash=file_hash,
        sku=sku, markup_bps=markup_bps, clock_iso=clock_iso,
    )
    order, _job = create_and_capture_order(
        scenario, item_count=item_count, is_sample=False,
    )
    order, job = advance_order_to_delivered(scenario, order)
    scenario["order"] = order
    scenario["job"] = job
    return scenario


def create_payout_cycle(
    creator_id: str,
    cycle_start: str,
    cycle_end: str,
) -> dict:
    """Admin creates a DRAFT PayoutCycle."""
    resp = api_client.create_payout_cycle(
        creator_id, payout_cycle_payload(cycle_start, cycle_end),
        make_platform_admin_headers(),
    )
    return get_success_data(resp)


def release_payout_cycle(cycle_id: str) -> dict:
    resp = api_client.release_payout(cycle_id, make_platform_admin_headers())
    return get_success_data(resp)
