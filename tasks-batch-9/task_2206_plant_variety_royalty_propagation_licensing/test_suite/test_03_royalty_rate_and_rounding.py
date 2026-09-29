"""The two pricing bases, per-line rounding, and the empty-report gate."""

from test_helpers import (
    BREEDER,
    OFFICER,
    OFFICER_TWO,
    ApiErrorId,
    add_line_item,
    assert_decimal_equals,
    create_production_quota_payload,
    draft_report,
    licensed_quota,
    reconciled_tag_order,
    submitted_report,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReportedVersusAuditedBasis:
    """Submission prices on declared units; acceptance reprices on tag activations."""

    def _under_declared_report(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_A",
            territory_class="DOMESTIC",
            allocated_units=20000,
            season_code="2026S1",
            basis="PER_PLANT",
            variety_overrides={
                "denomination": "Orchard Gold",
                "species": "Malus domestica",
                "breeder_code": "OG",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA", "US-OR"],
            propagator_name="Northfield Nursery",
        )
        chain["tag_order"] = reconciled_tag_order(api, chain, requested_units=12000)
        chain.update(submitted_report(api, chain, 9800))
        return chain

    def test_submission_bills_the_self_declared_units_only(self, api):
        """On the reported basis the line bills the 9800 units the propagator
        declared at the 40.2500 tier-A domestic rate, leaves the overrun flag
        down, and produces no final total at all.

        PRD 3.7: "On the reported basis no late fee and no booked amount are produced, and `final_total_cents` stays 0."

        Design: Difficulty/dual_variant_calc/royalty_report_reported_basis_versus_audited_basis_divergence
        """
        chain = self._under_declared_report(api)

        line = validate_success(api.get_royalty_line_item(chain["line_item_id"], BREEDER))
        assert line["billable_units"] == 9800
        assert_decimal_equals(line["effective_rate_cents"], "40.2500", "effective_rate_cents")
        assert line["provisional_amount_cents"] == 394450
        assert line["overrun_flagged"] is False

        report = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert report["provisional_total_cents"] == 394450
        assert report["final_total_cents"] == 0

    def test_acceptance_raises_the_billed_quantity_to_the_tag_activations(self, api):
        """12000 activated tags exceed the 9800 declared, so the audited basis
        bills 12000 units, drops into the 0.95 volume band at 38.2375, flags the
        overrun, and books 458850.

        PRD 3.7: "For each line, `billable_units` becomes the larger of the line's `reported_units` and the quota's `tags_activated_units` — tag activations above the self-declared figure raise the billed quantity, and can simultaneously push the line into a lower volume band and thus change `effective_rate_cents` as well."

        Design: Difficulty/dual_variant_calc/royalty_report_reported_basis_versus_audited_basis_divergence
        """
        chain = self._under_declared_report(api)

        accepted = validate_success(
            api.accept_royalty_report(chain["report_id"], OFFICER_TWO)
        )

        line = validate_success(api.get_royalty_line_item(chain["line_item_id"], BREEDER))
        assert line["billable_units"] == 12000
        assert_decimal_equals(line["effective_rate_cents"], "38.2375", "effective_rate_cents")
        assert line["final_amount_cents"] == 458850
        assert line["overrun_flagged"] is True
        assert accepted["final_total_cents"] == 458850
        assert accepted["late_fee_cents"] == 0
        assert accepted["booked_amount_cents"] == 458850

    def test_the_provisional_figures_survive_acceptance_unchanged(self, api):
        """The two bases stay independently readable: acceptance writes the final
        figures without disturbing what submission wrote.

        PRD 3.7: "`provisional_total_cents` and the provisional per-line amounts are left exactly as submission left them, so the two bases remain independently readable side by side."

        Design: Difficulty/dual_variant_calc/royalty_report_reported_basis_versus_audited_basis_divergence
        """
        chain = self._under_declared_report(api)

        accepted = validate_success(
            api.accept_royalty_report(chain["report_id"], OFFICER_TWO)
        )

        assert accepted["provisional_total_cents"] == 394450
        line = validate_success(api.get_royalty_line_item(chain["line_item_id"], BREEDER))
        assert line["provisional_amount_cents"] == 394450


class TestPerLineRoundingOrder:
    """A report total is the sum of already-rounded per-line integers."""

    def _two_line_report(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_C",
            territory_class="EXPORT",
            allocated_units=5000,
            season_code="2026S1",
            basis="PER_PLANT",
            variety_overrides={
                "denomination": "Basalt Ruby",
                "species": "Vitis vinifera",
                "breeder_code": "BR",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Sagebrush Vines",
        )
        second_quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"],
                    season_code="2026S2", basis="PER_PLANT",
                    territory_class="EXPORT", allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        report = draft_report(api, chain)
        first_line = add_line_item(api, chain, report["id"], 2)
        second_line = add_line_item(api, chain, report["id"], 2,
                                    quota_id=second_quota["id"])
        submitted = validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        return chain, submitted, first_line, second_line

    def test_each_line_rounds_to_whole_cents_on_its_own(self, api):
        """Two units at the tier-C export rate of 37.1875 is 74.375 cents, which
        rounds half up to 74 on each line independently.

        PRD 2.6: "**Per-line-then-sum for royalty totals.** Each line's money amount is rounded to whole cents individually, and the report total is the sum of those already-rounded integers."

        Design: Difficulty/combinatorial_formula/royalty_total_rounds_per_line_before_summing
        """
        _chain, _submitted, first_line, second_line = self._two_line_report(api)

        for line_id in (first_line["id"], second_line["id"]):
            line = validate_success(api.get_royalty_line_item(line_id, BREEDER))
            assert_decimal_equals(line["effective_rate_cents"], "37.1875",
                                  "effective_rate_cents")
            assert line["provisional_amount_cents"] == 74

    def test_report_total_sums_the_rounded_line_amounts(self, api):
        """The total is 74 plus 74; summing the unrounded 74.375 products and
        rounding once would have produced 149.

        PRD 3.7: "The rounding order here is pinned and is not interchangeable: each line is rounded to whole cents first and the rounded integers are summed."

        Design: Difficulty/combinatorial_formula/royalty_total_rounds_per_line_before_summing
        """
        _chain, submitted, _first, _second = self._two_line_report(api)

        assert submitted["provisional_total_cents"] == 148


class TestEmptyReportSubmissionGate:
    """A report with no line items may not be submitted."""

    def _empty_draft_report(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_B",
            territory_class="DOMESTIC",
            allocated_units=20000,
            variety_overrides={
                "denomination": "Hollow Creek Fig",
                "species": "Ficus carica",
                "breeder_code": "HF",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Hollow Creek Farms",
        )
        chain["report"] = draft_report(api, chain)
        chain["report_id"] = chain["report"]["id"]
        return chain

    def test_submitting_a_report_with_no_lines_is_refused(self, api):
        """A zero total computed from nothing is indistinguishable from a genuine
        zero-production period, so the empty collection blocks submission and
        leaves the report exactly as it was.

        PRD 3.7: "The agreement must be `ACTIVE`, and the report must carry at least one line item; an empty report is rejected with `ERR_REPORT_HAS_NO_LINES` (HTTP 422), because a zero total computed from nothing is indistinguishable from a genuine zero-production period."

        Design: Difficulty/boundary_precision_check/empty_line_item_collection_blocks_report_submission
        """
        chain = self._empty_draft_report(api)
        lines, meta = validate_paginated(
            api.list_royalty_line_items(BREEDER, {"report_id": chain["report_id"]})
        )
        assert lines == []
        assert meta["total_count"] == 0

        validate_error(
            api.submit_royalty_report(chain["report_id"], chain["propagator_headers"]),
            ApiErrorId.ERR_REPORT_HAS_NO_LINES.value,
            422,
        )

        unchanged = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert unchanged["review_status"] == "DRAFT"
        assert unchanged["submitted_at"] is None
        assert unchanged["provisional_total_cents"] == 0
        assert unchanged["version"] == chain["report"]["version"]

    def test_one_line_is_enough_to_pass_the_gate(self, api):
        """Adding a single unit of declared production satisfies the gate and the
        same submission call now prices the report at the 35-cent base.

        PRD 3.7: "The report's `provisional_total_cents` is then the sum of those already-rounded per-line amounts."

        Design: Difficulty/boundary_precision_check/empty_line_item_collection_blocks_report_submission
        """
        chain = self._empty_draft_report(api)
        line = add_line_item(api, chain, chain["report_id"], 1)

        submitted = validate_success(
            api.submit_royalty_report(chain["report_id"], chain["propagator_headers"])
        )

        assert submitted["review_status"] == "SUBMITTED"
        assert submitted["provisional_total_cents"] == 35
        priced = validate_success(api.get_royalty_line_item(line["id"], BREEDER))
        assert priced["provisional_amount_cents"] == 35
