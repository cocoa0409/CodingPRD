"""Composite setup helpers.

Each test runs against an empty database (the harness restarts the server before
every test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Fixtures use get_success_data() internally so a setup
failure surfaces as a clear "Setup failed" rather than a confusing assertion.

Identity threading: after creating an entity-backed entity, ownership-gated
calls use make_<role>_headers(<owner principal>) — never the shared TEST_USERS
fallback. Customer ownership binds to VehicleProfile.customer_user_id; Installer
to Installer.installer_user_id; FleetManager to FleetAccount.fleet_manager_user_id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_shop_manager_headers,
    make_compliance_officer_headers,
    make_customer_headers,
    make_installer_headers,
    make_fleet_manager_headers,
)

SM = make_shop_manager_headers()
CO = make_compliance_officer_headers()


# Common payload presets used widely across both design queues.
TINT_PACKAGE = {
    "name": "Tint Full Sedan", "service_type": "TINT", "base_rate_cents": 28000,
    "duration_minutes": 120, "cure_buffer_minutes": 0, "warranty_days": 365,
    "requires_proof": False,
}
PPF_PACKAGE = {
    "name": "PPF Partial", "service_type": "PPF", "base_rate_cents": 90000,
    "duration_minutes": 180, "cure_buffer_minutes": 30, "warranty_days": 365,
    "requires_proof": False,
}
WRAP_PACKAGE = {
    "name": "Wrap Full", "service_type": "WRAP", "base_rate_cents": 120000,
    "duration_minutes": 240, "cure_buffer_minutes": 60, "warranty_days": 730,
    "requires_proof": True,
}
TINT_MATERIAL = {"category": "TINT_FILM", "cure_hours": 24, "price_multiplier_bps": 14500}
PPF_MATERIAL = {"category": "PPF_FILM", "cure_hours": 48, "price_multiplier_bps": 10000}
WRAP_MATERIAL = {"category": "WRAP_VINYL", "cure_hours": 12, "price_multiplier_bps": 12000}


# --- Atomic creators -------------------------------------------------------

def create_regulation(state_code="CA", front_side_min_vlt_pct=35,
                      windshield_strip_max_inches=5, medical_exemption_allowed=True):
    resp = api_client.create_state_tint_regulation(
        {"state_code": state_code, "front_side_min_vlt_pct": front_side_min_vlt_pct,
         "windshield_strip_max_inches": windshield_strip_max_inches,
         "medical_exemption_allowed": medical_exemption_allowed},
        CO)
    return get_success_data(resp)


def create_shop(state_code="CA", name="Test Shop"):
    resp = api_client.create_shop_location({"name": name, "state_code": state_code}, SM)
    return get_success_data(resp)


def create_package(**overrides):
    payload = dict(TINT_PACKAGE)
    payload.update(overrides)
    return get_success_data(api_client.create_service_package(payload, SM))


def create_material(sku, **overrides):
    payload = dict(TINT_MATERIAL)
    payload.update(overrides)
    payload["sku"] = sku
    return get_success_data(api_client.create_film_material(payload, SM))


def create_vehicle(customer_user_id="cust-1", vin="VIN-1", size_class="SEDAN"):
    resp = api_client.create_vehicle_profile(
        {"customer_user_id": customer_user_id, "vin": vin, "size_class": size_class}, SM)
    return get_success_data(resp)


def create_fleet(fleet_manager_user_id="fm-1", discount_bps=0,
                 credit_limit_cents=5000000, company_name="FleetCo"):
    resp = api_client.create_fleet_account(
        {"company_name": company_name, "fleet_manager_user_id": fleet_manager_user_id,
         "discount_bps": discount_bps, "credit_limit_cents": credit_limit_cents}, SM)
    return get_success_data(resp)


def create_bay(shop_id, label="Bay 1"):
    return get_success_data(api_client.create_bay(
        {"shop_location_id": shop_id, "label": label}, SM))


def create_installer(shop_id, installer_user_id="inst-1", full_name="Ivy",
                     certified_service_types=("TINT",)):
    resp = api_client.create_installer(
        {"shop_location_id": shop_id, "installer_user_id": installer_user_id,
         "full_name": full_name,
         "certified_service_types": list(certified_service_types)}, SM)
    return get_success_data(resp)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, SM))


# --- Quote construction ----------------------------------------------------

def create_quote(vehicle_id, shop_id, fleet_account_id=None, rushed=None):
    payload = {"vehicle_profile_id": vehicle_id, "shop_location_id": shop_id}
    if fleet_account_id is not None:
        payload["fleet_account_id"] = fleet_account_id
    if rushed is not None:
        payload["rushed"] = rushed
    data = get_success_data(api_client.create_quote(payload, SM))
    return data, data["version"]


def add_line(quote_id, expected_version, package_id, material_id, coverage="FULL",
             window_position="REAR_SIDE", requested_vlt_pct=None, strip_depth_inches=None):
    payload = {
        "service_package_id": package_id, "film_material_id": material_id,
        "coverage": coverage, "window_position": window_position,
        "expected_quote_version": expected_version,
    }
    if requested_vlt_pct is not None:
        payload["requested_vlt_pct"] = requested_vlt_pct
    if strip_depth_inches is not None:
        payload["strip_depth_inches"] = strip_depth_inches
    data = get_success_data(api_client.add_quote_line(quote_id, payload, SM))
    # The add-line response is the QuoteLine resource, whose own `version` is the
    # line's version (1). Adding a line bumps the *quote's* version (PRD §3.3), and
    # the next OCC-guarded write needs that quote version. Re-read the quote and
    # surface its current version under "version" so callers can thread it.
    quote = get_success_data(api_client.get_quote(quote_id, SM))
    data = dict(data)
    data["version"] = quote["version"]
    return data


def price_quote(quote_id, expected_version):
    data = get_success_data(api_client.price_quote(
        quote_id, {"expected_quote_version": expected_version}, SM))
    return data, data["version"]


def accept_quote(quote_id, expected_version, customer_user_id):
    data = get_success_data(api_client.accept_quote(
        quote_id, {"expected_quote_version": expected_version},
        make_customer_headers(customer_user_id)))
    return data, data["version"]


def build_accepted_quote(shop_id, vehicle_id, customer_user_id, package_id, material_id,
                         fleet_account_id=None, coverage="FULL",
                         window_position="REAR_SIDE", requested_vlt_pct=50, rushed=None):
    """Create DRAFT quote + one INCLUDED line, price, accept. Returns the ACCEPTED
    quote dict (carrying its post-accept version)."""
    quote, v0 = create_quote(vehicle_id, shop_id, fleet_account_id=fleet_account_id, rushed=rushed)
    add_line(quote["id"], v0, package_id, material_id, coverage=coverage,
             window_position=window_position, requested_vlt_pct=requested_vlt_pct)
    # re-read latest version after the line add
    line_state = get_success_data(api_client.get_quote(quote["id"], SM))
    _, v2 = price_quote(quote["id"], line_state["version"])
    accepted, _ = accept_quote(quote["id"], v2, customer_user_id)
    return accepted


# --- Full scenario builders ------------------------------------------------

def setup_scheduled_tint_workorder(state_code="CA", customer_user_id="cust-1",
                                    installer_user_id="inst-1", vin="VIN-WO",
                                    scheduled_start="2026-06-02T09:00:00Z",
                                    front_side_min_vlt_pct=35):
    """Empty DB -> a SCHEDULED TINT WorkOrder (no proof required).
    Returns dict with shop, package, material, vehicle, bay, installer, quote, work_order
    plus the principals so ownership-gated calls can thread identity."""
    create_regulation(state_code=state_code, front_side_min_vlt_pct=front_side_min_vlt_pct)
    shop = create_shop(state_code=state_code)
    pkg = create_package(**TINT_PACKAGE)
    mat = create_material("CER-TINT", **TINT_MATERIAL)
    veh = create_vehicle(customer_user_id=customer_user_id, vin=vin)
    bay = create_bay(shop["id"])
    inst = create_installer(shop["id"], installer_user_id=installer_user_id,
                            certified_service_types=("TINT",))
    accepted = build_accepted_quote(shop["id"], veh["id"], customer_user_id,
                                     pkg["id"], mat["id"])
    wo = get_success_data(api_client.create_work_order(
        {"quote_id": accepted["id"], "bay_id": bay["id"], "installer_id": inst["id"],
         "scheduled_start": scheduled_start,
         "expected_quote_version": accepted["version"]}, SM))
    return {
        "shop": shop, "package": pkg, "material": mat, "vehicle": veh,
        "bay": bay, "installer": inst, "quote_id": accepted["id"], "work_order": wo,
        "customer_user_id": customer_user_id, "installer_user_id": installer_user_id,
    }


def setup_scheduled_wrap_workorder_with_proof(state_code="UT",
                                              customer_user_id="cust-w",
                                              installer_user_id="inst-w",
                                              scheduled_start="2026-06-02T09:00:00Z"):
    """Empty DB -> a SCHEDULED WRAP WorkOrder (requires_proof) with one submitted
    proof (PROOF_SUBMITTED, revision_round 1). Returns scenario dict incl. work_order
    and proof."""
    create_regulation(state_code=state_code, front_side_min_vlt_pct=35,
                      windshield_strip_max_inches=6, medical_exemption_allowed=False)
    shop = create_shop(state_code=state_code)
    pkg = create_package(**WRAP_PACKAGE)
    mat = create_material("VINYL-WP", **WRAP_MATERIAL)
    veh = create_vehicle(customer_user_id=customer_user_id, vin="VIN-WP")
    bay = create_bay(shop["id"])
    inst = create_installer(shop["id"], installer_user_id=installer_user_id,
                            certified_service_types=("WRAP",))
    accepted = build_accepted_quote(shop["id"], veh["id"], customer_user_id,
                                     pkg["id"], mat["id"], coverage="FULL",
                                     window_position="BODY_PANEL", requested_vlt_pct=None)
    wo = get_success_data(api_client.create_work_order(
        {"quote_id": accepted["id"], "bay_id": bay["id"], "installer_id": inst["id"],
         "scheduled_start": scheduled_start,
         "expected_quote_version": accepted["version"]}, SM))
    proof = get_success_data(api_client.submit_proof(
        wo["id"], {"design_ref": "draft-v1"},
        make_installer_headers(installer_user_id)))
    return {
        "shop": shop, "package": pkg, "material": mat, "vehicle": veh, "bay": bay,
        "installer": inst, "quote_id": accepted["id"], "work_order": wo, "proof": proof,
        "customer_user_id": customer_user_id, "installer_user_id": installer_user_id,
    }


def drive_to_completed(scenario, start_clock="2026-06-02T09:00:00Z",
                       complete_clock=None):
    """Advance a SCHEDULED (no-proof) work order through start + complete-install
    to CURING. Returns the work order after complete-install."""
    wo = scenario["work_order"]
    iuid = scenario["installer_user_id"]
    set_clock(start_clock)
    get_success_data(api_client.start_work_order(wo["id"], make_installer_headers(iuid)))
    if complete_clock:
        set_clock(complete_clock)
    completed = get_success_data(
        api_client.complete_install_work_order(wo["id"], make_installer_headers(iuid)))
    return completed


def drive_to_released(scenario, start_clock="2026-06-02T09:00:00Z",
                      release_clock="2026-06-04T00:00:00Z"):
    """SCHEDULED (no-proof) -> COMPLETED (released). Returns released work order."""
    drive_to_completed(scenario, start_clock=start_clock)
    set_clock(release_clock)
    released = get_success_data(
        api_client.release_work_order(scenario["work_order"]["id"], SM))
    return released
