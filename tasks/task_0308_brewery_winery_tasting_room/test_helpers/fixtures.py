"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for every setup call so a failed
precondition surfaces as a clear "Setup step failed" error rather than a
confusing downstream assertion failure.

Build order mirrors the PRD's production -> club pipeline:
  winery -> batch -> (age -> bottling) -> bottling run -> product activate
         -> release create/open -> member create/activate -> membership enroll/activate
         -> shipment schedule.

The four staff roles are opaque (X-User-ID is an operator token), so the shared
TEST_USERS headers are canonical for them. The Member role is entity_backed and
its ownership-gated reads must use make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_winery_payload, create_batch_payload, create_product_payload,
    create_release_payload, create_member_payload, create_membership_payload,
    create_shipment_payload,
)
from .test_users import TEST_USERS

CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["cellar_manager_headers"]
CLM = TEST_USERS["club_manager_headers"]
TRS = TEST_USERS["tasting_room_staff_headers"]

DEFAULT_CLOCK = "2026-06-15T00:00:00Z"


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Pin the deterministic server clock (ComplianceOfficer-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, CO))


# ─── Tier 1: Single-entity creation shortcuts ─────────

def create_winery(**overrides):
    """Create an ACTIVE bonded winery. Returns the winery dict."""
    return get_success_data(api_client.create_winery(create_winery_payload(**overrides), CO))


def create_batch(winery_id, **overrides):
    """Create a FERMENTING production batch. Returns the batch dict."""
    return get_success_data(
        api_client.create_batch(create_batch_payload(winery_id, **overrides), CM)
    )


def create_product(winery_id, source_batch_id, **overrides):
    """Create a DRAFT product. Returns the product dict."""
    return get_success_data(
        api_client.create_product(create_product_payload(winery_id, source_batch_id, **overrides), CM)
    )


# ─── Tier 2: Batch lifecycle progression ──────────────

def advance_batch_to_bottling(batch_id):
    """Walk a FERMENTING batch through AGING into BOTTLING. Returns the batch dict."""
    get_success_data(api_client.transition_batch(batch_id, {"action": "BEGIN_AGING"}, CM))
    return get_success_data(api_client.transition_batch(batch_id, {"action": "OPEN_BOTTLING"}, CM))


def create_batch_in_bottling(winery_id, batch_overrides=None):
    """Create a batch already advanced to BOTTLING. Returns the batch dict."""
    batch = create_batch(winery_id, **(batch_overrides or {}))
    advance_batch_to_bottling(batch["id"])
    return get_success_data(api_client.get_batch(batch["id"], CM))


def bottle_run(batch_id, product_id, requested_bottles):
    """Perform one bottling run. Returns the batch dict (the endpoint's output)."""
    return get_success_data(api_client.create_bottling_run(
        batch_id, {"product_id": product_id, "requested_bottles": requested_bottles}, CM))


# ─── Tier 3: Product to ACTIVE (bottled + activated) ──

def setup_active_product(winery_id=None, bottled_bottles=10, batch_overrides=None,
                         product_overrides=None):
    """winery (if not given) -> batch in BOTTLING -> product -> bottle N -> ACTIVATE product.

    Returns (winery, batch, product) with the product ACTIVE and carrying
    `bottled_bottles` of on_hand inventory.
    """
    if winery_id is None:
        winery = create_winery()
        winery_id = winery["id"]
    else:
        winery = get_success_data(api_client.get_winery(winery_id, CO))

    batch = create_batch(winery_id, **(batch_overrides or {}))
    advance_batch_to_bottling(batch["id"])
    product = create_product(winery_id, batch["id"], **(product_overrides or {}))
    if bottled_bottles > 0:
        bottle_run(batch["id"], product["id"], bottled_bottles)
    pv0 = get_success_data(api_client.get_product(product["id"], CM))["version"]
    product = get_success_data(api_client.transition_product(
        product["id"], {"action": "ACTIVATE", "expected_product_version": pv0}, CM))
    batch = get_success_data(api_client.get_batch(batch["id"], CM))
    winery = get_success_data(api_client.get_winery(winery_id, CO))
    return winery, batch, product


# ─── Tier 4: Open allocation release on an ACTIVE product ───

def setup_open_release(winery_id=None, pool_bottles=6, per_member_cap=6,
                       bottled_bottles=None, opens_at="2026-06-01T00:00:00Z",
                       closes_at="2026-07-01T00:00:00Z", product_overrides=None):
    """Active product -> create release -> OPEN_RELEASE.

    Bottles enough inventory to cover the pool (defaults to pool_bottles unless
    `bottled_bottles` is given). Returns (winery, product, release).
    """
    if bottled_bottles is None:
        bottled_bottles = pool_bottles
    winery, batch, product = setup_active_product(
        winery_id=winery_id, bottled_bottles=bottled_bottles,
        product_overrides=product_overrides)
    release = get_success_data(api_client.create_release(
        create_release_payload(winery["id"], product["id"], pool_bottles=pool_bottles,
                               per_member_cap=per_member_cap, opens_at=opens_at,
                               closes_at=closes_at), CM))
    pv = get_success_data(api_client.get_product(product["id"], CM))["version"]
    release = get_success_data(api_client.transition_release(
        release["id"],
        {"action": "OPEN_RELEASE", "expected_release_version": release["version"],
         "expected_product_version": pv}, CM))
    product = get_success_data(api_client.get_product(product["id"], CM))
    return winery, product, release


# ─── Tier 5: Active member + membership ───────────────

def setup_active_member(winery_id, dob="1990-01-01T00:00:00Z", ship_to_state_code="CA",
                        email="ada@x.com", **member_overrides):
    """Create a member and ACTIVATE it. Returns the member dict."""
    member = get_success_data(api_client.create_member(
        create_member_payload(winery_id, date_of_birth=dob,
                              ship_to_state_code=ship_to_state_code,
                              email=email, **member_overrides), CLM))
    member = get_success_data(api_client.transition_member(
        member["id"], {"action": "ACTIVATE"}, CLM))
    return member


def setup_active_membership(winery_id, member_id, tier="SILVER", cadence_months=3,
                            bottles_per_shipment=6):
    """Enroll a membership and ACTIVATE it. Returns the membership dict."""
    membership = get_success_data(api_client.create_membership(
        create_membership_payload(winery_id, member_id, tier=tier,
                                  cadence_months=cadence_months,
                                  bottles_per_shipment=bottles_per_shipment), CLM))
    membership = get_success_data(api_client.transition_membership(
        membership["id"], {"action": "ACTIVATE"}, CLM))
    return membership


# ─── Tier 6: Full club setup ready to schedule shipments ───

def setup_club_ready(pool_bottles=12, per_member_cap=12, tier="PLATINUM",
                     bottled_bottles=None, dob="1990-01-01T00:00:00Z",
                     ship_to_state_code="CA", list_price_cents=5000,
                     opens_at="2026-06-01T00:00:00Z", closes_at="2026-07-01T00:00:00Z",
                     clock=DEFAULT_CLOCK):
    """Full pipeline ready to schedule a shipment.

    clock set -> winery -> active product (bottled) -> open release ->
    active member -> active membership.

    Returns (winery, product, release, member, membership).
    """
    set_clock(clock)
    winery, product, release = setup_open_release(
        pool_bottles=pool_bottles, per_member_cap=per_member_cap,
        bottled_bottles=bottled_bottles,
        opens_at=opens_at, closes_at=closes_at,
        product_overrides={"list_price_cents": list_price_cents})
    member = setup_active_member(winery["id"], dob=dob, ship_to_state_code=ship_to_state_code)
    membership = setup_active_membership(winery["id"], member["id"], tier=tier)
    return winery, product, release, member, membership


def schedule_shipment(winery_id, membership_id, release_id, requested_bottles):
    """Schedule a SCHEDULED shipment drawing on a release. Returns the shipment dict."""
    return get_success_data(api_client.create_shipment(
        create_shipment_payload(winery_id, membership_id, release_id, requested_bottles), CLM))


def setup_scheduled_shipment(requested_bottles=12, **club_kwargs):
    """setup_club_ready -> schedule one shipment.

    Returns (winery, product, release, member, membership, shipment).
    """
    winery, product, release, member, membership = setup_club_ready(**club_kwargs)
    shipment = schedule_shipment(winery["id"], membership["id"], release["id"], requested_bottles)
    return winery, product, release, member, membership, shipment


# ─── Tier 7: Reservation helpers ──────────────────────

def create_confirmed_reservation(winery_id, table_code="T1",
                                 starts_at="2026-06-20T18:00:00Z",
                                 ends_at="2026-06-20T19:00:00Z", party_size=2):
    """Create a reservation and CONFIRM it. Returns the reservation dict."""
    from .factories import create_reservation_payload
    res = get_success_data(api_client.create_reservation(
        create_reservation_payload(winery_id, table_code=table_code, party_size=party_size,
                                   starts_at=starts_at, ends_at=ends_at), TRS))
    res = get_success_data(api_client.transition_reservation(res["id"], {"action": "CONFIRM"}, TRS))
    return res


# ─── Tier 8: Distribution helpers ─────────────────────

def setup_submitted_distribution_order(case_count=1, bottled_bottles=50,
                                       list_price_cents=5000):
    """Active product -> create distribution order -> SUBMIT.

    Returns (winery, product, dist_order).
    """
    from .factories import create_distribution_order_payload
    winery, batch, product = setup_active_product(
        bottled_bottles=bottled_bottles,
        product_overrides={"list_price_cents": list_price_cents})
    dist = get_success_data(api_client.create_distribution_order(
        create_distribution_order_payload(winery["id"], product["id"], case_count=case_count), CO))
    dist = get_success_data(api_client.transition_distribution_order(
        dist["id"], {"action": "SUBMIT"}, CO))
    return winery, product, dist
