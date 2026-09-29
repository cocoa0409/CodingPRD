"""Machines that revisit states rather than marching forward: the scoping loop,
the two independent candidate axes, and the inconclusive background self-loop.
"""
from test_helpers import (
    CONSULTANT,
    adjudicate_background,
    api_client,
    book_trial,
    finalize_scope,
    order_background_verification,
    read_background_verification,
    read_candidate,
    read_requisition,
    read_trial,
    record_background_result,
    record_trial_outcome,
    run_scoping_round,
    scope_requisition_payload,
    set_clock,
    setup_scenario,
    start_trial,
    validate_error,
    verify_reference,
)

# A CHAUFFEUR search whose household changes its mind twice.
DUNMORE_OPTIONS = {
    "client": {
        "household_name": "Dunmore Lodge",
        "primary_contact_email": "ops@dunmore.example",
        "region_code": "TX",
    },
    "signatory_name": "A. Dunmore",
    "fee_schedules": [
        {
            "role_type": "CHAUFFEUR",
            "comp_band_floor_cents": 0,
            "comp_band_ceiling_cents": 15_000_000,
            "fee_percent_bps": 1500,
            "guarantee_window_days": 60,
            "effective_from": "2026-01-01",
        }
    ],
    "requisition": {
        "role_type": "CHAUFFEUR",
        "first_year_compensation_cents": 5_400_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "scope": {"scope_note": "Two vehicles, evening cover."},
}

# A HOUSEKEEPER search used to walk the candidate's two axes apart.
FOWLER_OPTIONS = {
    "client": {
        "household_name": "Eastcote Grange",
        "primary_contact_email": "ops@eastcote.example",
        "region_code": "MA",
    },
    "signatory_name": "S. Eastcote",
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
        "first_year_compensation_cents": 6_800_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "candidate": {
        "full_name": "N. Fowler",
        "contact_email": "nf@mail.example",
        "primary_role_type": "HOUSEKEEPER",
        "years_experience": 12,
        "live_in_willing": False,
    },
    "references": [
        {
            "principal_employer_name": "Pemberton Family",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2023-01",
            "employment_end_month": "2023-06",
            "contact_email": "pemberton@mail.example",
        },
        {
            "principal_employer_name": "Kingsleigh Family",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2023-07",
            "employment_end_month": "2023-12",
            "contact_email": "kingsleigh@mail.example",
            "chain_to_previous": True,
        },
    ],
    "background": {"provider_reference": "BV-4001", "scope_items": ["IDENTITY", "CRIMINAL"]},
    "trial": {
        "engagement_type": "TRIAL_DAY",
        "day_rate_cents": 30_000,
        "start_at": "2026-08-11T09:00:00Z",
        "end_at": "2026-08-11T17:00:00Z",
    },
}

# A CHAUFFEUR whose vendor keeps coming back inconclusive.
ABERNATHY_OPTIONS = {
    "client": {
        "household_name": "Farnsworth Place",
        "primary_contact_email": "ops@farnsworth.example",
        "region_code": "TX",
    },
    "signatory_name": "W. Farnsworth",
    "fee_schedules": [
        {
            "role_type": "CHAUFFEUR",
            "comp_band_floor_cents": 0,
            "comp_band_ceiling_cents": 15_000_000,
            "fee_percent_bps": 1500,
            "guarantee_window_days": 60,
            "effective_from": "2026-01-01",
        }
    ],
    "requisition": {
        "role_type": "CHAUFFEUR",
        "first_year_compensation_cents": 5_600_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "candidate": {
        "full_name": "K. Abernathy",
        "contact_email": "ka@mail.example",
        "primary_role_type": "CHAUFFEUR",
        "years_experience": 10,
        "live_in_willing": False,
    },
    "references": [
        {
            "principal_employer_name": "Thorncliffe Estate",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2022-01",
            "employment_end_month": "2022-12",
            "contact_email": "thorncliffe@mail.example",
        },
        {
            "principal_employer_name": "Ashgrove House",
            "relationship_type": "PRINCIPAL_EMPLOYER",
            "employment_start_month": "2023-01",
            "employment_end_month": "2023-12",
            "contact_email": "ashgrove@mail.example",
            "chain_to_previous": True,
        },
    ],
    "background": {"provider_reference": "BV-5001", "scope_items": ["IDENTITY", "DMV"]},
}

FEE_STAMP_FIELDS = (
    "resolved_fee_schedule_id",
    "fee_percent_bps",
    "guarantee_window_days",
    "provisional_fee_cents",
)


class TestScopingLoop:
    def test_01_a_re_scope_clears_the_fee_stamp_and_the_next_finalisation_rebuilds_it(self):
        """The stamp exists only between finalize-scope and the next re-scope.

        PRD §3.1: "On the re-scope path specifically, the previously resolved
        commercial terms are discarded: `resolved_fee_schedule_id`,
        `fee_percent_bps`, `guarantee_window_days` and `provisional_fee_cents`
        are all cleared back to null, so that the next finalisation re-resolves
        the fee band from scratch against the revised compensation."

        Design: Difficulty/non_linear_state_machine/requisition_rescope_loop_clears_the_fee_stamp_and_caps_at_three_rounds
        """
        scenario = setup_scenario(stage="sourcing", **DUNMORE_OPTIONS)
        first = scenario["requisition"]
        assert first["status"] == "SOURCING"
        assert first["scoping_round"] == 1
        assert first["fee_percent_bps"] == 1500
        assert first["provisional_fee_cents"] == 810_000

        rescoped = run_scoping_round(
            first,
            scope_note="Household added weekend cover.",
            first_year_compensation_cents=5_800_000,
        )
        assert rescoped["status"] == "SCOPING"
        assert rescoped["scoping_round"] == 2
        for field in FEE_STAMP_FIELDS:
            assert rescoped[field] is None, f"{field} should be cleared on a re-scope"

        second = finalize_scope(rescoped, note="Second scope agreed.")
        assert second["status"] == "SOURCING"
        assert second["first_year_compensation_cents"] == 5_800_000
        assert second["provisional_fee_cents"] == 870_000
        assert second["fee_percent_bps"] == 1500

    def test_02_the_third_round_is_accepted_and_the_fourth_attempt_is_refused(self):
        """The loop is bounded at three rounds and the refusal changes nothing.

        PRD §3.1: "any scoping attempt on a requisition whose `scoping_round` has
        already reached three is refused with `ERR_SCOPING_ROUND_LIMIT` (HTTP
        409) — the third round is accepted and takes `scoping_round` from 2 to 3,
        and it is the fourth attempt that is refused."

        Design: Difficulty/non_linear_state_machine/requisition_rescope_loop_clears_the_fee_stamp_and_caps_at_three_rounds
        """
        scenario = setup_scenario(stage="sourcing", **DUNMORE_OPTIONS)
        requisition = finalize_scope(
            run_scoping_round(
                scenario["requisition"],
                scope_note="Household added weekend cover.",
                first_year_compensation_cents=5_800_000,
            ),
            note="Second scope agreed.",
        )
        requisition = finalize_scope(
            run_scoping_round(
                requisition,
                scope_note="Household reverted to weekday cover.",
                first_year_compensation_cents=5_400_000,
            ),
            note="Third scope agreed.",
        )
        assert requisition["status"] == "SOURCING"
        assert requisition["scoping_round"] == 3
        assert requisition["provisional_fee_cents"] == 810_000
        version_before = requisition["version"]

        response = api_client.scope_requisition(
            requisition["id"],
            scope_requisition_payload(scope_note="A fourth change of mind."),
            CONSULTANT,
        )
        validate_error(response, "ERR_SCOPING_ROUND_LIMIT")

        after = read_requisition(requisition)
        assert after["status"] == "SOURCING"
        assert after["scoping_round"] == 3
        assert after["provisional_fee_cents"] == 810_000
        assert after["version"] == version_before


class TestCandidateAxes:
    def test_03_the_vetting_axis_advances_while_availability_stays_available(self):
        """Three vetting states pass under one unchanged availability value.

        PRD §2.9: "The two axes evolve on their own except for exactly one
        coupling, which runs in exactly one direction: when a candidate's
        `vetting_status` becomes `REJECTED`, its `availability_status` is driven
        from `ON_TRIAL` to `INACTIVE`."

        Design: Difficulty/non_linear_state_machine/candidate_vetting_and_availability_dimensions_advance_independently
        """
        scenario = setup_scenario(stage="references_recorded", **FOWLER_OPTIONS)
        candidate = read_candidate(scenario["candidate"])
        assert (candidate["vetting_status"], candidate["availability_status"]) == (
            "SCREENING",
            "AVAILABLE",
        )

        for reference in scenario["references"]:
            verify_reference(reference)
        candidate = read_candidate(candidate)
        assert (candidate["vetting_status"], candidate["availability_status"]) == (
            "REFERENCES_VERIFIED",
            "AVAILABLE",
        )

        verification = order_background_verification(
            candidate, **FOWLER_OPTIONS["background"]
        )
        candidate = read_candidate(candidate)
        assert (candidate["vetting_status"], candidate["availability_status"]) == (
            "BACKGROUND_PENDING",
            "AVAILABLE",
        )

        record_background_result(verification, "CLEARED")
        candidate = read_candidate(candidate)
        assert (candidate["vetting_status"], candidate["availability_status"]) == (
            "CLEARED",
            "AVAILABLE",
        )
        assert candidate["screening_score"] == 72

    def test_04_the_availability_axis_moves_out_and_back_without_touching_vetting(self):
        """A trial and a failed outcome cycle availability, not vetting.

        PRD §3.4: "`FAILED` moves the engagement `IN_PROGRESS → FAILED`,
        recomputes `active_trial_count`, returns the candidate `ON_TRIAL →
        AVAILABLE` provided the candidate holds no other engagement in
        `SCHEDULED` or `IN_PROGRESS`, and moves the requisition `TRIALING →
        SOURCING` when the recomputed `active_trial_count` reaches 0 and no
        placement on that requisition sits in `PENDING_ACCEPTANCE`."

        Design: Difficulty/non_linear_state_machine/candidate_vetting_and_availability_dimensions_advance_independently
        """
        scenario = setup_scenario(stage="background_recorded", **FOWLER_OPTIONS)
        trial = book_trial(
            scenario["requisition"], scenario["candidate"], **FOWLER_OPTIONS["trial"]
        )
        candidate = read_candidate(scenario["candidate"])
        assert (candidate["vetting_status"], candidate["availability_status"]) == (
            "CLEARED",
            "ON_TRIAL",
        )
        assert read_requisition(scenario["requisition"])["status"] == "TRIALING"

        set_clock("2026-08-11T17:00:00Z")
        start_trial(trial)
        record_trial_outcome(trial, "FAILED")

        candidate = read_candidate(candidate)
        assert (candidate["vetting_status"], candidate["availability_status"]) == (
            "CLEARED",
            "AVAILABLE",
        )
        assert candidate["screening_score"] == 72
        assert read_trial(trial)["status"] == "FAILED"
        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "SOURCING"
        assert requisition["active_trial_count"] == 0


class TestBackgroundSelfLoop:
    def test_05_repeated_inconclusive_results_only_move_the_rerun_counter(self):
        """The self-loop leaves the candidate exactly where it found them.

        PRD §3.3: "`rerun_count` is incremented by exactly 1 each time an
        `INCONCLUSIVE` result is recorded on a screen that is *already*
        `INCONCLUSIVE`, and the re-runs are otherwise observable only through
        that counter."

        Design: Difficulty/non_linear_state_machine/background_inconclusive_self_loop_then_flagged_adjudication_halves_the_points
        """
        scenario = setup_scenario(stage="background_ordered", **ABERNATHY_OPTIONS)
        verification = scenario["background"]
        assert verification["status"] == "INITIATED"
        assert verification["rerun_count"] == 0

        first = record_background_result(verification, "INCONCLUSIVE")
        assert first["status"] == "INCONCLUSIVE"
        assert first["rerun_count"] == 0
        candidate = read_candidate(scenario["candidate"])
        assert candidate["vetting_status"] == "BACKGROUND_PENDING"

        second = record_background_result(verification, "INCONCLUSIVE")
        assert second["status"] == "INCONCLUSIVE"
        assert second["rerun_count"] == 1
        assert second["version"] > first["version"]
        candidate = read_candidate(candidate)
        assert candidate["vetting_status"] == "BACKGROUND_PENDING"
        assert candidate["availability_status"] == "AVAILABLE"
        assert candidate["screening_score"] == 74
        assert candidate["placement_ready_score"] == 74

    def test_06_a_flagged_screen_leaves_the_candidate_pending_until_adjudication(self):
        """FLAGGED moves the screen and nothing else.

        PRD §3.3: "A `result` of `FLAGGED` moves the screen to `FLAGGED` and
        stamps the same two fields, but leaves the candidate at
        `BACKGROUND_PENDING` pending adjudication — no candidate-side movement at
        all."

        Design: Difficulty/non_linear_state_machine/background_inconclusive_self_loop_then_flagged_adjudication_halves_the_points
        """
        scenario = setup_scenario(stage="background_ordered", **ABERNATHY_OPTIONS)
        verification = scenario["background"]
        record_background_result(verification, "INCONCLUSIVE")
        record_background_result(verification, "INCONCLUSIVE")
        flagged = record_background_result(verification, "FLAGGED")
        assert flagged["status"] == "FLAGGED"
        assert flagged["rerun_count"] == 1

        candidate = read_candidate(scenario["candidate"])
        assert candidate["vetting_status"] == "BACKGROUND_PENDING"
        assert candidate["placement_ready_score"] == 74

    def test_07_adjudicated_pass_is_worth_half_of_a_clean_result(self):
        """The waived flag adds 10 background points, not 20.

        PRD §3.3: "**Background points** are 20 when a `BackgroundVerification`
        of this candidate has reached `CLEARED`, 10 when the best status the
        candidate's screens have reached is `ADJUDICATED_PASS` — a waived flag is
        worth half of a clean result — and 0 otherwise."

        Design: Difficulty/non_linear_state_machine/background_inconclusive_self_loop_then_flagged_adjudication_halves_the_points
        """
        scenario = setup_scenario(stage="background_ordered", **ABERNATHY_OPTIONS)
        verification = scenario["background"]
        record_background_result(verification, "INCONCLUSIVE")
        record_background_result(verification, "INCONCLUSIVE")
        record_background_result(verification, "FLAGGED")

        before = read_candidate(scenario["candidate"])
        adjudicated = adjudicate_background(verification, "PASS", before["version"])
        assert adjudicated["status"] == "ADJUDICATED_PASS"
        assert read_background_verification(verification)["rerun_count"] == 1

        after = read_candidate(before)
        assert after["vetting_status"] == "CLEARED"
        assert after["screening_score"] == 74
        assert after["placement_ready_score"] == 84
        assert after["version"] == before["version"] + 1
