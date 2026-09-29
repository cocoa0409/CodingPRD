"""Composed formulas behind the draft order and the rookie money ledger.

Three arithmetic chains in this domain are built from several dependent steps
whose evaluation order changes the answer: the four-step draft-order ranking
that turns seeding inputs and a drawn combination sequence into a slot order,
the slotted rookie contract whose bonus is prorated per year before being
summed, and the undrafted-signing budget whose credit rate is keyed on the base
pool that precedes the credit.
"""

from typing import Dict

import pytest

from test_helpers import (
    CYCLE_SETUP_NOW,
    UDFA_WINDOW_CLOSE_AT,
    ApiClient,
    advance_clock,
    assert_cents_equal,
    build_first_selection,
    create_cycle,
    declare_prospect,
    make_club_gm_headers,
    move_phase,
    offer_drafted_contract,
    player_contract_payload,
    read_club,
    read_cycle,
    read_prospect,
    register_club,
    register_prospect,
    run_lottery,
    set_clock,
    sign_contract,
    validate_success,
)

# Seeding inputs for the clubs outside the shared seed set.
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

# The blocks laid out in pre-lottery order are HAR 1-140, BRN 141-265,
# CED 266-370, DEL 371-460 and ELM 461-535 out of 535 assigned combinations.
_LOTTERY_DRAW = [500, 300, 500, 200, 50]


@pytest.fixture
def six_club_lottery_run(api: ApiClient) -> Dict:
    """Six clubs seeded and the drawn sequence resolved into four slots."""
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
    cycle = run_lottery(api, cycle["id"], _LOTTERY_DRAW)
    return {
        "cycle": read_cycle(api, cycle["id"]),
        "clubs": {code: read_club(api, club["id"]) for code, club in clubs.items()},
    }


class TestDraftOrderRanking:
    """Seeding, combination blocks, slot truncation and the playoff tail."""

    def test_pre_lottery_seed_breaks_the_record_tie_on_strength_of_schedule(
        self, api: ApiClient, six_club_lottery_run: Dict
    ) -> None:
        """Brenton and Cedar Falls tie at 0.250 and separate on schedule strength.

        "Order that pool by `prior_season_win_pct` ascending, so the worst record
        seeds first; break ties by `strength_of_schedule` ascending; break remaining
        ties by `head_to_head_rank` ascending; break any remaining tie by
        `created_at` ascending."

        Design: Difficulty/combinatorial_formula/lottery_order_nonlinear_seed_tiebreak_duplicate_skip_and_playoff_tail
        """
        clubs = six_club_lottery_run["clubs"]

        assert clubs["HAR"]["pre_lottery_rank"] == 1
        assert clubs["BRN"]["pre_lottery_rank"] == 2
        assert clubs["CED"]["pre_lottery_rank"] == 3
        assert clubs["DEL"]["pre_lottery_rank"] == 4
        assert clubs["ELM"]["pre_lottery_rank"] == 5
        assert clubs["FOX"]["pre_lottery_rank"] == 0

    def test_duplicate_draw_awards_nothing_and_the_slot_list_stops_at_four(
        self, api: ApiClient, six_club_lottery_run: Dict
    ) -> None:
        """The repeated 500 is skipped, so the four slots read ELM, CED, BRN, HAR.

        "If that club already holds a slot, skip the value and move on — a duplicate
        draw awards nothing."

        Design: Difficulty/combinatorial_formula/lottery_order_nonlinear_seed_tiebreak_duplicate_skip_and_playoff_tail
        """
        state = six_club_lottery_run
        clubs = state["clubs"]

        assert state["cycle"]["lottery_completed"] is True
        assert state["cycle"]["lottery_slot_club_ids"] == [
            clubs["ELM"]["id"],
            clubs["CED"]["id"],
            clubs["BRN"]["id"],
            clubs["HAR"]["id"],
        ]

    def test_playoff_club_tails_the_order_behind_every_non_playoff_club(
        self, api: ApiClient, six_club_lottery_run: Dict
    ) -> None:
        """Slot winners lead, unslotted Delta Bay follows, Foxridge drafts last.

        "Every playoff club therefore drafts after every non-playoff club, no matter
        how poor its record."

        Design: Difficulty/combinatorial_formula/lottery_order_nonlinear_seed_tiebreak_duplicate_skip_and_playoff_tail
        """
        clubs = six_club_lottery_run["clubs"]

        assert clubs["ELM"]["draft_order_index"] == 1
        assert clubs["CED"]["draft_order_index"] == 2
        assert clubs["BRN"]["draft_order_index"] == 3
        assert clubs["HAR"]["draft_order_index"] == 4
        assert clubs["DEL"]["draft_order_index"] == 5
        assert clubs["FOX"]["draft_order_index"] == 6


class TestSlottedRookieContractMoney:
    """The pinned proration order behind the cap figures."""

    def test_first_year_charge_and_commitment_use_the_pinned_proration_order(
        self, api: ApiClient
    ) -> None:
        """Overall pick one commits 818361940 cents, a cent above the shortcut.

        "It must not be computed as `total_value_cents` plus `signing_bonus_cents`:
        because the per-year share is rounded before being multiplied back up, the
        pinned order can differ from that shortcut by as much as one cent per
        contract year."

        Design: Difficulty/combinatorial_formula/rookie_contract_bonus_prorated_per_year_before_summation
        """
        state = build_first_selection(api)
        elm = state["clubs"]["ELM"]
        prospect = read_prospect(api, state["prospect"]["id"])

        response = api.create_player_contract(
            player_contract_payload(
                prospect["id"],
                elm["id"],
                "DRAFTED",
                prospect["version"],
                draft_pick_id=state["used_pick"]["id"],
            ),
            make_club_gm_headers(elm["id"]),
        )
        contract = validate_success(response, expected_status=201)

        assert contract["contract_years"] == 4
        assert_cents_equal(contract["total_value_cents"], 511476212)
        assert_cents_equal(contract["signing_bonus_cents"], 306885727)
        assert_cents_equal(contract["first_year_cap_charge_cents"], 196721432)
        assert_cents_equal(contract["total_cap_commitment_cents"], 818361940)
        assert contract["total_cap_commitment_cents"] != 818361939
        assert contract["status"] == "OFFERED"
        assert read_prospect(api, prospect["id"])["signing_status"] == "OFFER_OUT"

    def test_minted_pick_carries_the_same_slotting_arithmetic(
        self, api: ApiClient, order_final: Dict
    ) -> None:
        """Overall pick one is minted with the four read-only slot money fields.

        "The same slotting arithmetic runs at draft-order finalize time for every
        minted pick, populating four read-only fields on the pick from that pick's
        own position and the four-year drafted length: `slot_total_value_cents`,
        `slot_signing_bonus_cents`, `slot_first_year_cap_charge_cents` and
        `slot_total_cap_commitment_cents`."

        Design: Difficulty/combinatorial_formula/rookie_contract_bonus_prorated_per_year_before_summation
        """
        pick = order_final["pick"]["r1p1"]

        assert_cents_equal(pick["slot_total_value_cents"], 511476212)
        assert_cents_equal(pick["slot_signing_bonus_cents"], 306885727)
        assert_cents_equal(pick["slot_first_year_cap_charge_cents"], 196721432)
        assert_cents_equal(pick["slot_total_cap_commitment_cents"], 818361940)

    def test_pinned_proration_can_land_one_cent_under_the_shortcut(
        self, api: ApiClient, order_final: Dict
    ) -> None:
        """Overall pick two commits 804722573 cents, a cent below the shortcut.

        "And `total_cap_commitment_cents` is `total_value_cents` plus the per-year
        bonus share multiplied by `contract_years`."

        Design: Difficulty/combinatorial_formula/rookie_contract_bonus_prorated_per_year_before_summation
        """
        pick = order_final["pick"]["r1p2"]

        assert_cents_equal(pick["slot_total_value_cents"], 502951609)
        assert_cents_equal(pick["slot_signing_bonus_cents"], 301770965)
        assert_cents_equal(pick["slot_first_year_cap_charge_cents"], 193442741)
        assert_cents_equal(pick["slot_total_cap_commitment_cents"], 804722573)
        assert pick["slot_total_cap_commitment_cents"] != 804722574


class TestUndraftedPoolAllocation:
    """The credit rate tier and the base pool it is keyed on."""

    def test_credit_rate_tier_is_keyed_on_the_base_pool_not_the_credited_total(
        self, api: ApiClient
    ) -> None:
        """A 110000000 base pool takes the 0.40 rate and totals 167049207 cents.

        "This tier must be selected before the credit is added, never from the
        post-credit total; reversing the two steps changes the tier and therefore
        the answer."

        Design: Difficulty/combinatorial_formula/udfa_pool_credit_rate_tier_keyed_on_base_pool_not_post_credit_total
        """
        state = build_first_selection(api)
        cycle_id = state["cycle"]["id"]
        elm = state["clubs"]["ELM"]
        contract = offer_drafted_contract(
            api, state["prospect"], elm, state["used_pick"]
        )

        set_clock(api, "2027-04-23T00:00:00.000Z")
        advance_clock(api, cycle_id)
        sign_contract(api, contract)
        cycle = move_phase(api, cycle_id, "UDFA_WINDOW")

        elm_after = read_club(api, elm["id"])
        assert_cents_equal(elm_after["rookie_pool_remaining_cents"], 700000000)
        assert_cents_equal(elm_after["udfa_pool_total_cents"], 167049207)
        assert elm_after["udfa_pool_total_cents"] != 145655755
        assert_cents_equal(elm_after["udfa_pool_remaining_cents"], 167049207)
        assert cycle["status"] == "UDFA_WINDOW"
        assert cycle["udfa_window_close_at"] == UDFA_WINDOW_CLOSE_AT

    @pytest.mark.parametrize(
        "club_code, expected_udfa_pool_total_cents",
        [("ELM", 214508256), ("HAR", 223969910)],
    )
    def test_credit_rate_falls_as_each_club_own_base_pool_rises(
        self,
        api: ApiClient,
        udfa_window: Dict,
        club_code: str,
        expected_udfa_pool_total_cents: int,
    ) -> None:
        """Elmwood's larger rollover earns the 0.25 rate, Harbor City's the 0.40.

        "The rate is 0.25 when the base pool is at least 120,000,000 cents;
        otherwise 0.40 when the base pool is at least 60,000,000 cents; otherwise
        0.55."

        Design: Difficulty/combinatorial_formula/udfa_pool_credit_rate_tier_keyed_on_base_pool_not_post_credit_total
        """
        club = read_club(api, udfa_window["clubs"][club_code]["id"])

        assert_cents_equal(
            club["udfa_pool_total_cents"], expected_udfa_pool_total_cents
        )
        assert_cents_equal(
            club["udfa_pool_remaining_cents"], expected_udfa_pool_total_cents
        )

    def test_undrafted_budget_is_zero_until_the_draft_completes(
        self, api: ApiClient, order_final: Dict
    ) -> None:
        """No club carries an undrafted budget while the order is merely final.

        "The result is `udfa_pool_total_cents`, which is 0 for every club before the
        draft completes and is frozen at this transition."

        Design: Difficulty/combinatorial_formula/udfa_pool_credit_rate_tier_keyed_on_base_pool_not_post_credit_total
        """
        for club in order_final["clubs"].values():
            fresh = read_club(api, club["id"])
            assert_cents_equal(fresh["udfa_pool_total_cents"], 0)
            assert_cents_equal(fresh["udfa_pool_remaining_cents"], 0)
