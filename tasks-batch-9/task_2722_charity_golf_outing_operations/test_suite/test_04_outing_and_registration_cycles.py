"""Cycles, self-loops and a fork whose branches close one another off."""

import pytest

from test_helpers import (
    DIRECTOR_HEADERS,
    SPONSORSHIP_HEADERS,
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CYCLE_OUTING = {
    "name": "Reopen Rodeo",
    "format": "SCRAMBLE",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
CYCLE_CONTRACT = {"guaranteed_player_count": 4}
CYCLE_INDEXES = (12.0, 18.4, 8.2, 24.0)

BRONZE = {"code": "BRONZE", "price_cents": 120000, "player_slots": 4, "gsv_cents": 24000}
SILVER = {"code": "SILVER", "price_cents": 150000, "player_slots": 4, "gsv_cents": 30000}
GOLD = {"code": "GOLD", "price_cents": 180000, "player_slots": 4, "gsv_cents": 36000}

SPONSOR_TIER = {
    "code": "GOLD",
    "price_cents": 250000,
    "player_slots": 0,
    "gsv_cents": 0,
    "inventory_cap": 5,
    "entitled_asset_type": "HOLE_SIGN",
    "entitled_asset_count": 1,
}
HOLE_SIGN = {
    "asset_type": "HOLE_SIGN",
    "label": "Hole 7 tee sign",
    "hole_number": 7,
    "capacity": 1,
    "exclusive": True,
    "list_price_cents": 50000,
}


def _one_team_outing(api):
    """An OPEN outing carrying exactly one complete foursome."""
    ctx = fx.open_outing(api, outing=CYCLE_OUTING, contract=CYCLE_CONTRACT)
    reg = fx.confirmed_registration(
        api, ctx, players=CYCLE_INDEXES, buyer_name="Cycle Co",
        names=["C1", "C2", "C3", "C4"],
    )
    team = fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name="Cycle Co")
    ctx.update(reg)
    ctx["team_id"] = team["id"]
    return ctx


class TestFieldReopenCycle:
    def test_a_third_reopen_is_refused_after_the_cap_is_reached(self, api):
        """The PRD caps the cycle: "an outing may be reopened at most twice. Each
        accepted reopen increments `reopen_count` by one, and a request that arrives
        when `reopen_count` already equals 2 is refused with
        `ERR_MAX_REOPENS_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/outing_field_reopen_cycle_with_independent_finance_dimension
        """
        ctx = _one_team_outing(api)
        for _ in range(2):
            fx.lock_field(api, ctx["outing_id"])
            fx.reopen_field(api, ctx["outing_id"])
        outing = fx.lock_field(api, ctx["outing_id"])
        assert outing["reopen_count"] == 2

        validate_error(
            api.play_transition(
                ctx["outing_id"],
                f.play_transition_payload("OPEN_REGISTRATION"),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.MAX_REOPENS_EXCEEDED,
        )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["reopen_count"] == 2
        assert outing["play_status"] == "FIELD_LOCKED"

    def test_the_lock_cycle_never_moves_the_finance_dimension(self, api):
        """The PRD keeps the two tracks apart: "An outing has a play dimension,
        `play_status`, and a finance dimension, `finance_status`" and "Neither
        dimension of a pair is derived from the other, and neither shares a trigger
        with the other."

        Design: Difficulty/non_linear_state_machine/outing_field_reopen_cycle_with_independent_finance_dimension
        """
        ctx = _one_team_outing(api)
        assert fx.read_outing(api, ctx["outing_id"])["finance_status"] == "COLLECTING"

        for expected_reopens in (0, 1):
            locked = fx.lock_field(api, ctx["outing_id"])
            assert locked["play_status"] == "FIELD_LOCKED"
            assert locked["finance_status"] == "COLLECTING"
            assert locked["reopen_count"] == expected_reopens
            team = fx.read_team(api, ctx["team_id"])
            assert team["handicap_variant"] == "LOCKED"
            assert team["team_playing_handicap"] == pytest.approx(7.1, abs=0.01)

            reopened = fx.reopen_field(api, ctx["outing_id"])
            assert reopened["play_status"] == "OPEN"
            assert reopened["finance_status"] == "COLLECTING"
            assert reopened["reopen_count"] == expected_reopens + 1
            team = fx.read_team(api, ctx["team_id"])
            assert team["handicap_variant"] == "PROVISIONAL"
            assert team["team_playing_handicap"] == pytest.approx(7.1, abs=0.01)

        final = fx.lock_field(api, ctx["outing_id"])
        assert final["finance_status"] == "COLLECTING"
        assert fx.read_team(api, ctx["team_id"])["handicap_variant"] == "LOCKED"


class TestRegistrationAmendSelfLoop:
    def _bronze_registration(self, api):
        ctx = fx.open_outing(
            api,
            outing={"name": "Amendment Open", "field_capacity_teams": 2},
            contract=CYCLE_CONTRACT,
            tier=BRONZE,
        )
        ctx["silver_id"] = fx.add_tier(api, ctx, **SILVER)["id"]
        ctx["gold_id"] = fx.add_tier(api, ctx, **GOLD)["id"]
        reg = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Upgrade Inc", player_count=4
        )
        ctx["registration"] = fx.pay_registration(api, reg["id"], 120000)
        ctx["registration_id"] = reg["id"]
        return ctx

    def test_a_second_amendment_takes_the_self_loop_and_still_increments_the_count(self, api):
        """The PRD gives the amendment a self-loop: "It moves a registration
        `CONFIRMED → AMENDED`, and from `AMENDED` it loops back to `AMENDED` so a
        package can be re-amended any number of times while the field is open; the
        preconditions and side effects of the self-loop are identical to those of the
        first amendment."  Each hop pays "the new tier's `price_cents` minus the
        currently held tier's `price_cents`", and "A positive delta is added to
        `amount_paid_cents`".

        Design: Difficulty/non_linear_state_machine/registration_amend_reconfirm_cycle_with_self_loop
        """
        ctx = self._bronze_registration(api)
        version = ctx["registration"]["version"]

        amended = validate_success(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(ctx["silver_id"], version, amount_cents=30000),
                DIRECTOR_HEADERS,
            )
        )
        assert amended["status"] == "AMENDED"
        assert amended["package_tier_id"] == ctx["silver_id"]
        assert amended["amount_paid_cents"] == 150000
        assert amended["amendment_count"] == 1

        looped = validate_success(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(ctx["gold_id"], amended["version"], amount_cents=30000),
                DIRECTOR_HEADERS,
            )
        )
        assert looped["status"] == "AMENDED"
        assert looped["package_tier_id"] == ctx["gold_id"]
        assert looped["amount_paid_cents"] == 180000
        assert looped["amendment_count"] == 2

        assert fx.read_tier(api, ctx["tier_id"])["sold_count"] == 0
        assert fx.read_tier(api, ctx["gold_id"])["sold_count"] == 1
        assert fx.read_outing(api, ctx["outing_id"])["gross_revenue_cents"] == 180000

    def test_reconfirming_closes_the_cycle_without_touching_the_amendment_count(self, api):
        """The PRD makes reconfirmation the way back: "it returns a registration
        `AMENDED → CONFIRMED` and closes the confirm-amend cycle", and its only
        condition is fiscal, namely that "`amount_paid_cents` minus
        `amount_refunded_cents` must equal the held tier's `price_cents` exactly,
        otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`".

        Design: Difficulty/non_linear_state_machine/registration_amend_reconfirm_cycle_with_self_loop
        """
        ctx = self._bronze_registration(api)
        version = ctx["registration"]["version"]
        amended = validate_success(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(ctx["silver_id"], version, amount_cents=30000),
                DIRECTOR_HEADERS,
            )
        )
        amended = validate_success(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(ctx["gold_id"], amended["version"], amount_cents=30000),
                DIRECTOR_HEADERS,
            )
        )

        reconfirmed = validate_success(
            api.registration_lifecycle(
                ctx["registration_id"],
                f.registration_lifecycle_payload("RECONFIRM"),
                DIRECTOR_HEADERS,
            )
        )
        assert reconfirmed["status"] == "CONFIRMED"
        assert reconfirmed["amendment_count"] == 2
        assert reconfirmed["amount_refunded_cents"] == 0
        assert reconfirmed["amount_paid_cents"] == 180000


class TestSponsorAllocationWaiveBranch:
    def _committed_entitlement(self, api):
        ctx = fx.sponsor_outing(
            api,
            outing={"name": "Sponsor Fork Open", "field_capacity_teams": 1},
            tier=SPONSOR_TIER,
            asset=HOLE_SIGN,
            buyer_name="Summit Bank",
        )
        allocation = fx.new_allocation(
            api, ctx["registration_id"], ctx["asset_id"], "PACKAGE_ENTITLEMENT"
        )
        ctx["allocation_id"] = allocation["id"]
        ctx["allocation"] = fx.drive_fulfillment(api, allocation["id"], "COMMIT")
        return ctx

    def test_waiving_credits_sixty_percent_of_the_list_price_up_three_hops(self, api):
        """On the waiver branch the PRD says "the allocation's
        `fulfillment_credit_cents` is set to 0.60 of the unit's `list_price_cents`",
        and that "it re-derives `fulfillment_credit_cents` on the linked registration
        as the sum of that registration's waived allocations, which re-derives the
        outing's `fulfillment_credit_cents` as the sum over all its waived
        allocations".  It adds that "waiving moves the occupancy from
        `committed_count` into `fulfilled_count` and re-derives the unit's posture".

        Design: Difficulty/non_linear_state_machine/sponsor_allocation_fork_join_waive_branch
        """
        ctx = self._committed_entitlement(api)

        waived = validate_success(
            api.allocation_fulfillment(
                ctx["allocation_id"],
                f.fulfillment_payload("WAIVE", waived_reason="Sign vendor missed the print run"),
                SPONSORSHIP_HEADERS,
            )
        )
        assert waived["status"] == "WAIVED"
        assert waived["fulfillment_credit_cents"] == 30000

        assert fx.read_registration(api, ctx["registration_id"])["fulfillment_credit_cents"] == 30000
        assert fx.read_outing(api, ctx["outing_id"])["fulfillment_credit_cents"] == 30000

        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["fulfilled_count"] == 1
        assert asset["committed_count"] == 0
        assert asset["remaining_capacity"] == 0
        assert asset["status"] == "FULFILLED"

    def test_the_artwork_branch_is_closed_once_the_waiver_is_taken(self, api):
        """The PRD closes the fork: "`VERIFIED` and `WAIVED` are both terminal", and a
        request whose action "is a declared edge out of the target row's current state
        in the relevant lifecycle" is otherwise refused with
        "`ERR_INVALID_STATE_TRANSITION` (HTTP 409)".

        Design: Difficulty/non_linear_state_machine/sponsor_allocation_fork_join_waive_branch
        """
        ctx = self._committed_entitlement(api)
        fx.drive_fulfillment(
            api, ctx["allocation_id"], "WAIVE",
            waived_reason="Sign vendor missed the print run",
        )

        validate_error(
            api.allocation_fulfillment(
                ctx["allocation_id"],
                f.fulfillment_payload("APPROVE_ARTWORK"),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        allocation = fx.read_allocation(api, ctx["allocation_id"])
        assert allocation["status"] == "WAIVED"
        assert allocation["artwork_approved_by_user_id"] is None
        assert allocation["fulfillment_credit_cents"] == 30000
