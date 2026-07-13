"""Annual emissions inventory: totals, tiered fees, certification, and the fee
ledger invariant.

Covers the estimated-vs-assessed fee variants, the marginal tier selection, the
sum-then-round total, the unresolved-exceedance certify gate, the certify/amend
compensation, and the inventory validation corners.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    register_facility, setup_facility_with_source, create_inventory, add_line_item,
    setup_submitted_inventory, certify_inventory, create_exceedance,
    current_facility_version, make_facility_operator_headers, TEST_USERS, api_client,
)

REVIEWER = TEST_USERS["permit_reviewer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ─── dual_variant_calc / emissions_fee_estimated_vs_assessed ───

def test_assessed_fee_adds_late_surcharge_over_estimated(api):
    """PRD §3.8: "The provisional estimated_fee_cents computed at submission stops
    here. The final assessed_fee_cents, computed at certification, applies one
    further step in this order: if the inventory's certified_at is at or after its
    due_at, a 15% late surcharge is applied, multiplying the amount by 1.15 and
    rounding half-up to whole cents."

    Design: Difficulty/dual_variant_calc/emissions_fee_estimated_vs_assessed
    """
    facility, source = setup_facility_with_source("Acme Co", max_hourly_rate_lbs=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [60.000],
                                    reporting_year=2025, due_at="2026-04-01T00:00:00Z")
    assert inv["estimated_fee_cents"] == 252500
    validate_success(api.set_clock("2026-05-01T00:00:00Z", REVIEWER), 200)
    certified = certify_inventory(facility["id"], inv["id"])
    assert certified["assessed_fee_cents"] == 290375


def test_assessed_fee_equals_estimated_when_on_time(api):
    """PRD §3.8: "if the inventory's certified_at is at or after its due_at, a 15%
    late surcharge is applied, multiplying the amount by 1.15 and rounding half-up
    to whole cents."

    Design: Difficulty/dual_variant_calc/emissions_fee_estimated_vs_assessed
    """
    facility, source = setup_facility_with_source("Acme OnTime Co", max_hourly_rate_lbs=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [60.000],
                                    reporting_year=2025, due_at="2026-04-01T00:00:00Z")
    assert inv["estimated_fee_cents"] == 252500
    certified = certify_inventory(facility["id"], inv["id"])
    assert certified["assessed_fee_cents"] == 252500


# ─── combinatorial_formula / emissions_fee_marginal_tier_selection ───

def test_fee_spans_first_two_tiers_at_100_tons(api):
    """PRD §3.8: "The first 25 tons are charged at 4,500 cents per ton; the next 75
    tons — the portion above 25 tons and up to 100 tons — at 4,000 cents per ton;
    and every ton above 100 tons at 3,500 cents per ton."

    Design: Difficulty/combinatorial_formula/emissions_fee_marginal_tier_selection
    """
    facility, source = setup_facility_with_source("Bravo Co", source_type="GENERATOR",
                                                  pollutant="CO", max_hourly_rate_lbs=300)
    inv = setup_submitted_inventory(facility["id"], source["id"], [100.000])
    assert inv["total_emissions_tons"] == 100.0
    assert inv["estimated_fee_cents"] == 412500


def test_fee_reaches_third_tier_above_100_tons(api):
    """PRD §3.8: "The first 25 tons are charged at 4,500 cents per ton; the next 75
    tons — the portion above 25 tons and up to 100 tons — at 4,000 cents per ton;
    and every ton above 100 tons at 3,500 cents per ton."

    Design: Difficulty/combinatorial_formula/emissions_fee_marginal_tier_selection
    """
    facility, source = setup_facility_with_source("Bravo Tier3 Co", source_type="GENERATOR",
                                                  pollutant="CO", max_hourly_rate_lbs=300)
    inv = setup_submitted_inventory(facility["id"], source["id"], [150.000])
    assert inv["total_emissions_tons"] == 150.0
    assert inv["estimated_fee_cents"] == 587500


# ─── combinatorial_formula / inventory_total_sum_then_round ───

def test_inventory_total_sums_before_rounding(api):
    """PRD §3.8: "The total emissions are the sum of every line item's reported_tons
    for the inventory, summed first and only then rounded half-up to two decimal
    places — the individual line items are never rounded to two decimals before
    summing."

    Design: Difficulty/combinatorial_formula/inventory_total_sum_then_round
    """
    facility, source = setup_facility_with_source("Charlie Co", source_type="FLARE",
                                                  pollutant="VOC", max_hourly_rate_lbs=20,
                                                  permit_limit_ppm=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [21.005, 21.005, 21.005])
    assert inv["total_emissions_tons"] == 63.02


def test_inventory_total_sum_then_round_carries_third_decimal(api):
    """PRD §3.8: "The total emissions are the sum of every line item's reported_tons
    for the inventory, summed first and only then rounded half-up to two decimal
    places — the individual line items are never rounded to two decimals before
    summing."

    Design: Difficulty/combinatorial_formula/inventory_total_sum_then_round
    """
    facility, source = setup_facility_with_source("Charlie Carry Co", source_type="FLARE",
                                                  pollutant="VOC", max_hourly_rate_lbs=20,
                                                  permit_limit_ppm=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [0.336, 0.336, 0.336])
    assert inv["total_emissions_tons"] == 1.01


# ─── cross_entity_state_dependency / certify_requires_no_open_exceedance_on_sources ───

def test_certify_blocked_by_open_exceedance(api):
    """PRD §3.8: "only when no emission source referenced by the inventory's line
    items has an OPEN or REPORTED_LATE exceedance event (otherwise
    ERR_UNRESOLVED_EXCEEDANCE)."

    Design: Difficulty/cross_entity_state_dependency/certify_requires_no_open_exceedance_on_sources
    """
    facility, source = setup_facility_with_source("Mike Co", max_hourly_rate_lbs=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [10.000])
    create_exceedance(source["id"], detected_at="2026-03-01T00:00:00Z",
                      event_type="EXCEEDANCE", magnitude_pct=5)
    res = api.certify_inventory(
        inv["id"], {"expected_facility_version": current_facility_version(facility["id"])}, REVIEWER)
    validate_error(res, "ERR_UNRESOLVED_EXCEEDANCE")


def test_certify_succeeds_once_exceedance_reported(api):
    """PRD §3.8: "only when no emission source referenced by the inventory's line
    items has an OPEN or REPORTED_LATE exceedance event (otherwise
    ERR_UNRESOLVED_EXCEEDANCE)." PRD §3.5: "If the logical clock is at or before 72
    hours past detected_at, the event moves OPEN → REPORTED".

    Design: Difficulty/cross_entity_state_dependency/certify_requires_no_open_exceedance_on_sources
    """
    facility, source = setup_facility_with_source("Mike Clear Co", max_hourly_rate_lbs=50)
    op = make_facility_operator_headers(facility["id"])
    inv = setup_submitted_inventory(facility["id"], source["id"], [10.000])
    exc = create_exceedance(source["id"], detected_at="2026-03-01T00:00:00Z",
                            event_type="EXCEEDANCE", magnitude_pct=5)
    validate_success(api.report_exceedance(exc["id"], op), 200)
    certified = certify_inventory(facility["id"], inv["id"])
    assert certified["status"] == "CERTIFIED"


# ─── compensating_invariant / fee_balance_certify_then_amend_nets_to_zero ───

def test_fee_balance_returns_to_zero_after_amend(api):
    """PRD §3.8: "amendment moves the inventory CERTIFIED → AMENDED, decreases the
    facility's fee_balance_cents by exactly that inventory's assessed_fee_cents —
    reversing the certify debit and restoring the ledger invariant — and resets the
    inventory's assessed_fee_cents to 0."

    Design: Difficulty/compensating_invariant/fee_balance_certify_then_amend_nets_to_zero
    """
    facility, source = setup_facility_with_source("Papa Co", max_hourly_rate_lbs=50)
    op = make_facility_operator_headers(facility["id"])
    inv = setup_submitted_inventory(facility["id"], source["id"], [30.000])
    certify_inventory(facility["id"], inv["id"])
    amended = validate_success(api.amend_inventory(inv["id"], op), 200)
    assert amended["assessed_fee_cents"] == 0
    fac = validate_success(api.get_facility(facility["id"], op), 200)
    assert fac["fee_balance_cents"] == 0


def test_fee_balance_reflects_assessed_fee_after_certify(api):
    """PRD §2.8: "certifying an inventory increases the balance by that inventory's
    assessed fee, and amending a certified inventory reverses exactly that debit."

    Design: Difficulty/compensating_invariant/fee_balance_certify_then_amend_nets_to_zero
    """
    facility, source = setup_facility_with_source("Papa Debit Co", max_hourly_rate_lbs=50)
    op = make_facility_operator_headers(facility["id"])
    inv = setup_submitted_inventory(facility["id"], source["id"], [30.000])
    certified = certify_inventory(facility["id"], inv["id"])
    assert certified["assessed_fee_cents"] == 132500
    fac = validate_success(api.get_facility(facility["id"], op), 200)
    assert fac["fee_balance_cents"] == 132500


# ─── calculations corner ───

def test_fee_small_emitter_discount_applied(api):
    """PRD §3.8: "Next, if the resulting amount is below 100,000 cents, a
    small-emitter discount reduces it to 90% of its value (a 10% reduction),
    rounded half-up to whole cents."

    Design: Corner/calculations/fee_small_emitter_discount_applied
    """
    facility, source = setup_facility_with_source("Delta2 Co", max_hourly_rate_lbs=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [15.000])
    assert inv["estimated_fee_cents"] == 60750


# ─── validations & state_machines corner ───

def test_duplicate_reporting_year_rejected(api):
    """PRD §3.8: "The reporting year must be unique per facility; a second inventory
    for the same facility and reporting_year is rejected with
    ERR_DUPLICATE_INVENTORY_YEAR."

    Design: Corner/validations/duplicate_inventory_year_returns_error
    """
    facility = register_facility(name="Kilo2 Co")
    op = make_facility_operator_headers(facility["id"])
    create_inventory(facility["id"], reporting_year=2025)
    res = api.create_inventory(
        {"facility_id": facility["id"], "reporting_year": 2025, "due_at": "2026-12-31T00:00:00Z"}, op)
    validate_error(res, "ERR_DUPLICATE_INVENTORY_YEAR")


def test_submit_without_line_items_rejected(api):
    """PRD §3.8: "Submitting an inventory requires it to be DRAFT and to have at
    least one line item — a submit with zero line items is rejected with
    ERR_NO_LINE_ITEMS."

    Design: Corner/validations/submit_without_line_items_returns_error
    """
    facility = register_facility(name="Lima2 Co")
    op = make_facility_operator_headers(facility["id"])
    inv = create_inventory(facility["id"], reporting_year=2025)
    res = api.submit_inventory(inv["id"], op)
    validate_error(res, "ERR_NO_LINE_ITEMS")


def test_certify_draft_inventory_reports_invalid_state(api):
    """PRD §3.8: "Certifying an inventory ... is allowed only while the inventory is
    SUBMITTED". PRD §2.10: "(5) the target resource is in a state that permits the
    requested transition, else ERR_INVALID_STATE (409)".

    Design: Corner/state_machines/certify_from_draft_returns_invalid_state
    """
    facility, source = setup_facility_with_source("Yankee Co", max_hourly_rate_lbs=50)
    inv = create_inventory(facility["id"], reporting_year=2025)
    add_line_item(facility["id"], inv["id"], source["id"], 10.000)
    res = api.certify_inventory(
        inv["id"], {"expected_facility_version": current_facility_version(facility["id"])}, REVIEWER)
    validate_error(res, "ERR_INVALID_STATE")


def test_reject_returns_inventory_to_draft(api):
    """PRD §3.8: "A PermitReviewer may reject a submitted inventory, returning it
    SUBMITTED → DRAFT for correction."

    Design: Corner/state_machines/inventory_reject_returns_to_draft
    """
    facility, source = setup_facility_with_source("Alpha2 Co", max_hourly_rate_lbs=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [10.000])
    rejected = validate_success(api.reject_inventory(inv["id"], REVIEWER), 200)
    assert rejected["status"] == "DRAFT"


# ─── endpoints corner ───

def test_line_items_filtered_by_source_id(api):
    """PRD §3.8: "line items may be listed and filtered by inventory_id and by
    source_id."

    Design: Corner/endpoints/line_items_filtered_by_source_id
    """
    facility, source = setup_facility_with_source("Oscar2 Co", max_hourly_rate_lbs=50)
    op = make_facility_operator_headers(facility["id"])
    inv = create_inventory(facility["id"], reporting_year=2025)
    add_line_item(facility["id"], inv["id"], source["id"], 10.000)
    data, meta = validate_paginated(api.list_line_items(op, params={"source_id": source["id"]}))
    assert meta["total_count"] == 1
