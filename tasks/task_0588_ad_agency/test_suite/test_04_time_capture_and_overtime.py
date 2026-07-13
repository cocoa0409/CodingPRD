"""Time capture: the diary rules, the daily and labour ceilings, overtime pricing, utilization."""

from test_helpers import (
    ApiErrorId,
    assert_time_entry,
    create_time_entry_payload,
    log_and_approve_time,
    log_time,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDailyMinuteCap:
    """Difficulty: boundary_precision_check / daily_minutes_cap_600_passes_601_fails."""

    @staticmethod
    def _setup():
        base = setup_base()
        log_time(base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T17:00:00Z")  # 480 minutes
        return base

    def test_exactly_six_hundred_minutes_in_a_day_is_accepted(self, api):
        """PRD §3.5: "Next, no one may log more than ten hours in a single UTC day: the sum of
        `minutes` across every entry of that `staff_id` on that `work_date` whose status is
        `SUBMITTED`, `APPROVED` or `BILLED`, plus the new entry's minutes, must not exceed 600
        minutes. Non-billable entries count toward this ceiling. Exactly 600 minutes is
        accepted; 601 is rejected with `ERR_DAILY_MINUTES_EXCEEDED`."
        PRD §3.5: "When the entry is accepted, it is stored with status `SUBMITTED`,
        `approved_by_staff_id` null, and `regular_minutes`, `overtime_minutes` and
        `billable_amount_cents` all 0."

        Design: Difficulty/boundary_precision_check/daily_minutes_cap_600_passes_601_fails
        """
        base = self._setup()

        resp = api.create_time_entry(
            create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                      "2026-06-02T17:00:00Z", "2026-06-02T19:00:00Z"),
            base["dana_headers"],
        )
        data = validate_success(resp, 201)

        assert_time_entry(data)
        assert data["minutes"] == 120, "480 already logged + 120 == exactly the 600-minute cap"
        assert data["status"] == "SUBMITTED"
        assert data["approved_by_staff_id"] is None
        assert data["regular_minutes"] == 0
        assert data["overtime_minutes"] == 0
        assert data["billable_amount_cents"] == 0

    def test_the_six_hundred_and_first_minute_breaches_the_daily_cap(self, api):
        """PRD §3.5: "Next, no one may log more than ten hours in a single UTC day: the sum of
        `minutes` across every entry of that `staff_id` on that `work_date` whose status is
        `SUBMITTED`, `APPROVED` or `BILLED`, plus the new entry's minutes, must not exceed 600
        minutes. Non-billable entries count toward this ceiling. Exactly 600 minutes is
        accepted; 601 is rejected with `ERR_DAILY_MINUTES_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/daily_minutes_cap_600_passes_601_fails
        """
        base = self._setup()
        log_time(base, "dana", "2026-06-02T17:00:00Z", "2026-06-02T19:00:00Z")  # now at 600

        resp = api.create_time_entry(
            create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                      "2026-06-02T19:00:00Z", "2026-06-02T19:01:00Z"),
            base["dana_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DAILY_MINUTES_EXCEEDED.value)
        assert resp.status_code == 422

        _rows, meta = validate_paginated(api.list_time_entries(
            base["admin_headers"], params={"staff_id": base["dana_id"]}))
        assert meta["total_count"] == 2, "the 601st minute must not create a row"


class TestTimeEntryHalfOpenInterval:
    """Difficulty: resource_temporal_overlap /
    time_entry_half_open_interval_allows_touching_endpoints_on_staff."""

    @staticmethod
    def _setup():
        base = setup_base()
        log_time(base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T12:00:00Z")  # 180 minutes
        return base

    def test_an_interval_that_straddles_an_existing_entry_collides(self, api):
        """PRD §3.5: "Two intervals collide when the new entry starts strictly before the
        existing entry ends and the existing entry starts strictly before the new entry ends;
        entries that merely touch — where one starts at the exact instant the other ends — do
        not collide. A collision is rejected with `ERR_TIME_ENTRY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/time_entry_half_open_interval_allows_touching_endpoints_on_staff
        """
        base = self._setup()

        resp = api.create_time_entry(
            create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                      "2026-06-02T11:30:00Z", "2026-06-02T13:00:00Z"),
            base["dana_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TIME_ENTRY_OVERLAP.value)
        assert resp.status_code == 409

    def test_an_interval_that_merely_touches_an_existing_entry_is_accepted(self, api):
        """PRD §3.5: "Two intervals collide when the new entry starts strictly before the
        existing entry ends and the existing entry starts strictly before the new entry ends;
        entries that merely touch — where one starts at the exact instant the other ends — do
        not collide. A collision is rejected with `ERR_TIME_ENTRY_OVERLAP`."
        PRD §3.5: "`estimated_amount_cents` is then the entry's minutes multiplied by that
        pinned hourly rate, divided by 60, rounded half up to a whole cent."

        Design: Difficulty/resource_temporal_overlap/time_entry_half_open_interval_allows_touching_endpoints_on_staff
        """
        base = self._setup()

        resp = api.create_time_entry(
            create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                      "2026-06-02T12:00:00Z", "2026-06-02T13:00:00Z"),
            base["dana_headers"],
        )
        data = validate_success(resp, 201)

        assert data["minutes"] == 60
        assert data["estimated_amount_cents"] == 20_000

        _rows, meta = validate_paginated(api.list_time_entries(
            base["admin_headers"], params={"staff_id": base["dana_id"]}))
        assert meta["total_count"] == 2


class TestUtilizationDualVariant:
    """Difficulty: dual_variant_calc / staff_utilization_capacity_vs_logged_divergence."""

    @staticmethod
    def _setup():
        base = setup_base()
        # 480 billable minutes, approved.
        log_and_approve_time(base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T17:00:00Z")
        # 180 non-billable minutes, submitted.
        log_time(base, "dana", "2026-06-03T09:00:00Z", "2026-06-03T12:00:00Z", billable=False)
        # 120 billable minutes, never approved.
        log_time(base, "dana", "2026-06-04T09:00:00Z", "2026-06-04T11:00:00Z")
        return base

    def test_capacity_and_logged_denominators_disagree_on_identical_data(self, api):
        """PRD §3.9: "`capacity_minutes` is the number of UTC calendar dates in the window that
        fall on a Monday, Tuesday, Wednesday, Thursday or Friday, multiplied by that person's
        `standard_daily_capacity_minutes` — weekends contribute no capacity. `billable_minutes`
        is the sum of `minutes` across the person's time entries whose `work_date` falls in the
        window, that are billable, and whose status is `APPROVED` or `BILLED`. `logged_minutes`
        is the sum of `minutes` across the person's time entries whose `work_date` falls in the
        window and whose status is `SUBMITTED`, `APPROVED` or `BILLED` — every row, regardless
        of the `billable` flag."
        PRD §3.9: "`utilization_pct_capacity_based` is `billable_minutes` divided by
        `capacity_minutes`, multiplied by 100 and rounded half up to one decimal place — or 0.0
        when `capacity_minutes` is zero."
        PRD §3.9: "`utilization_pct_logged_based` is `billable_minutes` divided by
        `logged_minutes`, multiplied by 100 and rounded half up to one decimal place — or 0.0
        when `logged_minutes` is zero."

        Design: Difficulty/dual_variant_calc/staff_utilization_capacity_vs_logged_divergence
        """
        base = self._setup()

        data = validate_success(api.get_staff_utilization(
            base["dana_id"], base["admin_headers"],
            params={"period_start": "2026-06-01", "period_end": "2026-06-08"},
        ))

        assert data["capacity_minutes"] == 2400, "five weekdays x 480 contracted minutes"
        assert data["billable_minutes"] == 480
        assert data["logged_minutes"] == 780
        assert data["utilization_pct_capacity_based"] == 20.0
        assert data["utilization_pct_logged_based"] == 61.5
        assert data["utilization_pct_capacity_based"] != data["utilization_pct_logged_based"]

    def test_billed_amount_and_effective_rate_count_only_approved_billable_rows(self, api):
        """PRD §3.9: "`billed_amount_cents` is the sum of `billable_amount_cents` over the same
        rows that `billable_minutes` counts."
        PRD §3.9: "Alongside them, `effective_billable_rate_cents_per_hour` is
        `billed_amount_cents` multiplied by 60 and divided by `billable_minutes`, rounded half
        up to a whole cent — or 0 when `billable_minutes` is zero."
        PRD §3.5: "If `billable` is false, both `pinned_rate_cents_per_hour` and
        `estimated_amount_cents` are 0."

        Design: Difficulty/dual_variant_calc/staff_utilization_capacity_vs_logged_divergence
        """
        base = self._setup()

        data = validate_success(api.get_staff_utilization(
            base["dana_id"], base["admin_headers"],
            params={"period_start": "2026-06-01", "period_end": "2026-06-08"},
        ))
        assert data["staff_id"] == base["dana_id"]
        assert data["billed_amount_cents"] == 160_000
        assert data["effective_billable_rate_cents_per_hour"] == 20_000

        rows, _meta = validate_paginated(api.list_time_entries(
            base["admin_headers"], params={"staff_id": base["dana_id"]}))
        non_billable = next(r for r in rows if r["billable"] is False)
        assert non_billable["estimated_amount_cents"] == 0
        assert non_billable["pinned_rate_cents_per_hour"] == 0


def test_overtime_threshold_splits_a_straddling_entry_and_rounds_each_leg(api):
    """PRD §3.5: "The regular allowance for the day is eight hours, that is 480 minutes.
    `regular_minutes` is therefore that 480-minute threshold minus the prior minutes, clamped so
    that it never exceeds this entry's own minutes and never falls below zero; `overtime_minutes`
    is the entry's minutes less `regular_minutes`."
    PRD §3.5: "`billable_amount_cents` is then assembled from the two legs, each rounded on its
    own before they are added: the regular leg is `regular_minutes` multiplied by
    `pinned_rate_cents_per_hour` divided by 60, rounded half up to a whole cent; the overtime leg
    is `overtime_minutes` multiplied by `pinned_rate_cents_per_hour`, multiplied by the overtime
    multiplier of 1.5 (time-and-a-half), divided by 60, and rounded half up to a whole cent; and
    `billable_amount_cents` is the sum of the two rounded results."
    PRD §3.5: "Approval moves the entry `SUBMITTED → APPROVED`, stamps the approver's
    `X-User-ID` into `approved_by_staff_id`, and splits the entry's minutes into a regular leg
    and an overtime leg."

    Design: Corner/calculations/overtime_threshold_splits_a_straddling_time_entry
    """
    base = setup_base()

    first = log_and_approve_time(base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T16:50:00Z")
    assert first["regular_minutes"] == 470
    assert first["overtime_minutes"] == 0
    assert first["billable_amount_cents"] == 156_667

    second = log_time(base, "dana", "2026-06-02T16:50:00Z", "2026-06-02T17:50:00Z")
    assert second["minutes"] == 60
    assert second["estimated_amount_cents"] == 20_000, "the estimate carries no overtime uplift"

    approved = validate_success(api.approve_time_entry(second["id"], base["am_headers"]))
    assert approved["regular_minutes"] == 10, "480 - 470 prior minutes"
    assert approved["overtime_minutes"] == 50
    assert approved["billable_amount_cents"] == 28_333, "3333 regular leg + 25000 overtime leg"
    assert approved["approved_by_staff_id"] == base["ravi_id"]


def test_labour_cap_accepts_an_exactly_equal_sum_and_rejects_the_next_entry(api):
    """PRD §3.5: "Finally, the statement of work's labour budget must hold: the SOW's
    `consumed_labor_cents` before this request, plus the new entry's `estimated_amount_cents`,
    must not exceed `labor_cap_cents`. A sum exactly equal to the cap is accepted; anything
    strictly greater is rejected with `ERR_SOW_LABOR_CAP_EXCEEDED`."
    PRD §3.5: "The owning SOW's `consumed_labor_cents` is then recomputed as the sum of
    `estimated_amount_cents` over every time entry whose campaign belongs to that SOW and whose
    status is `SUBMITTED`, `APPROVED` or `BILLED`"

    Design: Corner/calculations/sow_labor_cap_exactly_equal_is_accepted
    """
    base = setup_base(labor_cap_cents=20_000, sow_title="Tight SOW")

    accepted = validate_success(
        api.create_time_entry(
            create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                      "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z"),
            base["dana_headers"],
        ),
        201,
    )
    assert accepted["estimated_amount_cents"] == 20_000

    sow = validate_success(api.get_sow(base["sow_id"], base["admin_headers"]))
    assert sow["consumed_labor_cents"] == 20_000, "exactly equal to the cap is accepted"

    resp = api.create_time_entry(
        create_time_entry_payload(base["campaign_id"], base["dana_id"],
                                  "2026-06-02T10:00:00Z", "2026-06-02T10:30:00Z"),
        base["dana_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SOW_LABOR_CAP_EXCEEDED.value)
    assert resp.status_code == 422

    sow_after = validate_success(api.get_sow(base["sow_id"], base["admin_headers"]))
    assert sow_after["consumed_labor_cents"] == 20_000, "the rejected entry booked nothing"


def test_time_entry_list_applies_the_staff_filter_before_paginating(api):
    """PRD §3.5: "Time entries may be listed and filtered by `campaign_id`, by `staff_id`, by
    `approved_by_staff_id`, and by `status`."
    PRD §2.3: "List results are always returned in ascending `created_at` order — the oldest
    resource first — so that paging through a collection is stable. On every list response the
    `meta` object carries `limit`, `offset`, `total_count` (the number of rows matching the
    filters before pagination is applied) and `has_more` (true when rows remain beyond the
    current window). Filters offered by individual list endpoints, described in section 3
    alongside the resources they narrow, are applied before pagination."

    Design: Corner/endpoints/list_time_entries_filter_and_pagination_interact
    """
    base = setup_base()
    log_time(base, "dana", "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")
    log_time(base, "dana", "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z")
    log_time(base, "dana", "2026-06-04T09:00:00Z", "2026-06-04T10:00:00Z")
    log_time(base, "ravi", "2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z")

    page_one, meta_one = validate_paginated(api.list_time_entries(
        base["admin_headers"], params={"staff_id": base["dana_id"], "limit": 2, "offset": 0}))
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(api.list_time_entries(
        base["admin_headers"], params={"staff_id": base["dana_id"], "limit": 2, "offset": 2}))
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    for row in page_one + page_two:
        assert row["staff_id"] == base["dana_id"], "Ravi's entry must never appear"
