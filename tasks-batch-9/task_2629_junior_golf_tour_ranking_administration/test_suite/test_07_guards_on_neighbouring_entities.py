"""Guards that live on a different row than the one being written: a card refused
because its grandparent event never started, and a recruiting read that flips on
the state of a consent grant.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_COACH_ACCESS_DENIED,
    ERR_INVALID_TOURNAMENT_STATE,
)
from test_helpers.test_users import COACH, TOUR_ADMIN, member_headers
from test_helpers.types import (
    COACH_DECISION_GRANTED,
    COACH_GRANT_GRANTED,
    COACH_GRANT_REQUESTED,
    COACH_GRANT_REVOKED,
    ENTRY_ACCEPTED,
    ENTRY_COMPETING,
    ROUND_SCHEDULED,
    ROUND_SUBMITTED,
    TOURNAMENT_FIELD_SET,
)


class TestScoreSubmissionNeedsTheEventUnderway:
    """The round and the entry are both ready; the tournament is not."""

    def test_a_card_cannot_be_submitted_while_the_event_is_only_field_set(self, api):
        """The refusal names the tournament, not the round.

        PRD: "Four cross-entity conditions guard the submission: the tournament
        must be `IN_PROGRESS`, the entry's `entry_status` must be `ACCEPTED` or
        `COMPETING`, the entry's `fee_status` must be `PAID` or `AID_COVERED` —
        this is the single point at which the money dimension gates the
        competitive one — and the round itself must be `SCHEDULED` or `DISPUTED`."

        Design: Difficulty/cross_entity_state_dependency/submit_score_requires_tournament_in_progress
        """
        ctx = fx.settled_field(api, member_count=2)
        assert ctx["tournament"]["status"] == TOURNAMENT_FIELD_SET

        round_row = fx.create_round(
            api, ctx["entry_ids"][0], ctx["member_ids"][1], 1, fx.TEE_TIME_ROUND_ONE
        )
        assert round_row["status"] == ROUND_SCHEDULED

        validate_error(
            api.submit_score(round_row["id"], f.score_payload(72),
                             member_headers(ctx["member_ids"][0])),
            ERR_INVALID_TOURNAMENT_STATE,
            409,
        )

        untouched = fx.read_round(api, round_row["id"])
        assert untouched["status"] == ROUND_SCHEDULED
        assert untouched["gross_strokes"] is None
        assert fx.read_entry(api, ctx["entry_ids"][0])["entry_status"] == ENTRY_ACCEPTED

    def test_the_same_card_is_accepted_once_the_event_is_in_progress(self, api):
        """Starting the tournament is the only thing that changes between the two calls.

        PRD: "From `SCHEDULED` the submission records `gross_strokes`, advances the
        round `SCHEDULED → SUBMITTED`, and, when this is the entry's first
        submission, also advances the entry `ACCEPTED → COMPETING`."

        Design: Difficulty/cross_entity_state_dependency/submit_score_requires_tournament_in_progress
        """
        ctx = fx.settled_field(api, member_count=2)
        round_row = fx.create_round(
            api, ctx["entry_ids"][0], ctx["member_ids"][1], 1, fx.TEE_TIME_ROUND_ONE
        )
        validate_error(
            api.submit_score(round_row["id"], f.score_payload(72),
                             member_headers(ctx["member_ids"][0])),
            ERR_INVALID_TOURNAMENT_STATE,
            409,
        )

        fx.set_clock(api, fx.CLOCK_ROUND_ONE)
        validate_success(api.start_tournament(ctx["tournament_id"], TOUR_ADMIN), 200)

        submitted = validate_success(
            api.submit_score(round_row["id"], f.score_payload(72),
                             member_headers(ctx["member_ids"][0])),
            200,
        )
        assert submitted["status"] == ROUND_SUBMITTED
        assert submitted["gross_strokes"] == 72
        assert fx.read_entry(api, ctx["entry_ids"][0])["entry_status"] == ENTRY_COMPETING


class TestPublishedResultsFollowTheGrant:
    """The same read by the same coach flips on a third row's status."""

    def test_a_requested_grant_denies_and_a_granted_one_admits(self, api):
        """One decision by the junior turns 403 into 200.

        PRD: "A `Coach` reading a junior's recruiting data must hold a grant whose
        `status` is `GRANTED`, whose `expires_at` is strictly after the logical
        clock, and whose `scope` covers the requested view."

        Design: Difficulty/cross_entity_state_dependency/published_results_visibility_flips_with_grant_state
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]

        grant = fx.requested_coach_grant(api, member_id)
        assert grant["status"] == COACH_GRANT_REQUESTED

        validate_error(api.get_published_results(member_id, COACH),
                       ERR_COACH_ACCESS_DENIED, 403)

        granted = validate_success(
            api.decide_coach_access(
                grant["id"], f.coach_decision_payload(COACH_DECISION_GRANTED),
                member_headers(member_id),
            ),
            200,
        )
        assert granted["status"] == COACH_GRANT_GRANTED
        assert granted["expires_at"] == "2027-02-06T00:00:00Z"

        results = validate_success(api.get_published_results(member_id, COACH), 200)
        assert results["publication_opt_in"] is True
        assert results["finished_event_count"] == 0
        assert results["certified_rank_position"] is None

        assert validate_success(
            api.get_coach_access_grant(grant["id"], TOUR_ADMIN), 200
        )["status"] == COACH_GRANT_GRANTED

    def test_revoking_the_grant_closes_the_view_again(self, api):
        """Access tracks the grant in both directions.

        PRD: "A coach whose grant is absent, still `REQUESTED`, `DENIED`,
        `REVOKED`, `SUPERSEDED` or expired, or whose `scope` is too narrow, is
        refused with `ERR_COACH_ACCESS_DENIED`, and that same rule guards both the
        published-results view and the ranking view."

        Design: Difficulty/cross_entity_state_dependency/published_results_visibility_flips_with_grant_state
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        grant = fx.granted_coach_grant(api, member_id)
        validate_success(api.get_published_results(member_id, COACH), 200)

        revoked = validate_success(
            api.revoke_coach_access(grant["id"], f.revocation_payload(),
                                    member_headers(member_id)),
            200,
        )
        assert revoked["status"] == COACH_GRANT_REVOKED
        assert revoked["expires_at"] is None

        validate_error(api.get_published_results(member_id, COACH),
                       ERR_COACH_ACCESS_DENIED, 403)
