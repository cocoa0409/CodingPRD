"""Concurrency tokens, the reorder threshold, and derived counters that never drift.

The first two suites drive the two optimistic-concurrency tokens the platform
requires on a request body: a replayed projection and a replayed toner order are
both refused on the stale token, nothing moves, and the same body succeeds once
the token is re-read. The remaining suites pin the inclusive reorder threshold,
prove every denormalised counter is recomputed by the request that changes its
source, and show that no cascade is deferred to a later pass.
"""

from test_helpers import (
    FLEET_OPS_2_USER_ID,
    FLEET_OPS_USER_ID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_device_dimensions,
    assert_fields,
    cancel_order_payload,
    consumable_order_payload,
    fetch_billing_period,
    fetch_consumable_order,
    fetch_contract,
    fetch_device,
    fetch_meter_read,
    fetch_site,
    get_success_data,
    list_orders_for_device,
    make_fleet_ops_headers,
    meter_read_payload,
    open_order_for_device,
    provisional_statement_payload,
    run_sweep,
    set_clock,
    setup_print_environment,
    validate_error,
    validate_paginated,
    validate_success,
    void_read_payload,
)

AM = TEST_USERS["account_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
OPS = TEST_USERS["fleet_ops_headers"]

CONTRACT = {
    "customer_name": "Larkin Mfg",
    "term_months": 36,
    "included_service_scope": "BASIC",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 48_000,
}
MONO_TIERS = ((1, 1, None, 9_375),)
DEVICE = {
    "asset_tag": "MPS-0001",
    "model_code": "XR-M4200",
    "rated_monthly_duty_cycle": 20_000,
    "assessed_monthly_mono_pages": 9_000,
    "assessed_monthly_color_pages": 0,
    "baseline_cost_micro_dollars_per_page": 21_000,
    "baseline_overhead_cents_per_month": 4_500,
    "color_capable": False,
}
SITE = {"name": "Plant 1", "address_region": "NE-01", "toner_unit_cap": 4}

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
MID_PERIOD_CLOCK = "2026-08-15T00:00:00Z"
MID_PERIOD_COVERAGE_END = "2026-08-15T00:00:00Z"

# The August window is 31 days long and 14 whole days have elapsed at the
# mid-period clock, so 3,000 actual mono pages project to
# round_half_up(3000 * 31 / 14) = 6,643 pages, and 6,643 pages at 9,375
# micro-dollars each is 6,227.8125 cents, which rounds half up to 6,228 cents.
ACTUAL_MONO_PAGES = 3_000
PROJECTED_CENTS = 6_228
# The same 3,000 pages priced as actuals are 2,812.5 cents, rounding to 2,813.
ACTUAL_CENTS = 2_813
MANUAL_UNIT_PRICE_CENTS = 9_200
AUTO_UNIT_PRICE_CENTS = 8_900


def _metered_fleet(clock=MID_PERIOD_CLOCK, toner_unit_cap=4):
    """One ACTIVE device at one site, with an OPEN period and the clock set."""
    site = dict(SITE)
    site["toner_unit_cap"] = toner_unit_cap
    return setup_print_environment(
        contract=CONTRACT,
        mono_tiers=MONO_TIERS,
        site=site,
        devices=[dict(DEVICE)],
        period=(PERIOD_START, PERIOD_END),
        clock=clock,
    )


def _submit_read(
    env,
    mono_meter,
    toner_level_pct,
    coverage_start=PERIOD_START,
    coverage_end=MID_PERIOD_COVERAGE_END,
    user_id=FLEET_OPS_USER_ID,
):
    """Push one automated reading and return the raw response."""
    return api_client.submit_automated_meter_read(
        meter_read_payload(
            env["device_id"],
            env["period_id"],
            mono_meter=mono_meter,
            color_meter=0,
            toner_level_pct=toner_level_pct,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        ),
        make_fleet_ops_headers(user_id),
    )


def _statements_for_period(period_id):
    data, meta = validate_paginated(
        api_client.list_billing_statements(BA, params={"billing_period_id": period_id})
    )
    return data, meta


def _fleet_with_one_accepted_reading():
    """The metered fleet plus a single ACCEPTED reading of 3,000 mono pages."""
    env = _metered_fleet()
    env["read"] = get_success_data(_submit_read(env, ACTUAL_MONO_PAGES, 70))
    return env


class TestStalePeriodVersionBlocksRegeneration:
    """Regeneration is legal, so only the period version token can stop a replay."""

    def test_a_replayed_projection_carrying_the_stale_period_version_is_refused(self):
        """The second call with the same token is refused and supersedes nothing.

        PRD: "A provisional-statement request must carry `expected_billing_period_version` as a required (never optional) body field, holding the client's last observed `version` of the target `BillingPeriod`."
        PRD: "If that value differs from the period's current `version` at the moment the write is applied, the request is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412), so an analyst cannot publish a projection derived from a period whose read set or sweep count has since advanced."
        PRD: "Generation drives `OPEN → PROVISIONAL`, `SWEPT → PROVISIONAL` or `PROVISIONAL → PROVISIONAL`, sets `provisional_total_cents` to the new statement's `total_cents`, and increments the period's `version` by 1."
        PRD: "Each device's projected pages for a meter are its actual pages for that meter multiplied by the period length in days, divided by the elapsed length in days, and rounded half up to a whole page."

        Design: Corner/complexity_layers/optimistic_concurrency_stale_period_version_blocks_regeneration_then_the_refreshed_version_succeeds
        """
        env = _fleet_with_one_accepted_reading()
        period_id = env["period_id"]
        observed_version = fetch_billing_period(period_id)["version"]

        first = validate_success(
            api_client.generate_provisional_statement(
                period_id, provisional_statement_payload(observed_version), BA
            ),
            expected_status=201,
        )
        assert_fields(
            first,
            variant="PROVISIONAL",
            projection_basis="PROJECTED",
            usage_subtotal_cents=PROJECTED_CENTS,
            total_cents=PROJECTED_CENTS,
        )
        assert_fields(
            fetch_billing_period(period_id),
            status="PROVISIONAL",
            provisional_total_cents=PROJECTED_CENTS,
            version=observed_version + 1,
        )

        # The identical body, replayed against a period whose version has moved.
        validate_error(
            api_client.generate_provisional_statement(
                period_id, provisional_statement_payload(observed_version), BA
            ),
            ApiErrorId.ERR_STALE_PERIOD_VERSION,
        )

        # No statement was created, none was superseded, and the period stood still.
        statements, statements_meta = _statements_for_period(period_id)
        assert statements_meta["total_count"] == 1
        assert statements[0]["id"] == first["id"]
        assert_fields(
            fetch_billing_period(period_id),
            status="PROVISIONAL",
            provisional_total_cents=PROJECTED_CENTS,
            version=observed_version + 1,
        )
        assert_fields(
            validate_success(api_client.get_billing_statement(first["id"], BA)),
            id=first["id"],
            total_cents=PROJECTED_CENTS,
        )

    def test_the_refreshed_period_version_regenerates_and_supersedes_the_projection(self):
        """Re-reading the version lets the same body through, deleting the first projection.

        PRD: "If that value differs from the period's current `version` at the moment the write is applied, the request is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412), so an analyst cannot publish a projection derived from a period whose read set or sweep count has since advanced."
        PRD: "Regeneration is a first-class operation: any pre-existing provisional statement for that period is **superseded**, meaning it is deleted together with all of its lines and replaced by the newly generated one, and `provisional_total_cents` is overwritten with the new projection."
        PRD: "Each `StatementLine` records its parent `statement_id`, the `device_id` it prices, the `page_class`, the `pages` it covers, the `rate_micro_dollars_per_page` copied from the statement's selected rate for that class, and an `amount_cents` computed as the pages multiplied by that rate, divided by 10,000, and rounded half up to a whole cent."

        Design: Corner/complexity_layers/optimistic_concurrency_stale_period_version_blocks_regeneration_then_the_refreshed_version_succeeds
        """
        env = _fleet_with_one_accepted_reading()
        period_id = env["period_id"]
        first_version = fetch_billing_period(period_id)["version"]
        first = get_success_data(
            api_client.generate_provisional_statement(
                period_id, provisional_statement_payload(first_version), BA
            )
        )
        validate_error(
            api_client.generate_provisional_statement(
                period_id, provisional_statement_payload(first_version), BA
            ),
            ApiErrorId.ERR_STALE_PERIOD_VERSION,
        )

        refreshed_version = fetch_billing_period(period_id)["version"]
        assert refreshed_version == first_version + 1
        second = validate_success(
            api_client.generate_provisional_statement(
                period_id, provisional_statement_payload(refreshed_version), BA
            ),
            expected_status=201,
        )
        assert second["id"] != first["id"]
        assert_fields(
            second,
            variant="PROVISIONAL",
            projection_basis="PROJECTED",
            usage_subtotal_cents=PROJECTED_CENTS,
            total_cents=PROJECTED_CENTS,
        )

        # The superseded projection is gone, lines and all.
        validate_error(
            api_client.get_billing_statement(first["id"], BA),
            ApiErrorId.ERR_STATEMENT_NOT_FOUND,
        )
        statements, statements_meta = _statements_for_period(period_id)
        assert statements_meta["total_count"] == 1
        assert statements[0]["id"] == second["id"]
        lines, lines_meta = validate_paginated(
            api_client.list_statement_lines(second["id"], BA, params={"limit": 100})
        )
        assert lines_meta["total_count"] == 1
        assert_fields(
            lines[0],
            device_id=env["device_id"],
            page_class="MONO",
            pages=6_643,
            rate_micro_dollars_per_page=9_375,
            amount_cents=PROJECTED_CENTS,
        )
        assert_fields(
            fetch_billing_period(period_id),
            status="PROVISIONAL",
            provisional_total_cents=PROJECTED_CENTS,
            version=refreshed_version + 1,
        )


def _device_in_supply_low_with_no_open_order():
    """A device whose toner is at 10 percent and whose automatic order was cancelled.

    The reading drives the supply dimension to SUPPLY_ORDERED and raises the
    automatic cartridge order; cancelling that order releases both commitment
    counters and, because the toner level is still at or below 15 percent,
    leaves the device in SUPPLY_LOW — the one state a manual order may act on.
    """
    env = _metered_fleet(toner_unit_cap=2)
    env["read"] = get_success_data(_submit_read(env, 4_000, 10))
    auto_order = open_order_for_device(env["device_id"])
    get_success_data(
        api_client.cancel_consumable_order(
            auto_order["id"], cancel_order_payload("WRONG_PART"), OPS
        )
    )
    env["auto_order"] = auto_order
    return env


def _manual_order_body(env, expected_device_version):
    return consumable_order_payload(
        env["device_id"],
        expected_device_version,
        part_type="TONER_BLACK",
        unit_price_cents=MANUAL_UNIT_PRICE_CENTS,
        quantity=1,
    )


class TestStaleDeviceVersionBlocksTheManualOrder:
    """The device token is checked ahead of the supply-state gate it would also trip."""

    def test_a_replayed_manual_order_carrying_the_stale_device_version_is_refused(self):
        """The replay reports the version failure, not the supply-state failure, and holds nothing.

        PRD: "A manual consumable-order creation must carry `expected_device_version` as a required (never optional) body field, holding the client's last observed `version` of the target `Device`."
        PRD: "If that value differs from the device's current `version` at the moment the write is applied, the request is rejected with `ERR_STALE_DEVICE_VERSION` (HTTP 412), so an operator cannot re-order toner against a stale view of the device's supply dimension."
        PRD: "**Optimistic concurrency.** The supplied parent version matches the parent's current `version` per §2.8 — otherwise `ERR_STALE_PERIOD_VERSION` or `ERR_STALE_DEVICE_VERSION` (412)."
        PRD: "The device's `supply_state` must currently be `SUPPLY_LOW` or `SUPPLY_BLOCKED`, and a device in `SUPPLY_OK` or already `SUPPLY_ORDERED` is refused as an invalid device transition reporting `ERR_DEVICE_INVALID_STATE`."
        PRD: "The order is created with `trigger_source` `MANUAL` and a `status` of `ORDERED`; its `committed_cents` is derived as the `quantity` multiplied by the `unit_price_cents`."

        Design: Corner/complexity_layers/optimistic_concurrency_stale_device_version_blocks_the_manual_toner_order
        """
        env = _device_in_supply_low_with_no_open_order()
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_LOW")
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        observed_version = fetch_device(env["device_id"])["version"]

        first = validate_success(
            api_client.create_consumable_order(
                _manual_order_body(env, observed_version), OPS
            ),
            expected_status=201,
        )
        assert_fields(
            first,
            trigger_source="MANUAL",
            status="ORDERED",
            quantity=1,
            unit_price_cents=MANUAL_UNIT_PRICE_CENTS,
            committed_cents=MANUAL_UNIT_PRICE_CENTS,
        )
        assert_device_dimensions(
            fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_ORDERED"
        )
        assert_fields(fetch_device(env["device_id"]), version=observed_version + 1)
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=MANUAL_UNIT_PRICE_CENTS,
        )

        # The identical body replayed on the version observed before the order.
        validate_error(
            api_client.create_consumable_order(
                _manual_order_body(env, observed_version), OPS
            ),
            ApiErrorId.ERR_STALE_DEVICE_VERSION,
        )

        # No second order, no extra commitment, no further version increment.
        open_orders = list_orders_for_device(env["device_id"], status="ORDERED")
        assert len(open_orders) == 1
        assert open_orders[0]["id"] == first["id"]
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=MANUAL_UNIT_PRICE_CENTS,
        )
        assert_fields(fetch_device(env["device_id"]), version=observed_version + 1)
        assert_device_dimensions(
            fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_ORDERED"
        )

    def test_the_same_manual_order_succeeds_once_the_device_version_is_re_read(self):
        """Cancelling the open order and re-reading the version lets the same body through.

        PRD: "If that value differs from the device's current `version` at the moment the write is applied, the request is rejected with `ERR_STALE_DEVICE_VERSION` (HTTP 412), so an operator cannot re-order toner against a stale view of the device's supply dimension."
        PRD: "The site's `open_toner_units` falls by the order's `quantity` and the contract's `consumables_committed_cents` falls by its `committed_cents`, so that both counters land back exactly on their pre-creation values, and the order's `version` increments."
        PRD: "The order is created with `trigger_source` `MANUAL` and a `status` of `ORDERED`; its `committed_cents` is derived as the `quantity` multiplied by the `unit_price_cents`."

        Design: Corner/complexity_layers/optimistic_concurrency_stale_device_version_blocks_the_manual_toner_order
        """
        env = _device_in_supply_low_with_no_open_order()
        stale_version = fetch_device(env["device_id"])["version"]
        first = get_success_data(
            api_client.create_consumable_order(_manual_order_body(env, stale_version), OPS)
        )
        validate_error(
            api_client.create_consumable_order(_manual_order_body(env, stale_version), OPS),
            ApiErrorId.ERR_STALE_DEVICE_VERSION,
        )

        cancelled = validate_success(
            api_client.cancel_consumable_order(
                first["id"], cancel_order_payload("WRONG_PART"), OPS
            )
        )
        assert_fields(cancelled, status="CANCELLED", cancel_reason="WRONG_PART")
        assert_device_dimensions(fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_LOW")
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)

        refreshed_version = fetch_device(env["device_id"])["version"]
        assert refreshed_version > stale_version
        second = validate_success(
            api_client.create_consumable_order(
                _manual_order_body(env, refreshed_version), OPS
            ),
            expected_status=201,
        )
        assert_fields(
            second,
            status="ORDERED",
            trigger_source="MANUAL",
            committed_cents=MANUAL_UNIT_PRICE_CENTS,
        )
        assert second["id"] != first["id"]
        assert_device_dimensions(
            fetch_device(env["device_id"]), "ACTIVE", "SUPPLY_ORDERED"
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=MANUAL_UNIT_PRICE_CENTS,
        )


FIRST_CLOCK = "2026-08-05T00:00:00Z"
SECOND_CLOCK = "2026-08-10T00:00:00Z"
THIRD_CLOCK = "2026-08-20T00:00:00Z"


def _fleet_with_a_reading_just_above_the_threshold():
    """One accepted reading of 1,000 mono pages reporting toner at 16 percent."""
    env = _metered_fleet(clock=FIRST_CLOCK)
    env["first_read"] = get_success_data(
        _submit_read(env, 1_000, 16, PERIOD_START, FIRST_CLOCK)
    )
    return env


def _fleet_with_the_threshold_order_open():
    """A second reading at exactly 15 percent has raised the automatic order."""
    env = _fleet_with_a_reading_just_above_the_threshold()
    set_clock(SECOND_CLOCK)
    env["second_read"] = get_success_data(
        _submit_read(env, 5_000, 15, FIRST_CLOCK, SECOND_CLOCK)
    )
    env["order"] = open_order_for_device(env["device_id"])
    return env


class TestTonerReorderThresholdIsInclusiveAtFifteen:
    """Silent at 16 percent, firing at 15, and re-armed by the next delivery."""

    def test_a_reading_at_sixteen_percent_raises_no_order_at_all(self):
        """One point above the threshold leaves the supply dimension untouched.

        PRD: "When an accepted reading leaves a device's `toner_level_pct` at or below 15 and the device's `supply_state` is `SUPPLY_OK`, the supply dimension moves `SUPPLY_OK → SUPPLY_LOW` and the device's `version` increments."
        PRD: "The second hop writes the device: `last_accepted_mono_meter` and `last_accepted_color_meter` take the submitted absolute values, `last_read_at` takes the reading's `coverage_end`, `toner_level_pct` takes the reading's reported level, `lifetime_mono_pages` grows by `mono_delta`, `lifetime_color_pages` grows by `color_delta`, `pages_since_last_cartridge` grows by the sum of the two deltas, and the device's `version` increments."

        Design: Corner/complexity_layers/rate_threshold_triggers_toner_reorder_fires_at_15_percent_not_16_and_re_arms_after_delivery
        """
        env = _metered_fleet(clock=FIRST_CLOCK)
        read = validate_success(
            _submit_read(env, 1_000, 16, PERIOD_START, FIRST_CLOCK), expected_status=201
        )
        assert_fields(read, status="ACCEPTED", mono_delta=1_000, toner_level_pct=16)

        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_OK")
        assert_fields(device, toner_level_pct=16, pages_since_last_cartridge=1_000)
        assert list_orders_for_device(env["device_id"]) == []
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)

    def test_a_reading_at_exactly_fifteen_percent_raises_one_automatic_order(self):
        """The threshold is inclusive, and it raises a single cartridge at the standard price.

        PRD: "When an accepted reading leaves a device's `toner_level_pct` at or below 15 and the device's `supply_state` is `SUPPLY_OK`, the supply dimension moves `SUPPLY_OK → SUPPLY_LOW` and the device's `version` increments."
        PRD: "When both hold, the supply dimension moves `SUPPLY_LOW → SUPPLY_ORDERED` and a cartridge order is created with `trigger_source` `AUTO_THRESHOLD`, a `quantity` of exactly 1, a `unit_price_cents` of 8,900 — the provider's standard automatic-replenishment unit price of $89 per cartridge — and a `part_type` chosen from the device and the reading: `TONER_COLOR` when the device is `color_capable` **and** the accepted reading's `color_delta` is greater than zero, and `TONER_BLACK` in every other case."
        PRD: "The order is then flagged as waste, in the derived `waste_flagged` field, exactly when two things hold together: the device has at least one earlier cartridge order that reached `DELIVERED`, and the snapshotted page count is **strictly less than 3,000 pages**."
        PRD: "The fourth hop is caused by the third: if a cartridge order was created, the hosting site's `open_toner_units` grows by that order's `quantity` and the contract's `consumables_committed_cents` grows by that order's committed value."

        Design: Corner/complexity_layers/rate_threshold_triggers_toner_reorder_fires_at_15_percent_not_16_and_re_arms_after_delivery
        """
        env = _fleet_with_a_reading_just_above_the_threshold()
        set_clock(SECOND_CLOCK)
        read = validate_success(
            _submit_read(env, 5_000, 15, FIRST_CLOCK, SECOND_CLOCK), expected_status=201
        )
        assert_fields(read, status="ACCEPTED", mono_delta=4_000, toner_level_pct=15)

        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_ORDERED")
        assert_fields(device, toner_level_pct=15, pages_since_last_cartridge=5_000)

        orders = list_orders_for_device(env["device_id"])
        assert len(orders) == 1
        assert_fields(
            orders[0],
            status="ORDERED",
            trigger_source="AUTO_THRESHOLD",
            part_type="TONER_BLACK",
            quantity=1,
            unit_price_cents=AUTO_UNIT_PRICE_CENTS,
            committed_cents=AUTO_UNIT_PRICE_CENTS,
            pages_since_last_cartridge_at_order=5_000,
            waste_flagged=False,
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=AUTO_UNIT_PRICE_CENTS,
        )

    def test_delivery_resets_the_watermark_and_the_threshold_re_arms(self):
        """After delivery the counters release and a later 15 percent reading orders again.

        PRD: "Delivery performs `ORDERED → DELIVERED`, stamps `delivered_at` with the logical clock, returns the device's supply dimension `SUPPLY_ORDERED → SUPPLY_OK`, resets the device's `pages_since_last_cartridge` to 0 against the new delivery watermark, releases the commitment by reducing the site's `open_toner_units` by the order's `quantity` and the contract's `consumables_committed_cents` by the order's `committed_cents`, and increments both the order's `version` and the device's `version`."
        PRD: "It is the total of monochrome plus colour pages across the device's accepted readings whose `coverage_end` falls after the `delivered_at` of the device's most recent delivered cartridge order; when no order has ever been delivered for that device, it is simply the device's `lifetime_mono_pages` plus its `lifetime_color_pages`."
        PRD: "The order is then flagged as waste, in the derived `waste_flagged` field, exactly when two things hold together: the device has at least one earlier cartridge order that reached `DELIVERED`, and the snapshotted page count is **strictly less than 3,000 pages**."

        Design: Corner/complexity_layers/rate_threshold_triggers_toner_reorder_fires_at_15_percent_not_16_and_re_arms_after_delivery
        """
        env = _fleet_with_the_threshold_order_open()
        delivered = validate_success(
            api_client.deliver_consumable_order(env["order"]["id"], env["tech_headers"])
        )
        assert_fields(delivered, status="DELIVERED")

        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_OK")
        assert_fields(device, pages_since_last_cartridge=0, toner_level_pct=15)
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)

        # The threshold is armed again: a further 3,000 pages at 15 percent order once more.
        set_clock(THIRD_CLOCK)
        read = validate_success(
            _submit_read(env, 8_000, 15, SECOND_CLOCK, THIRD_CLOCK), expected_status=201
        )
        assert_fields(read, status="ACCEPTED", mono_delta=3_000)

        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_ORDERED")
        assert_fields(
            device, pages_since_last_cartridge=3_000, lifetime_mono_pages=8_000
        )
        assert len(list_orders_for_device(env["device_id"])) == 2
        open_orders = list_orders_for_device(env["device_id"], status="ORDERED")
        assert len(open_orders) == 1
        assert open_orders[0]["id"] != env["order"]["id"]
        assert_fields(
            open_orders[0],
            trigger_source="AUTO_THRESHOLD",
            quantity=1,
            unit_price_cents=AUTO_UNIT_PRICE_CENTS,
            pages_since_last_cartridge_at_order=3_000,
            waste_flagged=False,
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=AUTO_UNIT_PRICE_CENTS,
        )
        assert_fields(fetch_consumable_order(env["order"]["id"]), status="DELIVERED")


SECOND_READ_MONO_PAGES = 2_000
SECOND_READ_CENTS = 1_875


def _fleet_with_an_accepted_reading_that_ordered_toner():
    """One accepted reading of 3,000 pages at 10 percent toner, so an order stands."""
    env = _metered_fleet()
    env["read"] = get_success_data(_submit_read(env, ACTUAL_MONO_PAGES, 10))
    env["order"] = open_order_for_device(env["device_id"])
    return env


def _fleet_after_the_reading_was_voided():
    """The same fleet once the reading has been withdrawn and every counter reverted."""
    env = _fleet_with_an_accepted_reading_that_ordered_toner()
    env["void"] = get_success_data(
        api_client.void_meter_read(
            env["read"]["id"], void_read_payload(voided_reason="WRONG_DEVICE"), OPS
        )
    )
    return env


class TestDerivedCountersHoldThroughCreateVoidAndClose:
    """Counters rise on acceptance, revert exactly on a void, and settle at close."""

    def test_acceptance_raises_every_counter_in_the_chain_at_once(self):
        """One intake call writes the reading, the device, the order and both parents.

        PRD: "The second hop writes the device: `last_accepted_mono_meter` and `last_accepted_color_meter` take the submitted absolute values, `last_read_at` takes the reading's `coverage_end`, `toner_level_pct` takes the reading's reported level, `lifetime_mono_pages` grows by `mono_delta`, `lifetime_color_pages` grows by `color_delta`, `pages_since_last_cartridge` grows by the sum of the two deltas, and the device's `version` increments."
        PRD: "The fourth hop is caused by the third: if a cartridge order was created, the hosting site's `open_toner_units` grows by that order's `quantity` and the contract's `consumables_committed_cents` grows by that order's committed value."
        PRD: "`consumables_committed_cents` is the total committed value of the contract's cartridge orders that are still open, that is, whose `status` is `ORDERED`."

        Design: Corner/complexity_layers/derived_field_reconciliation_counters_hold_after_create_after_void_and_after_close
        """
        env = _metered_fleet()
        read = validate_success(
            _submit_read(env, ACTUAL_MONO_PAGES, 10), expected_status=201
        )
        assert_fields(read, status="ACCEPTED", mono_delta=ACTUAL_MONO_PAGES, color_delta=0)

        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_ORDERED")
        assert_fields(
            device,
            last_accepted_mono_meter=ACTUAL_MONO_PAGES,
            last_accepted_color_meter=0,
            last_read_at=MID_PERIOD_COVERAGE_END,
            lifetime_mono_pages=ACTUAL_MONO_PAGES,
            lifetime_color_pages=0,
            pages_since_last_cartridge=ACTUAL_MONO_PAGES,
            toner_level_pct=10,
        )

        orders = list_orders_for_device(env["device_id"])
        assert len(orders) == 1
        assert_fields(
            orders[0],
            status="ORDERED",
            trigger_source="AUTO_THRESHOLD",
            quantity=1,
            committed_cents=AUTO_UNIT_PRICE_CENTS,
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=AUTO_UNIT_PRICE_CENTS,
        )
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)

    def test_voiding_walks_the_same_chain_backwards_to_the_pre_operation_values(self):
        """Withdrawing the reading zeroes its deltas and releases both parent counters.

        PRD: "the general rule is that derived counters are never left stale, and compensating operations (voiding a reading, cancelling an order, cancelling a ticket) must walk the same chain backwards so that reverted counters land exactly on their pre-operation values."
        PRD: "The device's `last_accepted_mono_meter`, `last_accepted_color_meter` and `last_read_at` revert to the values carried by the device's remaining accepted reading with the greatest `coverage_end` (tie broken by `created_at`), or to 0, 0 and null when no accepted reading remains."
        PRD: "The reading's own `mono_delta` and `color_delta` are zeroed, its `status` becomes `VOID` and its `voided_reason` is recorded."
        PRD: "The device's `toner_level_pct` reverts to the `toner_level_pct` of that same remaining accepted reading, or to 100 when none remains."
        PRD: "A third hop follows from that cancellation: the site's `open_toner_units` and the contract's `consumables_committed_cents` both fall by the cancelled order's `quantity` and committed value respectively."

        Design: Corner/complexity_layers/derived_field_reconciliation_counters_hold_after_create_after_void_and_after_close
        """
        env = _fleet_with_an_accepted_reading_that_ordered_toner()
        voided = validate_success(
            api_client.void_meter_read(
                env["read"]["id"], void_read_payload(voided_reason="WRONG_DEVICE"), OPS
            )
        )
        assert_fields(
            voided,
            status="VOID",
            voided_reason="WRONG_DEVICE",
            mono_delta=0,
            color_delta=0,
        )

        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_OK")
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

        assert_fields(
            fetch_consumable_order(env["order"]["id"]),
            status="CANCELLED",
            cancel_reason="READ_VOIDED",
        )
        assert list_orders_for_device(env["device_id"], status="ORDERED") == []
        assert_fields(fetch_site(env["site_id"]), open_toner_units=0)
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)
        assert_fields(fetch_billing_period(env["period_id"]), exception_open_count=0)

    def test_the_close_bills_only_what_survived_and_settles_the_contract_counters(self):
        """A later reading rebuilds the counters and the final statement bills just it.

        PRD: "Only readings assigned to the period with `status` `ACCEPTED` contribute anything; readings in `PENDING_VALIDATION`, `EXCEPTION` or `VOID` contribute nothing at all."
        PRD: "The period then moves `OPEN → SWEPT` (or `SWEPT → SWEPT` on a re-run), its `sweep_run_count` increases by 1 and its `version` increments."
        PRD: "Closing creates the final statement, sets `status` to `CLOSED` and `final_total_cents` to the statement's `total_cents`, and then cascades onto the contract: `lifetime_billed_cents` grows by the statement's `total_cents`, and `true_up_balance_cents` grows by the period's `final_total_cents` less its `provisional_total_cents`"
        PRD: "`true_up_balance_cents` is the running sum, across closed periods, of the difference between each period's final statement total and its provisional statement total; a period that never had a provisional projection contributes exactly zero to that balance rather than contributing its full final total."

        Design: Corner/complexity_layers/derived_field_reconciliation_counters_hold_after_create_after_void_and_after_close
        """
        env = _fleet_after_the_reading_was_voided()
        set_clock(THIRD_CLOCK)
        read = validate_success(
            _submit_read(
                env, SECOND_READ_MONO_PAGES, 55, MID_PERIOD_COVERAGE_END, THIRD_CLOCK
            ),
            expected_status=201,
        )
        assert_fields(read, status="ACCEPTED", mono_delta=SECOND_READ_MONO_PAGES)

        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_OK")
        assert_fields(
            device,
            last_accepted_mono_meter=SECOND_READ_MONO_PAGES,
            last_read_at=THIRD_CLOCK,
            lifetime_mono_pages=SECOND_READ_MONO_PAGES,
            pages_since_last_cartridge=SECOND_READ_MONO_PAGES,
            toner_level_pct=55,
        )
        # The cancelled order is the only one on the device, and it commits nothing.
        assert len(list_orders_for_device(env["device_id"])) == 1
        assert_fields(fetch_contract(env["contract_id"]), consumables_committed_cents=0)

        run_sweep(env["period_id"])
        period = fetch_billing_period(env["period_id"])
        assert_fields(
            period, status="SWEPT", sweep_run_count=1, exception_open_count=0
        )

        set_clock(PERIOD_END, headers=BA)
        final = validate_success(
            api_client.close_billing_period(env["period_id"], BA), expected_status=201
        )
        assert_fields(
            final,
            variant="FINAL",
            projection_basis="ACTUAL",
            mono_pages_billed=SECOND_READ_MONO_PAGES,
            color_pages_billed=0,
            usage_subtotal_cents=SECOND_READ_CENTS,
            shortfall_pages=0,
            shortfall_cents=0,
            waste_penalty_cents=0,
            total_cents=SECOND_READ_CENTS,
        )

        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="CLOSED",
            final_total_cents=SECOND_READ_CENTS,
            provisional_total_cents=None,
        )
        assert_fields(
            fetch_contract(env["contract_id"]),
            lifetime_billed_cents=SECOND_READ_CENTS,
            true_up_balance_cents=0,
        )

        lines, _ = validate_paginated(
            api_client.list_statement_lines(final["id"], BA)
        )
        assert len(lines) == 1
        assert_fields(
            lines[0],
            device_id=env["device_id"],
            page_class="MONO",
            pages=SECOND_READ_MONO_PAGES,
            rate_micro_dollars_per_page=9_375,
            amount_cents=SECOND_READ_CENTS,
        )


class TestEveryCascadeIsImmediatelyReadable:
    """What a write reports about itself is what the very next read reports."""

    def test_the_acceptance_cascade_is_complete_before_the_call_returns(self):
        """The intake response and the follow-up reads of all four hops agree.

        PRD: "A single meter-reading acceptance, for example, first writes the reading, then writes the device's counters, then may move the device's supply dimension and create a cartridge order, then adjusts the hosting site's open-cartridge tally and the contract's committed-spend counter — four hops from one call."
        PRD: "Each affected row's `version` increments and `updated_at` refreshes on the hop that touches it."
        PRD: "From `SUPPLY_LOW` the system immediately attempts to raise the order within the same acceptance."
        PRD: "The first hop writes the reading: `status` `ACCEPTED`, the two deltas, `exception_reason` back to `NONE`."

        Design: Corner/consistency_model/immediate_consistency_every_cascade_is_readable_in_the_same_response_and_the_next_read
        """
        env = _metered_fleet()
        read = validate_success(
            _submit_read(env, ACTUAL_MONO_PAGES, 10), expected_status=201
        )
        # The creating response already reports the first hop in full.
        assert_fields(
            read,
            status="ACCEPTED",
            source="AUTOMATED",
            exception_reason="NONE",
            mono_delta=ACTUAL_MONO_PAGES,
            color_delta=0,
            toner_level_pct=10,
            device_id=env["device_id"],
            billing_period_id=env["period_id"],
        )

        # Reading the same row back changes nothing about it.
        assert_fields(
            fetch_meter_read(read["id"]),
            status="ACCEPTED",
            source="AUTOMATED",
            mono_delta=ACTUAL_MONO_PAGES,
            color_delta=0,
        )

        # Hops two, three and four are all visible on the first subsequent read.
        device = fetch_device(env["device_id"])
        assert_device_dimensions(device, "ACTIVE", "SUPPLY_ORDERED")
        assert_fields(
            device,
            last_accepted_mono_meter=ACTUAL_MONO_PAGES,
            last_read_at=read["coverage_end"],
            lifetime_mono_pages=ACTUAL_MONO_PAGES,
            pages_since_last_cartridge=ACTUAL_MONO_PAGES,
            toner_level_pct=10,
        )
        assert device["version"] > 1

        orders = list_orders_for_device(env["device_id"], status="ORDERED")
        assert len(orders) == 1
        assert_fields(
            orders[0],
            trigger_source="AUTO_THRESHOLD",
            quantity=1,
            committed_cents=AUTO_UNIT_PRICE_CENTS,
            device_id=env["device_id"],
        )
        assert_fields(fetch_site(env["site_id"]), open_toner_units=1)
        assert_fields(
            fetch_contract(env["contract_id"]),
            consumables_committed_cents=AUTO_UNIT_PRICE_CENTS,
        )

    def test_the_sweep_and_the_close_report_the_state_the_next_read_finds(self):
        """Sweep and close both return their own effects, and the parents match at once.

        PRD: "The period then moves `OPEN → SWEPT` (or `SWEPT → SWEPT` on a re-run), its `sweep_run_count` increases by 1 and its `version` increments."
        PRD: "Closing creates the final statement, sets `status` to `CLOSED` and `final_total_cents` to the statement's `total_cents`, and then cascades onto the contract: `lifetime_billed_cents` grows by the statement's `total_cents`, and `true_up_balance_cents` grows by the period's `final_total_cents` less its `provisional_total_cents`"
        PRD: "Creating a new resource returns HTTP 201; every other successful operation, including all state transitions, all reads and all list queries, returns HTTP 200."

        Design: Corner/consistency_model/immediate_consistency_every_cascade_is_readable_in_the_same_response_and_the_next_read
        """
        env = _fleet_with_one_accepted_reading()
        swept = validate_success(api_client.run_meter_sweep(env["period_id"], OPS))
        assert_fields(swept, status="SWEPT", sweep_run_count=1, exception_open_count=0)
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="SWEPT",
            sweep_run_count=1,
            exception_open_count=0,
            final_total_cents=None,
        )

        set_clock(PERIOD_END, headers=BA)
        final = validate_success(
            api_client.close_billing_period(env["period_id"], BA), expected_status=201
        )
        assert_fields(
            final,
            variant="FINAL",
            projection_basis="ACTUAL",
            mono_pages_billed=ACTUAL_MONO_PAGES,
            usage_subtotal_cents=ACTUAL_CENTS,
            total_cents=ACTUAL_CENTS,
            billing_period_id=env["period_id"],
        )

        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="CLOSED",
            final_total_cents=ACTUAL_CENTS,
        )
        assert_fields(
            fetch_contract(env["contract_id"]),
            lifetime_billed_cents=ACTUAL_CENTS,
            true_up_balance_cents=0,
        )
        statements, meta = _statements_for_period(env["period_id"])
        assert meta["total_count"] == 1
        assert statements[0]["id"] == final["id"]
