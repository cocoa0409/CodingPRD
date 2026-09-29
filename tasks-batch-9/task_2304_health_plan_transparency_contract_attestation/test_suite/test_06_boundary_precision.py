"""Pairs of inputs that straddle a declared threshold by the smallest step.

Each pair differs by three minutes, one millisecond, or 250 cents, and the two
members of the pair must land on opposite sides of the rule. Rounding to fewer
places, rounding the wrong way, or swapping a strict comparison for an inclusive
one collapses a pair into a single outcome.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    CYCLE_CERTIFIED,
    CYCLE_LATE_CERTIFIED,
    DEFICIENCY_TOOL_SLA,
    DISCLOSURE_REASONABLE,
    DISCLOSURE_UNREASONABLE,
    POSTURE_AT_RISK,
    VENDOR_TYPE_CONSULTANT,
    assert_accrual_pricing,
    assert_instant_equals,
    assert_score_close,
    factories as f,
    fixtures as fx,
    validate_success,
)

TOOL_LAUNCH_CLOCK = "2027-01-05T09:00:00Z"
EVALUATION_CLOCK = "2027-07-02T00:00:00Z"
EVALUATION_MONTH = "2027-06"
WINDOW_START = "2027-06-10T00:00:00Z"

# June 2027 offers 30 x 1440 = 43,200 minutes.
WINDOW_END_432_MINUTES = "2027-06-10T07:12:00Z"
WINDOW_END_435_MINUTES = "2027-06-10T07:15:00Z"
WINDOW_END_434_MINUTES = "2027-06-10T07:14:00Z"


def _launched_tool(api: ApiClient, plan_year_id: str, tool_name: str) -> str:
    """A LIVE tool with a full catalogue, launched before the scored month."""
    tool = fx.live_price_comparison_tool(
        api,
        plan_year_id,
        tool_name=tool_name,
        covered_items_count=800,
        sla_target_uptime_pct=99.00,
    )
    return tool["id"]


def _append_window(api: ApiClient, tool_id: str, window_end: str) -> None:
    """Report one outage window that lies wholly in observed history."""
    validate_success(
        api.append_outage_window(
            tool_id,
            f.outage_window_payload(
                window_start=WINDOW_START,
                window_end=window_end,
                cause="Rate-table cache rebuild",
            ),
            PLATFORM_OPERATOR_HEADERS,
        )
    )


def _read_tool(api: ApiClient, tool_id: str) -> dict:
    return validate_success(api.get_price_comparison_tool(tool_id, SPONSOR_ADMIN_HEADERS))


def _two_pending_cycles(api: ApiClient) -> dict:
    """One plan year, four published files, and the May and June cycles pending."""
    fx.set_clock(api, TOOL_LAUNCH_CLOCK)
    setup = fx.activated_plan_year(api, covered_lives=6000)
    plan_year_id = setup["plan_year"]["id"]
    for month in ("2027-05", "2027-06"):
        fx.published_mrf_pair(api, plan_year_id, month)
    may = fx.open_refresh_cycle(
        api,
        plan_year_id,
        period_month="2027-05",
        period_start="2027-05-01",
        period_end="2027-05-31",
    )
    june = fx.open_refresh_cycle(
        api,
        plan_year_id,
        period_month="2027-06",
        period_start="2027-06-01",
        period_end="2027-06-30",
    )
    return {"plan_year_id": plan_year_id, "may": may, "june": june}


def _consultant_contract(
    api: ApiClient, plan_year_id: str, legal_name: str, email: str, fee_cents: int
) -> str:
    vendor = fx.create_vendor(
        api,
        legal_name=legal_name,
        vendor_type=VENDOR_TYPE_CONSULTANT,
        contact_email=email,
    )
    contract = fx.create_contract(
        api,
        plan_year_id,
        vendor["id"],
        contract_type=VENDOR_TYPE_CONSULTANT,
        annual_fee_cents=fee_cents,
    )
    return contract["id"]


class TestToolUptimeBoundary:
    """432 minutes of downtime is compliant; 435 is a breach."""

    def test_the_three_minute_gap_puts_the_two_tools_on_opposite_sides(
        self, api: ApiClient
    ) -> None:
        """One tool lands exactly on target, the other one hundredth below it.

        PRD 3.3: "On a thirty-day month with a 99.00 target, 432 minutes of
        merged downtime yields exactly 99.00 percent and no breach, while 435
        minutes yields 98.99 percent and a breach."

        Design: Difficulty/boundary_precision_check/tool_uptime_boundary_432_versus_435_downtime_minutes
        """
        fx.set_clock(api, TOOL_LAUNCH_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        tool_a = _launched_tool(api, plan_year_id, "Care Cost Finder A")
        tool_b = _launched_tool(api, plan_year_id, "Care Cost Finder B")

        fx.set_clock(api, EVALUATION_CLOCK)
        _append_window(api, tool_a, WINDOW_END_432_MINUTES)
        _append_window(api, tool_b, WINDOW_END_435_MINUTES)

        fx.evaluate_tool(api, tool_a, EVALUATION_MONTH)
        fx.evaluate_tool(api, tool_b, EVALUATION_MONTH)

        compliant = _read_tool(api, tool_a)
        assert compliant["last_downtime_minutes"] == 432
        assert compliant["last_uptime_pct"] == 99.00
        assert compliant["sla_breach_open"] is False
        assert compliant["breach_onset_date"] is None

        breaching = _read_tool(api, tool_b)
        assert breaching["last_downtime_minutes"] == 435
        assert breaching["last_uptime_pct"] == 98.99
        assert breaching["sla_breach_open"] is True
        assert breaching["breach_onset_date"] == "2027-07-01"

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["tool_sla_breach_count"] == 1
        assert plan_year["deficiency_points"] == 2
        assert plan_year["compliance_posture"] == POSTURE_AT_RISK
        assert plan_year["penalty_exposure_cents"] == 20_000

    def test_only_the_breaching_tool_posts_an_availability_accrual(
        self, api: ApiClient
    ) -> None:
        """The compliant tool's evaluation is silent in the ledger.

        PRD 3.3: "When `sla_breach_open` flips from false to true,
        `breach_onset_date` is set to the first day of the month *after*
        `evaluation_month` — the sponsor is given the breached month itself and
        the deficiency is dated from the following day one — and the system posts
        one penalty ledger accrual of `deficiency_type` `TOOL_SLA` with
        `onset_date` equal to that `breach_onset_date`, priced as §3.9
        describes."

        Design: Difficulty/boundary_precision_check/tool_uptime_boundary_432_versus_435_downtime_minutes
        """
        fx.set_clock(api, TOOL_LAUNCH_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        tool_a = _launched_tool(api, plan_year_id, "Care Cost Finder A")
        tool_b = _launched_tool(api, plan_year_id, "Care Cost Finder B")

        fx.set_clock(api, EVALUATION_CLOCK)
        _append_window(api, tool_a, WINDOW_END_432_MINUTES)
        fx.evaluate_tool(api, tool_a, EVALUATION_MONTH)
        assert fx.list_ledger_entries(api, plan_year_id) == []

        _append_window(api, tool_b, WINDOW_END_435_MINUTES)
        fx.evaluate_tool(api, tool_b, EVALUATION_MONTH)

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["deficiency_type"] == DEFICIENCY_TOOL_SLA
        assert entry["onset_date"] == "2027-07-01"
        # Onset 2027-07-01 through the posting clock date 2027-07-02, inclusive.
        assert_accrual_pricing(entry, 5_000, 2, 2.0)
        assert entry["signed_amount_cents"] == 20_000

    def test_rounding_to_two_places_happens_before_the_strict_comparison(
        self, api: ApiClient
    ) -> None:
        """434 minutes rounds back up onto the target and is still compliant.

        PRD 3.3: "From there, `last_uptime_pct` is 100 multiplied by the month's
        uptime minutes — that is, `month_minutes` less `last_downtime_minutes` —
        divided by `month_minutes`, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/tool_uptime_boundary_432_versus_435_downtime_minutes
        """
        fx.set_clock(api, TOOL_LAUNCH_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        tool_id = _launched_tool(api, plan_year_id, "Care Cost Finder C")

        fx.set_clock(api, EVALUATION_CLOCK)
        _append_window(api, tool_id, WINDOW_END_434_MINUTES)
        fx.evaluate_tool(api, tool_id, EVALUATION_MONTH)

        tool = _read_tool(api, tool_id)
        # 42,766 / 43,200 = 98.99537 percent, which rounds half up to 99.00.
        assert tool["last_downtime_minutes"] == 434
        assert tool["last_uptime_pct"] == 99.00
        assert tool["sla_breach_open"] is False
        assert fx.list_ledger_entries(api, plan_year_id) == []


class TestRefreshCertificationDeadlineInstant:
    """The deadline is compared at millisecond resolution and includes itself."""

    def test_one_millisecond_separates_certified_from_late_certified(
        self, api: ApiClient
    ) -> None:
        """May is certified on the deadline instant; June one millisecond past it.

        PRD 3.2: "Certifying at exactly `deadline_at` is on time; one
        millisecond later it is late."

        Design: Difficulty/boundary_precision_check/refresh_certification_deadline_exact_millisecond
        """
        built = _two_pending_cycles(api)

        fx.set_clock(api, "2027-06-05T23:59:59.999Z")
        may = validate_success(
            api.certify_refresh_cycle(
                built["may"]["id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.certify_cycle_payload(
                    certification_note="Certified at the deadline instant."
                ),
            )
        )
        assert_instant_equals(may["deadline_at"], "2027-06-05T23:59:59.999Z")
        assert may["status"] == CYCLE_CERTIFIED
        assert may["on_time"] is True
        assert_instant_equals(may["certified_at"], "2027-06-05T23:59:59.999Z")

        fx.set_clock(api, "2027-07-06T00:00:00.000Z")
        june = validate_success(
            api.certify_refresh_cycle(
                built["june"]["id"],
                COMPLIANCE_OFFICER_HEADERS,
                f.certify_cycle_payload(
                    certification_note="Certified one millisecond late."
                ),
            )
        )
        assert_instant_equals(june["deadline_at"], "2027-07-05T23:59:59.999Z")
        assert june["status"] == CYCLE_LATE_CERTIFIED
        assert june["on_time"] is False
        assert_instant_equals(june["certified_at"], "2027-07-06T00:00:00.000Z")

        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["deficiency_points"] == 2
        assert plan_year["compliance_posture"] == POSTURE_AT_RISK

    def test_neither_side_of_the_deadline_posts_money(self, api: ApiClient) -> None:
        """Late certification costs points, never a ledger entry.

        PRD 3.2: "Certifying at any instant after `deadline_at` moves it `PENDING
        → LATE_CERTIFIED` instead, stamps `certified_at`, sets `on_time` to
        false, increments `version` by 1, and additionally recomputes the plan
        year's `deficiency_points` and `compliance_posture` — a late-certified
        cycle carries two points for as long as it exists."

        Design: Difficulty/boundary_precision_check/refresh_certification_deadline_exact_millisecond
        """
        built = _two_pending_cycles(api)

        fx.set_clock(api, "2027-06-05T23:59:59.999Z")
        validate_success(
            api.certify_refresh_cycle(
                built["may"]["id"], COMPLIANCE_OFFICER_HEADERS, f.certify_cycle_payload()
            )
        )
        fx.set_clock(api, "2027-07-06T00:00:00.000Z")
        validate_success(
            api.certify_refresh_cycle(
                built["june"]["id"], COMPLIANCE_OFFICER_HEADERS, f.certify_cycle_payload()
            )
        )

        assert fx.list_ledger_entries(api, built["plan_year_id"]) == []
        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["penalty_exposure_cents"] == 0

    def test_the_millisecond_before_the_deadline_is_also_on_time(
        self, api: ApiClient
    ) -> None:
        """The inclusive boundary is approached from below as well.

        PRD 3.2: "Certifying at an instant at or before `deadline_at` moves the
        cycle `PENDING → CERTIFIED`, stamps `certified_at` with the clock,
        records the certifying officer's `X-User-ID` in `certified_by_user_id`,
        sets `on_time` to true, and increments the cycle's `version` by 1."

        Design: Difficulty/boundary_precision_check/refresh_certification_deadline_exact_millisecond
        """
        built = _two_pending_cycles(api)

        fx.set_clock(api, "2027-06-05T23:59:59.998Z")
        may = validate_success(
            api.certify_refresh_cycle(
                built["may"]["id"], COMPLIANCE_OFFICER_HEADERS, f.certify_cycle_payload()
            )
        )
        assert may["status"] == CYCLE_CERTIFIED
        assert may["on_time"] is True
        assert_instant_equals(may["certified_at"], "2027-06-05T23:59:59.998Z")

        plan_year = fx.read_plan_year(api, built["plan_year_id"])
        assert plan_year["deficiency_points"] == 0


class TestReasonablenessThresholdInclusive:
    """A score of exactly 55.00 is unreasonable; 54.99 is not."""

    def test_exactly_fifty_five_is_unreasonable_because_the_boundary_includes_it(
        self, api: ApiClient
    ) -> None:
        """875,000 cents of direct pay lands the score on the threshold itself.

        PRD 3.7: "And a consultant with 875,000 cents direct against a
        1,000,000-cent benchmark, a scope score of 4 and a completeness score of
        4 produces 35.00, 8.33 and 11.67, landing exactly on 55.00, which is
        `UNREASONABLE` because the boundary is inclusive."

        Design: Difficulty/boundary_precision_check/reasonableness_threshold_inclusive_at_exactly_55
        """
        fx.set_clock(api, "2027-03-02T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        contract_id = _consultant_contract(
            api,
            setup["plan_year"]["id"],
            "Pinehurst Benefits Consulting",
            "advisors@pinehurst.example",
            875_000,
        )

        assessed = fx.assessed_compensation_disclosure(
            api,
            contract_id,
            direct_comp_cents=875_000,
            indirect_comp_cents=0,
            benchmark_median_cents=1_000_000,
            services_scope_score=4,
            disclosure_completeness_score=4,
        )

        assert_score_close(assessed["component_price_score"], 35.00)
        assert_score_close(assessed["component_scope_score"], 8.33)
        assert_score_close(assessed["component_disclosure_score"], 11.67)
        assert_score_close(assessed["unreasonableness_score"], 55.00)
        assert assessed["status"] == DISCLOSURE_UNREASONABLE

    def test_two_hundred_fifty_cents_less_falls_below_the_threshold(
        self, api: ApiClient
    ) -> None:
        """874,750 cents scores 54.99 and stays reasonable.

        PRD 3.7: "The threshold is 55.00 and the comparison is inclusive. A score
        of 55.00 or above moves the disclosure `RECEIVED → UNREASONABLE`;
        anything below moves it `RECEIVED → REASONABLE`."

        Design: Difficulty/boundary_precision_check/reasonableness_threshold_inclusive_at_exactly_55
        """
        fx.set_clock(api, "2027-03-02T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        contract_id = _consultant_contract(
            api,
            setup["plan_year"]["id"],
            "Lakeshore Actuarial Advisors",
            "team@lakeshore.example",
            874_750,
        )

        assessed = fx.assessed_compensation_disclosure(
            api,
            contract_id,
            direct_comp_cents=874_750,
            indirect_comp_cents=0,
            benchmark_median_cents=1_000_000,
            services_scope_score=4,
            disclosure_completeness_score=4,
        )

        # 40 x 0.87475 = 34.99, so the sum lands one hundredth below 55.00.
        assert_score_close(assessed["component_price_score"], 34.99)
        assert_score_close(assessed["unreasonableness_score"], 54.99)
        assert assessed["status"] == DISCLOSURE_REASONABLE

    def test_only_the_disclosure_on_the_threshold_charges_the_plan_year(
        self, api: ApiClient
    ) -> None:
        """Two near-identical disclosures contribute three points between them.

        PRD 2.8: "three points for each compensation disclosure whose `status` is
        `UNREASONABLE`, counting disclosures reached through the plan year's
        contracts."

        Design: Difficulty/boundary_precision_check/reasonableness_threshold_inclusive_at_exactly_55
        """
        fx.set_clock(api, "2027-03-02T09:00:00Z")
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        on_threshold = _consultant_contract(
            api,
            plan_year_id,
            "Pinehurst Benefits Consulting",
            "advisors@pinehurst.example",
            875_000,
        )
        below_threshold = _consultant_contract(
            api,
            plan_year_id,
            "Lakeshore Actuarial Advisors",
            "team@lakeshore.example",
            874_750,
        )

        shared = {
            "indirect_comp_cents": 0,
            "benchmark_median_cents": 1_000_000,
            "services_scope_score": 4,
            "disclosure_completeness_score": 4,
        }
        fx.assessed_compensation_disclosure(
            api, on_threshold, direct_comp_cents=875_000, **shared
        )
        fx.assessed_compensation_disclosure(
            api, below_threshold, direct_comp_cents=874_750, **shared
        )

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["deficiency_points"] == 3
        assert plan_year["compliance_posture"] == POSTURE_AT_RISK
