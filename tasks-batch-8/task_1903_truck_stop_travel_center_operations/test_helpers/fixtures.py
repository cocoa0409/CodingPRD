"""Composite setup helpers.

Multi-step preconditions shared by the test suite. Every fixture builds its
state from scratch through public endpoints (the server restarts with an
empty database before every test) and uses lenient get_success_data so setup
failures surface as clear "Setup failed" errors.

Ordering note: retail fuel prices are always posted while the logical clock
still reads its initial value (2026-08-01T00:00:00Z) with effective_from equal
to that instant, so the posting is never in the past; the clock is advanced to
the working time only after prices are in place.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, REGISTER_FLOAT_CENTS, TEST_CLOCK_ISO
from .factories import (
    create_bay_payload,
    create_bulk_tank_payload,
    create_contract_payload,
    create_discount_network_payload,
    create_enrollment_payload,
    create_fleet_account_payload,
    create_fuel_price_payload,
    create_fuel_sale_payload,
    create_loyalty_member_payload,
    create_member_vehicle_payload,
    create_parking_reservation_payload,
    create_parking_space_payload,
    create_pump_payload,
    create_purchase_order_payload,
    create_register_payload,
    create_scale_ticket_payload,
    create_service_ticket_payload,
    create_shift_payload,
    create_site_payload,
    create_stock_item_payload,
    create_technician_payload,
    create_vendor_payload,
    create_work_order_payload,
    dispensing_complete_payload,
    issue_part_payload,
    member_adjustment_payload,
    po_receive_payload,
    scale_settle_payload,
    scale_weigh_payload,
    set_clock_payload,
    shift_close_payload,
    shift_drop_payload,
    shift_payout_payload,
    work_order_estimate_payload,
    work_order_schedule_payload,
    complete_work_payload,
)
from .test_users import (
    TEST_USERS,
    make_fleet_manager_headers,
    make_loyalty_member_headers,
    make_maintenance_tech_headers,
)

GM = TEST_USERS["gm_headers"]
SM_1 = TEST_USERS["sm_1_headers"]
SM_2 = TEST_USERS["sm_2_headers"]
FDL = TEST_USERS["fdl_headers"]
CASH_1 = TEST_USERS["cash_1_headers"]
CASH_2 = TEST_USERS["cash_2_headers"]


# ---------------------------------------------------------------------------
# Tier 0: atomic helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=TEST_CLOCK_ISO):
    """Advance the logical clock (GeneralManager-only admin capability)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), GM))


def create_site(name="Site A", parking_total_spaces=60, parking_paid_capacity=2,
                shower_units_count=1, laundry_machines_count=1):
    payload = create_site_payload(
        name=name,
        parking_total_spaces=parking_total_spaces,
        parking_paid_capacity=parking_paid_capacity,
        shower_units_count=shower_units_count,
        laundry_machines_count=laundry_machines_count,
    )
    return get_success_data(api_client.create_site(payload, GM))


def reload_site(site_id):
    return get_success_data(api_client.get_site(site_id, GM))


def post_fuel_price(site_id, fuel_type="DIESEL", cents=385,
                    effective_from=DEFAULT_CLOCK_ISO, effective_to=None):
    """Post a retail price against a site, sourcing the OCC guard from a fresh
    site read. Returns (price_row, site_version_after)."""
    site = reload_site(site_id)
    payload = create_fuel_price_payload(
        site["version"], fuel_type=fuel_type, cents=cents,
        effective_from=effective_from, effective_to=effective_to,
    )
    price = get_success_data(api_client.create_fuel_price(site_id, payload, FDL))
    return price, reload_site(site_id)["version"]


def create_pump(site_id, pump_number=1, fuel_types=("DIESEL",)):
    return get_success_data(
        api_client.create_pump(site_id, create_pump_payload(pump_number, fuel_types), FDL)
    )


def create_register(site_id, register_code="R1", float_cents=REGISTER_FLOAT_CENTS):
    return get_success_data(
        api_client.create_register(
            site_id, create_register_payload(register_code, float_cents), GM)
    )


def open_shift(site_id, register_id, cashier_user_id="cash-1", shift_label="DAY",
               opener_headers=None):
    """Open a shift on a register; opened_by records the acting manager."""
    headers = opener_headers or SM_1
    return get_success_data(
        api_client.create_shift(
            site_id, create_shift_payload(register_id, cashier_user_id, shift_label),
            headers)
    )


def reload_shift(shift_id):
    return get_success_data(api_client.get_shift(shift_id, SM_2))


def reload_register(register_id):
    return get_success_data(api_client.get_register(register_id, SM_2))


def reload_pump(pump_id):
    return get_success_data(api_client.get_pump(pump_id, GM))


def reload_member(member_id):
    return get_success_data(api_client.get_loyalty_member(member_id, GM))


def reload_fleet(fleet_id):
    return get_success_data(api_client.get_fleet_account(fleet_id, GM))


def reload_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, GM))


def reload_stock_item(item_id):
    return get_success_data(api_client.get_stock_item(item_id, GM))


def reload_bay(bay_id):
    return get_success_data(api_client.get_bay(bay_id, GM))


def reload_work_order(wo_id):
    return get_success_data(api_client.get_work_order(wo_id, GM))


# ---------------------------------------------------------------------------
# Tier 1: site + register + shift base states
# ---------------------------------------------------------------------------

def setup_shift_site(name="Site A", register_float=REGISTER_FLOAT_CENTS,
                     clock=TEST_CLOCK_ISO, cashier="cash-1",
                     parking_total_spaces=60, parking_paid_capacity=2,
                     shower_units_count=1, laundry_machines_count=1):
    """Bare site with one register and one OPEN shift (cashier `cashier`,
    opened by sm-1). Logical clock advanced to `clock`."""
    site = create_site(name, parking_total_spaces, parking_paid_capacity,
                       shower_units_count, laundry_machines_count)
    set_clock(clock)
    register = create_register(site["id"])
    shift = open_shift(site["id"], register["id"], cashier_user_id=cashier)
    return SimpleNamespace(site=site, register=register, shift=shift)


def setup_fuel_site(name="Site A", diesel_cents=385, extra_prices=(),
                    clock=TEST_CLOCK_ISO, pump_fuel_types=("DIESEL",),
                    num_pumps=1, register_float=REGISTER_FLOAT_CENTS,
                    parking_total_spaces=60, parking_paid_capacity=2,
                    shower_units_count=1, laundry_machines_count=1):
    """Site with a retail DIESEL price (posted at the initial clock instant so
    the window is never in the past), optional extra fuel prices, pumps, one
    register, and an OPEN shift; clock advanced to `clock`.

    extra_prices: iterable of (fuel_type, cents) posted after the diesel row.
    pump_fuel_types: a single tuple applied to every pump, or a list of tuples
    (one per pump when num_pumps > 1).
    """
    site = create_site(name, parking_total_spaces, parking_paid_capacity,
                       shower_units_count, laundry_machines_count)
    prices = {}
    if diesel_cents is not None:
        prices["DIESEL"], _ = post_fuel_price(site["id"], "DIESEL", diesel_cents)
    for fuel_type, cents in extra_prices:
        prices[fuel_type], _ = post_fuel_price(site["id"], fuel_type, cents)
    set_clock(clock)
    if num_pumps > 1 and pump_fuel_types and isinstance(pump_fuel_types[0], (list, tuple)):
        type_plan = list(pump_fuel_types)
    else:
        type_plan = [pump_fuel_types] * num_pumps
    pumps = [create_pump(site["id"], i + 1, type_plan[i]) for i in range(num_pumps)]
    register = create_register(site["id"], float_cents=register_float)
    shift = open_shift(site["id"], register["id"])
    return SimpleNamespace(site=site, prices=prices, pumps=pumps,
                           register=register, shift=shift)


def setup_contract_site(name="Site B", rack_price_4dp=2.7000,
                        clock=TEST_CLOCK_ISO, num_pumps=1,
                        register_float=REGISTER_FLOAT_CENTS,
                        pump_fuel_types=("DIESEL",)):
    """Site with a DIESEL bulk tank carrying the given rack price (feeds
    contract quoting), pumps, register, and an OPEN shift."""
    site = create_site(name)
    tank = get_success_data(api_client.create_bulk_tank(
        site["id"],
        create_bulk_tank_payload(
            product_type="DIESEL", rack_price_cents_per_gallon_4dp=rack_price_4dp),
        GM))
    set_clock(clock)
    pumps = [create_pump(site["id"], i + 1, pump_fuel_types)
             for i in range(num_pumps)]
    register = create_register(site["id"], float_cents=register_float)
    shift = open_shift(site["id"], register["id"])
    return SimpleNamespace(site=site, tank=tank, pumps=pumps,
                           register=register, shift=shift)


# ---------------------------------------------------------------------------
# Tier 2: loyalty members, vehicles, networks
# ---------------------------------------------------------------------------

def create_member(points=0, stack_cap_points=None, full_name="Driver A",
                  email="a@x.com", fleet_account_id=None):
    overrides = {}
    if stack_cap_points is not None:
        overrides["stack_cap_points"] = stack_cap_points
    if fleet_account_id is not None:
        overrides["fleet_account_id"] = fleet_account_id
    member = get_success_data(api_client.create_loyalty_member(
        create_loyalty_member_payload(full_name, email, **overrides), CASH_1))
    if points:
        get_success_data(api_client.member_adjustment(
            member["id"], member_adjustment_payload(points, "seed"), GM))
        member = reload_member(member["id"])
    return member


def create_active_network(name="FleetPass", discount_per_gallon=0.10,
                          applicable_fuel_types=("DIESEL",), program_cap=2):
    network = get_success_data(api_client.create_discount_network(
        create_discount_network_payload(name, discount_per_gallon,
                                        applicable_fuel_types, program_cap), GM))
    get_success_data(api_client.network_activate(network["id"], GM))
    return reload_network(network["id"])


def reload_network(network_id):
    return get_success_data(api_client.get_discount_network(network_id, GM))


def enroll_member(member_id, network_id, activate=True):
    enrollment = get_success_data(api_client.create_member_enrollment(
        member_id, create_enrollment_payload(network_id), CASH_1))
    if activate:
        enrollment = get_success_data(
            api_client.enrollment_activate(enrollment["id"], CASH_1))
    return enrollment


def setup_enrolled_member(points=9000, stack_cap_points=None,
                          discount_per_gallon=0.10,
                          fuel_types=("DIESEL",), program_cap=2,
                          full_name="Driver A", email="a@x.com",
                          network_name="FleetPass"):
    """Member (seeded with `points`) holding an ACTIVE enrollment in an ACTIVE
    network granting `discount_per_gallon` off the given fuel types."""
    member = create_member(points=points, stack_cap_points=stack_cap_points,
                           full_name=full_name, email=email)
    network = create_active_network(network_name, discount_per_gallon,
                                    fuel_types, program_cap)
    enrollment = enroll_member(member["id"], network["id"], activate=True)
    member = reload_member(member["id"])
    return SimpleNamespace(member=member, network=network, enrollment=enrollment)


def create_member_with_plate(plate="AAA111", vehicle_type="TRACTOR", points=0,
                             stack_cap_points=None, full_name="Driver A",
                             email="a@x.com"):
    """Member owning a registered vehicle plate."""
    member = create_member(points=points, stack_cap_points=stack_cap_points,
                           full_name=full_name, email=email)
    vehicle = get_success_data(api_client.create_member_vehicle(
        member["id"], create_member_vehicle_payload(plate, vehicle_type), CASH_1))
    return SimpleNamespace(member=member, vehicle=vehicle)


# ---------------------------------------------------------------------------
# Tier 2: fleets and contracts
# ---------------------------------------------------------------------------

def create_fleet(name="Fleet A", credit_limit_cents=50_000_000, pricing_tier="T1"):
    return get_success_data(api_client.create_fleet_account(
        create_fleet_account_payload(name, credit_limit_cents, pricing_tier), GM))


def create_contract(fleet_id, contract_code="C-1", pricing_tier="T1",
                    discount_per_gallon_off=0.0,
                    applicable_fuel_types=("DIESEL",),
                    effective_from="2026-08-01T00:00:00Z",
                    effective_to="2027-08-01T00:00:00Z"):
    return get_success_data(api_client.create_contract(
        fleet_id,
        create_contract_payload(contract_code, pricing_tier,
                                discount_per_gallon_off, applicable_fuel_types,
                                effective_from, effective_to),
        GM))


def setup_fleet_with_contract(name="Fleet A", credit_limit_cents=50_000_000,
                              fleet_tier="T1", contract_tier="T1",
                              discount_per_gallon_off=0.0, contract_code="C-1",
                              applicable_fuel_types=("DIESEL",), activate=True):
    """Fleet account plus one contract (activated when `activate`)."""
    fleet = create_fleet(name, credit_limit_cents, fleet_tier)
    contract = create_contract(fleet["id"], contract_code, contract_tier,
                               discount_per_gallon_off, applicable_fuel_types)
    if activate:
        contract = get_success_data(api_client.contract_activate(contract["id"], GM))
    return SimpleNamespace(fleet=reload_fleet(fleet["id"]), contract=contract)


# ---------------------------------------------------------------------------
# Tier 3: fuel sale lifecycle shortcuts
# ---------------------------------------------------------------------------

def authorize_retail_sale(ctx, pump_idx=0, member_id=None, redeem_points=0,
                          max_gallons=40.0, fuel_type="DIESEL",
                          tender_type="CASH"):
    overrides = {}
    if member_id is not None:
        overrides["loyalty_member_id"] = member_id
    if redeem_points:
        overrides["requested_redeem_points"] = redeem_points
    payload = create_fuel_sale_payload(
        ctx.pumps[pump_idx]["id"], ctx.shift["id"], pricing_mode="RETAIL",
        fuel_type=fuel_type, tender_type=tender_type, max_gallons=max_gallons,
        **overrides)
    return get_success_data(
        api_client.create_fuel_sale(ctx.site["id"], payload, CASH_1))


def authorize_contract_sale(ctx, fleet_id, contract_id, pump_idx=0,
                            max_gallons=100.0, fuel_type="DIESEL"):
    payload = create_fuel_sale_payload(
        ctx.pumps[pump_idx]["id"], ctx.shift["id"], pricing_mode="CONTRACT",
        fuel_type=fuel_type, tender_type="FLEET_BILLING", max_gallons=max_gallons,
        fleet_account_id=fleet_id, contract_id=contract_id)
    return get_success_data(
        api_client.create_fuel_sale(ctx.site["id"], payload, CASH_1))


def dispensing_start(sale_id):
    return get_success_data(api_client.fuel_sale_dispensing_start(sale_id, CASH_1))


def dispensing_complete(sale_id, dispensed_gallons):
    return get_success_data(api_client.fuel_sale_dispensing_complete(
        sale_id, dispensing_complete_payload(dispensed_gallons), CASH_1))


def finalize_sale(sale_id):
    return get_success_data(api_client.fuel_sale_finalize(sale_id, CASH_1))


def finalize_fuel_sale(sale_id, dispensed_gallons):
    """Walk a sale AUTHORIZED -> FUELING -> PENDING_FINALIZE -> COMPLETED."""
    dispensing_start(sale_id)
    dispensing_complete(sale_id, dispensed_gallons)
    return finalize_sale(sale_id)


def pay_sale_cash(sale_id):
    return get_success_data(
        api_client.fuel_sale_pay(sale_id, {"tender_type": "CASH"}, CASH_1))


def void_sale(sale_id, reason="void", headers=None):
    return get_success_data(
        api_client.fuel_sale_void(sale_id, {"reason": reason}, headers or SM_2))


# ---------------------------------------------------------------------------
# Tier 3: parking reservations
# ---------------------------------------------------------------------------

def create_parking_reservation(site_id, member_id, plate, space_type="STANDARD",
                               reserved_from="2026-08-12T22:00:00Z",
                               reserved_to="2026-08-13T06:00:00Z",
                               redeem_points=None, headers=None):
    overrides = {}
    if redeem_points is not None:
        overrides["requested_redeem_points"] = redeem_points
    payload = create_parking_reservation_payload(
        member_id, plate, space_type, reserved_from, reserved_to, **overrides)
    return get_success_data(api_client.create_parking_reservation(
        site_id, payload, headers or CASH_1))


def create_parking_space(site_id, space_number="A1", space_type="STANDARD",
                         is_reservable=True):
    return get_success_data(api_client.create_parking_space(
        site_id,
        create_parking_space_payload(space_number, space_type, is_reservable),
        GM))


# ---------------------------------------------------------------------------
# Tier 3: service queue
# ---------------------------------------------------------------------------

def create_service_ticket(site_id, service_type="SHOWER", shift_id=None,
                          member_id=None, redeem_points=None):
    overrides = {}
    if shift_id is not None:
        overrides["shift_id"] = shift_id
    if member_id is not None:
        overrides["loyalty_member_id"] = member_id
    if redeem_points is not None:
        overrides["requested_redeem_points"] = redeem_points
    return get_success_data(api_client.create_service_ticket(
        site_id, create_service_ticket_payload(service_type, **overrides), CASH_1))


def call_queue(site_id, service_type="SHOWER"):
    return get_success_data(api_client.call_service_queue(
        site_id, {"service_type": service_type}, CASH_1))


def start_ticket(ticket_id):
    return get_success_data(api_client.service_ticket_start(ticket_id, CASH_1))


# ---------------------------------------------------------------------------
# Tier 3: scale tickets
# ---------------------------------------------------------------------------

def create_scale_ticket(ctx, certified=True, vehicle_plate="TRK-9",
                        carrier_name="Acme Hauling"):
    return get_success_data(api_client.create_scale_ticket(
        ctx.site["id"],
        create_scale_ticket_payload(ctx.shift["id"], vehicle_plate,
                                    carrier_name, certified),
        CASH_1))


def record_weigh(ticket_id, weigh_kind, weight_lbs):
    return get_success_data(api_client.scale_ticket_weigh(
        ticket_id, scale_weigh_payload(weigh_kind, weight_lbs), CASH_1))


def settle_ticket(ticket_id, tender_type="CASH"):
    return get_success_data(api_client.scale_ticket_settle(
        ticket_id, scale_settle_payload(tender_type), CASH_1))


# ---------------------------------------------------------------------------
# Tier 2/3: stock, vendors, purchase orders
# ---------------------------------------------------------------------------

def create_stock_item(site_id, **overrides):
    return get_success_data(api_client.create_stock_item(
        site_id, create_stock_item_payload(**overrides), GM))


def create_vendor(site_id, name="Parts R Us", category="GENERAL"):
    return get_success_data(api_client.create_vendor(
        site_id, create_vendor_payload(name, category), GM))


def receive_stock_via_po(site_id, sku, quantity, unit_price_cents=3000):
    """Full replenishment cycle: vendor -> DRAFT PO -> APPROVED -> RECEIVED.
    Returns the received purchase order."""
    vendor = create_vendor(site_id)
    po = get_success_data(api_client.create_purchase_order(
        site_id,
        create_purchase_order_payload(
            vendor["id"], [{"sku": sku, "quantity": quantity,
                            "unit_price_cents": unit_price_cents}]),
        GM))
    get_success_data(api_client.purchase_order_approve(po["id"], GM))
    return get_success_data(api_client.purchase_order_receive(
        po["id"], po_receive_payload([{"sku": sku, "quantity": quantity}]), GM))


# ---------------------------------------------------------------------------
# Tier 3: work orders
# ---------------------------------------------------------------------------

def create_technician(site_id, name="Tech One", hourly_rate_cents=12500):
    return get_success_data(api_client.create_technician(
        site_id, create_technician_payload(name, hourly_rate_cents), GM))


def create_bay(site_id, bay_number=1):
    return get_success_data(api_client.create_bay(
        site_id, create_bay_payload(bay_number), GM))


def create_work_order(site_id, vehicle_plate="TRK-1", complaint="brake shake",
                      fleet_account_id=None):
    overrides = {}
    if fleet_account_id is not None:
        overrides["fleet_account_id"] = fleet_account_id
    return get_success_data(api_client.create_work_order(
        site_id, create_work_order_payload(vehicle_plate, complaint, **overrides),
        CASH_1))


def advance_work_order_to_approved(wo_id, tech_id, labor_hours_est=2.0,
                                   approver_headers=None):
    """CREATED -> ESTIMATED -> APPROVED (retail approval by GM by default)."""
    tech_headers = make_maintenance_tech_headers(tech_id)
    get_success_data(api_client.work_order_estimate(
        wo_id, work_order_estimate_payload(labor_hours_est), tech_headers))
    get_success_data(api_client.work_order_approve_estimate(
        wo_id, approver_headers or GM))
    return reload_work_order(wo_id)


def schedule_work_order(wo_id, bay_id, tech_id,
                        scheduled_from="2026-08-13T08:00:00Z",
                        scheduled_to="2026-08-13T10:00:00Z"):
    get_success_data(api_client.work_order_schedule(
        wo_id,
        work_order_schedule_payload(bay_id, tech_id, scheduled_from, scheduled_to),
        GM))
    return reload_work_order(wo_id)


def setup_work_order_in_progress(site=None, tech_rate=12500, labor_est=2.0,
                                 scheduled_from="2026-08-13T08:00:00Z",
                                 scheduled_to="2026-08-13T10:00:00Z",
                                 complaint="brake shake", vehicle_plate="TRK-1",
                                 set_clock_first=True):
    """Work order walked CREATED -> ESTIMATED -> APPROVED -> SCHEDULED ->
    IN_SHOP -> IN_PROGRESS with one technician and one bay."""
    if site is None:
        site = create_site("Shop Site")
        if set_clock_first:
            set_clock(TEST_CLOCK_ISO)
    tech = create_technician(site["id"], hourly_rate_cents=tech_rate)
    bay = create_bay(site["id"], 1)
    wo = create_work_order(site["id"], vehicle_plate, complaint)
    advance_work_order_to_approved(wo["id"], tech["id"], labor_est)
    schedule_work_order(wo["id"], bay["id"], tech["id"],
                        scheduled_from, scheduled_to)
    tech_headers = make_maintenance_tech_headers(tech["id"])
    get_success_data(api_client.work_order_check_in(wo["id"], tech_headers))
    get_success_data(api_client.work_order_start_work(wo["id"], tech_headers))
    wo = reload_work_order(wo["id"])
    return SimpleNamespace(site=site, tech=tech, bay=bay, wo=wo,
                           tech_headers=tech_headers)


# ---------------------------------------------------------------------------
# Tier 4: shift cash accumulation
# ---------------------------------------------------------------------------

def post_drop(shift_id, amount_cents, denominations, headers=None):
    return get_success_data(api_client.shift_drop(
        shift_id, shift_drop_payload(amount_cents, denominations),
        headers or CASH_1))


def post_payout(shift_id, amount_cents, reason="payout", headers=None):
    return get_success_data(api_client.shift_payout(
        shift_id, shift_payout_payload(amount_cents, reason), headers or SM_2))


def close_shift(shift_id, counted_cash_cents, approve_variance=None,
                headers=None):
    return get_success_data(api_client.shift_close(
        shift_id, shift_close_payload(counted_cash_cents, approve_variance),
        headers or SM_2))
