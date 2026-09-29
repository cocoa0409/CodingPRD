"""Read-your-writes behaviour of the hazardous waste TSDF API.

Nothing in this system settles later: an operation with consequences beyond the
row it names returns only once those consequences are in place, so the creating
response and an immediate follow-up read tell the same story.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_cents,
    assert_mass,
    assert_ratio,
    factories,
    fixtures,
)


class TestPlacementConsistency:
    """Placing a drum settles the unit, the receipt line and the money at once."""

    def test_placement_response_already_carries_every_derived_consequence(self):
        """A 900.0 kg tote into a 1000.0 kg unit comes back with its own derived
        figures settled, and the unit, line and assurance figures it moves are
        already settled too — with nothing shifting on a repeat read.

        "When an operation has consequences beyond the row it names, every consequence is applied before the response is returned, and each affected row's `updated_at` and `version` advance as part of the same request."
        "The **headspace rule** requires `net_weight_kg` to be no greater than 95 percent of `capacity_kg`, and the container's `fill_ratio` — `net_weight_kg` divided by `capacity_kg`, carried to 4 decimals — is exposed so the margin is visible."
        "Otherwise it is `RESTRICTED` when any container in the unit is `DEFICIENT`, or when `utilization_pct` reaches or exceeds 0.9000 — the utilisation threshold is inclusive, so a unit sitting at exactly 0.9000 is restricted."
        "`closure_base_cost_cents` is 25,000,000 cents of fixed closure overhead plus 1,800 cents for every kilogram of `held_mass_kg`, that per-kilogram product being rounded half up to whole cents before it is added to the fixed component."

        Design: Corner/consistency model/container_placement_response_already_shows_every_derived_consequence
        """
        scenario = fixtures.setup_received_manifest(
            unit_overrides={"permitted_capacity_kg": 1000.0},
            declared_quantity_kg=2000.0,
            declared_container_count=8,
        )

        response = api_client.create_container(
            factories.container_payload(
                scenario.line["id"],
                scenario.unit["id"],
                net_weight_kg=900.0,
                capacity_kg=1000.0,
                container_type="TOTE",
            ),
            TEST_USERS["clerk"],
        )
        container = validate_success(response, expected_status=201)

        # The drum's own derived figures come back with the creation.
        assert container["custody_state"] == "FILLING"
        assert container["compliance_state"] == "COMPLIANT"
        assert_mass(container["net_weight_kg"], 900.0, "net_weight_kg")
        assert_ratio(container["fill_ratio"], 0.9000, "fill_ratio")
        assert container["accumulation_days"] == 0
        assert container["ten_day_overdue"] is False

        # The unit it entered is already restricted at exactly 0.9000.
        unit = fixtures.read_unit(scenario.unit["id"])
        assert unit["container_count"] == 1
        assert_mass(unit["stored_kg"], 900.0, "stored_kg")
        assert_ratio(unit["utilization_pct"], 0.9000, "utilization_pct")
        assert unit["posture"] == "RESTRICTED"

        # The receipt line it drew on has already given up the mass.
        line = fixtures.read_line(scenario.manifest["id"], 1)
        assert_mass(
            line["allocated_container_mass_kg"], 900.0, "allocated_container_mass_kg"
        )

        # And the money has already been repriced off the new held mass:
        # 25,000,000 + 1,800 x 900 = 26,620,000 at TIER_1, surcharged 5 percent
        # to 27,951,000, plus 8,000,000 of post-closure cost.
        summary = fixtures.read_assurance_summary(scenario.facility["id"])
        assert_mass(summary["held_mass_kg"], 900.0, "held_mass_kg")
        assert_cents(
            summary["closure_base_cost_cents"], 26_620_000, "closure_base_cost_cents"
        )
        assert summary["assurance_tier"] == "TIER_1"
        assert_cents(
            summary["closure_cost_estimate_cents"],
            27_951_000,
            "closure_cost_estimate_cents",
        )
        assert_cents(
            summary["required_assurance_cents"], 35_951_000, "required_assurance_cents"
        )
        assert_cents(summary["assurance_shortfall_cents"], 0, "assurance_shortfall_cents")
        assert_mass(summary["mass_ledger_kg"], 2000.0, "mass_ledger_kg")

        # Reading again at the same clock instant settles nothing further.
        unit_again = fixtures.read_unit(scenario.unit["id"])
        for field in ("container_count", "stored_kg", "utilization_pct", "posture"):
            assert unit_again[field] == unit[field], field

        summary_again = fixtures.read_assurance_summary(scenario.facility["id"])
        for field in (
            "held_mass_kg",
            "closure_base_cost_cents",
            "assurance_tier",
            "closure_cost_estimate_cents",
            "required_assurance_cents",
            "assurance_shortfall_cents",
            "mass_ledger_kg",
        ):
            assert summary_again[field] == summary[field], field
