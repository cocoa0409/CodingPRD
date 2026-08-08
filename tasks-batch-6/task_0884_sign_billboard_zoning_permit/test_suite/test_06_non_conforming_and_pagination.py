"""Non-conforming amortization valuations and list pagination."""
from test_helpers import (
    validate_paginated,
    make_planner_headers, make_applicant_headers,
    create_parcel, create_applicant, create_application,
    register_non_conforming, list_non_conforming_for_parcel, set_clock,
)


def _find(regs, ncr_id):
    match = [r for r in regs if r["id"] == ncr_id]
    assert match, f"registration {ncr_id} not found in list"
    return match[0]


# ── Dual-variant amortization: straight-line vs declining-balance (Difficulty) ─
def test_straight_line_valuation_at_two_years(api):
    """PRD §3.6: "The **straight-line** valuation, `straight_line_value_cents`, is
    `original_value_cents` multiplied by the remaining fraction of the term — one minus
    elapsed years divided by `amortization_period_years`, with that fraction floored at
    zero so the value never goes negative — then rounded half up to whole cents."
    PRD §3.6: "Let the elapsed time be the number of days between `registered_at` and the
    current instant, divided by 365 to yield elapsed years."

    Design: Difficulty/dual_variant_calc/non_conforming_straight_line_vs_declining
    """
    parcel = create_parcel(api, max_sign_area_sqft=200, allowed_illumination="EXTERNAL", max_signs=3)
    ncr = register_non_conforming(api, parcel["id"], original_value_cents=1000000,
                                  amortization_period_years=5)
    set_clock(api, "2028-04-30T00:00:00Z")  # exactly 730 days = 2.0 years elapsed
    regs = list_non_conforming_for_parcel(api, parcel["id"])
    row = _find(regs, ncr["id"])
    assert row["straight_line_value_cents"] == 600000


def test_declining_balance_valuation_at_two_years(api):
    """PRD §3.6: "The **declining-balance** valuation, `declining_balance_value_cents`, is
    `original_value_cents` multiplied by 0.8 (that is, one minus the decline rate of 0.20)
    raised to the power of the elapsed years, rounded half up to whole cents; because it
    decays geometrically it diverges from the straight-line figure for the same inputs."

    Design: Difficulty/dual_variant_calc/non_conforming_straight_line_vs_declining
    """
    parcel = create_parcel(api, max_sign_area_sqft=200, allowed_illumination="EXTERNAL", max_signs=3)
    ncr = register_non_conforming(api, parcel["id"], original_value_cents=1000000,
                                  amortization_period_years=5)
    set_clock(api, "2028-04-30T00:00:00Z")  # exactly 730 days = 2.0 years elapsed
    regs = list_non_conforming_for_parcel(api, parcel["id"])
    row = _find(regs, ncr["id"])
    assert row["declining_balance_value_cents"] == 640000


# ── Valuation at zero elapsed equals original (Corner) ───────────────────────
def test_valuation_at_zero_elapsed_equals_original(api):
    """PRD §3.6: "The **straight-line** valuation, `straight_line_value_cents`, is
    `original_value_cents` multiplied by the remaining fraction of the term — one minus
    elapsed years divided by `amortization_period_years`, with that fraction floored at
    zero so the value never goes negative — then rounded half up to whole cents."
    PRD §3.6: "The **declining-balance** valuation, `declining_balance_value_cents`, is
    `original_value_cents` multiplied by 0.8 (that is, one minus the decline rate of 0.20)
    raised to the power of the elapsed years, rounded half up to whole cents".

    Design: Corner/calculations/non_conforming_valuation_at_zero_elapsed_equals_original
    """
    parcel = create_parcel(api, max_sign_area_sqft=200, allowed_illumination="EXTERNAL", max_signs=3)
    ncr = register_non_conforming(api, parcel["id"], original_value_cents=1000000,
                                  amortization_period_years=5, description="fresh registry")
    regs = list_non_conforming_for_parcel(api, parcel["id"])
    row = _find(regs, ncr["id"])
    assert row["straight_line_value_cents"] == 1000000
    assert row["declining_balance_value_cents"] == 1000000


# ── List pagination (Corner) ─────────────────────────────────────────────────
def test_list_applications_pagination(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the total
    number of records matching the filter, before pagination), and `has_more` (a boolean
    that is true when records remain beyond the current page) inside the `meta` object."

    Design: Corner/endpoints/list_applications_pagination
    """
    parcel = create_parcel(api)
    applicant = create_applicant(api)
    create_application(api, parcel["id"], applicant["id"], sign_type="WALL",
                       requested_area_sqft=40)
    create_application(api, parcel["id"], applicant["id"], sign_type="MONUMENT",
                       requested_area_sqft=50, requested_height_ft=22, requested_setback_ft=12,
                       requested_illumination="EXTERNAL")
    resp = api.list_applications(
        make_planner_headers(), params={"parcel_id": parcel["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
