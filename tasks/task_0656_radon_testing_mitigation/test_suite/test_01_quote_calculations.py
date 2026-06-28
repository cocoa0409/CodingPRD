"""Mitigation-quote pricing: tiered foundation/area/points/sump base, the
pinned rush-surcharge-off-subtotal evaluation order, and the 30% deposit.

Each test reaches a QUOTED job and asserts the literal cents the PRD's quote
formula pins.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_designed_job, DESIGNER,
)


def test_quote_basement_tier2_three_points_with_sump(api):
    """PRD §3.4: "a base price is selected by the property's `foundation_type`:
    a slab foundation bases at 150000 cents, a basement at 185000 cents, and a
    crawlspace at 240000 cents."
    PRD §3.4: "the number of suction points beyond the first — that is,
    `num_suction_points` minus 1, but never less than zero — multiplied by 45000
    cents per additional point."
    PRD §3.4: "a sump-seal fee of 32000 cents is added when `has_sump_pump` is
    true, and zero otherwise."
    PRD §3.4: "an area greater than 1500 but at most 3000 square feet adds 50000
    cents."

    Design: Difficulty/combinatorial_formula/cf_quote_tiered_nonlinear_three_plus_inputs
    """
    _, _, _, job = setup_designed_job(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        job_overrides={"num_suction_points": 3, "has_sump_pump": True,
                       "is_rush": False})
    quoted = validate_success(api.quote_job(job["id"], DESIGNER), 200)
    # 185000 + 2*45000 + 32000 + 50000 = 357000
    assert quoted["quote_subtotal_cents"] == 357000
    assert quoted["rush_surcharge_cents"] == 0
    assert quoted["quote_total_cents"] == 357000
    assert quoted["deposit_required_cents"] == 107100


def test_quote_standard_no_rush_surcharge_and_deposit_off_subtotal(api):
    """PRD §3.4: "The `rush_surcharge_cents` is then 15 percent of the subtotal,
    rounded half up, when `is_rush` is true, and zero when it is false."
    PRD §3.4: "the `deposit_required_cents` is 30 percent of the
    `quote_total_cents`, rounded half up."

    Design: Difficulty/combinatorial_formula/cf_quote_tiered_nonlinear_three_plus_inputs
    """
    _, _, _, job = setup_designed_job(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        job_overrides={"num_suction_points": 3, "has_sump_pump": True,
                       "is_rush": False})
    quoted = validate_success(api.quote_job(job["id"], DESIGNER), 200)
    assert quoted["rush_surcharge_cents"] == 0
    assert quoted["quote_total_cents"] == 357000
    # 30% of 357000 = 107100
    assert quoted["deposit_required_cents"] == 107100


def test_quote_rush_surcharge_keyed_off_resolved_subtotal(api):
    """PRD §3.4: "The evaluation order is fixed, because the rush surcharge keys
    off the resolved subtotal and must not be computed until the subtotal is
    final."
    PRD §3.4: "The `rush_surcharge_cents` is then 15 percent of the subtotal,
    rounded half up, when `is_rush` is true, and zero when it is false."

    Design: Difficulty/combinatorial_formula/cf_quote_rush_surcharge_keyed_off_subtotal_order_pinned
    """
    _, _, _, job = setup_designed_job(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        is_real_estate_transaction=True,
        closing_deadline_utc="2026-05-01T00:00:00Z",
        job_overrides={"num_suction_points": 3, "has_sump_pump": True,
                       "is_rush": True})
    quoted = validate_success(api.quote_job(job["id"], DESIGNER), 200)
    assert quoted["quote_subtotal_cents"] == 357000
    # 15% of 357000 = 53550
    assert quoted["rush_surcharge_cents"] == 53550
    assert quoted["quote_total_cents"] == 410550


def test_quote_rush_total_drives_thirty_percent_deposit(api):
    """PRD §3.4: "The `quote_total_cents` is the subtotal plus the rush
    surcharge."
    PRD §3.4: "the `deposit_required_cents` is 30 percent of the
    `quote_total_cents`, rounded half up."

    Design: Difficulty/combinatorial_formula/cf_quote_rush_surcharge_keyed_off_subtotal_order_pinned
    """
    _, _, _, job = setup_designed_job(
        foundation_type="BASEMENT", floor_area_sqft=2200,
        is_real_estate_transaction=True,
        closing_deadline_utc="2026-05-01T00:00:00Z",
        job_overrides={"num_suction_points": 3, "has_sump_pump": True,
                       "is_rush": True})
    quoted = validate_success(api.quote_job(job["id"], DESIGNER), 200)
    assert quoted["quote_total_cents"] == 410550
    # 30% of 410550 = 123165
    assert quoted["deposit_required_cents"] == 123165


def test_quote_crawlspace_tier3_constants_applied(api):
    """PRD §3.4: "a base price is selected by the property's `foundation_type`:
    a slab foundation bases at 150000 cents, a basement at 185000 cents, and a
    crawlspace at 240000 cents."
    PRD §3.4: "an area greater than 3000 square feet adds 120000 cents."

    Design: Corner/calculations/calc_quote_area_tier3_crawlspace
    """
    _, _, _, job = setup_designed_job(
        foundation_type="CRAWLSPACE", floor_area_sqft=3500, lab_result=8.0,
        job_overrides={"system_design": "SUB_MEMBRANE_DEPRESSURIZATION",
                       "num_suction_points": 2, "has_sump_pump": False,
                       "is_rush": False})
    quoted = validate_success(api.quote_job(job["id"], DESIGNER), 200)
    # 240000 + 1*45000 + 0 + 120000 = 405000
    assert quoted["quote_subtotal_cents"] == 405000
    assert quoted["quote_total_cents"] == 405000
    # 30% of 405000 = 121500
    assert quoted["deposit_required_cents"] == 121500
