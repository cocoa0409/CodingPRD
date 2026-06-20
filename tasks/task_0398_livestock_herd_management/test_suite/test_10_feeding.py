"""Feed ration waterfall allocation (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_ration,
    TEST_USERS,
)

FEED = TEST_USERS["feedlot_operator_headers"]


class TestRationWaterfall:
    def test_grower_ration_total_as_fed(self, api):
        """PRD §3.7: "For every ingredient except the last, the dry-matter allocated to
        that ingredient is the smaller of two quantities: that ingredient's
        `max_inclusion_pct` multiplied by the ration's `target_dmi_kg`, and whatever
        dry-matter budget remains."
        PRD §3.7: "The last ingredient is the filler: it absorbs whatever dry-matter
        budget remains after all earlier ingredients have taken their share".
        PRD §3.7: "The `total_as_fed_kg` is the sum of the per-ingredient as-fed
        quantities, rounded to three decimal places."

        Design: Corner/calculations/ration_waterfall_allocation_grower
        """
        set_clock("2026-04-01T00:00:00Z", headers=FEED)
        ration = create_ration(
            target_dmi_kg=10.0,
            ingredients=[
                {"feedstuff": "CORN_SILAGE", "dry_matter_pct": 0.35,
                 "max_inclusion_pct": 0.50, "cost_per_kg_as_fed": 0.05},
                {"feedstuff": "ALFALFA_HAY", "dry_matter_pct": 0.88,
                 "max_inclusion_pct": 0.30, "cost_per_kg_as_fed": 0.18},
                {"feedstuff": "GRAIN_MIX", "dry_matter_pct": 0.90,
                 "max_inclusion_pct": 1.00, "cost_per_kg_as_fed": 0.22},
            ],
            name="GROWER",
        )
        computed = validate_success(api.get_computed_ration(ration["id"], FEED))
        assert computed["total_as_fed_kg"] == 19.917, (
            f"filler-absorbed waterfall total should be 19.917, "
            f"got {computed['total_as_fed_kg']}"
        )
