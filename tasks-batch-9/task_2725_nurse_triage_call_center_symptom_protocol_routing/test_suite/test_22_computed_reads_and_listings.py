"""Zero-activity projections and the two heavily filtered listings."""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_percentage,
    assert_whole_minutes,
)


@pytest.fixture
def brand_new_practice_with_no_activity(world):
    """One ACTIVE practice and nothing else in the system at all."""
    world.set_clock("2026-08-03T14:30:00Z")
    world.create_practice(audit_period_start_utc="2026-08-01T00:00:00Z")
    return world.practice_id


class TestZeroActivityProjections:
    def test_the_compliance_summary_reports_zero_rates_not_a_division_error(
        self, world, brand_new_practice_with_no_activity
    ):
        """PRD §3.10: "Each count becomes a rate the same way: when `audited_count` is
        zero the rate is 0.0 and never a division error".

        Design: Corner/endpoints/zero_activity_practice_reads_return_zeroed_projections_not_errors
        """
        summary = world.compliance_summary(brand_new_practice_with_no_activity)

        assert summary["audited_count"] == 0
        assert_percentage(summary["concordance_rate_strict_pct"], 0.0, "strict rate")
        assert_percentage(
            summary["concordance_rate_band_tolerant_pct"], 0.0, "band-tolerant rate"
        )
        assert summary["variance_severity_points_total"] == 0
        assert summary["compliance_posture"] == "NORMAL"

    def test_the_after_hours_invoice_totals_nothing_at_the_zero_percent_tier(
        self, world, brand_new_practice_with_no_activity
    ):
        """PRD §3.10: "With no escalated callbacks at all the gross and the credit are
        both zero and the total equals the accrued advice fees exactly."

        Design: Corner/endpoints/zero_activity_practice_reads_return_zeroed_projections_not_errors
        """
        pid = brand_new_practice_with_no_activity

        invoice = get_success_data(
            world.api.get_after_hours_invoice(pid, world.liaison_headers(pid))
        )

        assert_cents(invoice["advice_subtotal_cents"], 0, "advice_subtotal_cents")
        assert_whole_minutes(
            invoice["billed_advice_minutes_total"], 0, "billed_advice_minutes_total"
        )
        assert invoice["escalated_callback_count"] == 0
        assert_cents(invoice["escalation_gross_cents"], 0, "escalation_gross_cents")
        assert invoice["coverage_credit_pct"] == 0
        assert_cents(invoice["coverage_credit_cents"], 0, "coverage_credit_cents")
        assert_cents(invoice["invoice_total_cents"], 0, "invoice_total_cents")

    def test_zero_demand_staffing_is_adequate_by_definition(
        self, world, brand_new_practice_with_no_activity
    ):
        """PRD §3.10: "`adequacy_ratio_pct` is 100.0 whenever `required_nurse_minutes`
        is zero — the zero-demand case is always fully adequate and never a division
        error".

        Design: Corner/endpoints/zero_activity_practice_reads_return_zeroed_projections_not_errors
        """
        readout = world.staffing_adequacy(
            state_code="CA",
            window_start_utc="2026-08-03T12:00:00Z",
            window_end_utc="2026-08-03T20:00:00Z",
        )

        assert readout["offered_call_count"] == 0
        assert_whole_minutes(
            readout["required_nurse_minutes"], 0, "required_nurse_minutes"
        )
        assert_whole_minutes(
            readout["scheduled_nurse_minutes"], 0, "scheduled_nurse_minutes"
        )
        assert_percentage(readout["adequacy_ratio_pct"], 100.0, "adequacy_ratio_pct")
        assert readout["staffing_posture"] == "ADEQUATE"
        assert readout["licensed_nurse_count"] == 0


@pytest.fixture
def four_calls_across_two_practices(world):
    """Three INTAKE calls on the first practice and one on the second."""
    world.set_clock("2026-08-03T14:30:00Z")
    practice_1 = world.create_practice(name="Northside Family Health")
    practice_2 = get_success_data(
        world.api.create_practice(
            f.practice_payload(
                name="Lakeside Pediatrics", per_minute_rate_millicents=3900
            ),
            world.admin,
        )
    )
    first_three = [
        world.open_call(
            practice_1["id"],
            caller_name=name,
            caller_phone=phone,
            reason_text=reason,
        )
        for name, phone, reason in (
            ("Dana Reyes", "+14155550100", "call one"),
            ("Ada Kim", "+14155550102", "call two"),
            ("Ivo Cruz", "+14155550103", "call three"),
        )
    ]
    fourth = world.open_call(
        practice_2["id"],
        caller_name="Rey Osei",
        caller_phone="+14155550104",
        reason_text="other practice",
    )
    return practice_1, practice_2, first_three, fourth


class TestTriageCallListing:
    def test_the_practice_filter_pages_without_leaking_across_practices(
        self, world, four_calls_across_two_practices
    ):
        """PRD §2.3: "The `meta` object of a list response carries `limit` and `offset`
        as they were resolved for the request, `total_count` as the number of records
        matching the filters before paging, and `has_more` as a boolean that is true
        exactly when `offset` plus the number of records returned is still less than
        `total_count`."

        Design: Corner/endpoints/triage_call_listing_filters_by_practice_and_pages_deterministically
        """
        practice_1, _, _, _ = four_calls_across_two_practices

        page_one, page_one_meta = validate_paginated(
            world.api.list_triage_calls(
                world.admin,
                {"practice_id": practice_1["id"], "limit": 2, "offset": 0},
            )
        )
        page_two, page_two_meta = validate_paginated(
            world.api.list_triage_calls(
                world.admin,
                {"practice_id": practice_1["id"], "limit": 2, "offset": 2},
            )
        )

        assert page_one_meta["total_count"] == 3
        assert page_one_meta["has_more"] is True
        assert len(page_one) == 2
        assert all(row["practice_id"] == practice_1["id"] for row in page_one)
        assert page_two_meta["total_count"] == 3
        assert page_two_meta["has_more"] is False
        assert len(page_two) == 1
        assert page_one[0]["id"] != page_two[0]["id"]

    def test_the_other_practice_sees_only_its_own_single_call(
        self, world, four_calls_across_two_practices
    ):
        """PRD §2.3: "List results are ordered by `created_at` ascending — oldest record
        first — and that ordering is applied after all filters and before `limit` and
        `offset` are applied."

        Design: Corner/endpoints/triage_call_listing_filters_by_practice_and_pages_deterministically
        """
        _, practice_2, _, fourth = four_calls_across_two_practices

        rows, meta = validate_paginated(
            world.api.list_triage_calls(world.admin, {"practice_id": practice_2["id"]})
        )

        assert meta["total_count"] == 1
        assert rows[0]["id"] == fourth["id"]

    def test_the_status_filter_alone_fits_all_four_on_the_default_page(
        self, world, four_calls_across_two_practices
    ):
        """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may
        not be smaller than 1, and may not be larger than 100."

        Design: Corner/endpoints/triage_call_listing_filters_by_practice_and_pages_deterministically
        """
        rows, meta = validate_paginated(
            world.api.list_triage_calls(world.admin, {"status": "INTAKE"})
        )

        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(rows) == 4


@pytest.fixture
def one_high_risk_task_due_at_half_past_four(world):
    """An acuity 70 ED_NOW disposition and the single HIGH_RISK task it owes."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    _, _, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    return disposition


class TestCallbackTaskListing:
    def test_the_due_before_horizon_is_a_strict_upper_bound(
        self, world, one_high_risk_task_due_at_half_past_four
    ):
        """PRD §3.8: "and by `due_before_utc`, which restricts results to tasks falling
        due before a supplied instant."

        Design: Corner/endpoints/callback_task_listing_filters_by_risk_class_and_due_before
        """
        disposition = one_high_risk_task_due_at_half_past_four

        inside, inside_meta = validate_paginated(
            world.api.list_callback_tasks(
                world.admin,
                {
                    "practice_id": world.practice_id,
                    "risk_class": "HIGH_RISK",
                    "due_before_utc": "2026-08-03T17:00:00Z",
                },
            )
        )
        _, outside_meta = validate_paginated(
            world.api.list_callback_tasks(
                world.admin,
                {
                    "practice_id": world.practice_id,
                    "risk_class": "HIGH_RISK",
                    "due_before_utc": "2026-08-03T16:00:00Z",
                },
            )
        )

        assert inside_meta["total_count"] == 1
        assert_instant(inside[0]["due_by_utc"], "2026-08-03T16:30:00Z", "due_by_utc")
        assert inside[0]["disposition_id"] == disposition["id"]
        assert inside[0]["practice_id"] == world.practice_id
        assert inside[0]["assigned_nurse_id"] == world.nurse_id("nurse_a")
        assert inside[0]["max_attempts"] == 3
        assert outside_meta["total_count"] == 0

    def test_asking_for_the_wrong_risk_class_returns_nothing(
        self, world, one_high_risk_task_due_at_half_past_four
    ):
        """PRD §3.8: "They may be narrowed by `practice_id`, by `disposition_id`, by
        `assigned_nurse_id`, by `verified_by_nurse_id`, by `status`, by `risk_class`, and
        by `due_before_utc`".

        Design: Corner/endpoints/callback_task_listing_filters_by_risk_class_and_due_before
        """
        _, standard_meta = validate_paginated(
            world.api.list_callback_tasks(
                world.admin,
                {"practice_id": world.practice_id, "risk_class": "STANDARD"},
            )
        )
        _, mine_meta = validate_paginated(
            world.api.list_callback_tasks(
                world.admin,
                {
                    "assigned_nurse_id": world.nurse_id("nurse_a"),
                    "status": "PENDING",
                },
            )
        )

        assert standard_meta["total_count"] == 0
        assert mine_meta["total_count"] == 1
