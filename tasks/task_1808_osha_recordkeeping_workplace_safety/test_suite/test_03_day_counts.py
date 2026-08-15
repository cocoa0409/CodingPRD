"""Day-count entries: interval validity, stored vs projected variants, caps."""
from test_helpers import (
    ApiErrorId,
    add_day_entry,
    assert_case,
    assert_day_entry,
    create_case,
    create_classified_case,
    get_case,
    get_success_data,
    set_clock,
    setup_org,
    validate_error,
    validate_success,
    void_day_entry,
)
from test_helpers.fixtures import OFFICER


class TestIntervalValidity:
    def test_day_interval_end_before_start_rejected(self, api):
        """PRD §3.3: "An `end_date` earlier than its `start_date` is rejected
        with `ERR_DAY_INTERVAL_INVALID`, as is an interval that overlaps
        another `ACTIVE` interval of the same `day_type` on the same case"

        Design: Corner/validations/day_interval_end_before_start_rejected
        """
        _, establishment, employee = setup_org(fein="03-0000022",
                                               site_name="DI Site")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-01T10:00:00Z",
            classification="JOB_TRANSFER_RESTRICTION",
            clock_iso="2026-08-01T12:00:00Z")
        resp = api.add_day_entry(
            case["id"],
            {"day_type": "RESTRICTED", "start_date": "2026-08-10",
             "end_date": "2026-08-05"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_DAY_INTERVAL_INVALID)


class TestProjectedVsRecordedVariants:
    def _case_with_running_entry(self, fein="98-7654321"):
        _, establishment, employee = setup_org(
            fein=fein, site_name="Warehouse 7", naics_code="493110",
            state_code="TX", size_class="SMALL")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-05T09:00:00Z",
            classification="JOB_TRANSFER_RESTRICTION",
            clock_iso="2026-08-05T12:00:00Z", description="Shoulder strain",
            body_part="shoulder")
        entry = add_day_entry(case["id"], "RESTRICTED", "2026-08-10",
                              "2026-08-30")
        return case, entry

    def test_projected_restricted_truncates_at_clock(self, api):
        """PRD §3.3: "For any `ACTIVE` entry whose `end_date` lies strictly
        after the logical clock's current date, the projection counts only the
        days from `start_date` through the clock date inclusive — an
        accrual-to-date view — while entries already ended count in full; the
        combined 180-day ceiling with days-away precedence is applied after
        this truncation."
        PRD §3.3: "the entry's `calendar_days` is the number of calendar days
        the interval spans counting both endpoints — a Monday-through-Friday
        interval counts five days, and counting is by calendar day rather than
        scheduled work day."

        Design: Difficulty/dual_variant_calc/day_count_projected_vs_recorded
        """
        case, entry = self._case_with_running_entry()
        set_clock("2026-08-20T00:00:00Z")

        read = get_case(case["id"])
        assert_case(read)
        assert read["restricted_days_count"] == 21, (
            "RECORDED variant stores the full 2026-08-10..2026-08-30 span")
        assert read["projected_restricted_days_count"] == 11, (
            "PROJECTED_FINAL accrues 2026-08-10..2026-08-20 inclusive")
        assert read["day_count_closed"] is False

        entries = get_success_data(api.list_day_entries(case["id"], OFFICER))
        assert_day_entry(entries[0])
        assert entries[0]["calendar_days"] == 21
        assert read["restricted_days_count"] != read[
            "projected_restricted_days_count"], (
            "Stored and projected variants diverge while the entry runs")

    def test_projected_agrees_with_recorded_after_entry_ends(self, api):
        """PRD §3.3: "Projections are never stored and never feed the annual
        summary, so identical entries can yield projected figures below the
        recorded ones while an interval is still running, and the two variants
        agree once every entry's end lies in the past."

        Design: Difficulty/dual_variant_calc/day_count_projected_vs_recorded
        """
        case, _ = self._case_with_running_entry(fein="98-7654322")
        set_clock("2026-08-31T00:00:00Z")

        read = get_case(case["id"])
        assert read["restricted_days_count"] == 21
        assert read["projected_restricted_days_count"] == 21, (
            "Once the entry's end lies in the past the variants agree")


class TestSameTypeOverlap:
    def _restricted_case_with_entry(self, fein="55-9990001"):
        _, establishment, employee = setup_org(fein=fein, site_name="Bakery 2",
                                               naics_code="311811",
                                               state_code="IL",
                                               size_class="SMALL")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-04T10:00:00Z",
            classification="JOB_TRANSFER_RESTRICTION",
            clock_iso="2026-08-05T08:00:00Z", description="Wrist strain",
            body_part="wrist")
        add_day_entry(case["id"], "RESTRICTED", "2026-08-10", "2026-08-12")
        return case

    def test_touching_same_type_intervals_rejected(self, api):
        """PRD §3.3: "An `end_date` earlier than its `start_date` is rejected
        with `ERR_DAY_INTERVAL_INVALID`, as is an interval that overlaps
        another `ACTIVE` interval of the same `day_type` on the same case"
        PRD §3.3: "the entry's `calendar_days` is the number of calendar days
        the interval spans counting both endpoints"

        Design: Difficulty/resource_temporal_overlap/day_entry_same_type_overlap_rejected_but_cross_type_allowed
        """
        case = self._restricted_case_with_entry()
        resp = api.add_day_entry(
            case["id"],
            {"day_type": "RESTRICTED", "start_date": "2026-08-12",
             "end_date": "2026-08-15"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_DAY_INTERVAL_INVALID)

    def test_cross_type_overlap_allowed(self, api):
        """PRD §3.3: "raw overlapping accrual across the two types is
        tolerated transiently because the combined ceiling is applied only at
        rollup."
        PRD §3.3: "the entry's `calendar_days` is the number of calendar days
        the interval spans counting both endpoints — a Monday-through-Friday
        interval counts five days, and counting is by calendar day rather than
        scheduled work day."

        Design: Difficulty/resource_temporal_overlap/day_entry_same_type_overlap_rejected_but_cross_type_allowed
        """
        case = self._restricted_case_with_entry(fein="55-9990002")
        resp = api.add_day_entry(
            case["id"],
            {"day_type": "DAYS_AWAY", "start_date": "2026-08-10",
             "end_date": "2026-08-12"},
            OFFICER)
        entry = validate_success(resp, 201)
        assert_day_entry(entry)
        assert entry["calendar_days"] == 3, (
            "2026-08-10..2026-08-12 spans three calendar days")


class TestVoidInvariant:
    def _restricted_case(self, fein="55-4564567"):
        _, establishment, employee = setup_org(fein=fein, site_name="Press 1",
                                               naics_code="323111",
                                               state_code="NY",
                                               size_class="STANDARD")
        return create_classified_case(
            establishment["id"], employee["id"], "2026-08-01T10:00:00Z",
            classification="JOB_TRANSFER_RESTRICTION",
            clock_iso="2026-08-03T08:00:00Z", description="Finger pinch",
            body_part="finger")

    def test_day_entry_add_accumulates_totals(self, api):
        """PRD §3.3: "The raw days-away figure is the sum of `calendar_days`
        over the case's `ACTIVE` entries of type `DAYS_AWAY`, and the raw
        restricted figure is the analogous sum over `RESTRICTED` entries."

        Design: Difficulty/compensating_invariant/day_entry_void_preserves_case_day_totals
        """
        case = self._restricted_case()
        baseline = get_case(case["id"])
        assert baseline["restricted_days_count"] == 0
        assert baseline["days_away_count"] == 0

        add_day_entry(case["id"], "RESTRICTED", "2026-08-04", "2026-08-07")
        mid = get_case(case["id"])
        assert mid["restricted_days_count"] == 4, (
            "2026-08-04..2026-08-07 inclusive adds four restricted days")
        assert mid["days_away_count"] == 0

    def test_day_entry_void_restores_pre_add_totals(self, api):
        """PRD §3.3: "Entries are born `ACTIVE`, and voiding one moves it to
        `VOIDED` and excludes it from every rollup."

        Design: Difficulty/compensating_invariant/day_entry_void_preserves_case_day_totals
        """
        case = self._restricted_case(fein="55-4564568")
        entry = add_day_entry(case["id"], "RESTRICTED", "2026-08-04",
                              "2026-08-07")
        assert get_case(case["id"])["restricted_days_count"] == 4

        voided = void_day_entry(case["id"], entry["id"])
        assert_day_entry(voided)
        assert voided["status"] == "VOIDED"

        end = get_case(case["id"])
        assert end["restricted_days_count"] == 0, (
            "Voiding the only entry restores the pre-add total exactly")
        assert end["days_away_count"] == 0
