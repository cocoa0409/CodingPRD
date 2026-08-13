"""Capacity reporting: utilization basis points and outcome deltas."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    book_session,
    complete_session,
    create_counselor,
    create_outcome_measure_payload,
    make_clinical_director_headers,
    make_counselor_headers,
    setup_open_episode,
    validate_success,
)

CD = TEST_USERS["clinical_director_headers"]


def _setup_report_scenario():
    """Two active counselors at 10 sessions/week; one student with a
    MODERATE STUDENT_FEE episode under counselor A; four past sessions
    (60+60+60+45 minutes) completed after the clock advances."""
    # Counselor B is a second active counselor counted in bookable minutes.
    create_counselor(license_id="LIC-B", full_name="Coun B",
                     weekly_capacity=10, max_risk_points=1000)
    counselor, student, episode = setup_open_episode(
        student_number="S400", full_name="Rep Stud",
        license_id="LIC-A", weekly_capacity=10, max_risk_points=1000,
        base_session_limit=8, no_show_strike_limit=3)
    return counselor, student, episode


class TestCapacityReport:

    def _build(self):
        counselor, student, episode = _setup_report_scenario()
        sessions = [
            book_session(episode["id"], counselor["id"],
                         "2026-08-02T14:00:00Z", 60),
            book_session(episode["id"], counselor["id"],
                         "2026-08-02T16:00:00Z", 60),
            book_session(episode["id"], counselor["id"],
                         "2026-08-03T14:00:00Z", 60),
            book_session(episode["id"], counselor["id"],
                         "2026-08-03T16:00:00Z", 45),
        ]
        advance_clock("2026-08-04T00:00:00Z")
        for s in sessions:
            complete_session(s["id"], counselor["id"])
        return counselor

    def test_capacity_report_delivered_and_bookable_minutes(self):
        """PRD section 3.9: "`delivered_minutes` sums the `duration_minutes`
        of all `COMPLETED` sessions belonging to episodes in the term.
        `bookable_minutes` sums, over every active counselor, the
        `weekly_individual_capacity` multiplied by sixty minutes and by the
        fifteen weeks of a term."

        60+60+60+45 = 225 delivered; 2 counselors x 10/wk x 60min x 15wk =
        18000 bookable.

        Design: Difficulty/combinatorial_formula/capacity_report_evaluation_order_pinned
        """
        self._build()
        report = validate_success(api_client.get_capacity_report(
            CD, params={"academic_term": "2026-FALL"}))
        assert report["delivered_minutes"] == 225, \
            f"delivered must be 225, got {report['delivered_minutes']}"
        assert report["bookable_minutes"] == 18000, \
            f"bookable must be 18000, got {report['bookable_minutes']}"

    def test_capacity_report_utilization_bps_rounded_last(self):
        """PRD section 3.9: "`utilization_bps` divides delivered by bookable,
        scales by ten thousand so the integer result reads in basis points
        (ten thousand equals one hundred percent utilization), rounds half up,
        and reports zero whenever bookable minutes are zero."

        round_half_up(10000 * 225 / 18000) = 125 — the division and single
        half-up rounding happen last, after both aggregates.

        Design: Difficulty/combinatorial_formula/capacity_report_evaluation_order_pinned
        """
        self._build()
        report = validate_success(api_client.get_capacity_report(
            CD, params={"academic_term": "2026-FALL"}))
        assert report["utilization_bps"] == 125, \
            f"utilization must be 125 bps, got {report['utilization_bps']}"


class TestOutcomeDelta:

    def test_outcome_measure_recording_and_report_delta(self):
        """PRD section 3.9: "`outcomes_delta` averages, per instrument, the
        discharge score minus the baseline score across episodes closed in the
        term that carry both a `BASELINE` and a `DISCHARGE` administration,
        reported to two decimal places rounded half up."
        PRD section 3.9: "`utilization_bps` divides delivered by bookable,
        scales by ten thousand so the integer result reads in basis points
        (ten thousand equals one hundred percent utilization), rounds half up,
        and reports zero whenever bookable minutes are zero."

        Design: Corner/endpoints/outcome_measure_recording_and_report_delta
        """
        counselor, student, episode = setup_open_episode(
            student_number="P300", full_name="Outcome Stud",
            license_id="LIC-P3", weekly_capacity=10, no_show_strike_limit=5)
        c_headers = make_counselor_headers(counselor["id"])
        validate_success(api_client.create_outcome_measure(
            create_outcome_measure_payload(episode["id"], instrument="PHQ9",
                                           phase="BASELINE", score=15),
            c_headers), expected_status=201)
        validate_success(api_client.create_outcome_measure(
            create_outcome_measure_payload(episode["id"], instrument="PHQ9",
                                           phase="DISCHARGE", score=7),
            c_headers), expected_status=201)
        validate_success(api_client.close_episode(episode["id"], c_headers))
        report = validate_success(api_client.get_capacity_report(
            make_clinical_director_headers(counselor["id"]),
            params={"academic_term": "2026-FALL"}))
        assert report["outcomes_delta"] == pytest.approx(-8.0, abs=0.01), \
            f"mean of (7 - 15) over the single qualifying episode is -8.00, got {report['outcomes_delta']}"
        assert report["utilization_bps"] == 0, \
            "no COMPLETED sessions this term means zero utilization"
