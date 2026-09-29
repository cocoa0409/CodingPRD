"""
The four compensating pairs, each walked forward and then back.

The invariant under test is that the return hop restores the exact figures the
forward hop found, not merely a plausible-looking state.
"""

from typing import Dict, List, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    GM_HEADERS,
    PRODUCER_HEADERS,
    ApiClient,
    World,
    factories,
    fixtures,
)


def _accounts_by_investor(api: ApiClient, world: World) -> Dict[str, dict]:
    rows, _ = validate_paginated(
        api.list_investor_accounts(
            COMPTROLLER_HEADERS, {"production_id": world.production_id}
        )
    )
    return {row["investor_id"]: row for row in rows}


def _ledger_snapshot(world: World) -> Dict[str, object]:
    production = world.production()
    return {
        key: production[key]
        for key in (
            "capital_raised_cents",
            "escrow_balance_cents",
            "active_investor_count",
            "offering_status",
        )
    }


class TestAcceptThenRescind:
    """Rescission unwinds acceptance to exactly the same depth."""

    def _two_investor_offering(
        self, api: ApiClient
    ) -> Tuple[World, List[str], List[str]]:
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        fixtures.with_effective_document(
            world,
            offering_amount_cents=120_000_000,
            unit_price_cents=60_000_000,
            max_investors=5,
        )
        investor_ids: List[str] = []
        subscription_ids: List[str] = []
        for index in range(2):
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

    def test_rescinding_restores_the_one_unit_snapshot_exactly(self, api: ApiClient):
        """Capital, escrow, headcount and the syndication axis all come back.

        "Accept-then-rescind conserves the production's `capital_raised_cents`
        exactly."

        Design: Difficulty/compensating_invariant/subscription_accept_then_rescind_conserves_capital_and_ownership
        """
        world, _, subscription_ids = self._two_investor_offering(api)

        fixtures.accept_subscription(world, subscription_ids[0])
        one_unit = _ledger_snapshot(world)
        assert one_unit == {
            "capital_raised_cents": 60_000_000,
            "escrow_balance_cents": 60_000_000,
            "active_investor_count": 1,
            "offering_status": "OFFERING",
        }

        fixtures.accept_subscription(world, subscription_ids[1])
        assert _ledger_snapshot(world) == {
            "capital_raised_cents": 120_000_000,
            "escrow_balance_cents": 120_000_000,
            "active_investor_count": 2,
            "offering_status": "FULLY_SUBSCRIBED",
        }

        get_success_data(
            api.rescind_subscription(
                subscription_ids[1], factories.rescission_payload(), COUNSEL_HEADERS
            ),
            200,
        )
        assert _ledger_snapshot(world) == one_unit

    def test_the_surviving_account_is_reprorated_back_to_the_whole_show(
        self, api: ApiClient
    ):
        """The rescinded investor's account is emptied, and the other owns it all.

        "It then unwinds the cascade to exactly the same depth: the investor's
        capital account is recomputed downward, `ownership_pct` is recomputed for
        every capital account of the production, and the production's
        `capital_raised_cents`, `escrow_balance_cents` and
        `active_investor_count` are re-rolled — and if `capital_raised_cents` has
        fallen below `capitalization_target_cents`, the syndication axis reverts
        `FULLY_SUBSCRIBED → OFFERING`."

        Design: Difficulty/compensating_invariant/subscription_accept_then_rescind_conserves_capital_and_ownership
        """
        world, investor_ids, subscription_ids = self._two_investor_offering(api)
        fixtures.accept_subscription(world, subscription_ids[0])
        fixtures.accept_subscription(world, subscription_ids[1])

        halves = _accounts_by_investor(api, world)
        assert halves[investor_ids[0]]["ownership_pct"] == 0.500000
        assert halves[investor_ids[1]]["ownership_pct"] == 0.500000

        rescinded = get_success_data(
            api.rescind_subscription(
                subscription_ids[1], factories.rescission_payload(), COUNSEL_HEADERS
            ),
            200,
        )
        assert rescinded["status"] == "RESCINDED"
        assert rescinded["rescission_reason"]
        assert (
            get_success_data(
                api.get_subscription(subscription_ids[0], COUNSEL_HEADERS), 200
            )["status"]
            == "ACCEPTED"
        )

        after = _accounts_by_investor(api, world)
        assert after[investor_ids[0]]["ownership_pct"] == 1.000000
        assert after[investor_ids[0]]["contributed_cents"] == 60_000_000
        assert after[investor_ids[0]]["units_total"] == 1
        assert after[investor_ids[1]]["ownership_pct"] == 0.000000
        assert after[investor_ids[1]]["units_total"] == 0
        assert sum(row["ownership_pct"] for row in after.values()) == 1.000000


class TestCertifyThenVoid:
    """Voiding unwinds all five hops of certification, including the deferral."""

    def _two_certified_weeks(self, api: ApiClient) -> Tuple[World, str, str]:
        world = fixtures.ledger_world(
            api,
            capitalization_target_cents=18_362_500,
            unit_price_cents=18_362_500,
            pool_basis=True,
        )
        fixtures.with_submitted_standard_week(world)
        profitable_id = world.wrap_id or ""
        fixtures.certify_wrap(world, profitable_id)
        assert world.production()["recoupment_status"] == "RECOUPED"

        world.set_clock("2026-09-14")
        losing_id = fixtures.new_wrap(
            world,
            week_ending_date="2026-09-13",
            gross_receipts_cents=30_000_000,
            paid_attendance=4_000,
        )
        fixtures.submit_wrap(world, losing_id)
        fixtures.certify_wrap(world, losing_id)
        assert world.production()["deferred_royalty_cents"] == 800_000
        return world, profitable_id, losing_id

    def test_voiding_the_loss_week_gives_back_the_deferral(self, api: ApiClient):
        """The accrued guarantees leave the production, and the cash ledger stands.

        "Every allocation of that wrap whose `status` is `ALLOCATED` becomes
        `REVERSED` and its `version` advances; each affected participant's
        `cumulative_royalty_cents` is re-rolled downward, since reversed
        allocations no longer count; the recoupment figures are re-derived without
        this wrap, because a `VOID` wrap is outside the certified input set, and
        this wrap's `deferred_royalty_added_cents` is subtracted from the
        production's `deferred_royalty_cents`; and if the recompute drops
        `recouped_amount_cents` back below `capitalization_target_cents`, the
        production reverts to `UNRECOUPED` and every capital account flips its
        `basis` back to `RECOUPMENT_RETURN`."

        Design: Difficulty/compensating_invariant/wrap_certify_then_void_conserves_recoupment_and_deferral_ledgers
        """
        world, _, losing_id = self._two_certified_weeks(api)

        get_success_data(
            api.void_weekly_wrap(losing_id, factories.void_payload(), COMPTROLLER_HEADERS),
            200,
        )

        production = world.production()
        assert production["deferred_royalty_cents"] == 0
        assert production["recouped_amount_cents"] == 18_362_500
        assert production["recoupment_status"] == "RECOUPED"

        # A loss week's pool was 0, so it never produced an allocation to reverse.
        _, meta = validate_paginated(
            api.list_royalty_allocations(COMPTROLLER_HEADERS, {"wrap_id": losing_id})
        )
        assert meta["total_count"] == 0

    def test_voiding_the_profitable_week_unwinds_the_recoupment_flip(
        self, api: ApiClient
    ):
        """Both weeks gone, the ledger is back to zero and the basis reverts.

        "Certify-then-void conserves the production's `recouped_amount_cents`
        exactly."

        Design: Difficulty/compensating_invariant/wrap_certify_then_void_conserves_recoupment_and_deferral_ledgers
        """
        world, profitable_id, losing_id = self._two_certified_weeks(api)

        for wrap_id in (losing_id, profitable_id):
            voided = get_success_data(
                api.void_weekly_wrap(
                    wrap_id, factories.void_payload(), COMPTROLLER_HEADERS
                ),
                200,
            )
            assert voided["status"] == "VOID"

        production = world.production()
        assert production["recouped_amount_cents"] == 0
        assert production["recoupment_pct"] == 0.0000
        assert production["recoupment_status"] == "UNRECOUPED"
        assert production["distributable_cash_cents"] == 0
        assert production["distributed_total_cents"] == 0
        # The raise itself is untouched by show accounting.
        assert production["capital_raised_cents"] == 18_362_500

        rows, meta = validate_paginated(
            api.list_royalty_allocations(COMPTROLLER_HEADERS, {"wrap_id": profitable_id})
        )
        assert meta["total_count"] == 3
        assert [row["status"] for row in rows] == ["REVERSED"] * 3

        for participant_id in world.participant_ids:
            participant = get_success_data(
                api.get_royalty_participant(participant_id, GM_HEADERS), 200
            )
            assert participant["cumulative_royalty_cents"] == 0

        account = fixtures.sole_account(world)
        assert account["basis"] == "RECOUPMENT_RETURN"
        assert account["recoupment_credited_cents"] == 0


class TestTerminateThenReinstate:
    """The participation cycle conserves the point total and the shares."""

    def _shares(self, api: ApiClient, world: World) -> Dict[str, dict]:
        rows, _ = validate_paginated(
            api.list_royalty_participants(
                GM_HEADERS, {"production_id": world.production_id}
            )
        )
        return {row["id"]: row for row in rows}

    def test_terminating_a_participation_reprorates_the_survivors(
        self, api: ApiClient
    ):
        """Nine points become seven, and the two survivors split them 4:3.

        "Terminating sets that participant's `pool_share_pct` to 0.0000,
        re-rolls the production's `total_pool_points`, recomputes every surviving
        `ACTIVE` participant's `pool_share_pct`, and advances the production's
        `version`."

        Design: Difficulty/compensating_invariant/participant_terminate_then_reinstate_conserves_pool_points_and_shares
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        author_id, composer_id, director_id = world.participant_ids

        before = self._shares(api, world)
        assert before[author_id]["pool_share_pct"] == 0.4445
        assert before[composer_id]["pool_share_pct"] == 0.3333
        assert before[director_id]["pool_share_pct"] == 0.2222
        assert world.production()["total_pool_points"] == 9

        terminated = get_success_data(
            api.terminate_royalty_participant(director_id, PRODUCER_HEADERS), 200
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["pool_share_pct"] == 0.0000

        after = self._shares(api, world)
        # 4/7 and 3/7 round to 0.5714 and 0.4286, which already sum to 1.0000.
        assert after[author_id]["pool_share_pct"] == 0.5714
        assert after[composer_id]["pool_share_pct"] == 0.4286
        assert world.production()["total_pool_points"] == 7

    def test_reinstating_restores_the_point_total_and_every_share(
        self, api: ApiClient
    ):
        """The round trip is exact, down to the pinned residue on the author.

        "The pair conserves `total_pool_points` exactly: terminate then reinstate
        returns the production to the point total it had."

        Design: Difficulty/compensating_invariant/participant_terminate_then_reinstate_conserves_pool_points_and_shares
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        author_id, composer_id, director_id = world.participant_ids
        before = self._shares(api, world)

        get_success_data(
            api.terminate_royalty_participant(director_id, PRODUCER_HEADERS), 200
        )
        reinstated = get_success_data(
            api.reinstate_royalty_participant(director_id, PRODUCER_HEADERS), 200
        )
        assert reinstated["status"] == "ACTIVE"

        after = self._shares(api, world)
        assert world.production()["total_pool_points"] == 9
        for participant_id in (author_id, composer_id, director_id):
            assert (
                after[participant_id]["pool_share_pct"]
                == before[participant_id]["pool_share_pct"]
            )
            assert (
                after[participant_id]["pool_points"]
                == before[participant_id]["pool_points"]
            )
            assert after[participant_id]["cumulative_royalty_cents"] == 0
        assert after[author_id]["pool_share_pct"] == 0.4445
        assert after[director_id]["pool_share_pct"] == 0.2222


class TestIssueThenWithdrawClosingNotice:
    """Withdrawal reverses all three hops of posting a closing notice."""

    def _notice_ready_world(self, api: ApiClient) -> Tuple[World, str]:
        world = fixtures.ledger_world(api, pool_basis=True)
        fixtures.with_reserve_line(world, 2_000_000)
        line_id = world.reserve_line_id or ""
        fixtures.with_submitted_standard_week(world)
        fixtures.certify_wrap(world, world.wrap_id or "")

        planned = get_success_data(api.get_budget_line(line_id, GM_HEADERS), 200)
        assert planned["commitment_status"] == "PLANNED"
        production = world.production()
        assert production["budget_committed_cents"] == 0
        assert production["operating_status"] == "RUNNING"
        return world, line_id

    def test_posting_commits_the_reserve_and_withdrawal_gives_it_back(
        self, api: ApiClient
    ):
        """The committed total goes up on posting and back down on withdrawal.

        "The production returns to `RUNNING`, every `RESERVE` line that is
        `COMMITTED` reverts to `PLANNED`, and `budget_committed_cents` is
        re-rolled."

        Design: Difficulty/compensating_invariant/closing_notice_issue_then_withdraw_conserves_committed_budget
        """
        world, line_id = self._notice_ready_world(api)

        fixtures.with_issued_closing_notice(
            world, notice_date="2026-09-07", final_performance_date="2026-09-21"
        )
        issued = world.production()
        assert issued["operating_status"] == "CLOSING_NOTICE"
        assert issued["budget_committed_cents"] == 2_000_000
        assert (
            get_success_data(api.get_budget_line(line_id, GM_HEADERS), 200)[
                "commitment_status"
            ]
            == "COMMITTED"
        )

        withdrawn = get_success_data(
            api.withdraw_closing_notice(
                world.closing_notice_id or "",
                factories.withdrawal_payload("Investor group funded eight more weeks"),
                PRODUCER_HEADERS,
            ),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason"] == (
            "Investor group funded eight more weeks"
        )

        restored = world.production()
        assert restored["operating_status"] == "RUNNING"
        assert restored["budget_committed_cents"] == 0
        assert (
            get_success_data(api.get_budget_line(line_id, GM_HEADERS), 200)[
                "commitment_status"
            ]
            == "PLANNED"
        )
        assert restored["recouped_amount_cents"] == 18_362_500

    def test_a_withdrawn_notice_is_not_an_issued_one_so_a_second_may_be_posted(
        self, api: ApiClient
    ):
        """The single-notice constraint counts only notices still in ISSUED.

        "The production may not already hold a notice in `ISSUED` status, else
        `ERR_CLOSING_NOTICE_ALREADY_ISSUED` (HTTP 409)."

        Design: Difficulty/compensating_invariant/closing_notice_issue_then_withdraw_conserves_committed_budget
        """
        world, line_id = self._notice_ready_world(api)
        fixtures.with_issued_closing_notice(
            world, notice_date="2026-09-07", final_performance_date="2026-09-21"
        )
        first_notice_id = world.closing_notice_id or ""
        get_success_data(
            api.withdraw_closing_notice(
                first_notice_id,
                factories.withdrawal_payload("Investor group funded eight more weeks"),
                PRODUCER_HEADERS,
            ),
            200,
        )

        second = get_success_data(
            api.create_closing_notice(
                factories.closing_notice_payload(
                    world.production_id, "2026-09-07", "2026-09-28"
                ),
                PRODUCER_HEADERS,
            ),
            201,
        )
        assert second["status"] == "ISSUED"
        assert second["notice_days"] == 21

        reposted = world.production()
        assert reposted["operating_status"] == "CLOSING_NOTICE"
        assert reposted["budget_committed_cents"] == 2_000_000
        assert (
            get_success_data(api.get_budget_line(line_id, GM_HEADERS), 200)[
                "commitment_status"
            ]
            == "COMMITTED"
        )

        rows, meta = validate_paginated(
            api.list_closing_notices(
                PRODUCER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["status"] for row in rows) == ["ISSUED", "WITHDRAWN"]
