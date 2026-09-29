"""
Writes refused because of the state of a row other than the one being written.

The target row is perfectly admissible in each case; it is a document, a budget
or a sibling wrap elsewhere in the production that closes the gate.
"""

from typing import Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    GM_HEADERS,
    PRODUCER_HEADERS,
    ApiClient,
    ApiErrorId,
    World,
    assert_no_write,
    factories,
    fixtures,
)


def _submitted_subscription_world(api: ApiClient, **doc_overrides) -> Tuple[World, str]:
    """An offering with one accredited investor's unit sitting in SUBMITTED."""
    world = fixtures.base_world(api)
    fixtures.open_offering(world)
    fixtures.with_effective_document(world, **doc_overrides)
    investor_id = fixtures.new_accredited_investor(world)
    world.investor_id = investor_id
    subscription_id = fixtures.new_subscription(world, investor_id, units=1)
    world.subscription_id = subscription_id
    return world, subscription_id


def _committed_reserve_line(world: World, amount_cents: int) -> str:
    """Plan a RESERVE line, approve the budget, and commit the line."""
    fixtures.with_reserve_line(world, amount_cents)
    line_id = world.reserve_line_id or ""
    get_success_data(
        world.client.approve_budget(world.production_id, PRODUCER_HEADERS), 200
    )
    get_success_data(world.client.commit_budget_line(line_id, GM_HEADERS), 200)
    return line_id


class TestWithdrawnDocumentBlocksAcceptance:
    """A withdrawn instrument is a generic not-effective gate."""

    def _withdrawn_document_world(self, api: ApiClient) -> Tuple[World, str]:
        world, subscription_id = _submitted_subscription_world(
            api, unit_price_cents=60_000_000
        )
        withdrawn = get_success_data(
            api.withdraw_offering_document(
                world.offering_document_id or "",
                factories.withdrawal_payload(
                    "Blue-sky filing deficiency in two states"
                ),
                COUNSEL_HEADERS,
            ),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason"] == (
            "Blue-sky filing deficiency in two states"
        )
        return world, subscription_id

    def test_acceptance_under_a_withdrawn_instrument_is_refused(self, api: ApiClient):
        """The subscription is still SUBMITTED, but its instrument is gone.

        "**Cross-entity state gates.** The related rows are in the states the
        operation requires, else one of `ERR_OFFERING_NOT_EFFECTIVE`,
        `ERR_PRODUCTION_NOT_PERFORMING`, `ERR_PRODUCTION_NOT_OFFERING`,
        `ERR_PRODUCTION_NOT_CAPITALIZED`, `ERR_UNCERTIFIED_WRAPS_EXIST`,
        `ERR_OPERATING_BUDGET_CHANGED`, or `ERR_ACTIVE_OPERATING_BUDGET_MISSING`
        (all 409)."

        Design: Difficulty/cross_entity_state_dependency/withdrawn_offering_document_blocks_subscription_acceptance
        """
        world, subscription_id = self._withdrawn_document_world(api)

        refused = api.accept_subscription(subscription_id, COUNSEL_HEADERS)
        validate_error(refused, ApiErrorId.OFFERING_NOT_EFFECTIVE)
        assert world.production()["offering_status"] == "OFFERING"

    def test_the_refused_acceptance_opens_no_capital_account(self, api: ApiClient):
        """Nothing was raised, so no account exists to prorate.

        "Withdrawal is available from either `DRAFT` or `EFFECTIVE`, takes a
        `withdrawal_reason` which is recorded on the document, and lands the
        document in the terminal `WITHDRAWN` state; the field reads null on any
        document that has not been withdrawn."

        Design: Difficulty/cross_entity_state_dependency/withdrawn_offering_document_blocks_subscription_acceptance
        """
        world, subscription_id = self._withdrawn_document_world(api)
        before = world.production()

        validate_error(
            api.accept_subscription(subscription_id, COUNSEL_HEADERS),
            ApiErrorId.OFFERING_NOT_EFFECTIVE,
        )

        assert (
            get_success_data(api.get_subscription(subscription_id, COUNSEL_HEADERS), 200)[
                "status"
            ]
            == "SUBMITTED"
        )
        after = world.production()
        assert_no_write(before, after)
        assert after["capital_raised_cents"] == 0
        _, meta = validate_paginated(
            api.list_investor_accounts(
                COMPTROLLER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 0


class TestLapsedDocumentBlocksAcceptanceSpecifically:
    """An expired instrument reports the specific temporal code, not the generic one."""

    def _lapsed_document_world(self, api: ApiClient) -> Tuple[World, str, int]:
        world, subscription_id = _submitted_subscription_world(
            api,
            unit_price_cents=60_000_000,
            effective_date="2026-08-01",
            expiration_date="2026-08-31",
        )
        document_id = world.offering_document_id or ""
        # Still inside the inclusive window, with a day to spare.
        world.set_clock("2026-08-15")
        effective = get_success_data(
            api.get_offering_document(document_id, COUNSEL_HEADERS), 200
        )
        assert effective["status"] == "EFFECTIVE"
        world.set_clock("2026-09-01")
        return world, subscription_id, int(effective["version"])

    def test_reading_the_document_after_its_window_lapses_expires_it(
        self, api: ApiClient
    ):
        """Nobody withdrew it; the read itself moved it to EXPIRED.

        "Whenever a request reads or writes an offering document, the system
        first checks whether that document is `EFFECTIVE` and whether the current
        logical UTC date has passed its `expiration_date`; if so, the document
        transitions `EFFECTIVE → EXPIRED` and its `version` advances before the
        request's own validations run."

        Design: Difficulty/cross_entity_state_dependency/lazily_expired_offering_document_blocks_acceptance_with_specific_error
        """
        world, _, effective_version = self._lapsed_document_world(api)

        lapsed = get_success_data(
            api.get_offering_document(world.offering_document_id or "", COUNSEL_HEADERS),
            200,
        )
        assert lapsed["status"] == "EXPIRED"
        assert lapsed["withdrawal_reason"] is None
        assert int(lapsed["version"]) > effective_version

    def test_acceptance_against_the_lapsed_instrument_reports_the_expiry(
        self, api: ApiClient
    ):
        """The generic not-effective code would be wrong here.

        "First, the cross-entity gate at step 9 treats a `DRAFT` or `WITHDRAWN`
        offering document as `ERR_OFFERING_NOT_EFFECTIVE` (409), but it
        deliberately does **not** catch an `EXPIRED` document: the lapsed-window
        case is deferred to the temporal rules at step 12 so that it reports the
        more specific `ERR_OFFERING_EXPIRED` (422)."

        Design: Difficulty/cross_entity_state_dependency/lazily_expired_offering_document_blocks_acceptance_with_specific_error
        """
        world, subscription_id, _ = self._lapsed_document_world(api)

        refused = api.accept_subscription(subscription_id, COUNSEL_HEADERS)
        validate_error(refused, ApiErrorId.OFFERING_EXPIRED)

        assert (
            get_success_data(api.get_subscription(subscription_id, COUNSEL_HEADERS), 200)[
                "status"
            ]
            == "SUBMITTED"
        )
        production = world.production()
        assert production["offering_status"] == "OFFERING"
        assert production["capital_raised_cents"] == 0
        assert production["escrow_balance_cents"] == 0


class TestSupersededBudgetBlocksCertification:
    """A wrap pins its budget, and superseding that budget invalidates the wrap."""

    def _superseded_budget_world(self, api: ApiClient) -> Tuple[World, str, str, str]:
        world = fixtures.ledger_world(api, pool_basis=True)
        first_budget_id = world.operating_budget_id or ""
        fixtures.with_submitted_standard_week(world)
        wrap_id = world.wrap_id or ""

        fixtures.with_active_operating_budget(
            world, weekly_fixed_running_cost_cents=40_000_000
        )
        second_budget_id = world.operating_budget_id or ""
        assert second_budget_id != first_budget_id
        return world, wrap_id, first_budget_id, second_budget_id

    def test_certification_is_refused_once_the_pinned_budget_is_superseded(
        self, api: ApiClient
    ):
        """The wrap pinned a budget version that no longer stands.

        "And the pinned budget must be unchanged: the current `version` of the
        operating budget identified by `operating_budget_id` must still equal the
        wrap's `operating_budget_version_pinned`."

        Design: Difficulty/cross_entity_state_dependency/superseded_pinned_operating_budget_blocks_wrap_certification
        """
        world, wrap_id, first_budget_id, second_budget_id = (
            self._superseded_budget_world(api)
        )

        refused = api.certify_weekly_wrap(wrap_id, COMPTROLLER_HEADERS)
        validate_error(refused, ApiErrorId.OPERATING_BUDGET_CHANGED)

        assert (
            get_success_data(api.get_operating_budget(first_budget_id, GM_HEADERS), 200)[
                "status"
            ]
            == "SUPERSEDED"
        )
        assert (
            get_success_data(api.get_operating_budget(second_budget_id, GM_HEADERS), 200)[
                "status"
            ]
            == "ACTIVE"
        )
        assert (
            get_success_data(api.get_weekly_wrap(wrap_id, GM_HEADERS), 200)["status"]
            == "SUBMITTED"
        )
        assert world.production()["recouped_amount_cents"] == 0

    def test_the_refused_certification_settles_nothing(self, api: ApiClient):
        """The wrap keeps its old pin, and no royalty allocation was written.

        "If a newer budget has superseded it in the meantime — bumping the old
        row's `version` — the certification is refused with
        `ERR_OPERATING_BUDGET_CHANGED` (HTTP 409), and the wrap must be disputed
        and amended so that it re-pins to the budget now in force."

        Design: Difficulty/cross_entity_state_dependency/superseded_pinned_operating_budget_blocks_wrap_certification
        """
        world, wrap_id, first_budget_id, _ = self._superseded_budget_world(api)
        before = get_success_data(api.get_weekly_wrap(wrap_id, GM_HEADERS), 200)

        validate_error(
            api.certify_weekly_wrap(wrap_id, COMPTROLLER_HEADERS),
            ApiErrorId.OPERATING_BUDGET_CHANGED,
        )

        after = get_success_data(api.get_weekly_wrap(wrap_id, GM_HEADERS), 200)
        assert_no_write(before, after)
        assert after["status"] == "SUBMITTED"
        assert after["operating_budget_id"] == first_budget_id

        production = world.production()
        assert production["recouped_amount_cents"] == 0
        assert production["recoupment_status"] == "UNRECOUPED"
        _, meta = validate_paginated(
            api.list_royalty_allocations(COMPTROLLER_HEADERS, {"wrap_id": wrap_id})
        )
        assert meta["total_count"] == 0


class TestUncertifiedWrapBlocksSettlement:
    """The books close before the show does."""

    def _notice_with_an_open_week(self, api: ApiClient) -> Tuple[World, str, str]:
        world = fixtures.ledger_world(
            api,
            capitalization_target_cents=20_000_000,
            unit_price_cents=20_000_000,
            pool_basis=True,
        )
        line_id = _committed_reserve_line(world, 2_000_000)

        fixtures.with_submitted_standard_week(world)
        fixtures.certify_wrap(world, world.wrap_id or "")

        world.set_clock("2026-09-14")
        open_wrap_id = fixtures.new_wrap(
            world,
            week_ending_date="2026-09-13",
            gross_receipts_cents=20_000_000,
            paid_attendance=2_600,
        )
        fixtures.submit_wrap(world, open_wrap_id)

        fixtures.with_issued_closing_notice(
            world, notice_date="2026-09-14", final_performance_date="2026-09-28"
        )
        return world, open_wrap_id, line_id

    def test_settlement_is_refused_while_a_week_is_still_open(self, api: ApiClient):
        """A single SUBMITTED wrap is enough to hold the settlement back.

        "It carries four preconditions: the notice must be `ISSUED`, else
        `ERR_INVALID_CLOSING_NOTICE_STATE` (HTTP 409); the production's
        `operating_status` must read `CLOSING_NOTICE`; the settling operator's
        `X-User-ID` must differ from the notice's `issued_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); and no wrap of the production may
        still be in `DRAFT`, `SUBMITTED`, `DISPUTED`, or `AMENDED`, else
        `ERR_UNCERTIFIED_WRAPS_EXIST` (HTTP 409) — the books must be closed
        before the show is."

        Design: Difficulty/cross_entity_state_dependency/uncertified_wrap_blocks_closing_settlement_until_certified
        """
        world, _, line_id = self._notice_with_an_open_week(api)

        refused = fixtures.settle_closing_notice(world, closing_costs_cents=300_000)
        validate_error(refused, ApiErrorId.UNCERTIFIED_WRAPS_EXIST)

        assert (
            get_success_data(
                api.get_closing_notice(world.closing_notice_id or "", PRODUCER_HEADERS),
                200,
            )["status"]
            == "ISSUED"
        )
        assert (
            get_success_data(api.get_budget_line(line_id, GM_HEADERS), 200)[
                "commitment_status"
            ]
            == "COMMITTED"
        )
        assert world.production()["operating_status"] == "CLOSING_NOTICE"

    def test_certifying_the_open_week_lets_the_settlement_through(
        self, api: ApiClient
    ):
        """The losing week certifies to zero, and the retried settlement closes the show.

        "`reserve_balance_at_settlement_cents` is the sum of `amount_cents` over
        the production's budget lines whose `component` is `RESERVE` and whose
        `commitment_status` is `COMMITTED` at the settlement instant — these are
        exactly the lines the notice's posting moved from `PLANNED`, so `PLANNED`
        and `SPENT` lines are outside the scope."

        Design: Difficulty/cross_entity_state_dependency/uncertified_wrap_blocks_closing_settlement_until_certified
        """
        world, open_wrap_id, line_id = self._notice_with_an_open_week(api)
        validate_error(
            fixtures.settle_closing_notice(world, closing_costs_cents=300_000),
            ApiErrorId.UNCERTIFIED_WRAPS_EXIST,
        )

        certified = fixtures.certify_wrap(world, open_wrap_id)
        assert certified["royalty_base_cents"] == 0
        assert certified["royalty_pool_cents"] == 0
        assert certified["weekly_operating_profit_cents"] == 0
        assert certified["deferred_royalty_added_cents"] == 800_000

        settled = get_success_data(
            fixtures.settle_closing_notice(world, closing_costs_cents=300_000), 200
        )
        assert settled["status"] == "SETTLED"
        assert settled["reserve_released_cents"] == 1_700_000
        assert settled["closing_cost_shortfall_cents"] == 0

        production = world.production()
        assert production["operating_status"] == "CLOSED"
        assert production["recouped_amount_cents"] == 20_062_500
        assert production["recoupment_pct"] == 1.0031
        assert production["recoupment_status"] == "RECOUPED"
        assert production["deferred_royalty_cents"] == 800_000
        assert (
            get_success_data(api.get_budget_line(line_id, GM_HEADERS), 200)[
                "commitment_status"
            ]
            == "SPENT"
        )
