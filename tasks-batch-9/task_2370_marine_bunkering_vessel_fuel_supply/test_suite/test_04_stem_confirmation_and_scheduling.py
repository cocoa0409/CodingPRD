"""Giving a confirmed stem a slot: candidate pools, buffers and port throughput.

Three contended resources decide whether a slot can exist. The server's own asset
selector needs a non-empty candidate pool. The chosen barge needs strictly more
than its turnaround buffer between its own slots, measured on closed intervals.
The port needs spare concurrency, counted across all barges on half-open
intervals — a deliberate asymmetry between the two interval rules.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    EARLY_QUOTE,
    NON_EXISTENT_UUID,
    OPS,
    add_asset,
    add_confirmed_nomination,
    api_client,
    assert_delivery_order,
    assert_nomination_state,
    assert_slot_end_from_quantity,
    auto_schedule_payload,
    build_approved_nomination,
    build_confirmed_nomination,
    build_scheduled_order,
    build_two_asset_context,
    create_delivery_order_payload,
    read_asset,
    read_nomination,
    read_order,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SLOT_START = "2026-08-10T06:00:00Z"
SLOT_END = "2026-08-10T12:00:00Z"

INSIDE_NOTICE_PERIOD = "2026-08-09T12:00:00Z"
LONG_SLOT_END = "2026-08-10T18:00:00Z"

ADJACENT_AT_BUFFER = "2026-08-10T13:30:00Z"
ADJACENT_PAST_BUFFER = "2026-08-10T13:31:00Z"
SECOND_SLOT_END = "2026-08-10T17:00:00Z"

REPLACEMENT_SLOT_START = "2026-08-10T14:00:00Z"
REPLACEMENT_SLOT_END = "2026-08-10T20:00:00Z"

STRADDLING_START = "2026-08-10T11:00:00Z"
STRADDLING_END = "2026-08-10T13:00:00Z"
TOUCHING_START = "2026-08-10T12:00:00Z"
TOUCHING_END = "2026-08-10T18:00:00Z"

ANTWERP_SINGLE_LANE = {
    "port_code": "BEANR",
    "name": "Antwerp",
    "concurrent_ops_capacity": 1,
    "spill_response_tier": "TIER_2",
}

SECOND_STEM = {
    "nominated_quantity_mt": 800.000,
    "vessel_imo": "9654321",
    "vessel_name": "MV Boreas",
    "eca_documentation_ref": "CHG-2026-0002",
}


class TestAutoScheduleCandidatePool:
    """The delegated route needs at least one surviving candidate."""

    def test_an_empty_candidate_pool_leaves_the_stem_exactly_as_it_was(self):
        """PRD §3.4: "When the operations desk delegates, the server builds a
        candidate pool from the delivery assets satisfying every one of the following:
        the asset's `home_port_id` equals the nomination's `port_id`; the asset's
        `asset_type` equals the nomination's `delivery_mode`; the asset's `status` is
        `AVAILABLE`; the asset's `capacity_mt` is at least the nomination's
        `nominated_quantity_mt`; the asset is `boom_certified`; the asset's
        `last_grade_id` is null, or shares the nominated grade's cross-contamination
        family, or the asset has `segregated_tanks`; the asset has no spill incident in
        status `OPEN`; and the derived slot violates neither the asset-level buffer rule
        nor the port-level capacity rule described above."
        PRD §3.4: "If the pool is empty, the request is rejected with
        `ERR_NO_ELIGIBLE_ASSET` (HTTP 409)."

        The only barge at the port lifts 1000.000 mt against a 1200.000 mt stem, so
        the capacity criterion empties the pool.

        Design: Difficulty/boundary_precision_check/auto_schedule_empty_candidate_pool
        """
        ctx = build_confirmed_nomination(
            quotes=[EARLY_QUOTE],
            asset={"name": "Bunker Small", "capacity_mt": 1000.000},
        )
        before = ctx["nomination"]

        response = api_client.auto_schedule_nomination(
            before["id"], auto_schedule_payload(SLOT_START, before["version"]), OPS
        )

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_ASSET)
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "CONFIRMED")
        assert after["version"] == before["version"], (
            "A refused selection must not move the stem's version, expected "
            f"{before['version']}, got {after['version']}"
        )

    def test_one_qualifying_barge_moves_the_pool_from_zero_to_one(self):
        """PRD §3.4: "Surviving candidates are ranked by `compliance_score` in
        descending order; ties are broken by the tightest fit, meaning the smallest
        value of the asset's `capacity_mt` minus the nomination's
        `nominated_quantity_mt`, in ascending order; any remaining tie is broken by
        `created_at` in ascending order."
        PRD §3.4: "The pumping duration in minutes is the nomination's
        `nominated_quantity_mt` divided by a pumping rate of 250 metric tonnes per
        hour, converted to minutes by multiplying by 60, and rounded **up** to a whole
        minute."
        PRD §3.4: "`slot_end` is `slot_start` plus that pumping duration plus a fixed
        hose connection and disconnection allowance of 60 minutes."
        PRD §3.4: "`planned_quantity_mt` on the created order defaults to the
        nomination's `nominated_quantity_mt`, carried at three decimal places."

        1200.000 mt at 250 mt per hour is 288 minutes, plus the 60-minute hose
        allowance, so the derived slot runs 06:00 to 11:48.

        Design: Difficulty/boundary_precision_check/auto_schedule_empty_candidate_pool
        """
        ctx = build_confirmed_nomination(
            quotes=[EARLY_QUOTE],
            asset={"name": "Bunker Small", "capacity_mt": 1000.000},
        )
        small_asset_id = ctx["asset"]["id"]
        before_version = ctx["nomination"]["version"]
        big_asset = add_asset(
            ctx["port"]["id"], name="Bunker Charlie", capacity_mt=3000.000
        )

        order = validate_success(
            api_client.auto_schedule_nomination(
                ctx["nomination"]["id"],
                auto_schedule_payload(SLOT_START, before_version),
                OPS,
            ),
            201,
        )

        assert_delivery_order(order)
        assert order["asset_id"] == big_asset["id"], (
            "The only barge that can lift the stem must be chosen, got "
            f"{order['asset_id']}"
        )
        assert order["asset_id"] != small_asset_id, (
            "The undersized barge must never enter the pool"
        )
        assert order["planned_quantity_mt"] == pytest.approx(1200.000, abs=0.0005), (
            "The planned tonnage defaults to the nominated tonnage, got "
            f"{order['planned_quantity_mt']}"
        )
        assert order["slot_start"].startswith("2026-08-10T06:00:00"), (
            f"The requested start must be honoured, got {order['slot_start']}"
        )
        assert order["slot_end"].startswith("2026-08-10T11:48:00"), (
            "288 pumping minutes plus 60 hose minutes from 06:00 is 11:48, got "
            f"{order['slot_end']}"
        )
        assert_slot_end_from_quantity(order, 1200.000)
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "SCHEDULED")
        assert after["version"] == before_version + 1, (
            f"Scheduling increments the stem's version once, expected "
            f"{before_version + 1}, got {after['version']}"
        )


class TestAssetTurnaroundBuffer:
    """Closed intervals plus a strictly-greater-than buffer on one barge."""

    def _barge_with_one_slot_and_a_waiting_stem(self):
        """Barge Alpha booked 06:00 to 12:00, plus a confirmed 800.000 mt stem."""
        ctx = build_scheduled_order(quotes=[EARLY_QUOTE])
        add_confirmed_nomination(ctx, store_as="nomination_b", **SECOND_STEM)
        return ctx

    def _second_order_payload(self, ctx, slot_start):
        nomination_b = ctx["nomination_b"]
        return create_delivery_order_payload(
            nomination_b["id"],
            ctx["asset"]["id"],
            nomination_b["version"],
            planned_quantity_mt=800.000,
            slot_start=slot_start,
            slot_end=SECOND_SLOT_END,
        )

    def test_a_gap_exactly_equal_to_the_buffer_is_rejected(self):
        """PRD §3.4: "The slot must not collide with the asset's own commitments:
        taking every **other** delivery order on the same asset whose
        `logistics_status` is `SCHEDULED`, `CLEARED` or `PUMPING`, the new closed
        interval from `slot_start` through `slot_end` must not intersect the existing
        closed interval, and the gap between the two intervals must be strictly greater
        than the asset's `turnaround_buffer_minutes` — a gap exactly equal to the buffer
        is rejected, not accepted."
        PRD §3.1: "`committed_quantity_mt` is the sum of `planned_quantity_mt` across
        the asset's delivery orders whose `logistics_status` is `SCHEDULED`, `CLEARED`
        or `PUMPING`, held to three decimals and initialised to 0.000; it is recomputed
        whenever an order enters or leaves that set."

        The intervals do not overlap at all — 12:00 against 13:30 — but the 90-minute
        gap only equals the barge's buffer.

        Design: Difficulty/resource_temporal_overlap/asset_turnaround_buffer_adjacency_conflict
        """
        ctx = self._barge_with_one_slot_and_a_waiting_stem()

        response = api_client.create_delivery_order(
            self._second_order_payload(ctx, ADJACENT_AT_BUFFER), OPS
        )

        validate_error(response, ApiErrorId.ERR_ASSET_SLOT_CONFLICT)
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            1200.000, abs=0.0005
        ), "Only the first slot may be committed after a refused booking"
        assert_nomination_state(
            read_nomination(nomination_id=ctx["nomination_b"]["id"]),
            "APPROVED",
            "CONFIRMED",
        )

    def test_one_minute_past_the_buffer_is_accepted(self):
        """PRD §3.4: "A violation of either half of that rule is reported as
        `ERR_ASSET_SLOT_CONFLICT` (HTTP 409)."
        PRD §3.4: "Either route moves `fulfillment_status` to `SCHEDULED` from either
        `CONFIRMED` or `AWAITING_SCHEDULE` — any other fulfilment state is rejected
        with `ERR_INVALID_NOMINATION_STATE` — creates a `DeliveryOrder` with
        `logistics_status` `SCHEDULED` and `measurement_status` `NOT_STARTED`,
        recomputes the chosen asset's `committed_quantity_mt`, and increments the
        nomination's `version` by one."

        Design: Difficulty/resource_temporal_overlap/asset_turnaround_buffer_adjacency_conflict
        """
        ctx = self._barge_with_one_slot_and_a_waiting_stem()
        first_order_id = ctx["order"]["id"]

        second = validate_success(
            api_client.create_delivery_order(
                self._second_order_payload(ctx, ADJACENT_PAST_BUFFER), OPS
            ),
            201,
        )

        assert second["slot_start"].startswith("2026-08-10T13:31:00"), (
            "A 91-minute gap clears the 90-minute buffer, got "
            f"{second['slot_start']}"
        )
        assert second["logistics_status"] == "SCHEDULED", (
            f"The replacement slot opens SCHEDULED, got {second['logistics_status']}"
        )
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            2000.000, abs=0.0005
        ), "Both slots must now be committed against the barge"
        first = read_order(order_id=first_order_id)
        assert first["slot_end"].startswith("2026-08-10T12:00:00"), (
            f"The earlier slot must be untouched, got {first['slot_end']}"
        )
        assert first["logistics_status"] == "SCHEDULED", (
            "A second slot on a different stem must not supersede the first, got "
            f"{first['logistics_status']}"
        )


class TestPortConcurrencyCap:
    """Half-open intervals aggregated across every barge at the port."""

    def _single_lane_port_with_one_slot_taken(self):
        """A one-lane port, two barges, Alpha holding 06:00 to 12:00."""
        ctx = build_scheduled_order(
            build_two_asset_context(port=ANTWERP_SINGLE_LANE, quotes=[EARLY_QUOTE])
        )
        add_confirmed_nomination(ctx, store_as="nomination_b", **SECOND_STEM)
        return ctx

    def _bravo_payload(self, ctx, slot_start, slot_end):
        nomination_b = ctx["nomination_b"]
        return create_delivery_order_payload(
            nomination_b["id"],
            ctx["second_asset"]["id"],
            nomination_b["version"],
            planned_quantity_mt=800.000,
            slot_start=slot_start,
            slot_end=slot_end,
        )

    def test_a_straddling_slot_on_another_barge_exhausts_the_port(self):
        """PRD §3.4: "Finally the port's own throughput is capped: counting the
        delivery orders at the same port whose `logistics_status` is `SCHEDULED`,
        `CLEARED` or `PUMPING` and whose half-open interval from `slot_start` up to but
        excluding `slot_end` intersects the new order's half-open interval, the new
        order is rejected with `ERR_PORT_CAPACITY_EXCEEDED` (HTTP 409) when that count
        already equals or exceeds the port's `concurrent_ops_capacity`."
        PRD §3.1: "`concurrent_ops_capacity` caps how many delivery orders may hold
        overlapping slots at the port simultaneously and defaults to 2, with a floor of
        1."

        The two orders sit on different barges, so the asset-level rule cannot explain
        the refusal.

        Design: Difficulty/resource_temporal_overlap/port_concurrency_halfopen_aggregate_capacity
        """
        ctx = self._single_lane_port_with_one_slot_taken()

        response = api_client.create_delivery_order(
            self._bravo_payload(ctx, STRADDLING_START, STRADDLING_END), OPS
        )

        validate_error(response, ApiErrorId.ERR_PORT_CAPACITY_EXCEEDED)
        assert read_asset(ctx, asset_id=ctx["second_asset"]["id"])[
            "committed_quantity_mt"
        ] == pytest.approx(0.000, abs=0.0005), (
            "The refused booking must leave the second barge uncommitted"
        )

    def test_touching_endpoints_never_intersect_under_half_open_semantics(self):
        """PRD §3.4: "Because the port rule uses half-open intervals, two back-to-back
        slots that merely touch at an endpoint do not intersect and are always allowed —
        a deliberate asymmetry with the asset rule, which uses closed intervals and
        therefore treats a shared endpoint as an overlap."

        Design: Difficulty/resource_temporal_overlap/port_concurrency_halfopen_aggregate_capacity
        """
        ctx = self._single_lane_port_with_one_slot_taken()

        second = validate_success(
            api_client.create_delivery_order(
                self._bravo_payload(ctx, TOUCHING_START, TOUCHING_END), OPS
            ),
            201,
        )

        assert second["asset_id"] == ctx["second_asset"]["id"], (
            f"The second barge must carry the new slot, got {second['asset_id']}"
        )
        assert second["logistics_status"] == "SCHEDULED", (
            f"Expected SCHEDULED, got {second['logistics_status']}"
        )
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            1200.000, abs=0.0005
        ), "The first barge keeps only its own slot"
        assert read_asset(ctx, asset_id=ctx["second_asset"]["id"])[
            "committed_quantity_mt"
        ] == pytest.approx(800.000, abs=0.0005), (
            "The second barge takes the new tonnage"
        )


class TestSchedulingPreconditions:
    """What must already be true before either scheduling route may run."""

    def test_auto_schedule_is_refused_while_the_stem_is_still_draft(self):
        """PRD §3.4: "Either route moves `fulfillment_status` to `SCHEDULED` from
        either `CONFIRMED` or `AWAITING_SCHEDULE` — any other fulfilment state is
        rejected with `ERR_INVALID_NOMINATION_STATE` — creates a `DeliveryOrder` with
        `logistics_status` `SCHEDULED` and `measurement_status` `NOT_STARTED`,
        recomputes the chosen asset's `committed_quantity_mt`, and increments the
        nomination's `version` by one."
        PRD §3.4: "Once confirmed, a stem needs a slot."

        Compliance is already `APPROVED` and an eligible barge is on the books, so the
        fulfilment dimension is the only obstacle.

        Design: Corner/state_machines/auto_schedule_from_draft_nomination_rejected
        """
        ctx = build_approved_nomination(quotes=[EARLY_QUOTE])
        approved = ctx["nomination"]
        assert_nomination_state(approved, "APPROVED", "DRAFT")

        response = api_client.auto_schedule_nomination(
            approved["id"], auto_schedule_payload(SLOT_START, approved["version"]), OPS
        )

        validate_error(response, ApiErrorId.ERR_INVALID_NOMINATION_STATE)
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "DRAFT")
        assert after["version"] == approved["version"], (
            f"A refused schedule must not move the version, expected "
            f"{approved['version']}, got {after['version']}"
        )
        _orders, meta = validate_paginated(api_client.list_delivery_orders(OPS))
        assert meta["total_count"] == 0, (
            f"No delivery order may exist after the refusal, got {meta['total_count']}"
        )

    def test_an_unknown_asset_reference_is_refused_before_the_nomination_moves(self):
        """PRD §2.7: "The order of resolution across the system is: `port_id`, then
        `grade_id`, then `customer_id`, then `asset_id`, then `nomination_id`, then
        `delivery_order_id`, then `bdn_id`, then `claim_id`, then
        `retest_of_analysis_id`, then an invoice `id`, then a spill incident `id`."
        PRD §2.7: "The corresponding rejections are `ERR_PORT_NOT_FOUND`,
        `ERR_FUEL_GRADE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
        `ERR_NOMINATION_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`,
        `ERR_BDN_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LAB_ANALYSIS_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND` and `ERR_SPILL_INCIDENT_NOT_FOUND`, each carrying HTTP
        404."
        PRD §3.4: "Either route moves `fulfillment_status` to `SCHEDULED` from either
        `CONFIRMED` or `AWAITING_SCHEDULE` — any other fulfilment state is rejected with
        `ERR_INVALID_NOMINATION_STATE` — creates a `DeliveryOrder` with
        `logistics_status` `SCHEDULED` and `measurement_status` `NOT_STARTED`,
        recomputes the chosen asset's `committed_quantity_mt`, and increments the
        nomination's `version` by one."

        The payload carries two independent references; the nomination resolves and the
        asset does not, and `asset_id` is resolved first.

        Design: Corner/entities/delivery_order_rejects_unknown_asset_reference
        """
        ctx = build_confirmed_nomination(quotes=[EARLY_QUOTE])
        confirmed = ctx["nomination"]

        response = api_client.create_delivery_order(
            create_delivery_order_payload(
                confirmed["id"], NON_EXISTENT_UUID, confirmed["version"]
            ),
            OPS,
        )

        validate_error(response, ApiErrorId.ERR_ASSET_NOT_FOUND)
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "CONFIRMED")
        assert after["version"] == confirmed["version"], (
            "A rejected write must not bump the optimistic-concurrency version, "
            f"expected {confirmed['version']}, got {after['version']}"
        )
        _orders, meta = validate_paginated(api_client.list_delivery_orders(OPS))
        assert meta["total_count"] == 0, (
            f"No delivery order may exist after the refusal, got {meta['total_count']}"
        )


class TestNominationVersionGuardOnScheduling:
    """`expected_nomination_version` protects the supersede side effect."""

    def _scheduled_stem_and_its_now_stale_version(self):
        """One SCHEDULED order plus the version the caller read before creating it."""
        ctx = build_confirmed_nomination(quotes=[EARLY_QUOTE])
        stale_version = ctx["nomination"]["version"]
        first = validate_success(
            api_client.create_delivery_order(
                create_delivery_order_payload(
                    ctx["nomination"]["id"], ctx["asset"]["id"], stale_version
                ),
                OPS,
            ),
            201,
        )
        ctx["order"] = first
        return ctx, stale_version

    def _replacement_payload(self, ctx, expected_version):
        return create_delivery_order_payload(
            ctx["nomination"]["id"],
            ctx["asset"]["id"],
            expected_version,
            slot_start=REPLACEMENT_SLOT_START,
            slot_end=REPLACEMENT_SLOT_END,
        )

    def test_replaying_the_consumed_version_takes_no_slot(self):
        """PRD §2.9: "Scheduling a delivery order against a nomination — whether the
        asset and slot are chosen explicitly or derived by the server's auto-schedule
        capability — requires the non-optional input field
        `expected_nomination_version`, carrying the client's last observed `version` of
        the target `Nomination`. If that value does not equal the nomination's current
        `version`, the request is rejected with `ERR_STALE_NOMINATION_VERSION` (HTTP
        412)."
        PRD §2.9: "This guard exists because a new order legitimately supersedes the
        nomination's existing scheduled or cleared order by cancelling it; without the
        guard, a client working from a stale read would silently cancel a slot it had
        never seen."

        Design: Corner/cross_cutting_complexity_layers/stale_nomination_version_on_order_create_rejected
        """
        ctx, stale_version = self._scheduled_stem_and_its_now_stale_version()

        response = api_client.create_delivery_order(
            self._replacement_payload(ctx, stale_version), OPS
        )

        validate_error(response, ApiErrorId.ERR_STALE_NOMINATION_VERSION)
        assert read_order(ctx)["logistics_status"] == "SCHEDULED", (
            "The slot the caller never saw must survive the refused replay, got "
            f"{read_order(ctx)['logistics_status']}"
        )
        _orders, meta = validate_paginated(
            api_client.list_delivery_orders(
                OPS, params={"nomination_id": ctx["nomination"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"Only the original slot may exist, got {meta['total_count']}"
        )
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            1200.000, abs=0.0005
        ), "The barge must still hold exactly the one committed slot"

    def test_the_first_order_create_is_what_consumed_the_version(self):
        """PRD §3.4: "Either route moves `fulfillment_status` to `SCHEDULED` from
        either `CONFIRMED` or `AWAITING_SCHEDULE` — any other fulfilment state is
        rejected with `ERR_INVALID_NOMINATION_STATE` — creates a `DeliveryOrder` with
        `logistics_status` `SCHEDULED` and `measurement_status` `NOT_STARTED`,
        recomputes the chosen asset's `committed_quantity_mt`, and increments the
        nomination's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/stale_nomination_version_on_order_create_rejected
        """
        ctx, stale_version = self._scheduled_stem_and_its_now_stale_version()

        current = read_nomination(ctx)

        assert_nomination_state(current, "APPROVED", "SCHEDULED")
        assert current["version"] == stale_version + 1, (
            f"Creating the first order increments the stem once, expected "
            f"{stale_version + 1}, got {current['version']}"
        )


class TestPortNoticePeriod:
    """`slot_start` measured against the clock plus the port's notice lead."""

    def test_a_slot_eighteen_hours_out_misses_a_twenty_four_hour_notice(self):
        """PRD §3.4: "The slot must respect the port's notice period: `slot_start` must
        be no earlier than the current logical clock plus the port's
        `notice_lead_hours`, or the request is rejected with
        `ERR_NOTICE_PERIOD_MISSED`."
        PRD §2.4: "Every subsequent evaluation of sample custody, claim windows, notice
        periods, slot admissibility and spill-decay ageing uses the new instant."
        PRD §3.1: "`committed_quantity_mt` is the sum of `planned_quantity_mt` across
        the asset's delivery orders whose `logistics_status` is `SCHEDULED`, `CLEARED`
        or `PUMPING`, held to three decimals and initialised to 0.000; it is recomputed
        whenever an order enters or leaves that set."

        The stem was confirmed while the slot was still five days out; advancing the
        clock to 2026-08-09T12:00:00Z leaves only 18 hours against Rotterdam's 24.

        Design: Corner/validations/notice_period_missed_on_order_creation_rejected
        """
        ctx = build_confirmed_nomination(quotes=[EARLY_QUOTE])
        confirmed = ctx["nomination"]
        assert ctx["port"]["notice_lead_hours"] == 24, (
            f"The port must demand 24 hours' notice, got "
            f"{ctx['port']['notice_lead_hours']}"
        )
        set_logical_clock(INSIDE_NOTICE_PERIOD)

        response = api_client.create_delivery_order(
            create_delivery_order_payload(
                confirmed["id"], ctx["asset"]["id"], confirmed["version"]
            ),
            OPS,
        )

        validate_error(response, ApiErrorId.ERR_NOTICE_PERIOD_MISSED)
        _orders, meta = validate_paginated(api_client.list_delivery_orders(OPS))
        assert meta["total_count"] == 0, (
            f"No slot may be taken after the refusal, got {meta['total_count']}"
        )
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            0.000, abs=0.0005
        ), (
            "The barge must stay uncommitted, got "
            f"{read_asset(ctx)['committed_quantity_mt']}"
        )
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "CONFIRMED")
        assert after["version"] == confirmed["version"], (
            f"A refused slot must not move the version, expected "
            f"{confirmed['version']}, got {after['version']}"
        )


class TestHandScheduledAssetSuitability:
    """The named asset must be the right kind of asset and big enough."""

    def test_a_planned_tonnage_above_the_barge_capacity_is_refused(self):
        """PRD §3.4: "The `planned_quantity_mt` may not exceed the asset's
        `capacity_mt`, or the request is rejected with
        `ERR_ASSET_CAPACITY_EXCEEDED`."
        PRD §3.1: "Each asset has a `name`, an `asset_type` of either `BARGE` or
        `TRUCK` declaring the delivery mode it provides, a `capacity_mt` giving the
        maximum tonnage it can lift in one delivery to three decimals and strictly
        positive, and a `home_port_id` naming the only port at which it may be
        scheduled."
        PRD §3.1: "`committed_quantity_mt` is the sum of `planned_quantity_mt` across
        the asset's delivery orders whose `logistics_status` is `SCHEDULED`, `CLEARED`
        or `PUMPING`, held to three decimals and initialised to 0.000; it is recomputed
        whenever an order enters or leaves that set."

        A 3500.000 mt stem cannot ride a 3000.000 mt barge, and the twelve-hour slot
        sits well inside the window so no temporal rule competes.

        Design: Corner/validations/asset_capacity_exceeded_on_order_rejected
        """
        ctx = build_confirmed_nomination(
            quotes=[EARLY_QUOTE],
            nomination={
                "nominated_quantity_mt": 3500.000,
                "vessel_imo": "9778899",
                "vessel_name": "MV Megas",
                "eca_documentation_ref": "CHG-2026-0010",
            },
        )
        confirmed = ctx["nomination"]
        assert ctx["asset"]["capacity_mt"] == pytest.approx(3000.000, abs=0.0005), (
            f"The barge must lift 3000.000 mt, got {ctx['asset']['capacity_mt']}"
        )

        response = api_client.create_delivery_order(
            create_delivery_order_payload(
                confirmed["id"],
                ctx["asset"]["id"],
                confirmed["version"],
                planned_quantity_mt=3500.000,
                slot_start=SLOT_START,
                slot_end=LONG_SLOT_END,
            ),
            OPS,
        )

        validate_error(response, ApiErrorId.ERR_ASSET_CAPACITY_EXCEEDED)
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            0.000, abs=0.0005
        ), (
            "The barge must stay uncommitted, got "
            f"{read_asset(ctx)['committed_quantity_mt']}"
        )
        after = read_nomination(ctx)
        assert_nomination_state(after, "APPROVED", "CONFIRMED")
        assert after["version"] == confirmed["version"], (
            f"A refused slot must not move the version, expected "
            f"{confirmed['version']}, got {after['version']}"
        )

    def test_a_truck_cannot_serve_a_barge_mode_stem(self):
        """PRD §3.4: "A hand-scheduled order must name a suitable asset: the asset's
        `home_port_id` must equal the nomination's `port_id` and the asset's
        `asset_type` must equal the nomination's `delivery_mode`, or the request is
        rejected with `ERR_ASSET_NOT_SUITABLE`."
        PRD §3.3: "Operationally it states `delivery_mode`, either `BARGE` or `TRUCK`,
        and the delivery window as `window_start`, the earliest instant the vessel can
        receive bunkers, and `window_end`, the latest."

        The truck is at the right port and lifts the tonnage comfortably, so the
        mismatch of kind is the only defect.

        Design: Corner/validations/truck_asset_for_barge_mode_rejected
        """
        ctx = build_confirmed_nomination(
            quotes=[EARLY_QUOTE],
            asset={
                "name": "Truck One",
                "asset_type": "TRUCK",
                "capacity_mt": 200.000,
            },
            nomination={
                "nominated_quantity_mt": 150.000,
                "vessel_imo": "9889900",
                "vessel_name": "MV Mikros",
                "eca_documentation_ref": "CHG-2026-0011",
            },
        )
        confirmed = ctx["nomination"]
        assert confirmed["delivery_mode"] == "BARGE", (
            f"The stem must ask for a barge, got {confirmed['delivery_mode']}"
        )
        assert ctx["asset"]["asset_type"] == "TRUCK", (
            f"The only asset must be a truck, got {ctx['asset']['asset_type']}"
        )

        response = api_client.create_delivery_order(
            create_delivery_order_payload(
                confirmed["id"],
                ctx["asset"]["id"],
                confirmed["version"],
                planned_quantity_mt=150.000,
            ),
            OPS,
        )

        validate_error(response, ApiErrorId.ERR_ASSET_NOT_SUITABLE)
        _orders, meta = validate_paginated(api_client.list_delivery_orders(OPS))
        assert meta["total_count"] == 0, (
            f"No slot may be taken after the refusal, got {meta['total_count']}"
        )
        assert read_asset(ctx)["committed_quantity_mt"] == pytest.approx(
            0.000, abs=0.0005
        ), (
            "The truck must stay uncommitted, got "
            f"{read_asset(ctx)['committed_quantity_mt']}"
        )
