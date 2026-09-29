"""Two thresholds probed one unit either side: the 0.75 seminar credit ratio and
the 180-minute daily credit ceiling.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import ERR_DAILY_CREDIT_CAP_REACHED
from test_helpers.assertions import (
    assert_four_decimals,
    assert_money_cents,
    assert_two_decimals,
)
from test_helpers.fixtures import (
    build_program,
    create_cohort,
    create_novice,
    create_site,
    hold_session,
    read_match,
    read_novice,
    read_session,
    record_attendance,
    schedule_seminar_session,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import ADMIN, make_site_lead_headers


class TestSeminarCreditRatioExactThreshold:
    """One minute of attendance separates a credited row from an uncredited one."""

    @staticmethod
    def _two_late_rows_on_a_held_session(api: InductionApiClient) -> dict:
        site = create_site(api)
        cohort = create_cohort(api)
        lead = make_site_lead_headers(site["id"])
        novice_a = create_novice(api, site["id"], cohort["id"], full_name="Dana Pike")
        novice_b = create_novice(
            api,
            site["id"],
            cohort["id"],
            full_name="Eli Navarro",
            subject_area="SCIENCE",
        )
        session = schedule_seminar_session(
            api,
            cohort["id"],
            1,
            "2026-08-03T14:00:00Z",
            "2026-08-03T16:00:00Z",
            topic="Classroom routines seminar",
        )
        row_a = record_attendance(api, session["id"], novice_a["id"], "LATE", 100, lead)
        row_b = record_attendance(api, session["id"], novice_b["id"], "LATE", 99, lead)
        set_clock(api, "2026-08-03T18:00:00Z")
        hold_session(api, session["id"])
        return {
            "session_id": session["id"],
            "novice_a_id": novice_a["id"],
            "novice_b_id": novice_b["id"],
            "row_a_id": row_a["id"],
            "row_b_id": row_b["id"],
        }

    def test_a_ratio_of_exactly_three_quarters_earns_credit(self, api: InductionApiClient):
        """100 late minutes on a 120-minute session is exactly 0.7500 and is credited.

        The PRD puts the boundary inside the credited side: "The row's `credited`
        flag is true only when both conditions hold: `attendance_status` is
        `PRESENT` or `LATE`, and the rounded `credit_ratio` is at least
        three-quarters. A ratio of exactly 0.75 therefore earns credit."

        Design: Difficulty/boundary_precision_check/seminar_credit_ratio_exact_threshold
        """
        context = self._two_late_rows_on_a_held_session(api)

        row = validate_success(api.get_attendance(context["row_a_id"], ADMIN))
        assert_four_decimals(row["credit_ratio"], 0.7500, "credit_ratio")
        assert row["credited"] is True, (
            f"a ratio of exactly 0.75 must be credited, got credited {row['credited']}"
        )

        assert read_session(api, context["session_id"])["credited_attendance_count"] == 1, (
            "only the 100-minute row is credited against the session"
        )
        novice = read_novice(api, context["novice_a_id"])
        assert novice["credited_seminar_sessions"] == 1, (
            "the held session lets the credited row count for the novice, got "
            f"{novice['credited_seminar_sessions']}"
        )
        assert_two_decimals(novice["readiness_index_live"], 25.00, "readiness_index_live")

    def test_one_minute_less_falls_below_the_threshold(self, api: InductionApiClient):
        """99 late minutes rounds to 0.7417 and earns nothing at all.

        The ratio itself is fixed to four places after the flat late penalty: "A
        late arrival forfeits a flat 10 minutes: the effective minutes are the raw
        `minutes_attended` less that penalty for a `LATE` row and the raw minutes
        themselves otherwise, floored at zero so a novice who arrived 5 minutes
        into a session and is marked late does not go negative. The `credit_ratio`
        is then the effective minutes divided by the session's
        `scheduled_minutes`, rounded half up to 4 decimal places."

        Design: Difficulty/boundary_precision_check/seminar_credit_ratio_exact_threshold
        """
        context = self._two_late_rows_on_a_held_session(api)

        row = validate_success(api.get_attendance(context["row_b_id"], ADMIN))
        assert_four_decimals(row["credit_ratio"], 0.7417, "credit_ratio")
        assert row["credited"] is False, (
            f"89 effective minutes over 120 is below the gate, got credited {row['credited']}"
        )

        novice = read_novice(api, context["novice_b_id"])
        assert novice["credited_seminar_sessions"] == 0, (
            f"an uncredited row counts for nothing, got {novice['credited_seminar_sessions']}"
        )
        assert_two_decimals(novice["readiness_index_live"], 0.00, "readiness_index_live")


class TestDailyCreditCapExactBoundary:
    """179 credited minutes leaves exactly one minute of room; 180 leaves none."""

    @staticmethod
    def _day_with_one_minute_left(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-08T12:00:00Z")
        first = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-07T09:00:00Z",
            minutes=179,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
        )
        verify_contact_log(api, first["id"], lead)
        second = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-07T13:00:00Z",
            minutes=100,
            contact_type="DEBRIEF",
            mentor_id=program["mentor_id"],
            description="Extended debrief on the observed lesson segment and next steps",
        )
        third = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-07T16:00:00Z",
            minutes=30,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Short one-on-one check-in late in the school day about pacing",
        )
        program["lead"] = lead
        program["first_log_id"] = first["id"]
        program["second_log_id"] = second["id"]
        program["third_log_id"] = third["id"]
        return program

    def test_the_last_remaining_minute_is_still_credited(self, api: InductionApiClient):
        """A 75-minute weighted claim is truncated to the single minute of room left.

        The PRD gives the boundary in both directions: "At exactly 180
        already-credited minutes the next verification is refused; at 179 it
        succeeds and is truncated down to a single credited minute."

        Design: Difficulty/boundary_precision_check/daily_credit_cap_exact_boundary
        """
        program = self._day_with_one_minute_left(api)

        first = validate_success(api.get_contact_log(program["first_log_id"], ADMIN))
        assert first["credited_minutes"] == 179, (
            f"a 179-minute one-on-one credits 179, got {first['credited_minutes']}"
        )
        assert_money_cents(first["stipend_cents"], 12530, "stipend_cents")

        second = validate_success(
            api.review_contact_log(
                program["second_log_id"],
                f.review_payload("VERIFY", note="Debrief confirmed by the observing lead"),
                program["lead"],
            )
        )
        assert second["verification_status"] == "VERIFIED", (
            "one minute of room is still room, so the review succeeds"
        )
        assert second["credited_minutes"] == 1, (
            "floor(100 * 0.75) = 75 weighted minutes clip to the single remaining "
            f"minute, got {second['credited_minutes']}"
        )
        assert_money_cents(second["stipend_cents"], 70, "stipend_cents")

        match = read_match(api, program["match_id"])
        assert match["verified_minutes_total"] == 180, (
            f"the day lands exactly on the ceiling, got {match['verified_minutes_total']}"
        )
        assert_money_cents(match["accrued_stipend_cents"], 12600, "accrued_stipend_cents")

    def test_the_next_verification_on_a_full_day_is_refused(self, api: InductionApiClient):
        """Once the day holds 180 credited minutes the following review is refused.

        The PRD prefers a refusal to a zero: "If the already-credited total for
        that match and date has reached the full three hours, so that no room at
        all remains, the verification is refused outright with
        `ERR_DAILY_CREDIT_CAP_REACHED` rather than producing a zero-minute
        credit."

        Design: Difficulty/boundary_precision_check/daily_credit_cap_exact_boundary
        """
        program = self._day_with_one_minute_left(api)
        validate_success(
            api.review_contact_log(
                program["second_log_id"],
                f.review_payload("VERIFY", note="Debrief confirmed by the observing lead"),
                program["lead"],
            )
        )

        response = api.review_contact_log(
            program["third_log_id"],
            f.review_payload("VERIFY", note="Third log of the same day"),
            program["lead"],
        )
        validate_error(response, ERR_DAILY_CREDIT_CAP_REACHED, 422)

        third = validate_success(api.get_contact_log(program["third_log_id"], ADMIN))
        assert third["verification_status"] == "SUBMITTED", (
            f"the refused review leaves the log alone, got {third['verification_status']}"
        )
        assert third["credited_minutes"] == 0, "a refused review credits nothing"
        assert read_match(api, program["match_id"])["verified_minutes_total"] == 180
