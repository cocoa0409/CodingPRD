"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints only, and
uses the lenient ``get_success_data`` so a broken precondition surfaces as a setup failure.

Identity threading: an ``AirlineRep``'s ``X-User-ID`` is the id of the acting AirlineAccount,
so every ownership-gated call goes through ``make_airline_rep_headers(account["id"])``.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_airline_rep_headers, make_inspector_headers, make_billing_headers,
)
from . import factories as F

# Canonical logical-clock instants used across the suite.
CLOCK = "2026-08-10T06:00:00Z"
DEPARTURE = "2026-08-10T08:00:00Z"
WINDOW_START = "2026-08-10T06:00:00Z"
WINDOW_END = "2026-08-10T07:30:00Z"

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]
AGENT = TEST_USERS["agent_headers"]
ENVIRO = TEST_USERS["environmental_headers"]
BILLING = TEST_USERS["billing_headers"]

INSPECTOR_A = make_inspector_headers("qi-alice")
INSPECTOR_B = make_inspector_headers("qi-bob")
INSPECTOR_C = make_inspector_headers("qi-carol")

ALL_PASS_METRICS = {
    "water_reaction_rating": 1,
    "particulate_mg_per_l": 0.5,
    "conductivity_ps_per_m": 120.0,
    "observed_density_kg_per_m3": 795.0,
    "flash_point_c": 42.0,
}


# --- primitives -------------------------------------------------------------


def set_clock(to_iso8601=CLOCK):
    """Drive the logical clock. Admin-only capability."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_farm(**overrides):
    payload = F.create_fuel_farm_payload(**overrides)
    return get_success_data(api_client.create_fuel_farm(payload, ADMIN))


def issue_permit(farm_id, **overrides):
    payload = F.create_environmental_permit_payload(**overrides)
    return get_success_data(api_client.create_environmental_permit(farm_id, payload, ADMIN))


def register_tank(farm_id, **overrides):
    payload = F.create_storage_tank_payload(**overrides)
    return get_success_data(api_client.create_storage_tank(farm_id, payload, ADMIN))


def register_truck(farm_id, **overrides):
    payload = F.create_fueling_asset_payload(**overrides)
    return get_success_data(api_client.create_fueling_asset(farm_id, payload, ADMIN))


def register_cart(farm_id, **overrides):
    payload = F.create_hydrant_cart_payload(**overrides)
    return get_success_data(api_client.create_fueling_asset(farm_id, payload, ADMIN))


def register_pit(farm_id, source_storage_tank_id, **overrides):
    payload = F.create_hydrant_pit_payload(source_storage_tank_id, **overrides)
    return get_success_data(api_client.create_hydrant_pit(farm_id, payload, ADMIN))


def open_account(**overrides):
    payload = F.create_airline_account_payload(**overrides)
    return get_success_data(api_client.create_airline_account(payload, ADMIN))


def register_flight(account_id, **overrides):
    # The canonical departure must be applied *before* the factory fills its own
    # default, otherwise the factory value wins and the flight departs before the
    # canonical clock (making every derived authorization instantly EXPIRED).
    overrides.setdefault("scheduled_departure_utc", DEPARTURE)
    payload = F.create_flight_payload(account_id, **overrides)
    return get_success_data(
        api_client.create_flight(payload, make_airline_rep_headers(account_id)))


def issue_authorization(account_id, flight_id, **overrides):
    payload = F.create_fuel_authorization_payload(account_id, flight_id, **overrides)
    return get_success_data(
        api_client.create_fuel_authorization(payload, make_airline_rep_headers(account_id)))


def draw_tank_sample(tank_id, inspector=INSPECTOR_A):
    return get_success_data(api_client.create_tank_sample(
        tank_id, inspector, {"sample_purpose": "PERIODIC_TANK_QA"}))


def post_results(sample_id, inspector=INSPECTOR_A, **metric_overrides):
    payload = dict(ALL_PASS_METRICS)
    payload.update(metric_overrides)
    return get_success_data(api_client.post_test_results(sample_id, payload, inspector))


def release_tank_quality(tank_id, inspector=INSPECTOR_B):
    return get_success_data(api_client.release_tank_quality(tank_id, inspector))


def make_released_tank(farm_id, drawer=INSPECTOR_A, releaser=INSPECTOR_B,
                       observed_density=None, **tank_overrides):
    """Register a tank and walk its quality dimension ON_TEST -> RELEASED.

    The drawing inspector and the releasing inspector are deliberately different
    identities, because an inspector may not release a tank on a sample they drew.
    """
    tank = register_tank(farm_id, **tank_overrides)
    sample = draw_tank_sample(tank["id"], drawer)
    density = observed_density if observed_density is not None else tank["density_kg_per_m3"]
    post_results(sample["id"], drawer, observed_density_kg_per_m3=density)
    tank = release_tank_quality(tank["id"], releaser)
    return tank


def record_receipt(tank_id, **overrides):
    payload = F.create_fuel_receipt_payload(tank_id, **overrides)
    return get_success_data(api_client.create_fuel_receipt(payload, OPERATOR))


def draw_receipt_sample(receipt_id, inspector=INSPECTOR_A):
    return get_success_data(api_client.create_receipt_sample(receipt_id, inspector))


def sign_verdict(receipt_id, decision, inspector=INSPECTOR_B):
    return get_success_data(
        api_client.sign_receipt_verdict(receipt_id, {"decision": decision}, inspector))


def make_tested_receipt(tank_id, drawer=INSPECTOR_A, metrics=None, **receipt_overrides):
    """Record a receipt and drive it RECORDED -> SAMPLED -> UNDER_TEST."""
    receipt = record_receipt(tank_id, **receipt_overrides)
    sample = draw_receipt_sample(receipt["id"], drawer)
    metrics = metrics or {}
    metrics.setdefault("observed_density_kg_per_m3",
                       receipt["certificate_density_kg_per_m3"])
    post_results(sample["id"], drawer, **metrics)
    # Re-read before handing the row back: the creation response predates the sample draw, and
    # PRD §3.2 has that draw "stamp the receipt's `sampled_by_user_id` with the acting
    # identifier" and move the receipt on, so only a fresh read shows the state this helper
    # promises to have reached.
    return read_receipt(receipt["id"]), sample


def make_released_receipt(tank_id, drawer=INSPECTOR_A, signer=INSPECTOR_B,
                          metrics=None, **receipt_overrides):
    """Record a receipt and drive it all the way to RELEASED, so its net volume is in the ledger."""
    receipt, sample = make_tested_receipt(tank_id, drawer, metrics, **receipt_overrides)
    receipt = sign_verdict(receipt["id"], "RELEASE", signer)
    return receipt


def make_quarantined_receipt(tank_id, drawer=INSPECTOR_A, signer=INSPECTOR_B,
                             metrics=None, **receipt_overrides):
    """Record a receipt, test it, and sign a QUARANTINE verdict."""
    receipt, sample = make_tested_receipt(tank_id, drawer, metrics, **receipt_overrides)
    receipt = sign_verdict(receipt["id"], "QUARANTINE", signer)
    return receipt


# --- order-level primitives -------------------------------------------------


def create_order(flight_id, auth_id, tank_id, code, actor=AGENT, **overrides):
    # Same ordering trap as register_flight: the canonical fuelling window has to be
    # seeded into the overrides before the factory supplies its own default, or the
    # order's window sits outside the canonical logical clock.
    overrides.setdefault("window_start_utc", WINDOW_START)
    overrides.setdefault("window_end_utc", WINDOW_END)
    payload = F.create_fueling_order_payload(flight_id, auth_id, tank_id, code, **overrides)
    return get_success_data(api_client.create_fueling_order(payload, actor))


def authorize_order(order_id):
    return get_success_data(api_client.authorize_order(order_id, AGENT))


def assign_order(order_id, asset_id, pit_id=None):
    payload = {"fueling_asset_id": asset_id}
    if pit_id is not None:
        payload["hydrant_pit_id"] = pit_id
    return get_success_data(api_client.assign_order(order_id, payload, AGENT))


def start_order(order_id):
    return get_success_data(api_client.start_order(order_id, AGENT))


def current_order_version(order_id):
    return get_success_data(api_client.get_fueling_order(order_id, AGENT))["version"]


def post_uplift(order_id, expected_version=None, **overrides):
    """Post an uplift ticket, reading the order's live version when none is supplied."""
    if expected_version is None:
        expected_version = current_order_version(order_id)
    payload = F.create_uplift_record_payload(expected_version, **overrides)
    return get_success_data(api_client.create_uplift_record(order_id, payload, AGENT))


def complete_order(order_id):
    return get_success_data(api_client.complete_order(order_id, AGENT))


def abort_order(order_id, abort_reason="EQUIPMENT_FAILURE"):
    return get_success_data(
        api_client.abort_order(order_id, {"abort_reason": abort_reason}, AGENT))


def report_spill(farm_id, **overrides):
    payload = F.create_spill_incident_payload(farm_id, **overrides)
    return get_success_data(api_client.create_spill_incident(payload, ENVIRO))


def escalate_spill(spill_id, regulator_reference="REG-2026-0001"):
    return get_success_data(api_client.escalate_spill(
        spill_id, {"regulator_reference": regulator_reference}, ENVIRO))


def contain_spill(spill_id, contained_volume_liters):
    return get_success_data(api_client.contain_spill(
        spill_id, {"contained_volume_liters": contained_volume_liters}, ENVIRO))


def read_farm(farm_id, headers=ADMIN):
    return get_success_data(api_client.get_fuel_farm(farm_id, headers))


def read_tank(tank_id, headers=ADMIN):
    return get_success_data(api_client.get_storage_tank(tank_id, headers))


def read_asset(asset_id, headers=ADMIN):
    return get_success_data(api_client.get_fueling_asset(asset_id, headers))


def read_account(account_id, headers=ADMIN):
    return get_success_data(api_client.get_airline_account(account_id, headers))


def read_order(order_id, headers=ADMIN):
    return get_success_data(api_client.get_fueling_order(order_id, headers))


def read_authorization(auth_id, headers=ADMIN):
    return get_success_data(api_client.get_fuel_authorization(auth_id, headers))


def read_uplift(ticket_id, headers=ADMIN):
    return get_success_data(api_client.get_uplift_record(ticket_id, headers))


def read_invoice(invoice_id, headers=BILLING):
    return get_success_data(api_client.get_invoice(invoice_id, headers))


def read_receipt(receipt_id, headers=OPERATOR):
    return get_success_data(api_client.get_fuel_receipt(receipt_id, headers))


def read_sample(sample_id, headers=INSPECTOR_A):
    return get_success_data(api_client.get_quality_sample(sample_id, headers))


def read_pit(pit_id, headers=ADMIN):
    return get_success_data(api_client.get_hydrant_pit(pit_id, headers))


def read_spill(spill_id, headers=ENVIRO):
    return get_success_data(api_client.get_spill_incident(spill_id, headers))


# --- Tier 2: farm environments ---------------------------------------------


def setup_fuel_farm(clock=CLOCK, hydrant_system_available=True,
                    unpumpable_bottom_liters=500.0, permit_overrides=None,
                    farm_overrides=None):
    """Logical clock set, farm registered, one ACTIVE permit covering the clock.

    Returns {"farm": ..., "permit": ...}. A farm without an active permit is FROZEN by
    definition, so every scenario that needs to move fuel starts here.
    """
    set_clock(clock)
    farm = create_farm(hydrant_system_available=hydrant_system_available,
                       unpumpable_bottom_liters=unpumpable_bottom_liters,
                       **(farm_overrides or {}))
    permit = issue_permit(farm["id"], **(permit_overrides or {}))
    return {"farm": farm, "permit": permit}


def setup_farm_with_released_tank(clock=CLOCK, opening_volume_liters=1_000_000.0,
                                  density_kg_per_m3=795.0, tank_overrides=None,
                                  permit_overrides=None, hydrant_system_available=True,
                                  unpumpable_bottom_liters=500.0):
    """Farm + ACTIVE permit + one tank released on the quality dimension."""
    env = setup_fuel_farm(clock=clock, hydrant_system_available=hydrant_system_available,
                          unpumpable_bottom_liters=unpumpable_bottom_liters,
                          permit_overrides=permit_overrides)
    overrides = {
        "capacity_liters": 5_000_000.0,
        "safe_fill_liters": 4_000_000.0,
        "density_kg_per_m3": density_kg_per_m3,
        "opening_volume_liters": opening_volume_liters,
    }
    overrides.update(tank_overrides or {})
    env["tank"] = make_released_tank(env["farm"]["id"], **overrides)
    return env


def setup_airline(account_overrides=None, flight_overrides=None,
                  max_authorized_liters=20_000.0):
    """Airline account + one SCHEDULED flight + one ISSUED authorization for that flight."""
    account = open_account(**(account_overrides or {}))
    flight = register_flight(account["id"], **(flight_overrides or {}))
    auth = issue_authorization(account["id"], flight["id"],
                               max_authorized_liters=max_authorized_liters)
    return {"account": account, "flight": flight, "auth": auth}


# --- Tier 3: order lifecycle shortcuts -------------------------------------


def setup_truck_order(target_state="REQUESTED", requested_uplift_liters=20_000.0,
                      max_authorized_liters=20_000.0, opening_volume_liters=1_000_000.0,
                      account_overrides=None, flight_overrides=None, order_overrides=None,
                      asset_overrides=None, tank_overrides=None, permit_overrides=None,
                      clock=CLOCK, density_kg_per_m3=795.0):
    """Full TRUCK-delivery scenario walked to ``target_state``.

    target_state is one of REQUESTED, AUTHORIZED, ASSIGNED, FUELING.
    Returns a dict with farm, permit, tank, truck, account, flight, auth and order.
    """
    env = setup_farm_with_released_tank(
        clock=clock, opening_volume_liters=opening_volume_liters,
        density_kg_per_m3=density_kg_per_m3, tank_overrides=tank_overrides,
        permit_overrides=permit_overrides)
    truck_kwargs = {"tank_capacity_liters": 40_000.0, "turnaround_buffer_minutes": 15,
                    "differential_pressure_kpa": 10.0}
    truck_kwargs.update(asset_overrides or {})
    env["truck"] = register_truck(env["farm"]["id"], **truck_kwargs)
    env.update(setup_airline(account_overrides, flight_overrides, max_authorized_liters))
    env["order"] = create_order(
        env["flight"]["id"], env["auth"]["id"], env["tank"]["id"],
        env["auth"]["authorization_code"], delivery_mode="TRUCK",
        requested_uplift_liters=requested_uplift_liters, **(order_overrides or {}))
    order_id = env["order"]["id"]
    if target_state in ("AUTHORIZED", "ASSIGNED", "FUELING"):
        env["order"] = authorize_order(order_id)
    if target_state in ("ASSIGNED", "FUELING"):
        env["order"] = assign_order(order_id, env["truck"]["id"])
    if target_state == "FUELING":
        env["order"] = start_order(order_id)
    return env


def setup_hydrant_order(target_state="REQUESTED", requested_uplift_liters=20_000.0,
                        max_authorized_liters=20_000.0, stand_code="A12",
                        opening_volume_liters=1_000_000.0, order_overrides=None,
                        account_overrides=None, clock=CLOCK):
    """Full HYDRANT-delivery scenario (cart + pit on the flight's stand) walked to a state."""
    env = setup_farm_with_released_tank(clock=clock,
                                        opening_volume_liters=opening_volume_liters)
    env["cart"] = register_cart(env["farm"]["id"], turnaround_buffer_minutes=15,
                                differential_pressure_kpa=10.0)
    env["pit"] = register_pit(env["farm"]["id"], env["tank"]["id"], stand_code=stand_code)
    env.update(setup_airline(account_overrides, {"stand_code": stand_code},
                             max_authorized_liters))
    env["order"] = create_order(
        env["flight"]["id"], env["auth"]["id"], env["tank"]["id"],
        env["auth"]["authorization_code"], delivery_mode="HYDRANT",
        requested_uplift_liters=requested_uplift_liters, **(order_overrides or {}))
    order_id = env["order"]["id"]
    if target_state in ("AUTHORIZED", "ASSIGNED", "FUELING"):
        env["order"] = authorize_order(order_id)
    if target_state in ("ASSIGNED", "FUELING"):
        env["order"] = assign_order(order_id, env["cart"]["id"], env["pit"]["id"])
    if target_state == "FUELING":
        env["order"] = start_order(order_id)
    return env


# --- Tier 4: uplift / billing accumulation ---------------------------------


def setup_fueling_order_with_uplift(meter_end_liters=20_000.0, temperature_c=15.0,
                                    requested_uplift_liters=20_000.0,
                                    max_authorized_liters=20_000.0,
                                    account_overrides=None, ticket_number=None,
                                    **kwargs):
    """A FUELING TRUCK order carrying exactly one POSTED uplift ticket."""
    env = setup_truck_order(target_state="FUELING",
                            requested_uplift_liters=requested_uplift_liters,
                            max_authorized_liters=max_authorized_liters,
                            account_overrides=account_overrides, **kwargs)
    extra = {"meter_start_liters": 0.0, "meter_end_liters": meter_end_liters,
             "temperature_c": temperature_c}
    if ticket_number is not None:
        extra["ticket_number"] = ticket_number
    env["uplift"] = post_uplift(env["order"]["id"], env["order"]["version"], **extra)
    return env


def setup_completed_order(meter_end_liters=20_000.0, temperature_c=15.0,
                          requested_uplift_liters=20_000.0,
                          max_authorized_liters=20_000.0, account_overrides=None,
                          **kwargs):
    """A COMPLETED TRUCK order with one POSTED uplift ticket; authorization is REDEEMED."""
    env = setup_fueling_order_with_uplift(
        meter_end_liters=meter_end_liters, temperature_c=temperature_c,
        requested_uplift_liters=requested_uplift_liters,
        max_authorized_liters=max_authorized_liters,
        account_overrides=account_overrides, **kwargs)
    env["order"] = complete_order(env["order"]["id"])
    return env


def create_draft_invoice(account_id, period_start_utc="2026-08-01T00:00:00Z",
                         period_end_utc="2026-09-01T00:00:00Z",
                         expected_version=None, clerk=BILLING, **overrides):
    """Sweep the account's unbilled POSTED tickets into a DRAFT invoice."""
    if expected_version is None:
        expected_version = read_account(account_id)["version"]
    payload = F.create_invoice_payload(account_id, expected_version,
                                       period_start_utc=period_start_utc,
                                       period_end_utc=period_end_utc, **overrides)
    return get_success_data(api_client.create_invoice(payload, clerk))


def setup_issued_invoice(meter_end_liters=20_000.0, account_overrides=None,
                         clerk=BILLING, **kwargs):
    """A COMPLETED order whose POSTED ticket has been swept and the invoice ISSUED."""
    env = setup_completed_order(meter_end_liters=meter_end_liters,
                                account_overrides=account_overrides, **kwargs)
    env["invoice"] = create_draft_invoice(env["account"]["id"], clerk=clerk)
    env["invoice"] = get_success_data(
        api_client.issue_invoice(env["invoice"]["id"], clerk))
    return env


def setup_asset_at_element_life(farm_id, differential_pressure_kpa):
    """Register a truck whose pressure leg alone drives its element life."""
    return register_truck(farm_id, differential_pressure_kpa=differential_pressure_kpa,
                          tank_capacity_liters=40_000.0)


def isolate_tank(tank_id, start_utc, end_utc, headers=OPERATOR):
    payload = {"to_status": "ISOLATED", "isolation_window_start_utc": start_utc,
               "isolation_window_end_utc": end_utc}
    return get_success_data(api_client.change_tank_service_status(tank_id, payload, headers))


def gauge_tank(tank_id, measured_volume_liters, water_bottom_mm=1.0, temperature_c=15.0):
    payload = {"measured_volume_liters": measured_volume_liters,
               "temperature_c": temperature_c, "water_bottom_mm": water_bottom_mm}
    return get_success_data(
        api_client.create_gauge_measurement(tank_id, payload, OPERATOR))


def open_reconciliation_run(farm_id, period_start_utc="2026-08-10T00:00:00Z",
                            period_end_utc="2026-08-11T00:00:00Z"):
    payload = F.create_reconciliation_run_payload(period_start_utc=period_start_utc,
                                                  period_end_utc=period_end_utc)
    return get_success_data(
        api_client.create_reconciliation_run(farm_id, payload, OPERATOR))


def measure_reconciliation_run(run_id, tank_measurements):
    return get_success_data(api_client.measure_reconciliation_run(
        run_id, {"tank_measurements": tank_measurements}, OPERATOR))


# --- Tier 5: multi-order billing scenarios ---------------------------------


def setup_sequential_uplifts_for_account(uplift_liters=(30_000.0, 30_000.0, 40_000.0),
                                         base_price_cents_per_liter=62.00,
                                         tax_exempt=False, credit_limit_cents=100_000_000,
                                         opening_volume_liters=1_000_000.0,
                                         permit_overrides=None):
    """One account, one truck, N COMPLETED orders each carrying one POSTED uplift ticket.

    The orders run in non-overlapping windows that respect the truck's turnaround buffer, and
    the clock is advanced between them so each ticket's created_at is ordered. Returns a dict
    with farm, permit, tank, truck, account, flights, auths, orders and uplifts (lists).
    """
    env = setup_farm_with_released_tank(opening_volume_liters=opening_volume_liters,
                                       permit_overrides=permit_overrides)
    env["truck"] = register_truck(env["farm"]["id"], tank_capacity_liters=40_000.0,
                                  turnaround_buffer_minutes=15,
                                  differential_pressure_kpa=10.0)
    env["account"] = open_account(base_price_cents_per_liter=base_price_cents_per_liter,
                                  tax_exempt=tax_exempt,
                                  credit_limit_cents=credit_limit_cents)
    env["flights"], env["auths"], env["orders"], env["uplifts"] = [], [], [], []

    windows = [("2026-08-10T06:00:00Z", "2026-08-10T06:30:00Z", "2026-08-10T09:00:00Z"),
               ("2026-08-10T07:00:00Z", "2026-08-10T07:30:00Z", "2026-08-10T10:00:00Z"),
               ("2026-08-10T08:00:00Z", "2026-08-10T08:30:00Z", "2026-08-10T11:00:00Z"),
               ("2026-08-10T09:00:00Z", "2026-08-10T09:30:00Z", "2026-08-10T12:00:00Z")]
    meter = 0.0
    for index, liters in enumerate(uplift_liters):
        window_start, window_end, departure = windows[index]
        set_clock(window_start)
        flight = register_flight(env["account"]["id"], scheduled_departure_utc=departure,
                                 stand_code=f"A{20 + index}")
        auth = issue_authorization(env["account"]["id"], flight["id"],
                                   max_authorized_liters=liters)
        order = create_order(flight["id"], auth["id"], env["tank"]["id"],
                             auth["authorization_code"], delivery_mode="TRUCK",
                             requested_uplift_liters=liters,
                             window_start_utc=window_start, window_end_utc=window_end)
        authorize_order(order["id"])
        assign_order(order["id"], env["truck"]["id"])
        order = start_order(order["id"])
        uplift = post_uplift(order["id"], order["version"], meter_start_liters=meter,
                             meter_end_liters=meter + liters, temperature_c=15.0)
        meter += liters
        order = complete_order(order["id"])
        env["flights"].append(flight)
        env["auths"].append(auth)
        env["orders"].append(order)
        env["uplifts"].append(uplift)
    return env
