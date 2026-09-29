"""Values sitting exactly on a threshold, and values one unit past it.

Every pair here is one cent, one day or one basis point apart, which is the distance
at which an inclusive comparison and an exclusive one stop agreeing.
"""

from typing import Any, Dict

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_case_money_invariants,
    assert_dob_report,
    assert_skill_fit_report,
    assert_volunteer_deployment,
    read_case,
    read_funding_source,
    request_disbursement,
    setup_awarded_case,
    setup_case_with_verified_damage,
    setup_permitted_project_with_group,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["volunteer_coordinator_headers"]
OFFICER = TEST_USERS["disbursement_officer_headers"]


def _setup_contents_case_with_mixed_assistance() -> Dict[str, Any]:
    """A 1500000 contents need with 500000 in the duplication pool.

    400000 is documented and 100000 is disputed; both figures enter the pool even
    though only the documented one offsets unmet need, so the headroom before exposure
    begins is exactly 1000000.
    """
    return setup_case_with_verified_damage(
        damage=[("CONTENTS", 1_500_000)],
        assistance=[
            {
                "source_type": "INSURANCE_SETTLEMENT",
                "purpose_code": "CONTENTS_REPLACEMENT",
                "awarded_cents": 400_000,
                "received_on": "2026-07-05",
                "documentation_status": "DOCUMENTED",
            },
            {
                "source_type": "CROWDFUNDING",
                "purpose_code": "CONTENTS_REPLACEMENT",
                "awarded_cents": 100_000,
                "received_on": "2026-07-12",
                "documentation_status": "DISPUTED",
            },
        ],
        survivor_overrides={"household_name": "Okafor Household", "household_size": 2},
    )


def test_exposure_of_exactly_zero_clears_the_request(api):
    """PRD §3.6: "The fork is strict: exposure of exactly 0 clears, and exposure of a
    single cent flags."

    Design: Difficulty/boundary_precision_check/dob_exposure_zero_clears_and_one_cent_over_flags
    """
    scenario = _setup_contents_case_with_mixed_assistance()

    row = request_disbursement(
        scenario["case"]["id"],
        "CONTENTS_REPLACEMENT",
        1_000_000,
        payee_name="Valley Furniture Co",
    )

    assert row["status"] == "DOB_CLEARED"
    # 400000 documented plus 100000 disputed.
    assert row["dob_pool_cents"] == 500_000
    assert row["dob_exposure_cents"] == 0


def test_a_single_cent_beyond_the_bucket_need_flags_the_request(api):
    """PRD §3.6: "`dob_exposure_cents` is `dob_pool_cents` plus the prior-disbursed
    figure plus this request's `requested_cents`, less the bucket need, floored at
    zero."

    Design: Difficulty/boundary_precision_check/dob_exposure_zero_clears_and_one_cent_over_flags
    """
    scenario = _setup_contents_case_with_mixed_assistance()
    cleared = request_disbursement(
        scenario["case"]["id"],
        "CONTENTS_REPLACEMENT",
        1_000_000,
        payee_name="Valley Furniture Co",
    )
    assert cleared["status"] == "DOB_CLEARED"

    flagged = request_disbursement(
        scenario["case"]["id"],
        "CONTENTS_REPLACEMENT",
        1_000_001,
        payee_name="Valley Furniture Co",
    )

    assert flagged["status"] == "DOB_FLAGGED"
    assert flagged["dob_pool_cents"] == 500_000
    assert flagged["dob_exposure_cents"] == 1


def test_the_planning_read_reports_the_same_pool_and_bucket_need(api):
    """PRD §3.6: "For planning ahead of a request, a computed read exposes the same
    duplication-of-benefits arithmetic for a case."

    Design: Difficulty/boundary_precision_check/dob_exposure_zero_clears_and_one_cent_over_flags
    """
    scenario = _setup_contents_case_with_mixed_assistance()
    request_disbursement(
        scenario["case"]["id"],
        "CONTENTS_REPLACEMENT",
        1_000_000,
        payee_name="Valley Furniture Co",
    )

    report = validate_success(
        api.get_dob_report(
            scenario["case"]["id"], OFFICER, params={"purpose_code": "CONTENTS_REPLACEMENT"}
        )
    )

    assert_dob_report(report)
    assert report["case_id"] == scenario["case"]["id"]
    assert report["purpose_code"] == "CONTENTS_REPLACEMENT"
    assert report["dob_pool_cents"] == 500_000
    assert report["bucket_need_cents"] == 1_500_000
    # The cleared row is neither APPROVED nor PAID, so it is not prior-disbursed money.
    assert report["prior_disbursed_cents"] == 0
    assert scenario["case"]["id"] in report["sibling_case_ids"]


def _setup_twelve_person_crew_for_a_weighted_phase() -> Dict[str, Any]:
    """A phase needing 1350 weighted hours and the crew that covers exactly 60 percent."""
    return setup_permitted_project_with_group(
        project_overrides={
            "required_trade_hours": {"FRAMING": 300, "ROOFING": 150, "GENERAL_LABOR": 300},
            "estimated_material_cents": 900_000,
            "critical_trades": ["FRAMING"],
        },
        group_overrides={
            "group_name": "Brookfield Build Team",
            "home_organization": "Brookfield Baptist",
            "member_count": 12,
            "skill_profile": {"FRAMING": 5, "ROOFING": 2, "GENERAL_LABOR": 12},
            "requires_housing": False,
        },
        permit_number="PB-3316",
    )


def test_a_score_of_exactly_six_thousand_basis_points_is_accepted(api):
    """PRD §3.8: "The floor is inclusive: a score of exactly 6000 is accepted."

    Design: Difficulty/boundary_precision_check/skill_fit_exactly_at_minimum_accepted_and_one_day_shorter_rejected
    """
    scenario = _setup_twelve_person_crew_for_a_weighted_phase()

    booking = validate_success(
        api.create_volunteer_deployment(
            {
                "group_id": scenario["group"]["id"],
                "project_id": scenario["project"]["id"],
                "arrival_date": "2026-09-07",
                "departure_date": "2026-09-11",
            },
            COORDINATOR,
        ),
        201,
    )

    assert_volunteer_deployment(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["day_count"] == 5
    assert booking["skill_fit_score_bps"] == 6000
    assert booking["crew_hours_committed"] == 360


def test_one_day_shorter_falls_below_the_floor_and_is_refused(api):
    """PRD §3.8: "The server computes `skill_fit_score_bps` in the `COVERAGE_WEIGHTED`
    variant and stores it on the deployment, and refuses the booking with
    `ERR_SKILL_FIT_BELOW_MINIMUM` when the score is below 6000 basis points."

    Design: Difficulty/boundary_precision_check/skill_fit_exactly_at_minimum_accepted_and_one_day_shorter_rejected
    """
    scenario = _setup_twelve_person_crew_for_a_weighted_phase()
    validate_success(
        api.create_volunteer_deployment(
            {
                "group_id": scenario["group"]["id"],
                "project_id": scenario["project"]["id"],
                "arrival_date": "2026-09-07",
                "departure_date": "2026-09-11",
            },
            COORDINATOR,
        ),
        201,
    )

    response = api.create_volunteer_deployment(
        {
            "group_id": scenario["group"]["id"],
            "project_id": scenario["project"]["id"],
            "arrival_date": "2026-09-20",
            "departure_date": "2026-09-23",
        },
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_SKILL_FIT_BELOW_MINIMUM.value, 422)


def test_the_score_is_rounded_half_up_to_the_whole_basis_point(api):
    """PRD §3.8: "In both variants the score is ten thousand multiplied by the
    numerator, divided by the denominator, rounded half up to the nearest whole basis
    point."

    Design: Difficulty/boundary_precision_check/skill_fit_exactly_at_minimum_accepted_and_one_day_shorter_rejected
    """
    scenario = _setup_twelve_person_crew_for_a_weighted_phase()

    probe = validate_success(
        api.get_skill_fit(
            scenario["project"]["id"],
            COORDINATOR,
            params={
                "group_id": scenario["group"]["id"],
                "variant": "COVERAGE_WEIGHTED",
                "arrival_date": "2026-09-20",
                "departure_date": "2026-09-23",
            },
        )
    )

    assert_skill_fit_report(probe)
    assert probe["day_count"] == 4
    # 3*120 + 48 + 288 over 1350; the exact quotient is 5155.55...
    assert probe["weighted_covered"] == 696
    assert probe["weighted_required"] == 1350
    assert probe["score_bps"] == 5156
    assert probe["meets_minimum"] is False


UNRESTRICTED_POOL = {
    "label": "General donations 2026",
    "source_type": "INDIVIDUAL_DONATION",
    "restriction_code": "UNRESTRICTED",
    "total_cents": 2_000_000,
    "admin_retention_allowed": True,
}


def _setup_award_on_a_five_thousand_dollar_need() -> Dict[str, Any]:
    """A determined need of exactly 500000 cents, the TIER_A/TIER_B band edge."""
    return setup_awarded_case(
        damage=[("CONTENTS", 500_000)],
        orgs=[{"org_name": "Willow Creek Guild", "annual_pledge_cap_cents": 1_000_000}],
        pledges=[(0, 300_000, "CONTENTS_REPLACEMENT")],
        funding_sources=[UNRESTRICTED_POOL],
    )


def test_a_determined_need_of_exactly_five_thousand_dollars_selects_tier_b(api):
    """PRD §3.5: "`TIER_A` when the determined need is strictly less than $5,000;
    otherwise `TIER_B` when it is strictly less than $25,000; otherwise `TIER_C`. A
    determined need of exactly $5,000 is `TIER_B`, and exactly $25,000 is `TIER_C`."

    Design: Difficulty/boundary_precision_check/tier_band_half_open_at_exactly_500000_selects_tier_b
    """
    scenario = _setup_award_on_a_five_thousand_dollar_need()

    assert scenario["assessment"]["unmet_need_total_cents"] == 500_000
    assert scenario["presentation"]["bridge_tier"] == "TIER_B"


def test_the_tier_b_percentage_caps_the_bridge_below_the_open_gap(api):
    """PRD §3.5: "The bridge cap is a tier-dependent percentage of the determined need,
    rounded half up to the nearest cent: 50 percent under `TIER_A`, 30 percent under
    `TIER_B` and 15 percent under `TIER_C`."

    Design: Difficulty/boundary_precision_check/tier_band_half_open_at_exactly_500000_selects_tier_b
    """
    scenario = _setup_award_on_a_five_thousand_dollar_need()
    presentation = scenario["presentation"]

    assert presentation["pledged_total_cents"] == 300_000
    # The gap is 200000 but 30 percent of 500000 is only 150000.
    assert presentation["bridge_authorized_cents"] == 150_000
    assert presentation["awarded_cents"] == 450_000
    assert presentation["shortfall_cents"] == 50_000
    case = read_case(scenario["case"]["id"])
    assert case["total_committed_cents"] == 450_000
    assert case["reference_unmet_cents"] == 500_000
    assert case["residual_unmet_cents"] == 50_000
    assert_case_money_invariants(case)
    assert case["funding_status"] == "PARTIALLY_COMMITTED"
    assert case["case_status"] == "ACTIVE_RECOVERY"
    source = read_funding_source(scenario["funding_sources"][0]["id"])
    assert source["available_cents"] == 2_000_000
