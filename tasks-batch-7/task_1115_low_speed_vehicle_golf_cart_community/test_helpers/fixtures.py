"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
surface as clear "Setup failed" errors instead of confusing assertion
failures. Every fixture builds its preconditions from scratch via the public
API — the test runner restarts the server before every test, so each test
starts against an empty database and the logical clock at 2026-05-01T00:00:00Z.

Identity threading: PermitHolder is entity-backed (PRD §2.1). After creating a
holder, every ownership-gated call uses make_permit_holder_headers(holder_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_charging_reservation_payload,
    create_charging_station_payload,
    create_community_payload,
    create_fleet_dispatch_payload,
    create_fleet_vehicle_payload,
    create_full_equipment_lsv_payload,
    create_inspection_payload,
    create_insurance_policy_payload,
    create_permit_holder_payload,
    create_registration_payload,
    create_route_pass_payload,
    create_route_payload,
    create_vehicle_payload,
    create_violation_payload,
    finalize_inspection_payload,
    wallet_deposit_payload,
)
from .test_users import TEST_USERS, make_permit_holder_headers

ADMIN = TEST_USERS["platform_admin_headers"]
COMMUNITY_ADMIN = TEST_USERS["community_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Tier 1: single-entity state progression ─────────────────────────────

def create_community(name="Test Community", **overrides):
    """Create a community as PlatformAdmin. Returns the community dict."""
    res = api_client.create_community(create_community_payload(name=name, **overrides), ADMIN)
    return get_success_data(res)


def create_holder(community_id: str, **overrides):
    """Self-register a permit holder (Anonymous). Returns the holder dict."""
    res = api_client.create_permit_holder(
        create_permit_holder_payload(community_id, **overrides), ANON)
    return get_success_data(res)


def create_eligible_holder(community_id: str, **overrides):
    """Create a holder and verify eligibility (PENDING_VERIFICATION -> ELIGIBLE).
    Returns the ELIGIBLE holder dict."""
    holder = create_holder(community_id, **overrides)
    res = api_client.verify_eligibility(holder["id"], COMMUNITY_ADMIN)
    return get_success_data(res)


def deposit(holder_id: str, amount_cents: int, expected_version: int):
    """Deposit into a holder wallet (OCC-guarded). Returns updated holder."""
    res = api_client.deposit_wallet(
        holder_id,
        wallet_deposit_payload(amount_cents, expected_version),
        make_permit_holder_headers(holder_id),
    )
    return get_success_data(res)


def get_holder(holder_id: str):
    res = api_client.get_permit_holder(holder_id, COMMUNITY_ADMIN)
    return get_success_data(res)


def create_vehicle(holder_id: str, **overrides):
    """Create a vehicle owned by the holder. Returns the vehicle dict."""
    res = api_client.create_vehicle(
        create_vehicle_payload(holder_id, **overrides),
        make_permit_holder_headers(holder_id),
    )
    return get_success_data(res)


def create_full_equipment_lsv(holder_id: str, **overrides):
    """Create an LSV with all 8 equipment items and 6 seats."""
    res = api_client.create_vehicle(
        create_full_equipment_lsv_payload(holder_id, **overrides),
        make_permit_holder_headers(holder_id),
    )
    return get_success_data(res)


def create_draft_registration(vehicle_id: str, holder_id: str, **overrides):
    """Create a DRAFT registration. Returns the registration dict."""
    res = api_client.create_registration(
        create_registration_payload(vehicle_id, holder_id, **overrides),
        make_permit_holder_headers(holder_id),
    )
    return get_success_data(res)


def finalize_inspection_for_registration(registration_id: str, score: int = 90):
    """Schedule + finalize an inspection with uniform component scores.
    Returns the finalized inspection dict."""
    ins = get_success_data(api_client.create_inspection(
        create_inspection_payload(registration_id), INSPECTOR))
    res = api_client.finalize_inspection(
        ins["id"], finalize_inspection_payload(score=score), INSPECTOR)
    return get_success_data(res)


def create_insurance(holder_id: str, vehicle_id: str, **overrides):
    """Document an insurance policy. Returns the policy dict."""
    res = api_client.create_insurance_policy(
        create_insurance_policy_payload(holder_id, vehicle_id, **overrides),
        make_permit_holder_headers(holder_id),
    )
    return get_success_data(res)


def set_clock(to_iso8601: str):
    """Advance the logical clock (PlatformAdmin). Returns the response data."""
    res = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(res)


# ─── Tier 2: entity hierarchy / activation-ready scenarios ───────────────

def setup_activation_ready_registration(
        community_name="C-AR", fleet_program_enabled=True,
        deposit_cents=100000, vehicle_kind="lsv_full",
        insurance_overrides=None, inspection_score=90):
    """Community + ELIGIBLE funded holder + vehicle + DRAFT registration +
    PASSED inspection + ACTIVE insurance. Everything needed for activate.

    Returns dict with keys: community, holder, vehicle, registration.
    """
    community = create_community(
        name=community_name, fleet_program_enabled=fleet_program_enabled)
    holder = create_eligible_holder(community["id"])
    holder = deposit(holder["id"], deposit_cents, holder["version"])
    if vehicle_kind == "lsv_full":
        vehicle = create_full_equipment_lsv(holder["id"])
    else:
        vehicle = create_vehicle(holder["id"])
    registration = create_draft_registration(vehicle["id"], holder["id"])
    finalize_inspection_for_registration(registration["id"], score=inspection_score)
    create_insurance(holder["id"], vehicle["id"], **(insurance_overrides or {}))
    registration = get_success_data(
        api_client.get_registration(registration["id"], COMMUNITY_ADMIN))
    return {
        "community": community,
        "holder": holder,
        "vehicle": vehicle,
        "registration": registration,
    }


def setup_active_registration(**overrides):
    """Full path through DRAFT -> ACTIVE. Returns dict with keys:
    community, holder, vehicle, registration (the ACTIVE registration)."""
    ctx = setup_activation_ready_registration(**overrides)
    reg = get_success_data(api_client.activate_registration(
        ctx["registration"]["id"], make_permit_holder_headers(ctx["holder"]["id"])))
    ctx["registration"] = reg
    ctx["holder"] = get_holder(ctx["holder"]["id"])
    return ctx


# ─── Tier 3: route passes, charging, fleet ────────────────────────────────

def setup_route(community_id: str, **overrides):
    """Create a DESIGNATED route. Returns the route dict."""
    res = api_client.create_route(create_route_payload(community_id, **overrides),
                                  COMMUNITY_ADMIN)
    return get_success_data(res)


def setup_route_pass(route_id: str, registration_id: str, holder_id: str, **overrides):
    """Book an ACTIVE route pass. Returns the pass dict."""
    res = api_client.create_route_pass(
        create_route_pass_payload(route_id, registration_id, holder_id, **overrides),
        make_permit_holder_headers(holder_id),
    )
    return get_success_data(res)


def setup_station(community_id: str, **overrides):
    """Create an ONLINE charging station. Returns the station dict."""
    res = api_client.create_charging_station(
        create_charging_station_payload(community_id, **overrides), COMMUNITY_ADMIN)
    return get_success_data(res)


def setup_reservation(station_id: str, holder_id: str, **overrides):
    """Book a BOOKED charging reservation (fee debited at booking)."""
    res = api_client.create_charging_reservation(
        create_charging_reservation_payload(station_id, holder_id, **overrides),
        make_permit_holder_headers(holder_id),
    )
    return get_success_data(res)


def setup_fleet_vehicle(community_id: str, station_id: str, **overrides):
    """Create an AVAILABLE fleet vehicle. Returns the vehicle dict."""
    res = api_client.create_fleet_vehicle(
        create_fleet_vehicle_payload(community_id, station_id, **overrides),
        COMMUNITY_ADMIN)
    return get_success_data(res)


def setup_dispatch(vehicle_id: str, holder_id: str, **overrides):
    """Book a BOOKED fleet dispatch. Returns the dispatch dict."""
    res = api_client.create_fleet_dispatch(
        create_fleet_dispatch_payload(vehicle_id, holder_id, **overrides),
        make_permit_holder_headers(holder_id),
    )
    return get_success_data(res)


def setup_fleet_scenario(community_name="C-FLEET", slot_count=1, rate=10):
    """Community + ELIGIBLE holder + ONLINE station + AVAILABLE fleet vehicle.
    Returns dict with keys: community, holder, station, fleet_vehicle."""
    community = create_community(name=community_name)
    holder = create_eligible_holder(community["id"])
    station = setup_station(community["id"], slot_count=slot_count,
                            rate_cents_per_min=rate)
    fleet_vehicle = setup_fleet_vehicle(community["id"], station["id"])
    return {
        "community": community,
        "holder": holder,
        "station": station,
        "fleet_vehicle": fleet_vehicle,
    }


# ─── Tier 4: violations / standing accumulation ──────────────────────────

def file_and_uphold_violation(holder_id: str, points: int, **overrides):
    """File a violation and uphold it. Returns the UPHELD violation dict."""
    vio = get_success_data(api_client.create_violation(
        create_violation_payload(holder_id, points_assessed=points, **overrides),
        OFFICER))
    res = api_client.uphold_violation(vio["id"], OFFICER)
    return get_success_data(res)


def setup_barred_holder(community_name="C-BARRED", violations=3, points_each=4,
                        **violation_overrides):
    """Community + ELIGIBLE holder flipped into BARRED via upheld violations.
    Default: 3 x 4 points = 12 >= 12 (BARRED, inclusive threshold).
    Returns dict with keys: community, holder (the BARRED holder), violations.
    """
    community = create_community(name=community_name)
    holder = create_eligible_holder(community["id"])
    upheld = []
    for _ in range(violations):
        upheld.append(file_and_uphold_violation(
            holder["id"], points_each, **violation_overrides))
    return {
        "community": community,
        "holder": get_holder(holder["id"]),
        "violations": upheld,
    }
