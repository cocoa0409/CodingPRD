"""Two shapes that a single-track state machine cannot express: an entry whose
competitive and money dimensions advance on different triggers, and a scoring
dispute loop that is re-entrant twice and then terminal.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents
from test_helpers.test_users import TOUR_ADMIN, member_headers
from test_helpers.types import (
    ENTRY_ACCEPTED,
    ENTRY_APPLIED,
    ENTRY_COMPETING,
    ENTRY_WAITLISTED,
    FEE_AID_PARTIAL,
    FEE_PAID,
    PEER_DISPUTE,
    PEER_VERIFY,
    ROUND_DISPUTED,
    ROUND_NO_CARD,
    ROUND_PEER_VERIFIED,
    ROUND_SUBMITTED,
)

LATE_ENTRY_CLOCK = "2026-08-30T00:00:00Z"


class TestEntryStatusDimensionsAreIndependent:
    """Paying moves only the money dimension; teeing off moves only the other."""

    def test_paid_then_playing_entry_reads_competing_and_paid_at_once(self, api):
        """The unplayed peer stays ACCEPTED and PAID while its rival turns COMPETING.

        PRD: "The two advance through disjoint sets of triggers, so an entry may
        perfectly legitimately be `WAITLISTED` and `PAID`, or `ACCEPTED` and
        `UNPAID`."

        Design: Difficulty/non_linear_state_machine/entry_parallel_status_dimensions_move_independently
        """
        ctx = fx.verified_roster(api, member_count=2)
        first_member_id, second_member_id = ctx["member_ids"]
        application = fx.approved_aid_application(
            api, first_member_id, ctx["season_id"],
            household_income_cents=6000000, dependents=3,
        )
        tournament = fx.create_tournament(
            api, ctx["season_id"], entry_fee_cents=32000
        )
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
        fx.set_clock(api, LATE_ENTRY_CLOCK)

        assisted = fx.submit_entry(
            api, first_member_id, tournament["id"],
            request_assistance=True, aid_application_id=application["id"],
        )
        assert assisted["fee_status"] == FEE_AID_PARTIAL
        assert assisted["entry_status"] == ENTRY_APPLIED
        unassisted = fx.submit_entry(api, second_member_id, tournament["id"])

        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
        validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)

        paid = fx.pay_entry(api, first_member_id, assisted["id"], 6400)
        assert paid["fee_status"] == FEE_PAID
        assert paid["entry_status"] == ENTRY_ACCEPTED
        fx.pay_entry(api, second_member_id, unassisted["id"], 35200)

        fx.set_clock(api, fx.CLOCK_ROUND_ONE)
        validate_success(api.start_tournament(tournament["id"], TOUR_ADMIN), 200)
        round_row = fx.create_round(
            api, assisted["id"], second_member_id, 1, fx.TEE_TIME_ROUND_ONE
        )
        submitted = validate_success(
            api.submit_score(round_row["id"], f.score_payload(72),
                             member_headers(first_member_id)),
            200,
        )
        assert submitted["status"] == ROUND_SUBMITTED

        playing = fx.read_entry(api, assisted["id"])
        assert playing["entry_status"] == ENTRY_COMPETING
        assert playing["fee_status"] == FEE_PAID
        assert_cents(playing["amount_paid_cents"], 6400, "amount_paid_cents")
        assert_cents(playing["net_fee_due_cents"], 6400, "net_fee_due_cents")

        waiting = fx.read_entry(api, unassisted["id"])
        assert waiting["entry_status"] == ENTRY_ACCEPTED
        assert waiting["fee_status"] == FEE_PAID

    def test_a_waitlisted_entry_may_be_fully_paid(self, api):
        """Money can run ahead of a slot: WAITLISTED and PAID is a legal pairing.

        PRD: "The two advance through disjoint sets of triggers, so an entry may
        perfectly legitimately be `WAITLISTED` and `PAID`, or `ACCEPTED` and
        `UNPAID`."

        Design: Difficulty/non_linear_state_machine/entry_parallel_status_dimensions_move_independently
        """
        ctx = fx.field_set(api, member_count=2, field_size_limit=1)
        accepted, waitlisted = ctx["entries"]
        assert accepted["entry_status"] == ENTRY_ACCEPTED
        assert waitlisted["entry_status"] == ENTRY_WAITLISTED
        assert waitlisted["waitlist_position"] == 1

        paid = fx.pay_entry(api, ctx["member_ids"][1], waitlisted["id"])
        assert paid["fee_status"] == FEE_PAID
        assert paid["entry_status"] == ENTRY_WAITLISTED
        assert paid["waitlist_position"] == 1
        assert fx.read_entry(api, accepted["id"])["fee_status"] != FEE_PAID


def _submitted_card(api, gross_strokes=66):
    """A live event with one card sitting at SUBMITTED, awaiting its marker."""
    ctx = fx.tournament_in_progress(api, 2)
    round_row = fx.create_round(
        api, ctx["entry_ids"][0], ctx["member_ids"][1], 1, fx.TEE_TIME_ROUND_ONE
    )
    validate_success(
        api.submit_score(round_row["id"], f.score_payload(gross_strokes),
                         member_headers(ctx["member_ids"][0])),
        200,
    )
    ctx["round_id"] = round_row["id"]
    return ctx


def _resubmit(api, ctx, gross_strokes):
    return validate_success(
        api.submit_score(ctx["round_id"], f.score_payload(gross_strokes),
                         member_headers(ctx["member_ids"][0])),
        200,
    )


def _dispute(api, ctx, note):
    return validate_success(
        api.peer_verify(ctx["round_id"], f.peer_verify_payload(PEER_DISPUTE, note=note),
                        member_headers(ctx["member_ids"][1])),
        200,
    )


class TestRoundDisputeCycle:
    """SUBMITTED and DISPUTED cycle twice, and the third dispute leaves the cycle."""

    def test_third_dispute_voids_the_card_instead_of_returning_it(self, api):
        """Two disputes hand the card back; the third ends the loop at NO_CARD.

        PRD: "When the round's `dispute_count` is already 2 before the increment,
        the third dispute ends the loop instead of continuing it: `dispute_count`
        is set to 3, the round moves `SUBMITTED → NO_CARD`, and both
        `adjusted_gross` and `scoring_differential` stay null."

        Design: Difficulty/non_linear_state_machine/round_dispute_cycle_returns_to_submitted_then_voids_at_limit
        """
        ctx = _submitted_card(api, 66)

        first = _dispute(api, ctx, "front nine total does not reconcile")
        assert first["status"] == ROUND_DISPUTED
        assert first["dispute_count"] == 1

        second_card = _resubmit(api, ctx, 67)
        assert second_card["status"] == ROUND_SUBMITTED

        second = _dispute(api, ctx, "hole 14 still shows the wrong stroke count")
        assert second["dispute_count"] == 2
        assert second["status"] == ROUND_DISPUTED

        _resubmit(api, ctx, 68)
        third = _dispute(api, ctx, "third card still disagrees with the marker's tally")
        assert third["status"] == ROUND_NO_CARD
        assert third["dispute_count"] == 3
        assert third["scoring_differential"] is None
        assert third["adjusted_gross"] is None

        entry = fx.read_entry(api, ctx["entry_ids"][0])
        assert entry["certified_round_count"] == 0
        assert entry["avg_scoring_differential"] is None
        assert entry["entry_status"] == ENTRY_COMPETING

    def test_a_disputed_card_can_be_resubmitted_and_then_verified(self, api):
        """The loop is re-entrant: a first dispute is not the end of the card.

        PRD: "When the round's `dispute_count` is 0 or 1 before the increment, the
        dispute raises `dispute_count` by one and advances the round `SUBMITTED →
        DISPUTED`, returning the card to the golfer for resubmission and closing
        the loop `SUBMITTED → DISPUTED → SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/round_dispute_cycle_returns_to_submitted_then_voids_at_limit
        """
        ctx = _submitted_card(api, 66)

        disputed = _dispute(api, ctx, "the marker's card reads one stroke fewer")
        assert disputed["status"] == ROUND_DISPUTED
        assert disputed["dispute_count"] == 1

        corrected = _resubmit(api, ctx, 67)
        assert corrected["status"] == ROUND_SUBMITTED
        assert corrected["gross_strokes"] == 67
        assert corrected["dispute_count"] == 1

        verified = validate_success(
            api.peer_verify(ctx["round_id"], f.peer_verify_payload(PEER_VERIFY),
                            member_headers(ctx["member_ids"][1])),
            200,
        )
        assert verified["status"] == ROUND_PEER_VERIFIED
        assert verified["dispute_count"] == 1
