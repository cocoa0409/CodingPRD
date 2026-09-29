"""What the two pricing phases each produce: bands, fees and the booked amount."""

from test_helpers import (
    OFFICER,
    OFFICER_TWO,
    add_line_item,
    advance_clock,
    assert_decimal_equals,
    create_production_quota_payload,
    draft_report,
    licensed_quota,
    validate_success,
)

_FOXGLEN = {
    "denomination": "Foxglen Bramble",
    "species": "Rubus idaeus",
    "breeder_code": "FG",
    "base_royalty_cents_per_plant": 35,
    "base_royalty_cents_per_acre": 1200,
}

_IRONWOOD = {
    "denomination": "Ironwood Bramble",
    "species": "Rubus idaeus",
    "breeder_code": "IW",
    "base_royalty_cents_per_plant": 35,
    "base_royalty_cents_per_acre": 1200,
}


class TestTheLateFeeIsTakenOnTheAuditedTotal:
    """A TIER_A line of 10000 plants, filed five days after the deadline."""

    def _submitted_late(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_A", territory_class="DOMESTIC",
            allocated_units=20000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides=dict(_FOXGLEN),
            territory_codes=["US-WA"], propagator_name="Foxglen Nursery",
            home_territory_code="US-WA",
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-05T00:00:00Z",
            due_at="2026-08-10T00:00:00Z",
        )
        add_line_item(api, chain, report["id"], 10000)
        advance_clock(api, "2026-08-15T00:00:00Z")
        submitted = validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        chain["report_id"] = report["id"]
        chain["submitted"] = submitted
        return chain

    def test_the_reported_basis_produces_no_fee_at_all(self, api):
        """Submission after the deadline marks the report late and prices it at
        402500, but the fee and the booked amount are not a submission concern.

        PRD 3.7: "On the reported basis no late fee and no booked amount are produced, and `final_total_cents` stays 0."

        Design: Corner/calculations/late_fee_percentage_constant_applied_to_the_final_total
        """
        chain = self._submitted_late(api)
        submitted = chain["submitted"]

        assert submitted["review_status"] == "SUBMITTED"
        assert submitted["is_late"] is True
        assert submitted["provisional_total_cents"] == 402500
        assert submitted["late_fee_cents"] == 0
        assert submitted["final_total_cents"] == 0

    def test_acceptance_takes_two_percent_of_the_final_total_and_books_the_sum(self, api):
        """The fee is two percent of the audited 402500, which is 8050, and the
        booked amount is the audited total plus that fee rather than either alone.

        PRD 3.7: "When `is_late` is true, `late_fee_cents` is `final_total_cents` multiplied by 0.02, rounded half-up to whole cents; when `is_late` is false, `late_fee_cents` is 0."

        Design: Corner/calculations/late_fee_percentage_constant_applied_to_the_final_total
        """
        chain = self._submitted_late(api)

        accepted = validate_success(
            api.accept_royalty_report(chain["report_id"], OFFICER_TWO)
        )
        assert accepted["review_status"] == "ACCEPTED"
        assert accepted["final_total_cents"] == 402500
        assert accepted["late_fee_cents"] == 8050
        assert accepted["booked_amount_cents"] == 410550

    def test_the_ledger_books_the_total_including_the_fee(self, api):
        """The propagator's payable side takes the booked amount, so the fee is
        money owed and not a mere annotation, and the late filing costs six
        compliance points without breaching the suspension bar.

        PRD 3.7: "Among those accepted reports, `royalty_payable_cents` is the sum of `booked_amount_cents` over the ones whose `settlement_status` is `UNSETTLED` or `REVERSED`, and `royalty_settled_cents` is the sum of `booked_amount_cents` over the ones whose `settlement_status` is `SETTLED`."

        Design: Corner/calculations/late_fee_percentage_constant_applied_to_the_final_total
        """
        chain = self._submitted_late(api)
        validate_success(api.accept_royalty_report(chain["report_id"], OFFICER_TWO))

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["royalty_payable_cents"] == 410550
        assert propagator["royalty_settled_cents"] == 0
        assert propagator["compliance_score"] == 94
        assert validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )["status"] == "ACTIVE"


class TestTheVolumeBandBoundaryAtTenThousandUnits:
    """Two lines one unit apart, priced across the first band edge."""

    def _report_with_two_lines(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_A", territory_class="DOMESTIC",
            allocated_units=20000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides=dict(_IRONWOOD),
            territory_codes=["US-WA"], propagator_name="Ironwood Nursery",
            home_territory_code="US-WA",
        )
        second_quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"], season_code="2026S2",
                    basis="PER_PLANT", territory_code="US-WA",
                    territory_class="DOMESTIC", allocated_units=20000,
                ),
                OFFICER,
            ),
            201,
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-11-01T00:00:00Z",
            due_at="2026-11-15T00:00:00Z",
        )
        first_line = add_line_item(api, chain, report["id"], 10000)
        second_line = add_line_item(api, chain, report["id"], 10001,
                                    quota_id=second_quota["id"])
        submitted = validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        chain.update({"report_id": report["id"], "submitted": submitted,
                      "first_line_id": first_line["id"],
                      "second_line_id": second_line["id"]})
        return chain

    def test_exactly_ten_thousand_units_still_earns_the_undiscounted_band(self, api):
        """The first band's upper edge is inclusive, so a line of exactly 10000
        billable units keeps the 1.00 multiplier and prices at 35 x 1.15.

        PRD 3.7: "The third is a volume band read off the line's `billable_units`: 1.00 when `billable_units` is 10000 or fewer, 0.95 when it is between 10001 and 50000 inclusive, and 0.90 when it exceeds 50000."

        Design: Corner/calculations/royalty_rate_volume_band_boundary_at_ten_thousand_units
        """
        chain = self._report_with_two_lines(api)
        assert chain["submitted"]["is_late"] is False

        line = validate_success(
            api.get_royalty_line_item(chain["first_line_id"], chain["propagator_headers"])
        )
        assert line["billable_units"] == 10000
        assert_decimal_equals(line["effective_rate_cents"], "40.2500",
                              "effective_rate_cents")
        assert line["provisional_amount_cents"] == 402500

    def test_one_unit_more_discounts_the_whole_line_not_just_the_excess(self, api):
        """At 10001 billable units the band multiplier becomes 0.95 and it applies
        to every unit on the line, so the rate falls to 38.2375 and the rounded
        line amount is 382413.

        PRD 3.7: "For each line, `billable_units` is set to `reported_units` verbatim, `overrun_flagged` is left false, `effective_rate_cents` is computed as described above, and `provisional_amount_cents` is set to `billable_units` multiplied by `effective_rate_cents`, rounded half-up to whole cents."

        Design: Corner/calculations/royalty_rate_volume_band_boundary_at_ten_thousand_units
        """
        chain = self._report_with_two_lines(api)

        line = validate_success(
            api.get_royalty_line_item(chain["second_line_id"], chain["propagator_headers"])
        )
        assert line["billable_units"] == 10001
        assert_decimal_equals(line["effective_rate_cents"], "38.2375",
                              "effective_rate_cents")
        assert line["provisional_amount_cents"] == 382413

    def test_the_larger_line_is_cheaper_and_the_total_sums_the_rounded_amounts(self, api):
        """The report total is the sum of the two already-rounded line amounts,
        and the arithmetic leaves the bigger line billing less than the smaller
        one because the discount is not marginal.

        PRD 3.7: "The rounding order here is pinned and is not interchangeable: each line is rounded to whole cents first and the rounded integers are summed."

        Design: Corner/calculations/royalty_rate_volume_band_boundary_at_ten_thousand_units
        """
        chain = self._report_with_two_lines(api)

        report = validate_success(
            api.get_royalty_report(chain["report_id"], chain["propagator_headers"])
        )
        assert report["provisional_total_cents"] == 784913

        first = validate_success(
            api.get_royalty_line_item(chain["first_line_id"], chain["propagator_headers"])
        )
        second = validate_success(
            api.get_royalty_line_item(chain["second_line_id"], chain["propagator_headers"])
        )
        assert second["provisional_amount_cents"] < first["provisional_amount_cents"]
