"""Composed money formulas whose answer depends on the order the steps run in:
the min/max price ladder, the proration rounding order, and the rebate waterfall.
"""

from test_helpers import (
    ReconciliationStatus,
    RegistrationType,
    assert_money,
    assert_ratio,
    fixtures,
    validate_success,
)

CHEAP_TITLE = {
    "isbn": "978-0-11-000009-0",
    "title": "Statistics Workbook",
    "list_price_cents": 3000,
}
STAT_SECTION = {
    "subject_code": "STAT",
    "catalog_number": "050",
    "section_number": "001",
    "instructor_user_id": "fac-9",
}


def _floor_bound_section(api):
    """One student on a title whose 60% list cap (1800) sits below the 2500 floor."""
    return fixtures.setup_billed_section(
        api,
        setup_clock="2026-07-01T00:00:00Z",
        title_overrides=CHEAP_TITLE,
        bands=((1, None, 2000),),
        section_overrides=STAT_SECTION,
        roster=(("S-2001", "Dev Rao"),),
    )


class TestPriceLadder:
    """The floor is the last step of the ladder, so it outranks the list-price cap."""

    def test_price_floor_overrides_the_list_price_cap(self, api, bursar_officer):
        """PRD §3.5: "The system then takes the lesser of the fee-inclusive price
        and the list-price cap, and finally takes the greater of that result and
        the agreement's `price_floor_cents`. The floor is applied last and
        therefore wins: a contractual floor set above the list-price cap raises
        the price above the cap."

        Design: Difficulty/combinatorial_formula/combinatorial_price_floor_overrides_list_price_cap
        """
        scenario = _floor_bound_section(api)

        charge = validate_success(
            api.get_charge(scenario["charge_ids"][0], bursar_officer)
        )

        assert_money(charge["gross_price_cents"], 2500)
        assert_money(charge["billed_amount_cents"], 2500)
        assert_money(charge["net_billed_cents"], 2500)
        # Neither the list cap floor(3000 * 0.60) = 1800 nor the fee-loaded tier
        # price round(2000 * 1.05) = 2100 may survive the ladder.
        assert charge["gross_price_cents"] != 1800
        assert charge["gross_price_cents"] != 2100

    def test_publisher_share_and_bursar_balance_follow_the_floored_price(self, api,
                                                                        registrar,
                                                                        bursar_officer):
        """PRD §3.5: "`net_billed_cents` is always the signed sum of the charge's
        ledger movements, and `publisher_share_cents` is that net amount
        multiplied by one minus the agreement's `bookstore_margin_pct`, rounded
        half up to whole cents."

        Design: Difficulty/combinatorial_formula/combinatorial_price_floor_overrides_list_price_cap
        """
        scenario = _floor_bound_section(api)

        charge = validate_success(
            api.get_charge(scenario["charge_ids"][0], bursar_officer)
        )
        student = validate_success(
            api.get_student(scenario["student_ids"][0], registrar)
        )

        assert_money(charge["publisher_share_cents"], 2200)
        assert_money(student["bursar_balance_cents"], 2500)


class TestProrationRoundingOrder:
    """94 of 110 days rounds to 0.8545 before the multiplication, giving 6729."""

    @staticmethod
    def _section_with_a_late_fourth_charge(api):
        scenario = fixtures.setup_billed_section(
            api,
            setup_clock="2026-07-01T00:00:00Z",
            roster=(("S-1001", "Ada Lin"), ("S-1002", "Ben Ortiz"), ("S-1003", "Cara Wu")),
        )
        student4 = fixtures.create_student(api, "S-1004", "Dana Ek")
        fixtures.set_clock(api, "2026-09-09T08:00:00Z")
        enrollment4 = fixtures.create_enrollment(
            api, scenario["section_id"], student4["id"], "2026-09-09"
        )
        scenario["student4"] = student4
        scenario["enrollment4"] = enrollment4
        return scenario

    def test_late_registration_rounds_the_ratio_before_multiplying(self, api,
                                                                  bursar_officer,
                                                                  registrar):
        """PRD §3.5: "The rounding order is pinned: the ratio is rounded to four
        decimals *first*, then `gross_price_cents` is multiplied by the rounded
        ratio, and only that product is rounded half up to whole cents to give
        `billed_amount_cents`."

        Design: Difficulty/combinatorial_formula/combinatorial_late_registration_ratio_rounded_before_multiplication
        """
        scenario = self._section_with_a_late_fourth_charge(api)

        charge4 = validate_success(
            api.post_enrollment_charge(scenario["enrollment4"]["id"], bursar_officer),
            expected_status=201,
        )

        enrollment4 = validate_success(
            api.get_enrollment(scenario["enrollment4"]["id"], registrar)
        )
        assert enrollment4["registration_type"] == RegistrationType.LATE.value

        # Frozen basis of 3 selects band [3, null]: round(7500 * 1.05) = 7875.
        assert_money(charge4["gross_price_cents"], 7875)
        assert_ratio(charge4["proration_pct"], 0.8545)
        assert_money(charge4["billed_amount_cents"], 6729)
        # 6730 is what multiplying by the unrounded 94/110 would produce.
        assert charge4["billed_amount_cents"] != 6730
        assert_money(charge4["net_billed_cents"], 6729)
        assert_money(charge4["publisher_share_cents"], 5922)

    def test_five_day_floor_binds_after_add_drop_while_day_one_charges_stay_whole(
            self, api, bursar_officer):
        """PRD §3.5: "When the charge posts on or after the add/drop deadline —
        the ordinary situation for a late registrant — the five-day floor is
        later than both other candidates and binds instead, guaranteeing every
        student at least five days to decline the material no matter how late
        the charge lands."

        Design: Difficulty/combinatorial_formula/combinatorial_late_registration_ratio_rounded_before_multiplication
        """
        scenario = self._section_with_a_late_fourth_charge(api)

        charge4 = validate_success(
            api.post_enrollment_charge(scenario["enrollment4"]["id"], bursar_officer),
            expected_status=201,
        )

        assert charge4["opt_out_deadline_at"] == "2026-09-14T08:00:00.000Z"

        day_one_charge = validate_success(
            api.get_charge(scenario["charge_ids"][0], bursar_officer)
        )
        assert_ratio(day_one_charge["proration_pct"], 1.0000)
        assert_money(day_one_charge["billed_amount_cents"], 7875)


class TestRebateWaterfall:
    """The rebate threshold is tested on the gross invoice and never re-tested."""

    def test_rebate_applies_on_gross_even_though_settlement_falls_below_threshold(
            self, api, program_admin):
        """PRD §3.8: "Second, `rebate_cents` is `gross_invoice_cents` multiplied
        by the agreement's `rebate_pct` and rounded half up to whole cents when
        `gross_invoice_cents` is at or above the agreement's
        `rebate_threshold_cents`, and 0 when it is below that threshold — the
        threshold is tested against the *gross* invoice."

        Design: Difficulty/combinatorial_formula/combinatorial_rebate_threshold_tested_on_gross_then_subtracted
        """
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")

        run = validate_success(
            api.create_reconciliation_run(
                {
                    "agreement_id": scenario["agreement_id"],
                    "term_id": scenario["term_id"],
                    "method": "ENROLLMENT_SNAPSHOT",
                    "publisher_reported_count": 2,
                    "publisher_reported_amount_cents": 16133,
                    "expected_agreement_version": scenario["agreement_version"],
                },
                program_admin,
            ),
            expected_status=201,
        )

        assert run["billable_count"] == 2
        assert run["opted_out_count"] == 0
        assert_money(run["gross_invoice_cents"], 16632)
        assert_money(run["rebate_cents"], 499)
        assert_money(run["settlement_amount_cents"], 16133)

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        # 16133 < 16500, yet the rebate computed on the gross invoice still stands.
        assert run["settlement_amount_cents"] < agreement["rebate_threshold_cents"]

    def test_computing_a_run_leaves_the_agreement_computed_with_no_settled_amount(
            self, api, program_admin):
        """PRD §3.8: "Third, `settlement_amount_cents` is `gross_invoice_cents`
        minus `rebate_cents`; the threshold is never re-tested against the
        settlement amount, even when subtracting the rebate drops the figure
        back under the threshold."

        Design: Difficulty/combinatorial_formula/combinatorial_rebate_threshold_tested_on_gross_then_subtracted
        """
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")

        run = validate_success(
            api.create_reconciliation_run(
                {
                    "agreement_id": scenario["agreement_id"],
                    "term_id": scenario["term_id"],
                    "method": "ENROLLMENT_SNAPSHOT",
                    "publisher_reported_count": 2,
                    "publisher_reported_amount_cents": 16133,
                    "expected_agreement_version": scenario["agreement_version"],
                },
                program_admin,
            ),
            expected_status=201,
        )

        assert run["settlement_amount_cents"] == run["gross_invoice_cents"] - run["rebate_cents"]
        assert_money(run["variance_cents"], 0)
        assert run["count_variance"] == 0

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.COMPUTED.value
        assert agreement["settled_amount_cents"] is None
