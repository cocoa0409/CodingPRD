"""Live-bait tanks: mortality decay, dispensing limits, capacity boundary,
dispense/return conservation, and OCC-guarded batch delivery."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_tank_decay_reduces_available_count(api):
    """PRD 3.4: "The number of dead units in that batch is the batch's `initial_count` multiplied by the daily mortality fraction — the `mortality_rate_bps_per_day` divided by 10,000 — multiplied by the age in days, floored to a whole number; a batch's survivors are its `initial_count` minus its dead units, never below zero."

    Design: Corner/calculations/calc_tank_decay_reduces_available
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    tank = fixtures.create_bait_tank(name="Decay Tank", species="MINNOW",
                                     capacity_units=100, mortality_rate_bps_per_day=200)
    fixtures.set_clock("2026-07-01T00:00:00Z")
    validate_success(
        api.deliver_batch(tank["id"],
                          {"initial_count": 100, "delivered_at": "2026-07-01T00:00:00Z",
                           "expected_bait_tank_version": tank["version"]}, MANAGER),
        expected_status=201,
    )
    fixtures.set_clock("2026-07-06T00:00:00Z")  # 5 days later

    data = validate_success(api.get_bait_tank(tank["id"], CLERK))
    assert data["available_count"] == 90, "dead = floor(100 * 0.02 * 5) = 10"
    assert data["status"] == "HEALTHY", "90 >= low_stock_threshold ceil(100*0.10)=10"


def test_dispense_beyond_availability_rejected(api):
    """PRD 3.4: "A `ShopClerk` or `ShopManager` dispenses bait by supplying a `qty`, which must be positive and no greater than the current `available_count`; a request exceeding availability is rejected with `ERR_INSUFFICIENT_BAIT` (HTTP 409)."

    Design: Corner/validations/val_insufficient_bait_on_dispense
    """
    tank = fixtures.create_bait_tank(name="Empty Tank", species="SHRIMP",
                                     capacity_units=100, mortality_rate_bps_per_day=0)
    resp = api.dispense_bait(tank["id"], {"qty": 5}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BAIT.value)


def test_dispense_zero_qty_rejected_as_invalid_request(api):
    """PRD 2.8: "Request well-formedness** — required fields present, enums and types valid, and quantities, weights, and counts positive where required, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/val_invalid_quantity_dispense_zero
    """
    tank = fixtures.create_bait_tank(name="Zero Tank", species="SHRIMP",
                                     capacity_units=100, mortality_rate_bps_per_day=0)
    resp = api.dispense_bait(tank["id"], {"qty": 0}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_stale_version_batch_delivery_rejected(api):
    """PRD 2.7: "If that value does not equal the tank's current `version` — because another delivery has already been recorded and advanced the tank's `version` since the client last read it — the delivery is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently stocking the tank twice."

    Design: Corner/cross_cutting_complexity_layers/occ_batch_delivery_stale_version_rejected
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    tank = fixtures.create_bait_tank(name="OCC Tank", species="MINNOW",
                                     capacity_units=1000, mortality_rate_bps_per_day=0)
    v0 = tank["version"]
    after = validate_success(
        api.deliver_batch(tank["id"],
                          {"initial_count": 50, "delivered_at": "2026-07-01T00:00:00Z",
                           "expected_bait_tank_version": v0}, MANAGER),
        expected_status=201,
    )
    assert after["version"] == v0 + 1, "first delivery advances the version"

    resp = api.deliver_batch(tank["id"],
                             {"initial_count": 50, "delivered_at": "2026-07-01T00:00:00Z",
                              "expected_bait_tank_version": v0}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_correct_version_batch_delivery_succeeds(api):
    """PRD 2.7: "A delivery against fresh, unchanged tank state succeeds, because deliveries are additive up to capacity."

    Design: Corner/cross_cutting_complexity_layers/occ_batch_delivery_correct_version_succeeds
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    tank = fixtures.create_bait_tank(name="OCC Tank 2", species="MINNOW",
                                     capacity_units=1000, mortality_rate_bps_per_day=0)
    v0 = tank["version"]
    after1 = validate_success(
        api.deliver_batch(tank["id"],
                          {"initial_count": 50, "delivered_at": "2026-07-01T00:00:00Z",
                           "expected_bait_tank_version": v0}, MANAGER),
        expected_status=201,
    )
    v1 = after1["version"]
    after2 = validate_success(
        api.deliver_batch(tank["id"],
                          {"initial_count": 30, "delivered_at": "2026-07-01T00:00:00Z",
                           "expected_bait_tank_version": v1}, MANAGER),
        expected_status=201,
    )
    assert after2["version"] == v1 + 1
    assert after2["available_count"] == 80, "50 + 30, no decay"


# --- Difficulty: boundary_precision_check / tank_delivery_capacity_boundary ---

def test_deliver_exactly_capacity_accepted(api):
    """PRD 3.4: "A delivery is rejected with `ERR_TANK_CAPACITY_EXCEEDED` (HTTP 409) when it would push the tank's current `available_count` plus the delivered `initial_count` above `capacity_units`."

    Design: Difficulty/boundary_precision_check/tank_delivery_capacity_boundary
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    tank = fixtures.create_bait_tank(name="Minnow A", species="MINNOW",
                                     capacity_units=100, mortality_rate_bps_per_day=0)
    after = validate_success(
        api.deliver_batch(tank["id"],
                          {"initial_count": 100, "delivered_at": "2026-07-01T00:00:00Z",
                           "expected_bait_tank_version": tank["version"]}, MANAGER),
        expected_status=201,
    )
    assert after["available_count"] == 100, "delivery at exactly capacity accepted"


def test_deliver_one_over_capacity_rejected(api):
    """PRD 3.4: "A delivery is rejected with `ERR_TANK_CAPACITY_EXCEEDED` (HTTP 409) when it would push the tank's current `available_count` plus the delivered `initial_count` above `capacity_units`."

    Design: Difficulty/boundary_precision_check/tank_delivery_capacity_boundary
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    tank = fixtures.create_bait_tank(name="Minnow A", species="MINNOW",
                                     capacity_units=100, mortality_rate_bps_per_day=0)
    after = validate_success(
        api.deliver_batch(tank["id"],
                          {"initial_count": 100, "delivered_at": "2026-07-01T00:00:00Z",
                           "expected_bait_tank_version": tank["version"]}, MANAGER),
        expected_status=201,
    )
    resp = api.deliver_batch(tank["id"],
                             {"initial_count": 1, "delivered_at": "2026-07-01T00:00:00Z",
                              "expected_bait_tank_version": after["version"]}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED.value)


# --- Difficulty: compensating_invariant / bait_count_conserved_on_dispense_return ---

def test_dispense_reduces_available_count(api):
    """PRD 3.4: "Dispensing adds `qty` to `sold_count` and recomputes availability and status."

    Design: Difficulty/compensating_invariant/bait_count_conserved_on_dispense_return
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    tank = fixtures.create_tank_with_batch(initial_count=100, capacity_units=100,
                                           mortality_rate_bps_per_day=0,
                                           delivered_at="2026-07-01T00:00:00Z",
                                           species="SHINER", name="Shiner Tank")
    assert tank["available_count"] == 100
    after = validate_success(api.dispense_bait(tank["id"], {"qty": 30}, CLERK))
    assert after["available_count"] == 70
    assert after["sold_count"] == 30


def test_return_restores_available_count_conserved(api):
    """PRD 3.4: "A previously dispensed quantity may be returned by supplying a `qty`, which subtracts from `sold_count`, clamped so `sold_count` never drops below zero, and again recomputes availability and status; returns are the compensating action for a dispense."

    Design: Difficulty/compensating_invariant/bait_count_conserved_on_dispense_return
    """
    fixtures.set_clock("2026-07-01T00:00:00Z")
    tank = fixtures.create_tank_with_batch(initial_count=100, capacity_units=100,
                                           mortality_rate_bps_per_day=0,
                                           delivered_at="2026-07-01T00:00:00Z",
                                           species="SHINER", name="Shiner Tank")
    validate_success(api.dispense_bait(tank["id"], {"qty": 30}, CLERK))
    after = validate_success(api.return_bait(tank["id"], {"qty": 30}, CLERK))
    assert after["available_count"] == 100, "conserved after dispense+return round-trip"
    assert after["sold_count"] == 0
