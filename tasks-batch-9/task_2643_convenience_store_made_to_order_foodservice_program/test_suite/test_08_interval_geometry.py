"""Two opposite interval geometries, probed where they touch.

Oven slots are exclusive with a sanitation buffer folded into the right bound;
pickup windows are a half-open concurrency count against a capacity. Both
rules use strict comparisons, so intervals that merely touch are legal - and
each test sits one minute either side of that touch point.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

CLOCK_EARLY = "2026-08-01T06:00:00Z"
CLOCK_LUNCH = "2026-08-01T11:00:00Z"

A_BAKE_START = "2026-08-01T06:00:00Z"
A_OCCUPANCY_END = "2026-08-01T10:40:00Z"
ONE_MINUTE_BEFORE_FREE = "2026-08-01T10:39:00Z"
EXACTLY_WHEN_FREE = "2026-08-01T10:40:00Z"
C_OCCUPANCY_END = "2026-08-01T15:20:00Z"

W1 = ("2026-08-01T13:00:00Z", "2026-08-01T13:30:00Z")
W2 = ("2026-08-01T13:15:00Z", "2026-08-01T13:45:00Z")
W3 = ("2026-08-01T13:29:00Z", "2026-08-01T13:59:00Z")
W4 = ("2026-08-01T13:30:00Z", "2026-08-01T14:00:00Z")


def _slot_one_booked_until_ten_forty(api):
    """A pan planned at 06:00 owning slot 1 of a two-slot case until 10:40."""
    X.set_clock(api, CLOCK_EARLY)
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"], slot_count=2)
    pretzel = X.create_pretzel(api)
    batch_a = X.create_planned_batch(
        api,
        store["id"],
        pretzel["id"],
        unit["id"],
        slot_index=1,
        planned_qty=40,
        bake_start_at=A_BAKE_START,
    )
    return store, unit, pretzel, batch_a


def _plan_slot_one_at(api, store, pretzel, unit, bake_start_at):
    return api.create_production_batch(
        F.production_batch_payload(
            store["id"],
            pretzel["id"],
            unit["id"],
            slot_index=1,
            planned_qty=24,
            bake_start_at=bake_start_at,
        ),
        H.KITCHEN_ASSOCIATE_HEADERS,
    )


def _two_concurrent_windows_already_placed(api):
    """A capacity-2 store with 13:00-13:30 and 13:15-13:45 both committed."""
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH, pickup_slot_capacity=2)
    hoagie = X.create_hoagie(api)

    def preorder(window):
        order = X.create_draft_preorder(api, store["id"], window[0], window[1])
        X.add_order_line(api, order["id"], hoagie["id"], 1)
        return order

    first = X.place_order(api, preorder(W1)["id"])
    second = X.place_order(api, preorder(W2)["id"])
    assert first["production_status"] == "PLACED"
    assert second["production_status"] == "PLACED"
    return store, hoagie, first, second, preorder


def test_a_start_one_minute_inside_the_sanitation_buffer_is_refused(api):
    """The buffer lives inside the occupancy end bound, not beside it.

    Occupancy runs to "the computed `occupancy_end_at`, which is the
    `bake_start_at` advanced by the item's `bake_minutes`, then by the item's
    `hold_minutes`, and then by a mandatory sanitation window of 15 minutes" -
    25 + 240 + 15 from 06:00 is 10:40. A start at 10:39 satisfies both strict
    comparisons of the conflict rule, so "A new batch is refused with
    `ERR_UNIT_SLOT_CONFLICT` (HTTP 409) when some other batch on the *same*
    holding unit and the *same* slot index, whose status is `PLANNED`, `BAKING`
    or `HOLDING`" overlaps it.

    Design: Difficulty/resource_temporal_overlap/sanitation_buffered_slot_interval_touches_legally_at_ten_forty
    """
    store, unit, pretzel, batch_a = _slot_one_booked_until_ten_forty(api)
    assert batch_a["occupancy_end_at"] == A_OCCUPANCY_END

    response = _plan_slot_one_at(api, store, pretzel, unit, ONE_MINUTE_BEFORE_FREE)

    H.validate_error(response, H.ApiErrorId.ERR_UNIT_SLOT_CONFLICT.value, 409)
    assert X.read_batch(api, batch_a["id"])["status"] == "PLANNED"


def test_a_start_exactly_at_the_occupancy_end_is_accepted(api):
    """Touching intervals share the slot legally.

    "Because both comparisons are strict, intervals that merely touch are
    legal: a new batch whose `bake_start_at` equals an existing batch's
    `occupancy_end_at` is accepted, while a start one minute earlier is
    refused." The accepted pan books the same slot for the next 280 minutes and
    opens cold, since "A newly planned batch opens in `PLANNED` with every
    quantity counter at 0", so no oven slot is occupied at the store level yet.

    Design: Difficulty/resource_temporal_overlap/sanitation_buffered_slot_interval_touches_legally_at_ten_forty
    """
    store, unit, pretzel, batch_a = _slot_one_booked_until_ten_forty(api)

    response = _plan_slot_one_at(api, store, pretzel, unit, EXACTLY_WHEN_FREE)

    batch_c = H.get_success_data(response, 201)
    assert batch_c["status"] == "PLANNED"
    assert batch_c["slot_index"] == 1
    assert batch_c["occupancy_end_at"] == C_OCCUPANCY_END
    assert X.read_batch(api, batch_a["id"])["slot_index"] == 1
    assert X.read_store(api, store["id"])["hot_case_slots_used"] == 0


def test_both_touching_pans_are_listed_against_the_same_holding_unit(api):
    """The unit ends up holding two bookings on one slot, back to back.

    The refused 10:39 attempt wrote nothing, and the accepted 10:40 attempt is
    a second row on the same slot, so the unit's batch list carries exactly the
    two pans. Batches are readable this way because "Batches may be read
    individually with their full quantity ledger, hold clock and `version`, and
    listed with filters on `store_id`, `menu_item_id`, `holding_unit_id` and
    `status`."

    Design: Difficulty/resource_temporal_overlap/sanitation_buffered_slot_interval_touches_legally_at_ten_forty
    """
    store, unit, pretzel, batch_a = _slot_one_booked_until_ten_forty(api)
    refused = _plan_slot_one_at(api, store, pretzel, unit, ONE_MINUTE_BEFORE_FREE)
    H.validate_error(refused, H.ApiErrorId.ERR_UNIT_SLOT_CONFLICT.value, 409)
    accepted = H.get_success_data(
        _plan_slot_one_at(api, store, pretzel, unit, EXACTLY_WHEN_FREE), 201
    )

    response = api.list_production_batches(
        H.KITCHEN_ASSOCIATE_HEADERS, {"holding_unit_id": unit["id"]}
    )

    rows, meta = H.validate_paginated(response)
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {batch_a["id"], accepted["id"]}


def test_a_third_window_overlapping_both_committed_windows_is_refused(api):
    """Two concurrent windows exhaust a capacity of two.

    The count is over "the *other* orders of the same store, excluding this
    one, whose `channel` is `MOBILE_PREORDER` or `CATERING` and whose
    `production_status` is one of `PLACED`, `IN_PRODUCTION`, `ASSEMBLED` or
    `READY`", and 13:29-13:59 overlaps both committed windows. "If that count
    is already at or above the store's `pickup_slot_capacity`, the commit is
    refused with `ERR_PICKUP_WINDOW_FULL` (HTTP 409)". The refusal leaves the
    order in `DRAFT` with nothing snapshotted.

    Design: Difficulty/resource_temporal_overlap/half_open_pickup_capacity_counts_concurrent_windows_not_exclusive_slots
    """
    store, hoagie, first, second, preorder = _two_concurrent_windows_already_placed(api)
    third = preorder(W3)

    response = api.place_order(third["id"], {}, H.STORE_TERMINAL_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_PICKUP_WINDOW_FULL.value, 409)
    refused = X.read_order(api, third["id"])
    assert refused["production_status"] == "DRAFT"
    assert refused["daypart_at_placement"] is None


def test_a_window_that_merely_touches_an_earlier_one_still_commits(api):
    """Touching windows do not overlap, so capacity is not reached.

    A 13:30-14:00 window starts exactly as the first one ends: "windows that
    merely touch, where one ends exactly as the other starts, do not overlap".
    Only the 13:15-13:45 order therefore counts against it, and "the commit
    proceeds only when the count is strictly below the capacity". The order the
    system refused a moment ago is not counted either, because "Draft,
    picked-up and voided orders are excluded".

    Design: Difficulty/resource_temporal_overlap/half_open_pickup_capacity_counts_concurrent_windows_not_exclusive_slots
    """
    store, hoagie, first, second, preorder = _two_concurrent_windows_already_placed(api)
    third = preorder(W3)
    fourth = preorder(W4)
    refused = api.place_order(third["id"], {}, H.STORE_TERMINAL_HEADERS)
    H.validate_error(refused, H.ApiErrorId.ERR_PICKUP_WINDOW_FULL.value, 409)

    placed = X.place_order(api, fourth["id"])

    assert placed["production_status"] == "PLACED"
    assert placed["subtotal_gross_cents"] == 899
    assert X.read_order(api, third["id"])["production_status"] == "DRAFT"
    assert X.read_order(api, first["id"])["production_status"] == "PLACED"
    assert X.read_order(api, second["id"])["production_status"] == "PLACED"
