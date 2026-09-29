"""Demo slots at a store are an aggregate, buffered, half-open capacity."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    PromotionEventType,
    PromotionState,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)

BUFFER_MINUTES = 30
MAX_CONCURRENT_DEMOS = 2
STORE = "S001"
OTHER_STORE = "S002"
PLAN_INSTANT = "2026-09-03T00:00:00Z"
DEMO_DAY = "2026-09-05"


def demo_window(start_hhmm, end_hhmm):
    return (f"{DEMO_DAY}T{start_hhmm}:00Z", f"{DEMO_DAY}T{end_hhmm}:00Z")


@pytest.fixture
def four_planned_demos_at_one_store(api):
    """Four demo events at a chain that tolerates two concurrent demos with a 30 minute pad.

    Raw windows: 10:00-12:00, 11:00-13:00, 11:30-12:30 and 13:30-15:00.
    """
    scope = fixtures.awarded_authorization_without_deal(
        api,
        retailer_overrides={
            "demo_changeover_buffer_minutes": BUFFER_MINUTES,
            "max_concurrent_demos": MAX_CONCURRENT_DEMOS,
        },
        default_store_count=400,
    )
    fixtures.set_clock(api, PLAN_INSTANT)
    authorization_id = scope["authorization"]["id"]
    scope["demos"] = {
        label: fixtures.create_demo(
            api, authorization_id, *demo_window(start, end), store_code=STORE
        )
        for label, (start, end) in {
            "morning": ("10:00", "12:00"),
            "midday": ("11:00", "13:00"),
            "squeezed": ("11:30", "12:30"),
            "afternoon": ("13:30", "15:00"),
        }.items()
    }
    return scope


def commit(api, scope, label):
    return api.commit_promotion(scope["demos"][label]["id"], ACCOUNT_MANAGER_HEADERS)


def fill_the_two_slots(api, scope):
    get_success_data(commit(api, scope, "morning"), 200)
    get_success_data(commit(api, scope, "midday"), 200)


class TestBufferedDemoSlotCapacity:
    def test_two_overlapping_demos_are_legal_below_the_limit(
        self, api, four_planned_demos_at_one_store
    ):
        """Overlap alone is not a conflict; only the aggregate count matters.

        PRD: "And for `DEMO_SAMPLING` only, the store must have free demo capacity: counting the
        `DEMO_SAMPLING` events already `COMMITTED` or `EXECUTED` on the same chain and the same
        `store_code` whose windows — each expanded by the chain's
        `demo_changeover_buffer_minutes` at both ends — intersect the requested window, that
        count must be strictly fewer than the chain's `max_concurrent_demos`, otherwise
        `ERR_DEMO_SLOT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/buffered_demo_slot_capacity_is_aggregate_per_store_and_half_open
        """
        first = get_success_data(commit(api, four_planned_demos_at_one_store, "morning"), 200)
        second = get_success_data(commit(api, four_planned_demos_at_one_store, "midday"), 200)

        assert first["state"] == PromotionState.COMMITTED
        assert second["state"] == PromotionState.COMMITTED
        assert second["committed_at"] is not None

    def test_the_third_intersecting_demo_exhausts_the_capacity(
        self, api, four_planned_demos_at_one_store
    ):
        """Both buffered windows cover 11:30-12:30, so occupancy has reached the ceiling.

        PRD: "Committing an event with the retailer moves `state` from `PLANNED` to `COMMITTED`
        and imposes three conditions."

        Design: Difficulty/resource_temporal_overlap/buffered_demo_slot_capacity_is_aggregate_per_store_and_half_open
        """
        fill_the_two_slots(api, four_planned_demos_at_one_store)

        response = commit(api, four_planned_demos_at_one_store, "squeezed")
        validate_error(response, ApiErrorId.DEMO_SLOT_CAPACITY, 409)

        blocked = fixtures.get_promotion(
            api, four_planned_demos_at_one_store["demos"]["squeezed"]["id"]
        )
        assert blocked["state"] == PromotionState.PLANNED
        assert blocked["committed_at"] is None

    def test_a_window_touching_a_buffered_edge_exactly_still_commits(
        self, api, four_planned_demos_at_one_store
    ):
        """The midday demo's buffered window ends at 13:30 and the afternoon one starts there.

        PRD: "The buffered intervals are half-open, so two buffered windows that merely touch at
        an edge do not intersect."

        Design: Difficulty/resource_temporal_overlap/buffered_demo_slot_capacity_is_aggregate_per_store_and_half_open
        """
        fill_the_two_slots(api, four_planned_demos_at_one_store)

        committed = get_success_data(commit(api, four_planned_demos_at_one_store, "afternoon"), 200)
        assert committed["state"] == PromotionState.COMMITTED
        assert committed["committed_at"] is not None

    def test_only_the_committed_windows_carry_the_pad(
        self, api, four_planned_demos_at_one_store
    ):
        """The requested window is compared raw, so 13:30 is not pulled back to 13:00.

        PRD: "And for `DEMO_SAMPLING` only, the store must have free demo capacity: counting the
        `DEMO_SAMPLING` events already `COMMITTED` or `EXECUTED` on the same chain and the same
        `store_code` whose windows — each expanded by the chain's
        `demo_changeover_buffer_minutes` at both ends — intersect the requested window, that
        count must be strictly fewer than the chain's `max_concurrent_demos`, otherwise
        `ERR_DEMO_SLOT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/buffered_demo_slot_capacity_is_aggregate_per_store_and_half_open
        """
        fill_the_two_slots(api, four_planned_demos_at_one_store)
        validate_error(
            commit(api, four_planned_demos_at_one_store, "squeezed"),
            ApiErrorId.DEMO_SLOT_CAPACITY,
            409,
        )
        get_success_data(commit(api, four_planned_demos_at_one_store, "afternoon"), 200)

        response = api.list_promotions(
            ACCOUNT_MANAGER_HEADERS,
            {"store_code": STORE, "state": PromotionState.COMMITTED},
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 3
        assert {row["id"] for row in rows} == {
            four_planned_demos_at_one_store["demos"][label]["id"]
            for label in ("morning", "midday", "afternoon")
        }

    def test_the_capacity_is_scoped_to_one_store_of_the_chain(
        self, api, four_planned_demos_at_one_store
    ):
        """The identical window commits cleanly at a second store code.

        PRD: "A `DEMO_SAMPLING` event is the only type that occupies physical space in a store,
        so it *requires* a `store_code`, which must be omitted for the other two types, and it
        requires `sample_units_requested` of at least one sample case; for the other types
        `sample_units_requested` defaults to 0."

        Design: Difficulty/resource_temporal_overlap/buffered_demo_slot_capacity_is_aggregate_per_store_and_half_open
        """
        fill_the_two_slots(api, four_planned_demos_at_one_store)
        validate_error(
            commit(api, four_planned_demos_at_one_store, "squeezed"),
            ApiErrorId.DEMO_SLOT_CAPACITY,
            409,
        )

        elsewhere = fixtures.create_demo(
            api,
            four_planned_demos_at_one_store["authorization"]["id"],
            *demo_window("11:30", "12:30"),
            store_code=OTHER_STORE,
            sample_units_requested=200,
        )
        committed = get_success_data(
            api.commit_promotion(elsewhere["id"], ACCOUNT_MANAGER_HEADERS), 200
        )

        assert committed["state"] == PromotionState.COMMITTED
        assert committed["store_code"] == OTHER_STORE
        assert committed["event_type"] == PromotionEventType.DEMO_SAMPLING
