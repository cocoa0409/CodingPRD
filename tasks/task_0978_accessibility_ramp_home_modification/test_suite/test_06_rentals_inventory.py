"""Rental ramp pricing, lifecycle, inventory fleet cycles, and overlap guards."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_inventory_unit, assert_rental_ramp,
    create_case, create_inventory_unit, setup_rental, setup_installed_rental,
    setup_pickup_scheduled_rental, create_rental_ramp_payload,
    create_inventory_unit_payload, set_clock, get_case,
)

IC = TEST_USERS["intake_coordinator_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
CL = TEST_USERS["crew_lead_headers"]


# ---------------------------------------------------------------------------
# Difficulty: calendar-month tier reading vs fixed 30-day block (Rental domain)
# ---------------------------------------------------------------------------

def test_rental_calendar_month_tier1_rate(api):
    """PRD §3.6: "Pricing follows a duration-tiered schedule computed at
    reservation time. The base rate is the unit's `monthly_rate_cents`. A rental
    of one to three months bills at 100 percent of that base rate; four to six
    months bills at 90 percent; seven to twelve months bills at 80 percent; and
    thirteen months or longer bills at 70 percent." 2026-05-01 to 2026-08-01 is
    exactly three months (May, June, July), so tier 1 applies.

    Design: Difficulty/dual_variant_calc/rental_calendar_month_vs_fixed_block_duration_divergence
    """
    set_clock()
    case, unit, ramp = setup_rental(
        rental_start="2026-05-01T00:00:00Z", rental_end="2026-08-01T00:00:00Z",
        unit_overrides={"unit_tag": "U-100", "monthly_rate_cents": 30000,
                        "purchase_price_cents": 500000})
    assert ramp["monthly_rate_cents"] == 30000, (
        "three calendar months is tier 1 (100%); a 30-day-block reading would give 27000")


def test_rental_calendar_month_deposit_and_initial_state(api):
    """PRD §3.6: "The `deposit_cents` is the lesser of two months of the computed
    monthly rate and 20 percent of the unit's `purchase_price_cents`. The
    reservation starts in `RESERVED` with its `deposit_status` at `HELD`, and
    creating it moves the referenced unit from `AVAILABLE` to `RESERVED`."

    Design: Difficulty/dual_variant_calc/rental_calendar_month_vs_fixed_block_duration_divergence
    """
    set_clock()
    case, unit, ramp = setup_rental(
        rental_start="2026-05-01T00:00:00Z", rental_end="2026-08-01T00:00:00Z",
        unit_overrides={"unit_tag": "U-100", "monthly_rate_cents": 30000,
                        "purchase_price_cents": 500000})
    assert ramp["deposit_cents"] == 60000, "min(2*30000, 500000*0.20)"
    assert ramp["status"] == "RESERVED"
    assert ramp["deposit_status"] == "HELD"


# ---------------------------------------------------------------------------
# Difficulty: tier multiplier x deposit cap interaction
# ---------------------------------------------------------------------------

def test_rental_tier2_rate_for_five_months(api):
    """PRD §3.6: "four to six months bills at 90 percent". "The reservation's
    `monthly_rate_cents` is the base rate multiplied by the applicable tier
    multiplier, rounded half up to whole cents." 2026-05-01 to 2026-10-01 is five
    months on a 30000 base.

    Design: Difficulty/combinatorial_formula/rental_tiered_rate_with_deposit_cap_interaction
    """
    set_clock()
    case, unit, ramp = setup_rental(
        rental_start="2026-05-01T00:00:00Z", rental_end="2026-10-01T00:00:00Z",
        unit_overrides={"unit_tag": "U-200", "ramp_type": "PORTABLE_THRESHOLD",
                        "monthly_rate_cents": 30000, "purchase_price_cents": 100000})
    assert ramp["monthly_rate_cents"] == 27000, "round_half_up(30000 * 0.90)"


def test_rental_deposit_capped_by_purchase_price(api):
    """PRD §3.6: "The `deposit_cents` is the lesser of two months of the computed
    monthly rate and 20 percent of the unit's `purchase_price_cents`."

    Design: Difficulty/combinatorial_formula/rental_tiered_rate_with_deposit_cap_interaction
    """
    set_clock()
    case, unit, ramp = setup_rental(
        rental_start="2026-05-01T00:00:00Z", rental_end="2026-10-01T00:00:00Z",
        unit_overrides={"unit_tag": "U-200", "ramp_type": "PORTABLE_THRESHOLD",
                        "monthly_rate_cents": 30000, "purchase_price_cents": 100000})
    assert ramp["deposit_cents"] == 20000, (
        "purchase-price cap branch wins: min(2*27000=54000, 100000*0.20=20000)")


# ---------------------------------------------------------------------------
# Difficulty: InventoryUnit maintenance/deployment cycle
# ---------------------------------------------------------------------------

def test_unit_maintenance_cycle_closes_to_available(api):
    """PRD §3.6: "a unit in `AVAILABLE` or `DEPLOYED` may be sent to
    `MAINTENANCE`, a unit in `MAINTENANCE` may be returned to `AVAILABLE`, and a
    unit in `AVAILABLE` or `MAINTENANCE` may be `RETIRED`, which is terminal."

    Design: Difficulty/non_linear_state_machine/inventory_unit_maintenance_deployment_cycle
    """
    set_clock()
    unit = create_inventory_unit(unit_tag="U-300", ramp_type="SUITCASE", length_feet=6,
                                 width_inches=30, weight_capacity_lbs=500,
                                 monthly_rate_cents=20000, purchase_price_cents=400000)
    in_maint = validate_success(api.send_unit_to_maintenance(unit["id"], LC), 200)
    assert in_maint["status"] == "MAINTENANCE"
    back = validate_success(api.return_unit_to_service(unit["id"], LC), 200)
    assert back["status"] == "AVAILABLE", "the maintenance cycle must close"


def test_unit_reenters_reservation_cycle_after_maintenance(api):
    """PRD §3.6: "The reservation starts in `RESERVED` with its `deposit_status`
    at `HELD`, and creating it moves the referenced unit from `AVAILABLE` to
    `RESERVED`." "On or after `rental_start`, and while the unit still reads
    `RESERVED`, a `LogisticsCoordinator` records delivery: the rental moves from
    `RESERVED` to `DELIVERED` and the unit from `RESERVED` to `DEPLOYED`."

    Design: Difficulty/non_linear_state_machine/inventory_unit_maintenance_deployment_cycle
    """
    set_clock()
    unit = create_inventory_unit(unit_tag="U-300", ramp_type="SUITCASE", length_feet=6,
                                 width_inches=30, weight_capacity_lbs=500,
                                 monthly_rate_cents=20000, purchase_price_cents=400000)
    validate_success(api.send_unit_to_maintenance(unit["id"], LC), 200)
    validate_success(api.return_unit_to_service(unit["id"], LC), 200)
    case = create_case(client_name="Hana Ives", client_address="55 Loop Ave",
                       client_phone="555-0105")
    ramp = validate_success(api.create_rental_ramp(
        case["id"], create_rental_ramp_payload(unit["id"]), LC), 201)
    unit_mid = validate_success(api.get_inventory_unit(unit["id"], IC), 200)
    assert unit_mid["status"] == "RESERVED", "unit re-enters the cycle after maintenance"
    delivered = validate_success(api.deliver_rental_ramp(case["id"], ramp["id"], LC), 200)
    assert delivered["status"] == "DELIVERED"
    unit_end = validate_success(api.get_inventory_unit(unit["id"], IC), 200)
    assert unit_end["status"] == "DEPLOYED"


# ---------------------------------------------------------------------------
# Difficulty: overlapping rental window on the same unit
# ---------------------------------------------------------------------------

def _setup_first_rental(api):
    set_clock()
    case, unit, ramp1 = setup_rental(
        rental_start="2026-05-01T00:00:00Z", rental_end="2026-06-01T00:00:00Z",
        unit_overrides={"unit_tag": "U-500", "monthly_rate_cents": 22000,
                        "purchase_price_cents": 420000})
    return case, unit, ramp1


def test_overlapping_rental_on_same_unit_rejected(api):
    """PRD §3.6: "Two clinical and logistical guards apply, in the order of §2.6:
    if the case's assessment indicates `purchase_required` — permanent
    installation is medically necessary — the reservation is refused with
    `ERR_RENTAL_NOT_CLINICALLY_INDICATED`, and if the requested period overlaps an
    existing active rental of the same unit the reservation is refused with
    `ERR_UNIT_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/overlapping_rental_on_same_unit_rejected
    """
    case, unit, ramp1 = _setup_first_rental(api)
    res = api.create_rental_ramp(
        case["id"],
        create_rental_ramp_payload(unit["id"], rental_start="2026-05-15T00:00:00Z",
                                   rental_end="2026-07-01T00:00:00Z"),
        LC)
    validate_error(res, ApiErrorId.ERR_UNIT_UNAVAILABLE, expected_status=409)


def test_overlap_rejection_leaves_first_rental_untouched(api):
    """PRD §3.6: "if the requested period overlaps an existing active rental of
    the same unit the reservation is refused with `ERR_UNIT_UNAVAILABLE` (HTTP
    409)." A refused reservation changes nothing: the first rental stays
    `RESERVED` and the unit stays `RESERVED`.

    Design: Difficulty/resource_temporal_overlap/overlapping_rental_on_same_unit_rejected
    """
    case, unit, ramp1 = _setup_first_rental(api)
    validate_error(api.create_rental_ramp(
        case["id"],
        create_rental_ramp_payload(unit["id"], rental_start="2026-05-15T00:00:00Z",
                                   rental_end="2026-07-01T00:00:00Z"),
        LC), ApiErrorId.ERR_UNIT_UNAVAILABLE, expected_status=409)
    ramp1_after = validate_success(api.get_rental_ramp(case["id"], ramp1["id"], IC), 200)
    assert ramp1_after["status"] == "RESERVED"
    unit_after = validate_success(api.get_inventory_unit(unit["id"], IC), 200)
    assert unit_after["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Corner: defaults, tiers, transitions, return side effects, lookups
# ---------------------------------------------------------------------------

def test_inventory_unit_condition_grade_defaults_to_a(api):
    """PRD §3.6: "A `LogisticsCoordinator` registers each unit with its `unit_tag`
    asset label, a `ramp_type` of `MODULAR_ALUMINUM`, `PORTABLE_THRESHOLD`,
    `SUITCASE`, or `CUSTOM_WOOD`, the `length_feet` and `width_inches` dimensions,
    the `weight_capacity_lbs` rating, the standard `monthly_rate_cents`, the
    `purchase_price_cents` if sold, and optionally a `condition_grade` of `A`,
    `B`, `C`, or `D` that defaults to `A`." "Units are created `AVAILABLE`".

    Design: Corner/entities/inventory_unit_condition_grade_defaults_to_a
    """
    unit = create_inventory_unit(unit_tag="U-D1", ramp_type="SUITCASE", length_feet=5,
                                 width_inches=30, weight_capacity_lbs=600,
                                 monthly_rate_cents=9000, purchase_price_cents=150000)
    assert unit["condition_grade"] == "A"
    assert unit["status"] == "AVAILABLE"


def test_rental_ramp_billing_cycle_day_defaults_to_1(api):
    """PRD §3.6: "A rental reservation is created under a case by a
    `LogisticsCoordinator` naming the `inventory_unit_id`, the `rental_start` and
    `rental_end` dates, and optionally the `billing_cycle_day` of the month on
    which billing recurs, defaulting to 1."

    Design: Corner/entities/rental_ramp_billing_cycle_day_defaults_to_1
    """
    set_clock()
    case, unit, ramp = setup_rental(
        unit_overrides={"unit_tag": "U-D2", "ramp_type": "PORTABLE_THRESHOLD",
                        "monthly_rate_cents": 8000, "purchase_price_cents": 120000})
    assert ramp["billing_cycle_day"] == 1


def test_rental_tier1_two_months_full_rate(api):
    """PRD §3.6: "A rental of one to three months bills at 100 percent of that
    base rate". "The `deposit_cents` is the lesser of two months of the computed
    monthly rate and 20 percent of the unit's `purchase_price_cents`."

    Design: Corner/calculations/rental_tier1_two_months_full_rate
    """
    set_clock()
    case, unit, ramp = setup_rental(
        rental_start="2026-05-01T00:00:00Z", rental_end="2026-07-01T00:00:00Z",
        unit_overrides={"unit_tag": "U-900", "ramp_type": "SUITCASE",
                        "monthly_rate_cents": 12000, "purchase_price_cents": 100000})
    assert ramp["monthly_rate_cents"] == 12000, "tier 1 multiplier 1.00"
    assert ramp["deposit_cents"] == 20000, "min(2*12000, 100000*0.20)"


def test_rental_tier4_thirteen_months_rate(api):
    """PRD §3.6: "and thirteen months or longer bills at 70 percent." "The
    reservation's `monthly_rate_cents` is the base rate multiplied by the
    applicable tier multiplier, rounded half up to whole cents." "The
    `deposit_cents` is the lesser of two months of the computed monthly rate and
    20 percent of the unit's `purchase_price_cents`."

    Design: Corner/calculations/rental_tier4_thirteen_months_rate
    """
    set_clock()
    case, unit, ramp = setup_rental(
        rental_start="2026-05-01T00:00:00Z", rental_end="2027-06-01T00:00:00Z",
        unit_overrides={"unit_tag": "U-901", "monthly_rate_cents": 20000,
                        "purchase_price_cents": 1000000})
    assert ramp["monthly_rate_cents"] == 14000, "round(20000 * 0.70)"
    assert ramp["deposit_cents"] == 28000, "cap branch not binding: min(28000, 200000)"


def test_rental_install_from_reserved_rejected(api):
    """PRD §3.6: "A `CrewLead` then installs the ramp, moving the rental from
    `DELIVERED` to `INSTALLED`". From RESERVED that transition does not exist.
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/rental_install_from_reserved_rejected
    """
    set_clock()
    case, unit, ramp = setup_rental(
        unit_overrides={"unit_tag": "U-600", "ramp_type": "SUITCASE",
                        "monthly_rate_cents": 9000, "purchase_price_cents": 160000})
    res = api.install_rental_ramp(case["id"], ramp["id"], CL)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_rental_ramp(case["id"], ramp["id"], IC), 200)
    assert after["status"] == "RESERVED"


def test_unit_operations_from_retired_rejected(api):
    """PRD §3.6: "a unit in `AVAILABLE` or `MAINTENANCE` may be `RETIRED`, which
    is terminal."
    PRD §2.6: "5. **Target resource state.** The resource being acted on must be
    in a state from which the requested transition exists; failure is one of
    `ERR_INVALID_STATE_TRANSITION`, `ERR_QUOTE_NOT_DRAFT`,
    `ERR_ASSESSMENT_NOT_SCHEDULED`, or `ERR_JOB_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Corner/state_machines/unit_operations_from_retired_rejected
    """
    unit = create_inventory_unit(unit_tag="U-700", ramp_type="CUSTOM_WOOD", length_feet=12,
                                 width_inches=36, weight_capacity_lbs=900,
                                 monthly_rate_cents=11000, purchase_price_cents=200000)
    validate_success(api.retire_unit(unit["id"], LC), 200)
    res = api.send_unit_to_maintenance(unit["id"], LC)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    after = validate_success(api.get_inventory_unit(unit["id"], IC), 200)
    assert after["status"] == "RETIRED"


def test_rental_return_side_effects_unit_available(api):
    """PRD §3.6: "When the ramp is no longer needed a `LogisticsCoordinator`
    schedules pickup, moving the rental from `IN_USE` or `INSTALLED` to
    `PICKUP_SCHEDULED`, and later confirms pickup: the rental moves to `RETURNED`,
    `actual_pickup` is stamped, the unit returns from `DEPLOYED` to `AVAILABLE`
    with the rental's duration added to its `total_rental_days`".

    Design: Corner/state_machines/rental_return_side_effects_unit_available
    """
    set_clock()
    case, unit, ramp = setup_pickup_scheduled_rental(
        rental_start="2026-05-01T00:00:00Z", rental_end="2026-05-31T00:00:00Z",
        unit_overrides={"unit_tag": "U-800", "monthly_rate_cents": 18000,
                        "purchase_price_cents": 360000})
    # Advance the logical clock (PRD §2.9) past rental_start so the rental's
    # duration is unambiguously positive under any PRD-faithful reading of
    # "the rental's duration" (elapsed or booked).
    set_clock("2026-05-31T00:00:00Z")
    returned = validate_success(api.confirm_pickup(case["id"], ramp["id"], LC), 200)
    assert returned["status"] == "RETURNED"
    assert returned["actual_pickup"] is not None
    unit_after = validate_success(api.get_inventory_unit(unit["id"], IC), 200)
    assert unit_after["status"] == "AVAILABLE"
    assert unit_after["total_rental_days"] > 0


def test_unit_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."
    "Inventory units are the only top-level resources outside the case hierarchy".

    Design: Corner/errors/unit_not_found_returns_404
    """
    res = api.get_inventory_unit(NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_UNIT_NOT_FOUND, expected_status=404)


def test_ramp_not_found_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/errors/ramp_not_found_returns_404
    """
    case = create_case(client_name="NF Ramp", client_address="55 NF Rd",
                       client_phone="555-0605")
    res = api.get_rental_ramp(case["id"], NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_RAMP_NOT_FOUND, expected_status=404)


def test_inventory_units_filter_by_ramp_type(api):
    """PRD §2.3: "Several list endpoints additionally accept domain filters: the
    case list accepts optional `status` and `funding_posture` filters, the quote
    list and the invoice list each accept an optional `status` filter, and the
    inventory-unit list accepts optional `status` and `ramp_type` filters."

    Design: Corner/endpoints/inventory_units_filter_by_ramp_type
    """
    unit_al = create_inventory_unit(unit_tag="U-F1", ramp_type="MODULAR_ALUMINUM")
    unit_sc = create_inventory_unit(unit_tag="U-F2", ramp_type="SUITCASE")
    data, _ = validate_paginated(api.list_inventory_units(IC, params={"ramp_type": "SUITCASE"}))
    ids = [u["id"] for u in data]
    assert all(u["ramp_type"] == "SUITCASE" for u in data)
    assert unit_sc["id"] in ids
    assert unit_al["id"] not in ids
