"""Statement pricing arithmetic: the input set, the ladder, rounding and the extras.

Every suite here drives the six-step statement algorithm with pinned reading data
and asserts the cent figures the PRD's rounding discipline uniquely determines.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_fields,
    assert_lines_sum_to_usage_subtotal,
    assert_statement_total_is_consistent,
    create_billing_period,
    fetch_billing_period,
    fetch_contract,
    fetch_device,
    fetch_meter_read,
    fetch_statement_lines,
    generate_provisional_statement,
    get_success_data,
    list_orders_for_device,
    make_account_manager_headers,
    make_field_technician_headers,
    open_order_for_device,
    provisional_statement_payload,
    quarterly_review_payload,
    resolve_ticket_payload,
    run_sweep,
    set_clock,
    setup_dispatched_ticket,
    setup_print_environment,
    submit_automated_read,
    sweep_and_close_period,
    validate_error,
    validate_paginated,
    validate_success,
)

BA_HEADERS = TEST_USERS["billing_analyst_headers"]

# A single unbounded MONO band, so tier selection never changes the rate.
FLAT_MONO_TIERS = ((1, 1, None, 9_375),)
# A two-band MONO ladder whose boundary sits at 20,000 pages.
TIERED_MONO_TIERS = ((1, 1, 20_000, 9_375), (2, 20_001, None, 7_333))

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
PERIOD_2_START = "2026-09-01T00:00:00Z"
PERIOD_2_END = "2026-10-01T00:00:00Z"

# 15 elapsed days of a 31-day window: the projection multiplier is 31/15.
MID_PERIOD_CLOCK = "2026-08-16T00:00:00Z"
# 20 elapsed days of the same window: the multiplier drops to 31/20.
LATE_PERIOD_CLOCK = "2026-08-21T00:00:00Z"


def _flat_mono_environment(**overrides):
    """One ACTIVE mono device priced off a flat ladder, plus the August period."""
    params = dict(
        mono_tiers=FLAT_MONO_TIERS,
        period=(PERIOD_START, PERIOD_END),
        clock="2026-08-08T00:00:00Z",
    )
    params.update(overrides)
    return setup_print_environment(**params)


def _deliver_order(order_id, technician_id):
    """Record cartridge delivery as the technician who carried it."""
    return get_success_data(
        api_client.deliver_consumable_order(order_id, make_field_technician_headers(technician_id))
    )


def _period_version(period_id):
    return fetch_billing_period(period_id)["version"]


class TestAcceptedReadsAreTheOnlyPricingInput:
    """One accepted reading and one rolled-back reading over the same device."""

    @staticmethod
    def _one_accepted_and_one_rollback():
        env = _flat_mono_environment()
        env["accepted_read"] = submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=5_000,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-08T00:00:00Z",
        )
        # The counter goes backwards from 5,000 to 3,000, so this reading cannot validate.
        env["rollback_read"] = submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=3_000,
            toner_level_pct=70,
            coverage_start="2026-08-08T00:00:00Z",
            coverage_end="2026-08-15T00:00:00Z",
        )
        set_clock(MID_PERIOD_CLOCK)
        return env

    def test_rolled_back_reading_contributes_no_pages_to_the_projection(self, api):
        """Only the accepted 5,000 pages are projected; the exception adds nothing.

        PRD: "Only readings assigned to the period with `status` `ACCEPTED` contribute
        anything; readings in `PENDING_VALIDATION`, `EXCEPTION` or `VOID` contribute
        nothing at all."
        PRD: "If **either** candidate delta is negative, the reading lands in
        `EXCEPTION` with `exception_reason` `ROLLBACK` — a counter that went backwards
        means the panel was replaced, the wrong asset was read, or the agent is
        confused."
        PRD: "A reading that is not `ACCEPTED` carries a `mono_delta` and a
        `color_delta` of exactly 0 and moves no device counter whatsoever."

        Design: Corner/calculations/input_set_filtering_exception_reads_contribute_no_pages_to_the_projection
        """
        env = self._one_accepted_and_one_rollback()

        response = api.generate_provisional_statement(
            env["period_id"], provisional_statement_payload(_period_version(env["period_id"])), BA_HEADERS
        )

        statement = validate_success(response, 201)
        assert_fields(
            fetch_meter_read(env["accepted_read"]["id"]), status="ACCEPTED", mono_delta=5_000
        )
        assert_fields(
            fetch_meter_read(env["rollback_read"]["id"]),
            status="EXCEPTION",
            exception_reason="ROLLBACK",
            mono_delta=0,
            color_delta=0,
        )
        assert_fields(
            statement,
            variant="PROVISIONAL",
            projection_basis="PROJECTED",
            mono_pages_billed=10_333,
            color_pages_billed=0,
            mono_tier_index=1,
            mono_rate_micro_dollars_per_page=9_375,
            usage_subtotal_cents=9_687,
            shortfall_pages=0,
            shortfall_cents=0,
            waste_penalty_cents=0,
            sla_credit_cents=0,
            total_cents=9_687,
        )
        assert_statement_total_is_consistent(statement)
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="PROVISIONAL",
            provisional_total_cents=9_687,
            exception_open_count=1,
        )

    def test_projection_emits_exactly_one_line_for_the_only_accepted_meter(self, api):
        """The rolled-back reading produces no second line and no colour line.

        PRD: "A line is emitted only when the device's billable pages for that meter
        are greater than zero; a zero-page meter produces no line at all."
        PRD: "The statement's `usage_subtotal_cents` is then the sum of the emitted
        lines' `amount_cents`."

        Design: Corner/calculations/input_set_filtering_exception_reads_contribute_no_pages_to_the_projection
        """
        env = self._one_accepted_and_one_rollback()

        response = api.generate_provisional_statement(
            env["period_id"], provisional_statement_payload(_period_version(env["period_id"])), BA_HEADERS
        )

        statement = validate_success(response, 201)
        lines = fetch_statement_lines(statement["id"])
        assert len(lines) == 1, f"expected exactly 1 statement line, got {len(lines)}: {lines}"
        assert_fields(
            lines[0],
            statement_id=statement["id"],
            device_id=env["device_id"],
            page_class="MONO",
            pages=10_333,
            rate_micro_dollars_per_page=9_375,
            amount_cents=9_687,
        )
        assert_lines_sum_to_usage_subtotal(lines, statement)


class TestWastePenaltyOnlyLandsOnTheFinalVariant:
    """A cartridge reordered after only 500 pages costs $45 — but only at close."""

    @staticmethod
    def _period_with_one_wasted_cartridge():
        env = _flat_mono_environment()
        # First reading drops toner to 10 percent and raises the device's first cartridge.
        submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=2_000,
            toner_level_pct=10,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-08T00:00:00Z",
        )
        first_order = open_order_for_device(env["device_id"])
        set_clock("2026-08-09T00:00:00Z")
        _deliver_order(first_order["id"], env["technician_id"])
        # Second reading reorders after only 500 pages on the delivered cartridge.
        set_clock("2026-08-15T00:00:00Z")
        submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=2_500,
            toner_level_pct=8,
            coverage_start="2026-08-08T00:00:00Z",
            coverage_end="2026-08-14T00:00:00Z",
        )
        set_clock(MID_PERIOD_CLOCK)
        return env

    def test_projection_carries_no_waste_penalty_at_all(self):
        """The mid-period projection prices 5,167 scaled pages and charges no waste.

        PRD: "`waste_penalty_cents` is exactly 0 on the `PROVISIONAL` variant; on the
        `FINAL` variant it is 4,500 cents — a flat $45 per wasted cartridge — multiplied
        by the number of consumable orders belonging to a device of that contract which
        carry `waste_flagged` true, have a `status` other than `CANCELLED`, and were
        created inside the period's half-open window."
        PRD: "Each device's projected pages for a meter are its actual pages for that
        meter multiplied by the period length in days, divided by the elapsed length in
        days, and rounded half up to a whole page."

        Design: Corner/calculations/constants_applied_waste_penalty_is_charged_only_on_the_final_variant
        """
        env = self._period_with_one_wasted_cartridge()

        statement = generate_provisional_statement(env["period_id"])

        assert_fields(
            statement,
            variant="PROVISIONAL",
            mono_pages_billed=5_167,
            usage_subtotal_cents=4_844,
            waste_penalty_cents=0,
            total_cents=4_844,
        )
        assert_statement_total_is_consistent(statement)

    def test_close_adds_the_flat_penalty_for_the_one_flagged_cartridge(self, api):
        """The final statement prices 2,500 actual pages and adds exactly 4,500 cents.

        PRD: "`waste_penalty_cents` is exactly 0 on the `PROVISIONAL` variant; on the
        `FINAL` variant it is 4,500 cents — a flat $45 per wasted cartridge — multiplied
        by the number of consumable orders belonging to a device of that contract which
        carry `waste_flagged` true, have a `status` other than `CANCELLED`, and were
        created inside the period's half-open window."
        PRD: "`total_cents` is the `usage_subtotal_cents` plus `shortfall_cents` plus
        `service_labor_cents` plus `waste_penalty_cents`, **minus** `sla_credit_cents`."

        Design: Corner/calculations/constants_applied_waste_penalty_is_charged_only_on_the_final_variant
        """
        env = self._period_with_one_wasted_cartridge()
        generate_provisional_statement(env["period_id"])
        set_clock(PERIOD_END)

        response = api.close_billing_period(env["period_id"], BA_HEADERS)

        final_statement = validate_success(response, 201)
        delivered = list_orders_for_device(env["device_id"], status="DELIVERED")
        still_open = list_orders_for_device(env["device_id"], status="ORDERED")
        assert len(delivered) == 1, f"expected 1 delivered cartridge, got {delivered}"
        assert len(still_open) == 1, f"expected 1 open cartridge, got {still_open}"
        assert_fields(delivered[0], waste_flagged=False)
        assert_fields(still_open[0], waste_flagged=True, pages_since_last_cartridge_at_order=500)
        assert_fields(
            final_statement,
            variant="FINAL",
            projection_basis="ACTUAL",
            mono_pages_billed=2_500,
            usage_subtotal_cents=2_344,
            service_labor_cents=0,
            waste_penalty_cents=4_500,
            total_cents=6_844,
        )
        assert_statement_total_is_consistent(final_statement)
        assert_fields(
            fetch_billing_period(env["period_id"]), status="CLOSED", final_total_cents=6_844
        )
        assert_fields(fetch_contract(env["contract_id"]), lifetime_billed_cents=6_844)


class TestStatementLineRoundingDiscipline:
    """8 pages at 9,375 micro-dollars is exactly 7.5 cents — the awkward half."""

    @staticmethod
    def _eight_pages_per_device(device_count):
        env = _flat_mono_environment(clock="2026-08-14T00:00:00Z", devices=device_count)
        for device_id in env["device_ids"]:
            submit_automated_read(
                device_id,
                env["period_id"],
                mono_meter=8,
                toner_level_pct=90,
                coverage_start=PERIOD_START,
                coverage_end="2026-08-14T00:00:00Z",
            )
        set_clock(PERIOD_END)
        run_sweep(env["period_id"])
        return env

    def test_a_line_worth_exactly_half_a_cent_rounds_upwards(self, api):
        """7.5 cents becomes 8 cents, never 7.

        PRD: "Converting pages priced in micro-dollars into cents always uses the same
        discipline: multiply the page count by the rate in micro-dollars, divide by
        10,000, and round half up to the nearest whole cent."
        PRD: "Each `StatementLine` records its parent `statement_id`, the `device_id` it
        prices, the `page_class`, the `pages` it covers, the `rate_micro_dollars_per_page`
        copied from the statement's selected rate for that class, and an `amount_cents`
        computed as the pages multiplied by that rate, divided by 10,000, and rounded
        half up to a whole cent."

        Design: Corner/calculations/precision_statement_line_rounds_the_half_cent_upwards
        """
        env = self._eight_pages_per_device(1)

        response = api.close_billing_period(env["period_id"], BA_HEADERS)

        statement = validate_success(response, 201)
        assert_fields(
            statement,
            variant="FINAL",
            mono_pages_billed=8,
            mono_rate_micro_dollars_per_page=9_375,
            usage_subtotal_cents=8,
            total_cents=8,
        )
        lines = fetch_statement_lines(statement["id"])
        assert len(lines) == 1, f"expected exactly 1 statement line, got {len(lines)}: {lines}"
        assert_fields(lines[0], device_id=env["device_id"], pages=8, amount_cents=8)
        assert_fields(fetch_billing_period(env["period_id"]), final_total_cents=8)

    def test_each_line_rounds_before_the_subtotal_sums_them(self, api):
        """Two half-cent lines round to 8 each, so the subtotal is 16 and never 15.

        PRD: "The order is pinned: **round each line to whole cents first, then sum the
        lines**."
        PRD: "Accumulating micro-dollars across all lines and rounding once at the end
        produces a different subtotal and is incorrect."

        Design: Corner/calculations/precision_statement_line_rounds_the_half_cent_upwards
        """
        env = self._eight_pages_per_device(2)
        first_device, second_device = env["device_ids"]

        response = api.close_billing_period(env["period_id"], BA_HEADERS)

        statement = validate_success(response, 201)
        assert_fields(statement, mono_pages_billed=16, usage_subtotal_cents=16, total_cents=16)
        lines = fetch_statement_lines(statement["id"])
        assert len(lines) == 2, f"expected exactly 2 statement lines, got {len(lines)}: {lines}"
        assert_fields(lines[0], device_id=first_device, pages=8, amount_cents=8)
        assert_fields(lines[1], device_id=second_device, pages=8, amount_cents=8)
        assert_lines_sum_to_usage_subtotal(lines, statement)


FULL_SCOPE_CONTRACT = {
    "included_service_scope": "FULL",
    "labor_rate_cents_per_hour": 9_500,
    "monthly_service_fee_cents": 48_000,
}

TICKET_OPENED_CLOCK = "2026-08-10T08:00:00Z"
TICKET_WINDOW_START = "2026-08-10T13:00:00Z"
TICKET_WINDOW_END = "2026-08-10T15:00:00Z"


class TestFullServiceScopeBillsZeroLabor:
    """A FULL envelope swallows break/fix labour, whatever the technician reports."""

    @staticmethod
    def _onsite_ticket_under_full_scope():
        env = setup_dispatched_ticket(
            contract=dict(FULL_SCOPE_CONTRACT),
            mono_tiers=FLAT_MONO_TIERS,
            period=(PERIOD_START, PERIOD_END),
            severity="STANDARD",
            symptom_code="PAPER_JAM",
            clock=TICKET_OPENED_CLOCK,
            window_start=TICKET_WINDOW_START,
            window_end=TICKET_WINDOW_END,
        )
        set_clock(TICKET_WINDOW_START)
        env["ticket"] = get_success_data(
            api_client.arrive_onsite(env["ticket_id"], env["tech_headers"])
        )
        return env

    @pytest.mark.parametrize("labor_hours", [5, 8])
    def test_reported_labor_hours_are_recorded_but_priced_at_zero(self, api, labor_hours):
        """Five or eight hours at 9,500 cents an hour still bills nothing.

        PRD: "Under `FULL`, break/fix labour sits inside the cost-per-page envelope and
        is never billed as a separate line — the labour charge on every ticket of that
        contract is exactly zero cents regardless of the hours reported."
        PRD: "Second, `labor_cents`: exactly 0 whenever the contract's
        `included_service_scope` is `FULL`, and otherwise the reported `labor_hours`
        **rounded up to a whole number of hours first** and then multiplied by the
        contract's `labor_rate_cents_per_hour` — the rounding happens before the
        multiplication, never after."

        Design: Corner/calculations/correct_result_full_service_scope_bills_zero_labor_cents
        """
        env = self._onsite_ticket_under_full_scope()
        assert_fields(fetch_contract(env["contract_id"]), labor_rate_cents_per_hour=9_500)

        response = api.resolve_service_ticket(
            env["ticket_id"], resolve_ticket_payload(labor_hours), env["tech_headers"]
        )

        ticket = validate_success(response, 200)
        assert_fields(
            ticket,
            status="RESOLVED",
            labor_hours=labor_hours,
            labor_cents=0,
            hours_late=0,
            sla_credit_cents=0,
        )
        assert_fields(fetch_device(env["device_id"]), lifecycle_state="ACTIVE")

    def test_the_period_statement_carries_no_service_labor_either(self, api):
        """The resolved ticket lands in the window yet adds zero labour to the close.

        PRD: "The tickets that matter to a period are those with `status` `RESOLVED`,
        belonging to a device of that contract, whose `responded_at` falls inside the
        period's half-open window."
        PRD: "`service_labor_cents` is exactly 0 when the contract's
        `included_service_scope` is `FULL`, and otherwise the sum of `labor_cents`
        across those tickets."

        Design: Corner/calculations/correct_result_full_service_scope_bills_zero_labor_cents
        """
        env = self._onsite_ticket_under_full_scope()
        resolved = get_success_data(
            api_client.resolve_service_ticket(
                env["ticket_id"], resolve_ticket_payload(5), env["tech_headers"]
            )
        )
        assert resolved["labor_cents"] == 0, f"labour must be waived under FULL: {resolved}"
        set_clock("2026-08-14T00:00:00Z")
        submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=5_000,
            toner_level_pct=90,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-14T00:00:00Z",
        )
        set_clock(PERIOD_END)
        run_sweep(env["period_id"])

        response = api.close_billing_period(env["period_id"], BA_HEADERS)

        statement = validate_success(response, 201)
        assert_fields(
            statement,
            variant="FINAL",
            mono_pages_billed=5_000,
            usage_subtotal_cents=4_688,
            service_labor_cents=0,
            sla_credit_cents=0,
            waste_penalty_cents=0,
            total_cents=4_688,
        )
        assert_statement_total_is_consistent(statement)


class TestRegeneratedProjectionSupersedesThenCloseAddsTheFinal:
    """Two projections and one close leave exactly one PROVISIONAL and one FINAL."""

    @staticmethod
    def _period_with_one_early_reading():
        env = _flat_mono_environment()
        submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=5_000,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-08T00:00:00Z",
        )
        set_clock(MID_PERIOD_CLOCK)
        env["first_statement"] = generate_provisional_statement(env["period_id"])
        return env

    def test_regeneration_replaces_the_earlier_projection_outright(self, api):
        """The 31/20 projection overwrites the 31/15 one; the first statement is gone.

        PRD: "Regeneration is a first-class operation: any pre-existing provisional
        statement for that period is **superseded**, meaning it is deleted together with
        all of its lines and replaced by the newly generated one, and
        `provisional_total_cents` is overwritten with the new projection."
        PRD: "Generation drives `OPEN → PROVISIONAL`, `SWEPT → PROVISIONAL` or
        `PROVISIONAL → PROVISIONAL`, sets `provisional_total_cents` to the new statement's
        `total_cents`, and increments the period's `version` by 1."

        Design: Corner/calculations/variant_selection_regenerated_projection_supersedes_and_close_adds_the_final
        """
        env = self._period_with_one_early_reading()
        first_statement = env["first_statement"]
        assert first_statement["total_cents"] == 9_687, (
            f"the 15-day projection must bill 9,687 cents: {first_statement}"
        )
        set_clock(LATE_PERIOD_CLOCK)

        response = api.generate_provisional_statement(
            env["period_id"],
            provisional_statement_payload(_period_version(env["period_id"])),
            BA_HEADERS,
        )

        second_statement = validate_success(response, 201)
        assert second_statement["id"] != first_statement["id"], (
            "regeneration must create a new statement row, not mutate the old one"
        )
        assert_fields(
            second_statement,
            variant="PROVISIONAL",
            projection_basis="PROJECTED",
            mono_pages_billed=7_750,
            mono_rate_micro_dollars_per_page=9_375,
            usage_subtotal_cents=7_266,
            waste_penalty_cents=0,
            total_cents=7_266,
        )
        validate_error(
            api.get_billing_statement(first_statement["id"], BA_HEADERS),
            ApiErrorId.ERR_STATEMENT_NOT_FOUND.value,
            404,
        )
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="PROVISIONAL",
            provisional_total_cents=7_266,
        )
        surviving, _meta = validate_paginated(
            api.list_billing_statements(
                BA_HEADERS,
                params={"billing_period_id": env["period_id"], "variant": "PROVISIONAL"},
            )
        )
        assert [row["id"] for row in surviving] == [second_statement["id"]], (
            f"exactly one provisional statement must survive: {surviving}"
        )

    def test_closing_adds_a_second_statement_priced_on_the_actual_pages(self, api):
        """The FINAL statement joins the surviving projection instead of replacing it.

        PRD: "Every statement records which one it is in `variant` — `PROVISIONAL` or
        `FINAL` — and records the corresponding evidence basis in `projection_basis`,
        which is `PROJECTED` on a provisional statement and `ACTUAL` on a final one."
        PRD: "A **final statement** is issued when a `BillingAnalyst` closes the period,
        which drives `SWEPT → CLOSED` or `PROVISIONAL → CLOSED`; a period still `OPEN` and
        never swept cannot be closed and reports `ERR_PERIOD_INVALID_STATE`."

        Design: Corner/calculations/variant_selection_regenerated_projection_supersedes_and_close_adds_the_final
        """
        env = self._period_with_one_early_reading()
        set_clock(LATE_PERIOD_CLOCK)
        second_statement = get_success_data(
            api_client.generate_provisional_statement(
                env["period_id"],
                provisional_statement_payload(_period_version(env["period_id"])),
                BA_HEADERS,
            )
        )
        set_clock(PERIOD_END)

        response = api.close_billing_period(env["period_id"], BA_HEADERS)

        final_statement = validate_success(response, 201)
        assert_fields(
            final_statement,
            variant="FINAL",
            projection_basis="ACTUAL",
            mono_pages_billed=5_000,
            usage_subtotal_cents=4_688,
            waste_penalty_cents=0,
            total_cents=4_688,
        )
        assert_statement_total_is_consistent(final_statement)
        rows, _meta = validate_paginated(
            api.list_billing_statements(
                BA_HEADERS, params={"billing_period_id": env["period_id"]}
            )
        )
        assert sorted(row["id"] for row in rows) == sorted(
            [second_statement["id"], final_statement["id"]]
        ), f"the period must own exactly the surviving projection and the final: {rows}"
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="CLOSED",
            provisional_total_cents=7_266,
            final_total_cents=4_688,
        )
        assert_fields(fetch_contract(env["contract_id"]), lifetime_billed_cents=4_688)


class TestNonGraduatedBandSelection:
    """20,000 pages bill at 9,375; 20,001 pages bill every page at 7,333."""

    @staticmethod
    def _two_device_fleet_with_a_second_period():
        env = setup_print_environment(
            mono_tiers=TIERED_MONO_TIERS,
            devices=2,
            period=(PERIOD_START, PERIOD_END),
            clock="2026-08-20T00:00:00Z",
        )
        env["period_2_id"] = create_billing_period(
            env["contract_id"], PERIOD_2_START, PERIOD_2_END
        )["id"]
        first_device, second_device = env["device_ids"]
        for device_id, mono_meter in ((first_device, 12_000), (second_device, 8_000)):
            submit_automated_read(
                device_id,
                env["period_id"],
                mono_meter=mono_meter,
                toner_level_pct=60,
                coverage_start=PERIOD_START,
                coverage_end="2026-08-20T00:00:00Z",
            )
        set_clock(PERIOD_END)
        run_sweep(env["period_id"])
        return env

    def test_a_volume_sitting_exactly_on_the_upper_bound_stays_in_the_entry_band(self, api):
        """20,000 pages is inside the 1..20,000 band, so all of it prices at 9,375.

        PRD: "Each volume then selects **one** rate-card row from the rows of that
        contract and `page_class`: the single row whose band contains the volume, where
        the band runs from `from_page` to `to_page` with **both bounds inclusive** and a
        null `to_page` meaning unbounded above."
        PRD: "The contract-level monochrome volume is the sum of every participating
        device's billable monochrome pages, and the contract-level colour volume is the
        sum of every participating device's billable colour pages."

        Design: Corner/calculations/tiered_pricing_non_graduated_band_selection_makes_one_extra_page_cheaper
        """
        env = self._two_device_fleet_with_a_second_period()

        response = api.close_billing_period(env["period_id"], BA_HEADERS)

        statement = validate_success(response, 201)
        assert_fields(
            statement,
            variant="FINAL",
            mono_pages_billed=20_000,
            mono_tier_index=1,
            mono_rate_micro_dollars_per_page=9_375,
            usage_subtotal_cents=18_750,
            shortfall_pages=0,
            shortfall_cents=0,
            total_cents=18_750,
        )
        assert_statement_total_is_consistent(statement)

    def test_one_extra_page_reprices_every_page_and_lowers_the_invoice(self, api):
        """20,001 pages jump the whole fleet to 7,333, so the bigger period bills less.

        PRD: "The ladder is **non-graduated**: the single selected rate applies to
        *every* page of that class for *every* device, and pages are never split across
        bands."
        PRD: "The statement's `usage_subtotal_cents` is then the sum of the emitted
        lines' `amount_cents`."

        Design: Corner/calculations/tiered_pricing_non_graduated_band_selection_makes_one_extra_page_cheaper
        """
        env = self._two_device_fleet_with_a_second_period()
        first_device, second_device = env["device_ids"]
        cheaper_period_id = env["period_2_id"]
        first_statement = get_success_data(
            api_client.close_billing_period(env["period_id"], BA_HEADERS)
        )
        assert first_statement["total_cents"] == 18_750, (
            f"the 20,000-page period must bill 18,750 cents: {first_statement}"
        )
        set_clock("2026-09-20T00:00:00Z")
        for device_id, mono_meter in ((first_device, 24_000), (second_device, 16_001)):
            submit_automated_read(
                device_id,
                cheaper_period_id,
                mono_meter=mono_meter,
                toner_level_pct=50,
                coverage_start=PERIOD_2_START,
                coverage_end="2026-09-20T00:00:00Z",
            )
        set_clock(PERIOD_2_END)
        run_sweep(cheaper_period_id)

        response = api.close_billing_period(cheaper_period_id, BA_HEADERS)

        second_statement = validate_success(response, 201)
        assert_fields(
            second_statement,
            variant="FINAL",
            mono_pages_billed=20_001,
            mono_tier_index=2,
            mono_rate_micro_dollars_per_page=7_333,
            usage_subtotal_cents=14_667,
            total_cents=14_667,
        )
        assert second_statement["total_cents"] < first_statement["total_cents"], (
            "one extra page must make the invoice cheaper under a non-graduated ladder: "
            f"{second_statement['total_cents']} vs {first_statement['total_cents']}"
        )
        lines = fetch_statement_lines(second_statement["id"])
        assert len(lines) == 2, f"expected exactly 2 statement lines, got {len(lines)}: {lines}"
        assert_fields(
            lines[0],
            device_id=first_device,
            page_class="MONO",
            pages=12_000,
            rate_micro_dollars_per_page=7_333,
            amount_cents=8_800,
        )
        assert_fields(
            lines[1],
            device_id=second_device,
            page_class="MONO",
            pages=8_001,
            rate_micro_dollars_per_page=7_333,
            amount_cents=5_867,
        )
        assert_lines_sum_to_usage_subtotal(lines, second_statement)
        assert_fields(fetch_contract(env["contract_id"]), lifetime_billed_cents=33_417)


class TestVolumeTrendReadsTheTwoMostRecentClosedPeriods:
    """4,000 billed pages then 5,000 billed pages is a 25 percent rise."""

    @staticmethod
    def _two_closed_periods_of_rising_volume():
        env = setup_print_environment(
            mono_tiers=FLAT_MONO_TIERS,
            period=(PERIOD_START, PERIOD_END),
            clock="2026-08-20T00:00:00Z",
        )
        env["period_2_id"] = create_billing_period(
            env["contract_id"], PERIOD_2_START, PERIOD_2_END
        )["id"]
        submit_automated_read(
            env["device_id"],
            env["period_id"],
            mono_meter=4_000,
            toner_level_pct=70,
            coverage_start=PERIOD_START,
            coverage_end="2026-08-20T00:00:00Z",
        )
        set_clock(PERIOD_END)
        env["prior_statement"] = sweep_and_close_period(env["period_id"])
        set_clock("2026-09-20T00:00:00Z")
        submit_automated_read(
            env["device_id"],
            env["period_2_id"],
            mono_meter=9_000,
            toner_level_pct=60,
            coverage_start=PERIOD_2_START,
            coverage_end="2026-09-20T00:00:00Z",
        )
        set_clock(PERIOD_2_END)
        env["current_statement"] = sweep_and_close_period(env["period_2_id"])
        return env

    def test_the_trend_divides_the_rise_by_the_prior_period_volume(self, api):
        """The September period is the current one and August the prior one.

        PRD: "Take the contract's closed periods ordered by `period_end` descending, with
        earliest `created_at` breaking ties, and call the first one the current period and
        the second the prior period."
        PRD: "Each period's volume is its `FINAL` statement's `mono_pages_billed` plus
        `color_pages_billed`."
        PRD: "Otherwise it is the current volume less the prior volume, divided by the
        prior volume, multiplied by 100, and rounded half up to two decimal places."
        PRD: "The new review has `status` `DRAFT`, an `authored_by_user_id` stamped from
        the caller's `X-User-ID`, and a null `approved_by_user_id`."

        Design: Corner/calculations/chronological_volume_trend_compares_the_two_most_recent_closed_periods
        """
        env = self._two_closed_periods_of_rising_volume()
        assert_fields(env["prior_statement"], mono_pages_billed=4_000, total_cents=3_750)
        assert_fields(env["current_statement"], mono_pages_billed=5_000, total_cents=4_688)

        response = api.create_quarterly_review(
            quarterly_review_payload(env["contract_id"], "2026-Q3"),
            make_account_manager_headers("am-1"),
        )

        review = validate_success(response, 201)
        assert review["volume_trend_pct"] == pytest.approx(25.0, abs=0.01), (
            f"a 4,000 to 5,000 page rise is a 25 percent trend: {review}"
        )
        assert_fields(
            review,
            status="DRAFT",
            authored_by_user_id="am-1",
            approved_by_user_id=None,
        )

    def test_utilization_from_the_newest_closed_period_downgrades_the_device(self, api):
        """5,000 realized pages against a 20,000 duty cycle is 25 percent — a downgrade.

        PRD: "Each fleet device's utilization is its realized pages from the most recently
        closed period's `FINAL` statement lines divided by its `rated_monthly_duty_cycle`,
        and the comparison is made as an **exact rational** — pages against duty cycle
        scaled by the threshold percentage — never as a rounded decimal, so that a device
        sitting exactly on a boundary lands on the inclusive side."
        PRD: "The classification writes `right_sizing_action` on the device and is
        evaluated in this order: utilization at or below 15 percent yields `CONSOLIDATE`;
        otherwise utilization at or below 40 percent yields `DOWNGRADE`; otherwise
        utilization at or above 90 percent yields `UPGRADE`; otherwise the device yields
        `RETAIN`."
        PRD: "The review then records the four tallies across the fleet in `retain_count`,
        `downgrade_count`, `upgrade_count` and `consolidate_count`, and records
        `refresh_due_device_count` as the sum of `upgrade_count` and `consolidate_count` —
        the devices a refresh plan should touch."

        Design: Corner/calculations/chronological_volume_trend_compares_the_two_most_recent_closed_periods
        """
        env = self._two_closed_periods_of_rising_volume()

        response = api.create_quarterly_review(
            quarterly_review_payload(env["contract_id"], "2026-Q3"),
            make_account_manager_headers("am-1"),
        )

        review = validate_success(response, 201)
        assert_fields(
            review,
            downgrade_count=1,
            retain_count=0,
            upgrade_count=0,
            consolidate_count=0,
            refresh_due_device_count=0,
        )
        assert_fields(
            fetch_device(env["device_id"]), right_sizing_action="DOWNGRADE", refresh_due=False
        )
