"""Compensating operations must walk their cascade backwards, hop for hop.

Voiding the newest accepted reading rewinds the device's whole page ledger onto
the values implied by the reading that remains — not to zero, and not by
subtracting a raw absolute counter.  Cancelling an automatically raised
cartridge order returns the site's open-unit tally and the contract's committed
spend to their exact pre-create values while deliberately leaving the
cartridge-page watermark alone.
"""

from test_helpers import (
    TEST_USERS,
    assert_consumable_order,
    assert_device_dimensions,
    assert_fields,
    assert_meter_read,
    cancel_order_payload,
    fetch_billing_period,
    fetch_consumable_order,
    fetch_contract,
    fetch_device,
    fetch_meter_read,
    fetch_site,
    list_orders_for_device,
    list_reads_for_device,
    make_fleet_ops_headers,
    setup_environment_with_auto_toner_order,
    setup_print_environment,
    submit_automated_read,
    validate_success,
    void_read_payload,
)

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
VOID_CLOCK = "2026-08-20T00:00:00Z"

FIRST_WINDOW = ("2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z")
SECOND_WINDOW = ("2026-08-08T00:00:00Z", "2026-08-15T00:00:00Z")

AUTO_ORDER_UNIT_PRICE_CENTS = 8_900
OPS = TEST_USERS["fleet_ops_headers"]


def _assert_same_instant(actual, expected, label):
    """Compare two ISO 8601 UTC instants without pinning the fractional digits."""
    assert actual is not None, f"{label} must be stamped, got None"
    assert actual[:19] == expected[:19], f"expected {label} {expected}, got {actual}"


def _two_accepted_reads_environment():
    """One ACTIVE mono device carrying two accepted readings, 5,000 then 9,000 pages.

    The second reading is the newest accepted one: it covers the later window and
    is therefore the only reading that may be voided.
    """
    env = setup_print_environment(period=(PERIOD_START, PERIOD_END), clock=VOID_CLOCK)
    env["first_read"] = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=5_000,
        toner_level_pct=80,
        coverage_start=FIRST_WINDOW[0],
        coverage_end=FIRST_WINDOW[1],
    )
    env["second_read"] = submit_automated_read(
        env["device_id"],
        env["period_id"],
        mono_meter=9_000,
        toner_level_pct=70,
        coverage_start=SECOND_WINDOW[0],
        coverage_end=SECOND_WINDOW[1],
    )
    return env


def _auto_order_environment():
    """A reading at 10 percent toner has minted one automatic cartridge order."""
    return setup_environment_with_auto_toner_order(
        toner_level_pct=10,
        mono_meter=1_000,
        coverage_start=PERIOD_START,
        coverage_end="2026-08-09T00:00:00Z",
        clock="2026-08-10T00:00:00Z",
    )


class TestVoidNewestMeterRead:
    """Voiding the newest accepted reading neutralises it and rewinds the device."""

    def test_void_zeroes_the_reading_deltas_and_leaves_the_older_reading_accepted(self, api):
        """The voided row stops contributing pages; the earlier row is untouched.

        PRD: "Voiding is a `FleetOpsController` action that takes a
        `voided_reason` of `WRONG_DEVICE`, `DUPLICATE_CAPTURE` or
        `CUSTOMER_DISPUTE` (the field's default value before any void is `NONE`),
        and performs `ACCEPTED → VOID`, which is terminal."
        PRD: "The reading's own `mono_delta` and `color_delta` are zeroed, its
        `status` becomes `VOID` and its `voided_reason` is recorded."
        PRD: "The period's `exception_open_count` is deliberately **unchanged** by
        a void, because a voided reading is neither open nor billable."

        Design: Difficulty/compensating_invariant/void_newest_read_restores_device_meter_watermarks_and_lifetime_counters
        """
        env = _two_accepted_reads_environment()

        voided = validate_success(
            api.void_meter_read(
                env["second_read"]["id"],
                void_read_payload("DUPLICATE_CAPTURE"),
                make_fleet_ops_headers("ops-1"),
            ),
            200,
        )

        assert_meter_read(voided)
        assert_fields(
            voided,
            status="VOID",
            voided_reason="DUPLICATE_CAPTURE",
            mono_delta=0,
            color_delta=0,
        )
        assert_fields(
            fetch_meter_read(env["first_read"]["id"]),
            status="ACCEPTED",
            voided_reason="NONE",
            mono_delta=5_000,
            color_delta=0,
        )
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)

        statuses = sorted(read["status"] for read in list_reads_for_device(env["device_id"]))
        assert statuses == ["ACCEPTED", "VOID"], f"expected one live and one void read, got {statuses}"

    def test_void_rewinds_every_device_meter_watermark_onto_the_remaining_reading(self, api):
        """The ledger lands on the remaining reading's values, not on zero.

        PRD: "The device's `last_accepted_mono_meter`, `last_accepted_color_meter`
        and `last_read_at` revert to the values carried by the device's remaining
        accepted reading with the greatest `coverage_end` (tie broken by
        `created_at`), or to 0, 0 and null when no accepted reading remains."
        PRD: "`lifetime_mono_pages` shrinks by the voided reading's `mono_delta`,
        `lifetime_color_pages` shrinks by its `color_delta`, and
        `pages_since_last_cartridge` shrinks by the sum of the two."
        PRD: "The device's `toner_level_pct` reverts to the `toner_level_pct` of
        that same remaining accepted reading, or to 100 when none remains."

        Design: Difficulty/compensating_invariant/void_newest_read_restores_device_meter_watermarks_and_lifetime_counters
        """
        env = _two_accepted_reads_environment()
        before = fetch_device(env["device_id"])
        assert_fields(
            before,
            last_accepted_mono_meter=9_000,
            lifetime_mono_pages=9_000,
            pages_since_last_cartridge=9_000,
            toner_level_pct=70,
        )

        validate_success(
            api.void_meter_read(
                env["second_read"]["id"],
                void_read_payload("DUPLICATE_CAPTURE"),
                make_fleet_ops_headers("ops-1"),
            ),
            200,
        )

        device = fetch_device(env["device_id"])
        assert_fields(
            device,
            last_accepted_mono_meter=5_000,
            last_accepted_color_meter=0,
            lifetime_mono_pages=5_000,
            lifetime_color_pages=0,
            pages_since_last_cartridge=5_000,
            toner_level_pct=80,
        )
        _assert_same_instant(device["last_read_at"], FIRST_WINDOW[1], "last_read_at")
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_OK")

    def test_voiding_both_readings_returns_the_device_to_its_empty_metering_state(self, api):
        """With no accepted reading left the watermarks fall back to 0, null and 100.

        PRD: "The device's `last_accepted_mono_meter`, `last_accepted_color_meter`
        and `last_read_at` revert to the values carried by the device's remaining
        accepted reading with the greatest `coverage_end` (tie broken by
        `created_at`), or to 0, 0 and null when no accepted reading remains."
        PRD: "The device's `toner_level_pct` reverts to the `toner_level_pct` of
        that same remaining accepted reading, or to 100 when none remains."
        PRD: "`lifetime_mono_pages` shrinks by the voided reading's `mono_delta`,
        `lifetime_color_pages` shrinks by its `color_delta`, and
        `pages_since_last_cartridge` shrinks by the sum of the two."

        Design: Difficulty/compensating_invariant/void_newest_read_restores_device_meter_watermarks_and_lifetime_counters
        """
        env = _two_accepted_reads_environment()

        validate_success(
            api.void_meter_read(
                env["second_read"]["id"],
                void_read_payload("DUPLICATE_CAPTURE"),
                make_fleet_ops_headers("ops-1"),
            ),
            200,
        )
        second_void = validate_success(
            api.void_meter_read(
                env["first_read"]["id"],
                void_read_payload("WRONG_DEVICE"),
                make_fleet_ops_headers("ops-1"),
            ),
            200,
        )

        assert_fields(
            second_void,
            status="VOID",
            voided_reason="WRONG_DEVICE",
            mono_delta=0,
            color_delta=0,
        )

        device = fetch_device(env["device_id"])
        assert_fields(
            device,
            last_accepted_mono_meter=0,
            last_accepted_color_meter=0,
            last_read_at=None,
            lifetime_mono_pages=0,
            lifetime_color_pages=0,
            pages_since_last_cartridge=0,
            toner_level_pct=100,
        )
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_OK")
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)


class TestCancelAutoRaisedConsumableOrder:
    """Cancelling the auto-raised cartridge unwinds the replenishment commitment."""

    def test_cancel_returns_the_site_and_contract_commitment_counters_to_zero(self, api):
        """Both commitment counters land back exactly on their pre-create values.

        PRD: "The fourth hop is caused by the third: if a cartridge order was
        created, the hosting site's `open_toner_units` grows by that order's
        `quantity` and the contract's `consumables_committed_cents` grows by that
        order's committed value."
        PRD: "Cancellation performs `ORDERED → CANCELLED`, and both `DELIVERED`
        and `CANCELLED` are terminal — attempting to deliver or cancel an order
        that has already reached either reports `ERR_ORDER_INVALID_STATE`."
        PRD: "The site's `open_toner_units` falls by the order's `quantity` and
        the contract's `consumables_committed_cents` falls by its
        `committed_cents`, so that both counters land back exactly on their
        pre-creation values, and the order's `version` increments."

        Design: Difficulty/compensating_invariant/cancel_auto_order_returns_site_toner_units_and_contract_commitment_to_zero
        """
        env = _auto_order_environment()
        order_id = env["order"]["id"]
        assert_fields(
            fetch_consumable_order(order_id),
            status="ORDERED",
            trigger_source="AUTO_THRESHOLD",
            quantity=1,
            unit_price_cents=AUTO_ORDER_UNIT_PRICE_CENTS,
            committed_cents=AUTO_ORDER_UNIT_PRICE_CENTS,
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=AUTO_ORDER_UNIT_PRICE_CENTS,
        )

        cancelled = validate_success(
            api.cancel_consumable_order(order_id, cancel_order_payload("WRONG_PART"), OPS), 200
        )

        assert_consumable_order(cancelled)
        assert_fields(
            cancelled,
            status="CANCELLED",
            cancel_reason="WRONG_PART",
            committed_cents=AUTO_ORDER_UNIT_PRICE_CENTS,
            delivered_at=None,
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)
        assert list_orders_for_device(env["device_id"], status="ORDERED") == [], (
            "no order of the device may remain in ORDERED status after the cancellation"
        )

    def test_cancel_puts_the_supply_dimension_back_to_supply_low_not_supply_ok(self, api):
        """Toner is still at 10 percent, so the device stays a replenishment candidate.

        PRD: "When an accepted reading leaves a device's `toner_level_pct` at or
        below 15 and the device's `supply_state` is `SUPPLY_OK`, the supply
        dimension moves `SUPPLY_OK → SUPPLY_LOW` and the device's `version`
        increments."
        PRD: "The device's supply dimension then resolves on the reverted toner
        level, but only when no other order for that device remains in `ORDERED`
        status: if the device's `toner_level_pct` is still at or below 15 percent
        the dimension moves `SUPPLY_ORDERED → SUPPLY_LOW`, and if it is above 15
        percent the dimension moves `SUPPLY_ORDERED → SUPPLY_OK`."

        Design: Difficulty/compensating_invariant/cancel_auto_order_returns_site_toner_units_and_contract_commitment_to_zero
        """
        env = _auto_order_environment()
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_ORDERED")

        validate_success(
            api.cancel_consumable_order(
                env["order"]["id"], cancel_order_payload("WRONG_PART"), OPS
            ),
            200,
        )

        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_LOW")
        assert_fields(device, toner_level_pct=10)

    def test_cancel_does_not_reset_the_cartridge_page_watermark(self, api):
        """Only a delivery moves the cartridge watermark, so the metering totals stand.

        PRD: "It is the total of monochrome plus colour pages across the device's
        accepted readings whose `coverage_end` falls after the `delivered_at` of
        the device's most recent delivered cartridge order; when no order has ever
        been delivered for that device, it is simply the device's
        `lifetime_mono_pages` plus its `lifetime_color_pages`."
        PRD: "Delivery performs `ORDERED → DELIVERED`, stamps `delivered_at` with
        the logical clock, returns the device's supply dimension `SUPPLY_ORDERED →
        SUPPLY_OK`, resets the device's `pages_since_last_cartridge` to 0 against
        the new delivery watermark, releases the commitment by reducing the site's
        `open_toner_units` by the order's `quantity` and the contract's
        `consumables_committed_cents` by the order's `committed_cents`, and
        increments both the order's `version` and the device's `version`."

        Design: Difficulty/compensating_invariant/cancel_auto_order_returns_site_toner_units_and_contract_commitment_to_zero
        """
        env = _auto_order_environment()

        validate_success(
            api.cancel_consumable_order(
                env["order"]["id"], cancel_order_payload("WRONG_PART"), OPS
            ),
            200,
        )

        assert_fields(
            fetch_device(env["device_id"]),
            pages_since_last_cartridge=1_000,
            lifetime_mono_pages=1_000,
            lifetime_color_pages=0,
            last_accepted_mono_meter=1_000,
        )
        reads = list_reads_for_device(env["device_id"])
        assert len(reads) == 1, f"expected the single accepted reading to survive: {reads}"
        assert_meter_read(reads[0])
        assert_fields(reads[0], status="ACCEPTED", mono_delta=1_000, color_delta=0)
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)
