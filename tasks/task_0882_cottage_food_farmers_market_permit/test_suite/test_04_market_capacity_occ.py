"""Market day-slot capacity, occupancy conservation, and market-version OCC."""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    make_producer_headers, make_market_manager_headers, TEST_USERS,
    create_policy, create_registered_producer, create_class_a_issued_permit,
    create_approved_product, create_market, create_draft_manifest, submit_manifest,
    approve_manifest_fresh, add_approved_vendor,
)

INSPECTOR = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _capacity_one_second_vendor_submitted(api):
    """Market cap 1; vendor A's manifest APPROVED (slot full); vendor B's manifest
    SUBMITTED. Returns (market, vendor_b_producer_id, vendor_b_manifest_id)."""
    create_policy(api, food_category="BAKED_GOODS")
    market = create_market(api, max_vendors_per_day=1, allowed_classes=["CLASS_A"],
                           venue_type="TEMP_EVENT")
    a = add_approved_vendor(api, market=market, event_date="2026-06-15")
    approve_manifest_fresh(api, market["id"], a["manifest"]["id"])
    b = add_approved_vendor(api, market=market, event_date="2026-06-15")
    return market, b["producer"]["id"], b["manifest"]["id"]


def test_approve_at_capacity_boundary_rejected(api):
    """PRD §3.4: "requires that the count of manifests already in `APPROVED` or
    `CHECKED_IN` for that market and event date be strictly below the market's
    `max_vendors_per_day` (else `ERR_MARKET_CAPACITY_FULL`)."

    Design: Difficulty/boundary_precision_check/market_capacity_count_boundary
    """
    market, _pb, mb = _capacity_one_second_vendor_submitted(api)
    version = get_success_data(api.get_market(market["id"], ADMIN))["version"]
    resp = api.approve_manifest(mb, {"expected_market_version": version},
                                make_market_manager_headers(market["id"]))
    validate_error(resp, ApiErrorId.ERR_MARKET_CAPACITY_FULL.value, 409)


def test_approve_at_capacity_boundary_keeps_manifest_submitted(api):
    """PRD §3.4: "requires that the count of manifests already in `APPROVED` or
    `CHECKED_IN` for that market and event date be strictly below the market's
    `max_vendors_per_day` (else `ERR_MARKET_CAPACITY_FULL`)."

    Design: Difficulty/boundary_precision_check/market_capacity_count_boundary
    """
    market, _pb, mb = _capacity_one_second_vendor_submitted(api)
    version = get_success_data(api.get_market(market["id"], ADMIN))["version"]
    validate_error(api.approve_manifest(mb, {"expected_market_version": version},
                                        make_market_manager_headers(market["id"])),
                   ApiErrorId.ERR_MARKET_CAPACITY_FULL.value, 409)
    after = validate_success(api.get_manifest(mb, INSPECTOR), 200)
    assert after["status"] == "SUBMITTED"


def test_approve_with_stale_market_version_rejected(api):
    """PRD §2.9: "Because each prior approval consumes a day-slot and bumps the market's
    `version`, a manager acting on a stale market view — whose last slot may already be
    taken — is rejected with `ERR_STALE_MARKET_VERSION` at HTTP 412."

    Design: Corner/cross_cutting/occ_stale_market_version_rejected
    """
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="Occ Co")
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = create_approved_product(api, pid, unit_price_cents=300)
    market = create_market(api, max_vendors_per_day=2, allowed_classes=["CLASS_A"])
    mv0 = market["version"]
    m1 = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], "2026-06-15")
    submit_manifest(api, pid, m1["id"])
    m2 = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]], "2026-06-16")
    submit_manifest(api, pid, m2["id"])
    mm = make_market_manager_headers(market["id"])
    validate_success(api.approve_manifest(m1["id"], {"expected_market_version": mv0}, mm), 200)
    resp = api.approve_manifest(m2["id"], {"expected_market_version": mv0}, mm)
    validate_error(resp, ApiErrorId.ERR_STALE_MARKET_VERSION.value, 412)
    after = validate_success(api.get_manifest(m2["id"], INSPECTOR), 200)
    assert after["status"] == "SUBMITTED"


def _withdraw_frees_slot_setup(api):
    """Market cap 1; vendor A APPROVED (slot held); vendor B SUBMITTED; then A withdraws.
    Returns (market, producer_a_id, manifest_a_id, manifest_b_id)."""
    create_policy(api, food_category="BAKED_GOODS")
    market = create_market(api, max_vendors_per_day=1, allowed_classes=["CLASS_A"],
                           venue_type="TEMP_EVENT")
    a = add_approved_vendor(api, market=market, event_date="2026-06-15")
    approve_manifest_fresh(api, market["id"], a["manifest"]["id"])
    b = add_approved_vendor(api, market=market, event_date="2026-06-15")
    # Producer A withdraws its APPROVED manifest, releasing the single day-slot.
    validate_success(api.withdraw_manifest(a["manifest"]["id"],
                                           make_producer_headers(a["producer"]["id"])), 200)
    return market, a["manifest"]["id"], b["manifest"]["id"]


def test_withdraw_releases_slot_marks_manifest_withdrawn(api):
    """PRD §3.4: "A producer may withdraw their own manifest from either `SUBMITTED` or
    `APPROVED`, moving it to `WITHDRAWN`; when the withdrawn manifest had been
    `APPROVED`, the withdrawal releases the held day-slot and increments the market's
    `version` by one, preserving the occupancy-conservation invariant of §2.8."

    Design: Difficulty/compensating_invariant/market_slot_conserved_on_withdraw
    """
    market, ma, mb = _withdraw_frees_slot_setup(api)
    after_a = validate_success(api.get_manifest(ma, INSPECTOR), 200)
    assert after_a["status"] == "WITHDRAWN"


def test_freed_slot_lets_second_vendor_be_approved(api):
    """PRD §2.8: "The count of occupied slots for a given market and event date must
    therefore always equal the number of manifests currently in `APPROVED` or
    `CHECKED_IN` for that market and date."

    Design: Difficulty/compensating_invariant/market_slot_conserved_on_withdraw
    """
    market, ma, mb = _withdraw_frees_slot_setup(api)
    approved_b = approve_manifest_fresh(api, market["id"], mb)
    assert approved_b["status"] == "APPROVED"


def test_producer_cannot_approve_manifest(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/producer_cannot_approve_manifest_unauthorized
    """
    create_policy(api, food_category="BAKED_GOODS")
    producer = create_registered_producer(api, business_name="Rb2 Co")
    pid = producer["id"]
    permit = create_class_a_issued_permit(api, pid)
    product = create_approved_product(api, pid, unit_price_cents=300)
    market = create_market(api, allowed_classes=["CLASS_A"])
    manifest = create_draft_manifest(api, pid, market["id"], permit["id"], [product["id"]])
    submit_manifest(api, pid, manifest["id"])
    resp = api.approve_manifest(manifest["id"], {"expected_market_version": market["version"]},
                                make_producer_headers(pid))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
