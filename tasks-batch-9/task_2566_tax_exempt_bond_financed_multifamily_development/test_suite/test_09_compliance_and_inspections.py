"""Annual owner certifications, the recapture cascade, and physical inspection windows.

Once a development stabilizes, the covenant runs for decades and the agency watches it
through two instruments: one owner certification per calendar year and periodic physical
inspections. These tests cover the coherence and uniqueness rules on the filings, the
three-level recapture cascade a noncompliance finding fires, the buffered closed
inspection windows, and the immediacy with which every derived figure appears.
"""

from test_helpers import (
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_USER_ID,
    ApiErrorId,
    assert_fields,
    assert_nulls,
    assert_ids_equal,
    assert_page,
    assert_pool_ledger,
    assert_project_fractions,
    assert_unit_counts,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestFilingAndReviewingTheAnnualReport:
    """Every way a filing or a review can be refused on a stabilized development."""

    def test_reporting_errors_cover_incoherent_counts_duplicate_years_replayed_review_and_windows_outside_the_period(
        self, api
    ):
        """Four families of refusal against one development whose covenant runs 2027 to 2057.

        Coherence is a chain, and all three of its links are probed on the same four-unit
        development: three restricted households cannot sit inside two occupied units,
        four total units cannot hold five occupied, and an average band of 95 is outside
        the inclusive 1 to 80 range — three plausible filings, one code. Uniqueness then
        does double duty: a second 2027 filing collides on the development-and-year key,
        while a 2026 filing is refused for falling outside the covenant span even though
        no 2026 row exists at all. The review is terminal, so a second look at a cleared
        report is refused without disturbing the notes the first review stamped. Finally
        both bounds of the inspection window rule are probed, one window entirely before
        the compliance start and one whose end crosses the extended-use end.

        PRD: "Coherence is checked as a chain: `restricted_units_occupied` must not exceed `total_units_occupied`, which must not exceed the development's `total_units`, and `average_ami_percent` must lie between 1 and 80 inclusive; any breach is `ERR_REPORT_COUNTS_INCOHERENT`. At most one report may exist for a given development and `reporting_year` in any status, and the year must fall inside the calendar years spanned by the development's `compliance_start_date` through its `extended_use_end_date` inclusive; a duplicate year or an out-of-span year is `ERR_DUPLICATE_COMPLIANCE_REPORT`."
        PRD: "The `achieved_set_aside_bps` is the `restricted_units_occupied` multiplied by 10,000, divided by the development's `total_units`, floored to a whole basis point. The `shortfall_bps` is the larger of zero and the required threshold less the achieved ratio, where the required threshold is 2,000 basis points when the development's `set_aside_election` is `MIN_20_50` and 4,000 basis points under either of the other two elections."
        PRD: "The compliance officer reviews the report with a `finding` of `CLEARED` or `NONCOMPLIANCE` and optional `finding_notes`, and the report must be in `SUBMITTED` — reviewing twice is `ERR_COMPLIANCE_REPORT_STATE_INVALID`."
        PRD: "The window must also lie wholly inside the compliance period: `window_start` at or after the development's `compliance_start_date` and `window_end` at or before its `extended_use_end_date`, both bounds inclusive; otherwise `ERR_INSPECTION_OUTSIDE_COMPLIANCE_PERIOD`."

        Design: Corner/errors/compliance_reporting_errors_cover_incoherent_counts_duplicate_years_replayed_review_and_windows_outside_the_period
        """
        deal = fixtures.setup_converted_bond(api)
        assert_fields(
            deal.project,
            "project",
            development_status="STABILIZED",
            compliance_status="RESTRICTED",
            total_units=4,
        )
        assert deal.project["compliance_start_date"].startswith("2027-03-01T00:00:00")
        assert deal.project["extended_use_end_date"].startswith("2057-03-01T00:00:00")

        for counts in (
            {
                "restricted_units_occupied": 3,
                "total_units_occupied": 2,
                "average_ami_percent": 60,
            },
            {
                "restricted_units_occupied": 2,
                "total_units_occupied": 5,
                "average_ami_percent": 60,
            },
            {
                "restricted_units_occupied": 2,
                "total_units_occupied": 4,
                "average_ami_percent": 95,
            },
        ):
            validate_error(
                api.create_compliance_report(
                    deal.developer_headers,
                    project_id=deal.project_id,
                    reporting_year=2027,
                    **counts
                ),
                ApiErrorId.ERR_REPORT_COUNTS_INCOHERENT,
                422,
            )

        report = fixtures.file_compliance_report(
            api,
            deal,
            reporting_year=2027,
            restricted_units_occupied=2,
            total_units_occupied=4,
            average_ami_percent=60,
        )
        assert_fields(
            report,
            "compliance_report",
            status="SUBMITTED",
            achieved_set_aside_bps=5000,
            shortfall_bps=0,
        )
        assert_nulls(
            report, ("finding_notes", "reviewed_by_user_id"), "compliance_report"
        )

        validate_error(
            api.create_compliance_report(
                deal.developer_headers,
                project_id=deal.project_id,
                reporting_year=2027,
                restricted_units_occupied=2,
                total_units_occupied=3,
                average_ami_percent=55,
            ),
            ApiErrorId.ERR_DUPLICATE_COMPLIANCE_REPORT,
            409,
        )
        validate_error(
            api.create_compliance_report(
                deal.developer_headers,
                project_id=deal.project_id,
                reporting_year=2026,
                restricted_units_occupied=2,
                total_units_occupied=4,
                average_ami_percent=60,
            ),
            ApiErrorId.ERR_DUPLICATE_COMPLIANCE_REPORT,
            409,
        )

        cleared = fixtures.review_compliance_report(
            api, deal, 2027, finding="CLEARED", finding_notes="roster verified"
        )
        assert_fields(
            cleared,
            "compliance_report",
            status="CLEARED",
            finding_notes="roster verified",
            reviewed_by_user_id=COMPLIANCE_OFFICER_USER_ID,
        )

        validate_error(
            api.review_compliance_report(
                report["id"],
                COMPLIANCE_OFFICER,
                finding="NONCOMPLIANCE",
                finding_notes="second look",
            ),
            ApiErrorId.ERR_COMPLIANCE_REPORT_STATE_INVALID,
            409,
        )
        assert_fields(
            validate_success(
                api.get_compliance_report(report["id"], COMPLIANCE_OFFICER)
            ),
            "compliance_report",
            status="CLEARED",
            finding_notes="roster verified",
        )
        assert_fields(
            fixtures.read_project(api, deal), "project", compliance_status="RESTRICTED"
        )

        validate_error(
            api.create_physical_inspection(
                COMPLIANCE_OFFICER,
                project_id=deal.project_id,
                window_start="2026-12-01T00:00:00Z",
                window_end="2026-12-31T00:00:00Z",
                inspector_name="R. Ibarra",
            ),
            ApiErrorId.ERR_INSPECTION_OUTSIDE_COMPLIANCE_PERIOD,
            422,
        )
        validate_error(
            api.create_physical_inspection(
                COMPLIANCE_OFFICER,
                project_id=deal.project_id,
                window_start="2057-02-15T00:00:00Z",
                window_end="2057-03-15T00:00:00Z",
                inspector_name="R. Ibarra",
            ),
            ApiErrorId.ERR_INSPECTION_OUTSIDE_COMPLIANCE_PERIOD,
            422,
        )

        assert_page(
            api.list_compliance_reports(COMPLIANCE_OFFICER, project_id=deal.project_id),
            total_count=1,
        )
        assert_page(
            api.list_physical_inspections(
                COMPLIANCE_OFFICER, project_id=deal.project_id
            ),
            total_count=0,
        )


class TestClosingAnInspection:
    """The one action that stamps four fields and derives a date 1,095 days out."""

    def test_completing_an_inspection_stamps_the_result_and_the_three_year_next_due_date(
        self, api
    ):
        """One window closed on 2027-06-10, then both ways out of `SCHEDULED`.

        Completion stamps the date, the score and the deficiency count and derives the
        next due date as the completed date plus 1,095 days, which from 2027-06-10 lands
        on 2030-06-09 rather than the 2030-06-10 a naive three-year addition would give,
        because 2028 is a leap year. The row is then terminal: replaying the completion
        with a different score changes nothing, and a second window the clock has already
        turned to `MISSED` cannot be completed retroactively either, keeping its next due
        date null. Neither the compliance axis nor the development status moves at all.

        PRD: "The inspection opens in `SCHEDULED` with `completed_date`, `score`, `deficiency_count` and `next_inspection_due_date` all null."
        PRD: "Recording a result requires the inspection to be in `SCHEDULED` — completing one that is already `COMPLETED` or has lapsed to `MISSED` is `ERR_INSPECTION_STATE_INVALID` — and supplies the `completed_date`, the `score` out of 100 and the `deficiency_count`. The completed date must fall inside the scheduled window, at or after `window_start` and at or before `window_end`. Completion moves the inspection `SCHEDULED` → `COMPLETED`, which is terminal, stamps all three supplied values, and sets `next_inspection_due_date` to the `completed_date` plus 1,095 days — a three-year inspection cycle."
        PRD: "Every inspection still in `SCHEDULED` whose `window_end` now lies strictly in the past moves `SCHEDULED` → `MISSED`; a missed inspection's `next_inspection_due_date` stays null."

        Design: Corner/endpoints/completing_an_inspection_stamps_the_result_and_the_three_year_next_due_date
        """
        deal = fixtures.setup_converted_bond(api)

        first = fixtures.schedule_inspection(
            api,
            deal,
            window_start="2027-06-01T00:00:00Z",
            window_end="2027-06-30T00:00:00Z",
            inspector_name="R. Ibarra",
        )
        assert_fields(first, "inspection", status="SCHEDULED")
        assert_nulls(
            first,
            (
                "completed_date",
                "score",
                "deficiency_count",
                "next_inspection_due_date",
            ),
            "inspection",
        )

        completed = fixtures.complete_inspection(
            api,
            deal,
            completed_date="2027-06-10T00:00:00Z",
            score=92,
            deficiency_count=3,
        )
        assert_fields(completed, "inspection", status="COMPLETED", score=92,
                      deficiency_count=3)
        assert completed["completed_date"].startswith("2027-06-10T00:00:00")
        assert completed["next_inspection_due_date"].startswith("2030-06-09T00:00:00"), (
            "next due date should be 1,095 days after completion, got {0!r}".format(
                completed["next_inspection_due_date"]
            )
        )

        validate_error(
            api.complete_physical_inspection(
                first["id"],
                COMPLIANCE_OFFICER,
                completed_date="2027-06-12T00:00:00Z",
                score=99,
                deficiency_count=0,
            ),
            ApiErrorId.ERR_INSPECTION_STATE_INVALID,
            409,
        )
        assert_fields(
            validate_success(
                api.get_physical_inspection(first["id"], COMPLIANCE_OFFICER)
            ),
            "inspection",
            status="COMPLETED",
            score=92,
            deficiency_count=3,
        )

        second = fixtures.schedule_inspection(
            api,
            deal,
            window_start="2027-08-01T00:00:00Z",
            window_end="2027-08-31T00:00:00Z",
            inspector_name="R. Ibarra",
        )
        assert_fields(second, "second_inspection", status="SCHEDULED")

        fixtures.set_clock(api, "2027-09-01T00:00:00Z")
        missed = validate_success(
            api.get_physical_inspection(second["id"], COMPLIANCE_OFFICER)
        )
        assert_fields(missed, "second_inspection", status="MISSED")
        assert_nulls(
            missed,
            ("completed_date", "next_inspection_due_date"),
            "second_inspection",
        )

        validate_error(
            api.complete_physical_inspection(
                second["id"],
                COMPLIANCE_OFFICER,
                completed_date="2027-08-15T00:00:00Z",
                score=88,
                deficiency_count=5,
            ),
            ApiErrorId.ERR_INSPECTION_STATE_INVALID,
            409,
        )
        assert_fields(
            fixtures.read_project(api, deal),
            "project",
            compliance_status="RESTRICTED",
            development_status="STABILIZED",
        )


class TestTheRecaptureCascade:
    """One review call, three links, each existing only because of the one before it."""

    def test_a_noncompliance_finding_cascades_project_then_credit_allocation_then_delivery(
        self, api
    ):
        """A single shortfall on the ten-unit development, followed three levels down.

        The finding moves the report and the development's compliance axis; that
        development transition — not the report — is what moves the issued credit
        allocation into `RECAPTURE_PENDING` and stamps its exposure; and that allocation
        transition — not the development — is what flags the accepted delivery. The
        exposure is read off the single triggering report: 5,596,471 of annual credit
        against a 1,000 basis point shortfall is 559,647.1, which rounds half up to
        559,647. Nothing on the development's financing axis moves, and flagging is not a
        rescission, so the investor's running total is untouched.

        PRD: "The report moves `SUBMITTED` → `NONCOMPLIANCE_FOUND`, and the development's compliance axis moves `RESTRICTED` → `NONCOMPLIANT`. That development transition moves every credit allocation of the development sitting in `ISSUED` to `RECAPTURE_PENDING` and stamps its `recapture_amount_cents`: the **recapture exposure** is the allocation's `annual_credit_cents` multiplied by the `shortfall_bps` of the single report that triggered the finding, divided by 10,000, rounded half up to whole cents — earlier reports do not accumulate into it. That allocation transition in turn moves every `ACCEPTED` delivery of the allocation to `RECAPTURE_FLAGGED`; a flagged delivery keeps counting toward the allocation's `delivered_credit_cents` while flagged."
        PRD: "Which branch is admissible is decided by the computed shortfall rather than by the reviewer's preference: `CLEARED` requires `shortfall_bps` to be exactly zero, and `NONCOMPLIANCE` requires `shortfall_bps` to be greater than zero."

        Design: Difficulty/transitive_cascade/noncompliance_finding_cascades_project_then_credit_allocation_then_accepted_delivery
        """
        deal = fixtures.ten_unit_deal(
            api,
            stage=fixtures.setup_accepted_delivery,
            delivery_overrides={
                "requested_credit_cents": 20000000,
                "capital_contribution_cents": 17000000,
            },
        )
        assert_fields(
            deal.credit_allocation,
            "credit_allocation",
            status="ISSUED",
            annual_credit_cents=5596471,
            total_credit_cents=55964710,
            recapture_amount_cents=0,
        )
        assert_fields(
            deal.delivery, "delivery", status="ACCEPTED", delivered_credit_cents=20000000
        )

        fixtures.setup_converted_bond(api, deal)
        assert_fields(
            deal.project,
            "project",
            development_status="STABILIZED",
            compliance_status="RESTRICTED",
        )

        report = fixtures.file_compliance_report(
            api,
            deal,
            reporting_year=2027,
            restricted_units_occupied=3,
            total_units_occupied=9,
            average_ami_percent=60,
        )
        assert_fields(
            report,
            "compliance_report",
            status="SUBMITTED",
            achieved_set_aside_bps=3000,
            shortfall_bps=1000,
        )

        found = fixtures.review_compliance_report(
            api,
            deal,
            2027,
            finding="NONCOMPLIANCE",
            finding_notes=(
                "Only three of the four restricted units were occupied by "
                "qualifying households"
            ),
        )
        assert_fields(found, "compliance_report", status="NONCOMPLIANCE_FOUND")

        assert_fields(
            deal.project,
            "project",
            compliance_status="NONCOMPLIANT",
            development_status="STABILIZED",
        )
        assert_fields(
            fixtures.read_credit_allocation(api, deal),
            "credit_allocation",
            status="RECAPTURE_PENDING",
            recapture_amount_cents=559647,
            delivered_credit_cents=20000000,
        )
        assert_fields(
            fixtures.read_delivery(api, deal), "delivery", status="RECAPTURE_FLAGGED"
        )
        assert_fields(
            fixtures.read_investor(api, deal),
            "investor",
            total_credit_accepted_cents=20000000,
        )


class TestInspectionWindowGeometry:
    """Closed intervals with a fourteen-day buffer on each side of the new window."""

    def test_inspection_windows_are_closed_and_buffered_so_a_fourteen_day_gap_still_conflicts(
        self, api
    ):
        """One scheduled window, then three candidates separated by 14, 15 and 14 days.

        These intervals behave differently from draw periods: the window is closed at both
        ends, and the candidate is grown by fourteen days on each side before being
        compared against the existing window as filed. A candidate starting on 2027-06-19
        therefore reaches back exactly onto the existing end of 2027-06-05 and conflicts,
        while one starting a single day later clears. The mirror case proves the buffer is
        symmetric rather than forward-looking: a candidate ending 2027-05-18 reaches
        forward exactly onto the existing start of 2027-06-01 and conflicts too.

        PRD: "Inspection windows are **closed** intervals, and unlike draw periods, adjacency is a conflict here. A new window, expanded by fourteen days on each side, must not intersect the unexpanded closed window of any existing inspection of the same development whose `status` is `SCHEDULED` or `COMPLETED`; a window that has lapsed into `MISSED` likewise continues to reserve the same fourteen-day buffer against an overlapping replacement. Two separated windows therefore need a real gap of more than fourteen days between them, and a violation is `ERR_INSPECTION_WINDOW_CONFLICT`."
        PRD: "List physical inspections, optionally narrowed to one development or status. Ordered by `window_start` ascending."

        Design: Difficulty/resource_temporal_overlap/inspection_windows_are_closed_and_buffered_so_a_fourteen_day_gap_still_conflicts
        """
        deal = fixtures.ten_unit_deal(
            api,
            stage=fixtures.setup_converted_bond,
            draw_overrides={"requested_amount_cents": 120000000},
            operating_month_overrides={"occupied_units": 9},
            conversion_date="2027-04-01T00:00:00Z",
        )
        assert_fields(
            deal.bond_issue,
            "bond_issue",
            status="CONVERTED",
            dscr_basis="T3",
            dscr_bps=12000,
            min_occupancy_bps=9000,
        )
        assert_fields(deal.project, "project", development_status="STABILIZED")
        assert deal.project["compliance_start_date"].startswith("2027-04-01T00:00:00")
        assert deal.project["extended_use_end_date"].startswith("2057-04-01T00:00:00")

        first = fixtures.schedule_inspection(
            api,
            deal,
            window_start="2027-06-01T00:00:00Z",
            window_end="2027-06-05T00:00:00Z",
            inspector_name="Reyes Field Services",
        )
        assert_fields(first, "inspection", status="SCHEDULED")

        validate_error(
            api.create_physical_inspection(
                COMPLIANCE_OFFICER,
                project_id=deal.project_id,
                window_start="2027-06-19T00:00:00Z",
                window_end="2027-06-25T00:00:00Z",
                inspector_name="Reyes Field Services",
            ),
            ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT,
            409,
        )

        accepted = fixtures.schedule_inspection(
            api,
            deal,
            window_start="2027-06-20T00:00:00Z",
            window_end="2027-06-26T00:00:00Z",
            inspector_name="Reyes Field Services",
        )
        assert_fields(accepted, "second_inspection", status="SCHEDULED")
        assert accepted["window_start"].startswith("2027-06-20T00:00:00")

        validate_error(
            api.create_physical_inspection(
                COMPLIANCE_OFFICER,
                project_id=deal.project_id,
                window_start="2027-05-04T00:00:00Z",
                window_end="2027-05-18T00:00:00Z",
                inspector_name="Reyes Field Services",
            ),
            ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT,
            409,
        )

        items, _ = assert_page(
            api.list_physical_inspections(
                COMPLIANCE_OFFICER, project_id=deal.project_id
            ),
            total_count=2,
        )
        assert_ids_equal(items, [first["id"], accepted["id"]], "inspections")
        assert_fields(
            validate_success(
                api.get_physical_inspection(first["id"], COMPLIANCE_OFFICER)
            ),
            "inspection",
            status="SCHEDULED",
        )
        assert_nulls(
            validate_success(
                api.get_physical_inspection(first["id"], COMPLIANCE_OFFICER)
            ),
            ("completed_date", "next_inspection_due_date"),
            "inspection",
        )


class TestImmediateConsistency:
    """Every derived figure and every cascade is in the body of the write that caused it."""

    def test_every_derived_field_and_cascade_is_visible_in_the_same_request_cycle(
        self, api
    ):
        """A redesignation and a pool-exhausting award, each read exactly once.

        Two shapes of immediacy are probed. The same-entity recompute: patching unit 201
        into `RESTRICTED` must return the solved rent ceiling on that very response —
        one bedroom imputes a household of two at 7,200,000, the 60 band gives 4,320,000,
        thirty percent floored is 1,296,000, a twelfth floored is 108,000, and the 12,000
        allowance leaves 96,000 under the 150,000 market rent — and the next read of the
        development must already show three restricted units, 2,550 of 3,400 restricted
        square feet, and both fractions at 7,500. The cross-entity cascade: the award that
        exhausts the pool must have already deferred the sibling's pending request and
        stalled the sibling's development by the time its own response is produced. No
        assertion here is retried against a second read.

        PRD: "Because every derived development figure is re-derived from scratch on each designation change rather than incrementally adjusted, redesignating a unit and then reverting it restores the prior applicable fraction exactly."
        PRD: "The `utility_allowance_cents` is subtracted from that AMI-derived gross ceiling and from nothing else — it is never subtracted from market rent. The smaller of the utility-adjusted AMI ceiling and the unit's `market_rent_cents` is taken."
        PRD: "Every allocation create, decision, revision, return, expiry and release re-derives all six of those figures from scratch."
        PRD: "If the re-derivation leaves the pool at `pool_status` `EXHAUSTED`, then every *other* allocation of the same pool that is still `PENDING` and whose `requested_amount_cents` exceeds the new `awardable_cents` is moved `PENDING` → `DEFERRED`. Each of those deferrals in turn increments its own development's `volume_cap_deferral_count` by 1 and sets that development's `financing_stalled` to true; and because the pool counts a request in `reserved_cents` only while it is `PENDING`, the pool's reserved figure drops by each deferred request's requested amount as well."

        Design: Corner/consistency_model/every_derived_field_and_cascade_is_visible_in_the_same_request_cycle_with_no_re_read_delay
        """
        deal = fixtures.setup_units(api)
        primary = fixtures.request_cap(api, deal, requested_amount_cents=600000000)
        assert_fields(primary, "primary_request", status="PENDING")

        sibling_project = fixtures.file_second_project(api, deal, name="Bayside Two")
        sibling_request = validate_success(
            api.create_volume_cap_allocation(
                deal.developer_headers,
                **factories.cap_request_payload(
                    sibling_project["id"],
                    deal.pool_id,
                    requested_amount_cents=100000000,
                )
            ),
            201,
        )
        assert_fields(sibling_request, "sibling_request", status="PENDING")

        patched = validate_success(
            api.patch_unit_restriction(
                deal.units["201"]["id"],
                deal.developer_headers,
                designation="RESTRICTED",
                ami_percent=60,
                utility_allowance_cents=12000,
                market_rent_cents=150000,
            )
        )
        assert_fields(
            patched,
            "unit_201",
            designation="RESTRICTED",
            restricted_rent_cents=96000,
        )

        after_patch = fixtures.read_project(api, deal)
        assert_unit_counts(after_patch, restricted=3, market=1, designated=4)
        assert_project_fractions(
            after_patch,
            unit_fraction=7500,
            floor_space_fraction=7500,
            applicable_fraction=7500,
        )
        assert_fields(after_patch, "project", set_aside_ratio_bps=7500)

        awarded = fixtures.award_allocation(
            api,
            deal,
            primary["id"],
            awarded_amount_cents=600000000,
            expiry_date="2027-06-30T00:00:00Z",
        )
        assert_fields(
            awarded,
            "primary_request",
            status="AWARDED",
            awarded_amount_cents=600000000,
        )

        assert_pool_ledger(
            deal.pool,
            reserved_cents=0,
            committed_cents=600000000,
            available_cents=0,
            awardable_cents=0,
            pool_status="EXHAUSTED",
        )
        assert_fields(
            validate_success(
                api.get_volume_cap_allocation(
                    sibling_request["id"], deal.developer_headers
                )
            ),
            "sibling_request",
            status="DEFERRED",
        )
        assert_fields(
            validate_success(
                api.get_project(sibling_project["id"], deal.developer_headers)
            ),
            "sibling_project",
            financing_stalled=True,
            volume_cap_deferral_count=1,
        )
