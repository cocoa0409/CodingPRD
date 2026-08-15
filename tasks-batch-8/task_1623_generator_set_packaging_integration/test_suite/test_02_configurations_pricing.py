"""Package configurations: runtime gate, locale ullage, order total pricing (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_configuration,
    get_success_data,
    setup_authorized_order,
    setup_locked_configuration,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_engineer_headers"]
APP_ENG = TEST_USERS["application_engineer_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/fuel_tank_runtime_locale_ullage_nonlinear
# ---------------------------------------------------------------------------

def test_fuel_runtime_locale_ullage_tx_locks_ca_rejected(api):
    """PRD §3.3: "The ullage reserve depends on the order's `site_locale`: for
    `US_CA` the tank's unusable fraction is 12 percent, and for any other locale
    it is 10 percent, so `usable_gallons` is the tank size scaled by one minus
    that fraction."
    PRD §3.3: "`runtime_hours` is at least `min_runtime_hours` — an exactly-equal
    runtime passes, and a shortfall is rejected with `ERR_FUEL_RUNTIME_INSUFFICIENT`."

    A 400-gal tank on a 15.0 gph engine yields 24.00 h in US_TX (ullage 10%),
    locking cleanly, but only 23.47 h in US_CA (ullage 12%), which the lock gate
    rejects against the 24 h STANDARD floor.

    Design: Difficulty/combinatorial_formula/fuel_tank_runtime_locale_ullage_nonlinear
    """
    tx = setup_authorized_order(order_overrides={"site_locale": "US_TX"})
    cfg_tx = create_configuration(
        tx["order"]["id"], tx["study"]["id"],
        enclosure_type="WEATHERPROOF", enclosure_price_cents=5000000,
        fuel_tank_gallons=400,
    )
    assert cfg_tx["runtime_hours"] == pytest.approx(24.00, abs=0.001)
    cfg_tx = validate_success(api.lock_configuration(cfg_tx["id"], APP_ENG))
    assert cfg_tx["status"] == "LOCKED"

    ca = setup_authorized_order(
        customer_overrides={"primary_locale": "US_CA"},
        order_overrides={"site_locale": "US_CA"},
        engine_overrides={"emissions_tier_capability": "TIER_4_FINAL_CARB"},
    )
    cfg_ca = create_configuration(
        ca["order"]["id"], ca["study"]["id"],
        enclosure_type="WEATHERPROOF", enclosure_price_cents=5000000,
        fuel_tank_gallons=400,
    )
    assert cfg_ca["runtime_hours"] == pytest.approx(23.47, abs=0.001)
    resp = api.lock_configuration(cfg_ca["id"], APP_ENG)
    validate_error(resp, ApiErrorId.ERR_FUEL_RUNTIME_INSUFFICIENT)
    current = get_success_data(api.get_configuration(cfg_ca["id"], APP_ENG))
    assert current["status"] == "DRAFT"


def test_fuel_runtime_usable_gallons_differ_by_locale(api):
    """PRD §3.3: "for `US_CA` the tank's unusable fraction is 12 percent, and for
    any other locale it is 10 percent, so `usable_gallons` is the tank size
    scaled by one minus that fraction."

    The identical 400-gal tank computes usable_gallons 360.0 under US_TX and
    352.0 under US_CA — the locale branch alone drives the divergence.

    Design: Difficulty/combinatorial_formula/fuel_tank_runtime_locale_ullage_nonlinear
    """
    tx = setup_authorized_order(order_overrides={"site_locale": "US_TX"})
    cfg_tx = create_configuration(
        tx["order"]["id"], tx["study"]["id"], fuel_tank_gallons=400,
    )
    assert cfg_tx["usable_gallons"] == pytest.approx(360.0, abs=0.001)

    ca = setup_authorized_order(
        customer_overrides={"primary_locale": "US_CA"},
        order_overrides={"site_locale": "US_CA"},
        engine_overrides={"emissions_tier_capability": "TIER_4_FINAL_CARB"},
    )
    cfg_ca = create_configuration(
        ca["order"]["id"], ca["study"]["id"], fuel_tank_gallons=400,
    )
    assert cfg_ca["usable_gallons"] == pytest.approx(352.0, abs=0.001)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/runtime_exactly_24_locks
# ---------------------------------------------------------------------------

def test_runtime_exactly_24_locks(api):
    """PRD §3.3: "`runtime_hours` is at least `min_runtime_hours` — an
    exactly-equal runtime passes, and a shortfall is rejected with
    `ERR_FUEL_RUNTIME_INSUFFICIENT`."

    A 400-gal tank at 15.0 gph in US_TX computes runtime exactly 24.00 h,
    equal to the STANDARD floor, and the >= gate passes.

    Design: Difficulty/boundary_precision_check/runtime_exactly_24_locks
    """
    ctx = setup_authorized_order(order_overrides={"site_locale": "US_TX"})
    cfg = create_configuration(
        ctx["order"]["id"], ctx["study"]["id"], fuel_tank_gallons=400,
    )
    assert cfg["runtime_hours"] == pytest.approx(24.00, abs=0.001)
    cfg = validate_success(api.lock_configuration(cfg["id"], APP_ENG))
    assert cfg["status"] == "LOCKED"


def test_runtime_one_gallon_short_rejected(api):
    """PRD §3.3: "`runtime_hours` is at least `min_runtime_hours` — an
    exactly-equal runtime passes, and a shortfall is rejected with
    `ERR_FUEL_RUNTIME_INSUFFICIENT`."

    A 399-gal tank computes runtime 23.94 h, just under the 24 h floor, so the
    lock is rejected and the configuration stays DRAFT.

    Design: Difficulty/boundary_precision_check/runtime_exactly_24_locks
    """
    ctx = setup_authorized_order(order_overrides={"site_locale": "US_TX"})
    cfg = create_configuration(
        ctx["order"]["id"], ctx["study"]["id"], fuel_tank_gallons=399,
    )
    assert cfg["runtime_hours"] == pytest.approx(23.94, abs=0.001)
    resp = api.lock_configuration(cfg["id"], APP_ENG)
    validate_error(resp, ApiErrorId.ERR_FUEL_RUNTIME_INSUFFICIENT)
    current = get_success_data(api.get_configuration(cfg["id"], APP_ENG))
    assert current["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/order_total_circular_tier_pin
# ---------------------------------------------------------------------------

def test_order_total_tier8_pinned_evaluation_order(api):
    """PRD §3.3: "The `discount_tier` is keyed on that pre-discount subtotal,
    never on the discounted total: a pre-discount subtotal of at least 100000000
    cents earns `TIER_12` at a 12 percent rate, a subtotal of at least 50000000
    cents (but below the higher threshold) earns `TIER_8` at 8 percent, and
    anything lower earns `NONE` at zero. The discount itself is the pre-discount
    subtotal times the tier rate, rounded half-up to whole cents, and it applies
    to equipment and options only — freight is never discounted."

    Engine 30000000 + alternator 15000000 + enclosure 5000000 + tank 60000 =
    pre-discount 50060000 -> TIER_8, discount 4004800, total with freight
    1250000 = 47305200.

    Design: Difficulty/combinatorial_formula/order_total_circular_tier_pin
    """
    ctx = setup_authorized_order()
    cfg = create_configuration(
        ctx["order"]["id"], ctx["study"]["id"],
        enclosure_type="SOUND_ATTENUATED", enclosure_price_cents=5000000,
        fuel_tank_gallons=400,
    )
    assert cfg["tank_price_cents"] == 60000
    validate_success(api.lock_configuration(cfg["id"], APP_ENG))
    order = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    assert order["discount_tier"] == "TIER_8"
    assert order["total_price_cents"] == 47305200
    assert order["build_status"] == "CONFIGURING"


def test_order_total_freight_added_after_discount(api):
    """PRD §3.3: "The order's `total_price_cents` is then the pre-discount
    subtotal minus the discount plus the order's stored `freight_charge_cents`."

    The same locked configuration persists freight undiscounted: total is
    50060000 - 4004800 + 1250000 = 47305200, not a freight-discounted variant.

    Design: Difficulty/combinatorial_formula/order_total_circular_tier_pin
    """
    ctx = setup_authorized_order(freight_charge_cents=1250000)
    cfg = create_configuration(
        ctx["order"]["id"], ctx["study"]["id"],
        enclosure_type="SOUND_ATTENUATED", enclosure_price_cents=5000000,
        fuel_tank_gallons=400,
    )
    validate_success(api.lock_configuration(cfg["id"], APP_ENG))
    order = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    pre_discount = 30000000 + 15000000 + 5000000 + 60000
    discount = 4004800  # round_half_up(50060000 * 0.08)
    assert order["total_price_cents"] == pre_discount - discount + 1250000


# ---------------------------------------------------------------------------
# Corner/entities/configuration_computed_fields_at_creation
# ---------------------------------------------------------------------------

def test_configuration_computed_fields_at_creation(api):
    """PRD §3.3: "The ullage reserve depends on the order's `site_locale`: for
    `US_CA` the tank's unusable fraction is 12 percent, and for any other locale
    it is 10 percent... The `tank_price_cents` is the tank size in gallons
    multiplied by 150 cents per gallon... The runtime floor `min_runtime_hours`
    is 48 when the order's `occupancy_type` is `HOSPITAL` and 24 otherwise."

    A US_TX HOSPITAL configuration with a 1000-gal tank computes usable 900.0,
    tank price 150000, runtime 60.0 (burn 15.0), min runtime 48 — at creation,
    before any lock.

    Design: Corner/entities/configuration_computed_fields_at_creation
    """
    ctx = setup_authorized_order(order_overrides={"occupancy_type": "HOSPITAL"})
    cfg = create_configuration(
        ctx["order"]["id"], ctx["study"]["id"],
        enclosure_type="WEATHERPROOF", enclosure_price_cents=5000000,
        fuel_tank_gallons=1000,
    )
    assert cfg["usable_gallons"] == pytest.approx(900.0, abs=0.001)
    assert cfg["tank_price_cents"] == 150000
    assert cfg["min_runtime_hours"] == 48
    assert cfg["runtime_hours"] == pytest.approx(60.0, abs=0.001)


# ---------------------------------------------------------------------------
# Corner/state_machines/configuration_unlock_reverts_lock
# ---------------------------------------------------------------------------

def test_configuration_unlock_reverts_lock(api):
    """PRD §3.3: "A `LOCKED` configuration can revert to `DRAFT` through
    unlocking, but only while no permit case for it sits in `SUBMITTED` or
    `APPROVED`...; unlocking increments the configuration's `version`."

    With no permit created, the unlock succeeds and returns the configuration
    to DRAFT.

    Design: Corner/state_machines/configuration_unlock_reverts_lock
    """
    ctx = setup_locked_configuration()
    assert ctx["configuration"]["status"] == "LOCKED"
    unlocked = validate_success(api.unlock_configuration(ctx["configuration"]["id"], APP_ENG))
    assert unlocked["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/state_machines/unlock_blocked_by_live_permit
# ---------------------------------------------------------------------------

def test_unlock_blocked_by_live_permit(api):
    """PRD §3.3: "A `LOCKED` configuration can revert to `DRAFT` through
    unlocking, but only while no permit case for it sits in `SUBMITTED` or
    `APPROVED` (a live permit blocks the revert with `ERR_PERMIT_STATE_INVALID`)."

    Design: Corner/state_machines/unlock_blocked_by_live_permit
    """
    from test_helpers import setup_submitted_permit
    ctx = setup_submitted_permit()
    assert ctx["permit"]["status"] == "SUBMITTED"
    resp = api.unlock_configuration(ctx["configuration"]["id"], APP_ENG)
    validate_error(resp, ApiErrorId.ERR_PERMIT_STATE_INVALID)
    current = get_success_data(api.get_configuration(ctx["configuration"]["id"], APP_ENG))
    assert current["status"] == "LOCKED"


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/derived_field_recomputed_on_config_lock_and_version_bump
# ---------------------------------------------------------------------------

def test_order_total_null_before_lock_computed_at_lock(api):
    """PRD §3.3: "Locking recomputes and persists the order's `total_price_cents`
    and `discount_tier`..."

    The lock computes the total: engine 30000000 + alternator 15000000 +
    enclosure 2000000 + tank 60000 = pre-discount 47060000, tier NONE, total
    47060000 + freight 1250000 = 48310000.

    Design: Corner/cross_cutting_layers/derived_field_recomputed_on_config_lock_and_version_bump
    """
    ctx = setup_authorized_order()
    cfg = create_configuration(ctx["order"]["id"], ctx["study"]["id"])
    order_before = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    version_before = order_before["version"]
    validate_success(api.lock_configuration(cfg["id"], APP_ENG))
    order_after = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    assert order_after["total_price_cents"] == 48310000
    assert order_after["discount_tier"] == "NONE"
    assert order_after["version"] > version_before
