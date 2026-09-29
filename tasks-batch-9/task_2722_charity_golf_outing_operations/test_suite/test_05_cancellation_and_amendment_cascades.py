"""Two multi-hop cascades: a cancellation, and a mid-round rating amendment."""

import pytest

from test_helpers import (
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    TREASURER_HEADERS,
    assert_inventory_conservation,
    assert_receipt_ledger,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

CASCADE_OUTING = {
    "name": "Cascade Classic",
    "format": "SCRAMBLE",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
CASCADE_CONTRACT = {
    "guaranteed_player_count": 0,
    "cancellation_notice_days": 30,
}
HOLE_3_SIGN = {
    "asset_type": "HOLE_SIGN",
    "label": "Hole 3 tee sign",
    "hole_number": 3,
    "capacity": 1,
    "exclusive": True,
    "list_price_cents": 50000,
}


def _full_field_with_upsell_and_receipt(api):
    """One confirmed package holding a committed upsell, plus a waitlisted one.

    The field sells four player slots, so the second paid package can only
    waitlist, and the first package's receipt puts a live deductible on the
    outing before anything is unwound.
    """
    ctx = fx.open_outing(api, outing=CASCADE_OUTING, contract=CASCADE_CONTRACT)
    reg_a = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Fairway Freight", player_count=4
    )
    ctx["a_id"] = reg_a["id"]
    assert fx.pay_registration(api, ctx["a_id"], 120000)["status"] == "CONFIRMED"

    reg_b = fx.new_registration(
        api, ctx["outing_id"], ctx["tier_id"], buyer_name="Iron Works", player_count=4
    )
    ctx["b_id"] = reg_b["id"]
    assert fx.pay_registration(api, ctx["b_id"], 120000)["status"] == "WAITLISTED"

    asset = fx.new_asset(api, ctx["outing_id"], **HOLE_3_SIGN)
    ctx["asset_id"] = asset["id"]
    allocation = fx.new_allocation(api, ctx["a_id"], asset["id"], "UPSELL")
    ctx["allocation_id"] = allocation["id"]
    fx.drive_fulfillment(api, allocation["id"], "COMMIT")

    receipt = fx.issue_registration_receipt(api, ctx["outing_id"], ctx["a_id"])
    ctx["receipt"] = receipt
    ctx["receipt_id"] = receipt["id"]
    return ctx


def _cancel(api, registration_id):
    return validate_success(
        api.registration_lifecycle(
            registration_id, f.registration_lifecycle_payload("CANCEL"), DIRECTOR_HEADERS
        )
    )


class TestRegistrationCancellationCascade:
    def test_cancel_releases_the_allocation_down_to_the_outing_slot_counter(self, api):
        """The PRD chains the release: "Every sponsor allocation belonging to this
        registration whose status is not already `RELEASED` is moved to `RELEASED`",
        then "Each release in step 3 decrements the occupancy counter of its
        sponsorship asset and re-derives that asset's `remaining_capacity` and
        inventory posture", and then "The asset counters written in step 4 re-derive
        the outing's `reserved_asset_slot_count`".  Outside the notice window
        "`late_cancel_fee_cents` stays 0 and the refund is the whole of
        `amount_paid_cents`".

        Design: Difficulty/transitive_cascade/registration_cancel_cascades_allocation_asset_outing_inventory_and_waitlist
        """
        ctx = _full_field_with_upsell_and_receipt(api)
        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 1

        cancelled = _cancel(api, ctx["a_id"])
        assert cancelled["status"] == "REFUNDED"
        assert cancelled["late_cancel_fee_cents"] == 0
        assert cancelled["amount_refunded_cents"] == 120000

        assert fx.read_allocation(api, ctx["allocation_id"])["status"] == "RELEASED"

        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["reserved_count"] == 0
        assert asset["committed_count"] == 0
        assert asset["fulfilled_count"] == 0
        assert asset["remaining_capacity"] == 1
        assert asset["status"] == "AVAILABLE"
        assert_inventory_conservation(asset)

        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 0

    def test_cancel_promotes_exactly_one_waitlisted_package(self, api):
        """The PRD makes the freed slots reach the queue: "When the outing's play
        dimension is `OPEN`, the freed slots are offered to the waitlist as described
        below, and exactly one waitlisted registration may be promoted."  The winner
        "moves `WAITLISTED → CONFIRMED`, which stamps its `confirmed_at`, snapshots
        `handicap_index_at_confirm` on every one of its players and recomputes their
        `course_handicap`, and re-derives the tier's `sold_count` along with the
        outing's `confirmed_player_slots` and `waitlisted_registration_count`".

        Design: Difficulty/transitive_cascade/registration_cancel_cascades_allocation_asset_outing_inventory_and_waitlist
        """
        ctx = _full_field_with_upsell_and_receipt(api)
        _cancel(api, ctx["a_id"])

        assert fx.read_registration(api, ctx["b_id"])["status"] == "CONFIRMED"
        assert fx.read_tier(api, ctx["tier_id"])["sold_count"] == 1

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["waitlisted_registration_count"] == 0
        assert outing["confirmed_player_slots"] == 4

    def test_cancel_appends_a_reversal_and_rewrites_the_finance_rollup(self, api):
        """The PRD closes the cascade with two more hops: "When a charitable receipt of
        kind `REGISTRATION` with no live reversal exists for this registration, a
        reversal receipt row is appended with negated amounts and the outing's
        `receipted_deductible_total_cents` is re-derived", and "The outing's whole
        finance rollup is recomputed under its current `proceeds_variant`."

        Design: Difficulty/transitive_cascade/registration_cancel_cascades_allocation_asset_outing_inventory_and_waitlist
        """
        ctx = _full_field_with_upsell_and_receipt(api)
        assert ctx["receipt"]["payment_cents"] == 120000
        assert ctx["receipt"]["gsv_cents"] == 24000
        assert ctx["receipt"]["deductible_amount_cents"] == 96000
        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 96000

        _cancel(api, ctx["a_id"])

        receipts = fx.list_data(
            api.list_receipts(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        reversals = [r for r in receipts if r["receipt_kind"] == "REVERSAL"]
        assert len(reversals) == 1
        reversal = reversals[0]
        assert reversal["reverses_receipt_id"] == ctx["receipt_id"]
        assert reversal["payment_cents"] == -120000
        assert reversal["gsv_cents"] == -24000
        assert reversal["deductible_amount_cents"] == -96000

        original = fx.read_receipt(api, ctx["receipt_id"])
        for field in ("receipt_kind", "receipt_number", "payment_cents", "gsv_cents",
                      "deductible_amount_cents", "created_at"):
            assert original[field] == ctx["receipt"][field], (
                f"the reversed receipt must be immutable, but {field} changed"
            )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["receipted_deductible_total_cents"] == 0
        assert_receipt_ledger(outing, receipts)

        assert outing["gross_revenue_cents"] == 120000
        assert outing["refunded_cents"] == 120000
        assert outing["course_charge_cents"] == 38000
        assert outing["direct_costs_cents"] == 38000
        assert outing["net_proceeds_before_fee_cents"] == -38000
        assert outing["admin_fee_cents"] == 0
        assert outing["net_proceeds_cents"] == -38000


RATING_OUTING = {
    "name": "Rating Plate Open",
    "format": "SCRAMBLE",
    "field_capacity_teams": 1,
    "prize_pool_cents": 0,
}
RATING_CONTRACT = {
    "guaranteed_player_count": 4,
    "course_rating": 71.4,
    "slope_rating": 128,
    "par": 72,
    "tee_interval_minutes": 10,
    "cart_allowance_count": 4,
}
RATING_INDEXES = (12.0, 18.4, 8.2, 24.0)
POSTED_SCORE = {
    "gross_score": 68,
    "gross_back_9": 33,
    "gross_back_6": 22,
    "gross_back_3": 11,
    "gross_hole_18": 4,
}


def _team_with_a_posted_card(api):
    """A locked, in-play team that has already posted its gross card."""
    ctx = fx.open_outing(api, outing=RATING_OUTING, contract=RATING_CONTRACT)
    reg = fx.confirmed_registration(
        api, ctx, players=RATING_INDEXES, buyer_name="Bogey Bros",
        names=["A1", "A2", "A3", "A4"],
    )
    team = fx.new_team(api, ctx["outing_id"], reg["player_ids"], team_name="Bogey Bros")
    ctx.update(reg)
    ctx["team_id"] = team["id"]
    fx.lock_field(api, ctx["outing_id"])
    # Play may only start once every group has been placed on the tee sheet.
    fx.assign_tee(api, team["id"])
    fx.start_play(api, ctx["outing_id"])
    ctx["team"] = validate_success(
        api.post_score(team["id"], f.score_payload(**POSTED_SCORE), COURSE_HEADERS)
    )
    return ctx


def _amend_slope(api, contract_id, slope_rating):
    return validate_success(
        api.contract_lifecycle(
            contract_id,
            f.contract_lifecycle_payload("AMEND", slope_rating=slope_rating),
            COURSE_HEADERS,
        )
    )


class TestContractRatingAmendmentCascade:
    def test_amending_the_slope_rating_rewrites_players_then_the_team_figure(self, api):
        """The PRD names the chain: "Amending a contract's course rating, slope rating,
        or par rewrites the course handicap of every player of the outing; the new
        course handicaps rewrite the playing handicap of every team of the outing under
        whichever handicap variant that team currently carries".  The amendment itself
        "moves it `SIGNED → AMENDED`" and "increments `amendment_count` by one".

        Design: Difficulty/transitive_cascade/contract_amendment_cascades_player_handicap_team_handicap_net_score
        """
        ctx = _team_with_a_posted_card(api)
        before = [fx.read_player(api, pid)["course_handicap"] for pid in ctx["player_ids"]]
        assert before == [13, 20, 9, 27]
        assert ctx["team"]["team_playing_handicap"] == pytest.approx(7.1, abs=0.01)
        assert ctx["team"]["handicap_variant"] == "LOCKED"

        contract = _amend_slope(api, ctx["contract_id"], 113)
        assert contract["status"] == "AMENDED"
        assert contract["slope_rating"] == pytest.approx(113, abs=0.01)
        assert contract["amendment_count"] == 1

        after = [fx.read_player(api, pid)["course_handicap"] for pid in ctx["player_ids"]]
        assert after == [11, 18, 8, 23]

        team = fx.read_team(api, ctx["team_id"])
        assert team["team_playing_handicap"] == pytest.approx(6.2, abs=0.01)
        assert team["handicap_variant"] == "LOCKED"

    def test_the_amendment_rewrites_all_five_net_figures_and_no_gross_one(self, api):
        """The PRD closes the chain: "the new playing handicaps rewrite the net score
        and all four net tiebreak metrics of every team that has already posted a gross
        score", where "`net_score` is the `gross_score` less the whole
        `team_playing_handicap`, rounded half up to one decimal place" and
        "`net_back_9` is the `gross_back_9` less half the `team_playing_handicap`,
        rounded half up to two decimal places".

        Design: Difficulty/transitive_cascade/contract_amendment_cascades_player_handicap_team_handicap_net_score
        """
        ctx = _team_with_a_posted_card(api)
        posted = ctx["team"]
        assert posted["net_score"] == pytest.approx(60.9, abs=0.01)
        assert posted["net_back_9"] == pytest.approx(29.45, abs=0.01)
        assert posted["net_back_6"] == pytest.approx(19.63, abs=0.01)
        assert posted["net_back_3"] == pytest.approx(9.82, abs=0.01)
        assert posted["net_hole_18"] == pytest.approx(3.61, abs=0.01)

        _amend_slope(api, ctx["contract_id"], 113)
        team = fx.read_team(api, ctx["team_id"])

        assert team["net_score"] == pytest.approx(61.8, abs=0.01)
        assert team["net_back_9"] == pytest.approx(29.9, abs=0.01)
        assert team["net_back_6"] == pytest.approx(19.93, abs=0.01)
        assert team["net_back_3"] == pytest.approx(9.97, abs=0.01)
        assert team["net_hole_18"] == pytest.approx(3.66, abs=0.01)

        assert team["gross_score"] == 68
        assert team["gross_back_9"] == 33
        assert team["gross_back_6"] == 22
        assert team["gross_back_3"] == 11
        assert team["gross_hole_18"] == 4
