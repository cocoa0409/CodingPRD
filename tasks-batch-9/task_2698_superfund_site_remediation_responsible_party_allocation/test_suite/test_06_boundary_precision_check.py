"""Values sitting exactly on a threshold, and the precision around them.

A party exactly on the small-contributor ceiling is eligible, an offer exactly
on the premium floor is accepted, an empty valid-sample set blocks submission,
and a hazard index of exactly 1.00 trips the action level on its own.
"""
import pytest

from test_helpers import ApiErrorId, api_client, factories
from test_helpers.assertions import (
    assert_epc,
    assert_oversight_figures,
    assert_percentage,
    assert_seven_decimal_risk,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_sample,
    add_verified_waste_in,
    adopt_round,
    create_investigation,
    create_listed_site,
    create_participating_party,
    issue_action,
    open_round,
    post_oversight,
    prp_version,
    read_investigation,
    read_party,
    read_site,
    set_clock,
    share_for,
)
from test_helpers.test_users import TEST_USERS

AUTHOR = TEST_USERS["author_pm_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


def _tanner_creek_adopted_round():
    """Party B lands on exactly 1.00 percent of the verified site total."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Tanner Creek Solvent Recovery", epa_region=5, hrs_score=39.70
    )
    prp_a = create_participating_party(
        site["id"],
        legal_name="Tanner Solvents Inc",
        party_type="OWNER_OPERATOR",
        viability_score=88,
    )
    prp_b = create_participating_party(
        site["id"],
        legal_name="Creekside Auto Body LLC",
        party_type="GENERATOR",
        viability_score=19,
    )
    add_verified_waste_in(site["id"], prp_a["id"], 3960, "II", "A", 1976)
    add_verified_waste_in(site["id"], prp_b["id"], 40, "IV", "B", 1991)
    create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 chlorinated solvent plume",
    )
    allocation_round = open_round(site["id"], weights=(5000, 3000, 2000))
    adopt_round(allocation_round["id"], [prp_a["id"], prp_b["id"]])
    post_oversight(
        site["id"], 4_000_000, cost_category="RI_FS_OVERSIGHT", incurred_on="2027-02-20"
    )
    return site, prp_a, prp_b, allocation_round


class TestDeMinimisCeilingAndPremiumFloorAreInclusive:
    def test_a_share_of_exactly_one_percent_is_eligible_and_a_larger_share_is_not(self):
        """The share ceiling is inclusive and read from the rounded figure.

        PRD: "Every one of these comparisons is inclusive at the ceiling, and critically **the share test is applied to the rounded figure**: a party whose unrounded share is 1.004 percent rounds to 1.00 and is eligible, while a party at 1.005 percent rounds to 1.01 and is not."

        Design: Difficulty/boundary_precision_check/de_minimis_share_exactly_at_ceiling_and_premium_exactly_at_floor
        """
        _, prp_a, prp_b, _ = _tanner_creek_adopted_round()

        small = read_party(prp_b["id"])
        assert_percentage(small["volumetric_share_pct"], 1.00, "volumetric_share_pct")
        assert small["de_minimis_eligible"] is True
        assert small["verified_volume_tons"] == pytest.approx(40, abs=0.01)
        assert small["max_toxicity_class"] == "IV"

        large = read_party(prp_a["id"])
        assert_percentage(large["volumetric_share_pct"], 99.00, "volumetric_share_pct")
        assert large["de_minimis_eligible"] is False

    def test_the_response_cost_that_feeds_the_floor_is_the_first_tier_oversight_bill(self):
        """A subtotal on the first ceiling is rated at the first tier.

        PRD: "Both tier ceilings are inclusive, so a subtotal of exactly 5,000,000 cents is still in the first tier."

        Design: Difficulty/boundary_precision_check/de_minimis_share_exactly_at_ceiling_and_premium_exactly_at_floor
        """
        site, _, _, _ = _tanner_creek_adopted_round()

        after = read_site(site["id"])
        assert_oversight_figures(after, 4_000_000, 1550, 620_000, 4_620_000)
        assert after["total_response_cost_cents"] == 4_620_000
        assert after["oversight_cap_utilization_pct"] in (None, "")

    def test_an_offer_exactly_at_the_floor_is_accepted_and_the_floor_reads_the_allocated_share(self):
        """The floor is derived from the allocated exposure, not the raw volume.

        PRD: "The system first captures `respondent_share_pct_at_offer`, the respondent's `final_pct` in the adopted round — the *allocated* exposure, which is deliberately **not** the `volumetric_share_pct` that fed the allocation model, because the adopted allocation may have moved the party a long way from its raw volumetric arithmetic."

        Design: Difficulty/boundary_precision_check/de_minimis_share_exactly_at_ceiling_and_premium_exactly_at_floor
        """
        site, _, prp_b, allocation_round = _tanner_creek_adopted_round()

        share = share_for(allocation_round["id"], prp_b["id"])
        assert_percentage(share["final_pct"], 0.72, "final_pct")
        assert share["disposition"] == "ALLOCATED"

        action = issue_action(
            site["id"],
            prp_b["id"],
            66_528,
            action_type="DE_MINIMIS_SETTLEMENT",
        )
        assert_percentage(
            action["respondent_share_pct_at_offer"], 0.72, "respondent_share_pct_at_offer"
        )
        assert action["premium_floor_cents"] == 66_528
        assert action["demanded_cents"] == 66_528
        assert action["status"] == "OFFERED"
        assert action["received_cents"] == 0

    def test_one_cent_below_the_floor_is_the_first_failing_value(self):
        """The comparison is at-or-above, so the cent below the floor fails.

        PRD: "The respondent's `de_minimis_eligible` flag must be true — an ineligible party is refused with `ERR_NOT_DE_MINIMIS_ELIGIBLE` (HTTP 409) — and the `demanded_cents` must be at or above the computed `premium_floor_cents`, with an offer exactly at the floor accepted and anything below it refused with `ERR_DE_MINIMIS_PREMIUM_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/de_minimis_share_exactly_at_ceiling_and_premium_exactly_at_floor
        """
        site, _, prp_b, _ = _tanner_creek_adopted_round()

        response = api_client.create_cost_recovery_action(
            site["id"],
            factories.cost_recovery_action_payload(
                respondent_prp_id=prp_b["id"],
                demanded_cents=66_527,
                expected_prp_version=prp_version(prp_b["id"]),
                action_type="DE_MINIMIS_SETTLEMENT",
            ),
            COUNSEL,
        )
        validate_error(response, ApiErrorId.ERR_DE_MINIMIS_PREMIUM_INSUFFICIENT.value)


def _ridgemont_investigation_without_valid_samples():
    """Three samples, none of which can enter the central-tendency set."""
    set_clock("2027-02-01T09:00:00Z")
    site = create_listed_site(
        name="Ridgemont Plating Works", epa_region=2, hrs_score=36.20
    )
    investigation = create_investigation(
        site["id"],
        exposure_medium="GROUNDWATER",
        scope_summary="OU-1 groundwater chromium plume",
    )
    add_sample(
        investigation["id"], "SOIL", "CHROMIUM_VI", 700.0, "VALID",
        "2027-01-05T10:00:00Z", "LAB-R-0001",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "CHROMIUM_VI", 900.0, "REJECTED",
        "2027-01-06T10:00:00Z", "LAB-R-0002",
    )
    add_sample(
        investigation["id"], "GROUNDWATER", "CHROMIUM_VI", 5.0, "ESTIMATED",
        "2027-01-07T10:00:00Z", "LAB-R-0003",
    )
    return site, investigation


def _add_the_two_valid_results(ri_id):
    add_sample(
        ri_id, "GROUNDWATER", "CHROMIUM_VI", 1.111, "VALID",
        "2027-01-08T10:00:00Z", "LAB-R-0004",
    )
    add_sample(
        ri_id, "GROUNDWATER", "CHROMIUM_VI", 4.334, "VALID",
        "2027-01-09T10:00:00Z", "LAB-R-0005",
    )


class TestEmptyValidSetBlocksSubmissionAndHazardIndexLimitIsInclusive:
    def test_an_empty_valid_set_blocks_submission_even_with_three_samples_on_file(self):
        """Submission needs at least one valid result of the right medium.

        PRD: "Submission is permitted only when `valid_sample_count` is at least 1; an investigation with no result of its own exposure medium carrying a valid quality flag cannot leave draft, and the attempt is refused with `ERR_NO_VALID_SAMPLES`."

        Design: Difficulty/boundary_precision_check/hazard_index_exactly_at_limit_with_empty_valid_set_first_returns_4XX
        """
        _, investigation = _ridgemont_investigation_without_valid_samples()

        validate_error(
            api_client.submit_remedial_investigation(investigation["id"], AUTHOR),
            ApiErrorId.ERR_NO_VALID_SAMPLES.value,
        )
        after = read_investigation(investigation["id"])
        assert after["status"] == "DRAFT"
        assert after["valid_sample_count"] == 0
        assert after["central_tendency_epc_ug_per_l"] in (None, "")
        assert after["rme_epc_ug_per_l"] in (None, "")
        assert after["central_tendency_risk"] in (None, "")
        assert after["rme_risk"] in (None, "")
        assert after["hazard_index"] in (None, "")
        assert after["action_level_exceeded"] is False

    def test_only_valid_results_of_the_matching_medium_are_counted(self):
        """The wrong medium and the rejected flag are both invisible.

        PRD: "First the candidate set is narrowed to results of this investigation whose `medium` matches the investigation's `exposure_medium`; a result of any other medium is invisible here **even when its quality flag is valid**."

        Design: Difficulty/boundary_precision_check/hazard_index_exactly_at_limit_with_empty_valid_set_first_returns_4XX
        """
        _, investigation = _ridgemont_investigation_without_valid_samples()
        api_client.submit_remedial_investigation(investigation["id"], AUTHOR)
        _add_the_two_valid_results(investigation["id"])

        assert read_investigation(investigation["id"])["valid_sample_count"] == 2

    def test_the_central_tendency_concentration_rounds_half_up_at_three_decimals(self):
        """A mean of exactly 2.7225 rounds up to 2.723.

        PRD: "The `central_tendency_epc_ug_per_l` is the arithmetic mean of `concentration_ug_per_l` over the central-tendency set, rounded half up to three decimal places."

        Design: Difficulty/boundary_precision_check/hazard_index_exactly_at_limit_with_empty_valid_set_first_returns_4XX
        """
        _, investigation = _ridgemont_investigation_without_valid_samples()
        api_client.submit_remedial_investigation(investigation["id"], AUTHOR)
        _add_the_two_valid_results(investigation["id"])
        submitted = validate_success(
            api_client.submit_remedial_investigation(investigation["id"], AUTHOR)
        )

        assert submitted["status"] == "UNDER_REVIEW"
        assert_epc(
            submitted["central_tendency_epc_ug_per_l"], 2.723, "central_tendency_epc_ug_per_l"
        )
        assert_seven_decimal_risk(
            submitted["central_tendency_risk"], 0.0000136, "central_tendency_risk"
        )

    def test_the_hazard_index_at_exactly_one_trips_the_flag_while_the_risk_stays_below(self):
        """Both action-level comparisons are inclusive, and either one suffices.

        PRD: "Both comparisons are inclusive: an `rme_risk` of exactly 0.0001000 exceeds, and a `hazard_index` of exactly 1.00 exceeds."

        Design: Difficulty/boundary_precision_check/hazard_index_exactly_at_limit_with_empty_valid_set_first_returns_4XX
        """
        _, investigation = _ridgemont_investigation_without_valid_samples()
        api_client.submit_remedial_investigation(investigation["id"], AUTHOR)
        _add_the_two_valid_results(investigation["id"])
        submitted = validate_success(
            api_client.submit_remedial_investigation(investigation["id"], AUTHOR)
        )

        assert_epc(submitted["rme_epc_ug_per_l"], 5.0, "rme_epc_ug_per_l")
        assert_seven_decimal_risk(submitted["rme_risk"], 0.0000250, "rme_risk")
        assert_percentage(submitted["hazard_index"], 1.00, "hazard_index")
        assert submitted["action_level_exceeded"] is True
