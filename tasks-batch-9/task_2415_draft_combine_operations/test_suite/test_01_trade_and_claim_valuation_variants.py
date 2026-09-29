"""Authoritative and advisory valuation variants.

Two areas of the domain publish two different figures for the same inputs. A
pick trade publishes the positional chart balance that gates acceptance beside
the market-surplus balance that never does, and a compensatory claim publishes
the banded authoritative score beside the raw-participation advisory score.
These tests pin both members of each pair on identical data.
"""

from typing import Dict

import pytest

from test_helpers import (
    CYCLE_SETUP_NOW,
    ERR_TRADE_VALUE_IMBALANCED,
    ApiClient,
    assert_chart_points,
    assert_imbalance_ratio,
    assert_score,
    compensatory_claim_payload,
    create_cycle,
    declare_prospect,
    finalize_order,
    list_picks,
    make_club_gm_headers,
    move_phase,
    pick_index,
    pick_trade_payload,
    read_pick,
    read_trade,
    register_club,
    register_prospect,
    run_lottery,
    set_clock,
    validate_error,
    validate_success,
)

# Seeding inputs for the clubs outside the shared seed set. Cedar Falls ties
# Brenton on prior-season record and is separated by strength of schedule
# alone; Foxridge is the single postseason club.
_EXTRA_CLUB_SEEDS: Dict[str, Dict] = {
    "CED": {
        "market_name": "Cedar Falls",
        "prior_season_win_pct": 0.250,
        "strength_of_schedule": 0.510,
        "head_to_head_rank": 3,
        "rookie_pool_total_cents": 500000000,
        "lottery_combinations": 105,
    },
    "DEL": {
        "market_name": "Delta Bay",
        "prior_season_win_pct": 0.375,
        "strength_of_schedule": 0.500,
        "head_to_head_rank": 4,
        "rookie_pool_total_cents": 500000000,
        "lottery_combinations": 90,
    },
    "FOX": {
        "market_name": "Foxridge",
        "prior_season_win_pct": 0.750,
        "strength_of_schedule": 0.505,
        "head_to_head_rank": 6,
        "rookie_pool_total_cents": 500000000,
        "playoff_qualified": True,
        "playoff_exit_round": 2,
        "lottery_combinations": 0,
    },
}

# Registration order, which fixes the created_at tiebreak of the seeding sort.
_CLUB_ORDER = ("HAR", "BRN", "CED", "DEL", "ELM", "FOX")

# Combination blocks are HAR 1-140, BRN 141-265, CED 266-370, DEL 371-460 and
# ELM 461-535, so this draw seats ELM, CED, BRN and HAR in that slot order and
# the repeated 500 awards nothing.
_LOTTERY_DRAW = [500, 300, 500, 200, 50]


def _build_six_club_order_final(api: ApiClient) -> Dict:
    """A two-round 2027 cycle at ORDER_FINAL with its twelve picks minted."""
    set_clock(api, CYCLE_SETUP_NOW)
    cycle = create_cycle(api, rounds_count=2)
    clubs = {
        code: register_club(
            api, cycle["id"], code, **_EXTRA_CLUB_SEEDS.get(code, {})
        )
        for code in _CLUB_ORDER
    }
    move_phase(api, cycle["id"], "DECLARATION_OPEN")
    declare_prospect(api, register_prospect(api, cycle["id"]))
    move_phase(api, cycle["id"], "COMBINE_WEEK")
    move_phase(api, cycle["id"], "ORDER_PENDING")
    run_lottery(api, cycle["id"], _LOTTERY_DRAW)
    finalize_order(api, cycle["id"])
    picks = list_picks(api, cycle["id"])
    return {"cycle": cycle, "clubs": clubs, "pick": pick_index(picks)}


@pytest.fixture
def six_club_order_final(api: ApiClient) -> Dict:
    return _build_six_club_order_final(api)


@pytest.fixture
def cycle_with_claiming_club(api: ApiClient) -> Dict:
    """A 2027 cycle at SETUP with Harbor City registered and no claims filed."""
    set_clock(api, CYCLE_SETUP_NOW)
    cycle = create_cycle(api, rounds_count=2)
    return {"cycle": cycle, "club": register_club(api, cycle["id"], "HAR")}


class TestTradeChartAndSurplusVariants:
    """The two valuations a single pick package produces."""

    def test_chart_variant_and_surplus_variant_carry_opposite_signs(
        self, api: ApiClient, six_club_order_final: Dict
    ) -> None:
        """Swapping overall one for overall two loses chart value but gains surplus.

        "Because slotted cost falls far faster across the rounds than market price
        does, this figure can carry the opposite sign from `chart_balance_points`
        for the very same package — a trade the chart calls a loss can be a surplus
        gain."

        Design: Difficulty/dual_variant_calc/trade_chart_variant_and_market_surplus_variant_carry_opposite_signs
        """
        state = six_club_order_final
        elm = state["clubs"]["ELM"]
        ced = state["clubs"]["CED"]
        offered = state["pick"]["r1p1"]
        requested = state["pick"]["r1p2"]
        assert offered["owning_club_id"] == elm["id"]
        assert requested["owning_club_id"] == ced["id"]

        response = api.create_pick_trade(
            pick_trade_payload(
                state["cycle"]["id"],
                elm["id"],
                ced["id"],
                [offered["id"]],
                [requested["id"]],
            ),
            make_club_gm_headers(elm["id"]),
        )
        trade = validate_success(response, expected_status=201)

        assert_chart_points(trade["chart_balance_points"], -60.0)
        assert_imbalance_ratio(trade["imbalance_ratio"], 0.0600)
        assert_chart_points(trade["surplus_balance_points"], 8.5)
        assert trade["chart_balance_points"] < 0
        assert trade["surplus_balance_points"] > 0
        assert trade["status"] == "PROPOSED"
        assert trade["conditional_status"] == "NONE"

    def test_chart_imbalance_beyond_tolerance_blocks_acceptance(
        self, api: ApiClient, six_club_order_final: Dict
    ) -> None:
        """A round-one pick for a round-two pick is refused on the chart ratio.

        "Acceptance is allowed only when `imbalance_ratio` is at most 0.15,
        inclusive at that boundary; a wider gap is refused with
        `ERR_TRADE_VALUE_IMBALANCED`."

        Design: Difficulty/dual_variant_calc/trade_chart_variant_and_market_surplus_variant_carry_opposite_signs
        """
        state = six_club_order_final
        elm = state["clubs"]["ELM"]
        ced = state["clubs"]["CED"]
        offered = state["pick"]["r1p1"]
        requested = state["pick"]["r2p2"]
        assert requested["owning_club_id"] == ced["id"]

        proposal = validate_success(
            api.create_pick_trade(
                pick_trade_payload(
                    state["cycle"]["id"],
                    elm["id"],
                    ced["id"],
                    [offered["id"]],
                    [requested["id"]],
                ),
                make_club_gm_headers(elm["id"]),
            ),
            expected_status=201,
        )
        assert_chart_points(proposal["chart_balance_points"], -605.2)
        assert_imbalance_ratio(proposal["imbalance_ratio"], 0.6052)
        assert_chart_points(proposal["surplus_balance_points"], -711.3)

        refusal = api.accept_pick_trade(
            proposal["id"], None, make_club_gm_headers(ced["id"])
        )
        validate_error(refusal, ERR_TRADE_VALUE_IMBALANCED, expected_status=422)

        after = read_trade(api, proposal["id"])
        assert after["status"] == "PROPOSED"
        assert read_pick(api, offered["id"])["owning_club_id"] == elm["id"]

    def test_acceptance_turns_on_the_chart_variant_alone(
        self, api: ApiClient, six_club_order_final: Dict
    ) -> None:
        """The advisory surplus figure is published but decides nothing.

        "It is published to front offices as guidance and it never gates
        acceptance."

        Design: Difficulty/dual_variant_calc/trade_chart_variant_and_market_surplus_variant_carry_opposite_signs
        """
        state = six_club_order_final
        elm = state["clubs"]["ELM"]
        ced = state["clubs"]["CED"]
        offered = state["pick"]["r1p1"]
        requested = state["pick"]["r1p2"]

        proposal = validate_success(
            api.create_pick_trade(
                pick_trade_payload(
                    state["cycle"]["id"],
                    elm["id"],
                    ced["id"],
                    [offered["id"]],
                    [requested["id"]],
                ),
                make_club_gm_headers(elm["id"]),
            ),
            expected_status=201,
        )

        accepted = validate_success(
            api.accept_pick_trade(
                proposal["id"], None, make_club_gm_headers(ced["id"])
            ),
            expected_status=200,
        )
        assert accepted["status"] == "ACCEPTED"
        assert_imbalance_ratio(accepted["imbalance_ratio"], 0.0600)
        assert_chart_points(accepted["chart_balance_points"], -60.0)
        assert_chart_points(accepted["surplus_balance_points"], 8.5)
        assert read_pick(api, offered["id"])["owning_club_id"] == ced["id"]
        assert read_pick(api, requested["id"])["owning_club_id"] == elm["id"]


class TestCompensatoryClaimScoreVariants:
    """The banded authoritative score beside the raw-share advisory score."""

    def test_banded_snap_factor_and_raw_snap_share_diverge_on_one_claim(
        self, api: ApiClient, cycle_with_claiming_club: Dict
    ) -> None:
        """A departure at a 0.72 participation share scores 1470.00 and 1064.00.

        "`advisory_snap_adjusted_score` is the same base figure multiplied by the
        *raw* `snap_pct` rather than by the band, plus the same honours bonus,
        rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/compensatory_banded_snap_score_and_raw_snap_advisory_diverge
        """
        state = cycle_with_claiming_club
        club = state["club"]

        response = api.create_compensatory_claim(
            compensatory_claim_payload(
                state["cycle"]["id"],
                club["id"],
                player_name="Rowan Petty",
                departed_apy_cents=1450000000,
                snap_pct=0.72,
                postseason_honor="ALL_CONFERENCE",
            ),
            make_club_gm_headers(club["id"]),
        )
        claim = validate_success(response, expected_status=201)

        assert_score(claim["claim_score"], 1470.00)
        assert_score(claim["advisory_snap_adjusted_score"], 1064.00)
        assert_score(
            claim["claim_score"] - claim["advisory_snap_adjusted_score"], 406.00
        )
        assert claim["qualifies"] is True
        assert claim["status"] == "SUBMITTED"
        assert claim["awarded_round"] == 0

    @pytest.mark.parametrize(
        "snap_pct, expected_claim_score, expected_advisory_score",
        [
            (0.65, 1470.00, 962.50),
            (0.72, 1470.00, 1064.00),
            (0.90, 1470.00, 1325.00),
            (0.64, 1252.50, 948.00),
        ],
    )
    def test_shares_inside_one_band_score_identically_while_the_advisory_moves(
        self,
        api: ApiClient,
        cycle_with_claiming_club: Dict,
        snap_pct: float,
        expected_claim_score: float,
        expected_advisory_score: float,
    ) -> None:
        """Every share from 0.65 up scores 1470.00; 0.64 drops to the next band.

        "Because the factor is banded, every participation share inside a band
        scores identically."

        Design: Difficulty/dual_variant_calc/compensatory_banded_snap_score_and_raw_snap_advisory_diverge
        """
        state = cycle_with_claiming_club
        club = state["club"]

        claim = validate_success(
            api.create_compensatory_claim(
                compensatory_claim_payload(
                    state["cycle"]["id"],
                    club["id"],
                    player_name="Rowan Petty",
                    departed_apy_cents=1450000000,
                    snap_pct=snap_pct,
                    postseason_honor="ALL_CONFERENCE",
                ),
                make_club_gm_headers(club["id"]),
            ),
            expected_status=201,
        )

        assert_score(claim["claim_score"], expected_claim_score)
        assert_score(
            claim["advisory_snap_adjusted_score"], expected_advisory_score
        )
        assert claim["qualifies"] is True

    def test_advisory_figure_may_fall_below_the_threshold_the_banded_score_clears(
        self, api: ApiClient, cycle_with_claiming_club: Dict
    ) -> None:
        """A 300.00 banded score qualifies while its 195.00 advisory twin does not.

        "For any participation share strictly inside a band the two figures
        diverge, and a claim can sit below 250.00 on the advisory figure while
        authoritatively qualifying."

        Design: Difficulty/dual_variant_calc/compensatory_banded_snap_score_and_raw_snap_advisory_diverge
        """
        state = cycle_with_claiming_club
        club = state["club"]

        claim = validate_success(
            api.create_compensatory_claim(
                compensatory_claim_payload(
                    state["cycle"]["id"],
                    club["id"],
                    player_name="Marcus Idle",
                    departed_apy_cents=300000000,
                    snap_pct=0.65,
                    postseason_honor="NONE",
                ),
                make_club_gm_headers(club["id"]),
            ),
            expected_status=201,
        )

        assert_score(claim["claim_score"], 300.00)
        assert_score(claim["advisory_snap_adjusted_score"], 195.00)
        assert claim["qualifies"] is True
        assert claim["advisory_snap_adjusted_score"] < 250.00
        assert claim["awarded_round"] == 0
