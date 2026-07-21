"""Production batches: tempering, reseed, release, expiry (PRD §3.3, §3.4, §3.6).

Covers the tempering reseed back-edge, half-open tempering-line interval
conflict (and adjacency), the RELEASED precondition on allocation, direct
RAW->RELEASED, expired-lot release rejection, and the expiry sweep.
"""
from test_helpers import (
    validate_success, validate_error, make_customer_headers,
    PROD, SALES, ADMIN, start_tempering_payload,
    create_customer, create_product, create_tempering_line, create_batch,
    create_order, add_line, confirm_order, set_clock,
)


class TestReseedCycle:
    """non_linear_state_machine / batch_tempering_reseed_cycle — the batch cycles
    TEMPERING -> RAW (reseed), returning to its start state with reseed_count
    incremented to 1."""

    def _tempered_started_then_reseeded(self, api):
        product = create_product(
            base_price_cents=800, shelf_life_days=30, unit_weight_g=50,
            requires_tempering=True, tempering_minutes=60,
        )
        line = create_tempering_line()
        batch = create_batch(product["id"], 100)
        validate_success(api.start_tempering(
            batch["id"], start_tempering_payload(line["id"], "2026-07-01T10:00:00Z"), PROD))
        return validate_success(api.reseed_batch(batch["id"], PROD))

    def test_reseed_returns_to_raw_incrementing_count(self, api):
        """PRD §3.3: "reseeding sends a `TEMPERING` lot back to `RAW`: it
        increments the lot's `reseed_count` by 1 and frees the line by clearing
        `tempering_line_id`, `temper_start`, and `temper_end`."

        Design: Difficulty/non_linear_state_machine/batch_tempering_reseed_cycle
        """
        batch = self._tempered_started_then_reseeded(api)
        assert batch["status"] == "RAW", batch
        assert batch["reseed_count"] == 1, batch

    def test_reseed_frees_the_tempering_line(self, api):
        """PRD §3.3: "reseeding sends a `TEMPERING` lot back to `RAW`: it
        increments the lot's `reseed_count` by 1 and frees the line by clearing
        `tempering_line_id`, `temper_start`, and `temper_end`."

        Design: Difficulty/non_linear_state_machine/batch_tempering_reseed_cycle
        """
        batch = self._tempered_started_then_reseeded(api)
        assert batch["tempering_line_id"] is None, batch
        assert batch["temper_start"] is None, batch


class TestTemperingLineHalfOpenInterval:
    """resource_temporal_overlap / tempering_line_half_open_interval_overlap —
    batch2 [10:30,11:30) overlaps batch1 [10:00,11:00) on the same line and is
    rejected, whereas an end==start adjacency is allowed."""

    def _two_raw_batches_one_line(self, api):
        product = create_product(
            base_price_cents=800, shelf_life_days=30, unit_weight_g=50,
            requires_tempering=True, tempering_minutes=60,
        )
        line = create_tempering_line()
        b1 = create_batch(product["id"], 50)
        b2 = create_batch(product["id"], 50)
        validate_success(api.start_tempering(
            b1["id"], start_tempering_payload(line["id"], "2026-07-01T10:00:00Z"), PROD))
        return line, b2

    def test_overlapping_interval_rejected(self, api):
        """PRD §3.3: "any true overlap on the same `tempering_line_id` is rejected
        with `ERR_TEMPERING_LINE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tempering_line_half_open_interval_overlap
        """
        line, b2 = self._two_raw_batches_one_line(api)
        resp = api.start_tempering(
            b2["id"], start_tempering_payload(line["id"], "2026-07-01T10:30:00Z"), PROD)
        validate_error(resp, "ERR_TEMPERING_LINE_CONFLICT", 409)
        fetched = validate_success(api.get_batch(b2["id"], PROD))
        assert fetched["status"] == "RAW", fetched

    def test_end_to_start_adjacency_allowed(self, api):
        """PRD §3.3: "two lots that merely touch end-to-start — one ending exactly
        when the next begins — do not conflict, whereas any true overlap on the
        same `tempering_line_id` is rejected".

        Design: Difficulty/resource_temporal_overlap/tempering_line_half_open_interval_overlap
        """
        line, b2 = self._two_raw_batches_one_line(api)
        # b1 occupies [10:00, 11:00); b2 begins exactly at 11:00 -> adjacency.
        b2_started = validate_success(api.start_tempering(
            b2["id"], start_tempering_payload(line["id"], "2026-07-01T11:00:00Z"), PROD))
        assert b2_started["status"] == "TEMPERING", b2_started


class TestAllocateRequiresBatchReleased:
    """cross_entity_state_dependency / order_allocate_requires_batch_released — a
    confirmed order cannot allocate while the only batch of its product is
    TEMPERED (not RELEASED)."""

    def _confirmed_order_over_tempered_batch(self, api):
        product = create_product(
            base_price_cents=1000, shelf_life_days=30, unit_weight_g=40,
            requires_tempering=True, tempering_minutes=60,
        )
        line = create_tempering_line()
        batch = create_batch(product["id"], 100)
        validate_success(api.start_tempering(
            batch["id"], start_tempering_payload(line["id"], "2026-07-01T10:00:00Z"), PROD))
        set_clock("2026-07-01T11:00:00Z")
        validate_success(api.complete_tempering(batch["id"], PROD))
        customer = create_customer(account_type="RETAIL")
        order = create_order(customer["id"], "RETAIL")
        add_line(order["id"], customer["id"], product["id"], 1)
        confirm_order(order["id"], customer["id"])
        return batch, order

    def test_allocate_over_tempered_batch_rejected(self, api):
        """PRD §3.6: "requires that, for every line, the `RELEASED` non-expired
        batches of that line's product hold at least the line's `quantity` in
        aggregate `available_units`." PRD §3.6: "If, after all candidates for a
        line are exhausted, any need remains, the entire allocation is rejected
        with `ERR_INSUFFICIENT_INVENTORY`".

        Design: Difficulty/cross_entity_state_dependency/order_allocate_requires_batch_released
        """
        batch, order = self._confirmed_order_over_tempered_batch(api)
        resp = api.allocate_order(order["id"], SALES)
        validate_error(resp, "ERR_INSUFFICIENT_INVENTORY", 409)
        fetched_batch = validate_success(api.get_batch(batch["id"], PROD))
        assert fetched_batch["status"] == "TEMPERED", fetched_batch

    def test_order_stays_confirmed_after_failed_allocate(self, api):
        """PRD §3.6: "Once confirmed, an order is allocated against inventory by a
        `SalesManager`, advancing it `CONFIRMED -> ALLOCATED`." A rejected
        allocate leaves the order CONFIRMED with no reservations committed.

        Design: Difficulty/cross_entity_state_dependency/order_allocate_requires_batch_released
        """
        batch, order = self._confirmed_order_over_tempered_batch(api)
        api.allocate_order(order["id"], SALES)
        fetched = validate_success(api.get_order(order["id"], SALES))
        assert fetched["status"] == "CONFIRMED", fetched


def test_batch_release_from_raw_when_no_tempering(api):
    """PRD §3.3: "when the product does not, the lot goes directly `RAW ->
    RELEASED`". PRD §3.3: "on release the lot's `available_units` is set equal to
    its `initial_units`, making the full lot sellable."

    Design: Corner/state_machines/batch_release_from_raw_when_no_tempering
    """
    product = create_product(base_price_cents=700, shelf_life_days=60, unit_weight_g=20)
    batch = create_batch(product["id"], 80)
    released = validate_success(api.release_batch(batch["id"], PROD))
    assert released["status"] == "RELEASED", released
    assert released["available_units"] == 80, released


def test_release_expired_batch_rejected(api):
    """PRD §2.8: "Once the logical clock reaches or passes `lot_expiry`, the lot
    is expired and may no longer be tempered, released, cleared from quarantine,
    reserved, or allocated against; such attempts are rejected with
    `ERR_BATCH_EXPIRED`."

    Design: Corner/validations/release_expired_batch_rejected
    """
    product = create_product(base_price_cents=500, shelf_life_days=1, unit_weight_g=10)
    batch = create_batch(product["id"], 20, produced_at="2026-07-01T00:00:00Z")
    set_clock("2026-07-03T00:00:00Z")
    resp = api.release_batch(batch["id"], PROD)
    validate_error(resp, "ERR_BATCH_EXPIRED", 409)


def test_sweep_expired_transitions_released_to_expired(api):
    """PRD §3.4: "any `RELEASED` lot whose `lot_expiry` has been reached or passed
    by the logical clock transitions to the terminal `EXPIRED` state with
    `available_units` set to 0."

    Design: Corner/endpoints/sweep_expired_transitions_released_to_expired
    """
    product = create_product(base_price_cents=500, shelf_life_days=2, unit_weight_g=10)
    batch = create_batch(product["id"], 30, produced_at="2026-07-01T00:00:00Z")
    validate_success(api.release_batch(batch["id"], PROD))
    set_clock("2026-07-04T00:00:00Z")
    validate_success(api.sweep_expired(ADMIN))
    fetched = validate_success(api.get_batch(batch["id"], PROD))
    assert fetched["status"] == "EXPIRED", fetched
    assert fetched["available_units"] == 0, fetched
