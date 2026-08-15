"""Year-end close, carryover credits, per-report fee rounding, and the annual
state report (PRD §2.6, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_annual_state_report,
    close_water_year,
    create_account,
    create_annual_state_report,
    create_annual_state_report_payload,
    get_account,
    make_state_regulator_headers,
    pay_assessment,
    setup_account_with_active_production_well,
    setup_account_with_verified_extraction,
    setup_basin_condition,
    submit_and_verify_report,
    submit_extraction_report,
    create_penalty_assessment,
    validate_error,
    validate_success,
    verify_report,
)


class TestPerReportFeeRounding:
    def test_report_fee_per_report_rounding(self, api, water_master_headers):
        """PRD §3.3: "the fee equals `reported_af` multiplied by the base rate of 3000 cents per acre-foot, then multiplied by the basin-condition multiplier in force at the verification instant — 1.00 under `NORMAL`, 1.10 under `WATCH`, and 1.25 under `CRITICAL` — with the per-report result rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/report_fee_per_report_rounding_order
        """
        # WATCH in force (1 of 4 wells breaching -> breach_pct 25.00 -> WATCH, 1.10x).
        basin = setup_basin_condition([130.0, 50.0, 55.0, 60.0], publish=True)
        assert basin["snapshot"]["condition"] == "WATCH"

        account, well = setup_account_with_active_production_well(
            holder_name="Pumper D", base_allocation_af=100.000
        )
        report_1 = submit_extraction_report(well["id"], account["id"], month=6,
                                            reported_af=1.111)
        report_2 = submit_extraction_report(well["id"], account["id"], month=7,
                                            reported_af=1.111)

        verified_1 = validate_success(api.verify_report(report_1["id"], water_master_headers))
        verified_2 = validate_success(api.verify_report(report_2["id"], water_master_headers))
        # round_half_up(1.111 * 3000 * 1.10) = round_half_up(3666.3) = 3666 per report.
        assert verified_1["fee_cents"] == 3666, (
            f"per-report rounding must produce 3666, got {verified_1['fee_cents']}"
        )
        assert verified_2["fee_cents"] == 3666, (
            f"each report is rounded independently, got {verified_2['fee_cents']}"
        )

    def test_annual_total_sums_rounded_per_report_fees(self, api, water_master_headers):
        """PRD §2.6: "Critically, annual totals are never re-derived from aggregate volumes: the sum of pumping fees reported to the state is the sum of already-rounded per-report fees, never a fresh rounding of aggregate acre-feet multiplied by a rate."
        PRD §3.7: "`total_pumping_fees_cents` is the sum of `fee_cents` over that same set — the sum of the per-report rounded fees, never recomputed from `total_extracted_af`"

        Design: Difficulty/combinatorial_formula/report_fee_per_report_rounding_order
        """
        basin = setup_basin_condition([130.0, 50.0, 55.0, 60.0], publish=True)
        assert basin["snapshot"]["condition"] == "WATCH"

        account, well = setup_account_with_active_production_well(
            holder_name="Pumper D2", base_allocation_af=100.000
        )
        submit_and_verify_report(well["id"], account["id"], month=6, reported_af=1.111)
        submit_and_verify_report(well["id"], account["id"], month=7, reported_af=1.111)

        close_water_year(2026)
        annual = create_annual_state_report(2026)
        # Sum of per-report rounded fees: 3666 + 3666 = 7332. An implementation that
        # rounded the aggregate would produce round_half_up(2.222 * 3300) = 7333.
        assert annual["total_pumping_fees_cents"] == 7332, (
            f"the annual total must be the sum of already-rounded per-report fees "
            f"(7332), got {annual['total_pumping_fees_cents']}"
        )
        assert annual["verified_report_count"] == 2
        assert annual["total_extracted_af"] == pytest.approx(2.222, abs=1e-9)


class TestCarryover:
    def test_carryover_credit_applies_cap_at_year_close(self, api):
        """PRD §3.7: "For every account whose `status` is `ACTIVE` or `SUSPENDED` and whose `current_water_year` equals the closing year, the close computes a carryover credit on the settled basis (pending, unverified extraction does not reduce the carryover): the unused volume is the greater of zero and the effective allocation minus `extracted_af_ytd` minus `transfer_out_af_ytd`, rounded half-up to 3 decimals, and the carryover grant is the smaller of that unused volume and twenty-five percent of `base_allocation_af`, again rounded half-up to 3 decimals."
        PRD §3.7: "The grant is added to `credit_balance_af` (which therefore survives the year boundary), `extracted_af_ytd`, `pending_extraction_af`, and `transfer_out_af_ytd` reset to zero, `current_water_year` advances by one, and the account's `version` increments. The close response reports `closed_water_year`, the number of accounts rolled as `accounts_rolled`, and the aggregate grant as `total_carryover_af`."

        Design: Corner/calculations/carryover_credit_applies_cap_at_year_close
        """
        account, _well, _report = setup_account_with_verified_extraction(
            100.000, 30.000, holder_name="Pumper WY"
        )

        close = close_water_year(2026)
        assert close["closed_water_year"] == 2026
        assert close["accounts_rolled"] == 1
        # unused = 100 - 30 = 70.000; cap = 0.25 * 100 = 25.000 -> grant is the cap.
        assert close["total_carryover_af"] == pytest.approx(25.000, abs=1e-9), (
            f"min(70.000, 25.000) = 25.000, got {close['total_carryover_af']}"
        )

        after = get_account(account["id"])
        assert after["credit_balance_af"] == pytest.approx(25.000, abs=1e-9)
        assert after["extracted_af_ytd"] == pytest.approx(0.0, abs=1e-9)
        assert after["pending_extraction_af"] == pytest.approx(0.0, abs=1e-9)
        assert after["current_water_year"] == 2027


class TestAnnualReportAggregates:
    def test_annual_report_aggregates_from_persisted_records(self, api):
        """PRD §3.7: "The generated report aggregates the year's activity: `total_extracted_af` is the sum of `reported_af` over all `VERIFIED` extraction reports of that water year across all accounts, rounded half-up to 3 decimals; `verified_report_count` counts the same set; `total_pumping_fees_cents` is the sum of `fee_cents` over that same set — the sum of the per-report rounded fees, never recomputed from `total_extracted_af`; `overdraft_assessment_count` counts penalty assessments with `reason` `OVERDRAFT` for the year; `penalties_assessed_cents` sums `amount_cents` over all of the year's penalty assessments regardless of status; and `penalties_collected_cents` sums `paid_amount_cents` over the year's assessments whose status is `PAID`."
        PRD §3.7: "The report also captures basin condition at generation time: `final_basin_condition` and `avg_depth_ft` are the `condition` and `rolling_mean_depth_ft` of the official-condition selector snapshot — the latest `PUBLISHED` snapshot by `computed_at`, tie-broken by `created_at` descending — and both are null when no snapshot has ever been published. A new annual report starts in `DRAFT`."

        Design: Corner/calculations/annual_report_aggregates_from_persisted_records
        """
        account, well = setup_account_with_active_production_well(
            holder_name="Pumper AR", base_allocation_af=100.000
        )
        submit_and_verify_report(well["id"], account["id"], month=6, reported_af=10.000)
        submit_and_verify_report(well["id"], account["id"], month=7, reported_af=20.000)

        assessment = create_penalty_assessment(account["id"], "LATE_REPORT", 2026)
        pay_assessment(assessment["id"], account["id"])

        close_water_year(2026)
        annual = create_annual_state_report(2026)
        assert_annual_state_report(annual)

        assert annual["status"] == "DRAFT"
        assert annual["total_extracted_af"] == pytest.approx(30.000, abs=1e-9)
        assert annual["verified_report_count"] == 2
        # 10.000*3000*1.00 + 20.000*3000*1.00 at the default NORMAL multiplier.
        assert annual["total_pumping_fees_cents"] == 90000
        assert annual["overdraft_assessment_count"] == 0
        assert annual["penalties_assessed_cents"] == 10000
        assert annual["penalties_collected_cents"] == 10000
        assert annual["final_basin_condition"] is None, (
            "no snapshot has ever been published, so the basin fields are null"
        )
        assert annual["avg_depth_ft"] is None


class TestYearCloseGates:
    def test_close_year_with_unresolved_reports_rejected(self, api, water_master_headers):
        """PRD §3.7: "The close is blocked while any extraction report in `SUBMITTED` or `DISPUTED` status exists for the closing year across any account — such a request fails with `ERR_CLOSE_YEAR_UNRESOLVED_REPORTS`."

        Design: Corner/validations/close_year_with_unresolved_reports_rejected
        """
        account, well = setup_account_with_active_production_well(holder_name="Pumper CY")
        submit_extraction_report(well["id"], account["id"], month=6, reported_af=5.000)

        resp = api.close_water_year({"water_year": 2026}, water_master_headers)
        validate_error(resp, ApiErrorId.ERR_CLOSE_YEAR_UNRESOLVED_REPORTS)

    def test_annual_report_unclosed_then_duplicate_rejected(self, api, water_master_headers):
        """PRD §3.7: "Generating against a year that has not been closed fails with `ERR_WATER_YEAR_NOT_CLOSED`; a second report for the same year fails with `ERR_ANNUAL_REPORT_EXISTS`."

        Design: Corner/validations/annual_report_unclosed_then_duplicate_rejected
        """
        unclosed = api.create_annual_state_report({"water_year": 2026}, water_master_headers)
        validate_error(unclosed, ApiErrorId.ERR_WATER_YEAR_NOT_CLOSED)

        close_water_year(2026)
        created = validate_success(
            api.create_annual_state_report({"water_year": 2026}, water_master_headers), 201
        )
        assert created["status"] == "DRAFT"

        duplicate = api.create_annual_state_report({"water_year": 2026}, water_master_headers)
        validate_error(duplicate, ApiErrorId.ERR_ANNUAL_REPORT_EXISTS)

    def test_acknowledge_acknowledged_annual_report_rejected(self, api, water_master_headers):
        """PRD §3.7: "The `WaterMaster` submits a `DRAFT` report to the state, moving it to `SUBMITTED` (any other from-state yields `ERR_INVALID_ANNUAL_REPORT_STATE`), and a `StateRegulator` acknowledges a `SUBMITTED` report, moving it to `ACKNOWLEDGED`, which is terminal."
        PRD §2.8: "then the target resource's from-state preconditions (the various `ERR_INVALID_*_STATE` and `ERR_*_NOT_ACTIVE` codes), and only then the business-constraint, business-safety, and business-fiscal rules described in §3."

        Design: Corner/state_machines/acknowledge_acknowledged_annual_report_rejected
        """
        close_water_year(2026)
        annual = create_annual_state_report(2026)
        validate_success(api.submit_annual_state_report(annual["id"], water_master_headers))
        regulator = make_state_regulator_headers("sr-1")
        acked = validate_success(api.acknowledge_annual_state_report(annual["id"], regulator))
        assert acked["status"] == "ACKNOWLEDGED"

        resp = api.acknowledge_annual_state_report(annual["id"], regulator)
        validate_error(resp, ApiErrorId.ERR_INVALID_ANNUAL_REPORT_STATE)
