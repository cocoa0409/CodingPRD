"""Reversals that must land back exactly where they started: the assistance purse
after a pre-deadline withdrawal, and the slot census after a promotion.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_ledger,
    assert_slot_census,
    assert_two_decimals,
)
from test_helpers.constants import SEASON_ASSISTANCE_BUDGET_CENTS
from test_helpers.test_users import TOUR_ADMIN, member_headers
from test_helpers.types import (
    ENTRY_ACCEPTED,
    ENTRY_WAITLISTED,
    ENTRY_WITHDRAWN,
    FEE_REFUNDED,
)


def _assisted_entry(api):
    """A 32,000-cent entry carrying a 28,800-cent award, still APPLIED."""
    ctx = fx.verified_roster(api, member_count=1)
    season = fx.read_season(api, ctx["season_id"])
    assert_cents(season["assistance_available_cents"], SEASON_ASSISTANCE_BUDGET_CENTS,
                 "assistance_available_cents at the start")

    application = fx.approved_aid_application(
        api, ctx["member_ids"][0], ctx["season_id"],
        household_income_cents=6000000, dependents=3,
    )
    assert_two_decimals(application["covered_pct"], 0.90, "covered_pct")

    tournament = fx.create_tournament(api, ctx["season_id"], entry_fee_cents=32000)
    validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)
    entry = fx.submit_entry(
        api, ctx["member_ids"][0], tournament["id"],
        request_assistance=True, aid_application_id=application["id"],
    )
    assert_cents(entry["aid_award_cents"], 28800, "aid_award_cents")
    assert_cents(entry["net_fee_due_cents"], 3200, "net_fee_due_cents")
    assert_ledger(fx.read_season(api, ctx["season_id"]), 471200, 28800, 0)

    ctx["application"] = application
    ctx["tournament"] = tournament
    ctx["tournament_id"] = tournament["id"]
    ctx["entry"] = entry
    return ctx


def _withdraw(api, member_id, entry_id, reason="family travel conflict"):
    return validate_success(
        api.withdraw_entry(entry_id, f.withdrawal_payload(reason),
                           member_headers(member_id)),
        200,
    )


class TestAssistanceLedgerRestoredByWithdrawal:
    """Settlement and pre-deadline withdrawal are an exactly compensating pair."""

    def test_withdrawing_an_applied_entry_returns_every_bucket_to_its_start(self, api):
        """The award goes back to available, never to disbursed.

        PRD: "**Withdrawal** before the deadline reverses that exactly: it adds the
        award back to `assistance_available_cents`, subtracts it from
        `assistance_committed_cents`, and subtracts it from `consumed_cents`."

        Design: Difficulty/compensating_invariant/assistance_ledger_restored_exactly_by_predeadline_withdrawal
        """
        ctx = _assisted_entry(api)
        fx.set_clock(api, "2026-08-20T00:00:00Z")

        withdrawn = _withdraw(api, ctx["member_ids"][0], ctx["entry"]["id"])
        assert withdrawn["entry_status"] == ENTRY_WITHDRAWN
        assert withdrawn["fee_status"] == FEE_REFUNDED
        assert_cents(withdrawn["refunded_cents"], 0, "refunded_cents")

        assert_ledger(fx.read_season(api, ctx["season_id"]),
                      SEASON_ASSISTANCE_BUDGET_CENTS, 0, 0)
        assert_cents(
            validate_success(
                api.get_aid_application(ctx["application"]["id"], TOUR_ADMIN), 200
            )["consumed_cents"],
            0, "consumed_cents",
        )
        assert fx.read_member(api, ctx["member_ids"][0])["late_withdrawal_count"] == 0

        assert_slot_census(fx.read_tournament(api, ctx["tournament_id"]),
                           entry_count=1, applied_count=0, closed_count=1)

    def test_withdrawing_an_accepted_entry_before_the_deadline_restores_it_too(self, api):
        """The same reversal fires once the field has been set, so long as the deadline holds.

        PRD: "Settlement followed by a pre-deadline withdrawal is therefore an
        exactly compensating pair: `assistance_available_cents` returns to its
        precise pre-settlement value."

        Design: Difficulty/compensating_invariant/assistance_ledger_restored_exactly_by_predeadline_withdrawal
        """
        ctx = _assisted_entry(api)
        fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
        validate_success(api.close_entries(ctx["tournament_id"], TOUR_ADMIN), 200)
        validate_success(api.set_field(ctx["tournament_id"], TOUR_ADMIN), 200)
        assert fx.read_entry(api, ctx["entry"]["id"])["entry_status"] == ENTRY_ACCEPTED

        fx.set_clock(api, fx.CLOCK_BEFORE_WITHDRAWAL_DEADLINE)
        withdrawn = _withdraw(api, ctx["member_ids"][0], ctx["entry"]["id"])
        assert withdrawn["entry_status"] == ENTRY_WITHDRAWN
        assert_cents(withdrawn["aid_award_cents"], 0, "aid_award_cents")

        assert_ledger(fx.read_season(api, ctx["season_id"]),
                      SEASON_ASSISTANCE_BUDGET_CENTS, 0, 0)
        assert_cents(
            validate_success(
                api.get_aid_application(ctx["application"]["id"], TOUR_ADMIN), 200
            )["consumed_cents"],
            0, "consumed_cents",
        )
        assert fx.read_member(api, ctx["member_ids"][0])["late_withdrawal_count"] == 0
        assert_slot_census(fx.read_tournament(api, ctx["tournament_id"]),
                           accepted_count=0, waitlist_count=0, closed_count=1,
                           open_slot_count=2)


def _single_slot_queue(api):
    """One playing slot, three applicants, so the queue runs 1 and 2 behind it."""
    ctx = fx.verified_roster(api, member_count=3)
    tournament = fx.create_tournament(api, ctx["season_id"],
                                      name="Single Slot Regional", field_size_limit=1)
    validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

    ctx["entries"] = []
    for index, member_id in enumerate(ctx["member_ids"]):
        fx.set_clock(api, "2026-08-10T0%d:00:00Z" % index)
        ctx["entries"].append(fx.submit_entry(api, member_id, tournament["id"]))
    ctx["entry_ids"] = [entry["id"] for entry in ctx["entries"]]

    fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
    validate_success(api.close_entries(tournament["id"], TOUR_ADMIN), 200)
    field = validate_success(api.set_field(tournament["id"], TOUR_ADMIN), 200)
    assert_slot_census(field, accepted_count=1, waitlist_count=2, open_slot_count=0,
                       closed_count=0)
    assert fx.read_entry(api, ctx["entry_ids"][2])["waitlist_position"] == 2

    ctx["tournament"] = tournament
    ctx["tournament_id"] = tournament["id"]
    fx.set_clock(api, "2026-09-02T00:00:00Z")
    return ctx


class TestSlotCensusConservedByPromotion:
    """A withdrawal answered by a promotion leaves the census where it was."""

    def test_promotion_restores_accepted_and_open_counts_and_renumbers_the_queue(self, api):
        """One call performs two moves, so no slot is left idle and no gap is left behind.

        PRD: "Hop four, performed by that promotion, renumbers the surviving
        waitlist positions and restores `accepted_count` and `open_slot_count` to
        their exact pre-withdrawal values."

        Design: Difficulty/compensating_invariant/slot_census_conserved_by_withdrawal_answered_with_promotion
        """
        ctx = _single_slot_queue(api)

        withdrawn = _withdraw(api, ctx["member_ids"][0], ctx["entry_ids"][0], "injury")
        assert withdrawn["entry_status"] == ENTRY_WITHDRAWN

        after = fx.read_tournament(api, ctx["tournament_id"])
        assert_slot_census(after, entry_count=3, applied_count=0, accepted_count=1,
                           waitlist_count=1, closed_count=1, open_slot_count=0)
        assert_two_decimals(after["field_quality_factor"], 1.00,
                            "field_quality_factor")

        promoted = fx.read_entry(api, ctx["entry_ids"][1])
        assert promoted["entry_status"] == ENTRY_ACCEPTED
        assert promoted["waitlist_position"] is None

        renumbered = fx.read_entry(api, ctx["entry_ids"][2])
        assert renumbered["entry_status"] == ENTRY_WAITLISTED
        assert renumbered["waitlist_position"] == 1
        assert fx.read_member(api, ctx["member_ids"][0])["late_withdrawal_count"] == 0

    def test_a_waitlisted_departure_renumbers_without_promoting_anyone(self, api):
        """No playing slot is freed, so the accepted count does not move.

        PRD: "No promotion fires, because a waitlisted departure frees no playing
        slot."

        Design: Difficulty/compensating_invariant/slot_census_conserved_by_withdrawal_answered_with_promotion
        """
        ctx = _single_slot_queue(api)

        withdrawn = _withdraw(api, ctx["member_ids"][1], ctx["entry_ids"][1], "illness")
        assert withdrawn["entry_status"] == ENTRY_WITHDRAWN
        assert withdrawn["waitlist_position"] is None

        after = fx.read_tournament(api, ctx["tournament_id"])
        assert_slot_census(after, entry_count=3, accepted_count=1, waitlist_count=1,
                           closed_count=1, open_slot_count=0)

        assert fx.read_entry(api, ctx["entry_ids"][0])["entry_status"] == ENTRY_ACCEPTED
        still_waiting = fx.read_entry(api, ctx["entry_ids"][2])
        assert still_waiting["entry_status"] == ENTRY_WAITLISTED
        assert still_waiting["waitlist_position"] == 1
