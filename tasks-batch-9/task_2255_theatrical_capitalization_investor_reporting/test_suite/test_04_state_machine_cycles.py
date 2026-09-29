"""
The three state paths in this system that are cycles rather than one-way ladders.

Each one is walked round trip, because an implementation that models any of them
as a linear ladder passes the forward hop and fails the return.
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
    GM_HEADERS,
    ApiClient,
    ApiErrorId,
    World,
    factories,
    fixtures,
    make_investor_headers,
)


def _half_unit_offering(
    api: ApiClient, investor_count: int
) -> Tuple[World, List[str], List[str]]:
    """An offering of 120,000,000 in 60,000,000 units, with submitted subscriptions."""
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
    for index in range(investor_count):
        investor_id = fixtures.new_accredited_investor(
            world,
            legal_name=f"Investor {index + 1}",
            contact_email=f"investor{index + 1}@example.com",
        )
        investor_ids.append(investor_id)
        subscription_ids.append(fixtures.new_subscription(world, investor_id, units=1))
    return world, investor_ids, subscription_ids


class TestOfferingAxisRoundTrip:
    """FULLY_SUBSCRIBED is not terminal: a rescission drops the axis back."""

    def test_rescission_regresses_the_axis_and_a_replacement_refills_it(
        self, api: ApiClient
    ):
        """Two accepts fill the offering, a rescind empties a unit, a third accept refills.

        "On the syndication axis, `OFFERING → FULLY_SUBSCRIBED → OFFERING` is a
        legitimate round trip driven entirely by subscription arithmetic."

        Design: Difficulty/non_linear_state_machine/production_parallel_axes_with_offering_status_regression_cycle
        """
        world, investor_ids, subscription_ids = _half_unit_offering(api, 3)

        fixtures.accept_subscription(world, subscription_ids[0])
        fixtures.accept_subscription(world, subscription_ids[1])
        filled = world.production()
        assert filled["offering_status"] == "FULLY_SUBSCRIBED"
        assert filled["capital_raised_cents"] == 120_000_000

        get_success_data(
            api.rescind_subscription(
                subscription_ids[0], factories.rescission_payload(), COUNSEL_HEADERS
            ),
            200,
        )
        regressed = world.production()
        assert regressed["offering_status"] == "OFFERING"
        assert regressed["capital_raised_cents"] == 60_000_000

        fixtures.accept_subscription(world, subscription_ids[2])
        refilled = world.production()
        assert refilled["offering_status"] == "FULLY_SUBSCRIBED"
        assert refilled["capital_raised_cents"] == 120_000_000
        assert refilled["escrow_balance_cents"] == 120_000_000
        assert refilled["active_investor_count"] == 2

        rows, _ = validate_paginated(
            api.list_subscriptions(
                COUNSEL_HEADERS, {"offering_document_id": world.offering_document_id}
            )
        )
        by_id = {row["id"]: row for row in rows}
        assert by_id[subscription_ids[0]]["status"] == "RESCINDED"
        assert by_id[subscription_ids[1]]["status"] == "ACCEPTED"
        assert by_id[subscription_ids[2]]["status"] == "ACCEPTED"
        assert by_id[subscription_ids[0]]["investor_id"] == investor_ids[0]
        assert by_id[subscription_ids[2]]["investor_id"] == investor_ids[2]

    def test_the_calendar_axis_never_moves_while_the_offering_axis_cycles(
        self, api: ApiClient
    ):
        """Filling, emptying and refilling the offering leaves PRE_PRODUCTION alone.

        "A transition on one axis is never a transition on the other, and each
        axis reports its own rejection code: an inadmissible move on the
        syndication axis is `ERR_INVALID_OFFERING_STATE` (HTTP 409), and an
        inadmissible move on the calendar axis is
        `ERR_INVALID_OPERATING_STATE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/production_parallel_axes_with_offering_status_regression_cycle
        """
        world, _, subscription_ids = _half_unit_offering(api, 3)

        for step in (0, 1):
            fixtures.accept_subscription(world, subscription_ids[step])
            snapshot = world.production()
            assert snapshot["operating_status"] == "PRE_PRODUCTION"
            assert snapshot["recoupment_status"] == "UNRECOUPED"

        get_success_data(
            api.rescind_subscription(
                subscription_ids[0], factories.rescission_payload(), COUNSEL_HEADERS
            ),
            200,
        )
        after_rescind = world.production()
        assert after_rescind["operating_status"] == "PRE_PRODUCTION"
        assert after_rescind["recoupment_status"] == "UNRECOUPED"

        fixtures.accept_subscription(world, subscription_ids[2])
        final = world.production()
        assert final["operating_status"] == "PRE_PRODUCTION"
        assert final["recoupment_status"] == "UNRECOUPED"
        assert final["offering_status"] == "FULLY_SUBSCRIBED"


class TestCureCycleExhaustion:
    """Two cure rounds are allowed; the third return rejects the subscription."""

    def test_the_first_two_returns_land_in_returned_for_cure(self, api: ApiClient):
        """Rounds one and two send the subscription back and count up.

        "Two cure rounds are the limit. If the incremented count is at most 2,
        the subscription becomes `RETURNED_FOR_CURE` and the investor gets
        another chance; if the increment would carry the count past 2 — that is,
        on the third return — the subscription is instead driven straight to the
        terminal `REJECTED` state."

        Design: Difficulty/non_linear_state_machine/subscription_cure_cycle_exhaustion_branches_to_rejected
        """
        world, investor_ids, subscription_ids = _half_unit_offering(api, 1)
        subscription_id = subscription_ids[0]
        investor_headers = make_investor_headers(investor_ids[0])

        first_return = get_success_data(
            api.return_subscription_for_cure(
                subscription_id, factories.cure_payload(), COUNSEL_HEADERS
            ),
            200,
        )
        assert first_return["status"] == "RETURNED_FOR_CURE"
        assert first_return["cure_round_count"] == 1
        assert first_return["defect_note"]

        first_resubmit = get_success_data(
            api.resubmit_subscription(
                subscription_id, factories.resubmit_payload(1), investor_headers
            ),
            200,
        )
        assert first_resubmit["status"] == "SUBMITTED"
        assert first_resubmit["cure_round_count"] == 1

        second_return = get_success_data(
            api.return_subscription_for_cure(
                subscription_id, factories.cure_payload("Wire never received"),
                COUNSEL_HEADERS,
            ),
            200,
        )
        assert second_return["status"] == "RETURNED_FOR_CURE"
        assert second_return["cure_round_count"] == 2

    def test_the_third_return_rejects_terminally_and_blocks_resubmission(
        self, api: ApiClient
    ):
        """REJECTED is terminal, so the investor cannot restart the cycle.

        "Because a return can happen at most twice before the subscription is
        rejected, the `SUBMITTED → RETURNED_FOR_CURE → SUBMITTED` cycle can turn
        at most twice."

        Design: Difficulty/non_linear_state_machine/subscription_cure_cycle_exhaustion_branches_to_rejected
        """
        world, investor_ids, subscription_ids = _half_unit_offering(api, 1)
        subscription_id = subscription_ids[0]
        investor_headers = make_investor_headers(investor_ids[0])

        for note in ("Signature block unexecuted", "Wire never received"):
            get_success_data(
                api.return_subscription_for_cure(
                    subscription_id, factories.cure_payload(note), COUNSEL_HEADERS
                ),
                200,
            )
            get_success_data(
                api.resubmit_subscription(
                    subscription_id, factories.resubmit_payload(1), investor_headers
                ),
                200,
            )

        third_return = get_success_data(
            api.return_subscription_for_cure(
                subscription_id,
                factories.cure_payload("Questionnaire page 3 still missing"),
                COUNSEL_HEADERS,
            ),
            200,
        )
        assert third_return["status"] == "REJECTED"
        assert (
            get_success_data(api.get_subscription(subscription_id, COUNSEL_HEADERS), 200)[
                "status"
            ]
            == "REJECTED"
        )

        refused = api.resubmit_subscription(
            subscription_id, factories.resubmit_payload(1), investor_headers
        )
        validate_error(refused, ApiErrorId.INVALID_SUBSCRIPTION_STATE)

        production = world.production()
        assert production["offering_status"] == "OFFERING"
        assert production["capital_raised_cents"] == 0
        assert production["escrow_balance_cents"] == 0
        _, meta = validate_paginated(
            api.list_investor_accounts(
                COUNSEL_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 0


class TestWrapDisputeAmendThenVoid:
    """The wrap reaches CERTIFIED through a cycle, and CERTIFIED still has an exit."""

    def _disputed_then_amended_wrap(self, api: ApiClient) -> Tuple[World, str]:
        world = fixtures.ledger_world(api, pool_basis=True)
        world.set_clock("2026-09-07")
        wrap_id = fixtures.new_wrap(
            world, gross_receipts_cents=40_000_000, paid_attendance=5_000
        )
        fixtures.submit_wrap(world, wrap_id)

        disputed = get_success_data(
            api.dispute_weekly_wrap(
                wrap_id, factories.dispute_payload(), COMPTROLLER_HEADERS
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"

        amended = get_success_data(
            api.amend_weekly_wrap(
                wrap_id,
                factories.amend_payload(
                    performances=8,
                    gross_receipts_cents=65_000_000,
                    paid_attendance=8_200,
                    running_expenses_cents=33_500_000,
                ),
                GM_HEADERS,
            ),
            200,
        )
        assert amended["status"] == "AMENDED"
        assert amended["gross_receipts_cents"] == 65_000_000
        return world, wrap_id

    def test_certification_settles_the_amended_figures_only(self, api: ApiClient):
        """The corrected week settles at 18,362,500, never at the pre-amendment figure.

        "A `DISPUTED` wrap goes back to the `GeneralManager` for amendment,
        which is where the `SUBMITTED → DISPUTED → AMENDED → SUBMITTED` cycle
        turns."

        Design: Difficulty/non_linear_state_machine/wrap_dispute_amend_cycle_then_certified_to_void_compensation
        """
        world, wrap_id = self._disputed_then_amended_wrap(api)

        fixtures.submit_wrap(world, wrap_id)
        certified = fixtures.certify_wrap(world, wrap_id)

        assert certified["status"] == "CERTIFIED"
        assert certified["royalty_base_cents"] == 28_250_000
        assert certified["royalty_pool_cents"] == 9_887_500
        assert certified["weekly_operating_profit_cents"] == 18_362_500

        production = world.production()
        assert production["recouped_amount_cents"] == 18_362_500
        assert production["recoupment_pct"] == 0.1530

    def test_voiding_a_certified_wrap_unwinds_the_whole_settlement(
        self, api: ApiClient
    ):
        """VOID reverses the allocations and takes the week back out of the ledger.

        "Certify-then-void conserves the production's `recouped_amount_cents`
        exactly."

        Design: Difficulty/non_linear_state_machine/wrap_dispute_amend_cycle_then_certified_to_void_compensation
        """
        world, wrap_id = self._disputed_then_amended_wrap(api)
        fixtures.submit_wrap(world, wrap_id)
        fixtures.certify_wrap(world, wrap_id)

        voided = get_success_data(
            api.void_weekly_wrap(wrap_id, factories.void_payload(), COMPTROLLER_HEADERS),
            200,
        )
        assert voided["status"] == "VOID"
        assert (
            get_success_data(api.get_weekly_wrap(wrap_id, COMPTROLLER_HEADERS), 200)[
                "status"
            ]
            == "VOID"
        )

        production = world.production()
        assert production["recouped_amount_cents"] == 0
        assert production["recoupment_pct"] == 0.0000
        assert production["recoupment_status"] == "UNRECOUPED"

        rows, meta = validate_paginated(
            api.list_royalty_allocations(COMPTROLLER_HEADERS, {"wrap_id": wrap_id})
        )
        assert meta["total_count"] == 3
        assert [row["status"] for row in rows] == ["REVERSED"] * 3
