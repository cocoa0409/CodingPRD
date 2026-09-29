"""
The three deepest write cascades: certification, settlement, and acceptance.

Each is driven by a single request, and each is inspected hop by hop, because a
cascade that stops one hop short still returns a plausible-looking 200.
"""

from typing import Dict, List, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import (
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    GM_HEADERS,
    PRODUCER_HEADERS,
    ApiClient,
    World,
    fixtures,
)


def _certified_standard_week(world: World) -> str:
    """Move past the week ending 2026-09-06, record it, submit it, certify it."""
    fixtures.with_submitted_standard_week(world)
    wrap_id = world.wrap_id or ""
    fixtures.certify_wrap(world, wrap_id)
    return wrap_id


def _allocations(api: ApiClient, wrap_id: str) -> Tuple[Dict[str, dict], dict]:
    """The allocation rows a certification wrote, keyed by participant."""
    rows, meta = validate_paginated(
        api.list_royalty_allocations(COMPTROLLER_HEADERS, {"wrap_id": wrap_id})
    )
    return {row["royalty_participant_id"]: row for row in rows}, meta


def _committed_reserve_line(world: World, amount_cents: int) -> str:
    """Plan a RESERVE line, approve the budget, and commit the line."""
    fixtures.with_reserve_line(world, amount_cents)
    line_id = world.reserve_line_id or ""
    get_success_data(
        world.client.approve_budget(world.production_id, PRODUCER_HEADERS), 200
    )
    committed = get_success_data(
        world.client.commit_budget_line(line_id, GM_HEADERS), 200
    )
    assert committed["commitment_status"] == "COMMITTED"
    return line_id


class TestCertificationCascade:
    """One certify request writes the wrap, the allocations, the participants,
    the recoupment ledger, and the capital accounts."""

    def test_the_first_three_hops_reach_the_participants_cumulative_royalties(
        self, api: ApiClient
    ):
        """Settled figures, then allocation rows, then each participant's running total.

        "Certification then cascades five hops deep. The wrap's settled figures
        are written and `certified_by_user_id` is recorded. Second, the royalty
        pool is split into one allocation row per eligible participant. Third,
        each participant's `cumulative_royalty_cents` is re-rolled."

        Design: Difficulty/transitive_cascade/certify_wrap_five_hop_cascade_flips_recoupment_and_investor_basis
        """
        world = fixtures.ledger_world(
            api,
            capitalization_target_cents=18_362_500,
            unit_price_cents=18_362_500,
            pool_basis=True,
        )
        wrap_id = _certified_standard_week(world)

        wrap = get_success_data(api.get_weekly_wrap(wrap_id, GM_HEADERS), 200)
        assert wrap["status"] == "CERTIFIED"
        assert wrap["royalty_pool_cents"] == 9_887_500
        assert wrap["weekly_operating_profit_cents"] == 18_362_500
        assert wrap["certified_by_user_id"] == fixtures.CERTIFIER_USER_ID

        author_id, composer_id, director_id = world.participant_ids
        rows, meta = _allocations(api, wrap_id)
        assert meta["total_count"] == 3
        assert rows[author_id]["allocated_cents"] == 4_394_445
        assert rows[composer_id]["allocated_cents"] == 3_295_833
        assert rows[director_id]["allocated_cents"] == 2_197_222

        for participant_id, expected in (
            (author_id, 4_394_445),
            (composer_id, 3_295_833),
            (director_id, 2_197_222),
        ):
            participant = get_success_data(
                api.get_royalty_participant(participant_id, GM_HEADERS), 200
            )
            assert participant["cumulative_royalty_cents"] == expected

    def test_the_last_two_hops_recoup_the_show_and_rebase_the_investor(
        self, api: ApiClient
    ):
        """The week's profit exactly meets the target, so the account flips basis.

        "Fifth, if that recompute has carried `recouped_amount_cents` to or past
        `capitalization_target_cents`, the production's `recoupment_status`
        becomes `RECOUPED`, and every capital account of the production flips its
        `basis` from `RECOUPMENT_RETURN` to `NET_PROFIT` and refreshes its
        `recoupment_credited_cents`."

        Design: Difficulty/transitive_cascade/certify_wrap_five_hop_cascade_flips_recoupment_and_investor_basis
        """
        world = fixtures.ledger_world(
            api,
            capitalization_target_cents=18_362_500,
            unit_price_cents=18_362_500,
            pool_basis=True,
        )
        _certified_standard_week(world)

        production = world.production()
        assert production["recouped_amount_cents"] == 18_362_500
        assert production["recoupment_pct"] == 1.0000
        assert production["recoupment_status"] == "RECOUPED"
        assert production["distributable_cash_cents"] == 18_362_500
        assert production["distributed_total_cents"] == 0

        account = fixtures.sole_account(world)
        assert account["basis"] == "NET_PROFIT"
        assert account["recoupment_credited_cents"] == 18_362_500
        assert account["ownership_pct"] == 1.000000


class TestSettlementCascade:
    """One settle request spends the reserve, recoups the show, and closes it."""

    def _notice_ready_world(self, api: ApiClient) -> World:
        world = fixtures.ledger_world(
            api,
            capitalization_target_cents=20_000_000,
            unit_price_cents=20_000_000,
            pool_basis=True,
        )
        _committed_reserve_line(world, 2_000_000)
        _certified_standard_week(world)

        pre_settlement = world.production()
        assert pre_settlement["recouped_amount_cents"] == 18_362_500
        assert pre_settlement["recoupment_pct"] == 0.9181
        assert pre_settlement["recoupment_status"] == "UNRECOUPED"

        fixtures.with_issued_closing_notice(
            world, notice_date="2026-09-07", final_performance_date="2026-09-21"
        )
        notice = get_success_data(
            api.get_closing_notice(world.closing_notice_id or "", PRODUCER_HEADERS), 200
        )
        assert notice["status"] == "ISSUED"
        assert notice["notice_days"] == 14
        assert world.production()["operating_status"] == "CLOSING_NOTICE"
        return world

    def test_settlement_releases_the_surviving_reserve_and_spends_the_line(
        self, api: ApiClient
    ):
        """300,000 of costs against a 2,000,000 reserve releases 1,700,000.

        "Settlement then cascades four hops. The notice becomes the terminal
        `SETTLED`. Every `RESERVE` line that was `COMMITTED` becomes the terminal
        `SPENT`, and the reserve release is booked."

        Design: Difficulty/transitive_cascade/settle_closing_notice_four_hop_cascade_releases_reserve_and_closes
        """
        world = self._notice_ready_world(api)

        settled = get_success_data(
            fixtures.settle_closing_notice(world, closing_costs_cents=300_000), 200
        )
        assert settled["status"] == "SETTLED"
        assert settled["closing_costs_cents"] == 300_000
        assert settled["reserve_released_cents"] == 1_700_000
        assert settled["closing_cost_shortfall_cents"] == 0

        line = get_success_data(
            api.get_budget_line(world.reserve_line_id or "", GM_HEADERS), 200
        )
        assert line["commitment_status"] == "SPENT"

    def test_the_release_carries_the_show_past_its_target_and_closes_it(
        self, api: ApiClient
    ):
        """1,700,000 on top of 18,362,500 clears a 20,000,000 target on the way out.

        "And if that recompute carries the ledger to or past
        `capitalization_target_cents`, the production's `recoupment_status`
        becomes `RECOUPED` and every capital account of the production flips its
        `basis` to `NET_PROFIT` and refreshes its `recoupment_credited_cents` — a
        show can, and often does, recoup on its closing reserve release."

        Design: Difficulty/transitive_cascade/settle_closing_notice_four_hop_cascade_releases_reserve_and_closes
        """
        world = self._notice_ready_world(api)

        get_success_data(
            fixtures.settle_closing_notice(world, closing_costs_cents=300_000), 200
        )

        production = world.production()
        assert production["recouped_amount_cents"] == 20_062_500
        assert production["recoupment_pct"] == 1.0031
        assert production["recoupment_status"] == "RECOUPED"
        assert production["operating_status"] == "CLOSED"
        assert production["budget_committed_cents"] == 2_000_000

        account = fixtures.sole_account(world)
        assert account["basis"] == "NET_PROFIT"
        assert account["recoupment_credited_cents"] == 20_062_500


class TestAcceptanceCascade:
    """One accept request re-prorates every capital account of the production."""

    def _three_way_offering(self, api: ApiClient) -> Tuple[World, List[str], List[str]]:
        world = fixtures.base_world(api, capitalization_target_cents=180_000_000)
        fixtures.open_offering(world)
        fixtures.with_effective_document(
            world,
            offering_amount_cents=180_000_000,
            unit_price_cents=60_000_000,
            max_investors=5,
        )
        investor_ids: List[str] = []
        subscription_ids: List[str] = []
        for index in range(3):
            investor_id = fixtures.new_accredited_investor(
                world,
                legal_name=f"Investor {index + 1}",
                contact_email=f"investor{index + 1}@example.com",
            )
            investor_ids.append(investor_id)
            subscription_ids.append(
                fixtures.new_subscription(world, investor_id, units=1)
            )
        return world, investor_ids, subscription_ids

    def _accounts_by_investor(self, api: ApiClient, world: World) -> Dict[str, dict]:
        rows, _ = validate_paginated(
            api.list_investor_accounts(
                COMPTROLLER_HEADERS, {"production_id": world.production_id}
            )
        )
        return {row["investor_id"]: row for row in rows}

    def test_the_third_accept_reprorates_the_two_accounts_it_did_not_touch(
        self, api: ApiClient
    ):
        """Two halves become three thirds, and the residue lands on the earliest account.

        "Because that account's units changed, `ownership_pct` is then recomputed
        for **every** capital account of the production, not merely the one that
        moved."

        Design: Difficulty/transitive_cascade/accept_subscription_four_hop_cascade_reprorates_all_ownership
        """
        world, investor_ids, subscription_ids = self._three_way_offering(api)

        fixtures.accept_subscription(world, subscription_ids[0])
        fixtures.accept_subscription(world, subscription_ids[1])
        halves = self._accounts_by_investor(api, world)
        assert halves[investor_ids[0]]["ownership_pct"] == 0.500000
        assert halves[investor_ids[1]]["ownership_pct"] == 0.500000

        third = fixtures.accept_subscription(world, subscription_ids[2])
        assert third["status"] == "ACCEPTED"
        assert third["amount_cents"] == 60_000_000

        thirds = self._accounts_by_investor(api, world)
        assert len(thirds) == 3
        # Each raw share rounds to 0.333333, leaving +0.000001 for the earliest
        # of the three accounts tied at one unit.
        assert thirds[investor_ids[0]]["ownership_pct"] == 0.333334
        assert thirds[investor_ids[1]]["ownership_pct"] == 0.333333
        assert thirds[investor_ids[2]]["ownership_pct"] == 0.333333
        assert (
            sum(row["ownership_pct"] for row in thirds.values()) == 1.000000
        )
        for row in thirds.values():
            assert row["units_total"] == 1
            assert row["contributed_cents"] == 60_000_000

    def test_the_final_hop_re_rolls_the_production_and_fills_the_offering(
        self, api: ApiClient
    ):
        """The third unit takes the raise to the target and flips the syndication axis.

        "And because ownership and contributions changed, the production's
        `capital_raised_cents` (the sum of `amount_cents` over accepted
        subscriptions across all of the production's instruments),
        `escrow_balance_cents`, and `active_investor_count` (the number of the
        production's capital accounts whose `units_total` is greater than zero)
        are re-rolled; if `capital_raised_cents` has reached or passed
        `capitalization_target_cents`, the syndication axis advances `OFFERING →
        FULLY_SUBSCRIBED`."

        Design: Difficulty/transitive_cascade/accept_subscription_four_hop_cascade_reprorates_all_ownership
        """
        world, _, subscription_ids = self._three_way_offering(api)
        for subscription_id in subscription_ids:
            fixtures.accept_subscription(world, subscription_id)

        production = world.production()
        assert production["capital_raised_cents"] == 180_000_000
        assert production["escrow_balance_cents"] == 180_000_000
        assert production["active_investor_count"] == 3
        assert production["offering_status"] == "FULLY_SUBSCRIBED"
        assert production["operating_status"] == "PRE_PRODUCTION"

        for row in self._accounts_by_investor(api, world).values():
            assert row["basis"] == "RECOUPMENT_RETURN"
            assert row["recoupment_credited_cents"] == 0

        document = get_success_data(
            api.get_offering_document(world.offering_document_id or "", COUNSEL_HEADERS),
            200,
        )
        assert document["accepted_amount_cents"] == 180_000_000
        assert document["accepted_investor_count"] == 3
        assert document["accepted_units_total"] == 3
