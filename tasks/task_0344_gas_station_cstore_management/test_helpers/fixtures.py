"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Setup calls use
the lenient get_success_data() validator so a setup failure surfaces clearly.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_manager_headers, make_cashier_headers, make_loyalty_member_headers
from . import factories as f

MANAGER = make_manager_headers()
DEFAULT_CASHIER_ID = "cash1"


# --------------------------------------------------------------------------
# Tier 1: primitive creators
# --------------------------------------------------------------------------

def create_station(**overrides) -> dict:
    """Create a station. Returns the station entity."""
    resp = api_client.create_station(f.create_station_payload(**overrides), MANAGER)
    return get_success_data(resp)


def set_clock(station_id: str, to_iso8601: str) -> dict:
    resp = api_client.set_clock(f.set_clock_payload(station_id, to_iso8601), MANAGER)
    return get_success_data(resp)


def create_grade(station_id: str, code="REGULAR", octane=87, price_cents=None) -> dict:
    """Create a fuel grade; optionally reprice to price_cents. Returns the grade."""
    resp = api_client.create_fuel_grade(
        f.create_fuel_grade_payload(station_id, code=code, octane=octane), MANAGER)
    grade = get_success_data(resp)
    if price_cents is not None:
        resp = api_client.reprice_fuel_grade(
            grade["id"], f.reprice_payload(price_cents), MANAGER)
        grade = get_success_data(resp)
    return grade


def create_tank(station_id: str, grade_id: str, label="T1",
                capacity_gallons=10000, reorder_point_gallons=1500) -> dict:
    resp = api_client.create_tank(
        f.create_tank_payload(station_id, grade_id, label=label,
                              capacity_gallons=capacity_gallons,
                              reorder_point_gallons=reorder_point_gallons), MANAGER)
    return get_success_data(resp)


def create_pump(station_id: str, tank_id: str, number=1) -> dict:
    resp = api_client.create_pump(
        f.create_pump_payload(station_id, tank_id, number=number), MANAGER)
    return get_success_data(resp)


def open_shift(station_id: str, opening_float_cents=20000, cashier_id=DEFAULT_CASHIER_ID) -> dict:
    """Open a shift as the given cashier identity. Returns the shift."""
    resp = api_client.create_shift(
        f.create_shift_payload(station_id, opening_float_cents=opening_float_cents),
        make_cashier_headers(cashier_id))
    return get_success_data(resp)


def enroll_member(station_id: str, phone=None, name="Member") -> dict:
    resp = api_client.create_loyalty_account(
        f.create_loyalty_account_payload(station_id, phone=phone, name=name),
        make_cashier_headers())
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 2: delivery lifecycle helpers
# --------------------------------------------------------------------------

def create_draft_delivery(station_id: str, tank_id: str, net_gallons=5000,
                          unit_cost_cents=280, **overrides) -> dict:
    resp = api_client.create_delivery(
        f.create_delivery_payload(station_id, tank_id, net_gallons=net_gallons,
                                  unit_cost_cents=unit_cost_cents, **overrides), MANAGER)
    return get_success_data(resp)


def post_delivery(delivery_id: str, expected_tank_version: int) -> dict:
    resp = api_client.post_delivery(
        delivery_id, f.post_delivery_payload(expected_tank_version), MANAGER)
    return get_success_data(resp)


def create_and_post_delivery(station_id: str, tank_id: str, net_gallons=5000,
                             unit_cost_cents=280) -> dict:
    """Create a DRAFT delivery and post it, reading the tank's current version first.
    Returns the posted delivery."""
    tank = get_success_data(api_client.get_tank(tank_id, MANAGER))
    delivery = create_draft_delivery(station_id, tank_id, net_gallons=net_gallons,
                                     unit_cost_cents=unit_cost_cents)
    return post_delivery(delivery["id"], tank["version"])


# --------------------------------------------------------------------------
# Tier 3: stocked-station scenario (priced grade + stocked tank + pump + shift)
# --------------------------------------------------------------------------

def setup_stocked_station(price_cents=419, code="REGULAR", capacity_gallons=10000,
                          reorder_point_gallons=1500, delivery_gallons=5000,
                          delivery_unit_cost=280, opening_float_cents=20000,
                          clock_iso=None, cashier_id=DEFAULT_CASHIER_ID):
    """Active station with one priced grade, one stocked tank (one POSTED delivery),
    one IDLE pump, and one OPEN shift.

    Returns dict with keys: station, grade, tank, pump, shift.
    """
    station = create_station()
    if clock_iso is not None:
        set_clock(station["id"], clock_iso)
    grade = create_grade(station["id"], code=code, price_cents=price_cents)
    tank = create_tank(station["id"], grade["id"], capacity_gallons=capacity_gallons,
                       reorder_point_gallons=reorder_point_gallons)
    pump = create_pump(station["id"], tank["id"], number=1)
    create_and_post_delivery(station["id"], tank["id"], net_gallons=delivery_gallons,
                             unit_cost_cents=delivery_unit_cost)
    shift = open_shift(station["id"], opening_float_cents=opening_float_cents,
                       cashier_id=cashier_id)
    return {"station": station, "grade": grade, "tank": tank, "pump": pump, "shift": shift}


# --------------------------------------------------------------------------
# Tier 3b: fuel transaction lifecycle shortcuts
# --------------------------------------------------------------------------

def authorize_fuel(station_id: str, pump_id: str, shift_id: str, gallons=12,
                   tender="CARD", loyalty_account_id=None,
                   cashier_id=DEFAULT_CASHIER_ID) -> dict:
    payload = f.create_fuel_transaction_payload(station_id, pump_id, shift_id,
                                                gallons=gallons, tender=tender)
    if loyalty_account_id is not None:
        payload["loyalty_account_id"] = loyalty_account_id
    resp = api_client.create_fuel_transaction(payload, make_cashier_headers(cashier_id))
    return get_success_data(resp)


def capture_fuel(txn_id: str, cashier_id=DEFAULT_CASHIER_ID) -> dict:
    resp = api_client.capture_fuel_transaction(txn_id, make_cashier_headers(cashier_id))
    return get_success_data(resp)


def settle_fuel(txn_id: str, shift_id: str, cashier_id=DEFAULT_CASHIER_ID) -> dict:
    """Settle a captured fuel txn, reading the shift's live version for the OCC field."""
    shift = get_success_data(api_client.get_shift(shift_id, make_cashier_headers(cashier_id)))
    resp = api_client.settle_fuel_transaction(
        txn_id, f.settle_fuel_payload(shift["version"]), make_cashier_headers(cashier_id))
    return get_success_data(resp)


def authorize_capture_settle_fuel(station_id: str, pump_id: str, shift_id: str,
                                  gallons=12, tender="CARD", loyalty_account_id=None,
                                  cashier_id=DEFAULT_CASHIER_ID) -> dict:
    """Full fuel lifecycle: authorize -> capture -> settle. Returns the settled txn."""
    txn = authorize_fuel(station_id, pump_id, shift_id, gallons=gallons, tender=tender,
                         loyalty_account_id=loyalty_account_id, cashier_id=cashier_id)
    capture_fuel(txn["id"], cashier_id=cashier_id)
    return settle_fuel(txn["id"], shift_id, cashier_id=cashier_id)


# --------------------------------------------------------------------------
# Tier 4: loyalty tier seeding
# --------------------------------------------------------------------------

def seed_gold_member(station_id: str, shift_id: str, phone=None, name="Gold") -> dict:
    """Enroll a member and push them to GOLD via a single 250000-cent CARD store sale
    (floor(250000/100)*2 = 5000 lifetime points == GOLD threshold). Returns the member
    entity AFTER the accrual (re-fetched), with tier GOLD.
    """
    member = enroll_member(station_id, phone=phone, name=name)
    gift_item = f.line_item(sku="GC", name="GiftCard", category="MISC",
                            unit_price_cents=250000, qty=1, taxable=False)
    resp = api_client.create_store_transaction(
        f.create_store_transaction_payload(station_id, shift_id,
                                           line_items=[gift_item], tender="CARD",
                                           loyalty_account_id=member["id"]),
        make_cashier_headers())
    get_success_data(resp)
    return get_success_data(api_client.get_loyalty_account(member["id"], make_cashier_headers()))


# --------------------------------------------------------------------------
# Tier 5: shift to COUNTING (for close / non-owner / boundary tests)
# --------------------------------------------------------------------------

def open_shift_counting(station_id: str, opening_float_cents=20000,
                        cashier_id=DEFAULT_CASHIER_ID) -> dict:
    """Open a shift and advance it to COUNTING. Returns the COUNTING shift
    (with its post-begin-count version)."""
    shift = open_shift(station_id, opening_float_cents=opening_float_cents, cashier_id=cashier_id)
    resp = api_client.begin_count_shift(shift["id"], make_cashier_headers(cashier_id))
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 5b: car-wash code helper
# --------------------------------------------------------------------------

def issue_car_wash_code(station_id: str, package="BASIC", loyalty_account_id=None) -> dict:
    payload = f.create_car_wash_code_payload(station_id, package=package)
    if loyalty_account_id is not None:
        payload["loyalty_account_id"] = loyalty_account_id
    resp = api_client.create_car_wash_code(payload, make_cashier_headers())
    return get_success_data(resp)
