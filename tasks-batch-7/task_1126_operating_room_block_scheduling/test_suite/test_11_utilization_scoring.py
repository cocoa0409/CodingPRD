"""Utilization scoring: prime vs raw variants, boundaries, input-set filtering."""
from test_helpers import (
    TEST_USERS,
    CLOCK_AFTER_WEEK,
    assert_committee_review,
    assert_utilization_report,
    make_block,
    make_case,
    make_coverage,
    make_line,
    make_room,
    make_surgeon,
    make_surgeon_headers,
    schedule_case_in_block,
    setup_active_block_with_case,
    setup_deficient_review,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _reports(api, line_id):
    return validate_paginated(api.list_utilization_reports(line_id, ADMIN))


def _reviews(api, line_id, **extra):
    params = {"service_line_id": line_id}
    params.update(extra)
    return validate_paginated(api.list_committee_reviews(ADMIN, params=params))


class TestPrimeVsRawDivergence:
    def _setup_divergence(self, api):
        """Weekday block (prime) plus Saturday block (zero prime); both counted raw."""
        line = make_line(name="CARD", target=75)
        surgeon = make_surgeon(line["id"], full_name="Dr. P")
        room1 = make_room("OR1")
        room2 = make_room("OR2")
        make_coverage(room1["id"], "2026-05-01", 420, 1200)  # Friday
        make_coverage(room2["id"], "2026-05-02", 420, 1200)  # Saturday
        block_a = make_block(line["id"], room1["id"], date="2026-05-01",
                             start_minute=420, end_minute=1020, activate=True)
        block_b = make_block(line["id"], room2["id"], date="2026-05-02",
                             start_minute=480, end_minute=960, activate=True)
        for _ in range(3):
            schedule_case_in_block(
                make_case(surgeon["id"])["id"], block_a["id"], surgeon["id"]
            )
        for _ in range(4):
            schedule_case_in_block(
                make_case(surgeon["id"], priority="ADD_ON")["id"],
                block_b["id"], surgeon["id"],
            )
        validate_success(api.set_clock(CLOCK_AFTER_WEEK, ADMIN), 200)
        return line, surgeon

    def test_prime_and_raw_variants_diverge(self, api):
        """PRD §3.7: "The prime-time variant is the governance metric:
        `allocated_prime_minutes` sums, over the line's blocks dated in the period
        with any status other than `CANCELLED`, each block's prime-window overlap
        computed on its original window; `occupied_prime_minutes` sums, over cases
        in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` status scheduled in those
        blocks, the prime-window overlap of each case's scheduled span — `BUMPED`
        and `CANCELLED` cases are excluded everywhere."
        PRD §3.7: "The raw variant is the reporting metric: its denominator sums the
        `original_minutes` of the same block set, and its numerator sums the
        scheduled span — `scheduled_end_minute` minus `scheduled_start_minute` — of
        every case by the line's surgeons dated in the period in those same three
        statuses, regardless of room, hour, priority, or whether the case came from
        a block, open time, or an emergent placement".

        Design: Difficulty/dual_variant_calc/utilization_prime_vs_raw_divergence
        """
        line, _ = self._setup_divergence(api)
        result = validate_success(api.scoring_run(ADMIN), 200)
        assert result["reports_created"] == 1
        assert result["reviews_created"] == 1  # 45.00 < 75

        reports, meta = _reports(api, line["id"])
        assert meta["total_count"] == 1
        report = reports[0]
        assert_utilization_report(report)
        assert report["allocated_prime_minutes"] == 600  # weekday [420,1020)
        assert report["occupied_prime_minutes"] == 270   # 3 x 90, Saturday = 0
        assert report["prime_time_utilization_pct"] == 45.00
        # raw: occupied 270 + 360 = 630 over allocated 600 + 480 = 1080.
        assert report["raw_utilization_pct"] == 58.33
        assert report["prime_time_utilization_pct"] != report["raw_utilization_pct"]

    def test_deficiency_opens_review_with_report_provenance(self, api):
        """PRD §3.7: "A deficiency immediately opens governance: when a line's
        `prime_time_utilization_pct` lands strictly below its
        `target_utilization_pct`, the run creates a `CommitteeReview` in `OPEN`
        status, recording the `service_line_id`, the triggering
        `utilization_report_id`, and the `period_end`".
        PRD §3.7: "A fresh review's `decision` is `NONE`, and its three tallies —
        `tally_reduce`, `tally_maintain`, and `tally_abstain` — all start at zero."

        Design: Difficulty/dual_variant_calc/utilization_prime_vs_raw_divergence
        """
        line, _ = self._setup_divergence(api)
        validate_success(api.scoring_run(ADMIN), 200)

        reviews, meta = _reviews(api, line["id"])
        assert meta["total_count"] == 1
        review = reviews[0]
        assert_committee_review(review)
        assert review["status"] == "OPEN"
        assert review["decision"] == "NONE"
        assert review["tally_reduce"] == 0
        assert review["tally_maintain"] == 0
        assert review["tally_abstain"] == 0
        assert review["period_end"] == "2026-05-08"
        reports, _ = _reports(api, line["id"])
        assert review["utilization_report_id"] == reports[0]["id"]


class TestPartialPrimeWindow:
    def _setup_partial_window(self, api):
        """Block [960,1200) straddling the 1020 prime end on a Monday, one case."""
        line = make_line(name="NEUR", target=75)
        surgeon = make_surgeon(line["id"], full_name="Dr. N")
        room = make_room()
        make_coverage(room["id"], "2026-05-04", 900, 1260)
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=960, end_minute=1200, activate=True)
        schedule_case_in_block(make_case(surgeon["id"])["id"], block["id"], surgeon["id"])
        validate_success(api.set_clock(CLOCK_AFTER_WEEK, ADMIN), 200)
        return line

    def test_partial_window_overlap_arithmetic(self, api):
        """PRD §3.7: "The prime window is weekdays from 07:00 (minute 420) through
        17:00 (minute 1020, exclusive), and an interval's overlap is simply the
        portion of it falling inside that window — zero on Saturdays and Sundays.
        The `prime_time_utilization_pct` is one hundred times occupied over
        allocated, rounded half up to two decimals, and 0.00 when the line allocated
        no prime minutes at all."

        Design: Difficulty/combinatorial_formula/prime_time_occupancy_partial_window_overlap
        """
        line = self._setup_partial_window(api)
        result = validate_success(api.scoring_run(ADMIN), 200)
        assert result["reviews_created"] == 0  # 100.00 is not below 75

        reports, meta = _reports(api, line["id"])
        assert meta["total_count"] == 1
        report = reports[0]
        # Block: min(1200,1020) - max(960,420) = 60; case [960,1050): 60.
        assert report["allocated_prime_minutes"] == 60
        assert report["occupied_prime_minutes"] == 60
        assert report["prime_time_utilization_pct"] == 100.00
        assert report["raw_utilization_pct"] == 37.50  # 90 / 240

    def test_full_prime_utilization_records_period_without_review(self, api):
        """PRD §3.7: "For each line the period runs from `period_start` — today
        minus seven days, inclusive — to `period_end` — today, exclusive — and
        produces an immutable `UtilizationReport` snapshot referencing the scored
        `service_line_id`."
        PRD §3.7: "except that the run skips creation when an `OPEN` review already
        exists for the line" — and no deficiency (100.00 >= 75) opens nothing.

        Design: Difficulty/combinatorial_formula/prime_time_occupancy_partial_window_overlap
        """
        line = self._setup_partial_window(api)
        validate_success(api.scoring_run(ADMIN), 200)
        reports, _ = _reports(api, line["id"])
        report = reports[0]
        assert report["period_start"] == "2026-05-01"
        assert report["period_end"] == "2026-05-08"
        _, review_meta = _reviews(api, line["id"])
        assert review_meta["total_count"] == 0


class TestTargetBoundary:
    def _setup_at_target(self, api, case_count):
        """Block [420,1020) (600 prime minutes) with case_count STANDARD cases."""
        line = make_line(name="IR", target=75)
        surgeon = make_surgeon(line["id"], full_name="Dr. I")
        room = make_room()
        make_coverage(room["id"], "2026-05-01", 420, 1200)
        block = make_block(line["id"], room["id"], date="2026-05-01",
                           start_minute=420, end_minute=1020, activate=True)
        for _ in range(case_count):
            schedule_case_in_block(
                make_case(surgeon["id"])["id"], block["id"], surgeon["id"]
            )
        validate_success(api.set_clock(CLOCK_AFTER_WEEK, ADMIN), 200)
        return line

    def test_exactly_at_target_opens_no_review(self, api):
        """PRD §3.7: "when a line's `prime_time_utilization_pct` lands strictly
        below its `target_utilization_pct`, the run creates a `CommitteeReview` in
        `OPEN` status" — a value equal to the target is not strictly below it.

        Design: Difficulty/boundary_precision_check/utilization_exactly_at_target_opens_no_review
        """
        line = self._setup_at_target(api, case_count=5)  # 450 / 600 = exactly 75.00
        result = validate_success(api.scoring_run(ADMIN), 200)
        assert result["reports_created"] == 1
        assert result["reviews_created"] == 0

        reports, _ = _reports(api, line["id"])
        assert reports[0]["prime_time_utilization_pct"] == 75.00
        _, meta = _reviews(api, line["id"])
        assert meta["total_count"] == 0

    def test_below_target_opens_review(self, api):
        """PRD §3.7: "A deficiency immediately opens governance: when a line's
        `prime_time_utilization_pct` lands strictly below its
        `target_utilization_pct`, the run creates a `CommitteeReview` in `OPEN`
        status".

        Design: Difficulty/boundary_precision_check/utilization_exactly_at_target_opens_no_review
        """
        line = self._setup_at_target(api, case_count=4)  # 360 / 600 = 60.00 < 75
        result = validate_success(api.scoring_run(ADMIN), 200)
        assert result["reports_created"] == 1
        assert result["reviews_created"] == 1
        reports, _ = _reports(api, line["id"])
        assert reports[0]["prime_time_utilization_pct"] == 60.00
        _, meta = _reviews(api, line["id"], status="OPEN")
        assert meta["total_count"] == 1


class TestScoringInputSet:
    def test_cancelled_case_excluded_from_report(self, api):
        """PRD §3.7: "`occupied_prime_minutes` sums, over cases in `SCHEDULED`,
        `IN_PROGRESS`, or `COMPLETED` status scheduled in those blocks, the
        prime-window overlap of each case's scheduled span — `BUMPED` and
        `CANCELLED` cases are excluded everywhere."

        Design: Corner/calculations/utilization_input_set_excludes_cancelled_case
        """
        env = setup_active_block_with_case(block_start=420, block_end=1020)
        line, surgeon, block = env["line"], env["surgeon"], env["block"]
        c2 = schedule_case_in_block(
            make_case(surgeon["id"])["id"], block["id"], surgeon["id"]
        )
        c3 = schedule_case_in_block(
            make_case(surgeon["id"])["id"], block["id"], surgeon["id"]
        )
        # Cancel the middle case; the third repacks from 650 to 535.
        validate_success(api.cancel_case(c2["id"], make_surgeon_headers(surgeon["id"])), 200)
        c3_after = validate_success(api.get_case(c3["id"], ADMIN), 200)
        assert c3_after["scheduled_start_minute"] == 535

        block_after = validate_success(api.get_block(block["id"], ADMIN), 200)
        assert block_after["occupied_minutes"] == 205  # 90 + 90 + 25

        validate_success(api.set_clock(CLOCK_AFTER_WEEK, ADMIN), 200)
        validate_success(api.scoring_run(ADMIN), 200)
        reports, _ = _reports(api, line["id"])
        report = reports[0]
        assert report["occupied_prime_minutes"] == 180  # cancelled case excluded
        assert report["allocated_prime_minutes"] == 600
        assert report["prime_time_utilization_pct"] == 30.00


class TestScoringRunDedup:
    def test_second_run_appends_report_but_dedups_open_review(self, api):
        """PRD §3.7: "A deficiency immediately opens governance: when a line's
        `prime_time_utilization_pct` lands strictly below its
        `target_utilization_pct`, the run creates a `CommitteeReview` in `OPEN`
        status, recording the `service_line_id`, the triggering
        `utilization_report_id`, and the `period_end` — except that the run skips
        creation when an `OPEN` review already exists for the line."

        Design: Corner/endpoints/scoring_run_dedups_open_review_but_appends_reports
        """
        env = setup_active_block_with_case(block_start=420, block_end=1020)
        line = env["line"]
        validate_success(api.set_clock(CLOCK_AFTER_WEEK, ADMIN), 200)

        first = validate_success(api.scoring_run(ADMIN), 200)
        assert first["reports_created"] == 1
        assert first["reviews_created"] == 1

        second = validate_success(api.scoring_run(ADMIN), 200)
        assert second["reports_created"] == 1
        assert second["reviews_created"] == 0

        _, reports_meta = _reports(api, line["id"])
        assert reports_meta["total_count"] == 2  # snapshots are append-only
        _, reviews_meta = _reviews(api, line["id"])
        assert reviews_meta["total_count"] == 1
