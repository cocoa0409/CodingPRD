"""Spare selector scoring (PRD §3.7): multi-term ranking expression and the
created_at-ascending tie-break among equally scored units."""
from test_helpers import (
    api_client,
    create_spare_unit,
    validate_success,
)
from test_helpers import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]
OPS = TEST_USERS["ops_manager_headers"]

REQUEST = dict(
    unit_type="SPARE_TRANSFORMER",
    required_mva=20,
    required_voltage_kv=115,
    preferred_impedance_pct=6.0,
    site_location="Yard-A",
    start_ts="2026-09-10T10:00:00Z",
    end_ts="2026-09-10T14:00:00Z",
)


def _setup_three_units() -> dict:
    # U1: 25 MVA, impedance 7.0, Yard-B  -> 100*min(1,1.25) + 25*(1-1/4) + 0 = 118.75
    # U2: 20 MVA, impedance 6.0, Yard-A  -> 100*1 + 25*1 + 10 = 135.00 (created 2nd)
    # U3: 40 MVA, impedance 6.0, Yard-A  -> 100*1 + 25*1 + 10 = 135.00 (created 3rd)
    unit1 = create_spare_unit(rating_mva=25, impedance_pct=7.0, home_location="Yard-B")
    unit2 = create_spare_unit(rating_mva=20, impedance_pct=6.0, home_location="Yard-A")
    unit3 = create_spare_unit(rating_mva=40, impedance_pct=6.0, home_location="Yard-A")
    return {"unit1": unit1, "unit2": unit2, "unit3": unit3}


class TestSpareSelectorScoring:
    def test_selector_picks_highest_score_and_reserves_unit(self):
        """PRD §3.7: "The ranking score is the sum of three terms: an adequacy
        term of 100 times the lesser of 1.0 and the unit's `rating_mva` divided
        by `required_mva`; an impedance term that is 0 when
        `preferred_impedance_pct` is not supplied and otherwise 25 times the
        greater of 0 and one minus the absolute difference between the unit's
        `impedance_pct` and `preferred_impedance_pct` divided by 4.0; and a
        location term of 10 when `site_location` is supplied and equals the
        unit's `home_location`, else 0. Higher score wins; ties break by the
        unit's `created_at` ascending."
        PRD §3.7: "A successful reservation arrives `ACTIVE` and drives its
        unit from `AVAILABLE` to `RESERVED`."

        Design: Difficulty/combinatorial_formula/spare_selector_scoring_mode_a
        """
        units = _setup_three_units()
        reservation = validate_success(
            api_client.create_spare_reservation(REQUEST, COORD), 201
        )
        assert reservation["spare_unit_id"] == units["unit2"]["id"]
        assert reservation["status"] == "ACTIVE"
        unit2 = validate_success(api_client.get_spare_unit(units["unit2"]["id"], OPS))
        assert unit2["status"] == "RESERVED"

    def test_selector_tie_broken_by_earliest_created_unit(self):
        """PRD §3.7: "Higher score wins; ties break by the unit's `created_at`
        ascending."
        PRD §3.7: "When `spare_unit_id` is omitted, the platform selects a unit
        by score."

        Design: Difficulty/combinatorial_formula/spare_selector_scoring_mode_a
        """
        units = _setup_three_units()
        reservation = validate_success(
            api_client.create_spare_reservation(REQUEST, COORD), 201
        )
        # U2 and U3 score identically (135.00); the earlier-created U2 wins.
        assert reservation["spare_unit_id"] == units["unit2"]["id"]
        assert reservation["spare_unit_id"] != units["unit3"]["id"]
        # The lower-scored U1 (118.75) must never win over the tied 135.00 pair.
        assert reservation["spare_unit_id"] != units["unit1"]["id"]
