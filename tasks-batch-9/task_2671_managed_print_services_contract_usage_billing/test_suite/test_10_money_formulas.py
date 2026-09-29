"""Money formulas whose answer depends on the order the arithmetic is performed in.

Three pinned calculations live here: the response-time credit's nested min/max
layers, the end-of-contract settlement waterfall whose fee discount is keyed on
the subtotal that excludes the fee, and the statement subtotal that rounds every
line before summing rather than after.
"""

import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    adjust_part_stock,
    api_client,
    assert_fields,
    assert_lines_sum_to_usage_subtotal,
    assert_settlement_waterfall,
    assert_statement_total_is_consistent,
    close_period,
    create_ticket,
    dispatch_ticket,
    fetch_billing_period,
    fetch_contract,
    fetch_device,
    fetch_part_stock,
    fetch_statement_lines,
    fetch_technician,
    get_success_data,
    make_field_technician_headers,
    run_sweep,
    set_clock,
    setup_print_environment,
    setup_removal_order,
    submit_automated_read,
    validate_paginated,
    validate_success,
)

BA = TEST_USERS["billing_analyst_headers"]

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"


def _instant(value: str) -> datetime.datetime:
    """Parse an ISO 8601 UTC instant regardless of fractional-second formatting."""
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# The response-time credit
# ---------------------------------------------------------------------------
SLA_CONTRACT = {
    "customer_name": "Cedar Legal",
    "term_months": 36,
    "included_service_scope": "BASIC",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 48_000,
    "response_sla_hours_critical": 4,
    "response_sla_hours_standard": 24,
    "labor_rate_cents_per_hour": 9_500,
    "early_termination_fee_cents": 0,
}
FUSER_SKU = "FUSER-9"
TICKET_OPENED_AT = "2026-08-05T00:00:00Z"
HOLD_STARTED_AT = "2026-08-05T01:00:00Z"
RESOLVED_AT = "2026-08-06T05:00:00Z"


def _critical_ticket_held_for_parts(arrival_clock, included_service_scope="BASIC"):
    """A CRITICAL ticket detoured through PARTS_HOLD and standing ONSITE.

    The ticket opens at 2026-08-05T00:00:00Z so its four-hour critical deadline
    falls at 04:00; the hold starts at 01:00 and ends at ``arrival_clock``.
    """
    env = setup_print_environment(
        contract=dict(SLA_CONTRACT, included_service_scope=included_service_scope),
        mono_tiers=((1, 1, None, 9_375),),
        site={"name": "HQ Floor 3", "address_region": "NE-01", "toner_unit_cap": 4},
        devices=1,
        technician={"full_name": "Tess Rowan", "home_region": "NE-01", "skill_level": "L3"},
        clock=TICKET_OPENED_AT,
    )
    tech = make_field_technician_headers(env["technician_id"])
    ticket = create_ticket(
        env["device_id"],
        env["site_id"],
        severity="CRITICAL",
        symptom_code="FUSER-JAM",
        part_sku=FUSER_SKU,
    )
    dispatch_ticket(
        ticket["id"],
        env["technician_id"],
        "2026-08-05T01:00:00Z",
        "2026-08-05T03:00:00Z",
    )

    set_clock(HOLD_STARTED_AT)
    get_success_data(api_client.put_service_ticket_on_parts_hold(ticket["id"], tech))
    adjust_part_stock(env["site_id"], FUSER_SKU, 1)
    set_clock(arrival_clock)
    get_success_data(api_client.arrive_onsite(ticket["id"], tech))

    env["ticket_id"] = ticket["id"]
    env["tech_headers"] = tech
    return env


class TestResponseTimeCreditFormula:
    """One CRITICAL ticket, four interacting inputs, two nested min/max layers."""

    def test_parts_hold_excusal_then_four_hour_steps_then_critical_doubling(self, api):
        """25 late hours, 12 of them excused by a 20-hour hold, doubled to a 40 percent factor.

        PRD: "First, `hours_late`: the number of hours between `respond_by` and
        `responded_at`, rounded up to a whole hour, floored at zero so that a
        ticket resolved on or before its deadline records exactly 0."
        PRD: "Step one: the excused portion of the lateness is the smaller of
        `hours_late` and the amount by which `parts_hold_hours` exceeds an 8-hour
        parts grace allowance, that excess itself floored at zero — so a hold of 8
        hours or less excuses nothing, and a 13-hour hold excuses at most 5 hours
        of lateness."
        PRD: "Step three: otherwise the billable late hours are divided by a 4-hour
        credit step and rounded **up** to a whole step, that step count is
        multiplied by 5 percent, and the product is doubled when `severity` is
        `CRITICAL` and left as it is when `severity` is `STANDARD`; the resulting
        factor is then capped at 50 percent."
        PRD: "Step four: `sla_credit_cents` is the contract's
        `monthly_service_fee_cents` multiplied by that capped factor, rounded half
        up to a whole cent once, and finally capped at 25,000 cents — $250 — per
        ticket."

        Design: Difficulty/combinatorial_formula/sla_credit_nested_min_max_with_parts_hold_excusal_and_critical_doubling
        """
        env = _critical_ticket_held_for_parts("2026-08-05T21:00:00Z")
        set_clock(RESOLVED_AT)

        ticket = validate_success(
            api.resolve_service_ticket(env["ticket_id"], {"labor_hours": 3.5}, env["tech_headers"]),
            200,
        )

        assert_fields(
            ticket,
            status="RESOLVED",
            severity="CRITICAL",
            hours_late=25,
            parts_hold_hours=20,
            sla_credit_cents=19_200,
        )
        assert _instant(ticket["respond_by"]) == _instant("2026-08-05T04:00:00Z"), (
            f"respond_by must be four hours after opened_at, got {ticket['respond_by']}"
        )
        assert _instant(ticket["responded_at"]) == _instant(RESOLVED_AT), (
            f"responded_at must be stamped from the logical clock, got {ticket['responded_at']}"
        )

    def test_hold_of_exactly_eight_hours_excuses_nothing_and_the_factor_caps_at_fifty_percent(
        self, api
    ):
        """A hold at the grace allowance excuses nothing, so 7 steps cap the factor at 50 percent.

        PRD: "Step one: the excused portion of the lateness is the smaller of
        `hours_late` and the amount by which `parts_hold_hours` exceeds an 8-hour
        parts grace allowance, that excess itself floored at zero — so a hold of 8
        hours or less excuses nothing, and a 13-hour hold excuses at most 5 hours
        of lateness."
        PRD: "Step three: otherwise the billable late hours are divided by a 4-hour
        credit step and rounded **up** to a whole step, that step count is
        multiplied by 5 percent, and the product is doubled when `severity` is
        `CRITICAL` and left as it is when `severity` is `STANDARD`; the resulting
        factor is then capped at 50 percent."

        Design: Difficulty/combinatorial_formula/sla_credit_nested_min_max_with_parts_hold_excusal_and_critical_doubling
        """
        env = _critical_ticket_held_for_parts("2026-08-05T09:00:00Z")
        set_clock(RESOLVED_AT)

        ticket = validate_success(
            api.resolve_service_ticket(env["ticket_id"], {"labor_hours": 3.5}, env["tech_headers"]),
            200,
        )

        assert_fields(
            ticket,
            status="RESOLVED",
            hours_late=25,
            parts_hold_hours=8,
            sla_credit_cents=24_000,
        )

    @pytest.mark.parametrize(
        "included_service_scope, expected_labor_cents",
        [("BASIC", 38_000), ("FULL", 0)],
    )
    def test_labour_charge_rounds_the_hours_up_before_multiplying_the_rate(
        self, api, included_service_scope, expected_labor_cents
    ):
        """3.5 reported hours become 4 whole hours at 9,500 cents under BASIC, and nothing under FULL.

        PRD: "Second, `labor_cents`: exactly 0 whenever the contract's
        `included_service_scope` is `FULL`, and otherwise the reported
        `labor_hours` **rounded up to a whole number of hours first** and then
        multiplied by the contract's `labor_rate_cents_per_hour` — the rounding
        happens before the multiplication, never after."
        PRD: "Under `FULL`, break/fix labour sits inside the cost-per-page envelope
        and is never billed as a separate line — the labour charge on every ticket
        of that contract is exactly zero cents regardless of the hours reported."

        Design: Difficulty/combinatorial_formula/sla_credit_nested_min_max_with_parts_hold_excusal_and_critical_doubling
        """
        env = _critical_ticket_held_for_parts(
            "2026-08-05T21:00:00Z", included_service_scope=included_service_scope
        )
        set_clock(RESOLVED_AT)

        ticket = validate_success(
            api.resolve_service_ticket(env["ticket_id"], {"labor_hours": 3.5}, env["tech_headers"]),
            200,
        )

        assert_fields(
            ticket,
            status="RESOLVED",
            labor_cents=expected_labor_cents,
            sla_credit_cents=19_200,
        )
        assert_fields(fetch_device(env["device_id"]), lifecycle_state="ACTIVE")
        assert_fields(fetch_technician(env["technician_id"]), open_dispatch_count=0)
        assert_fields(fetch_part_stock(env["site_id"], FUSER_SKU), on_hand_qty=0)


# ---------------------------------------------------------------------------
# The end-of-contract settlement waterfall
# ---------------------------------------------------------------------------
SETTLEMENT_CONTRACT = {
    "customer_name": "Fjord Insurance",
    "term_months": 36,
    "included_service_scope": "FULL",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 90_000,
    "response_sla_hours_critical": 4,
    "response_sla_hours_standard": 24,
    "labor_rate_cents_per_hour": 9_500,
    "early_termination_fee_cents": 480_000,
}
COLLECTION_AT = "2026-08-20T00:00:00Z"
SANITIZE_CERT = "CERT-2026-08-20-A"


def _sanitized_two_device_fleet(unbilled_mono_pages, sanitization_method="CRYPTO_ERASE"):
    """Two removed devices, one still-open period holding the unbilled pages.

    The MONO entry rate is 9,375 micro-dollars per page, the contract was created
    against the 2026-08-01T00:00:00Z clock default with a 36-month term, and the
    billing period runs to 2026-09-01 so it may legitimately stay OPEN.
    """
    env = setup_print_environment(
        contract=SETTLEMENT_CONTRACT,
        mono_tiers=((1, 1, None, 9_375),),
        site={"name": "HQ Floor 3", "address_region": "NE-01"},
        devices=2,
        period=(PERIOD_START, PERIOD_END),
        clock="2026-08-10T00:00:00Z",
    )
    submit_automated_read(
        env["device_ids"][0],
        env["period_id"],
        mono_meter=unbilled_mono_pages,
        toner_level_pct=55,
        coverage_start=PERIOD_START,
        coverage_end="2026-08-09T00:00:00Z",
    )

    order = setup_removal_order(env["contract_id"], COLLECTION_AT, stage="SCHEDULED")
    tech = make_field_technician_headers(env["technician_id"])
    set_clock(COLLECTION_AT)
    get_success_data(api_client.collect_removal_order(order["id"], tech))
    get_success_data(
        api_client.sanitize_removal_order(
            order["id"],
            {
                "sanitization_method": sanitization_method,
                "sanitization_certificate_ref": SANITIZE_CERT,
            },
            tech,
        )
    )
    env["removal_order_id"] = order["id"]
    return env


class TestSettlementWaterfall:
    """The sanitization fee's discount tier is keyed on gross, which excludes the fee."""

    def test_gross_just_below_the_threshold_leaves_the_sanitization_fee_undiscounted(self, api):
        """Gross lands on 495,000 cents, so the 10 percent volume discount does not apply.

        PRD: "The settlement figures are computed in a **pinned waterfall**, and
        the order matters because the sanitization fee's discount tier is keyed on
        a subtotal that excludes the fee itself — which is how the apparent
        circularity is resolved."
        PRD: "`gross_settlement_cents` is `unbilled_pages_charge_cents` plus
        `early_termination_fee_applied_cents` **minus**
        `device_residual_credit_cents`. It deliberately excludes the sanitization
        fee."
        PRD: "The undiscounted sanitization base is 7,500 cents — $75 per asset —
        multiplied by the order's `device_count`. A volume discount of 10 percent
        applies when `gross_settlement_cents` is at or above 500,000 cents, that is
        at or above $5,000; below that threshold the discount is zero.
        `sanitization_fee_cents` is the base multiplied by one less the discount
        fraction, rounded half up to a whole cent **once**, after the discount
        multiplication."
        PRD: "`net_settlement_cents` is `gross_settlement_cents` plus
        `sanitization_fee_cents`, and it is the amount invoiced at settlement."

        Design: Difficulty/combinatorial_formula/settlement_sanitization_fee_discount_keyed_on_gross_not_net
        """
        env = _sanitized_two_device_fleet(41_600)

        order = validate_success(api.settle_removal_order(env["removal_order_id"], BA), 200)

        assert_fields(
            order,
            status="SETTLED",
            device_count=2,
            unbilled_pages_charge_cents=39_000,
            early_termination_fee_applied_cents=480_000,
            device_residual_credit_cents=24_000,
            gross_settlement_cents=495_000,
            sanitization_fee_cents=15_000,
            net_settlement_cents=510_000,
        )
        assert_settlement_waterfall(order)
        assert _instant(order["settled_at"]) == _instant(COLLECTION_AT), (
            f"settled_at must be stamped from the logical clock, got {order['settled_at']}"
        )

    def test_gross_above_the_threshold_discounts_the_sanitization_fee_by_ten_percent(self, api):
        """The same fleet with 48,000 unbilled pages pushes gross to 501,000 and earns the discount.

        PRD: "The undiscounted sanitization base is 7,500 cents — $75 per asset —
        multiplied by the order's `device_count`. A volume discount of 10 percent
        applies when `gross_settlement_cents` is at or above 500,000 cents, that is
        at or above $5,000; below that threshold the discount is zero.
        `sanitization_fee_cents` is the base multiplied by one less the discount
        fraction, rounded half up to a whole cent **once**, after the discount
        multiplication."
        PRD: "`unbilled_pages_charge_cents` is the monochrome pages multiplied by
        the `MONO` entry rate (the `rate_micro_dollars_per_page` of the contract's
        `tier_index` 1 `MONO` row, taken as 0 when absent), divided by 10,000 and
        rounded half up to a whole cent, plus the colour pages multiplied by the
        equivalent `COLOR` entry rate, divided by 10,000 and rounded half up to a
        whole cent."

        Design: Difficulty/combinatorial_formula/settlement_sanitization_fee_discount_keyed_on_gross_not_net
        """
        env = _sanitized_two_device_fleet(48_000)

        order = validate_success(api.settle_removal_order(env["removal_order_id"], BA), 200)

        assert_fields(
            order,
            status="SETTLED",
            unbilled_pages_charge_cents=45_000,
            device_residual_credit_cents=24_000,
            gross_settlement_cents=501_000,
            sanitization_fee_cents=13_500,
            net_settlement_cents=514_500,
        )
        assert_settlement_waterfall(order)

    def test_a_still_running_open_period_settles_its_accepted_pages_as_unbilled(self, api):
        """The August period may stay OPEN, and its accepted pages become the unbilled charge.

        PRD: "It requires the contract to be in `TERMINATING`, and it requires that
        every billing period of the contract whose `period_end` is at or before the
        logical clock has `status` `CLOSED` — a period that is still genuinely
        running may remain `OPEN`, and its accepted pages settle as unbilled —
        failing which the request reports `ERR_SETTLEMENT_PERIOD_OPEN`."
        PRD: "The unbilled readings are every reading with `status` `ACCEPTED` on a
        device of the contract whose billing period is still `OPEN`, `SWEPT` or
        `PROVISIONAL` — that is, any accepted page no final statement has yet
        billed."
        PRD: "Settlement stamps `settled_at` from the logical clock, increments the
        order's `version`, and cascades the contract `TERMINATING → CLOSED` with a
        contract `version` increment."

        Design: Difficulty/combinatorial_formula/settlement_sanitization_fee_discount_keyed_on_gross_not_net
        """
        env = _sanitized_two_device_fleet(41_600)

        order = validate_success(api.settle_removal_order(env["removal_order_id"], BA), 200)

        assert_fields(order, unbilled_pages_charge_cents=39_000)
        assert_fields(fetch_billing_period(env["period_id"]), status="OPEN")
        assert_fields(fetch_contract(env["contract_id"]), status="CLOSED", active_device_count=0)
        for device_id in env["device_ids"]:
            assert_fields(fetch_device(device_id), lifecycle_state="REMOVED")


# ---------------------------------------------------------------------------
# The statement subtotal: round every line, then sum the lines
# ---------------------------------------------------------------------------
ROUNDING_CONTRACT = {
    "customer_name": "Halden Clinic",
    "term_months": 24,
    "included_service_scope": "FULL",
    "minimum_mono_pages_per_period": 0,
    "minimum_color_pages_per_period": 0,
    "monthly_service_fee_cents": 60_000,
    "response_sla_hours_critical": 4,
    "response_sla_hours_standard": 24,
    "labor_rate_cents_per_hour": 9_000,
    "early_termination_fee_cents": 0,
}
HALF_CENT_RATE = 5_000
HALF_CENT_PAGES = (2_501, 2_503, 2_505, 2_507)
READ_AT = "2026-08-15T00:00:00Z"


def _four_devices_each_landing_on_a_half_cent():
    """Four devices whose page counts each price to exactly half a cent over.

    At 5,000 micro-dollars per page a page count of 2,501 prices to 1,250.5
    cents, so every one of the four lines has to round half up on its own. The
    period is swept at ``period_end`` so that closing is legitimate.
    """
    env = setup_print_environment(
        contract=ROUNDING_CONTRACT,
        mono_tiers=((1, 1, None, HALF_CENT_RATE),),
        color_tiers=(),
        site={"name": "Halden Ward B", "address_region": "NE-01"},
        devices=4,
        release_method="BADGE",
        vlan_tag=3_001,
        period=(PERIOD_START, PERIOD_END),
        clock=READ_AT,
    )
    for device_id, pages in zip(env["device_ids"], HALF_CENT_PAGES):
        submit_automated_read(
            device_id,
            env["period_id"],
            mono_meter=pages,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end=READ_AT,
        )
    set_clock(PERIOD_END)
    run_sweep(env["period_id"])
    return env


def _two_colour_devices_landing_on_half_cents():
    """Two colour-capable devices whose four meters each price to a half cent.

    Monochrome counts of 2,501 and 2,503 and colour counts of 1,501 and 1,503 at
    5,000 micro-dollars per page give 1,250.5, 750.5, 1,251.5 and 751.5 cents.
    """
    env = setup_print_environment(
        contract=ROUNDING_CONTRACT,
        mono_tiers=((1, 1, None, HALF_CENT_RATE),),
        color_tiers=((1, 1, None, HALF_CENT_RATE),),
        site={"name": "Halden Ward B", "address_region": "NE-01"},
        devices=[{"color_capable": True}, {"color_capable": True}],
        release_method="BADGE",
        vlan_tag=3_001,
        period=(PERIOD_START, PERIOD_END),
        clock=READ_AT,
    )
    for device_id, mono_pages, color_pages in zip(
        env["device_ids"], (2_501, 2_503), (1_501, 1_503)
    ):
        submit_automated_read(
            device_id,
            env["period_id"],
            mono_meter=mono_pages,
            color_meter=color_pages,
            toner_level_pct=80,
            coverage_start=PERIOD_START,
            coverage_end=READ_AT,
        )
    set_clock(PERIOD_END)
    run_sweep(env["period_id"])
    return env


class TestStatementLineRounding:
    """Four half-cent lines: rounding first gives 5,010 cents, rounding last gives 5,008."""

    def test_the_subtotal_is_the_sum_of_rounded_lines_not_the_rounding_of_a_sum(self, api):
        """10,016 pages priced per line total 5,010 cents, where one late rounding would give 5,008.

        PRD: "Converting pages priced in micro-dollars into cents always uses the
        same discipline: multiply the page count by the rate in micro-dollars,
        divide by 10,000, and round half up to the nearest whole cent."
        PRD: "The statement's `usage_subtotal_cents` is then the sum of the emitted
        lines' `amount_cents`."
        PRD: "The order is pinned: **round each line to whole cents first, then sum
        the lines**."
        PRD: "Accumulating micro-dollars across all lines and rounding once at the
        end produces a different subtotal and is incorrect."
        PRD: "`total_cents` is the `usage_subtotal_cents` plus `shortfall_cents`
        plus `service_labor_cents` plus `waste_penalty_cents`, **minus**
        `sla_credit_cents`."

        Design: Difficulty/combinatorial_formula/statement_lines_rounded_per_line_then_summed_not_summed_then_rounded
        """
        env = _four_devices_each_landing_on_a_half_cent()

        statement = validate_success(api.close_billing_period(env["period_id"], BA), 201)

        assert_fields(
            statement,
            variant="FINAL",
            projection_basis="ACTUAL",
            mono_pages_billed=10_016,
            mono_tier_index=1,
            mono_rate_micro_dollars_per_page=HALF_CENT_RATE,
            usage_subtotal_cents=5_010,
            shortfall_pages=0,
            shortfall_cents=0,
            service_labor_cents=0,
            sla_credit_cents=0,
            waste_penalty_cents=0,
            total_cents=5_010,
        )
        assert statement["usage_subtotal_cents"] != 5_008, (
            "5,008 cents is the sum-then-round answer; the pinned order rounds each line first"
        )
        assert_statement_total_is_consistent(statement)

    def test_every_line_carries_its_own_half_up_amount_in_device_creation_order(self, api):
        """The four MONO lines read 1,251, 1,252, 1,253 and 1,254 cents in device order.

        PRD: "Lines are emitted device by device in ascending order of the device's
        `created_at`, and within each device the monochrome line comes before the
        colour line."
        PRD: "Each `StatementLine` records its parent `statement_id`, the
        `device_id` it prices, the `page_class`, the `pages` it covers, the
        `rate_micro_dollars_per_page` copied from the statement's selected rate for
        that class, and an `amount_cents` computed as the pages multiplied by that
        rate, divided by 10,000, and rounded half up to a whole cent."
        PRD: "A line is emitted only when the device's billable pages for that meter
        are greater than zero; a zero-page meter produces no line at all."

        Design: Difficulty/combinatorial_formula/statement_lines_rounded_per_line_then_summed_not_summed_then_rounded
        """
        env = _four_devices_each_landing_on_a_half_cent()
        statement = close_period(env["period_id"])

        lines, meta = validate_paginated(
            api.list_statement_lines(statement["id"], BA, params={"limit": 100})
        )

        assert meta["total_count"] == 4, (
            f"four monochrome lines and no colour line were expected, got {meta['total_count']}"
        )
        expected = zip(env["device_ids"], HALF_CENT_PAGES, (1_251, 1_252, 1_253, 1_254))
        for line, (device_id, pages, amount_cents) in zip(lines, expected):
            assert_fields(
                line,
                statement_id=statement["id"],
                device_id=device_id,
                page_class="MONO",
                pages=pages,
                rate_micro_dollars_per_page=HALF_CENT_RATE,
                amount_cents=amount_cents,
            )
        assert_lines_sum_to_usage_subtotal(lines, statement)

    def test_each_meter_of_each_device_rounds_separately_before_the_subtotal(self, api):
        """Two devices with four half-cent meters total 4,006 cents, not the 4,004 of a late rounding.

        PRD: "The order is pinned: **round each line to whole cents first, then sum
        the lines**."
        PRD: "Accumulating micro-dollars across all lines and rounding once at the
        end produces a different subtotal and is incorrect."
        PRD: "Lines are emitted device by device in ascending order of the device's
        `created_at`, and within each device the monochrome line comes before the
        colour line."
        PRD: "The ladder is **non-graduated**: the single selected rate applies to
        *every* page of that class for *every* device, and pages are never split
        across bands."

        Design: Difficulty/combinatorial_formula/statement_lines_rounded_per_line_then_summed_not_summed_then_rounded
        """
        env = _two_colour_devices_landing_on_half_cents()

        statement = validate_success(api.close_billing_period(env["period_id"], BA), 201)

        assert_fields(
            statement,
            mono_pages_billed=5_004,
            color_pages_billed=3_004,
            mono_tier_index=1,
            color_tier_index=1,
            mono_rate_micro_dollars_per_page=HALF_CENT_RATE,
            color_rate_micro_dollars_per_page=HALF_CENT_RATE,
            usage_subtotal_cents=4_006,
            total_cents=4_006,
        )
        assert statement["usage_subtotal_cents"] != 4_004, (
            "4,004 cents is what summing micro-dollars across all four lines would give"
        )
        lines = fetch_statement_lines(statement["id"])
        assert [
            (line["device_id"], line["page_class"], line["pages"], line["amount_cents"])
            for line in lines
        ] == [
            (env["device_ids"][0], "MONO", 2_501, 1_251),
            (env["device_ids"][0], "COLOR", 1_501, 751),
            (env["device_ids"][1], "MONO", 2_503, 1_252),
            (env["device_ids"][1], "COLOR", 1_503, 752),
        ], f"lines must be per device, monochrome first, each rounded half up: {lines}"
        assert_lines_sum_to_usage_subtotal(lines, statement)
