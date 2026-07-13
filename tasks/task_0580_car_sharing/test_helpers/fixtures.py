"""Composite setup helpers for the Car Sharing API.

Every interesting claim needs the system walked into a specific state (a
CONFIRMED trip, a CHECKED_OUT trip with a claim UNDER_REVIEW, an approved
extension cascade, ...). These builders encapsulate those multi-step preambles
so tests focus on assertions.

The runner restarts the server (empty DB, logical clock reset to
2026-05-01T00:00:00Z) before every test, so each fixture builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so a broken precondition surfaces as "Setup
failed" rather than a confusing assertion.

Identity threading (PRD §2.1): Host and Guest are entity_backed; ownership-gated
calls use make_host_headers(host['id']) / make_guest_headers(guest['id']) with
the real id, never a shared fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    make_host_headers, make_guest_headers, make_admin_headers, make_anonymous_headers,
)
from .factories import (
    create_host_payload, create_guest_payload, submit_verification_payload,
    create_plan_payload, create_vehicle_payload, create_pricing_rule_payload,
    create_trip_payload, inspection_payload, create_extension_payload,
    create_claim_payload,
)

ADMIN = make_admin_headers()
ANON = make_anonymous_headers()


# --------------------------------------------------------------- primitives
def register_host(api, **overrides) -> dict:
    resp = api.create_host(create_host_payload(**overrides), ANON)
    return get_success_data(resp)


def register_unverified_guest(api, **overrides) -> dict:
    resp = api.create_guest(create_guest_payload(**overrides), ANON)
    return get_success_data(resp)


def register_verified_guest(api, license_number="DL-0001", **overrides) -> dict:
    guest = register_unverified_guest(api, **overrides)
    gid = guest["id"]
    headers = make_guest_headers(gid)
    api.submit_verification(gid, submit_verification_payload(license_number=license_number), headers)
    resp = api.verify_guest(gid, ADMIN)
    return get_success_data(resp)


def create_plan(api, **overrides) -> dict:
    resp = api.create_plan(create_plan_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_vehicle(api, host_id, **overrides) -> dict:
    """Create a DRAFT vehicle owned by host_id."""
    headers = make_host_headers(host_id)
    resp = api.create_vehicle(create_vehicle_payload(host_id, **overrides), headers)
    return get_success_data(resp)


def create_listed_vehicle(api, host_id, **overrides) -> dict:
    """Create a vehicle and transition it to LISTED. Returns the listed vehicle."""
    vehicle = create_vehicle(api, host_id, **overrides)
    headers = make_host_headers(host_id)
    resp = api.list_vehicle(vehicle["id"], headers)
    return get_success_data(resp)


def current_vehicle_version(api, vehicle_id) -> int:
    resp = api.get_vehicle(vehicle_id, ADMIN)
    return get_success_data(resp)["version"]


def current_host_version(api, host_id) -> int:
    resp = api.get_host(host_id, ADMIN)
    return get_success_data(resp)["version"]


def set_clock(api, iso: str):
    api.set_clock(iso, ADMIN)


def book_trip(api, vehicle_id, guest_id, plan_id, start_date, end_date,
              expected_version=None) -> dict:
    if expected_version is None:
        expected_version = current_vehicle_version(api, vehicle_id)
    headers = make_guest_headers(guest_id)
    payload = create_trip_payload(vehicle_id, guest_id, plan_id, start_date, end_date, expected_version)
    resp = api.create_trip(payload, headers)
    return get_success_data(resp)


def get_booked_block(api, trip_id) -> dict:
    """Return the single AvailabilityBlock wired to this trip (PRD §3.4)."""
    resp = api.list_availability_blocks(ADMIN, params={"trip_id": trip_id})
    blocks = get_success_data(resp)
    assert isinstance(blocks, list) and len(blocks) >= 1, "expected a BOOKED block for the trip"
    return blocks[0]


# ----------------------------------------------------------- composite tiers
def setup_requested_trip(api, start_date="2026-06-01", end_date="2026-06-08",
                         vehicle_overrides=None, plan_overrides=None,
                         guest_verified=True) -> dict:
    """Verified guest + STANDARD plan + LISTED vehicle + a REQUESTED trip.

    Returns a context dict with host, guest, plan, vehicle (listed) and trip,
    plus ready-made role headers.
    """
    vehicle_overrides = vehicle_overrides or {}
    plan_overrides = plan_overrides or {}
    host = register_host(api)
    guest = (register_verified_guest(api) if guest_verified
             else register_unverified_guest(api))
    plan = create_plan(api, **plan_overrides)
    vehicle = create_listed_vehicle(api, host["id"], **vehicle_overrides)
    trip = book_trip(api, vehicle["id"], guest["id"], plan["id"], start_date, end_date)
    return {
        "host": host,
        "guest": guest,
        "plan": plan,
        "vehicle": vehicle,
        "trip": trip,
        "host_headers": make_host_headers(host["id"]),
        "guest_headers": make_guest_headers(guest["id"]),
        "admin_headers": ADMIN,
    }


def setup_confirmed_trip(api, **kwargs) -> dict:
    ctx = setup_requested_trip(api, **kwargs)
    resp = api.approve_trip(ctx["trip"]["id"], ctx["host_headers"])
    ctx["trip"] = get_success_data(resp)
    return ctx


def setup_checked_in_trip(api, checkin_odometer=10000, checkin_fuel_pct=100,
                          checkin_clock="2026-06-01T10:00:00Z", **kwargs) -> dict:
    ctx = setup_confirmed_trip(api, **kwargs)
    set_clock(api, checkin_clock)
    resp = api.checkin_trip(
        ctx["trip"]["id"],
        inspection_payload(checkin_odometer, checkin_fuel_pct, ["in1"]),
        ctx["guest_headers"],
    )
    ctx["trip"] = get_success_data(resp)
    return ctx


def setup_checked_out_trip(api, checkin_odometer=10000, checkin_fuel_pct=100,
                           checkout_odometer=10500, checkout_fuel_pct=100,
                           checkin_clock="2026-06-01T10:00:00Z",
                           checkout_clock="2026-06-08T09:00:00Z", **kwargs) -> dict:
    ctx = setup_checked_in_trip(
        api, checkin_odometer=checkin_odometer, checkin_fuel_pct=checkin_fuel_pct,
        checkin_clock=checkin_clock, **kwargs,
    )
    set_clock(api, checkout_clock)
    resp = api.checkout_trip(
        ctx["trip"]["id"],
        inspection_payload(checkout_odometer, checkout_fuel_pct, ["out1"]),
        ctx["guest_headers"],
    )
    ctx["trip"] = get_success_data(resp)
    return ctx


def setup_completed_trip(api, **kwargs) -> dict:
    ctx = setup_checked_out_trip(api, **kwargs)
    resp = api.complete_trip(ctx["trip"]["id"], ctx["host_headers"])
    ctx["trip"] = get_success_data(resp)
    return ctx


def file_claim(api, ctx, claimant="HOST", damage_amount_cents=200000,
               description="incident") -> dict:
    """File a claim on the ctx trip. HOST claims use host headers, GUEST claims
    use guest headers (both are shared claim actors per PRD §4)."""
    headers = ctx["host_headers"] if claimant == "HOST" else ctx["guest_headers"]
    resp = api.create_claim(
        ctx["trip"]["id"],
        create_claim_payload(claimant, damage_amount_cents, description),
        headers,
    )
    return get_success_data(resp)


def setup_claim_under_review(api, claimant="HOST", damage_amount_cents=200000, **kwargs) -> dict:
    """CHECKED_OUT trip + a claim filed and advanced FILED -> UNDER_REVIEW."""
    ctx = setup_checked_out_trip(api, **kwargs)
    claim = file_claim(api, ctx, claimant, damage_amount_cents)
    resp = api.start_review_claim(claim["id"], ADMIN)
    ctx["claim"] = get_success_data(resp)
    return ctx


def setup_requested_extension(api, new_end_date="2026-06-10", **kwargs) -> dict:
    """CONFIRMED trip + a REQUESTED extension to new_end_date."""
    ctx = setup_confirmed_trip(api, **kwargs)
    resp = api.create_extension(
        ctx["trip"]["id"], create_extension_payload(new_end_date), ctx["guest_headers"],
    )
    ctx["extension"] = get_success_data(resp)
    return ctx


def add_active_pricing_rule(api, host_id, vehicle_id, start_date, end_date, daily_price_cents) -> dict:
    headers = make_host_headers(host_id)
    resp = api.create_pricing_rule(
        create_pricing_rule_payload(vehicle_id, start_date, end_date, daily_price_cents), headers,
    )
    return get_success_data(resp)
