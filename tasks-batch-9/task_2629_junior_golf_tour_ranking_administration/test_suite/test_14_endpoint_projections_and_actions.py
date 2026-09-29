"""The endpoints that project, stamp or supersede: rankings, clock, grants, fees."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_HANDICAP_ABOVE_LIMIT
from test_helpers.assertions import (
    assert_cents,
    assert_entry_status,
    assert_fee_status,
    assert_slot_census,
    assert_two_decimals,
    assert_version_is,
)
from test_helpers.constants import PROCESS_START_UTC, STANDARD_ENTRY_FEE_CENTS
from test_helpers.test_users import (
    COACH,
    COACH_USER_ID,
    SECOND_COACH,
    SECOND_COACH_USER_ID,
    TOUR_ADMIN,
    member_headers,
)
from test_helpers.types import (
    COACH_GRANT_REQUESTED,
    COACH_GRANT_SUPERSEDED,
    DIVISION_U17,
    ENTRY_ACCEPTED,
    ENTRY_APPLIED,
    ENTRY_FORFEITED,
    FEE_FORFEITED_FEE,
    FEE_PAID,
    SCOPE_FULL_PROFILE,
)


class TestComputedRankingReads:
    def test_a_junior_with_no_results_reads_as_unranked_not_as_last(self, api):
        """The projection shows the empty provisional figures and null certified ones.

        PRD: "Registration sets `conduct_points` to zero, `late_withdrawal_count`
        to zero, `provisional_ranking_points` to 0.00 and
        `provisional_counted_events` to zero; the certified ranking fields start
        empty, with `certified_ranking_points` null, `certified_counted_events`
        zero, `certified_rank_position` null and `last_ranking_epoch` null."

        Design: Corner/endpoints/ranking_read_of_a_member_with_no_results_is_all_zeros
        """
        ctx = fx.verified_roster(api, member_count=1)
        ranking = fx.read_ranking(api, ctx["member_ids"][0])

        assert ranking["member_id"] == ctx["member_ids"][0]
        assert ranking["age_division"] == DIVISION_U17
        assert_two_decimals(
            ranking["provisional_ranking_points"], 0.00, "provisional points"
        )
        assert ranking["provisional_counted_events"] == 0
        assert ranking["certified_ranking_points"] is None
        assert ranking["certified_counted_events"] == 0
        assert ranking["certified_rank_position"] is None
        assert ranking["last_ranking_epoch"] is None
        assert ranking["ranking_epoch"] == 0

    def test_a_run_over_an_empty_season_moves_the_epoch_and_nothing_else(self, api):
        """The season epoch advances to 1 while no junior is stamped or ranked.

        PRD: "Executing it recomputes `certified_ranking_points` and
        `certified_counted_events` for every junior of the season holding at
        least one qualifying finished entry, assigns `certified_rank_position`
        across those juniors and leaves it null for juniors with none,
        increments the season's `ranking_epoch` by one, stamps every ranked
        junior's `last_ranking_epoch` with that new epoch value, sets the
        season's `last_ranking_run_at` to the logical clock, sets
        `last_ranking_as_of_date` to the supplied `as_of_date` or, when it is
        omitted, to the calendar date of the logical clock, and sets
        `ranked_member_count` to the number of juniors who received a non-null
        position."

        Design: Corner/endpoints/ranking_run_with_no_finished_entries_bumps_only_the_epoch
        """
        ctx = fx.verified_roster(api, member_count=1)
        assert ctx["season"]["ranking_epoch"] == 0
        assert ctx["season"]["ranked_member_count"] == 0

        season = fx.run_ranking(api, ctx["season_id"], as_of_date="2026-08-10")
        assert season["ranking_epoch"] == 1
        assert season["ranked_member_count"] == 0
        assert season["last_ranking_as_of_date"] == "2026-08-10"
        assert season["last_ranking_run_at"].startswith("2026-08-10T00:00:00")

        ranking = fx.read_ranking(api, ctx["member_ids"][0])
        assert ranking["last_ranking_epoch"] is None
        assert ranking["certified_rank_position"] is None
        assert ranking["ranking_epoch"] == 1
        assert fx.read_season(api, ctx["season_id"])["ranking_epoch"] == 1


class TestClockAndSupersession:
    def test_the_clock_reports_the_instant_it_displaced(self, api):
        """previous_utc is the outgoing instant, first the process-start default.

        PRD: "An administrative test capability replaces the clock with a
        supplied `current_utc` instant and answers with both the new
        `current_utc` and the `previous_utc` value it displaced."

        Design: Corner/endpoints/clock_set_reports_the_instant_it_replaced
        """
        first = fx.set_clock(api, "2026-08-10T00:00:00Z")
        assert first["previous_utc"].startswith(PROCESS_START_UTC[:-1])
        assert first["current_utc"].startswith("2026-08-10T00:00:00")

        second = fx.set_clock(api, "2026-09-06T12:30:00Z")
        assert second["previous_utc"].startswith("2026-08-10T00:00:00")
        assert second["current_utc"].startswith("2026-09-06T12:30:00")

    def test_a_re_request_supersedes_that_coach_s_grant_only(self, api):
        """One coach's second request retires only its own earlier grant.

        PRD: "Any prior grant of the same junior and the same coach whose
        `status` is `REQUESTED` or `GRANTED` moves to `SUPERSEDED`, and the new
        grant starts at `REQUESTED` — which means a coach who re-requests
        **loses** the access they already had until the junior decides again."

        Design: Corner/endpoints/second_access_request_supersedes_only_the_same_coachs_grant
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        opening_version = fx.member_version(api, member_id)

        first = validate_success(
            api.request_coach_access(
                f.coach_access_payload(member_id, opening_version), COACH
            ),
            201,
        )
        assert first["status"] == COACH_GRANT_REQUESTED
        rival = validate_success(
            api.request_coach_access(
                f.coach_access_payload(
                    member_id, fx.member_version(api, member_id),
                    coach_school="Coastal College",
                ),
                SECOND_COACH,
            ),
            201,
        )
        assert rival["coach_user_id"] == SECOND_COACH_USER_ID

        replacement = validate_success(
            api.request_coach_access(
                f.coach_access_payload(
                    member_id, fx.member_version(api, member_id),
                    scope=SCOPE_FULL_PROFILE,
                ),
                COACH,
            ),
            201,
        )
        assert replacement["status"] == COACH_GRANT_REQUESTED
        assert replacement["coach_user_id"] == COACH_USER_ID
        assert replacement["scope"] == SCOPE_FULL_PROFILE
        assert replacement["expires_at"] is None

        superseded = validate_success(
            api.get_coach_access_grant(first["id"], TOUR_ADMIN), 200
        )
        assert superseded["status"] == COACH_GRANT_SUPERSEDED
        untouched = validate_success(
            api.get_coach_access_grant(rival["id"], TOUR_ADMIN), 200
        )
        assert untouched["status"] == COACH_GRANT_REQUESTED
        assert_version_is(fx.read_member(api, member_id), opening_version + 3)


class TestWithdrawalAndRevisionActions:
    def test_withdrawing_after_the_deadline_forfeits_and_is_charged(self, api):
        """The same endpoint keeps the money and charges a late withdrawal.

        PRD: "The entry moves `ACCEPTED → FORFEITED` and `withdrawn_at` is
        stamped. A `fee_status` of `PAID`, `AID_COVERED` or `AID_PARTIAL` moves
        to `FORFEITED_FEE`; `refunded_cents` stays at zero and
        `net_fee_due_cents` is set to zero, so the association keeps the money."

        Design: Corner/endpoints/withdraw_after_the_deadline_forfeits_and_charges_a_late_withdrawal
        """
        ctx = fx.settled_field(api, member_count=1)
        member_id = ctx["member_ids"][0]
        entry = ctx["entries"][0]
        assert ctx["members"][0]["late_withdrawal_count"] == 0
        assert_entry_status(entry, ENTRY_ACCEPTED)
        assert_fee_status(entry, FEE_PAID)
        assert_cents(
            entry["amount_paid_cents"], STANDARD_ENTRY_FEE_CENTS, "amount paid"
        )

        fx.set_clock(api, fx.CLOCK_AFTER_WITHDRAWAL_DEADLINE)
        forfeited = validate_success(
            api.withdraw_entry(
                entry["id"], f.withdrawal_payload(), member_headers(member_id)
            ),
            200,
        )
        assert_entry_status(forfeited, ENTRY_FORFEITED)
        assert_fee_status(forfeited, FEE_FORFEITED_FEE)
        assert_cents(forfeited["refunded_cents"], 0, "refunded")
        assert forfeited["withdrawn_at"].startswith("2026-09-06T00:00:00")
        assert_cents(
            forfeited["amount_paid_cents"], STANDARD_ENTRY_FEE_CENTS, "amount paid"
        )
        assert fx.read_member(api, member_id)["late_withdrawal_count"] == 1

    def test_a_handicap_revision_binds_the_next_entry_not_the_live_one(self, api):
        """The stored index is overwritten while the submitted entry is left alone.

        PRD: "Critically, a revision does **not** retroactively alter any
        existing entry: entry-time eligibility was settled when the entry was
        submitted, and a junior whose index rises above a tournament's ceiling
        after acceptance keeps their slot."

        Design: Corner/endpoints/handicap_revision_overwrites_the_index_without_touching_a_live_entry
        """
        ctx = fx.verified_roster(api, member_count=1)
        member_id = ctx["member_ids"][0]
        first = fx.create_tournament(
            api, ctx["season_id"], name="Carolina Regional U17", field_size_limit=4
        )
        second = fx.create_tournament(
            api, ctx["season_id"], f.october_tournament_payload,
            name="Piedmont Regional U17", field_size_limit=4,
        )
        for tournament in (first, second):
            validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        live_entry = fx.submit_entry(api, member_id, first["id"])
        assert_entry_status(live_entry, ENTRY_APPLIED)

        before = fx.member_version(api, member_id)
        revised = validate_success(
            api.revise_handicap(
                member_id,
                f.handicap_revision_payload(before, handicap_index=9.7),
                TOUR_ADMIN,
            ),
            200,
        )
        assert revised["handicap_index"] == 9.7
        assert revised["handicap_effective_date"] == "2026-08-09"
        assert_version_is(revised, before + 1)

        assert_entry_status(fx.read_entry(api, live_entry["id"]), ENTRY_APPLIED)
        refused = api.submit_entry(
            f.entry_payload(member_id, second["id"]), member_headers(member_id)
        )
        validate_error(refused, ERR_HANDICAP_ABOVE_LIMIT, 409)
        assert fx.read_member(api, member_id)["handicap_index"] == 9.7
        assert_slot_census(fx.read_tournament(api, second["id"]), entry_count=0)
