"""The two dual-variant calculations: the placement fee and the vetting score.

Each is computed twice from one stored row under two named variants, and the two
answers deliberately disagree.
"""
from test_helpers import (
    CONSULTANT,
    SENIOR_SCENARIO,
    api_client,
    assert_milestone_allocation,
    assert_score_variants,
    confirm_start,
    create_placement_payload,
    read_candidate,
    read_milestones,
    read_requisition,
    setup_scenario,
    setup_senior_scenario,
    validate_error,
    validate_paginated,
)

# The HOUSEKEEPER search whose candidate scores exactly 70 on the screening
# variant and 75 on the placement-ready variant.
MARCHETTI_OPTIONS = {
    "client": {
        "household_name": "Belgrave Mews",
        "primary_contact_email": "ops@belgrave.example",
        "region_code": "MA",
    },
    "signatory_name": "H. Belgrave",
    "fee_schedules": [
        {
            "role_type": "HOUSEKEEPER",
            "comp_band_floor_cents": 0,
            "comp_band_ceiling_cents": 15_000_000,
            "fee_percent_bps": 1800,
            "guarantee_window_days": 60,
            "effective_from": "2026-01-01",
        }
    ],
    "requisition": {
        "role_type": "HOUSEKEEPER",
        "first_year_compensation_cents": 6_500_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "candidate": {
        "full_name": "T. Marchetti",
        "contact_email": "tm@mail.example",
        "primary_role_type": "HOUSEKEEPER",
        "years_experience": 10,
        "live_in_willing": False,
    },
    "references": [
        {
            "principal_employer_name": "Cadogan Family",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2023-01",
            "employment_end_month": "2023-12",
            "contact_email": "cadogan@mail.example",
        },
        {
            "principal_employer_name": "Latimer Family",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2024-01",
            "employment_end_month": "2024-04",
            "contact_email": "latimer@mail.example",
            "chain_to_previous": True,
        },
        {
            "principal_employer_name": "Ellesmere Family",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2021-01",
            "employment_end_month": "2021-06",
            "contact_email": "ellesmere@mail.example",
        },
    ],
    "verify_outcomes": ["VERIFIED", "VERIFIED", "DISPUTED"],
    "background": {
        "provider_reference": "BV-2001",
        "scope_items": ["IDENTITY", "CRIMINAL"],
    },
    "trial": {
        "engagement_type": "WORKING_INTERVIEW",
        "day_rate_cents": 0,
        "start_at": "2026-08-11T09:00:00Z",
        "end_at": "2026-08-11T15:00:00Z",
    },
    "trial_end_clock": "2026-08-11T15:00:00Z",
}


class TestPlacementFeeVariants:
    def test_01_provisional_variant_rounds_the_aggregate_once(self):
        """The requisition and the offer both carry the PROVISIONAL answer.

        PRD §3.2: "Take the requisition's `first_year_compensation_cents`,
        multiply it by the `fee_percent_bps` just resolved, divide by 10000, and
        round the result half up to a whole number of cents; that value is
        stamped as the requisition's `provisional_fee_cents`."

        Design: Difficulty/dual_variant_calc/placement_fee_provisional_and_final_variants_diverge_by_one_cent
        """
        scenario = setup_senior_scenario(stage="placement_pending")
        requisition = read_requisition(scenario["requisition"])
        assert requisition["fee_percent_bps"] == 2233
        assert requisition["provisional_fee_cents"] == 3_349_500

        placement = scenario["placement"]
        assert placement["fee_variant"] == "PROVISIONAL"
        assert placement["fee_cents"] == 3_349_500
        assert placement["actual_first_year_compensation_cents"] == 15_000_000

    def test_02_final_variant_rounds_each_component_and_lands_one_cent_lower(self):
        """Confirming the start re-prices the same package one cent lower.

        PRD §3.6: "Rounding happens **before** the sum, four separate times, and
        this is the whole point of the two variants: the `FINAL` figure is not
        the `PROVISIONAL` figure recomputed, and on identical total compensation
        the two can differ by a cent or more."

        Design: Difficulty/dual_variant_calc/placement_fee_provisional_and_final_variants_diverge_by_one_cent
        """
        scenario = setup_senior_scenario(stage="placement_pending")
        assert scenario["placement"]["fee_cents"] == 3_349_500

        confirmed = confirm_start(scenario["placement"])
        assert confirmed["fee_variant"] == "FINAL"
        assert confirmed["fee_cents"] == 3_349_499
        assert confirmed["actual_first_year_compensation_cents"] == 15_000_000
        assert confirmed["fee_percent_bps"] == 2233
        assert confirmed["guarantee_window_days"] == 90
        assert confirmed["guarantee_expires_on"] == SENIOR_SCENARIO["GUARANTEE_EXPIRES_ON"]
        assert confirmed["placement_status"] == "ACTIVE"

    def test_03_the_two_variants_share_one_aggregate_compensation(self):
        """The whole one-cent difference comes from the rounding position.

        PRD §3.6: "An implementer who sums the components first and rounds once
        will produce the `PROVISIONAL` answer under a `FINAL` label."

        Design: Difficulty/dual_variant_calc/placement_fee_provisional_and_final_variants_diverge_by_one_cent
        """
        scenario = setup_senior_scenario(stage="placement_active")
        placement = scenario["placement"]
        components = (
            placement["base_salary_cents"],
            placement["guaranteed_bonus_cents"],
            placement["accommodation_imputed_cents"],
            placement["overtime_allowance_cents"],
        )
        assert sum(components) == 15_000_000
        assert placement["fee_cents"] == 3_349_499

        milestones = assert_milestone_allocation(
            read_milestones(placement), placement["fee_cents"]
        )
        assert [row["amount_cents"] for row in milestones] == [
            1_004_850,
            1_004_850,
            1_339_799,
        ]

        assert read_candidate(scenario["candidate"])["availability_status"] == "PLACED"
        assert read_requisition(scenario["requisition"])["status"] == "PLACED"


class TestVettingScoreVariants:
    def test_04_one_candidate_row_carries_both_score_variants(self):
        """Screening 70 and placement-ready 75 are read from the same row.

        PRD §3.3: "Because the two variants weigh different evidence against
        different thresholds, the very same stored dossier can admit a candidate
        to a trial day and refuse them an offer, and that divergence is
        intentional rather than a defect."

        Design: Difficulty/dual_variant_calc/vetting_score_variants_admit_to_trial_but_refuse_offer
        """
        scenario = setup_scenario(stage="background_recorded", **MARCHETTI_OPTIONS)
        candidate = read_candidate(scenario["candidate"])
        assert_score_variants(candidate, screening=70, placement_ready=75)
        assert candidate["verified_reference_count"] == 2
        assert candidate["reference_coverage_months"] == 16
        assert candidate["longest_contiguous_months"] == 16
        assert candidate["vetting_status"] == "CLEARED"

    def test_05_the_screening_variant_admits_the_candidate_to_a_trial(self):
        """A screening score of exactly 70 satisfies the presentation gate.

        PRD §3.4: "**The presentation score gate** is checked after the cap: the
        candidate's `screening_score` must be at least 70 points, and a lower
        score is refused with `ERR_CANDIDATE_SCORE_BELOW_THRESHOLD` (HTTP 422)."

        Design: Difficulty/dual_variant_calc/vetting_score_variants_admit_to_trial_but_refuse_offer
        """
        scenario = setup_scenario(stage="trial_booked", **MARCHETTI_OPTIONS)
        assert scenario["trial"]["status"] == "SCHEDULED"
        assert scenario["trial"]["engagement_type"] == "WORKING_INTERVIEW"
        assert read_candidate(scenario["candidate"])["screening_score"] == 70
        assert read_requisition(scenario["requisition"])["status"] == "TRIALING"

    def test_06_the_placement_ready_variant_refuses_the_offer(self):
        """The same dossier is refused at the offer gate on the other variant.

        PRD §3.3: "Its gate is a `placement_ready_score` of at least 80 points."

        Design: Difficulty/dual_variant_calc/vetting_score_variants_admit_to_trial_but_refuse_offer
        """
        scenario = setup_scenario(stage="trial_passed", **MARCHETTI_OPTIONS)
        candidate = read_candidate(scenario["candidate"])
        assert candidate["vetting_status"] == "CLEARED"
        assert candidate["availability_status"] == "ON_TRIAL"
        assert candidate["placement_ready_score"] == 75

        requisition = read_requisition(scenario["requisition"])
        response = api_client.create_placement(
            create_placement_payload(
                requisition["id"],
                candidate["id"],
                requisition["version"],
                start_date="2026-09-01",
                base_salary_cents=6_000_000,
                guaranteed_bonus_cents=300_000,
                accommodation_imputed_cents=0,
                overtime_allowance_cents=200_000,
            ),
            CONSULTANT,
        )
        validate_error(response, "ERR_CANDIDATE_SCORE_BELOW_THRESHOLD")

        rows, _ = validate_paginated(
            api_client.list_placements(CONSULTANT, {"requisition_id": requisition["id"]})
        )
        assert rows == []
        assert read_requisition(requisition)["status"] == "TRIALING"
