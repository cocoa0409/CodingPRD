"""The two-pass customer impact model that runs when a candidate program is approved.

The separation between the passes is the whole point: the volume tier is chosen
from undiscounted gross revenue, then the contract discount and that tier are
applied. Choosing the tier from discounted revenue lands in a different bracket
and produces a different recommendation.
"""

import pytest

from test_helpers import assert_rate_program, assert_shipment_line
from test_helpers import fixtures as fx

MODEL_CLOCK = "2026-02-01T00:00:00Z"

HEAVY_LINE = {
    "line_no": 1,
    "declared_class_code": 110,
    "declared_weight_lb": 14000,
    "pieces": 9,
    "declared_length_in": 96.0,
    "declared_width_in": 48.0,
    "declared_height_in": 60.0,
}


def _migration_scenario():
    """One billed 14,000-pound shipment under a 3000 c/cwt class-based program, plus a
    drafted density-based candidate at 4200 c/cwt."""
    env = fx.setup_pricing_environment(
        clock=MODEL_CLOCK,
        terminal_overrides={"code": "TRM2", "name": "Dallas Dock"},
        customer_overrides={"account_code": "HAUL", "name": "Haul Industries"},
        profile_overrides={
            "nmfc_item": "086000",
            "description": "Insulation board, palletised",
        },
        program_overrides={
            "program_type": "CLASS_BASED",
            "base_rate_per_cwt_cents": 3000,
            "discount_pct": 0.20,
            "min_charge_cents": 12500,
        },
    )
    scenario = fx.setup_billed_shipment(
        env=env,
        pro_number="PRO4001",
        line_specs=[HEAVY_LINE],
        shipment_overrides={
            "pickup_at": MODEL_CLOCK,
            "bol_declared_total_weight_lb": 14000,
        },
    )
    scenario["candidate"] = fx.create_rate_program(
        scenario["customer_id"],
        program_type="DENSITY_BASED",
        base_rate_per_cwt_cents=4200,
        discount_pct=0.35,
        min_charge_cents=12500,
    )
    scenario["candidate_id"] = scenario["candidate"]["id"]
    return scenario


def test_approval_pins_the_standard_and_measures_the_billed_history():
    """The baseline is the sum of assessed totals over the shipper's billed freight.

    PRD: "Its shipment set is every shipment of the program's shipper whose
    `billing_status` is `BILLED`, `REBILLED`, `CREDITED` or `CLOSED`, iterated in
    ascending `created_at`; shipments still `UNBILLED` are excluded from both the
    baseline and the model."

    Design: Difficulty/combinatorial_formula/migration_model_two_pass_volume_tier_from_undiscounted_gross
    """
    scenario = _migration_scenario()

    approved = fx.approve_rate_program(scenario["candidate_id"])
    line = fx.get_shipment_line(scenario["line_ids"][0])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert_rate_program(approved)
    assert_shipment_line(line)
    assert approved["status"] == "APPROVED"
    assert approved["pinned_tariff_version_id"] == scenario["tariff_version_id"], (
        "approval pins the newest published release"
    )
    assert approved["modeled_shipment_count"] == 1
    assert approved["baseline_revenue_cents"] == 288288
    assert line["declared_cubic_ft"] == 1440.00, (
        f"nine 96.0 x 48.0 x 60.0 units cube to 1440.00, got {line['declared_cubic_ft']}"
    )
    assert line["declared_density_pcf"] == 9.72
    assert shipment["assessed_total_cents"] == 288288


def test_the_volume_tier_comes_from_the_undiscounted_first_pass_gross():
    """Only the undiscounted 504504 reaches the 4 percent tier; the discounted
    revenue would have fallen into the 0 percent tier.

    PRD: "The volume tier is derived once, from the first pass's undiscounted
    gross; it is never re-derived from the discounted second-pass revenue, and the
    model never iterates toward a fixed point."

    Design: Difficulty/combinatorial_formula/migration_model_two_pass_volume_tier_from_undiscounted_gross
    """
    scenario = _migration_scenario()

    approved = fx.approve_rate_program(scenario["candidate_id"])

    assert approved["modeled_annual_revenue_cents"] == 314810, (
        f"327928 discounted revenue less the 4 percent volume tier is 314810, "
        f"got {approved['modeled_annual_revenue_cents']}"
    )
    assert approved["modeled_annual_revenue_cents"] != 327928, (
        "selecting the tier from the discounted pass would have left 327928 untouched"
    )


def test_the_recommendation_follows_the_four_decimal_modelled_delta():
    """A 9.2 percent modelled increase clears the 5 percent bar for migration.

    PRD: "The `migration_recommendation` follows directly:
    `MIGRATE_DENSITY_BASED` when the delta is at least 0.05, `HOLD_CLASS_BASED`
    when the delta is at most -0.05, and `NEGOTIATE_FAK` for anything strictly
    between those two bounds."

    Design: Difficulty/combinatorial_formula/migration_model_two_pass_volume_tier_from_undiscounted_gross
    """
    scenario = _migration_scenario()

    approved = fx.approve_rate_program(scenario["candidate_id"])
    incumbent = fx.get_rate_program(scenario["rate_program_id"])

    assert approved["modeled_delta_pct"] == pytest.approx(0.0920, abs=0.00005), (
        f"26522 over a 288288 baseline is 0.0920 at four decimal places, "
        f"got {approved['modeled_delta_pct']}"
    )
    assert approved["migration_recommendation"] == "MIGRATE_DENSITY_BASED"
    assert incumbent["status"] == "ACTIVE", (
        "modelling a candidate does not disturb the program actually in force"
    )
