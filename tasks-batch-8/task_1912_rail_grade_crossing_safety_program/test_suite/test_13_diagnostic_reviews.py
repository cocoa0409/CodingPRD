"""Diagnostic review lifecycle: acceptance supersedes the prior accepted review
(PRD §3.2)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_diagnostic_review,
    create_accepted_review,
    create_diagnostic_review_payload,
    create_locality,
    create_team,
    get_success_data,
    setup_locality_team_crossing,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


class TestReviewAcceptanceSupersede:
    def test_accepting_newer_review_supersedes_prior(self, api, admin_headers):
        """PRD §3.2: "acceptance stamps `accepted_at` and, because only one review
        may speak for a crossing at a time, the crossing's previously `ACCEPTED`
        review — if any — is automatically moved `ACCEPTED` → `SUPERSEDED` with
        its `superseded_by_review_id` set to the newly accepted review's `id`."

        Design: Corner/state_machines/review_accept_supersedes_prior
        """
        locality, team, crossing = setup_locality_team_crossing(
            {"dot_crossing_number": "DOT-020011"}
        )
        r1 = create_accepted_review(
            crossing["id"], team["id"], scheduled_date="2026-09-10"
        )
        assert r1["status"] == "ACCEPTED"
        assert r1["accepted_at"] is not None

        # Second review (team buffer satisfied: 2 days apart) up to
        # RECOMMENDATIONS_ISSUED, then accept it.
        r2 = get_success_data(
            api.create_diagnostic_review(
                create_diagnostic_review_payload(
                    crossing_id=crossing["id"],
                    team_id=team["id"],
                    scheduled_date="2026-09-12",
                ),
                ADMIN,
            )
        )
        get_success_data(
            api.transition_diagnostic_review(
                r2["id"], {"to_status": "IN_SESSION"}, OFFICER
            )
        )
        get_success_data(
            api.issue_recommendations(
                r2["id"], {"recommendations": ["INSTALL_PREEMPTION"]}, OFFICER
            )
        )
        r2_accepted = get_success_data(
            api.transition_diagnostic_review(
                r2["id"], {"to_status": "ACCEPTED"}, OFFICER
            )
        )
        assert r2_accepted["status"] == "ACCEPTED"
        assert_diagnostic_review(r2_accepted)

        r1_after = get_success_data(api.get_diagnostic_review(r1["id"], OFFICER))
        assert r1_after["status"] == "SUPERSEDED"
        assert r1_after["superseded_by_review_id"] == r2["id"]

    def test_first_acceptance_has_no_prior_to_supersede(self, api, admin_headers):
        """PRD §3.2: "The office accepts a review's recommendations by moving it
        `RECOMMENDATIONS_ISSUED` → `ACCEPTED`, which requires the crossing to
        still be `ACTIVE` (else `ERR_CROSSING_NOT_ACTIVE`); acceptance stamps
        `accepted_at` and, because only one review may speak for a crossing at a
        time, the crossing's previously `ACCEPTED` review — if any — is
        automatically moved `ACCEPTED` → `SUPERSEDED`".

        Design: Corner/state_machines/review_accept_supersedes_prior
        """
        locality, team, crossing = setup_locality_team_crossing(
            {"dot_crossing_number": "DOT-020012"}
        )
        r1 = create_accepted_review(
            crossing["id"], team["id"], scheduled_date="2026-09-10"
        )
        assert r1["status"] == "ACCEPTED"
        assert r1["accepted_at"] is not None
        assert r1.get("superseded_by_review_id") is None

        from test_helpers import validate_paginated

        rows, meta = validate_paginated(
            api.list_diagnostic_reviews(
                ADMIN, params={"crossing_id": crossing["id"], "status": "SUPERSEDED"}
            )
        )
        assert meta["total_count"] == 0, "no prior ACCEPTED review existed to supersede"
