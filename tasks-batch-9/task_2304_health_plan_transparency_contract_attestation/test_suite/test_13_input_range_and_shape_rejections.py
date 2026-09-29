"""Inputs that are well-typed but out of the window the program allows.

A schema check can only see that a field is an integer or an ISO date. It cannot
see that 2025 is the wrong reporting year for a 2027 plan, that a month has not
finished yet, that a benchmark of zero is a divisor, or that a label is already
spoken for. Each case pairs the refusal with the neighbouring value that is
accepted, so a rule cannot pass by rejecting everything.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    DEFAULT_SLA_TARGET_UPTIME_PCT,
    DISCLOSURE_RECEIVED,
    FILE_TYPE_IN_NETWORK_RATES,
    PACKAGE_EXPECTED,
    RX_OPEN,
    SECTION_D6_RX_TOTALS,
    TOOL_PENDING_LAUNCH,
    VENDOR_TYPE_BROKER,
    VENDOR_TYPE_PBM,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    make_vendor_contact_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2027-01-02T09:00:00Z"
PROJECTION_CLOCK = "2027-06-15T09:00:00Z"
REWIND_ANCHOR_CLOCK = "2027-06-15T12:00:00.000Z"
ONE_MILLISECOND_EARLIER = "2027-06-15T11:59:59.999Z"
RX_CLOCK = "2027-08-01T09:00:00Z"
MRF_CLOCK = "2027-04-01T09:00:00Z"
TOOL_CLOCK = "2027-02-01T09:00:00Z"
TOOL_LAUNCH_CLOCK = "2027-05-01T09:00:00Z"
EVALUATION_CLOCK = "2027-06-20T09:00:00Z"
OUTAGE_CLOCK = "2027-05-20T09:00:00Z"
DISCLOSURE_CLOCK = "2027-03-01T09:00:00Z"
PACKAGE_CLOCK = "2027-09-01T09:00:00Z"

OTHER_SPONSOR = "Northgate Foods Benefit Plan"
IN_WINDOW_URL = "https://meridian.example/mrf/2027-03-in-network-rates.json"
OUT_OF_WINDOW_URL = "https://meridian.example/mrf/2026-12-in-network-rates.json"


class TestPlanYearRegistryInputs:
    """The registry key, the span it covers, and the page window over it."""

    def test_a_label_already_in_the_registry_cannot_be_reused_by_another_sponsor(
        self, api: ApiClient
    ) -> None:
        """PY2027 is claimed globally, not once per employer.

        PRD 3.1: "Labels are a registry key rather than decoration: a second plan
        year reusing an existing `plan_year_label` is refused with
        `ERR_DUPLICATE_PLAN_YEAR_LABEL`."

        Design: Corner/validations/duplicate_plan_year_label_rejected
        """
        fx.set_clock(api, SETUP_CLOCK)
        first = fx.create_plan_year(api, plan_year_label="PY2027", covered_lives=6000)

        response = api.create_plan_year(
            f.plan_year_payload(
                sponsor_name=OTHER_SPONSOR,
                plan_year_label="PY2027",
                covered_lives=900,
            ),
            SPONSOR_ADMIN_HEADERS,
        )
        validate_error(
            response, ApiErrorId.DUPLICATE_PLAN_YEAR_LABEL, expected_status=409
        )

        rows, meta = validate_paginated(
            api.list_plan_years(
                COMPLIANCE_OFFICER_HEADERS, params={"plan_year_label": "PY2027"}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first["id"]]

    def test_a_plan_year_that_starts_and_ends_on_one_day_is_refused(
        self, api: ApiClient
    ) -> None:
        """The span must be strictly positive, and the refusal is the shape rule.

        PRD 2.5: "Interval inputs that are malformed — a plan year whose
        `end_date` is not strictly after its `start_date`, a contract whose
        `term_end` is not strictly after `term_start`, a refresh cycle whose
        `period_end` precedes `period_start` or whose period falls outside the
        span from the plan year's `start_date` through its `end_date`, an outage
        window whose `window_end` is not strictly after `window_start`, or an
        amendment whose `expires_at` is not strictly after the logical clock —
        are all refused with `ERR_INVALID_INTERVAL` (HTTP 422)."

        Design: Corner/validations/plan_year_inverted_date_interval_rejected
        """
        fx.set_clock(api, SETUP_CLOCK)

        response = api.create_plan_year(
            f.plan_year_payload(
                plan_year_label="PY2027-BAD",
                start_date="2027-06-01",
                end_date="2027-06-01",
                covered_lives=6000,
            ),
            SPONSOR_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.INVALID_INTERVAL, expected_status=422)

        rows, meta = validate_paginated(api.list_plan_years(COMPLIANCE_OFFICER_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_page_size_outside_one_through_one_hundred_is_refused_not_clamped(
        self, api: ApiClient
    ) -> None:
        """limit 0, limit 101 and a negative offset are all rejections.

        PRD 2.3: "`limit` is an integer with a default of 10, a minimum of 1 and
        a maximum of 100. `offset` is an integer with a default of 0 and a
        minimum of 0; it has no upper bound. A `limit` outside the inclusive
        range 1 through 100, a negative `offset`, or a non-integer value for
        either is refused with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/list_plan_years_invalid_pagination_rejected
        """
        fx.set_clock(api, SETUP_CLOCK)
        fx.create_plan_year(api, covered_lives=6000)

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            validate_error(
                api.list_plan_years(COMPLIANCE_OFFICER_HEADERS, params=params),
                ApiErrorId.INVALID_PAGINATION,
                expected_status=400,
            )

        rows, meta = validate_paginated(
            api.list_plan_years(COMPLIANCE_OFFICER_HEADERS, params={"limit": 1})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert meta["limit"] == 1
        assert meta["has_more"] is False


class TestReadTimeAndClockInputs:
    """One read parameter bounded by the plan year, and one monotonic clock."""

    def test_a_projection_date_outside_the_plan_year_is_refused_at_either_end(
        self, api: ApiClient
    ) -> None:
        """The final day of the year is inside the window; the day before it starts is not.

        PRD 3.9: "It accepts an optional `as_of_date`, defaulting to the logical
        clock's calendar date, which must fall between the plan year's
        `start_date` and `end_date` inclusive or the read is refused with
        `ERR_PROJECTION_DATE_OUT_OF_RANGE`."

        Design: Corner/validations/projection_as_of_date_outside_plan_year_rejected
        """
        fx.set_clock(api, PROJECTION_CLOCK)
        plan_year = fx.create_plan_year(api, covered_lives=6000)

        for out_of_range in ("2028-02-01", "2026-12-31"):
            validate_error(
                api.get_penalty_projection(
                    plan_year["id"],
                    EXTERNAL_AUDITOR_HEADERS,
                    params={"as_of_date": out_of_range},
                ),
                ApiErrorId.PROJECTION_DATE_OUT_OF_RANGE,
                expected_status=422,
            )

        on_the_last_day = validate_success(
            api.get_penalty_projection(
                plan_year["id"],
                EXTERNAL_AUDITOR_HEADERS,
                params={"as_of_date": "2027-12-31"},
            )
        )
        assert on_the_last_day["open_deficiency_count"] == 0
        assert on_the_last_day["size_multiplier"] == 2.0
        assert on_the_last_day["accrued_to_date_cents"] == 0

        on_the_first_day = validate_success(
            api.get_penalty_projection(
                plan_year["id"],
                EXTERNAL_AUDITOR_HEADERS,
                params={"as_of_date": "2027-01-01"},
            )
        )
        assert on_the_first_day["open_deficiency_count"] == 0

    def test_the_clock_may_be_held_but_never_moved_back(self, api: ApiClient) -> None:
        """One millisecond earlier is refused; the same instant again is accepted.

        PRD 2.6: "The clock may be moved forward or held at its present value; a
        `current_utc` strictly earlier than the clock's present value is refused
        with `ERR_CLOCK_REWIND_FORBIDDEN` (HTTP 409), so that day counts and
        deadline comparisons remain monotonic across a test run."

        Design: Corner/validations/clock_rewind_rejected
        """
        fx.set_clock(api, REWIND_ANCHOR_CLOCK)
        plan_year = fx.create_plan_year(api, covered_lives=6000)

        validate_error(
            api.set_clock(
                f.clock_payload(ONE_MILLISECOND_EARLIER), PLATFORM_OPERATOR_HEADERS
            ),
            ApiErrorId.CLOCK_REWIND_FORBIDDEN,
            expected_status=409,
        )
        held = validate_success(
            api.set_clock(
                f.clock_payload(REWIND_ANCHOR_CLOCK), PLATFORM_OPERATOR_HEADERS
            )
        )
        assert_instant_equals(held["current_utc"], REWIND_ANCHOR_CLOCK)

        summary = validate_success(
            api.run_compliance(plan_year["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert summary["penalty_exposure_cents"] == 0

        stored = fx.read_plan_year(api, plan_year["id"])
        assert_instant_equals(stored["last_compliance_run_at"], REWIND_ANCHOR_CLOCK)


class TestReportingWindowInputs:
    """A reference year, a posting month and an evaluation month, each bounded."""

    def test_a_reference_year_two_years_before_the_plan_year_is_refused(
        self, api: ApiClient
    ) -> None:
        """2025 clears the 2020 floor and still fails the alignment rule.

        PRD 3.6: "A `PlanSponsorAdmin` or a `ComplianceOfficer` opens the filing
        with the `plan_year_id` being reported and the `reference_year` of the
        data, which must be at least 2020 and must equal either the calendar year
        of the plan year's `start_date` or the year immediately before it —
        anything else is refused with `ERR_RX_REFERENCE_YEAR_INVALID`."

        Design: Corner/validations/rx_submission_reference_year_out_of_window_rejected
        """
        fx.set_clock(api, RX_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]

        validate_error(
            api.create_rx_submission(
                f.rx_submission_payload(plan_year_id, reference_year=2025),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            ApiErrorId.RX_REFERENCE_YEAR_INVALID,
            expected_status=422,
        )

        the_year_before = validate_success(
            api.create_rx_submission(
                f.rx_submission_payload(plan_year_id, reference_year=2026),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert the_year_before["status"] == RX_OPEN
        assert the_year_before["reference_year"] == 2026

        _, meta = validate_paginated(
            api.list_rx_submissions(
                COMPLIANCE_OFFICER_HEADERS, params={"plan_year_id": plan_year_id}
            )
        )
        assert meta["total_count"] == 1

    def test_a_posting_month_outside_the_plan_year_and_an_empty_file_share_one_error(
        self, api: ApiClient
    ) -> None:
        """2026-12 is a well-formed month in the wrong window; 0 rows is no posting.

        PRD 3.2: "Staging rejects a `posting_month` that falls outside the months
        spanned by the plan year's `start_date` through `end_date`, and a
        `row_count` below 1, with `ERR_INVALID_MRF_INPUT`."

        Design: Corner/validations/mrf_posting_month_outside_plan_year_rejected
        """
        fx.set_clock(api, MRF_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]

        validate_error(
            api.create_mrf(
                f.mrf_payload(
                    plan_year_id,
                    file_type=FILE_TYPE_IN_NETWORK_RATES,
                    posting_month="2026-12",
                    public_url=OUT_OF_WINDOW_URL,
                    row_count=480_000,
                ),
                SPONSOR_ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_MRF_INPUT,
            expected_status=422,
        )
        validate_error(
            api.create_mrf(
                f.mrf_payload(
                    plan_year_id,
                    file_type=FILE_TYPE_IN_NETWORK_RATES,
                    posting_month="2027-03",
                    public_url=IN_WINDOW_URL,
                    row_count=0,
                ),
                SPONSOR_ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_MRF_INPUT,
            expected_status=422,
        )

        rows, meta = validate_paginated(
            api.list_mrfs(SPONSOR_ADMIN_HEADERS, params={"plan_year_id": plan_year_id})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_current_month_and_a_pre_launch_month_are_both_unscoreable(
        self, api: ApiClient
    ) -> None:
        """June is still running and January predates the tool; May scores clean.

        PRD 3.3: "A month still in progress cannot be scored and neither can a
        month before the tool existed: an `evaluation_month` that is the clock's
        own month or any later month, or that precedes the month containing
        `launched_at`, is refused with `ERR_EVALUATION_MONTH_NOT_ELAPSED`."

        Design: Corner/validations/evaluation_of_month_still_in_progress_rejected
        """
        fx.set_clock(api, TOOL_LAUNCH_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        tool = fx.live_price_comparison_tool(
            api,
            setup["plan_year"]["id"],
            tool_name="Meridian Cost Estimator",
            covered_items_count=800,
        )
        fx.set_clock(api, EVALUATION_CLOCK)

        for unscoreable_month in ("2027-06", "2027-01"):
            validate_error(
                api.evaluate_price_comparison_tool(
                    tool["id"],
                    f.evaluation_payload(evaluation_month=unscoreable_month),
                    COMPLIANCE_OFFICER_HEADERS,
                ),
                ApiErrorId.EVALUATION_MONTH_NOT_ELAPSED,
                expected_status=422,
            )

        scored = validate_success(
            api.evaluate_price_comparison_tool(
                tool["id"],
                f.evaluation_payload(evaluation_month="2027-05"),
                COMPLIANCE_OFFICER_HEADERS,
            )
        )
        assert scored["last_evaluated_month"] == "2027-05"
        assert scored["last_downtime_minutes"] == 0
        assert scored["last_uptime_pct"] == 100.00
        assert scored["sla_breach_open"] is False


class TestToolLaunchAndOutageHistoryInputs:
    """Breadth of coverage at launch, and a history that must be observed history."""

    def test_a_thin_catalogue_registers_but_will_not_launch(
        self, api: ApiClient
    ) -> None:
        """499 priced items is one short, and the gate is on launch alone.

        PRD 3.3: "Launch requires the plan year to be `ACTIVE` and not frozen,
        and it requires real breadth of coverage: a tool pricing fewer than 500
        covered items and services is refused with
        `ERR_COVERED_ITEMS_INSUFFICIENT`."

        Design: Corner/validations/tool_launch_below_required_covered_items_rejected
        """
        fx.set_clock(api, TOOL_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        tool = fx.register_price_comparison_tool(
            api,
            setup["plan_year"]["id"],
            tool_name="Meridian Cost Estimator",
            covered_items_count=499,
        )
        assert tool["status"] == TOOL_PENDING_LAUNCH

        validate_error(
            api.launch_price_comparison_tool(tool["id"], SPONSOR_ADMIN_HEADERS),
            ApiErrorId.COVERED_ITEMS_INSUFFICIENT,
            expected_status=422,
        )

        stored = validate_success(
            api.get_price_comparison_tool(tool["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert stored["status"] == TOOL_PENDING_LAUNCH
        assert stored["launched_at"] is None
        assert stored["sla_target_uptime_pct"] == DEFAULT_SLA_TARGET_UPTIME_PCT

    def test_a_window_running_past_the_clock_or_starting_before_launch_is_refused(
        self, api: ApiClient
    ) -> None:
        """Both windows are well shaped and collide with nothing.

        PRD 3.3: "Finally range: the window must lie entirely in observed history
        and inside the tool's operating life, meaning `window_end` at or before
        the logical clock and `window_start` at or after `launched_at`, or the
        append is refused with `ERR_OUTAGE_WINDOW_OUT_OF_RANGE`."

        Design: Corner/validations/outage_window_ending_in_the_future_rejected
        """
        fx.set_clock(api, TOOL_LAUNCH_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        tool = fx.live_price_comparison_tool(
            api,
            setup["plan_year"]["id"],
            tool_name="Meridian Cost Estimator",
            covered_items_count=800,
        )
        assert_instant_equals(tool["launched_at"], TOOL_LAUNCH_CLOCK)
        fx.set_clock(api, OUTAGE_CLOCK)

        for window in (
            {
                "window_start": "2027-05-19T23:00:00Z",
                "window_end": "2027-05-21T01:00:00Z",
                "cause": "Window extends past the clock",
            },
            {
                "window_start": "2027-04-10T00:00:00Z",
                "window_end": "2027-04-10T02:00:00Z",
                "cause": "Before the tool was live",
            },
        ):
            validate_error(
                api.append_outage_window(
                    tool["id"],
                    f.outage_window_payload(**window),
                    PLATFORM_OPERATOR_HEADERS,
                ),
                ApiErrorId.OUTAGE_WINDOW_OUT_OF_RANGE,
                expected_status=422,
            )

        stored = validate_success(
            api.get_price_comparison_tool(tool["id"], SPONSOR_ADMIN_HEADERS)
        )
        assert stored["outage_windows"] == []


class TestDisclosureAndPackageFigures:
    """Money and counts that would corrupt a later calculation if stored."""

    def test_a_zero_benchmark_and_a_score_of_six_are_both_out_of_range(
        self, api: ApiClient
    ) -> None:
        """The divisor has a floor of 1 and the ratings a ceiling of 5.

        PRD 3.7: "`benchmark_median_cents` is the market benchmark median for
        comparable services and must be at least 1, because it is used as a
        divisor."

        PRD 3.7: "Any figure out of range — a benchmark below 1, a score outside
        1 through 5, or a negative compensation amount — is refused with
        `ERR_INVALID_BENCHMARK`."

        Design: Corner/validations/disclosure_zero_benchmark_and_out_of_range_scores_rejected
        """
        fx.set_clock(api, DISCLOSURE_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        broker = fx.add_contract_for_vendor_type(
            api,
            setup["plan_year"]["id"],
            VENDOR_TYPE_BROKER,
            annual_fee_cents=2_400_000,
        )
        contract_id = broker["contract"]["id"]

        for bad_figures in (
            {"benchmark_median_cents": 0, "services_scope_score": 4},
            {"benchmark_median_cents": 1_000_000, "services_scope_score": 6},
        ):
            validate_error(
                api.create_compensation_disclosure(
                    f.compensation_disclosure_payload(
                        contract_id,
                        direct_comp_cents=1_000_000,
                        indirect_comp_cents=400_000,
                        disclosure_completeness_score=4,
                        **bad_figures,
                    ),
                    SPONSOR_ADMIN_HEADERS,
                ),
                ApiErrorId.INVALID_BENCHMARK,
                expected_status=422,
            )

        rows, meta = validate_paginated(
            api.list_compensation_disclosures(
                COMPLIANCE_OFFICER_HEADERS, params={"contract_id": contract_id}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        accepted = validate_success(
            api.create_compensation_disclosure(
                f.compensation_disclosure_payload(
                    contract_id,
                    direct_comp_cents=1_000_000,
                    indirect_comp_cents=400_000,
                    benchmark_median_cents=1_000_000,
                    services_scope_score=5,
                    disclosure_completeness_score=4,
                ),
                SPONSOR_ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert accepted["status"] == DISCLOSURE_RECEIVED

    def test_the_same_section_is_unique_per_vendor_not_per_submission(
        self, api: ApiClient
    ) -> None:
        """A second PBM request for D6 collides; a network vendor's D6 does not.

        PRD 3.6: "Each combination of submission, vendor and data section may
        exist at most once; a duplicate request is refused with
        `ERR_DUPLICATE_DATA_SECTION`."

        Design: Corner/validations/duplicate_vendor_data_section_rejected
        """
        fx.set_clock(api, RX_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        pbm = fx.add_contract_for_vendor_type(
            api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
        )
        submission = fx.open_rx_submission(api, plan_year_id, reference_year=2026)
        first = fx.request_package(
            api,
            submission["id"],
            pbm["vendor"]["id"],
            data_section=SECTION_D6_RX_TOTALS,
            expected_record_count=1200,
        )
        network_vendor = fx.create_network_vendor(api)

        validate_error(
            api.create_vendor_data_package(
                f.vendor_data_package_payload(
                    submission["id"],
                    pbm["vendor"]["id"],
                    data_section=SECTION_D6_RX_TOTALS,
                    expected_record_count=1300,
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            ApiErrorId.DUPLICATE_DATA_SECTION,
            expected_status=409,
        )

        other_vendor_same_section = validate_success(
            api.create_vendor_data_package(
                f.vendor_data_package_payload(
                    submission["id"],
                    network_vendor["id"],
                    data_section=SECTION_D6_RX_TOTALS,
                    expected_record_count=400,
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert other_vendor_same_section["status"] == PACKAGE_EXPECTED
        assert other_vendor_same_section["data_section"] == SECTION_D6_RX_TOTALS

        _, meta = validate_paginated(
            api.list_vendor_data_packages(
                COMPLIANCE_OFFICER_HEADERS,
                params={"rx_submission_id": submission["id"]},
            )
        )
        assert meta["total_count"] == 2
        unchanged = validate_success(
            api.get_vendor_data_package(first["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert unchanged["expected_record_count"] == 1200

    def test_an_empty_delivery_and_a_negative_rebate_leave_the_package_untouched(
        self, api: ApiClient
    ) -> None:
        """A refused delivery must not advance the parent submission either.

        PRD 3.6: "A delivery must also carry a `record_count` of at least 1 and
        non-negative monetary totals, or it is refused with
        `ERR_INVALID_PACKAGE_TOTALS`."

        PRD 3.6: "It also bubbles up: if the parent submission is still `OPEN`,
        the first package to reach `RECEIVED` advances it `OPEN → ASSEMBLING` and
        increments the submission's `version` by 1."

        Design: Corner/validations/package_delivery_zero_record_count_rejected
        """
        fx.set_clock(api, RX_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        pbm = fx.add_contract_for_vendor_type(
            api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
        )
        fx.contract_with_secured_data_rights(api, pbm["contract"]["id"])
        submission = fx.open_rx_submission(api, plan_year_id, reference_year=2026)
        package = fx.request_package(
            api,
            submission["id"],
            pbm["vendor"]["id"],
            data_section=SECTION_D6_RX_TOTALS,
            expected_record_count=1200,
        )
        vendor_headers = make_vendor_contact_headers(pbm["vendor"]["id"])

        for bad_totals in (
            {"record_count": 0, "rebate_cents": 1_500_000},
            {"record_count": 1200, "rebate_cents": -1},
        ):
            validate_error(
                api.deliver_package(
                    package["id"],
                    f.deliver_package_payload(
                        plan_paid_cents=6_000_000,
                        member_paid_cents=1_000_000,
                        **bad_totals,
                    ),
                    vendor_headers,
                ),
                ApiErrorId.INVALID_PACKAGE_TOTALS,
                expected_status=422,
            )

        stored = validate_success(
            api.get_vendor_data_package(package["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert stored["status"] == PACKAGE_EXPECTED
        assert stored["delivery_round"] == 0
        assert stored["record_count"] is None

        parent = validate_success(
            api.get_rx_submission(submission["id"], COMPLIANCE_OFFICER_HEADERS)
        )
        assert parent["status"] == RX_OPEN
        assert parent["assembled_record_count"] == 0
