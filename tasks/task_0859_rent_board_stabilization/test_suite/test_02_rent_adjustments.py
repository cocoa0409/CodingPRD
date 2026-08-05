"""Allowable-increase rent adjustments: banked vs standard, cap boundary, missing AGA.

Sources: Difficulty/dual_variant_calc, Difficulty/boundary_precision_check, Corner/calculations.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error,
    make_landlord_headers,
    create_rent_adjustment_payload,
    create_landlord, create_unit, publish_aga,
    setup_unit_with_banked_headroom, setup_landlord_and_unit,
)


def test_banked_variant_admits_higher_increase(api):
    """PRD §3.3: "When apply_banked is true (the banked path), the allowable fraction is
    the smaller of two quantities: the sum of that year's aga_pct and the unit's current
    banked_pct, or the banking cap of 0.16 (sixteen percent)..."
    PRD §3.3: "On the banked path, the amount consumed from the bank is the taken fraction
    minus the year's aga_pct, floored at zero; that consumed amount is subtracted from banked_pct"

    Design: Difficulty/dual_variant_calc/allowable_increase_banked_vs_standard
    """
    ctx = setup_unit_with_banked_headroom(api, base_rent_cents=300000)
    lheaders = make_landlord_headers(ctx["landlord_id"])
    version = ctx["unit_after"]["version"]  # version 2 after the 2025 banking adjustment
    data = validate_success(api.create_rent_adjustment(
        ctx["unit_id"],
        create_rent_adjustment_payload("2026-06-01", 324000, True, version),
        lheaders))
    assert data["current_lawful_rent_cents"] == 324000
    assert data["banked_pct"] == 0


def test_standard_variant_caps_below_banked(api):
    """PRD §3.3: "When apply_banked is false (the standard path), the allowable fraction
    is exactly that year's aga_pct."
    PRD §3.3: "a proposed rent above the maximum, or below the prior lawful rent, is
    rejected with ERR_INCREASE_EXCEEDS_ALLOWABLE."

    Design: Difficulty/dual_variant_calc/allowable_increase_banked_vs_standard
    """
    ctx = setup_unit_with_banked_headroom(api, base_rent_cents=300000)
    lheaders = make_landlord_headers(ctx["landlord_id"])
    version = ctx["unit_after"]["version"]
    # Standard path: max = round(300000 * 1.03) = 309000; 324000 exceeds it.
    resp = api.create_rent_adjustment(
        ctx["unit_id"],
        create_rent_adjustment_payload("2026-06-01", 324000, False, version),
        lheaders)
    validate_error(resp, ApiErrorId.ERR_INCREASE_EXCEEDS_ALLOWABLE)


def test_increase_at_exact_cap_accepted(api):
    """PRD §3.3: "The maximum new rent is the prior lawful rent multiplied by one plus the
    allowable fraction, rounded half-up to whole cents."
    PRD §3.3: "A proposed rent equal to the maximum is allowed"

    Design: Difficulty/boundary_precision_check/increase_cap_exact_boundary
    """
    l = create_landlord(api)
    publish_aga(api, 2026, 0.03)
    unit = create_unit(api, l["id"], base_rent_cents=300000, bedrooms=2)
    data = validate_success(api.create_rent_adjustment(
        unit["id"],
        create_rent_adjustment_payload("2026-07-01", 309000, False, unit["version"]),
        make_landlord_headers(l["id"])))
    assert data["current_lawful_rent_cents"] == 309000


def test_increase_one_cent_above_cap_rejected(api):
    """PRD §3.3: "it may not exceed the maximum new rent ... a proposed rent above the
    maximum, or below the prior lawful rent, is rejected with ERR_INCREASE_EXCEEDS_ALLOWABLE."

    Design: Difficulty/boundary_precision_check/increase_cap_exact_boundary
    """
    l = create_landlord(api)
    publish_aga(api, 2026, 0.03)
    unit = create_unit(api, l["id"], base_rent_cents=300000, bedrooms=2)
    resp = api.create_rent_adjustment(
        unit["id"],
        create_rent_adjustment_payload("2026-07-01", 309001, False, unit["version"]),
        make_landlord_headers(l["id"]))
    validate_error(resp, ApiErrorId.ERR_INCREASE_EXCEEDS_ALLOWABLE)


def test_increase_below_prior_rent_rejected(api):
    """PRD §3.3: "it may not fall below the prior lawful rent (this operation only raises
    rent) ... a proposed rent ... below the prior lawful rent, is rejected with
    ERR_INCREASE_EXCEEDS_ALLOWABLE."

    Design: Difficulty/boundary_precision_check/increase_cap_exact_boundary
    """
    l = create_landlord(api)
    publish_aga(api, 2026, 0.03)
    unit = create_unit(api, l["id"], base_rent_cents=300000, bedrooms=2)
    resp = api.create_rent_adjustment(
        unit["id"],
        create_rent_adjustment_payload("2026-07-01", 299999, False, unit["version"]),
        make_landlord_headers(l["id"]))
    validate_error(resp, ApiErrorId.ERR_INCREASE_EXCEEDS_ALLOWABLE)


def test_rent_adjustment_no_aga_for_year(api):
    """PRD §3.3: "The system first selects the Annual General Adjustment whose effective_year
    equals the calendar year of the effective_date. If no adjustment has been published for
    that year, the request is rejected with ERR_NO_AGA_DETERMINATION."

    Design: Corner/calculations/rent_adjustment_no_aga_for_year
    """
    base = setup_landlord_and_unit(api)  # no AGA published for 2030
    unit = base["unit"]
    resp = api.create_rent_adjustment(
        unit["id"],
        create_rent_adjustment_payload("2030-06-01", 309000, False, unit["version"]),
        make_landlord_headers(base["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_NO_AGA_DETERMINATION)
