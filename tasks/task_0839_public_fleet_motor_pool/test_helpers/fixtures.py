"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors, not confusing assertion failures. Every helper builds
its preconditions from scratch because the server (and its database) is restarted
before each test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_vehicle_payload,
    create_department_payload,
    create_vehicle_class_policy_payload,
    create_reservation_payload,
    create_shop_bay_payload,
    create_work_order_payload,
    create_fuel_log_payload,
    create_accident_claim_payload,
    create_disposal_payload,
)
from .test_users import TEST_USERS

_ADMIN = TEST_USERS["fleet_admin_headers"]
_CLERK = TEST_USERS["motor_pool_clerk_headers"]
_TECH = TEST_USERS["shop_tech_headers"]
_FIN = TEST_USERS["finance_officer_headers"]


# ─── Primitive builders ───────────────────────────────────────────────

def set_clock(iso: str):
    """Move the server logical clock to `iso` (FleetAdmin)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, _ADMIN))


def create_policy(**overrides) -> dict:
    """Create a vehicle-class rate policy (SEDAN by default)."""
    return get_success_data(
        api_client.create_vehicle_class_policy(
            create_vehicle_class_policy_payload(**overrides), _ADMIN))


def create_department(budget: int = 10000000, **overrides) -> dict:
    payload = create_department_payload(monthly_budget_cents=budget, **overrides)
    return get_success_data(api_client.create_department(payload, _ADMIN))


def create_pool_vehicle(**overrides) -> dict:
    """Create a POOL vehicle (defaults IN_SERVICE / ACTIVE)."""
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(**overrides), _ADMIN))


def get_vehicle(vehicle_id: str) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, _ADMIN))


def get_vehicle_version(vehicle_id: str) -> int:
    return get_vehicle(vehicle_id)["version"]


def get_department(department_id: str) -> dict:
    return get_success_data(api_client.get_department(department_id, _FIN))


def get_department_version(department_id: str) -> int:
    return get_department(department_id)["version"]


def create_shop_bay(**overrides) -> dict:
    return get_success_data(api_client.create_shop_bay(create_shop_bay_payload(**overrides), _ADMIN))


# ─── Tier 1/2: State progression & threshold targeting ────────────────

def create_flagged_vehicle(clock: str = "2026-06-01T00:00:00Z",
                           in_service_date: str = "2010-01-01T00:00:00Z",
                           odometer: int = 150000,
                           acquisition_cost_cents: int = 2000000,
                           **veh_overrides) -> dict:
    """Create a policy + an old, high-mileage vehicle and drive it to
    FLAGGED_FOR_REPLACEMENT via a fuel-log (odometer) + replacement-evaluation.

    Defaults (age >> replacement_age_years, odometer == replacement_mileage) yield
    replacement_score 70.00, which flags the vehicle. Returns the re-fetched vehicle.
    """
    create_policy()
    set_clock(clock)
    vehicle = create_pool_vehicle(
        in_service_date=in_service_date,
        acquisition_cost_cents=acquisition_cost_cents,
        **veh_overrides)
    get_success_data(api_client.create_fuel_log(
        vehicle["id"],
        create_fuel_log_payload(reading_at="2026-06-01T06:00:00Z", gallons=1,
                                fuel_cost_cents=0, odometer_miles=odometer),
        _TECH))
    get_success_data(api_client.evaluate_replacement(vehicle["id"], _ADMIN))
    return get_vehicle(vehicle["id"])


def list_vehicle_for_disposal(vehicle_id: str, reserve_price_cents: int = 100000,
                              **overrides) -> dict:
    """List a FLAGGED_FOR_REPLACEMENT vehicle for auction (OCC-guarded). Returns the
    DisposalRecord in LISTED."""
    version = get_vehicle_version(vehicle_id)
    payload = create_disposal_payload(version, reserve_price_cents=reserve_price_cents, **overrides)
    return get_success_data(api_client.create_disposal(vehicle_id, payload, _ADMIN))


def create_bidding_disposal(vehicle_id: str, reserve_price_cents: int = 100000, **overrides) -> dict:
    """List a flagged vehicle then open bidding. Returns the DisposalRecord in BIDDING."""
    disposal = list_vehicle_for_disposal(vehicle_id, reserve_price_cents, **overrides)
    return get_success_data(api_client.open_bidding(disposal["id"], _ADMIN))


# ─── Reservation lifecycle shortcuts ──────────────────────────────────

def create_confirmed_reservation(department_id: str, **res_overrides) -> dict:
    """Request + confirm a reservation (a confirmable POOL vehicle must already exist).
    Returns the CONFIRMED reservation."""
    res = get_success_data(api_client.create_reservation(
        create_reservation_payload(department_id, **res_overrides), _CLERK))
    return get_success_data(api_client.confirm_reservation(res["id"], _CLERK))


def drive_reservation_to_returned(department_id: str, checkout_odometer: int = 0,
                                  return_odometer: int = 500, **res_overrides) -> dict:
    """Request → confirm → checkout → return. A confirmable POOL vehicle must exist.
    Returns the RETURNED reservation (miles_driven = return - checkout)."""
    confirmed = create_confirmed_reservation(department_id, **res_overrides)
    get_success_data(api_client.checkout_reservation(
        confirmed["id"], {"checkout_odometer": checkout_odometer}, _CLERK))
    return get_success_data(api_client.return_reservation(
        confirmed["id"], {"return_odometer": return_odometer}, _CLERK))


# ─── Work-order lifecycle shortcuts ───────────────────────────────────

def create_scheduled_work_order(vehicle_id: str, bay_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(vehicle_id, bay_id, **overrides), _TECH))


def create_started_work_order(vehicle_id: str, bay_id: str, **overrides) -> dict:
    """Schedule + start a work order (vehicle -> IN_SHOP). Returns the IN_PROGRESS order."""
    wo = create_scheduled_work_order(vehicle_id, bay_id, **overrides)
    return get_success_data(api_client.start_work_order(wo["id"], _TECH))


# ─── Accident / subrogation shortcuts ─────────────────────────────────

def create_subrogation_pending_claim(vehicle_id: str, estimated_damage_cents: int = 1000000,
                                      third_party_liable_pct: float = 0.5,
                                      deductible_cents: int = 0, **overrides) -> dict:
    """Report (not at fault) → investigate → subrogate. Returns the SUBROGATION_PENDING claim."""
    claim = get_success_data(api_client.create_accident_claim(
        create_accident_claim_payload(
            vehicle_id, at_fault=False,
            estimated_damage_cents=estimated_damage_cents,
            third_party_liable_pct=third_party_liable_pct,
            deductible_cents=deductible_cents, **overrides),
        _FIN))
    get_success_data(api_client.investigate_claim(claim["id"], _FIN))
    return get_success_data(api_client.subrogate_claim(claim["id"], _FIN))


# ─── Chargeback shortcuts ─────────────────────────────────────────────

def create_issued_invoice(department_id: str, period_start: str = "2026-06-01T00:00:00Z",
                          period_end: str = "2026-07-01T00:00:00Z", basis: str = "FINAL") -> dict:
    """Create a DRAFT invoice then issue it (debits billed_ytd). Returns the ISSUED invoice."""
    version = get_department_version(department_id)
    draft = get_success_data(api_client.create_invoice(
        department_id,
        {"period_start": period_start, "period_end": period_end, "basis": basis,
         "expected_department_version": version},
        _FIN))
    return get_success_data(api_client.issue_invoice(draft["id"], _FIN))
