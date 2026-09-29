"""The declared lifecycle hops, the ones that are refused, and their side effects."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ENTRY_FEE_OUTSTANDING,
    ERR_ENTRY_WINDOW_OPEN,
    ERR_INVALID_ENTRY_STATE,
    ERR_INVALID_ROUND_STATE,
    ERR_INVALID_TOURNAMENT_STATE,
    ERR_OPEN_RULES_CASE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_entry_status,
    assert_fee_status,
    assert_identity_fields,
    assert_member_eligibility,
    assert_round_status,
    assert_slot_census,
    assert_tournament_status,
)
from test_helpers.constants import STANDARD_ENTRY_FEE_CENTS
from test_helpers.test_users import (
    ANONYMOUS,
    CONDUCT_COMMITTEE,
    RULES_OFFICIAL,
    TOUR_ADMIN,
    member_headers,
)
from test_helpers.types import (
    CONDUCT_APPEAL_OPEN,
    CONDUCT_CLEARED,
    CONDUCT_DECISION_CLEARED,
    CONDUCT_DECISION_SANCTIONED,
    CONDUCT_SANCTIONED,
    DISPOSITION_PENALTY_STROKES,
    ELIGIBILITY_PENDING_VERIFICATION,
    ELIGIBILITY_VERIFIED,
    ENTRY_ACCEPTED,
    ENTRY_APPLIED,
    ENTRY_CANCELLED,
    ENTRY_COMPETING,
    ENTRY_FINISHED,
    ENTRY_FORFEITED,
    ENTRY_REJECTED,
    ENTRY_WITHDRAWN,
    FEE_FORFEITED_FEE,
    FEE_PAID,
    FEE_REFUNDED,
    FEE_UNPAID,
    INCIDENT_ABUSIVE_LANGUAGE,
    INCIDENT_PHYSICAL_ALTERCATION,
    PEER_VERIFY,
    REJECTION_MEMBER_SUSPENDED,
    ROUND_CERTIFIED,
    ROUND_PEER_VERIFIED,
    ROUND_SCHEDULED,
    RULES_CASE_REPORTED,
    SANCTION_MEMBER_SUSPENSION,
    SANCTION_VENUE_BAN_ONE_EVENT,
    SUBJECT_CADDIE,
    TIER_LOCAL,
    TOURNAMENT_CANCELLED,
    TOURNAMENT_COMPLETED,
    TOURNAMENT_ENTRY_OPEN,
    TOURNAMENT_FIELD_SET,
    TOURNAMENT_IN_PROGRESS,
    TOURNAMENT_SCHEDULED,
)


class TestInitialStates:
    def test_self_registered_junior_starts_pending_verification(self, api):
        """Nobody enters the tour by registering; a staffer still has to look.

        PRD: "Newly registered juniors land in `PENDING_VERIFICATION` and can do
        nothing competitive until a staffer looks at them."

        Design: Corner/state_machines/member_initial_state_is_pending_verification
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)

        member = validate_success(
            api.register_member(f.member_payload(season["id"]), ANONYMOUS), 201
        )

        assert member["eligibility_status"] == ELIGIBILITY_PENDING_VERIFICATION
        assert_identity_fields(member, expected_version=1)


class TestTournamentLifecycle:
    def test_opening_the_window_changes_the_gate_not_the_field(self, api):
        """The event moves to ENTRY_OPEN with its participation ledger untouched.

        PRD: "Opening the entry window advances a tournament `SCHEDULED →
        ENTRY_OPEN` and is permitted only while the logical clock is still
        strictly before `entry_close_at` — there is no point opening a window
        that has already elapsed."

        Design: Corner/state_machines/open_entries_moves_scheduled_tournament_to_entry_open
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)
        scheduled = fx.create_tournament(api, season["id"])
        assert_tournament_status(scheduled, TOURNAMENT_SCHEDULED)

        opened = validate_success(api.open_entries(scheduled["id"], TOUR_ADMIN), 200)

        assert_tournament_status(opened, TOURNAMENT_ENTRY_OPEN)
        assert_slot_census(opened, entry_count=0, open_slot_count=2)

    def test_closing_the_window_one_second_early_is_refused(self, api):
        """The boundary instant itself is the first legal moment to close.

        PRD: "Closing it advances the tournament `ENTRY_OPEN → ENTRY_CLOSED` and
        is permitted only once the logical clock has reached `entry_close_at`; an
        attempt to close early is refused with `ERR_ENTRY_WINDOW_OPEN`."

        Design: Corner/state_machines/close_entries_before_entry_close_at_is_rejected
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)
        tournament = fx.create_tournament(api, season["id"])
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        fx.set_clock(api, "2026-08-31T23:59:59Z")

        response = api.close_entries(tournament["id"], TOUR_ADMIN)

        validate_error(response, ERR_ENTRY_WINDOW_OPEN, 409)
        assert_tournament_status(
            fx.read_tournament(api, tournament["id"]), TOURNAMENT_ENTRY_OPEN
        )

    def test_starting_a_scheduled_event_fails_on_its_state_not_its_field(self, api):
        """The state gate answers before the empty-field capacity rule does.

        PRD: "Beginning play is a `TourAdmin` or `ChiefReferee` action that
        advances the tournament `FIELD_SET → IN_PROGRESS`."

        Design: Corner/state_machines/start_from_scheduled_tournament_is_rejected
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)
        tournament = fx.create_tournament(api, season["id"])

        response = api.start_tournament(tournament["id"], TOUR_ADMIN)

        validate_error(response, ERR_INVALID_TOURNAMENT_STATE, 409)
        assert_tournament_status(
            fx.read_tournament(api, tournament["id"]), TOURNAMENT_SCHEDULED
        )

    def test_cancelled_event_refuses_both_a_second_cancel_and_a_reopen(self, api):
        """A cancelled event is finished, and its frozen census is not recomputed.

        PRD: "An `IN_PROGRESS`, `COMPLETED` or already-`CANCELLED` tournament
        cannot be cancelled and the attempt yields
        `ERR_INVALID_TOURNAMENT_STATE`."

        Design: Corner/state_machines/cancelled_tournament_rejects_every_further_transition
        """
        season = validate_success(api.create_season(f.season_payload(), TOUR_ADMIN), 201)
        tournament = fx.create_tournament(api, season["id"])
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        cancelled = validate_success(
            api.cancel_tournament(
                tournament["id"], {"cancellation_reason": "course flooded"}, TOUR_ADMIN
            ),
            200,
        )
        assert_tournament_status(cancelled, TOURNAMENT_CANCELLED)
        assert_slot_census(cancelled, open_slot_count=2)

        second_cancel = api.cancel_tournament(
            tournament["id"], {"cancellation_reason": "cancelled again by mistake"},
            TOUR_ADMIN,
        )
        reopen = api.open_entries(tournament["id"], TOUR_ADMIN)

        validate_error(second_cancel, ERR_INVALID_TOURNAMENT_STATE, 409)
        validate_error(reopen, ERR_INVALID_TOURNAMENT_STATE, 409)
        after = fx.read_tournament(api, tournament["id"])
        assert_tournament_status(after, TOURNAMENT_CANCELLED)
        assert_slot_census(after, accepted_count=0, open_slot_count=2)

    def test_start_is_refused_while_one_accepted_entry_still_owes_its_fee(self, api):
        """The fee precondition is evaluated over the whole accepted set.

        PRD: "And every `ACCEPTED` entry must have `amount_paid_cents` at or
        above its `net_fee_due_cents`, or the attempt is refused with
        `ERR_ENTRY_FEE_OUTSTANDING`."

        Design: Corner/state_machines/start_requires_every_accepted_entry_to_have_settled_its_fee
        """
        ctx = fx.field_set(api, 2)
        assert_slot_census(ctx["tournament"], accepted_count=2)
        paid = fx.pay_entry(api, ctx["member_ids"][0], ctx["entry_ids"][0])
        assert_fee_status(paid, FEE_PAID)
        fx.set_clock(api, fx.CLOCK_ROUND_ONE)

        response = api.start_tournament(ctx["tournament_id"], TOUR_ADMIN)

        validate_error(response, ERR_ENTRY_FEE_OUTSTANDING, 409)
        assert_tournament_status(
            fx.read_tournament(api, ctx["tournament_id"]), TOURNAMENT_FIELD_SET
        )
        unpaid = fx.read_entry(api, ctx["entry_ids"][1])
        assert_fee_status(unpaid, FEE_UNPAID)
        assert_entry_status(unpaid, ENTRY_ACCEPTED)

    def test_only_the_last_certification_completes_the_event(self, api):
        """The roll-up waits for the final competing entry, not the first.

        PRD: "Formally, the tournament advances `IN_PROGRESS → COMPLETED` when
        its `accepted_count` is at least 1 and no entry of the tournament remains
        in `entry_status` `ACCEPTED` or `COMPETING` — in other words, when every
        entry whose `entry_status` is `ACCEPTED`, `COMPETING`, `FINISHED` or
        `DISQUALIFIED` has settled into `FINISHED` or `DISQUALIFIED`."

        Design: Corner/state_machines/tournament_auto_completes_only_on_the_last_certify
        """
        ctx = fx.tournament_in_progress(api, 2)
        day_one = fx.build_tee_sheet(api, ctx, 1, fx.TEE_TIME_ROUND_ONE)
        fx.play_round(api, ctx, 0, 1, 1, fx.TEE_TIME_ROUND_ONE, 66,
                      round_row=day_one[0])
        fx.play_round(api, ctx, 1, 0, 1, fx.TEE_TIME_ROUND_ONE, 74,
                      round_row=day_one[1])
        fx.set_clock(api, fx.CLOCK_ROUND_TWO)
        day_two = fx.build_tee_sheet(api, ctx, 2, fx.TEE_TIME_ROUND_TWO)
        fx.play_round(api, ctx, 0, 1, 2, fx.TEE_TIME_ROUND_TWO, 72,
                      round_row=day_two[0])
        last_round = fx.play_round(
            api, ctx, 1, 0, 2, fx.TEE_TIME_ROUND_TWO, 76, certify=False,
            round_row=day_two[1],
        )
        midway = fx.read_tournament(api, ctx["tournament_id"])
        assert_tournament_status(midway, TOURNAMENT_IN_PROGRESS)
        assert_slot_census(midway, finished_count=1)
        assert midway["winner_entry_id"] is None
        assert_entry_status(fx.read_entry(api, ctx["entry_ids"][0]), ENTRY_FINISHED)
        assert_entry_status(fx.read_entry(api, ctx["entry_ids"][1]), ENTRY_COMPETING)

        certified = validate_success(
            api.certify_round(last_round["id"], RULES_OFFICIAL), 200
        )

        assert_round_status(certified, ROUND_CERTIFIED)
        winner = fx.read_entry(api, ctx["entry_ids"][0])
        runner_up = fx.read_entry(api, ctx["entry_ids"][1])
        assert_entry_status(runner_up, ENTRY_FINISHED)
        completed = fx.read_tournament(api, ctx["tournament_id"])
        assert_tournament_status(completed, TOURNAMENT_COMPLETED)
        assert_slot_census(completed, finished_count=2)
        assert completed["completed_at"].startswith("2026-09-11T12:00:00")
        assert completed["winner_entry_id"] == ctx["entry_ids"][0]
        assert winner["finish_position"] == 1
        assert runner_up["finish_position"] == 2
        assert_cents(
            fx.read_season(api, ctx["season_id"])["assistance_disbursed_cents"], 0,
            "assistance_disbursed_cents",
        )

    def test_cancelling_a_set_field_refunds_every_paid_entry(self, api):
        """A cancellation refunds; it never forfeits the family's money.

        PRD: "Second, a `fee_status` of `PAID`, `AID_COVERED` or `AID_PARTIAL`
        becomes `REFUNDED`, with `refunded_cents` set to the former
        `amount_paid_cents` and `amount_paid_cents` reset to zero."

        Design: Corner/state_machines/tournament_cancel_reverses_every_paid_reservation
        """
        ctx = fx.settled_field(api, 2)
        fx.set_clock(api, "2026-09-02T00:00:00Z")

        cancelled = validate_success(
            api.cancel_tournament(
                ctx["tournament_id"], {"cancellation_reason": "hurricane warning"},
                TOUR_ADMIN,
            ),
            200,
        )

        assert_tournament_status(cancelled, TOURNAMENT_CANCELLED)
        assert_slot_census(cancelled, accepted_count=0, open_slot_count=2, closed_count=2)
        for entry_id in ctx["entry_ids"]:
            entry = fx.read_entry(api, entry_id)
            assert_entry_status(entry, ENTRY_CANCELLED)
            assert_fee_status(entry, FEE_REFUNDED)
            assert entry["fee_status"] != FEE_FORFEITED_FEE
            assert_cents(entry["refunded_cents"], STANDARD_ENTRY_FEE_CENTS,
                         "refunded_cents")
            assert_cents(entry["amount_paid_cents"], 0, "amount_paid_cents")
        assert fx.read_member(api, ctx["member_ids"][0])["late_withdrawal_count"] == 0


class TestEntryAndRoundLifecycle:
    def test_withdrawing_twice_is_refused_and_the_census_does_not_drift(self, api):
        """Withdrawal is not idempotent, and the second call double-counts nothing.

        PRD: "Withdrawal is admissible only from `APPLIED`, `ACCEPTED`,
        `WAITLISTED` or `COMPETING`; anything else yields
        `ERR_INVALID_ENTRY_STATE`."

        Design: Corner/state_machines/second_withdraw_on_withdrawn_entry_is_rejected
        """
        ctx = fx.applied_field(api, 1)
        entry_id = ctx["entry_ids"][0]
        member_id = ctx["member_ids"][0]
        fx.set_clock(api, "2026-08-12T00:00:00Z")
        withdrawn = validate_success(
            api.withdraw_entry(
                entry_id, f.withdrawal_payload("schedule change"),
                member_headers(member_id),
            ),
            200,
        )
        assert_entry_status(withdrawn, ENTRY_WITHDRAWN)

        response = api.withdraw_entry(
            entry_id, f.withdrawal_payload("withdrawn twice"), member_headers(member_id)
        )

        validate_error(response, ERR_INVALID_ENTRY_STATE, 409)
        assert_entry_status(fx.read_entry(api, entry_id), ENTRY_WITHDRAWN)
        assert_slot_census(
            fx.read_tournament(api, ctx["tournament_id"]),
            entry_count=1, applied_count=0, closed_count=1,
        )

    def test_peer_verifying_a_card_that_was_never_handed_in_is_refused(self, api):
        """With no card on the round there is nothing for the marker to attest.

        PRD: "Verification is admissible only while the round is `SUBMITTED`."

        Design: Corner/state_machines/peer_verify_on_scheduled_round_is_rejected
        """
        ctx = fx.scheduled_round(api)

        response = api.peer_verify(
            ctx["round_id"], f.peer_verify_payload(PEER_VERIFY),
            member_headers(ctx["member_ids"][1]),
        )

        validate_error(response, ERR_INVALID_ROUND_STATE, 409)
        round_row = fx.read_round(api, ctx["round_id"])
        assert_round_status(round_row, ROUND_SCHEDULED)
        assert round_row["dispute_count"] == 0
        assert round_row["gross_strokes"] is None

    def test_certification_is_blocked_while_a_reported_case_is_open(self, api):
        """Unresolved officiating holds the card short of becoming a result.

        PRD: "A round may be certified only from `PEER_VERIFIED`, only while the
        tournament is `IN_PROGRESS`, and only when the round's
        `open_rules_case_count` is zero — that is, when no rules case on the round
        sits in `REPORTED` or `APPEAL_OPEN` status; a card with unresolved
        officiating is refused with `ERR_OPEN_RULES_CASE`."

        Design: Corner/state_machines/certify_is_blocked_while_a_rules_case_is_open
        """
        ctx = fx.peer_verified_round(api, gross_strokes=70)
        assert_round_status(ctx["round"], ROUND_PEER_VERIFIED)
        case = validate_success(
            api.report_rules_case(
                f.rules_case_payload(
                    ctx["round_id"], DISPOSITION_PENALTY_STROKES, 1,
                    rule_reference="Rule 14.3 - ball cleaned",
                ),
                RULES_OFFICIAL,
            ),
            201,
        )
        assert case["status"] == RULES_CASE_REPORTED

        response = api.certify_round(ctx["round_id"], RULES_OFFICIAL)

        validate_error(response, ERR_OPEN_RULES_CASE, 409)
        round_row = fx.read_round(api, ctx["round_id"])
        assert_round_status(round_row, ROUND_PEER_VERIFIED)
        assert round_row["open_rules_case_count"] == 1
        assert round_row["scoring_differential"] is None
        assert fx.read_entry(api, ctx["entry_ids"][0])["certified_round_count"] == 0


def _second_event(api, season_id):
    """A cheaper local event a month later, so a junior can hold two entries."""
    tournament = fx.create_tournament(
        api, season_id, builder=f.october_tournament_payload,
        name="Piedmont Local", tier=TIER_LOCAL, entry_fee_cents=15000,
        course_rating=70.0, slope_rating=120,
    )
    validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
    return tournament


class TestConductDecisionsAndCompensation:
    def test_venue_ban_forfeits_only_the_named_events_accepted_entry(self, api):
        """The ban bites at one venue and in one status, and charges no walk-away.

        PRD: "In the `VENUE_BAN_ONE_EVENT` branch the junior's `conduct_points` is
        updated and the ban bites at one venue only: the junior's entry on the
        very tournament named by the case's `tournament_id`, and only if that
        entry's `entry_status` is `ACCEPTED`, moves to `FORFEITED` with its
        `fee_status` moving to `FORFEITED_FEE`, its aid moved from
        `assistance_committed_cents` to `assistance_disbursed_cents`, its slot
        freed, and the resulting waitlist promotion fired."

        Design: Corner/state_machines/venue_ban_forfeits_only_the_named_tournaments_accepted_entry
        """
        ctx = fx.verified_roster(api, 1)
        member_id = ctx["member_ids"][0]
        banned_event = fx.create_tournament(api, ctx["season_id"])
        validate_success(api.open_entries(banned_event["id"], TOUR_ADMIN), 200)
        other_event = _second_event(api, ctx["season_id"])
        banned_entry = fx.submit_entry(api, member_id, banned_event["id"])
        untouched_entry = fx.submit_entry(api, member_id, other_event["id"])
        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(banned_event["id"], TOUR_ADMIN), 200)
        validate_success(api.set_field(banned_event["id"], TOUR_ADMIN), 200)
        fx.pay_entry(api, member_id, banned_entry["id"])
        case = fx.file_conduct_case(
            api, member_id, banned_event["id"], INCIDENT_ABUSIVE_LANGUAGE,
            subject_name="Marcus Stone",
            narrative="verbal abuse of a volunteer marshal on the 9th tee",
        )

        decided = validate_success(
            api.decide_conduct_case(
                case["id"], f.conduct_decision_payload(CONDUCT_DECISION_SANCTIONED),
                CONDUCT_COMMITTEE,
            ),
            200,
        )

        assert decided["status"] == CONDUCT_SANCTIONED
        assert decided["points_assessed"] == 3
        assert decided["cumulative_points_at_decision"] == 3
        assert decided["sanction_tier"] == SANCTION_VENUE_BAN_ONE_EVENT
        assert decided["sanction_tier"] != SANCTION_MEMBER_SUSPENSION
        member = fx.read_member(api, member_id)
        assert member["conduct_points"] == 3
        assert_member_eligibility(member, ELIGIBILITY_VERIFIED)
        assert member["late_withdrawal_count"] == 0
        forfeited = fx.read_entry(api, banned_entry["id"])
        assert_entry_status(forfeited, ENTRY_FORFEITED)
        assert_fee_status(forfeited, FEE_FORFEITED_FEE)
        assert_cents(forfeited["refunded_cents"], 0, "refunded_cents")
        assert_entry_status(fx.read_entry(api, untouched_entry["id"]), ENTRY_APPLIED)
        assert_slot_census(
            fx.read_tournament(api, banned_event["id"]),
            accepted_count=0, open_slot_count=2,
        )

    def test_cleared_appeal_reinstates_the_junior_but_not_the_closed_entry(self, api):
        """Reinstatement is deliberately partial: eligibility only.

        PRD: "Reinstatement restores **eligibility only**: entries that the
        original suspension cascade already rejected or forfeited stay closed, and
        that asymmetry is deliberate."

        Design: Corner/state_machines/cleared_appeal_restores_the_member_but_not_the_closed_entry
        """
        ctx = fx.verified_roster(api, 1)
        member_id = ctx["member_ids"][0]
        event = _second_event(api, ctx["season_id"])
        entry = fx.submit_entry(api, member_id, event["id"])
        fx.set_clock(api, "2026-08-12T00:00:00Z")
        case = fx.file_conduct_case(
            api, member_id, event["id"], INCIDENT_PHYSICAL_ALTERCATION,
            subject_type=SUBJECT_CADDIE, subject_name="Dale Stone",
            narrative="shoved a rules official beside the 14th green",
        )
        sanctioned = fx.sanction_conduct_case(api, case["id"])
        assert sanctioned["sanction_tier"] == SANCTION_MEMBER_SUSPENSION
        fx.set_clock(api, "2026-08-20T00:00:00Z")
        appealed = validate_success(
            api.appeal_conduct_case(
                case["id"],
                f.appeal_payload(
                    "the caddie was not acting for the player and the player "
                    "was not present"
                ),
                member_headers(member_id),
            ),
            200,
        )
        assert appealed["status"] == CONDUCT_APPEAL_OPEN
        assert appealed["appeal_count"] == 1

        cleared = validate_success(
            api.decide_conduct_case(
                case["id"], f.conduct_decision_payload(CONDUCT_DECISION_CLEARED),
                CONDUCT_COMMITTEE,
            ),
            200,
        )

        assert cleared["status"] == CONDUCT_CLEARED
        assert cleared["points_assessed"] == 0
        assert cleared["sanction_tier"] is None
        assert cleared["decided_at"].startswith("2026-08-20T00:00:00")
        member = fx.read_member(api, member_id)
        assert member["conduct_points"] == 0
        assert_member_eligibility(member, ELIGIBILITY_VERIFIED)
        closed = fx.read_entry(api, entry["id"])
        assert_entry_status(closed, ENTRY_REJECTED)
        assert closed["rejection_reason"] == REJECTION_MEMBER_SUSPENDED
