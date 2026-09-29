"""Two inclusive/exclusive boundaries, probed one unit either side.

The ranking cut-off is inclusive and the impervious comparison is strict, so the
two boundaries land on opposite sides of the same kind of off-by-one mistake.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    complete_visit,
    create_parcel,
    file_application,
    read_application,
    read_easement,
    read_parcel,
    record_impervious,
    schedule_visit,
    set_clock,
    setup_program_with_round,
    setup_recorded_easement,
)

ADMIN = TEST_USERS["program_admin_headers"]
MONITOR = TEST_USERS["stewardship_monitor_headers"]

# A parcel shaped so that only the prime-soil acreage moves the composite score:
# 200 acres gives the full size component, 200 contiguous acres the full
# contiguity component, and no frontage, no sewer and a 10-acre minimum lot
# leave the pressure component at its floor of 5.00.
_FLAT_PARCEL = {
    "acres": 200.00,
    "statewide_important_soil_acres": 0.00,
    "contiguous_preserved_acres": 200.00,
    "road_frontage_feet": 0,
    "sewer_available": False,
    "zoning_min_lot_acres": 10.00,
    "unrestricted_value_cents": 400_000_000,
    "restricted_value_cents": 150_000_000,
}

# Four equal weights, so the composite is the plain mean of the four components.
_EQUAL_WEIGHTS = {
    "soil_weight": 0.25,
    "size_weight": 0.25,
    "contiguity_weight": 0.25,
    "pressure_weight": 0.25,
}


def _rank_two_parcels_at_the_cut_off() -> dict:
    """File one application scoring exactly 60.00 and one scoring 59.99."""
    scenario = setup_program_with_round(program_overrides=_EQUAL_WEIGHTS)
    landowner_id = scenario["landowner"]["id"]

    # 70.00 prime acres of 200 gives a soil score of 35.00 and a mean of 60.00.
    at_cut_off = create_parcel(
        landowner_id, county="Snyder", prime_soil_acres=70.00, **_FLAT_PARCEL
    )
    # 69.92 prime acres gives 34.96 and a mean of 59.99.
    below_cut_off = create_parcel(
        landowner_id, county="Juniata", prime_soil_acres=69.92, **_FLAT_PARCEL
    )
    assert at_cut_off["soil_quality_score"] == pytest.approx(35.00, abs=0.01)
    assert below_cut_off["soil_quality_score"] == pytest.approx(34.96, abs=0.01)
    assert at_cut_off["development_pressure_score"] == pytest.approx(5.00, abs=0.01)

    scenario["at_cut_off"] = {
        "parcel": at_cut_off,
        "application": file_application(
            scenario["round"]["id"],
            at_cut_off["id"],
            landowner_id,
            requested_price_cents=200_000_000,
        ),
    }
    scenario["below_cut_off"] = {
        "parcel": below_cut_off,
        "application": file_application(
            scenario["round"]["id"],
            below_cut_off["id"],
            landowner_id,
            requested_price_cents=200_000_000,
        ),
    }
    set_clock("2026-10-01T00:00:00Z")
    scenario["rank_result"] = validate_success(
        api_client.rank_funding_round(
            scenario["round"]["id"], {"score_basis": "RECEIPT_BASIS"}, ADMIN
        )
    )
    return scenario


class TestCompositeScoreCutOff:
    """`min_composite_score` of 60.00 is an inclusive cut-off."""

    def test_a_composite_of_exactly_the_cut_off_is_ranked(self):
        """A score equal to the cut-off is at or above it, so it ranks.

        PRD §3.3: "the set is then partitioned at the program's
        `min_composite_score` inclusively: a score at or above the cut-off moves
        the application `RECEIVED → RANKED`, while a score strictly below it
        moves the application `RECEIVED → NOT_SELECTED`."

        Design: Difficulty/boundary_precision_check/composite_score_sixty_exact_ranks_while_fifty_nine_ninety_nine_is_not_selected
        """
        scenario = _rank_two_parcels_at_the_cut_off()
        assert scenario["program"]["min_composite_score"] == pytest.approx(
            60.00, abs=0.01
        )

        application = read_application(scenario["at_cut_off"]["application"]["id"])
        # 0.25 x 35.00 + 0.25 x 100 + 0.25 x 100 + 0.25 x 5.00
        assert application["composite_score"] == pytest.approx(60.00, abs=0.01)
        assert application["status"] == "RANKED"
        assert application["rank_position"] == 1
        # A ranked application keeps its land.
        assert (
            read_parcel(scenario["at_cut_off"]["parcel"]["id"])["status"]
            == "UNDER_APPLICATION"
        )

    def test_a_composite_one_hundredth_below_the_cut_off_is_not_selected(self):
        """59.99 is strictly below 60.00, so the application is not selected.

        PRD §3.3: "Ranked applications receive a 1-based `rank_position`
        assigned over the ranked subset ordered by `composite_score` descending
        and then `created_at` ascending; applications that were not selected keep
        `rank_position` null. Because a not-selected application releases its
        land, each such parcel returns `UNDER_APPLICATION → ELIGIBLE` with its
        `version` incremented."

        Design: Difficulty/boundary_precision_check/composite_score_sixty_exact_ranks_while_fifty_nine_ninety_nine_is_not_selected
        """
        scenario = _rank_two_parcels_at_the_cut_off()

        application = read_application(scenario["below_cut_off"]["application"]["id"])
        assert application["composite_score"] == pytest.approx(59.99, abs=0.01)
        assert application["status"] == "NOT_SELECTED"
        assert application["rank_position"] is None

        released = read_parcel(scenario["below_cut_off"]["parcel"]["id"])
        assert released["status"] == "ELIGIBLE"
        assert released["version"] > scenario["below_cut_off"]["parcel"]["version"]

    def test_the_ranking_call_partitions_the_two_applications(self):
        """The response reports the partition it just made.

        PRD §3.3: "The call reports `ranked_count`, `selected_count`,
        `not_selected_count` and the list of `ranked_application_ids`."

        Design: Difficulty/boundary_precision_check/composite_score_sixty_exact_ranks_while_fifty_nine_ninety_nine_is_not_selected
        """
        scenario = _rank_two_parcels_at_the_cut_off()
        result = scenario["rank_result"]
        assert result["ranked_count"] == 1
        assert result["not_selected_count"] == 1
        assert result["ranked_application_ids"] == [
            scenario["at_cut_off"]["application"]["id"]
        ]
        # `selected_count` on the round counts everything not RECEIVED,
        # NOT_SELECTED or WITHDRAWN.
        assert result["selected_count"] == 1


class TestImperviousAllowanceBoundary:
    """139,392 square feet is inside the allowance and 139,393 is outside."""

    @staticmethod
    def _visit_at(easement_id: str):
        set_clock("2027-06-10T00:00:00Z")
        return schedule_visit(
            easement_id,
            window_start="2027-06-10T00:00:00Z",
            window_end="2027-06-17T00:00:00Z",
        )

    def test_an_observation_exactly_at_the_allowance_is_compliant(self):
        """The comparison is strictly greater, so equality passes.

        PRD §3.8: "its `finding` is decided by a strict comparison:
        `CONFIRMED_VIOLATION` when `observed_impervious_sqft` is strictly greater
        than the easement's `impervious_allowance_sqft`, and `NO_ISSUE`
        otherwise."

        Design: Difficulty/boundary_precision_check/impervious_exceedance_at_allowance_exactly_passes_one_sqft_over_opens_violation
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]
        # floor(160.00 x 43,560 x 0.02)
        assert scenario["easement"]["impervious_allowance_sqft"] == 139_392

        visit = self._visit_at(easement_id)
        completed = complete_visit(visit["id"], 139_392)
        assert completed["finding"] == "NO_ISSUE"
        assert completed["observed_impervious_sqft"] == 139_392

        easement = read_easement(easement_id)
        assert easement["compliance_status"] == "COMPLIANT"
        assert easement["open_violation_count"] == 0
        assert easement["stewardship_hold"] is False
        assert (
            validate_success(api_client.list_visit_violations(visit["id"], ADMIN)) == []
        )

    def test_an_observation_one_square_foot_over_opens_a_minor_violation(self):
        """One square foot over is strictly greater, so a violation opens.

        PRD §3.8: "with `excess_sqft` equal to the observed coverage less the
        allowance, and with `status` `OPEN`."

        Design: Difficulty/boundary_precision_check/impervious_exceedance_at_allowance_exactly_passes_one_sqft_over_opens_violation
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]

        visit = self._visit_at(easement_id)
        completed = complete_visit(visit["id"], 139_393)
        assert completed["finding"] == "CONFIRMED_VIOLATION"

        violations = validate_success(
            api_client.list_easement_violations(easement_id, ADMIN, {"limit": 100})
        )
        assert len(violations) == 1
        violation = violations[0]
        assert violation["excess_sqft"] == 1
        # 1 is not strictly above 2,000, so the 180-day MINOR clock applies.
        assert violation["severity"] == "MINOR"
        assert violation["status"] == "OPEN"
        assert violation["opened_on"].startswith("2027-06-10")
        assert violation["cure_deadline_on"].startswith("2027-12-07")

        easement = read_easement(easement_id)
        assert easement["compliance_status"] == "VIOLATION_OPEN"
        assert easement["stewardship_hold"] is True
        assert easement["open_violation_count"] == 1

    def test_the_impervious_request_admits_the_allowance_and_refuses_one_more(self):
        """The metering endpoint stops at the same boundary.

        PRD §3.8: "the requested amount is added to `impervious_used_sqft` only
        when the result stays within `impervious_allowance_sqft`, and the
        easement's `version` increments. A request that would push
        `impervious_used_sqft` above the allowance is rejected outright with
        `ERR_IMPERVIOUS_ALLOWANCE_EXCEEDED` and nothing is recorded."

        Design: Difficulty/boundary_precision_check/impervious_exceedance_at_allowance_exactly_passes_one_sqft_over_opens_violation
        """
        scenario = setup_recorded_easement()
        easement_id = scenario["easement"]["id"]

        filled = record_impervious(easement_id, 139_392)
        assert filled["impervious_used_sqft"] == 139_392
        assert filled["compliance_status"] == "COMPLIANT"
        assert filled["version"] > scenario["easement"]["version"]

        response = api_client.record_impervious_request(
            easement_id,
            {"added_impervious_sqft": 1, "description": "one more paving square"},
            MONITOR,
        )
        validate_error(response, ApiErrorId.ERR_IMPERVIOUS_ALLOWANCE_EXCEEDED.value)

        after = read_easement(easement_id)
        assert after["impervious_used_sqft"] == 139_392
        assert after["version"] == filled["version"]
