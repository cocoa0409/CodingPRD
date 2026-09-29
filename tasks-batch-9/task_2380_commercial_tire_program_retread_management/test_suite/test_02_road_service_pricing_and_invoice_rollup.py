"""Nested road service pricing and the four pinned invoice rollup steps."""

from test_helpers import (
    assert_invoice_rollup_arithmetic,
    assert_sla_pricing,
    entries_of_type,
    fixtures,
    validate_paginated,
    validate_success,
)


def _emergency_call_program():
    """An emergency call on an after-hours night, under an agreement whose
    emergency terms tighten both the response promise and the labour rate."""
    program = fixtures.setup_fleet_program(
        with_agreement=True,
        agreement_overrides={
            "emergency_response_minutes": 90,
            "emergency_labor_rate_cents_per_hour": 13000,
        },
        location_overrides={"road_service_response_minutes_committed": 120},
    )
    program["vehicle"] = fixtures.create_vehicle(program["fleet"]["id"])
    program["technician"] = fixtures.create_technician(program["location"]["id"])
    return program


def _run_capped_emergency_call(program):
    return fixtures.run_completed_call(
        program["fleet"]["id"],
        program["vehicle"]["id"],
        program["location"]["id"],
        program["technician"]["id"],
        reported_at="2026-08-10T04:00:00Z",
        dispatched_at="2026-08-10T04:30:00Z",
        arrived_at="2026-08-10T06:00:00Z",
        closed_at="2026-08-10T07:00:00Z",
        labor_hours=3.5,
        dispatch_miles=240,
        priority="EMERGENCY",
    )


class TestRoadServicePricingCap:
    """The surcharge is the larger of two multipliers, then capped."""

    def test_emergency_after_hours_surcharge_is_capped_at_forty_thousand_cents(
        self, api
    ):
        """PRD §3.6: "The surcharge is one less than that multiplier, multiplied
        by the sum of the base service call charge, the labour charge and the
        mileage charge, rounded half up to whole cents, and then capped at 40000
        cents — four hundred dollars — taking whichever is smaller."
        PRD §3.6: "The multipliers do not stack: an after-hours emergency is
        priced at 1.75, not at 1.75 times 1.35."

        Design: Difficulty/combinatorial_formula/road_service_pricing_nested_max_min_with_cap
        """
        program = _emergency_call_program()

        call = _run_capped_emergency_call(program)

        # base 9500 + labour 13000 * 3.5 = 45500 + mileage 285 * 240 = 68400
        pre_surcharge = 9500 + 45500 + 68400
        assert pre_surcharge == 123400
        assert call["gross_cents"] == 163400, (
            "the uncapped 0.75 surcharge would have been 92550 cents"
        )
        assert call["gross_cents"] - pre_surcharge == 40000, (
            "the surcharge lands exactly on the cap"
        )

    def test_tightened_emergency_commitment_drives_the_sla_credit(self, api):
        """PRD §3.6: "On an `EMERGENCY` call for which an `ACTIVE` national
        agreement covers the UTC date of `reported_at`, the commitment is the
        **smaller** of that location baseline and the agreement's
        `emergency_response_minutes` — the contract can tighten the promise but
        never loosen it."
        PRD §3.6: "`sla_credit_cents` is 20 percent of `gross_cents` rounded half
        up to whole cents when `sla_met` is false, and exactly 0 when `sla_met` is
        true — the fleet is credited a fifth of the call for a missed commitment."

        Design: Difficulty/combinatorial_formula/road_service_pricing_nested_max_min_with_cap
        """
        program = _emergency_call_program()

        call = _run_capped_emergency_call(program)

        assert call["committed_response_minutes"] == 90, (
            "the agreement's 90 minutes beats the location's 120-minute baseline"
        )
        assert call["actual_response_minutes"] == 120
        assert call["sla_met"] is False
        assert call["sla_credit_cents"] == 32680, "20 percent of 163400 cents"
        assert call["invoice_total_cents"] == 130720
        assert_sla_pricing(call)


class TestInvoiceRollupRounding:
    """Per-line rounding, then the credit cap, in the pinned order."""

    def test_tier_discount_is_rounded_per_line_before_it_is_summed(self, api):
        """PRD §3.8: "**First**, for each line, a per-line discount is computed
        as that call's `invoice_total_cents` multiplied by the agreement's
        `tier_discount_pct`, rounded half up to whole cents."
        PRD §3.8: "**Second**, the aggregates: `subtotal_cents` is the sum of the
        lines' `invoice_total_cents`; `discount_cents` is the sum of the
        **already-rounded** per-line discounts; and `net_before_credit_cents` is
        `subtotal_cents` less `discount_cents`."

        Design: Difficulty/combinatorial_formula/invoice_discount_per_line_rounding_order
        """
        program = fixtures.setup_national_account_program(tier_discount_pct=0.125)
        calls = fixtures.setup_two_billable_calls(program)
        assert [c["invoice_total_cents"] for c in calls] == [12820, 16140]

        invoice = validate_success(
            api.create_cross_location_invoice(
                {
                    "fleet_account_id": program["fleet"]["id"],
                    "billing_period_start": "2026-08-01",
                    "billing_period_end": "2026-08-31",
                    "expected_fleet_account_version": fixtures.read_fleet(
                        program["fleet"]["id"], fixtures.CLERK
                    )["version"],
                },
                fixtures.CLERK,
            ),
            expected_status=201,
        )

        assert invoice["line_count"] == 2
        assert invoice["subtotal_cents"] == 28960
        assert invoice["discount_cents"] == 3621, (
            "1603 + 2018 per line, not the 3620 the aggregate would give"
        )
        assert invoice["net_before_credit_cents"] == 25339
        assert invoice["credit_applied_cents"] == 0
        assert invoice["total_cents"] == 25339
        assert_invoice_rollup_arithmetic(invoice)

        for call in calls:
            claimed = fixtures.read_call(call["id"])
            assert claimed["billing_status"] == "INVOICED"
            assert claimed["cross_location_invoice_id"] == invoice["id"]

    def test_a_line_discount_of_exactly_half_a_cent_rounds_up(self, api):
        """PRD §3.8: "Rounding the aggregate instead — taking `subtotal_cents` times
        `tier_discount_pct` and rounding once — is forbidden, because the two answers
        differ by a cent whenever the per-line remainders round up but the aggregate
        remainder does not."
        PRD §3.8: "`line_count` records how many calls the invoice claims."

        Design: Difficulty/combinatorial_formula/invoice_discount_per_line_rounding_order
        """
        program = fixtures.setup_national_account_program(tier_discount_pct=0.125)
        call = fixtures.setup_billable_call(program)
        assert call["invoice_total_cents"] == fixtures.SMALL_LINE_CENTS == 12820

        invoice = fixtures.create_invoice(program["fleet"]["id"])

        assert invoice["line_count"] == 1
        assert invoice["subtotal_cents"] == 12820
        assert invoice["discount_cents"] == 1603, (
            "12820 times 0.125 is exactly 1602.5, which rounds half up, not down"
        )
        assert invoice["net_before_credit_cents"] == 11217
        assert invoice["credit_applied_cents"] == 0, "no credit has been accrued"
        assert invoice["total_cents"] == 11217
        assert_invoice_rollup_arithmetic(invoice)

    def test_credit_cap_is_keyed_on_net_before_credit_and_truncated(self, api):
        """PRD §3.8: "**Third**, the credit cap: the cap is 25 percent of
        `net_before_credit_cents`, truncated down to a whole number of cents, and
        `credit_applied_cents` is the smaller of the fleet's
        `casing_credit_balance_cents` and that cap."
        PRD §3.8: "**Fourth**, `total_cents` is `net_before_credit_cents` less
        `credit_applied_cents`."

        Design: Difficulty/combinatorial_formula/invoice_credit_cap_evaluation_order
        """
        program = fixtures.setup_national_account_program(
            tier_discount_pct=0.125, casing_credit_rate_cents=15000
        )
        fixtures.setup_two_billable_calls(program)
        fixtures.accrue_casing_credit(
            program["fleet"]["id"], program["location"]["id"], grade="B"
        )
        assert (
            fixtures.read_fleet(program["fleet"]["id"])["casing_credit_balance_cents"]
            == 10500
        )

        invoice = validate_success(
            api.create_cross_location_invoice(
                {
                    "fleet_account_id": program["fleet"]["id"],
                    "billing_period_start": "2026-08-01",
                    "billing_period_end": "2026-08-31",
                    "expected_fleet_account_version": fixtures.read_fleet(
                        program["fleet"]["id"], fixtures.CLERK
                    )["version"],
                },
                fixtures.CLERK,
            ),
            expected_status=201,
        )

        assert invoice["net_before_credit_cents"] == 25339
        assert invoice["credit_applied_cents"] == 6334, (
            "25 percent of 25339 is 6334.75, truncated to 6334, which is below "
            "the 10500 available"
        )
        assert invoice["total_cents"] == 19005
        assert_invoice_rollup_arithmetic(invoice)

    def test_invoice_creation_does_not_yet_consume_the_credit(self, api):
        """PRD §3.8: "Submitting an `OPEN` invoice hands it to the national
        account and is the moment the credit is actually consumed."
        PRD §3.8: "Creation also claims its lines and touches the fleet. Each
        resolved call advances `billing_status` from `UNBILLED` to `INVOICED` and
        records the invoice's identifier in its `cross_location_invoice_id`."

        Design: Difficulty/combinatorial_formula/invoice_credit_cap_evaluation_order
        """
        program = fixtures.setup_national_account_program(
            tier_discount_pct=0.125, casing_credit_rate_cents=15000
        )
        fixtures.setup_two_billable_calls(program)
        fixtures.accrue_casing_credit(
            program["fleet"]["id"], program["location"]["id"], grade="B"
        )

        invoice = fixtures.create_invoice(program["fleet"]["id"])
        assert invoice["credit_applied_cents"] == 6334

        fleet = fixtures.read_fleet(program["fleet"]["id"])
        assert fleet["casing_credit_balance_cents"] == 10500, (
            "the snapshot into credit_applied_cents does not move the balance"
        )
        entries = fixtures.list_ledger(program["fleet"]["id"])
        assert entries_of_type(entries, "APPLICATION") == [], (
            "no APPLICATION entry is posted until the invoice is submitted"
        )
        _data, meta = validate_paginated(
            api.list_cross_location_invoices(
                fixtures.CLERK, params={"fleet_account_id": program["fleet"]["id"]}
            )
        )
        assert meta["total_count"] == 1
