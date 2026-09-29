"""Three shared resources booked against time: the household's changeover
buffer, a candidate's employment months, and a candidate's ISO week.

Every case pins the exact edge — the minute at which a buffered window opens, the
month at which two intervals stop merging and start colliding, and the week key
that carries a finished trial's slot.
"""
from test_helpers import (
    CONSULTANT,
    RECORDER,
    api_client,
    book_trial,
    create_reference_check_payload,
    create_trial_engagement_payload,
    order_background_verification,
    read_candidate,
    read_requisition,
    read_trial,
    record_background_result,
    record_reference,
    record_trial_outcome,
    register_candidate,
    set_clock,
    setup_scenario,
    start_trial,
    validate_error,
    validate_paginated,
    verify_reference,
)

# A HOUSEKEEPER search on which two candidates are shown on the same day.
OAKHURST_OPTIONS = {
    "client": {
        "household_name": "Oakhurst Place",
        "primary_contact_email": "ops@oakhurst.example",
        "region_code": "TX",
    },
    "signatory_name": "J. Oakhurst",
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
        "first_year_compensation_cents": 6_900_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "candidate": {
        "full_name": "A. Bergstrom",
        "contact_email": "ab@mail.example",
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
    "background": {
        "provider_reference": "BV-1201",
        "scope_items": ["IDENTITY", "CRIMINAL"],
    },
    "trial": {
        "engagement_type": "TRIAL_DAY",
        "day_rate_cents": 30_000,
        "start_at": "2026-08-18T09:00:00Z",
        "end_at": "2026-08-18T17:00:00Z",
    },
}

# A CHAUFFEUR search used to fill one ISO week with finished trials.
PELHAM_OPTIONS = {
    "client": {
        "household_name": "Pelham Gardens",
        "primary_contact_email": "ops@pelham.example",
        "region_code": "TX",
    },
    "signatory_name": "K. Pelham",
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
        "full_name": "M. Ferreira",
        "contact_email": "mf@mail.example",
        "primary_role_type": "CHAUFFEUR",
        "years_experience": 12,
        "live_in_willing": True,
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
    "background": {
        "provider_reference": "BV-1301",
        "scope_items": ["IDENTITY", "DMV"],
    },
}

WEEK_33_TRIALS = (
    {
        "engagement_type": "TRIAL_DAY",
        "day_rate_cents": 28_000,
        "start_at": "2026-08-10T09:00:00Z",
        "end_at": "2026-08-10T17:00:00Z",
    },
    {
        "engagement_type": "TRIAL_DAY",
        "day_rate_cents": 28_000,
        "start_at": "2026-08-12T09:00:00Z",
        "end_at": "2026-08-12T17:00:00Z",
    },
)


def _second_housekeeper():
    """A. Bergstrom's rival on the same household: 12 years and 12 verified
    months split across two adjacent halves of 2022."""
    candidate = register_candidate(
        full_name="C. Delacroix",
        contact_email="cd@mail.example",
        primary_role_type="HOUSEKEEPER",
        years_experience=12,
        live_in_willing=False,
    )
    first = record_reference(
        candidate,
        principal_employer_name="Quimby Family",
        employment_start_month="2022-01",
        employment_end_month="2022-06",
        contact_email="quimby@mail.example",
    )
    second = record_reference(
        candidate,
        prior_reference_id=first["id"],
        principal_employer_name="Rothwell Family",
        employment_start_month="2022-07",
        employment_end_month="2022-12",
        contact_email="rothwell@mail.example",
    )
    verify_reference(first)
    verify_reference(second)
    record_background_result(
        order_background_verification(
            candidate,
            provider_reference="BV-1202",
            scope_items=["IDENTITY", "CRIMINAL"],
        ),
        "CLEARED",
    )
    return read_candidate(candidate)


def _two_failed_trials_in_week_33():
    scenario = setup_scenario(stage="background_recorded", **PELHAM_OPTIONS)
    scenario["trials"] = []
    for booking in WEEK_33_TRIALS:
        trial = book_trial(scenario["requisition"], scenario["candidate"], **booking)
        set_clock(booking["end_at"])
        start_trial(trial)
        scenario["trials"].append(record_trial_outcome(trial, "FAILED"))
    return scenario


class TestHouseholdChangeoverBuffer:
    def test_01_a_start_one_minute_inside_the_buffer_is_refused(self):
        """17:00 plus two hours is 19:00, so 18:59 still collides.

        PRD §3.4: "Because both intervals are half-open, the arithmetic is exact:
        after an engagement running 09:00 to 17:00 on a given day, the next
        admissible start for that same household is 19:00 exactly, and a start at
        18:59 is refused."

        Design: Difficulty/resource_temporal_overlap/household_trial_buffer_rejects_one_minute_inside_and_admits_the_boundary
        """
        scenario = setup_scenario(stage="trial_booked", **OAKHURST_OPTIONS)
        assert scenario["trial"]["status"] == "SCHEDULED"
        assert scenario["trial"]["start_at"].startswith("2026-08-18T09:00:00")

        rival = _second_housekeeper()
        assert rival["screening_score"] == 72
        assert rival["vetting_status"] == "CLEARED"
        assert rival["availability_status"] == "AVAILABLE"

        response = api_client.create_trial_engagement(
            scenario["requisition"]["id"],
            create_trial_engagement_payload(
                rival["id"],
                engagement_type="WORKING_INTERVIEW",
                day_rate_cents=0,
                start_at="2026-08-18T18:59:00Z",
                end_at="2026-08-18T22:00:00Z",
            ),
            CONSULTANT,
        )
        validate_error(response, "ERR_TRIAL_OVERLAP")

        rows, _ = validate_paginated(
            api_client.list_trial_engagements(
                CONSULTANT, {"client_id": scenario["client"]["id"]}
            )
        )
        assert len(rows) == 1
        assert read_requisition(scenario["requisition"])["active_trial_count"] == 1

    def test_02_the_boundary_minute_itself_is_admitted(self):
        """One minute later the buffered interval has closed.

        PRD §3.4: "Concretely: for every other `TrialEngagement` sharing this
        `client_id` whose `status` is `SCHEDULED` or `IN_PROGRESS`, form its
        occupancy interval by taking its `start_at` less two hours as the inclusive
        lower bound and its `end_at` plus two hours as the exclusive upper bound;
        if that interval intersects the proposed window, taken as `start_at`
        inclusive to `end_at` exclusive, the booking is refused with
        `ERR_TRIAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/household_trial_buffer_rejects_one_minute_inside_and_admits_the_boundary
        """
        scenario = setup_scenario(stage="trial_booked", **OAKHURST_OPTIONS)
        rival = _second_housekeeper()
        validate_error(
            api_client.create_trial_engagement(
                scenario["requisition"]["id"],
                create_trial_engagement_payload(
                    rival["id"],
                    engagement_type="WORKING_INTERVIEW",
                    day_rate_cents=0,
                    start_at="2026-08-18T18:59:00Z",
                    end_at="2026-08-18T22:00:00Z",
                ),
                CONSULTANT,
            ),
            "ERR_TRIAL_OVERLAP",
        )

        response = api_client.create_trial_engagement(
            scenario["requisition"]["id"],
            create_trial_engagement_payload(
                rival["id"],
                engagement_type="WORKING_INTERVIEW",
                day_rate_cents=0,
                start_at="2026-08-18T19:00:00Z",
                end_at="2026-08-18T22:00:00Z",
            ),
            CONSULTANT,
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["status"] == "SCHEDULED"

        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "TRIALING"
        assert requisition["active_trial_count"] == 2
        rows, _ = validate_paginated(
            api_client.list_trial_engagements(
                CONSULTANT, {"client_id": scenario["client"]["id"]}
            )
        )
        assert len(rows) == 2


class TestReferenceMonthIntervals:
    def test_03_adjacent_months_merge_into_one_run(self):
        """Two rows meeting at the 2023-12 / 2024-01 seam count as sixteen.

        PRD §3.3: "The intervals are sorted by start month and then merged
        pairwise whenever two of them either overlap or are *adjacent*, where
        adjacency means the next interval's start month is the calendar month
        immediately following the previous interval's end month, leaving a gap of
        zero months."

        Design: Difficulty/resource_temporal_overlap/adjacent_reference_months_merge_and_an_overlapping_month_is_refused
        """
        candidate = register_candidate(
            full_name="I. Solberg",
            contact_email="is@mail.example",
            primary_role_type="CHAUFFEUR",
            years_experience=8,
            live_in_willing=True,
        )
        first = record_reference(
            candidate,
            principal_employer_name="Cadogan Family",
            employment_start_month="2023-01",
            employment_end_month="2023-12",
            contact_email="cadogan@mail.example",
        )
        second = record_reference(
            candidate,
            prior_reference_id=first["id"],
            principal_employer_name="Latimer Family",
            employment_start_month="2024-01",
            employment_end_month="2024-04",
            contact_email="latimer@mail.example",
        )
        verify_reference(first)
        verify_reference(second)

        after = read_candidate(candidate)
        assert after["verified_reference_count"] == 2
        assert after["reference_coverage_months"] == 16
        assert after["longest_contiguous_months"] == 16
        assert after["vetting_status"] == "REFERENCES_VERIFIED"

    def _solberg_with_sixteen_merged_months(self):
        candidate = register_candidate(
            full_name="I. Solberg",
            contact_email="is@mail.example",
            primary_role_type="CHAUFFEUR",
            years_experience=8,
            live_in_willing=True,
        )
        first = record_reference(
            candidate,
            principal_employer_name="Cadogan Family",
            employment_start_month="2023-01",
            employment_end_month="2023-12",
            contact_email="cadogan@mail.example",
        )
        second = record_reference(
            candidate,
            prior_reference_id=first["id"],
            principal_employer_name="Latimer Family",
            employment_start_month="2024-01",
            employment_end_month="2024-04",
            contact_email="latimer@mail.example",
        )
        verify_reference(first)
        verify_reference(second)
        return read_candidate(candidate)

    def test_04_a_single_shared_month_is_an_overlap(self):
        """2024-04 is already occupied, so the new row collides on one month.

        PRD §3.3: "**Period overlap** comes second: the proposed closed month
        interval from `employment_start_month` through `employment_end_month` must
        not intersect the interval of any existing reference for the same candidate
        whose `status` is anything other than `UNREACHABLE`, and an intersection is
        refused with `ERR_REFERENCE_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/adjacent_reference_months_merge_and_an_overlapping_month_is_refused
        """
        candidate = self._solberg_with_sixteen_merged_months()

        response = api_client.create_reference_check(
            candidate["id"],
            create_reference_check_payload(
                principal_employer_name="Thorneycroft Family",
                relationship_type="AGENCY_SUPERVISOR",
                employment_start_month="2024-04",
                employment_end_month="2024-08",
                contact_email="thorneycroft@mail.example",
            ),
            RECORDER,
        )
        validate_error(response, "ERR_REFERENCE_PERIOD_OVERLAP")

        rows, _ = validate_paginated(
            api_client.list_candidate_reference_checks(candidate["id"], RECORDER)
        )
        assert len(rows) == 2
        after = read_candidate(candidate)
        assert after["reference_coverage_months"] == 16
        assert after["version"] == candidate["version"]


class TestWeeklyTrialCap:
    def test_05_two_finished_trials_still_consume_the_week(self):
        """Both rows are FAILED and both still count against the cap.

        PRD §3.4: "Note which statuses are counted and which are not: an
        engagement that was `CANCELLED` does not consume a slot, while one that
        already `PASSED` or `FAILED` does."

        Design: Difficulty/resource_temporal_overlap/weekly_trial_cap_counts_finished_rows_in_the_same_iso_week
        """
        scenario = _two_failed_trials_in_week_33()
        for trial in scenario["trials"]:
            assert trial["status"] == "FAILED"
            assert trial["iso_week_key"] == "2026-W33"

        candidate = read_candidate(scenario["candidate"])
        assert candidate["availability_status"] == "AVAILABLE"
        assert candidate["vetting_status"] == "CLEARED"
        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "SOURCING"
        assert requisition["active_trial_count"] == 0

        response = api_client.create_trial_engagement(
            requisition["id"],
            create_trial_engagement_payload(
                candidate["id"],
                engagement_type="TRIAL_DAY",
                day_rate_cents=28_000,
                start_at="2026-08-14T09:00:00Z",
                end_at="2026-08-14T17:00:00Z",
            ),
            CONSULTANT,
        )
        validate_error(response, "ERR_TRIAL_WEEKLY_CAP_EXCEEDED")

        rows, _ = validate_paginated(
            api_client.list_trial_engagements(
                CONSULTANT, {"candidate_id": candidate["id"]}
            )
        )
        assert len(rows) == 2

    def test_06_the_same_booking_in_the_following_week_is_admitted(self):
        """The cap is keyed on iso_week_key, so 2026-W34 starts empty.

        PRD §3.4: "Count the candidate's existing `TrialEngagement` rows whose
        `iso_week_key` equals the proposed row's `iso_week_key` and whose `status`
        is `SCHEDULED`, `IN_PROGRESS`, `PASSED` or `FAILED`; if that count has
        already reached two, the booking is refused with
        `ERR_TRIAL_WEEKLY_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/weekly_trial_cap_counts_finished_rows_in_the_same_iso_week
        """
        scenario = _two_failed_trials_in_week_33()
        validate_error(
            api_client.create_trial_engagement(
                scenario["requisition"]["id"],
                create_trial_engagement_payload(
                    scenario["candidate"]["id"],
                    engagement_type="TRIAL_DAY",
                    day_rate_cents=28_000,
                    start_at="2026-08-14T09:00:00Z",
                    end_at="2026-08-14T17:00:00Z",
                ),
                CONSULTANT,
            ),
            "ERR_TRIAL_WEEKLY_CAP_EXCEEDED",
        )

        admitted = book_trial(
            scenario["requisition"],
            scenario["candidate"],
            engagement_type="TRIAL_DAY",
            day_rate_cents=28_000,
            start_at="2026-08-17T09:00:00Z",
            end_at="2026-08-17T17:00:00Z",
        )
        assert admitted["status"] == "SCHEDULED"
        assert admitted["iso_week_key"] == "2026-W34"
        assert read_trial(admitted)["client_id"] == scenario["client"]["id"]

        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "TRIALING"
        assert requisition["active_trial_count"] == 1
        assert read_candidate(scenario["candidate"])["availability_status"] == "ON_TRIAL"
