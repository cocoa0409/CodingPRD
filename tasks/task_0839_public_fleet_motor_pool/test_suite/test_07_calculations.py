"""Chargeback mileage tiering, cost-per-mile rounding, provisional/final projection, invoice OCC."""
from test_helpers import (
    validate_success, validate_error,
    create_policy, create_department, create_pool_vehicle, create_shop_bay,
    drive_reservation_to_returned, set_clock, get_vehicle,
    get_department_version, create_fuel_log_payload, create_work_order_payload,
    TEST_USERS,
)

TECH = TEST_USERS["shop_tech_headers"]
FIN = TEST_USERS["finance_officer_headers"]

JUNE_START = "2026-06-01T00:00:00Z"
JUNE_END = "2026-07-01T00:00:00Z"


def _final_invoice_for_returned_miles(api, return_odometer, requested_start, requested_end):
    """Policy + dept + POOL vehicle + one RETURNED reservation, then a FINAL June invoice."""
    create_policy()
    dep = create_department()
    create_pool_vehicle()
    drive_reservation_to_returned(dep["id"], checkout_odometer=0, return_odometer=return_odometer,
                                  requested_start=requested_start, requested_end=requested_end)
    set_clock("2026-07-02T00:00:00Z")
    version = get_department_version(dep["id"])
    return validate_success(api.create_invoice(
        dep["id"],
        {"period_start": JUNE_START, "period_end": JUNE_END, "basis": "FINAL",
         "expected_department_version": version}, FIN), 201)


# ─── combinatorial_formula / mileage_tiering_straddle_mode_a ───

def test_mileage_tiering_straddle_charges_both_tiers(api):
    """PRD §3.7: "charge the miles_driven up to mileage_tier_boundary_miles at
    mileage_tier1_rate_cents and every mile strictly above the boundary at
    mileage_tier2_rate_cents".

    Design: Difficulty/combinatorial_formula/mileage_tiering_straddle_mode_a
    """
    invoice = _final_invoice_for_returned_miles(
        api, 1500, "2026-06-12T08:00:00Z", "2026-06-12T12:00:00Z")
    assert invoice["mileage_charge_cents"] == 90000


def test_mileage_tiering_straddle_total(api):
    """PRD §3.7: "The total_cents is the sum of the four lines." With only the mileage
    line non-zero, the total equals the straddled mileage charge.

    Design: Difficulty/combinatorial_formula/mileage_tiering_straddle_mode_a
    """
    invoice = _final_invoice_for_returned_miles(
        api, 1500, "2026-06-12T08:00:00Z", "2026-06-12T12:00:00Z")
    assert invoice["total_cents"] == 90000


# ─── combinatorial_formula / cost_per_mile_single_rounding_mode_b ───

def _drive_cost_per_mile_setup(api, vin):
    vehicle = create_pool_vehicle(vin=vin)
    bay = create_shop_bay(name=f"Bay-{vin}")
    validate_success(api.create_fuel_log(
        vehicle["id"],
        create_fuel_log_payload(reading_at="2026-03-02T00:00:00Z", gallons=5,
                                fuel_cost_cents=100, odometer_miles=3), TECH), 201)
    wo = validate_success(api.create_work_order(create_work_order_payload(
        vehicle["id"], bay["id"], wo_type="REPAIR",
        scheduled_start="2026-03-03T09:00:00Z", scheduled_end="2026-03-03T11:00:00Z",
        labor_rate_cents=100), TECH), 201)
    validate_success(api.start_work_order(wo["id"], TECH), 200)
    validate_success(api.complete_work_order(wo["id"], {"labor_hours": 1, "parts_cost_cents": 0}, TECH), 200)
    return get_vehicle(vehicle["id"])


def test_cost_per_mile_single_rounding(api):
    """PRD §3.4: "divide that summed numerator by odometer_miles and round half up a
    single time to whole cents. The components must be summed before the single division
    and the single final rounding".

    Design: Difficulty/combinatorial_formula/cost_per_mile_single_rounding_mode_b
    """
    vehicle = _drive_cost_per_mile_setup(api, "VIN-CPM-1")
    assert vehicle["cost_per_mile_cents"] == 67


def test_cost_per_mile_components_before_rounding(api):
    """PRD §3.4: "Sum the cost components first — the vehicle's lifetime_maintenance_cents
    plus its lifetime_fuel_cents". The maintenance total (100), fuel total (100), and
    odometer (3) are the pre-round inputs to the single division.

    Design: Difficulty/combinatorial_formula/cost_per_mile_single_rounding_mode_b
    """
    vehicle = _drive_cost_per_mile_setup(api, "VIN-CPM-2")
    assert vehicle["lifetime_maintenance_cents"] == 100
    assert vehicle["lifetime_fuel_cents"] == 100
    assert vehicle["odometer_miles"] == 3


# ─── dual_variant_calc / chargeback_provisional_vs_final_diverge ───

def test_final_invoice_bills_observed_mileage(api):
    """PRD §3.7: "Under FINAL, the four lines bill observed usage exactly as summed
    above." 500 observed miles under the tier-1 boundary yield an exact mileage charge.

    Design: Difficulty/dual_variant_calc/chargeback_provisional_vs_final_diverge
    """
    invoice = _final_invoice_for_returned_miles(
        api, 500, "2026-06-10T09:00:00Z", "2026-06-10T13:00:00Z")
    assert invoice["mileage_charge_cents"] == 25000
    assert invoice["total_cents"] == 25000


def test_provisional_invoice_projects_usage_lines(api):
    """PRD §3.7: "Under PROVISIONAL — an invoice issued mid-period — the three usage lines
    (mileage charge, fuel surcharge, and idle penalty) are each projected to a full-period
    run-rate before rounding, while the flat assignment fee is not projected."
    PRD §3.7: "The projection factor is the period days divided by the elapsed days, where
    the elapsed days are the seconds from period_start to the current clock divided by
    86,400, floored to a whole number, and then floored at a minimum of 1."

    Design: Difficulty/dual_variant_calc/chargeback_provisional_vs_final_diverge
    """
    create_policy()
    dep = create_department()
    create_pool_vehicle()
    drive_reservation_to_returned(dep["id"], checkout_odometer=0, return_odometer=500,
                                  requested_start="2026-06-10T09:00:00Z",
                                  requested_end="2026-06-10T13:00:00Z")
    set_clock("2026-06-16T00:00:00Z")  # 15 of 30 days elapsed -> projection factor 2
    version = get_department_version(dep["id"])
    invoice = validate_success(api.create_invoice(
        dep["id"],
        {"period_start": JUNE_START, "period_end": JUNE_END, "basis": "PROVISIONAL",
         "expected_department_version": version}, FIN), 201)
    assert invoice["mileage_charge_cents"] == 50000
    assert invoice["total_cents"] == 50000


# ─── cross_cutting_complexity_layers / stale_department_version_on_invoice_create ───

def test_stale_department_version_on_invoice_create(api):
    """PRD §2.6: "its request must carry expected_department_version holding the client's
    last-observed version of that department."
    PRD §2.6: "If that value does not equal the department's current version — because
    another writer has advanced the department ledger since the client read it — the
    create is rejected with ERR_STALE_DEPARTMENT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_department_version_on_invoice_create
    """
    dep = create_department(cost_center_code="CC-OCC")
    version = get_department_version(dep["id"])
    res = api.create_invoice(
        dep["id"],
        {"period_start": JUNE_START, "period_end": JUNE_END, "basis": "FINAL",
         "expected_department_version": version - 1}, FIN)
    validate_error(res, "ERR_STALE_DEPARTMENT_VERSION")
