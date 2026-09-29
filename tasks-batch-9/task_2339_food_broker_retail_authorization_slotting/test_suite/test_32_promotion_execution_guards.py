"""Two independent guards on one transition: the window must have elapsed and the money must fit."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    PromotionEventType,
    PromotionState,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers import factories as F
from test_helpers.constants import FUNDING_TOLERANCE_BPS

PLANNED_FUNDING_CENTS = 320000
FUNDING_CEILING_CENTS = 352000
PAST_WINDOW_START = "2026-08-05T10:00:00Z"
PAST_WINDOW_END = "2026-08-05T14:00:00Z"
FUTURE_WINDOW_START = "2026-09-20T10:00:00Z"
FUTURE_WINDOW_END = "2026-09-20T14:00:00Z"


@pytest.fixture
def two_planned_events(api):
    """One event whose window has already passed and one still ahead of the clock."""
    scope = fixtures.awarded_authorization_without_deal(api, default_store_count=400)
    authorization_id = scope["authorization"]["id"]
    scope["stale"] = fixtures.create_promotion(
        api,
        authorization_id,
        event_type=PromotionEventType.PRICE_FEATURE,
        window_start=PAST_WINDOW_START,
        window_end=PAST_WINDOW_END,
        planned_funding_cents=PLANNED_FUNDING_CENTS,
    )
    scope["upcoming"] = fixtures.create_promotion(
        api,
        authorization_id,
        event_type=PromotionEventType.PRICE_FEATURE,
        window_start=FUTURE_WINDOW_START,
        window_end=FUTURE_WINDOW_END,
        planned_funding_cents=PLANNED_FUNDING_CENTS,
    )
    return scope


def execute(api, promotion_id, actual_funding_cents):
    return api.execute_promotion(
        promotion_id, F.execute_promotion_payload(actual_funding_cents), ACCOUNT_MANAGER_HEADERS
    )


def commit_the_upcoming_event(api, scope):
    return get_success_data(
        api.commit_promotion(scope["upcoming"]["id"], ACCOUNT_MANAGER_HEADERS), 200
    )


class TestPromotionExecutionGuards:
    def test_committing_an_event_whose_window_already_started_is_refused(
        self, api, two_planned_events
    ):
        """The 2026-08-05 window opened a month before the current clock.

        PRD: "The `window_start` must be at or after the current logical clock, otherwise
        `ERR_PROMO_WINDOW_IN_PAST`."

        Design: Corner/state_machines/promotion_execute_window_and_funding_tolerance_guards
        """
        response = api.commit_promotion(two_planned_events["stale"]["id"], ACCOUNT_MANAGER_HEADERS)

        validate_error(response, ApiErrorId.PROMO_WINDOW_IN_PAST, 422)
        stale = fixtures.get_promotion(api, two_planned_events["stale"]["id"])
        assert stale["state"] == PromotionState.PLANNED
        assert stale["committed_at"] is None

    def test_executing_before_the_window_closes_is_refused(self, api, two_planned_events):
        """The event is properly committed but has not happened yet.

        PRD: "Moving `state` from `COMMITTED` to `EXECUTED` requires the logical clock to have
        reached or passed `window_end`, otherwise `ERR_PROMO_NOT_ELAPSED`, and carries
        `actual_funding_cents` — the funding genuinely delivered."

        Design: Corner/state_machines/promotion_execute_window_and_funding_tolerance_guards
        """
        committed = commit_the_upcoming_event(api, two_planned_events)
        assert committed["state"] == PromotionState.COMMITTED

        validate_error(
            execute(api, two_planned_events["upcoming"]["id"], PLANNED_FUNDING_CENTS),
            ApiErrorId.PROMO_NOT_ELAPSED,
            422,
        )
        assert (
            fixtures.get_promotion(api, two_planned_events["upcoming"]["id"])["state"]
            == PromotionState.COMMITTED
        )

    def test_one_cent_above_the_tolerance_is_an_overrun(self, api, two_planned_events):
        """A hundred and ten percent of 320,000 is 352,000, so 352,001 is too much.

        PRD: "Overspend is tolerated only up to a tenth: `actual_funding_cents` may not exceed
        11,000 basis points of `planned_funding_cents`, that is one hundred and ten percent of
        plan, floored to whole cents; beyond that the request is `ERR_PROMO_FUNDING_OVERRUN`."

        Design: Corner/state_machines/promotion_execute_window_and_funding_tolerance_guards
        """
        assert (
            PLANNED_FUNDING_CENTS * FUNDING_TOLERANCE_BPS // 10000 == FUNDING_CEILING_CENTS
        )
        commit_the_upcoming_event(api, two_planned_events)
        fixtures.set_clock(api, FUTURE_WINDOW_END)

        validate_error(
            execute(api, two_planned_events["upcoming"]["id"], FUNDING_CEILING_CENTS + 1),
            ApiErrorId.PROMO_FUNDING_OVERRUN,
            409,
        )
        assert (
            fixtures.get_promotion(api, two_planned_events["upcoming"]["id"])["actual_funding_cents"]
            == 0
        )

    def test_exactly_the_ceiling_executes_at_exactly_the_window_end(
        self, api, two_planned_events
    ):
        """Both boundaries are inclusive, and the proven funding figure is persisted.

        PRD: "Once persisted, `actual_funding_cents` becomes the proven funding figure that a
        promotional billback deduction is netted against."

        Design: Corner/state_machines/promotion_execute_window_and_funding_tolerance_guards
        """
        commit_the_upcoming_event(api, two_planned_events)
        fixtures.set_clock(api, FUTURE_WINDOW_END)

        executed = get_success_data(
            execute(api, two_planned_events["upcoming"]["id"], FUNDING_CEILING_CENTS), 200
        )

        assert executed["state"] == PromotionState.EXECUTED
        assert executed["actual_funding_cents"] == FUNDING_CEILING_CENTS
        assert executed["settled_funding_cents"] == 0

    def test_the_owning_authorization_has_settled_nothing_yet(self, api, two_planned_events):
        """Execution proves the spend but settles none of it.

        PRD: "It is driven by deduction settlement (§3.9): once the event's
        `settled_funding_cents` reaches or exceeds its `actual_funding_cents`, the event settles,
        and the cascade recomputes the owning authorization's `promo_settled_funding_cents` — the
        sum of `actual_funding_cents` over that authorization's `SETTLED` events — and with it
        `trade_spend_total_cents`."

        Design: Corner/state_machines/promotion_execute_window_and_funding_tolerance_guards
        """
        commit_the_upcoming_event(api, two_planned_events)
        fixtures.set_clock(api, FUTURE_WINDOW_END)
        get_success_data(execute(api, two_planned_events["upcoming"]["id"], FUNDING_CEILING_CENTS), 200)

        authorization = fixtures.get_authorization(api, two_planned_events["authorization"]["id"])
        assert authorization["promo_settled_funding_cents"] == 0
