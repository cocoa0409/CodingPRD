"""
Three thresholds tested at the cent: the recoupment flip and the offering ceiling.

Each is probed on the boundary and one cent to the wrong side of it, because an
off-by-one comparison is invisible anywhere else.
"""

from typing import List, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    ApiClient,
    ApiErrorId,
    World,
    assert_no_write,
    fixtures,
)


def _world_targeting(api: ApiClient, capitalization_target_cents: int) -> World:
    """A pool-basis production whose target is set to probe the flip, one week in."""
    world = fixtures.ledger_world(
        api,
        capitalization_target_cents=capitalization_target_cents,
        unit_price_cents=capitalization_target_cents,
        pool_basis=True,
    )
    fixtures.with_submitted_standard_week(world)
    fixtures.certify_wrap(world, world.wrap_id or "")
    return world


class TestRecoupmentFlipsOnTheCent:
    """A target met exactly to the cent is recouped."""

    def test_hitting_the_target_exactly_flips_the_status(self, api: ApiClient):
        """A 18,362,500 target met by 18,362,500 of profit reads RECOUPED.

        "Its `recoupment_status` is `RECOUPED` when `recouped_amount_cents` is
        greater than or equal to `capitalization_target_cents`, and `UNRECOUPED`
        otherwise — the comparison is inclusive of equality, so hitting the
        target to the cent is recoupment."

        Design: Difficulty/boundary_precision_check/recoupment_flips_at_exactly_target_cents
        """
        world = _world_targeting(api, 18_362_500)

        production = world.production()
        assert production["capitalization_target_cents"] == 18_362_500
        assert production["recouped_amount_cents"] == 18_362_500
        assert production["recoupment_pct"] == 1.0000
        assert production["recoupment_status"] == "RECOUPED"

    def test_the_exact_hit_rebases_the_account_and_the_report_agrees(
        self, api: ApiClient
    ):
        """The authoritative basis moves the status, and the account follows it.

        "The **cash basis** is authoritative: it is what is persisted on the
        production and the only basis that may move `recoupment_status`."

        Design: Difficulty/boundary_precision_check/recoupment_flips_at_exactly_target_cents
        """
        world = _world_targeting(api, 18_362_500)

        account = fixtures.sole_account(world)
        assert account["basis"] == "NET_PROFIT"
        assert account["recoupment_credited_cents"] == 18_362_500

        report = get_success_data(
            api.get_recoupment_report(world.production_id, COMPTROLLER_HEADERS), 200
        )
        assert report["cash_basis_recouped_cents"] == 18_362_500
        assert report["cash_basis_recoupment_pct"] == 1.0000
        assert report["recoupment_status"] == "RECOUPED"
        assert report["deferred_royalty_cents"] == 0


class TestRecoupmentOneCentShort:
    """A percentage that rounds to 1.0000 is not a recoupment."""

    def test_the_percentage_rounds_up_while_the_status_stays_unrecouped(
        self, api: ApiClient
    ):
        """18,362,500 against a 18,362,501 target reads 1.0000 and UNRECOUPED.

        "A rounding subtlety follows and matters for reporting:
        `recoupment_pct` can round up to 1.0000 while `recoupment_status` still
        reads `UNRECOUPED`, because the percentage is rounded and the status test
        is not."

        Design: Difficulty/boundary_precision_check/recoupment_one_cent_short_rounds_to_one_but_stays_unrecouped
        """
        world = _world_targeting(api, 18_362_501)

        production = world.production()
        assert production["capitalization_target_cents"] == 18_362_501
        assert production["recouped_amount_cents"] == 18_362_500
        assert production["recoupment_pct"] == 1.0000
        assert production["recoupment_status"] == "UNRECOUPED"

        report = get_success_data(
            api.get_recoupment_report(world.production_id, COMPTROLLER_HEADERS), 200
        )
        assert report["cash_basis_recoupment_pct"] == 1.0000
        assert report["recoupment_status"] == "UNRECOUPED"

    def test_the_account_keeps_its_recoupment_return_basis_and_is_still_credited(
        self, api: ApiClient
    ):
        """No flip happened, but the credited snapshot still tracks the ledger.

        "Finally, each account's `recoupment_credited_cents` is refreshed as the
        production's `recouped_amount_cents` multiplied by that account's
        `ownership_pct`, rounded half up to whole cents — a snapshot taken at the
        moment of the most recent recoupment recompute."

        Design: Difficulty/boundary_precision_check/recoupment_one_cent_short_rounds_to_one_but_stays_unrecouped
        """
        world = _world_targeting(api, 18_362_501)

        account = fixtures.sole_account(world)
        assert account["ownership_pct"] == 1.000000
        assert account["basis"] == "RECOUPMENT_RETURN"
        assert account["recoupment_credited_cents"] == 18_362_500

        production = world.production()
        assert production["distributable_cash_cents"] == 18_362_500
        assert production["distributed_total_cents"] == 0


class TestOfferingCeilingOnTheCent:
    """The offering fills exactly, and the next unit has nowhere to go."""

    def _offering_with_three_units(
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

    def test_the_second_unit_fills_the_offering_to_the_cent(self, api: ApiClient):
        """120,000,000 of amount against a 120,000,000 offering is admissible.

        "Then the amount: the instrument's `accepted_amount_cents` plus this
        subscription's `amount_cents` may not exceed its `offering_amount_cents`,
        else `ERR_OVERSUBSCRIPTION` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/offering_fills_exactly_at_ceiling_then_next_unit_oversubscribes
        """
        world, _, subscription_ids = self._offering_with_three_units(api)

        fixtures.accept_subscription(world, subscription_ids[0])
        second = fixtures.accept_subscription(world, subscription_ids[1])
        assert second["status"] == "ACCEPTED"

        document = get_success_data(
            api.get_offering_document(world.offering_document_id or "", COUNSEL_HEADERS),
            200,
        )
        assert document["accepted_amount_cents"] == 120_000_000
        assert document["offering_amount_cents"] == 120_000_000

        production = world.production()
        assert production["capital_raised_cents"] == 120_000_000
        assert production["offering_status"] == "FULLY_SUBSCRIBED"

    def test_the_third_unit_breaches_the_ceiling_and_changes_nothing(
        self, api: ApiClient
    ):
        """One cent of headroom would have been needed; there is none.

        "Accepting a subscription may not push the offering document's
        `accepted_amount_cents` above its `offering_amount_cents`; a breach is
        `ERR_OVERSUBSCRIPTION` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/offering_fills_exactly_at_ceiling_then_next_unit_oversubscribes
        """
        world, _, subscription_ids = self._offering_with_three_units(api)
        fixtures.accept_subscription(world, subscription_ids[0])
        fixtures.accept_subscription(world, subscription_ids[1])
        before = world.production()

        refused = api.accept_subscription(subscription_ids[2], COUNSEL_HEADERS)
        validate_error(refused, ApiErrorId.OVERSUBSCRIPTION)

        assert (
            get_success_data(
                api.get_subscription(subscription_ids[2], COUNSEL_HEADERS), 200
            )["status"]
            == "SUBMITTED"
        )
        after = world.production()
        assert_no_write(before, after)
        assert after["capital_raised_cents"] == 120_000_000
        assert after["escrow_balance_cents"] == 120_000_000
        assert after["active_investor_count"] == 2

        rows, meta = validate_paginated(
            api.list_investor_accounts(
                COMPTROLLER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert row["ownership_pct"] == 0.500000
