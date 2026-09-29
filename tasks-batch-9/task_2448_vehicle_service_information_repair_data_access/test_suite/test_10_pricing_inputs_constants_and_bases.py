"""Pricing arithmetic: which inputs feed it, which constants it reads, which basis it answers on.

Covers the per-vehicle charge branch, the tier multiplier and seat-factor
constants, the pinned billable-job read point and the discount bands above it,
the four-decimal parity rounding, and the two coverage bases over one fixture.
"""

import pytest

from test_helpers import (
    CellState,
    CoverageBasis,
    EntitlementModel,
    JobAbortReason,
    JobStatus,
    JobType,
    LicenseModel,
    LicenseStatus,
    ParityBasis,
    ParityStatus,
    PublicationType,
    SessionStatus,
    SettlementStatus,
    ShopTier,
    ToolStatus,
    assert_coverage_map,
    assert_coverage_partition,
    assert_entitlement,
    assert_gaps_sorted,
    assert_gateway_fee_breakdown,
    assert_parity_report,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_platform_admin_headers,
    validate_paginated,
    validate_success,
)


def _tool_row(api, ctx, tool_id):
    rows, _meta = validate_paginated(
        api.list_shop_diagnostic_tools(
            ctx["shop"]["id"], ctx["manager_headers"], {"limit": 100}
        )
    )
    return next(row for row in rows if row["id"] == tool_id)


class TestEntitlementChargeInputs:
    """The charge reads the license model, the shop tier and the purchased seats."""

    def test_a_per_vehicle_purchase_prices_off_the_vin_quota(self, api):
        """Forty VINs at 2,500 cents for a PRO shop is one rounding to 85,000.

        PRD 3.3: "For a `PER_VEHICLE` entitlement there is only one line and
        therefore no per-line rounding step: `charged_cents` is the license's
        `per_vehicle_fee_cents` multiplied by the purchased `vin_quota` and by the
        tier multiplier, rounded half up once. The same `PRO` shop buying 40 VINs at
        2,500 cents each is charged 85,000."

        Design: Corner/calculations/entitlement_charge_per_vehicle_provisional_correct_result
        """
        ctx = fixtures.build_funded_shop(
            api,
            funding_cents=100000,
            covered_area_codes=("POWERTRAIN",),
            license_model=LicenseModel.PER_VEHICLE,
        )

        entitlement = validate_success(
            api.create_entitlement(
                factories.per_vehicle_entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"], vin_quota=40
                ),
                ctx["manager_headers"],
            ),
            201,
        )

        assert_entitlement(entitlement)
        assert entitlement["charged_cents"] == 85000
        assert entitlement["entitlement_model"] == EntitlementModel.PER_VEHICLE
        assert entitlement["vin_quota"] == 40
        assert entitlement["settled_cents"] == 0
        assert entitlement["settlement_status"] == SettlementStatus.UNSETTLED

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 15000
        assert shop["funded_credit_total_cents"] == 100000

    def test_the_enterprise_multiplier_is_read_from_the_buying_shop(self, api):
        """The same single-line license charges an ENTERPRISE shop 70,000.

        PRD 3.3: "The tier multiplier is 1.00 for a `BASIC` shop, 0.85 for a `PRO`
        shop and 0.70 for an `ENTERPRISE` shop, read from the shop's `tier` as it
        stands at the moment the variant runs."

        Design: Corner/calculations/entitlement_charge_enterprise_tier_mult_constant_applied
        """
        ctx = fixtures.build_funded_shop(
            api,
            tier=ShopTier.ENTERPRISE,
            shop_name="Mega Fleet",
            covered_area_codes=("POWERTRAIN",),
        )

        entitlement = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"]
                ),
                ctx["manager_headers"],
            ),
            201,
        )

        assert entitlement["charged_cents"] == 70000

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 130000
        assert shop["tier"] == ShopTier.ENTERPRISE

    def test_the_seat_step_is_charged_only_above_the_included_seats(self, api):
        """Three seats cost 100,000 and the fourth seat adds exactly 5,000.

        PRD 3.3: "The seat factor is 1 plus five hundredths for each purchased seat
        beyond the first three, so an entitlement of three seats or fewer has a seat
        factor of exactly 1, four seats gives 1.05, and ten seats gives 1.35", over a
        `BASIC` shop whose tier multiplier is 1.00.

        Design: Corner/calculations/entitlement_charge_seat_factor_boundary_at_included_seats_plus_one
        """
        ctx = fixtures.build_funded_shop(
            api,
            tier=ShopTier.BASIC,
            funding_cents=150000,
            shop_name="Three Seat Garage",
            covered_area_codes=("POWERTRAIN",),
        )
        other = fixtures.add_second_shop(
            api, ctx, name="Four Seat Garage", tier=ShopTier.BASIC, funding_cents=150000
        )

        three_seats = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"], seats_total=3
                ),
                ctx["manager_headers"],
            ),
            201,
        )
        four_seats = validate_success(
            api.create_entitlement(
                factories.entitlement_payload(
                    other["shop"]["id"], ctx["license"]["id"], seats_total=4
                ),
                other["headers"],
            ),
            201,
        )

        assert three_seats["charged_cents"] == 100000
        assert four_seats["charged_cents"] == 105000
        assert four_seats["charged_cents"] - three_seats["charged_cents"] == 5000

        first_shop = fixtures.refresh_shop(api, ctx)
        assert first_shop["data_credit_balance_cents"] == 50000
        second_shop = validate_success(
            api.get_shop(other["shop"]["id"], other["headers"])
        )
        assert second_shop["data_credit_balance_cents"] == 45000


class TestGatewayFeeInputSetAndBands:
    """The billable set is read before the exit cascade, and the band follows it."""

    def test_a_job_still_queued_at_the_read_point_is_not_billed(self, api):
        """The queued flash job is aborted by the same exit but never priced.

        PRD 3.7: "The billable job set is read at the instant the session leaves
        `ACTIVE` and **immediately before that exit's own job cascade is applied**,
        and it comprises exactly the jobs whose status at that read point is
        `IN_PROGRESS`, `COMPLETED` or `REVALIDATION_REQUIRED`" — "a job still
        sitting in `QUEUED` at the read point is **not** billed even though the same
        exit aborts it". The completed branch "aborts jobs in `QUEUED` and in
        `REVALIDATION_REQUIRED` with `abort_reason` of `SESSION_COMPLETED`,
        decrementing `active_pin_count` for the `QUEUED` rows only".

        Design: Corner/calculations/gateway_fee_input_set_excludes_queued_job
        """
        ctx = fixtures.build_active_session(api, covered_area_codes=("POWERTRAIN",))
        fixtures.add_job(
            api,
            ctx,
            key="immobilizer",
            job_type=JobType.IMMOBILIZER_KEY,
            start=True,
            complete=True,
        )
        fixtures.add_job(
            api, ctx, key="flash", job_type=JobType.MODULE_FLASH, start=False
        )

        completed = validate_success(
            api.complete_gateway_session(
                ctx["sessions"]["main"]["id"], ctx["tech_headers"]["main"]
            )
        )

        assert completed["status"] == SessionStatus.COMPLETED
        assert_gateway_fee_breakdown(completed, 6800, 340, 816, 7276)

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["gateway_fee_accrued_cents"] == 7276

        immobilizer = fixtures.refresh_job(api, ctx, key="immobilizer")
        assert immobilizer["status"] == JobStatus.COMPLETED
        flash = fixtures.refresh_job(api, ctx, key="flash")
        assert flash["status"] == JobStatus.ABORTED
        assert flash["abort_reason"] == JobAbortReason.SESSION_COMPLETED

        version = fixtures.refresh_version(api, ctx)
        assert version["active_pin_count"] == 0

        tool = _tool_row(api, ctx, ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.IDLE

    def test_a_base_subtotal_of_ten_thousand_or_more_takes_the_ten_percent_band(
        self, api
    ):
        """Two immobilizer jobs reach 10,800 and the top band applies once.

        PRD 3.7: "a base subtotal of 10,000 cents or more earns ten percent", and
        "the rate is twelve percent when at least one billable job has `job_type` of
        `IMMOBILIZER_KEY`", with `total_access_fee_cents` set to "`base_subtotal_cents`
        minus `discount_cents` plus `surcharge_cents`, in exact integer arithmetic
        over the two already-rounded parts".

        Design: Corner/calculations/gateway_fee_waterfall_reaches_discount_tier_2_at_two_immobilizer_jobs
        """
        ctx = fixtures.build_session_with_completed_jobs(
            api,
            job_types=(JobType.IMMOBILIZER_KEY, JobType.IMMOBILIZER_KEY),
            covered_area_codes=("POWERTRAIN",),
        )

        completed = validate_success(
            api.complete_gateway_session(
                ctx["sessions"]["main"]["id"], ctx["tech_headers"]["main"]
            )
        )

        assert completed["status"] == SessionStatus.COMPLETED
        assert_gateway_fee_breakdown(completed, 10800, 1080, 1296, 11016)

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["gateway_fee_accrued_cents"] == 11016


class TestParityIndexPrecision:
    """The verdict is taken on the rounded index, not on the raw quotient."""

    def test_a_raw_index_above_the_ceiling_rounds_back_onto_it(self, api):
        """1.15004 rounds to 1.1500, so the OEM is compliant and activation passes.

        PRD 3.1: under the list basis "the index is the independent monthly price
        divided by the dealer monthly price, with the quotient rounded half up to
        four decimal places", and "the verdict is `COMPLIANT` when the rounded index
        is less than or equal to 1.15 ... an index landing exactly on 1.1500 is
        compliant". The report answers with "the `threshold` against which the index
        was judged, which is 1.15".

        Design: Corner/calculations/parity_index_precision_rounded_value_is_what_is_compared
        """
        ctx = fixtures.build_catalogue(
            api,
            area_codes=("POWERTRAIN",),
            manufacturer_overrides={
                "independent_list_monthly_cents": 115004,
                "independent_covered_system_count": 4,
                "oem_dealer_monthly_cents": 100000,
                "oem_dealer_covered_system_count": 4,
            },
        )
        manufacturer = ctx["manufacturer"]
        assert manufacturer["parity_index"] == pytest.approx(1.1500, abs=5e-5)
        assert manufacturer["parity_status"] == ParityStatus.COMPLIANT

        report = validate_success(
            api.get_parity_report(
                manufacturer["id"],
                make_compliance_officer_headers(),
                {"basis": ParityBasis.LIST_BASIS},
            )
        )
        assert_parity_report(report)
        assert report["parity_index"] == pytest.approx(1.1500, abs=5e-5)
        assert report["parity_status"] == ParityStatus.COMPLIANT
        assert report["threshold"] == pytest.approx(1.15, abs=5e-5)

        fixtures.add_license(
            api, ctx, activate=False, covered_area_codes=("POWERTRAIN",)
        )
        activated = validate_success(
            api.activate_license(ctx["license"]["id"], make_platform_admin_headers())
        )
        assert activated["status"] == LicenseStatus.ACTIVE
        assert activated["suspension_reason"] is None


class TestCoverageBasisDivergence:
    """One fixture, two bases, two different percentages."""

    def test_the_same_two_cells_read_zero_effective_and_fifty_declared(self, api):
        """A degraded cell earns nothing effective and everything declared.

        PRD 3.9: "Under the **effective** basis, the numerator is `covered_cells`
        alone, so an unvalidated-but-published procedure earns nothing. Under the
        **declared** basis, the numerator is `covered_cells` plus `degraded_cells`."
        With a flagged cell that has "a validated and published repair procedure but
        no calibration document at all, it is a `GAP`" and an unflagged cell whose
        published procedure is "still `DRAFT`, it is `DEGRADED`", so "The same
        underlying data then reads `0.00` on the effective basis and `50.00` on the
        declared basis." The stored figure "is always the effective-basis number".

        Design: Corner/calculations/coverage_completeness_effective_vs_declared_divergence
        """
        ctx = fixtures.build_entitled_shop(
            api,
            area_codes=("ADAS", "POWERTRAIN"),
            covered_area_codes=("ADAS", "POWERTRAIN"),
        )
        fixtures.add_publication_version(
            api,
            ctx,
            key="adas",
            publication_key="adas",
            system_area_code="ADAS",
            publication_type=PublicationType.REPAIR_PROCEDURE,
            source_tsb_ref="TSB-ADAS-1",
            validate=True,
            publish=True,
        )
        fixtures.add_publication_version(
            api,
            ctx,
            key="powertrain",
            publication_key="powertrain",
            system_area_code="POWERTRAIN",
            publication_type=PublicationType.REPAIR_PROCEDURE,
            source_tsb_ref="TSB-PT-1",
            validate=False,
            publish=True,
        )

        effective = validate_success(
            api.get_coverage_map(ctx["shop"]["id"], ctx["manager_headers"], None)
        )
        declared = validate_success(
            api.get_coverage_map(
                ctx["shop"]["id"],
                ctx["manager_headers"],
                {"basis": CoverageBasis.DECLARED},
            )
        )

        assert_coverage_map(effective)
        assert_coverage_partition(effective)
        assert effective["basis"] == CoverageBasis.EFFECTIVE
        assert effective["total_cells"] == 2
        assert effective["covered_cells"] == 0
        assert effective["degraded_cells"] == 1
        assert effective["gap_cells"] == 1
        assert effective["completeness_pct"] == pytest.approx(0.00, abs=0.005)

        gaps = effective["gaps"]
        assert_gaps_sorted(gaps)
        assert len(gaps) == 2
        assert gaps[0]["system_area_code"] == "ADAS"
        assert gaps[0]["cell_state"] == CellState.GAP
        assert gaps[1]["system_area_code"] == "POWERTRAIN"
        assert gaps[1]["cell_state"] == CellState.DEGRADED
        for entry in gaps:
            assert entry["model_code"] == "AX7"
            assert entry["vehicle_model_id"] == ctx["vehicle_model"]["id"]

        assert declared["basis"] == CoverageBasis.DECLARED
        assert declared["total_cells"] == 2
        assert declared["covered_cells"] == 0
        assert declared["degraded_cells"] == 1
        assert declared["gap_cells"] == 1
        assert declared["completeness_pct"] == pytest.approx(50.00, abs=0.005)

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["coverage_completeness_pct"] == pytest.approx(0.00, abs=0.005)
        assert shop["data_credit_balance_cents"] == 115000
