"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors instead of confusing assertion failures. Every helper
builds its preconditions from scratch using only PRD-declared endpoints,
because each test runs against a freshly restarted server.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AZ_RULE_PAYLOAD,
    DELIVERED_CLOCK,
    GP1_PAYLOAD,
    GP3_PAYLOAD,
    LOAD_DATE,
    MN_RULE_PAYLOAD,
    ORDER_DATE,
    SHIP_DATE,
    V200_PAYLOAD,
    WAVE_DATE,
)
from .factories import (
    create_a050_series_payload,
    create_dealer_payload,
    create_energy_code_rule_payload,
    create_glass_package_payload,
    create_gp3_package_payload,
    create_order_line_payload,
    create_order_payload,
    create_rack_payload,
    create_reservation_payload,
    create_warranty_claim_payload,
    create_wave_payload,
)
from .test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["plant_engineer_headers"]
PL = TEST_USERS["production_lead_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]
WA = TEST_USERS["warranty_adjuster_headers"]


# ─── Tier 1: single-resource creators ────────────────────────────────────────

def create_dealer(name="NorthStar", state="MN"):
    """Create a Dealer (credit_status starts ACTIVE per PRD §3.1)."""
    res = api_client.create_dealer(create_dealer_payload(name=name, ship_to_state_code=state), PM)
    return get_success_data(res)


def create_series_v200(**overrides):
    payload = dict(V200_PAYLOAD)
    payload.update(overrides)
    return get_success_data(api_client.create_catalog_series(payload, PE))


def create_series_a050(**overrides):
    return get_success_data(api_client.create_catalog_series(create_a050_series_payload(**overrides), PE))


def create_glass_gp1(**overrides):
    payload = dict(GP1_PAYLOAD)
    payload.update(overrides)
    return get_success_data(api_client.create_glass_package(payload, PE))


def create_glass_gp3(**overrides):
    return get_success_data(api_client.create_glass_package(create_gp3_package_payload(**overrides), PE))


def create_energy_rule(payload=None, **overrides):
    body = dict(payload if payload is not None else MN_RULE_PAYLOAD)
    body.update(overrides)
    return get_success_data(api_client.create_energy_code_rule(body, PE))


def create_az_rule():
    return create_energy_rule(payload=AZ_RULE_PAYLOAD)


def create_draft_order(dealer_id, order_date=ORDER_DATE, **overrides):
    res = api_client.create_order(
        create_order_payload(dealer_id, order_date=order_date, **overrides), PM
    )
    return get_success_data(res)


def add_line(order_id, series_id, glass_package_id, **overrides):
    res = api_client.add_order_line(
        order_id, create_order_line_payload(series_id, glass_package_id, **overrides), PM
    )
    return get_success_data(res)


def confirm_order(order_id):
    return get_success_data(api_client.confirm_order(order_id, PM))


# ─── Tier 2: catalog + order composites ──────────────────────────────────────

def setup_mn_catalog(dealer_name="NorthStar", dealer_state="MN", with_rule=True):
    """MN energy rule + V200 series + GP1 glass package + dealer.

    Returns dict(rule|None, series, glass, dealer).
    """
    rule = create_energy_rule() if with_rule else None
    series = create_series_v200()
    glass = create_glass_gp1()
    dealer = create_dealer(name=dealer_name, state=dealer_state)
    return {"rule": rule, "series": series, "glass": glass, "dealer": dealer}


def setup_confirmed_order(quantity=1, shape="RECTANGLE", width=40, height=60,
                          grid="NONE", hardware="STANDARD", order_date=ORDER_DATE,
                          catalog=None):
    """MN catalog + dealer + DRAFT order with one line, then confirm.

    Returns dict(order, line, wave=None, series, glass, dealer, rule).
    """
    cat = catalog or setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"], order_date=order_date)
    line = add_line(order["id"], cat["series"]["id"], cat["glass"]["id"],
                    shape=shape, width_in=width, height_in=height,
                    quantity=quantity, grid_style=grid, hardware_finish=hardware)
    order = confirm_order(order["id"])
    return {**cat, "order": order, "line": line}


# ─── Tier 3: waves and release lifecycle ─────────────────────────────────────

def create_wave(wave_date=WAVE_DATE, capacity_units=10, capacity_glass_sqft=500):
    return get_success_data(api_client.create_wave(
        create_wave_payload(wave_date=wave_date, capacity_units=capacity_units,
                            capacity_glass_sqft=capacity_glass_sqft), PL))


def create_open_wave(wave_date=WAVE_DATE, capacity_units=10, capacity_glass_sqft=500):
    wave = create_wave(wave_date, capacity_units, capacity_glass_sqft)
    return get_success_data(api_client.open_wave(wave["id"], PL))


def assign_order(wave_id, order_id, headers=None):
    """OCC-safe assignment: read the wave version, then assign (PRD §2.8)."""
    headers = headers or PL
    wave = get_success_data(api_client.get_wave(wave_id, headers))
    res = api_client.assign_order_to_wave(
        wave_id, {"order_id": order_id, "expected_wave_version": wave["version"]}, headers
    )
    return get_success_data(res)


def lock_and_release(wave_id):
    get_success_data(api_client.lock_wave(wave_id, PL))
    return get_success_data(api_client.release_wave(wave_id, PL))


def setup_order_in_production(quantity=1, capacity_units=10, capacity_glass_sqft=500,
                              wave_date=WAVE_DATE, catalog=None, **line_kw):
    """Confirmed order assigned to a wave, wave locked and released.

    Returns dict(order, line, wave, units, series, glass, dealer, rule).
    The order is IN_PROGRESS, its line IN_PRODUCTION, with `quantity`
    QUEUED IG units (PRD §3.4 release cascade).
    """
    env = setup_confirmed_order(quantity=quantity, catalog=catalog, **line_kw)
    wave = create_open_wave(wave_date=wave_date, capacity_units=capacity_units,
                            capacity_glass_sqft=capacity_glass_sqft)
    assign_order(wave["id"], env["order"]["id"])
    wave = lock_and_release(wave["id"])
    units = list_line_units(env["line"]["id"])
    return {**env, "wave": wave, "units": units}


# ─── IG unit helpers ─────────────────────────────────────────────────────────

def list_line_units(line_id):
    data, _meta = _paginated(api_client.list_line_ig_units(line_id, PL))
    return data


def find_remake_of(unit_id):
    data, _meta = _paginated(api_client.list_ig_units(PL, params={"remake_of_id": unit_id}))
    assert len(data) >= 1, f"expected a remake unit with remake_of_id == {unit_id}"
    return data[0]


def advance_unit_to_gas_filled(unit_id):
    """QUEUED -> GLASS_CUT -> SEALED -> GAS_FILLED (one stage per advance)."""
    unit = None
    for _ in range(3):
        unit = get_success_data(api_client.advance_ig_unit(unit_id, PL))
    return unit


def qc_unit(unit_id, argon_measured_pct=95):
    return get_success_data(
        api_client.qc_check_ig_unit(unit_id, {"argon_measured_pct": argon_measured_pct}, PL)
    )


def produce_line(line_id, argon_measured_pct=95):
    """Advance every unit of the line to GAS_FILLED and QC-pass it.

    Returns the list of QC'd unit payloads (PRD §3.5 bubble-up completes
    the line when its last unfinished unit passes).
    """
    passed = []
    for unit in list_line_units(line_id):
        if unit["status"] in ("BROKEN", "SCRAPPED", "QC_PASSED"):
            continue
        advance_unit_to_gas_filled(unit["id"])
        passed.append(qc_unit(unit["id"], argon_measured_pct))
    return passed


# ─── Tier 4: completed / shipped / delivered orders ──────────────────────────

def setup_completed_order(quantity=1, argon_measured_pct=95, catalog=None, **line_kw):
    """Order produced end-to-end: all units QC-passed, order COMPLETED.

    Returns dict(order, line, wave, units, series, glass, dealer, rule).
    """
    env = setup_order_in_production(quantity=quantity, catalog=catalog, **line_kw)
    produce_line(env["line"]["id"], argon_measured_pct)
    order = get_success_data(api_client.get_order(env["order"]["id"], PM))
    line = get_success_data(api_client.get_order_line(env["line"]["id"], PL))
    return {**env, "order": order, "line": line}


def create_rack(rack_code="R1", slot_capacity=5):
    return get_success_data(
        api_client.create_rack(create_rack_payload(rack_code=rack_code, slot_capacity=slot_capacity), SC)
    )


def create_reservation(rack_id, order_id, load_date=LOAD_DATE, ship_date=SHIP_DATE):
    return get_success_data(api_client.create_rack_reservation(
        rack_id, create_reservation_payload(order_id, load_date=load_date, ship_date=ship_date), SC
    ))


def setup_shipped_order(quantity=1, catalog=None, **line_kw):
    """COMPLETED order loaded onto a rack and shipped (order SHIPPED).

    Returns dict(order, line, wave, rack, reservation, series, glass, dealer, rule).
    """
    env = setup_completed_order(quantity=quantity, catalog=catalog, **line_kw)
    rack = create_rack()
    reservation = create_reservation(rack["id"], env["order"]["id"])
    get_success_data(api_client.load_rack_reservation(
        reservation["id"], {"order_line_id": env["line"]["id"]}, SC
    ))
    reservation = get_success_data(api_client.ship_rack_reservation(reservation["id"], SC))
    order = get_success_data(api_client.get_order(env["order"]["id"], PM))
    return {**env, "rack": rack, "reservation": reservation, "order": order}


def setup_delivered_order(quantity=1, catalog=None, **line_kw):
    """SHIPPED order confirmed delivered with the clock at DELIVERED_CLOCK.

    Returns dict(order, line, wave, rack, reservation, series, glass, dealer, rule);
    order.delivered_at stamps the warranty epoch (PRD §3.6).
    """
    env = setup_shipped_order(quantity=quantity, catalog=catalog, **line_kw)
    set_clock(DELIVERED_CLOCK)
    order = get_success_data(api_client.confirm_delivery(env["order"]["id"], PM))
    return {**env, "order": order}


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PM))


# ─── Tier 5: warranty claim composites ───────────────────────────────────────

def create_claim(order_id, line_id, component="FRAME", coverage_variant="COMPONENT",
                 failure_date="2027-09-01T00:00:00Z", description="failure reported"):
    return get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(
            order_id, line_id, component=component, coverage_variant=coverage_variant,
            failure_date=failure_date, description=description,
        ), PM
    ))


def setup_claim_under_review(component="FRAME", coverage_variant="COMPONENT",
                             failure_date="2027-09-01T00:00:00Z",
                             clock="2027-09-01T00:00:00Z", description="failure reported"):
    """Delivered order + one claim taken into UNDER_REVIEW.

    Returns dict(claim, order, line, ...environment).
    """
    env = setup_delivered_order()
    set_clock(clock)
    claim = create_claim(env["order"]["id"], env["line"]["id"], component=component,
                         coverage_variant=coverage_variant, failure_date=failure_date,
                         description=description)
    claim = get_success_data(api_client.take_review_claim(claim["id"], WA))
    return {**env, "claim": claim}


def approve_repair_part(claim_id, part_sku="CRANK-7", quantity=1, carrier="PARCEL"):
    return get_success_data(api_client.approve_claim(
        claim_id,
        {"remedy": "REPAIR_PART", "part_sku": part_sku, "quantity": quantity, "carrier": carrier},
        WA,
    ))


def list_claim_shipments(claim_id):
    data, _meta = _paginated(api_client.list_claim_shipments(claim_id, WA))
    return data


# ─── internal ────────────────────────────────────────────────────────────────

def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)
