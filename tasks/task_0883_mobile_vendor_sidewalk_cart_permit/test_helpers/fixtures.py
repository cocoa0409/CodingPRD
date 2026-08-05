"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a broken precondition
surfaces as a clear "setup failed" rather than a confusing assertion error.

The harness restarts the server (empty DB) before every test, so every helper
here builds its full precondition chain from scratch using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_vendor_payload, insurance_payload, create_commissary_payload,
    create_cart_payload, inspection_payload, create_zone_payload,
    create_spot_payload, create_permit_payload, create_violation_payload,
    create_spot_assignment_payload, adjudicate_payload,
)
from .test_users import (
    TEST_USERS, make_vendor_headers, OFFICER_ISSUER_ID, OFFICER_ADJUDICATOR_ID,
    make_enforcement_headers,
)
from .constants import DEFAULT_TEST_CLOCK

PO = TEST_USERS["permit_officer_headers"]
HI = TEST_USERS["health_inspector_headers"]


# --------------------------------------------------------------------------- #
# Primitive helpers
# --------------------------------------------------------------------------- #
def set_clock(iso=DEFAULT_TEST_CLOCK):
    return get_success_data(api_client.set_clock(iso, PO))


def zone_version(zone_id):
    """Fetch the zone's current version for use as expected_zone_version."""
    zone = get_success_data(api_client.get_zone(zone_id, PO))
    return zone["version"]


def create_vendor(seniority_years=0, **overrides):
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(seniority_years=seniority_years, **overrides), PO))


def activate_insurance(vendor_id, **overrides):
    return get_success_data(api_client.submit_insurance(
        vendor_id, insurance_payload(**overrides), make_vendor_headers(vendor_id)))


def create_insured_vendor(seniority_years=0, insurance_overrides=None, **vendor_overrides):
    vendor = create_vendor(seniority_years=seniority_years, **vendor_overrides)
    activate_insurance(vendor["id"], **(insurance_overrides or {}))
    return get_success_data(api_client.get_vendor(vendor["id"], PO))


def create_commissary(**overrides):
    return get_success_data(api_client.create_commissary(create_commissary_payload(**overrides), HI))


def create_cart(vendor_id, commissary_id, size_sqft=30, inspect=True,
                inspection_overrides=None, approve=True, **cart_overrides):
    vh = make_vendor_headers(vendor_id)
    cart = get_success_data(api_client.create_cart(
        create_cart_payload(vendor_id, commissary_id, size_sqft=size_sqft, **cart_overrides), vh))
    if inspect:
        get_success_data(api_client.inspect_cart(
            cart["id"], inspection_payload(**(inspection_overrides or {})), HI))
    if approve:
        get_success_data(api_client.approve_cart(cart["id"], PO))
    return get_success_data(api_client.get_cart(cart["id"], PO))


def create_zone(zone_type="STANDARD", capacity_slots=5, spacing_min_feet=20, **overrides):
    return get_success_data(api_client.create_zone(
        create_zone_payload(zone_type=zone_type, capacity_slots=capacity_slots,
                            spacing_min_feet=spacing_min_feet, **overrides), PO))


def create_spot(zone_id, label="S1", position_feet=100):
    return get_success_data(api_client.create_spot(
        zone_id, create_spot_payload(label=label, position_feet=position_feet), PO))


def create_draft_permit(vendor_id, cart_id, zone_id, permit_type="FOOD"):
    return get_success_data(api_client.create_permit(
        create_permit_payload(vendor_id, cart_id, zone_id, permit_type=permit_type),
        make_vendor_headers(vendor_id)))


def create_submitted_permit(vendor_id, cart_id, zone_id, permit_type="FOOD"):
    permit = create_draft_permit(vendor_id, cart_id, zone_id, permit_type)
    get_success_data(api_client.submit_permit(permit["id"], make_vendor_headers(vendor_id)))
    return get_success_data(api_client.get_permit(permit["id"], PO))


def issue_permit(permit_id):
    return get_success_data(api_client.issue_permit(permit_id, PO))


def create_issued_permit(vendor_id, cart_id, zone_id, permit_type="FOOD"):
    permit = create_submitted_permit(vendor_id, cart_id, zone_id, permit_type)
    return issue_permit(permit["id"])


# --------------------------------------------------------------------------- #
# Tier 2/3: One-call scenario builders
# --------------------------------------------------------------------------- #
def setup_issued_permit(clock=DEFAULT_TEST_CLOCK, zone_type="STANDARD", capacity_slots=5,
                        spacing_min_feet=20, size_sqft=30, seniority_years=0,
                        insurance_overrides=None, num_spots=0, spot_positions=None):
    """Full happy-path chain to an ISSUED permit on a STANDARD/MEDIUM cart.

    Returns a dict with keys: vendor, commissary, cart, zone, permit, spots,
    vendor_headers. `spots` is a list of created Spot dicts (empty unless
    num_spots>0 or spot_positions provided).
    """
    set_clock(clock)
    vendor = create_insured_vendor(seniority_years=seniority_years,
                                   insurance_overrides=insurance_overrides)
    commissary = create_commissary()
    cart = create_cart(vendor["id"], commissary["id"], size_sqft=size_sqft)
    zone = create_zone(zone_type=zone_type, capacity_slots=capacity_slots,
                       spacing_min_feet=spacing_min_feet)
    spots = []
    if spot_positions is not None:
        for i, pos in enumerate(spot_positions):
            spots.append(create_spot(zone["id"], label=f"S{i}", position_feet=pos))
    else:
        for i in range(num_spots):
            spots.append(create_spot(zone["id"], label=f"S{i}", position_feet=100 + i * 100))
    permit = create_issued_permit(vendor["id"], cart["id"], zone["id"])
    return {
        "vendor": vendor,
        "commissary": commissary,
        "cart": cart,
        "zone": zone,
        "permit": permit,
        "spots": spots,
        "vendor_headers": make_vendor_headers(vendor["id"]),
    }


def assign_spot(permit_id, spot_id, start_at, end_at, expected_zone_version=None,
                zone_id=None, headers=PO):
    """Create a direct spot assignment. If expected_zone_version is omitted,
    the current zone version is fetched first (requires zone_id)."""
    if expected_zone_version is None:
        assert zone_id is not None, "assign_spot needs zone_id when version omitted"
        expected_zone_version = zone_version(zone_id)
    res = api_client.create_spot_assignment(
        permit_id,
        create_spot_assignment_payload(spot_id, start_at, end_at, expected_zone_version),
        headers)
    return res


def setup_permit_with_active_assignment(clock=DEFAULT_TEST_CLOCK, spot_position=100,
                                        start_at="2026-06-01T09:00:00Z",
                                        end_at="2026-06-01T17:00:00Z"):
    """ISSUED permit with one ACTIVE DIRECT SpotAssignment on a single spot.

    Returns dict adding keys: spot, assignment.
    """
    ctx = setup_issued_permit(clock=clock, spot_positions=[spot_position])
    spot = ctx["spots"][0]
    res = assign_spot(ctx["permit"]["id"], spot["id"], start_at, end_at,
                      expected_zone_version=ctx["zone"]["version"])
    ctx["spot"] = spot
    ctx["assignment"] = get_success_data(res)
    return ctx


def issue_upheld_violation(permit_id, violation_type="MAJOR",
                           issuer_id=OFFICER_ISSUER_ID, adjudicator_id=OFFICER_ADJUDICATOR_ID):
    """Create a violation and adjudicate it UPHELD by a different officer.

    Returns the final Violation dict.
    """
    vio = get_success_data(api_client.create_violation(
        permit_id, create_violation_payload(violation_type=violation_type, description="v"),
        make_enforcement_headers(issuer_id)))
    get_success_data(api_client.adjudicate_violation(
        vio["id"], adjudicate_payload("UPHOLD"), make_enforcement_headers(adjudicator_id)))
    return get_success_data(api_client.get_violation(vio["id"], PO))


# --------------------------------------------------------------------------- #
# Impound helpers
# --------------------------------------------------------------------------- #
def create_held_impound(cart_id, reason="UNPERMITTED", impounded_at="2026-06-01T00:00:00Z",
                        issuer_id=OFFICER_ISSUER_ID):
    from .factories import create_impound_payload
    return get_success_data(api_client.create_impound(
        cart_id, create_impound_payload(reason=reason, impounded_at=impounded_at),
        make_enforcement_headers(issuer_id)))


# --------------------------------------------------------------------------- #
# Lottery helpers
# --------------------------------------------------------------------------- #
def setup_prime_zone_with_lottery(clock=DEFAULT_TEST_CLOCK, capacity_slots=1,
                                  spot_positions=(50,), entry_fee_cents=2_500):
    """PRIME zone + spots + an OPEN lottery over it. Returns dict with zone, spots,
    lottery, commissary."""
    from .factories import create_lottery_payload
    set_clock(clock)
    zone = create_zone(zone_type="PRIME", capacity_slots=capacity_slots, spacing_min_feet=20, name="Prime")
    spots = [create_spot(zone["id"], label=f"PS{i}", position_feet=pos)
             for i, pos in enumerate(spot_positions)]
    commissary = create_commissary()
    lottery = get_success_data(api_client.create_lottery(
        create_lottery_payload(zone["id"], entry_fee_cents=entry_fee_cents), PO))
    return {"zone": zone, "spots": spots, "commissary": commissary, "lottery": lottery}


def create_prime_entrant(zone_id, commissary_id, seniority_years, lottery_id, preferred_spot_ids):
    """Create an insured vendor + approved cart + ISSUED permit on the prime zone,
    then enter the lottery. Returns (vendor, permit, entry)."""
    from .factories import create_lottery_entry_payload
    vendor = create_insured_vendor(seniority_years=seniority_years)
    cart = create_cart(vendor["id"], commissary_id, size_sqft=30)
    permit = create_issued_permit(vendor["id"], cart["id"], zone_id)
    entry = get_success_data(api_client.create_lottery_entry(
        lottery_id, create_lottery_entry_payload(permit["id"], preferred_spot_ids),
        make_vendor_headers(vendor["id"])))
    return vendor, permit, entry
