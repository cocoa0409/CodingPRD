"""Two interval rules with deliberately different endpoint behaviour.

An onsite seat is occupied over a half-open window, so back-to-back sittings
share one seat; confidentiality coverage is a closed interval, so two spells
that merely touch at an endpoint collide.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers.assertions import assert_status
from test_helpers.factories import agreement_payload, session_payload
from test_helpers.fixtures import REVIEWER_ADA, REVIEWER_BEN, REVIEWER_ELENA
from test_helpers.test_users import ENGAGEMENT_MANAGER, STAFFING_COORDINATOR


class TestOnsiteSeatOverlapIsHalfOpen:
    """Occupancy counts sittings that genuinely overlap, endpoints excluded."""

    def _two_seats_occupied(self, matter_in_staffing):
        ladder = matter_in_staffing["ladder"]
        matter_id = matter_in_staffing["matter_id"]

        first = ladder.onboard(REVIEWER_ADA)
        second = ladder.onboard(REVIEWER_BEN, remote_work_addendum=True)
        third = ladder.onboard(REVIEWER_ELENA)

        validate_success(
            ladder.api.create_session(
                session_payload(
                    first["reviewer_id"],
                    matter_id,
                    starts_at_utc="2026-08-01T00:00:00Z",
                    ends_at_utc="2026-08-05T00:00:00Z",
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        validate_success(
            ladder.api.create_session(
                session_payload(
                    second["reviewer_id"],
                    matter_id,
                    starts_at_utc="2026-08-03T00:00:00Z",
                    ends_at_utc="2026-08-07T00:00:00Z",
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        return ladder, matter_id, third["reviewer_id"]

    def test_a_window_overlapping_both_occupied_seats_is_refused(
        self, matter_in_staffing
    ):
        """PRD §3.5: "If that occupancy plus one for the request itself would be greater
        than the matter's `onsite_seat_count`, the request is refused with
        `ERR_ONSITE_SEATS_EXHAUSTED`."

        Two seats are already taken across the requested window, so a third sitting
        would need a seat the matter does not hold.

        Design: Difficulty/resource_temporal_overlap/onsite_seat_overlap_is_half_open
        """
        ladder, matter_id, elena_id = self._two_seats_occupied(matter_in_staffing)

        response = ladder.api.create_session(
            session_payload(
                elena_id,
                matter_id,
                starts_at_utc="2026-08-04T00:00:00Z",
                ends_at_utc="2026-08-06T00:00:00Z",
            ),
            STAFFING_COORDINATOR,
        )
        validate_error(response, e.ERR_ONSITE_SEATS_EXHAUSTED, 409)

        sessions, _ = validate_paginated(
            ladder.api.list_sessions(STAFFING_COORDINATOR, matter_id=matter_id)
        )
        assert len(sessions) == 2

    def test_a_window_starting_when_another_ends_shares_the_seat(
        self, matter_in_staffing
    ):
        """PRD §3.5: "Sessions in `CLOSED` or `REVOKED` never occupy a seat, and because
        the window is half-open a session that ends at precisely the instant another
        begins does not overlap it — two back-to-back windows therefore share one seat."

        A sitting that begins at the precise instant another ends does not overlap it,
        so the freed seat is available immediately.

        Design: Difficulty/resource_temporal_overlap/onsite_seat_overlap_is_half_open
        """
        ladder, matter_id, elena_id = self._two_seats_occupied(matter_in_staffing)

        ladder.api.create_session(
            session_payload(
                elena_id,
                matter_id,
                starts_at_utc="2026-08-04T00:00:00Z",
                ends_at_utc="2026-08-06T00:00:00Z",
            ),
            STAFFING_COORDINATOR,
        )
        accepted = validate_success(
            ladder.api.create_session(
                session_payload(
                    elena_id,
                    matter_id,
                    starts_at_utc="2026-08-07T00:00:00Z",
                    ends_at_utc="2026-08-09T00:00:00Z",
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert_status(accepted, "SCHEDULED")
        assert accepted["workstation_class"] == "ONSITE_SECURE"

        by_matter, _ = validate_paginated(
            ladder.api.list_sessions(STAFFING_COORDINATOR, matter_id=matter_id)
        )
        assert len(by_matter) == 3

        by_reviewer, _ = validate_paginated(
            ladder.api.list_sessions(STAFFING_COORDINATOR, reviewer_id=elena_id)
        )
        assert len(by_reviewer) == 1


class TestAgreementCoverageOverlapIsClosedInterval:
    """Coverage spells that touch at an endpoint collide."""

    def _covered_reviewer(self, matter_in_staffing):
        ladder = matter_in_staffing["ladder"]
        ada = ladder.onboard(REVIEWER_ADA)
        return ladder, ada

    def test_new_coverage_beginning_on_the_previous_end_instant_collides(
        self, matter_in_staffing
    ):
        """PRD §2.9: "Consequently two coverage intervals that merely *touch* at an
        endpoint do collide, and issuing the second one is rejected with
        `ERR_CA_COVERAGE_OVERLAP`: the overlap test is that the existing interval's
        start is at or before the requested interval's end **and** the existing
        interval's end is at or after the requested interval's start."

        Coverage runs to the closing instant inclusive, so a spell starting at that
        instant is a genuine collision.

        Design: Difficulty/resource_temporal_overlap/agreement_coverage_overlap_is_closed_interval
        """
        ladder, ada = self._covered_reviewer(matter_in_staffing)

        response = ladder.api.create_agreement(
            agreement_payload(
                ada["reviewer_id"],
                matter_in_staffing["matter_id"],
                coverage_start_utc="2026-10-31T00:00:00Z",
                coverage_end_utc="2027-01-31T00:00:00Z",
            ),
            STAFFING_COORDINATOR,
        )
        validate_error(response, e.ERR_CA_COVERAGE_OVERLAP, 409)

        agreements, _ = validate_paginated(
            ladder.api.list_agreements(
                STAFFING_COORDINATOR, reviewer_id=ada["reviewer_id"]
            )
        )
        assert len(agreements) == 1

    def test_coverage_beginning_after_the_previous_end_is_accepted(
        self, matter_in_staffing
    ):
        """PRD §2.5: "Coverage intervals of confidentiality agreements for the same
        reviewer-and-matter pair whose `status` is `PENDING` or `EXECUTED` do not
        overlap — otherwise `ERR_CA_COVERAGE_OVERLAP` (HTTP 409), on agreement
        issuance."

        Clearing the touching endpoint by a day makes the second spell legal, and the
        first spell is left exactly as it was.

        Design: Difficulty/resource_temporal_overlap/agreement_coverage_overlap_is_closed_interval
        """
        ladder, ada = self._covered_reviewer(matter_in_staffing)

        ladder.api.create_agreement(
            agreement_payload(
                ada["reviewer_id"],
                matter_in_staffing["matter_id"],
                coverage_start_utc="2026-10-31T00:00:00Z",
                coverage_end_utc="2027-01-31T00:00:00Z",
            ),
            STAFFING_COORDINATOR,
        )
        accepted = validate_success(
            ladder.api.create_agreement(
                agreement_payload(
                    ada["reviewer_id"],
                    matter_in_staffing["matter_id"],
                    coverage_start_utc="2026-11-01T00:00:00Z",
                    coverage_end_utc="2027-01-31T00:00:00Z",
                ),
                STAFFING_COORDINATOR,
            ),
            expected_status=201,
        )
        assert_status(accepted, "PENDING")
        assert accepted["coverage_start_utc"].startswith("2026-11-01T00:00:00")

        agreements, _ = validate_paginated(
            ladder.api.list_agreements(
                STAFFING_COORDINATOR, reviewer_id=ada["reviewer_id"]
            )
        )
        assert len(agreements) == 2

        original = validate_success(
            ladder.api.get_agreement(ada["agreement_id"], STAFFING_COORDINATOR)
        )
        assert_status(original, "EXECUTED")

        matter = validate_success(
            ladder.api.get_matter(matter_in_staffing["matter_id"], ENGAGEMENT_MANAGER)
        )
        assert matter["staffed_reviewer_count"] == 1
        assert_status(matter, "IN_REVIEW")
