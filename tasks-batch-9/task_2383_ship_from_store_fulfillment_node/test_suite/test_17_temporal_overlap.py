"""Temporal overlap of two different shared resources.

The first resource is a node's carrier-pickup calendar, whose windows are kept
apart by a symmetric thirty-minute dead band. The second is a node's
in-progress pick labour, which stacks only over half-open pick intervals that
genuinely intersect and carries no buffer at all.
"""

import pytest

from test_helpers import (
    CARRIER,
    accept,
    api_client,
    cancel_pickup,
    commit_routing,
    create_carrier_pickup_payload,
    find_assignment,
    make_store_associate_headers,
    read_assignment,
    read_inventory,
    read_pickup,
    read_store,
    register_node,
    register_sku,
    schedule_pickup,
    set_clock,
    setup_order_with_lines,
    stock_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# shared preambles
# --------------------------------------------------------------------------


def _utc_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to whole-second precision.

    A response may carry three fractional digits, so the raw string is not
    directly comparable with the instant the logical clock was set to.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.replace("Z", "")
    if "." in text:
        text = text.split(".")[0]
    return text


def _node_with_afternoon_pickup() -> tuple:
    """One node whose only pickup window runs 16:00Z-18:00Z at status
    SCHEDULED, with no orders and no inventory anywhere."""
    set_clock("2026-08-03T09:00:00Z")
    store = register_node("S1")
    pickup = schedule_pickup(
        store["id"],
        carrier_code="GRD",
        window_start_utc="2026-08-03T16:00:00Z",
        window_end_utc="2026-08-03T18:00:00Z",
        parcel_capacity=5,
    )
    assert pickup["status"] == "SCHEDULED", "the seeded window must start SCHEDULED"
    return store, pickup


def _propose_window(store_id: str, start_utc: str, end_utc: str, carrier_code: str = "EXP"):
    """Raw scheduling call so a refusal can be validated instead of asserted away."""
    return api_client.create_carrier_pickup(
        store_id,
        create_carrier_pickup_payload(
            carrier_code=carrier_code,
            window_start_utc=start_utc,
            window_end_utc=end_utc,
            parcel_capacity=5,
        ),
        CARRIER,
    )


def _kiosk_with_four_pick_tasks() -> dict:
    """One node (staffed_labor_minutes 60) holding four assignments.

    The first commits and is accepted at 09:05 with a pick deadline of 13:00Z;
    the other three commit at 12:00 and therefore carry a pick deadline of
    16:00Z, so the elapsed interval and the live intervals can be told apart.
    """
    set_clock("2026-08-03T09:00:00Z")
    store = register_node("S4")
    sku = register_sku("SKU-A")
    inventory = stock_inventory(store["id"], sku["id"], 20, 2)

    def _commit_one(order_code, customer_ref, quantity):
        built = setup_order_with_lines(
            [(sku["id"], quantity, 4500)],
            order_code=order_code,
            customer_ref=customer_ref,
            destination_zone=4,
            service_level="GROUND",
            promised_ship_by_utc="2026-08-03T16:30:00Z",
        )
        commit_routing(built["order"]["id"])
        return find_assignment(order_id=built["order"]["id"], store_id=store["id"])

    first = _commit_one("O-6101", "C-33", 4)

    set_clock("2026-08-03T09:05:00Z")
    accept(first["id"], store["id"])

    set_clock("2026-08-03T12:00:00Z")
    second = _commit_one("O-6102", "C-34", 4)
    third = _commit_one("O-6103", "C-35", 2)
    fourth = _commit_one("O-6104", "C-36", 1)

    return {
        "store": store,
        "sku": sku,
        "inventory": inventory,
        "elapsed": read_assignment(first["id"]),
        "second": second,
        "third": third,
        "fourth": fourth,
    }


# --------------------------------------------------------------------------
# Resource 1 — the node's carrier-pickup calendar
# --------------------------------------------------------------------------


class TestPickupWindowDeadBand:
    def test_window_twenty_minutes_after_an_existing_window_conflicts(self):
        """PRD §3.6: "The geometry is pairwise, never aggregated: a proposed window conflicts with an existing one when the proposed `window_start_utc` is earlier than the existing `window_end_utc` extended forward by half an hour **and** the existing `window_start_utc` is earlier than the proposed `window_end_utc` extended forward by half an hour."
        PRD §3.6: "Exactly thirty minutes of gap is acceptable — a gap greater than or equal to the buffer passes, a gap strictly smaller fails — and a conflict is reported as `ERR_PICKUP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pickup_windows_conflict_under_a_thirty_minute_symmetric_buffer
        """
        store, _pickup = _node_with_afternoon_pickup()

        response = _propose_window(
            store["id"], "2026-08-03T18:20:00Z", "2026-08-03T19:00:00Z"
        )

        validate_error(response, "ERR_PICKUP_WINDOW_OVERLAP")

    def test_window_ten_minutes_before_an_existing_window_conflicts(self):
        """PRD §3.6: "The geometry is pairwise, never aggregated: a proposed window conflicts with an existing one when the proposed `window_start_utc` is earlier than the existing `window_end_utc` extended forward by half an hour **and** the existing `window_start_utc` is earlier than the proposed `window_end_utc` extended forward by half an hour."
        PRD §3.6: "Exactly thirty minutes of gap is acceptable — a gap greater than or equal to the buffer passes, a gap strictly smaller fails — and a conflict is reported as `ERR_PICKUP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pickup_windows_conflict_under_a_thirty_minute_symmetric_buffer
        """
        store, _pickup = _node_with_afternoon_pickup()

        response = _propose_window(
            store["id"], "2026-08-03T15:35:00Z", "2026-08-03T15:50:00Z"
        )

        validate_error(response, "ERR_PICKUP_WINDOW_OVERLAP")

    def test_windows_exactly_thirty_minutes_on_either_side_are_scheduled(self):
        """PRD §3.6: "Exactly thirty minutes of gap is acceptable — a gap greater than or equal to the buffer passes, a gap strictly smaller fails — and a conflict is reported as `ERR_PICKUP_WINDOW_OVERLAP`."
        PRD §3.6: "The geometry is pairwise, never aggregated: a proposed window conflicts with an existing one when the proposed `window_start_utc` is earlier than the existing `window_end_utc` extended forward by half an hour **and** the existing `window_start_utc` is earlier than the proposed `window_end_utc` extended forward by half an hour."
        PRD §3.6: "A new window begins at `status` `SCHEDULED` with `reserved_parcels` 0."

        Design: Difficulty/resource_temporal_overlap/pickup_windows_conflict_under_a_thirty_minute_symmetric_buffer
        """
        store, _pickup = _node_with_afternoon_pickup()

        after = validate_success(
            _propose_window(store["id"], "2026-08-03T18:30:00Z", "2026-08-03T19:30:00Z"),
            201,
        )
        before = validate_success(
            _propose_window(store["id"], "2026-08-03T15:00:00Z", "2026-08-03T15:30:00Z"),
            201,
        )

        assert after["status"] == "SCHEDULED", (
            "a window starting exactly 30 minutes after the existing window's end "
            "clears the dead band and must be scheduled"
        )
        assert _utc_instant(after["window_start_utc"]) == _utc_instant(
            "2026-08-03T18:30:00Z"
        ), "the accepted window must keep the proposed start instant"
        assert after["reserved_parcels"] == 0, "a new window holds no parcels"

        assert before["status"] == "SCHEDULED", (
            "a window ending exactly 30 minutes before the existing window's start "
            "clears the dead band and must be scheduled"
        )
        assert _utc_instant(before["window_end_utc"]) == _utc_instant(
            "2026-08-03T15:30:00Z"
        ), "the accepted window must keep the proposed end instant"
        assert before["reserved_parcels"] == 0, "a new window holds no parcels"

    def test_window_truly_overlapping_a_scheduled_window_conflicts(self):
        """PRD §3.6: "The geometry is pairwise, never aggregated: a proposed window conflicts with an existing one when the proposed `window_start_utc` is earlier than the existing `window_end_utc` extended forward by half an hour **and** the existing `window_start_utc` is earlier than the proposed `window_end_utc` extended forward by half an hour."
        PRD §3.6: "Exactly thirty minutes of gap is acceptable — a gap greater than or equal to the buffer passes, a gap strictly smaller fails — and a conflict is reported as `ERR_PICKUP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pickup_windows_conflict_under_a_thirty_minute_symmetric_buffer
        """
        store, _pickup = _node_with_afternoon_pickup()
        later = validate_success(
            _propose_window(store["id"], "2026-08-03T18:30:00Z", "2026-08-03T19:30:00Z"),
            201,
        )
        assert later["status"] == "SCHEDULED", "setup expected the 18:30Z window to be scheduled"

        response = _propose_window(
            store["id"], "2026-08-03T19:00:00Z", "2026-08-03T20:00:00Z", carrier_code="GRD"
        )

        validate_error(response, "ERR_PICKUP_WINDOW_OVERLAP")

    def test_cancelled_window_leaves_the_conflict_comparison_set(self):
        """PRD §3.6: "Only windows of the same node whose `status` is `SCHEDULED` or `CLOSED` participate; `CANCELLED` and `DEPARTED` windows are ignored entirely."
        PRD §3.6: "A coordinator may also cancel a `SCHEDULED` window, moving it `SCHEDULED → CANCELLED`, which releases its slot so a new overlapping window may be scheduled at the node and increments `version`; cancellation is permitted only while `reserved_parcels` is exactly 0, and a window holding parcels is refused with `ERR_PICKUP_HAS_PARCELS`."
        PRD §2.4: "Carrier pickups may be filtered by `store_id`, `status` and `carrier_code`."
        PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

        Design: Difficulty/resource_temporal_overlap/pickup_windows_conflict_under_a_thirty_minute_symmetric_buffer
        """
        store, pickup = _node_with_afternoon_pickup()
        after = validate_success(
            _propose_window(store["id"], "2026-08-03T18:30:00Z", "2026-08-03T19:30:00Z"),
            201,
        )
        before = validate_success(
            _propose_window(store["id"], "2026-08-03T15:00:00Z", "2026-08-03T15:30:00Z"),
            201,
        )

        cancel_pickup(pickup["id"])
        cancelled = read_pickup(pickup["id"])
        assert cancelled["status"] == "CANCELLED", (
            "cancelling a SCHEDULED window must move it to CANCELLED"
        )
        assert cancelled["reserved_parcels"] == 0, (
            "the cancelled window held no parcels, which is what permitted the cancel"
        )

        inside = validate_success(
            _propose_window(
                store["id"], "2026-08-03T17:00:00Z", "2026-08-03T17:30:00Z", carrier_code="GRD"
            ),
            201,
        )
        assert inside["status"] == "SCHEDULED", (
            "17:00Z-17:30Z sits inside the cancelled window's span, which no longer "
            "participates in the conflict comparison, so it must be scheduled"
        )

        rows, meta = validate_paginated(
            api_client.list_carrier_pickups(
                CARRIER, params={"store_id": store["id"], "status": "SCHEDULED"}
            )
        )
        assert meta["total_count"] == 3, (
            "only the three surviving SCHEDULED windows match the filters, "
            f"got total_count {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {after["id"], before["id"], inside["id"]}, (
            "the SCHEDULED list must hold exactly the two dead-band-clearing windows "
            "and the window scheduled inside the cancelled span"
        )


# --------------------------------------------------------------------------
# Resource 2 — the node's concurrent pick labour
# --------------------------------------------------------------------------


class TestConcurrentPickLabourIntervals:
    def test_accept_ignores_a_pick_interval_that_has_already_elapsed(self):
        """PRD §3.5: "Take the candidate interval running from the current clock instant, inclusive, up to but excluding this assignment's `pick_deadline_utc`."
        PRD §3.5: "Consider the node's other assignments whose `status` is `ACCEPTED`, `PICKED` or `SHORT_PICKED`; one of them overlaps the candidate interval when its `accepted_at` is strictly before the candidate interval's end and the candidate interval's start is strictly before its own `pick_deadline_utc` — half-open geometry with no additional buffer."
        PRD §3.5: "The concurrent load is the sum of `labor_minutes_reserved` over those overlapping assignments plus this assignment's own `labor_minutes_reserved`; the cap is half the node's `staffed_labor_minutes` with any fraction discarded."
        PRD §3.5: "And `pick_deadline_utc` is the earlier of two instants: four hours after the assignment's `created_at`, and the instant on the creation date's UTC calendar day that falls `cutoff_utc_minutes` minutes after midnight UTC."
        PRD §3.5: "A `StoreAssociate` takes ownership of the task by accepting it, moving `ASSIGNED → ACCEPTED` and setting `accepted_at` to the clock instant."
        PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."

        Design: Difficulty/resource_temporal_overlap/concurrent_pick_labor_counts_only_overlapping_pick_intervals
        """
        ctx = _kiosk_with_four_pick_tasks()
        elapsed = ctx["elapsed"]

        assert _utc_instant(elapsed["pick_deadline_utc"]) == _utc_instant(
            "2026-08-03T13:00:00Z"
        ), (
            "the first assignment was created at 09:00Z, so four hours later is the "
            "earlier of the two candidate instants"
        )
        assert _utc_instant(elapsed["accepted_at"]) == _utc_instant(
            "2026-08-03T09:05:00Z"
        ), "the first assignment recorded the clock instant of its accept"

        set_clock("2026-08-03T13:30:00Z")
        accept(ctx["second"]["id"], ctx["store"]["id"])

        second = read_assignment(ctx["second"]["id"])
        assert second["status"] == "ACCEPTED", (
            "the already-elapsed pick interval [09:05Z, 13:00Z) does not reach the "
            "candidate interval starting at 13:30Z, so the accept must succeed"
        )
        assert _utc_instant(second["accepted_at"]) == _utc_instant(
            "2026-08-03T13:30:00Z"
        ), "accepted_at is the clock instant of the accept"
        assert _utc_instant(second["pick_deadline_utc"]) == _utc_instant(
            "2026-08-03T16:00:00Z"
        ), "created at 12:00Z, four hours later is earlier than the 17:00Z cutoff instant"
        assert second["labor_minutes_reserved"] == pytest.approx(18.00, abs=0.01), (
            "the labour standard is 6 minutes per order plus 3 minutes for each of the "
            "4 assigned units"
        )
        assert read_assignment(elapsed["id"])["status"] == "ACCEPTED", (
            "the elapsed assignment is untouched by the later accept"
        )

    def test_accept_at_exactly_the_concurrent_labour_cap_is_allowed(self):
        """PRD §3.5: "Consider the node's other assignments whose `status` is `ACCEPTED`, `PICKED` or `SHORT_PICKED`; one of them overlaps the candidate interval when its `accepted_at` is strictly before the candidate interval's end and the candidate interval's start is strictly before its own `pick_deadline_utc` — half-open geometry with no additional buffer."
        PRD §3.5: "The concurrent load is the sum of `labor_minutes_reserved` over those overlapping assignments plus this assignment's own `labor_minutes_reserved`; the cap is half the node's `staffed_labor_minutes` with any fraction discarded."
        PRD §3.5: "When the load strictly exceeds the cap the accept is refused with `ERR_LABOR_WINDOW_OVERSUBSCRIBED`; a load exactly equal to the cap is allowed."
        PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."

        Design: Difficulty/resource_temporal_overlap/concurrent_pick_labor_counts_only_overlapping_pick_intervals
        """
        ctx = _kiosk_with_four_pick_tasks()

        set_clock("2026-08-03T13:30:00Z")
        accept(ctx["second"]["id"], ctx["store"]["id"])

        set_clock("2026-08-03T13:35:00Z")
        accept(ctx["third"]["id"], ctx["store"]["id"])

        third = read_assignment(ctx["third"]["id"])
        assert third["status"] == "ACCEPTED", (
            "18.00 overlapping minutes plus this assignment's own 12.00 is exactly the "
            "cap of 30, and a load equal to the cap is allowed"
        )
        assert _utc_instant(third["accepted_at"]) == _utc_instant(
            "2026-08-03T13:35:00Z"
        ), "accepted_at is the clock instant of the accept"
        assert third["labor_minutes_reserved"] == pytest.approx(12.00, abs=0.01), (
            "the labour standard is 6 minutes per order plus 3 minutes for each of the "
            "2 assigned units"
        )
        assert read_assignment(ctx["second"]["id"])[
            "labor_minutes_reserved"
        ] == pytest.approx(18.00, abs=0.01), (
            "the overlapping assignment still carries the labour standard committed at "
            "its creation"
        )

    def test_accept_is_refused_when_two_overlapping_picks_push_the_load_over_the_cap(self):
        """PRD §3.5: "The concurrent load is the sum of `labor_minutes_reserved` over those overlapping assignments plus this assignment's own `labor_minutes_reserved`; the cap is half the node's `staffed_labor_minutes` with any fraction discarded."
        PRD §3.5: "When the load strictly exceeds the cap the accept is refused with `ERR_LABOR_WINDOW_OVERSUBSCRIBED`; a load exactly equal to the cap is allowed."
        PRD §2.9: "A node's `reserved_labor_minutes` equals the sum of `labor_minutes_reserved` over that node's assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."
        PRD §3.3: "`units_committed_epoch` here is itself derived: it is the sum of `assigned_units` over the node's assignments whose `epoch` equals the epoch of the node's open performance window and whose `status` is neither `REJECTED` nor `CANCELLED`, and it is reset to 0 when a window closes."
        PRD §3.1: "A row's `reserved_units` is always the sum, over the assignment lines whose owning assignment belongs to this node and whose served demand line references this SKU, of that line's `units_assigned` minus its `units_cancelled`, counting only assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."
        PRD §2.9: "For every pairing of a node and a SKU, whenever `on_hand_units` minus `reserved_units` minus `safety_stock_units` is not negative, `on_hand_units` equals the sum of `available_to_promise_units`, `reserved_units` and `safety_stock_units`."

        Design: Difficulty/resource_temporal_overlap/concurrent_pick_labor_counts_only_overlapping_pick_intervals
        """
        ctx = _kiosk_with_four_pick_tasks()
        store_id = ctx["store"]["id"]

        set_clock("2026-08-03T13:30:00Z")
        accept(ctx["second"]["id"], store_id)
        set_clock("2026-08-03T13:35:00Z")
        accept(ctx["third"]["id"], store_id)

        set_clock("2026-08-03T13:40:00Z")
        response = api_client.accept_assignment(
            ctx["fourth"]["id"], make_store_associate_headers(store_id)
        )

        validate_error(response, "ERR_LABOR_WINDOW_OVERSUBSCRIBED")

        fourth = read_assignment(ctx["fourth"]["id"])
        assert fourth["status"] == "ASSIGNED", (
            "a refused accept leaves the assignment at ASSIGNED"
        )
        assert fourth["accepted_at"] is None, (
            "a refused accept never stamps accepted_at"
        )
        assert fourth["labor_minutes_reserved"] == pytest.approx(9.00, abs=0.01), (
            "the labour standard is 6 minutes per order plus 3 minutes for the single "
            "assigned unit"
        )

        node = read_store(store_id)
        assert node["reserved_labor_minutes"] == pytest.approx(57.00, abs=0.01), (
            "all four assignments still hold their labour standard: 18.00 + 18.00 + "
            "12.00 + 9.00"
        )
        assert node["units_committed_epoch"] == 11, (
            "the node's four live assignments committed 4 + 4 + 2 + 1 units in the epoch"
        )

        inventory = read_inventory(ctx["inventory"]["id"])
        assert inventory["reserved_units"] == 11, (
            "every unit assigned by the four live assignments is still reserved"
        )
        assert inventory["available_to_promise_units"] == 7, (
            "20 on hand less 11 reserved less the 2-unit safety buffer"
        )
