"""Requests that break two declared rules at once.

Each test drives a payload that is refused twice over, asserts which of the two
errors the PRD ranks first, and then isolates the losing rule on its own so the
ordering — not merely the presence of one error — is what is measured.
"""
from test_helpers import (
    CONSULTANT,
    RECORDER,
    add_vetted_candidate,
    api_client,
    append_ledger_adjustment,
    create_reference_check_payload,
    create_trial_engagement_payload,
    read_candidate,
    read_client,
    read_reference,
    read_requisition,
    read_trial,
    record_reference,
    record_trial_outcome_payload,
    register_candidate,
    set_clock,
    setup_scenario,
    start_trial,
    validate_error,
    validate_paginated,
    verify_reference,
)

# A HOUSEKEEPER search whose trial day is asked for a verdict while the day is
# still running.
IVERSEN_OPTIONS = {
    "client": {
        "household_name": "Harlow Court",
        "primary_contact_email": "ops@harlow.example",
        "region_code": "NY",
    },
    "signatory_name": "R. Harlow",
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
        "first_year_compensation_cents": 6_600_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "candidate": {
        "full_name": "B. Iversen",
        "contact_email": "bi@mail.example",
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
        "provider_reference": "BV-7001",
        "scope_items": ["IDENTITY", "CRIMINAL"],
    },
    "trial": {
        "engagement_type": "TRIAL_DAY",
        "day_rate_cents": 30_000,
        "start_at": "2026-08-13T09:00:00Z",
        "end_at": "2026-08-13T17:00:00Z",
    },
}

# The same role for a household that is over its credit limit, shown a
# candidate who scores 69 on the screening variant.
HALLORAN_OPTIONS = {
    "client": {
        "household_name": "Inglewood Manor",
        "primary_contact_email": "ops@inglewood.example",
        "region_code": "CA",
    },
    "signatory_name": "P. Inglewood",
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
        "first_year_compensation_cents": 6_400_000,
        "schedule_pattern": "FIVE_TWO",
        "live_in_required": False,
    },
    "candidate": {
        "full_name": "D. Halloran",
        "contact_email": "dh@mail.example",
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
            "employment_end_month": "2024-03",
            "contact_email": "latimer@mail.example",
            "chain_to_previous": True,
        },
    ],
    "background": {
        "provider_reference": "BV-7101",
        "scope_items": ["IDENTITY", "CRIMINAL"],
    },
}

OVER_THE_LIMIT_CENTS = 5_000_001

# The chain head every reference-ordering test starts from.
NAKAMURA_CANDIDATE = {
    "full_name": "E. Nakamura",
    "contact_email": "en@mail.example",
    "primary_role_type": "CHEF",
    "years_experience": 9,
    "live_in_willing": False,
}
OSBORNE_REFERENCE = {
    "principal_employer_name": "Osborne Residence",
    "relationship_type": "PRINCIPAL_EMPLOYER",
    "employment_start_month": "2023-01",
    "employment_end_month": "2023-12",
    "contact_email": "osborne@mail.example",
}
# 2023-06 sits before the chain head's end month and inside its interval, so
# this payload breaks continuity and overlap together.
PENNINGTON_REFERENCE = {
    "principal_employer_name": "Pennington House",
    "relationship_type": "PRINCIPAL_EMPLOYER",
    "employment_start_month": "2023-06",
    "employment_end_month": "2024-05",
    "contact_email": "pennington@mail.example",
}


def _candidate_with_one_verified_year():
    candidate = register_candidate(**NAKAMURA_CANDIDATE)
    head = verify_reference(record_reference(candidate, **OSBORNE_REFERENCE))
    assert head["status"] == "VERIFIED"
    return read_candidate(candidate), head


def _reference_rows(candidate):
    rows, _ = validate_paginated(
        api_client.list_candidate_reference_checks(candidate["id"], RECORDER)
    )
    return rows


class TestTrialStateOutranksTrialWindow:
    def test_01_a_verdict_on_a_scheduled_trial_reports_the_state_error(self):
        """The clock is inside the day, so both the state and the window fail.

        PRD §3.4: "These two conditions interact in a way an implementer must get
        right: the state check ranks above the temporal one, so recording an
        outcome on a `SCHEDULED` engagement whose `end_at` has not been reached
        breaks both rules and must surface `ERR_TRIAL_NOT_IN_PROGRESS`, not
        `ERR_TRIAL_WINDOW_NOT_ELAPSED`."

        Design: Difficulty/priority_pair_validation_conflict/trial_state_check_at_fifty_outranks_the_window_check_at_seventysix
        """
        scenario = setup_scenario(stage="trial_booked", **IVERSEN_OPTIONS)
        trial = scenario["trial"]
        assert trial["status"] == "SCHEDULED"

        set_clock("2026-08-13T14:00:00Z")
        response = api_client.record_trial_outcome(
            trial["id"], record_trial_outcome_payload("PASSED"), CONSULTANT
        )
        validate_error(response, "ERR_TRIAL_NOT_IN_PROGRESS")

        after = read_trial(trial)
        assert after["status"] == "SCHEDULED"
        assert after["outcome_note"] is None
        assert after["version"] == trial["version"]
        assert read_requisition(scenario["requisition"])["status"] == "TRIALING"
        assert read_candidate(scenario["candidate"])["availability_status"] == "ON_TRIAL"

    def test_02_starting_the_trial_first_exposes_the_window_error(self):
        """With the state rule satisfied the losing rule surfaces on its own.

        PRD §3.4: "The engagement must be `IN_PROGRESS`, or the request is refused
        with `ERR_TRIAL_NOT_IN_PROGRESS`; the logical clock must be at or after
        `end_at`, or it is refused with `ERR_TRIAL_WINDOW_NOT_ELAPSED`."

        Design: Difficulty/priority_pair_validation_conflict/trial_state_check_at_fifty_outranks_the_window_check_at_seventysix
        """
        scenario = setup_scenario(stage="trial_booked", **IVERSEN_OPTIONS)
        set_clock("2026-08-13T14:00:00Z")
        started = start_trial(scenario["trial"])
        assert started["status"] == "IN_PROGRESS"

        response = api_client.record_trial_outcome(
            started["id"], record_trial_outcome_payload("PASSED"), CONSULTANT
        )
        validate_error(response, "ERR_TRIAL_WINDOW_NOT_ELAPSED")

        after = read_trial(started)
        assert after["status"] == "IN_PROGRESS"
        assert after["version"] == started["version"]
        assert read_requisition(scenario["requisition"])["active_trial_count"] == 1


class TestScoreGateOutranksCreditHold:
    def _household_over_its_limit(self):
        scenario = setup_scenario(stage="background_recorded", **HALLORAN_OPTIONS)
        append_ledger_adjustment(
            scenario["client"],
            OVER_THE_LIMIT_CENTS,
            memo="Carried arrears from a prior search.",
        )
        client = read_client(scenario["client"])
        assert client["outstanding_balance_cents"] == OVER_THE_LIMIT_CENTS
        return scenario

    def test_03_the_candidate_is_named_before_the_receivable(self):
        """A 69-point candidate on an over-limit household reports the score.

        PRD §3.4: "That ordering is deliberate and load-bearing — a household that
        is simultaneously over its credit limit and being shown an under-scoring
        candidate is told about the candidate, because a safety judgement about
        who enters a home is never traded against a receivable."

        Design: Difficulty/priority_pair_validation_conflict/score_gate_at_seventynine_outranks_the_credit_hold_at_eightysix
        """
        scenario = self._household_over_its_limit()
        candidate = read_candidate(scenario["candidate"])
        assert candidate["vetting_status"] == "CLEARED"
        assert candidate["reference_coverage_months"] == 15
        assert candidate["screening_score"] == 69

        response = api_client.create_trial_engagement(
            scenario["requisition"]["id"],
            create_trial_engagement_payload(
                candidate["id"],
                engagement_type="TRIAL_DAY",
                day_rate_cents=30_000,
                start_at="2026-08-14T09:00:00Z",
                end_at="2026-08-14T17:00:00Z",
            ),
            CONSULTANT,
        )
        validate_error(response, "ERR_CANDIDATE_SCORE_BELOW_THRESHOLD")

        rows, _ = validate_paginated(
            api_client.list_trial_engagements(
                CONSULTANT, {"requisition_id": scenario["requisition"]["id"]}
            )
        )
        assert rows == []
        requisition = read_requisition(scenario["requisition"])
        assert requisition["status"] == "SOURCING"
        assert requisition["active_trial_count"] == 0
        assert read_candidate(candidate)["availability_status"] == "AVAILABLE"

    def test_04_a_scoring_candidate_on_the_same_household_reports_the_hold(self):
        """Clearing the score gate lets the receivable rule be reached.

        PRD §2.12: "When a household's `outstanding_balance_cents` is **strictly
        greater** than 5,000,000 cents — fifty thousand dollars — it is on
        **credit hold**, and neither a new trial booking nor a new offer may be
        made for it; both are refused with `ERR_CLIENT_CREDIT_HOLD` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/score_gate_at_seventynine_outranks_the_credit_hold_at_eightysix
        """
        scenario = self._household_over_its_limit()
        scoring = add_vetted_candidate(
            full_name="M. Tarleton",
            contact_email="mt@mail.example",
            reference_prefix="Tarleton",
            primary_role_type="HOUSEKEEPER",
            years_experience=10,
            live_in_willing=False,
        )
        assert scoring["screening_score"] == 74

        response = api_client.create_trial_engagement(
            scenario["requisition"]["id"],
            create_trial_engagement_payload(
                scoring["id"],
                engagement_type="TRIAL_DAY",
                day_rate_cents=30_000,
                start_at="2026-08-14T09:00:00Z",
                end_at="2026-08-14T17:00:00Z",
            ),
            CONSULTANT,
        )
        validate_error(response, "ERR_CLIENT_CREDIT_HOLD")

        assert read_requisition(scenario["requisition"])["status"] == "SOURCING"
        assert read_candidate(scoring)["availability_status"] == "AVAILABLE"


class TestChainContinuityOutranksPeriodOverlap:
    def test_05_a_backwards_chain_pointer_inside_the_prior_interval_reports_the_chain(self):
        """The pointer breaks continuity and the months overlap; chain wins.

        PRD §3.3: "A payload that violates both rules at once reports the chain
        mismatch, since continuity outranks overlap."

        Design: Difficulty/priority_pair_validation_conflict/chain_continuity_at_seventyone_outranks_the_period_overlap_at_ninety
        """
        candidate, head = _candidate_with_one_verified_year()
        assert candidate["verified_reference_count"] == 1
        assert candidate["reference_coverage_months"] == 12

        payload = create_reference_check_payload(**PENNINGTON_REFERENCE)
        payload["prior_reference_id"] = head["id"]
        response = api_client.create_reference_check(
            candidate["id"], payload, RECORDER
        )
        validate_error(response, "ERR_REFERENCE_CHAIN_MISMATCH")

        assert len(_reference_rows(candidate)) == 1
        after = read_candidate(candidate)
        assert after["verified_reference_count"] == 1
        assert after["reference_coverage_months"] == 12
        assert after["version"] == candidate["version"]
        assert read_reference(head)["status"] == "VERIFIED"

    def test_06_the_same_months_without_a_chain_pointer_report_the_overlap(self):
        """Dropping the pointer leaves only the second rule to fail.

        PRD §3.3: "**Period overlap** comes second: the proposed closed month
        interval from `employment_start_month` through `employment_end_month` must
        not intersect the interval of any existing reference for the same
        candidate whose `status` is anything other than `UNREACHABLE`, and an
        intersection is refused with `ERR_REFERENCE_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/chain_continuity_at_seventyone_outranks_the_period_overlap_at_ninety
        """
        candidate, _ = _candidate_with_one_verified_year()

        response = api_client.create_reference_check(
            candidate["id"],
            create_reference_check_payload(**PENNINGTON_REFERENCE),
            RECORDER,
        )
        validate_error(response, "ERR_REFERENCE_PERIOD_OVERLAP")

        assert len(_reference_rows(candidate)) == 1
        assert read_candidate(candidate)["reference_coverage_months"] == 12

    def test_07_an_adjacent_period_behind_a_legal_pointer_is_accepted(self):
        """Neither rule fires when the new period starts the following month.

        PRD §3.3: "Because these intervals are closed, sharing even a single
        month is an overlap, whereas one period ending in December and the next
        beginning the following January is adjacency and is accepted."

        Design: Difficulty/priority_pair_validation_conflict/chain_continuity_at_seventyone_outranks_the_period_overlap_at_ninety
        """
        candidate, head = _candidate_with_one_verified_year()

        chained = record_reference(
            candidate,
            prior_reference_id=head["id"],
            principal_employer_name="Pennington House",
            relationship_type="PRINCIPAL_EMPLOYER",
            employment_start_month="2024-01",
            employment_end_month="2024-12",
            contact_email="pennington@mail.example",
        )
        assert chained["status"] == "PENDING"
        assert chained["prior_reference_id"] == head["id"]
        assert len(_reference_rows(candidate)) == 2

        verify_reference(chained)
        after = read_candidate(candidate)
        assert after["verified_reference_count"] == 2
        assert after["reference_coverage_months"] == 24
        assert after["longest_contiguous_months"] == 24
        assert after["vetting_status"] == "REFERENCES_VERIFIED"
