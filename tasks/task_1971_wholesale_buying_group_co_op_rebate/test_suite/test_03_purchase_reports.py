"""Purchase reporting: nested reachability, flag/revise flow, strict quarter
timing, and tier-threshold boundary precision on the provisional rebate.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    bootstrap_coop,
    create_active_member,
    create_onboarded_supplier,
    create_open_program,
    enroll_member,
    setup_member_with_open_program,
    submit_report,
    get_accrual_for_enrollment,
    close_quarter,
    make_member_rep_headers,
    TIER_SCHEDULE_T1,
)


class TestReportReachability:
    def test_purchase_report_reverse_reachable_from_enrollment(
        self, api, admin_headers
    ):
        """PRD §2.10: "Several resources live beneath their parents in the
        URL hierarchy: supplier programs are created beneath their supplier,
        purchase reports are created and listed beneath their enrollment, and
        the audits targeting a report are listed beneath that report."

        A submitted report is listed beneath its owning enrollment with the
        enrollment foreign key populated.

        Design: Corner/entities/purchase_report_reverse_reachable_from_enrollment
        """
        scenario = setup_member_with_open_program(program_code="P-PAR")
        report = submit_report(
            scenario["enrollment"], scenario["member"], 0, 5, 5000
        )
        resp = api.list_enrollment_purchase_reports(
            scenario["enrollment"]["id"], admin_headers
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == report["id"]
        assert data[0]["enrollment_id"] == scenario["enrollment"]["id"]


class TestFlagAndRevise:
    def _flagged_report_scenario(self):
        scenario = setup_member_with_open_program(program_code="P-FLG")
        report = submit_report(scenario["enrollment"], scenario["member"], 0, 5, 5000)
        scenario["report"] = report
        return scenario

    def test_purchase_report_flag_from_submitted_succeeds(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §3.4: "When a `ProgramAuditor` doubts a self-report, flagging
        moves the report from `SUBMITTED` to `FLAGGED` — any other source
        state draws `ERR_INVALID_STATE`."

        Design: Corner/state_machines/purchase_report_flag_from_submitted_succeeds
        """
        scenario = self._flagged_report_scenario()
        resp = api.flag_purchase_report(scenario["report"]["id"], auditor_headers)
        flagged = validate_success(resp, 200)
        assert flagged["status"] == "FLAGGED"

    def test_purchase_report_revise_creates_superseding_report(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §3.4: "Revision does not edit in place. Instead, the old
        `FLAGGED` report transitions to `SUPERSEDED` with its `version`
        incremented, and a brand-new report is created in `SUBMITTED` status
        carrying the revised `self_report_qty` and `self_report_cents`, the
        same `quarter_index` as the old report, and `revision_of_id` pointing
        back at the report it supersedes. Because revision creates a new
        resource, it answers 201."

        Design: Corner/state_machines/purchase_report_revise_creates_superseding_report
        """
        scenario = self._flagged_report_scenario()
        old_report = scenario["report"]
        get_success_data(api.flag_purchase_report(old_report["id"], auditor_headers))

        resp = api.revise_purchase_report(
            old_report["id"],
            {"self_report_qty": 8, "self_report_cents": 8000},
            make_member_rep_headers(scenario["member"]["id"]),
        )
        new_report = validate_success(resp, 201)
        assert new_report["status"] == "SUBMITTED"
        assert new_report["id"] != old_report["id"]
        assert new_report["revision_of_id"] == old_report["id"]
        assert new_report["self_report_qty"] == 8
        assert new_report["self_report_cents"] == 8000
        assert new_report["quarter_index"] == old_report["quarter_index"]

        old_after = get_success_data(
            api.get_purchase_report(old_report["id"], auditor_headers)
        )
        assert old_after["status"] == "SUPERSEDED"


class TestQuarterTiming:
    def test_future_quarter_report_rejected_with_quarter_mismatch(
        self, api, admin_headers
    ):
        """PRD §3.4: "Timing is strict: the `quarter_index` must equal the
        co-op's `current_quarter_index` exactly — an earlier quarter is late
        and a later quarter is early, and both are refused with
        `ERR_QUARTER_MISMATCH` (HTTP 409), while a quarter that has not yet
        started is independently refused with `ERR_FUTURE_QUARTER`; per the
        pipeline order in §2.9, the quarter-match check fires first."

        A report for quarter 99 while the co-op sits in quarter 0 fails the
        quarter-match check.

        Design: Difficulty/resource_temporal_overlap/purchase_report_quarter_uniqueness_per_enrollment
        """
        scenario = setup_member_with_open_program(program_code="P-TO1")
        submit_report(scenario["enrollment"], scenario["member"], 0, 10, 10000)
        resp = api.submit_purchase_report(
            scenario["enrollment"]["id"],
            {"quarter_index": 99, "self_report_qty": 10, "self_report_cents": 10000},
            make_member_rep_headers(scenario["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUARTER_MISMATCH)

    def test_late_quarter_report_rejected_with_quarter_mismatch(
        self, api, admin_headers
    ):
        """PRD §3.4: "Timing is strict: the `quarter_index` must equal the
        co-op's `current_quarter_index` exactly — an earlier quarter is late
        and a later quarter is early, and both are refused with
        `ERR_QUARTER_MISMATCH` (HTTP 409)".

        After the quarter closes, a report filed for the quarter that just
        ended is late and refused with the same error.

        Design: Difficulty/resource_temporal_overlap/purchase_report_quarter_uniqueness_per_enrollment
        """
        scenario = setup_member_with_open_program(program_code="P-TO2")
        submit_report(scenario["enrollment"], scenario["member"], 0, 10, 10000)
        close_quarter()  # current quarter is now 1
        resp = api.submit_purchase_report(
            scenario["enrollment"]["id"],
            {"quarter_index": 0, "self_report_qty": 10, "self_report_cents": 10000},
            make_member_rep_headers(scenario["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUARTER_MISMATCH)


class TestTierThresholdBoundary:
    def test_qty_one_below_min_qty_earns_lower_tier(self, api, admin_headers):
        """PRD §3.3: "To resolve which tier applies to a given eligible
        quantity, walk the schedule and select the last tier whose `min_qty`
        is less than or equal to the eligible quantity — qualification is
        inclusive, so a quantity exactly equal to a tier's `min_qty` earns
        that tier's rate."
        PRD §3.3: "The rebate itself is the eligible purchase cents
        multiplied by the selected tier's `rate_bps` and divided by ten
        thousand, rounded down once to a whole cent after the multiplication
        and division."

        With tiers [{0,200},{100,500}], qty 99 (= min_qty - 1) resolves to
        the 200 bps tier: floor(100000 * 200 / 10000) = 2000.

        Design: Difficulty/boundary_precision_check/tier_threshold_at_exact_min_qty_applies_higher_rate
        """
        scenario = setup_member_with_open_program(
            program_code="P-BND1",
            tier_schedule=[{"min_qty": 0, "rate_bps": 200}, {"min_qty": 100, "rate_bps": 500}],
        )
        submit_report(scenario["enrollment"], scenario["member"], 0, 99, 100000)
        accrual = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual["provisional_rebate_cents"] == 2000, (
            f"qty 99 must resolve to the 200bps tier: expected 2000, got "
            f"{accrual['provisional_rebate_cents']}"
        )
        assert accrual["tier_applied_min_qty"] == 0

    def test_qty_at_exact_min_qty_earns_higher_tier(self, api, admin_headers):
        """PRD §3.3: "qualification is inclusive, so a quantity exactly equal
        to a tier's `min_qty` earns that tier's rate."
        PRD §3.3: "The tier breakpoint that was actually applied is
        remembered on the accrual as `tier_applied_min_qty`."

        With tiers [{0,200},{100,500}], qty 100 (= min_qty exactly) resolves
        to the 500 bps tier: floor(100000 * 500 / 10000) = 5000.

        Design: Difficulty/boundary_precision_check/tier_threshold_at_exact_min_qty_applies_higher_rate
        """
        scenario = setup_member_with_open_program(
            program_code="P-BND2",
            tier_schedule=[{"min_qty": 0, "rate_bps": 200}, {"min_qty": 100, "rate_bps": 500}],
        )
        submit_report(scenario["enrollment"], scenario["member"], 0, 100, 100000)
        accrual = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual["provisional_rebate_cents"] == 5000, (
            f"qty 100 must resolve to the 500bps tier: expected 5000, got "
            f"{accrual['provisional_rebate_cents']}"
        )
        assert accrual["tier_applied_min_qty"] == 100

    def test_tier_schedule_below_minimum_yields_zero_rebate(self, api, admin_headers):
        """PRD §3.3: "When the eligible quantity falls below even the first
        tier's `min_qty`, no scheduled tier applies and the rate is zero —
        equivalently, a synthetic tier with `min_qty` 0 and `rate_bps` 0
        takes effect."

        With a single tier at min_qty 100, a report of qty 50 earns a
        provisional rebate of 0.

        Design: Corner/calculations/tier_schedule_below_minimum_yields_zero_rebate
        """
        scenario = setup_member_with_open_program(
            program_code="P-ZERO",
            tier_schedule=[{"min_qty": 100, "rate_bps": 500}],
        )
        submit_report(scenario["enrollment"], scenario["member"], 0, 50, 100000)
        accrual = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual["provisional_rebate_cents"] == 0
