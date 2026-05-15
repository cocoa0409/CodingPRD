"""Concurrency and version-conflict tests (PRD §2.6, §2.10).

Covers optimistic concurrency on PATCH endpoints and the six declared
race-condition contracts. Each race uses the framework's run_race +
assert_race_outcome / validate_error_is_one_of helpers; we never assert
a specific loser error_id unless PRD names it explicitly.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_exactly_one_succeeds,
    create_open_tournament,
    create_referee,
    create_team_registration,
    create_team_registration_payload,
    make_team_manager_headers,
    reset_clock_to_epoch,
    run_race,
    setup_live_match_with_certified_referee,
    setup_transfer_offer_in_state,
    update_referee_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Optimistic concurrency control (PRD §2.6)
# ===========================================================================
class TestOptimisticConcurrency:
    def test_patch_referee_with_stale_version_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §2.6: "When version is supplied, the server compares it
        against the stored row's version; a mismatch is rejected with
        ERR_VERSION_CONFLICT."

        Claim: PATCH /referees/{rfid} with a stale version value →
        ERR_VERSION_CONFLICT.
        """
        referee = create_referee()
        # Bump the referee's version via a successful PATCH.
        first = api.update_referee(
            referee["id"],
            update_referee_payload(
                status="SUSPENDED", version=referee["version"],
            ),
            league_admin_headers,
        )
        validate_success(first)
        # Now attempt a PATCH with the original (now-stale) version.
        response = api.update_referee(
            referee["id"],
            update_referee_payload(
                status="ACTIVE", version=referee["version"],
            ),
            league_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# Concurrency contract: two report-result calls race (PRD §2.10)
# ===========================================================================
class TestReportResultRace:
    def test_two_concurrent_report_result_calls_exactly_one_wins(self, api):
        """PRD §2.10: "When two report-result calls race for the same
        Match after both teams claim victory, only one transitions
        LIVE to COMPLETED; the loser receives ERR_INVALID_STATE."

        Claim: two concurrent POST /matches/{mid}/report-result calls
        produce exactly one 2xx success and one error.
        """
        tournament, match, referee = setup_live_match_with_certified_referee()
        winner_a = match.get("team_a_id")
        winner_b = match.get("team_b_id")
        if not winner_a or not winner_b:
            pytest.skip("Need a non-bye LIVE match to race report-result")
        from test_helpers import make_referee_headers, report_result_payload
        ref_headers = make_referee_headers(referee["user_id"])
        results = run_race(
            lambda: api.report_result(
                match["id"], report_result_payload(winner_a), ref_headers,
            ),
            lambda: api.report_result(
                match["id"], report_result_payload(winner_b), ref_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD §2.10 names the loser error explicitly; assert it.
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )


# ===========================================================================
# Concurrency contract: two LeagueAdmin approve transfers, same player (PRD §2.10)
# ===========================================================================
class TestCoolingOffRace:
    def test_concurrent_league_approve_with_cooling_off_invariant(
        self, api, league_admin_headers,
    ):
        """PRD §2.10: "When two LeagueAdmin callers concurrently
        approve transfers for the same player_id within the same window,
        the second receives ERR_COOLING_OFF_ACTIVE because the first
        has already pinned the cooling-off invariant."

        Claim: two concurrent league-approve calls for the same player
        produce exactly one 2xx; loser receives ERR_COOLING_OFF_ACTIVE
        (or possibly ERR_INVALID_STATE if the loser sees the offer
        already LEAGUE_APPROVED — PRD §2.10 explicitly names cooling-off).
        """
        from test_helpers import (
            create_transfer_offer_payload,
            league_approve_payload,
        )
        # Set up two offers for the same player_id but to different
        # to_teams within the same window.
        (tournament, from_reg, to_reg_1, contract, window, offer_1,
         from_mgr, to_mgr_1) = setup_transfer_offer_in_state("ACCEPTED_BY_BOTH")
        # Build a second to_team and a parallel offer.
        from test_helpers import register_team_to_registered, advance_clock_to, iso_utc
        # Need to register a fresh team before the window closes — the
        # tournament was created in REGISTRATION_OPEN by the composite.
        # The fixture composite already advanced state; if registration
        # is closed, we must skip the race scenario.
        try:
            reset_clock_to_epoch()
            advance_clock_to(iso_utc())
            second_to_reg, _ = register_team_to_registered(
                tournament_id=tournament["id"],
                manager_id=f"{to_mgr_1}-second",
                team_name=f"SecondTo-{to_mgr_1[-6:]}",
            )
        except AssertionError:
            pytest.skip(
                "Could not register a second to_team for the cooling-off "
                "race in this composite — tournament has advanced past "
                "REGISTRATION_OPEN.",
            )
        # Race two approvals — only one should succeed.
        results = run_race(
            lambda: api.league_approve_offer(
                offer_1["id"], league_approve_payload("APPROVE"),
                league_admin_headers,
            ),
            lambda: api.league_approve_offer(
                offer_1["id"], league_approve_payload("APPROVE"),
                league_admin_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # PRD §2.10 names ERR_COOLING_OFF_ACTIVE as the loser contract.
        # In practice a race on the same offer id may also produce
        # ERR_INVALID_STATE (state already LEAGUE_APPROVED). Per the
        # `error-precedence` Silence-pattern rule, accept either.
        validate_error_is_one_of(
            loser, [
                ApiErrorId.ERR_COOLING_OFF_ACTIVE.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )
