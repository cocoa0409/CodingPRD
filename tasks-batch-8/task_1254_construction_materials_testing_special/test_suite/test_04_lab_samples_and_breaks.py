"""Laboratory cylinder samples: break-due computation, scheduling rules, day
capacity buckets, set-average rounding order, acceptance variants, tolerance
windows, and the discard path."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cast_sample,
    create_lab,
    discard_sample,
    get_lab_sample,
    get_project,
    list_project_ncrs,
    record_sample_break,
    schedule_sample_break,
    setup_concrete_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
LAB_ANALYST = TEST_USERS["lab_analyst_headers"]

CAST_AT = "2026-04-01T08:00:00Z"
DUE_DATE = "2026-04-29"
BROKEN_ON_TIME = "2026-04-29T08:00:00Z"


def _cast_three_scheduled(ctx, age=28, cast_at=CAST_AT, schedule_date=DUE_DATE):
    """Cast three samples on the context's assignment and book all breaks."""
    samples = [
        cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                    ctx["lab"]["id"], cast_at, age)
        for _ in range(3)
    ]
    for s in samples:
        schedule_sample_break(s["id"], schedule_date)
    return samples


class TestAcceptanceVariantDivergence:
    def _setup_two_variant_projects(self, api):
        """P1 judges by moving average with two prior conforming sets broken;
        P2 judges by individual set. Both are concrete projects sharing one lab
        and one technician."""
        lab = create_lab(name="Lab One", lab_code="L1", daily_break_capacity=10)
        ctx1 = setup_concrete_assignment(
            fc=4500, acceptance="MOVING_AVERAGE", required_count=3,
            project_overrides={"name": "P1 MovingAvg", "permit_number": "P-CONC-1"},
        )
        # Reuse the shared lab instead of the fixture-created one.
        s1 = cast_sample(ctx1["assignment"]["id"], ctx1["technician"]["id"],
                         lab["id"], CAST_AT, 28)
        s2 = cast_sample(ctx1["assignment"]["id"], ctx1["technician"]["id"],
                         lab["id"], CAST_AT, 28)
        s3 = cast_sample(ctx1["assignment"]["id"], ctx1["technician"]["id"],
                         lab["id"], CAST_AT, 28)
        for s in (s1, s2, s3):
            schedule_sample_break(s["id"], DUE_DATE)
        record_sample_break(s1["id"], BROKEN_ON_TIME, [4700])
        record_sample_break(s2["id"], BROKEN_ON_TIME, [4600])

        ctx2 = setup_concrete_assignment(
            fc=4500, acceptance="INDIVIDUAL_SET", required_count=1,
            work_date="2026-04-01",
            project_overrides={"name": "P2 Individual", "permit_number": "P-CONC-2"},
        )
        # The second fixture's technician differs from ctx1's; use its own.
        p2_sample = cast_sample(ctx2["assignment"]["id"], ctx2["technician"]["id"],
                                lab["id"], CAST_AT, 28)
        schedule_sample_break(p2_sample["id"], DUE_DATE)
        return ctx1, s3, ctx2, p2_sample

    def test_acceptance_method_flips_verdict_on_identical_cylinders(self, api):
        """PRD §3.5: "The set conforms when the moving average reaches f'c and
        every set average inside the window clears the individual floor: for
        f'c of 5000 psi or less the floor is 500 psi below f'c, and for higher
        strengths it is nine-tenths of f'c rounded half up to a whole psi — so
        a single below-f'c set can still pass. Under the `INDIVIDUAL_SET`
        variant the current set stands alone and conforms only when its own
        `set_average_psi` reaches f'c; identical cylinder data can flip the
        verdict between the two variants."

        Design: Difficulty/dual_variant_calc/concrete_acceptance_variant_divergence
        """
        ctx1, s3, ctx2, p2_sample = self._setup_two_variant_projects(api)
        third = record_sample_break(s3["id"], BROKEN_ON_TIME, [4300])
        assert third["set_average_psi"] == 4300
        assert third["break_result"] == "CONFORMING", (
            "moving average of 4700/4600/4300 rounds to 4530 >= f'c 4500; floor 4000 satisfied"
        )
        solo = record_sample_break(p2_sample["id"], BROKEN_ON_TIME, [4300])
        assert solo["set_average_psi"] == 4300
        assert solo["break_result"] == "NONCONFORMING", "4300 < 4500 under INDIVIDUAL_SET"

    def test_individual_set_nonconformance_raises_ncr_and_degrades_posture(self, api):
        """PRD §3.5: "A nonconforming break auto-creates an NCR with
        `source_type` of `LAB_SAMPLE`, severity `STRUCTURAL` or `MAJOR` by the
        same `is_structural` rule as field tests, and increments
        `open_ncr_count`."
        PRD §3.9: "Otherwise, if `open_ncr_count` — the number of the project's
        reports in `OPEN`, `CORRECTION_SUBMITTED`, or `ESCALATED` — is greater
        than zero, the posture is `NONCONFORMANCE_OUTSTANDING`."

        Design: Difficulty/dual_variant_calc/concrete_acceptance_variant_divergence
        """
        ctx1, s3, ctx2, p2_sample = self._setup_two_variant_projects(api)
        record_sample_break(s3["id"], BROKEN_ON_TIME, [4300])
        record_sample_break(p2_sample["id"], BROKEN_ON_TIME, [4300])

        project2 = get_project(ctx2["project"]["id"])
        assert project2["open_ncr_count"] == 1
        assert project2["compliance_posture"] == "NONCONFORMANCE_OUTSTANDING"
        project1 = get_project(ctx1["project"]["id"])
        assert project1["open_ncr_count"] == 0, (
            "the moving-average project accepted the same cylinder data"
        )


class TestNestedRounding:
    def test_set_averages_rounded_to_ten_psi_grid_first(self, api):
        """PRD §2.6: "Concrete strength figures are expressed on a 10-psi grid:
        a cylinder set's average is the arithmetic mean of its cylinder
        strengths, rounded half up to the nearest multiple of 10 psi, so that
        4215 psi becomes 4220 psi while 4214.9 psi becomes 4210 psi. Rounding
        order is pinned — each set is averaged and rounded first, and every
        downstream aggregate (including moving averages) consumes only these
        rounded set averages."

        Design: Difficulty/combinatorial_formula/concrete_moving_average_nested_rounding
        """
        ctx = setup_concrete_assignment(
            fc=4205, acceptance="MOVING_AVERAGE", required_count=3,
            project_overrides={"name": "Rounding", "permit_number": "P-RND-1"},
        )
        s1, s2, s3 = _cast_three_scheduled(ctx)
        r1 = record_sample_break(s1["id"], BROKEN_ON_TIME, [4206])
        r2 = record_sample_break(s2["id"], BROKEN_ON_TIME, [4203])
        r3 = record_sample_break(s3["id"], BROKEN_ON_TIME, [4205])
        assert r1["set_average_psi"] == 4210, "4206 rounds to the nearest 10"
        assert r2["set_average_psi"] == 4200, "4203 rounds down"
        assert r3["set_average_psi"] == 4210, "4205 rounds half up to 4210"

    def test_moving_average_consumes_rounded_set_averages(self, api):
        """PRD §2.6: "Rounding order is pinned — each set is averaged and
        rounded first, and every downstream aggregate (including moving
        averages) consumes only these rounded set averages."
        PRD §3.5: "Under the `MOVING_AVERAGE` variant, the server assembles the
        rounded set averages of every reported, non-discarded sample pinned to
        the same scope item — including this one — ordered by `break_due_at`
        ascending and then `created_at` ascending, takes the last three of them
        (or fewer when fewer exist), and averages those on the same 10-psi grid
        to form the moving average."

        Design: Difficulty/combinatorial_formula/concrete_moving_average_nested_rounding
        """
        ctx = setup_concrete_assignment(
            fc=4205, acceptance="MOVING_AVERAGE", required_count=3,
            project_overrides={"name": "Rounding", "permit_number": "P-RND-1"},
        )
        s1, s2, s3 = _cast_three_scheduled(ctx)
        record_sample_break(s1["id"], BROKEN_ON_TIME, [4206])
        record_sample_break(s2["id"], BROKEN_ON_TIME, [4203])
        r3 = record_sample_break(s3["id"], BROKEN_ON_TIME, [4205])
        assert r3["break_result"] == "CONFORMING", (
            "moving average of the rounded sets 4210/4200/4210 is 4206.67 -> 4210 "
            ">= f'c 4205; sum-then-round of the raw values would give 4200 and fail"
        )


class TestBreakWindowTolerance:
    def _setup_tolerance_project(self, api):
        ctx = setup_concrete_assignment(
            fc=4000, required_count=2, work_date="2026-05-01",
            project_overrides={"name": "Boundary Break", "permit_number": "P-BND-2"},
        )
        s1 = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                         ctx["lab"]["id"], "2026-05-01T08:00:00Z", 7)
        s2 = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                         ctx["lab"]["id"], "2026-05-01T08:00:00Z", 7)
        schedule_sample_break(s1["id"], "2026-05-08")
        schedule_sample_break(s2["id"], "2026-05-08")
        return ctx, s1, s2

    def test_break_exactly_at_tolerance_limit_is_within(self, api):
        """PRD §3.5: "Tolerance depends on the required age: a 7-day break
        allows 6 hours of absolute deviation from `break_due_at`, a 28-day
        break allows 24 hours, a 56-day break allows 48 hours, and any other
        age allows 12 hours; landing exactly at the limit is within tolerance,
        and `flagged_out_of_tolerance` is simply the negation of
        `within_tolerance`."

        Design: Difficulty/boundary_precision_check/break_window_tolerance_inclusive_edge
        """
        _ctx, s1, _s2 = self._setup_tolerance_project(api)
        r1 = record_sample_break(s1["id"], "2026-05-08T14:00:00Z", [5000])
        assert r1["within_tolerance"] is True, "exactly +6h00m on a 7-day break is within"
        assert r1["flagged_out_of_tolerance"] is False

    def test_break_one_minute_past_tolerance_raises_minor_ncr(self, api):
        """PRD §3.5: "Tolerance depends on the required age: a 7-day break
        allows 6 hours of absolute deviation from `break_due_at`, a 28-day
        break allows 24 hours, a 56-day break allows 48 hours, and any other
        age allows 12 hours; landing exactly at the limit is within tolerance,
        and `flagged_out_of_tolerance` is simply the negation of
        `within_tolerance`."
        PRD §3.5: "Independently of the verdict, a sample flagged out of
        tolerance auto-creates a second NCR at severity `MINOR` with its own
        increment of `open_ncr_count` — so one record-break can raise two
        reports."

        Design: Difficulty/boundary_precision_check/break_window_tolerance_inclusive_edge
        """
        ctx, s1, s2 = self._setup_tolerance_project(api)
        record_sample_break(s1["id"], "2026-05-08T14:00:00Z", [5000])
        r2 = record_sample_break(s2["id"], "2026-05-08T14:01:00Z", [5000])
        assert r2["within_tolerance"] is False, "+6h01m exceeds the 6-hour limit"
        assert r2["flagged_out_of_tolerance"] is True
        ncrs = list_project_ncrs(ctx["project"]["id"])
        assert len(ncrs) == 1, "both breaks are strength-conforming; only the flag raises an NCR"
        assert ncrs[0]["severity"] == "MINOR"
        assert ncrs[0]["source_type"] == "LAB_SAMPLE"


class TestLabDayCapacity:
    def _setup_capacity_project(self, api):
        ctx = setup_concrete_assignment(
            fc=4000, required_count=3, work_date="2026-05-01", lab_capacity=1,
            project_overrides={"name": "LabCap", "permit_number": "P-OVL-2"},
        )
        s1 = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                         ctx["lab"]["id"], "2026-05-01T08:00:00Z", 7)
        s2 = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                         ctx["lab"]["id"], "2026-05-01T08:00:00Z", 7)
        s3 = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                         ctx["lab"]["id"], "2026-05-01T08:00:00Z", 28)
        return ctx, s1, s2, s3

    def test_day_at_capacity_rejects_next_booking(self, api):
        """PRD §3.5: "The laboratory's day load is an aggregate bucket: the
        count of that lab's samples sharing the same `break_scheduled_date`
        and sitting in `BREAK_SCHEDULED` status must remain strictly below the
        lab's `daily_break_capacity`; a day already at capacity rejects with
        `ERR_LAB_DAY_CAPACITY`, while a day at one below capacity still
        accepts."

        Design: Difficulty/resource_temporal_overlap/lab_day_capacity_aggregate_bucket
        """
        ctx, s1, s2, s3 = self._setup_capacity_project(api)
        booked = schedule_sample_break(s1["id"], "2026-05-08")
        assert booked["status"] == "BREAK_SCHEDULED", "load 0 < capacity 1 accepts"
        resp = api.schedule_break(s2["id"], {"break_scheduled_date": "2026-05-08"}, LAB_ANALYST)
        validate_error(resp, ApiErrorId.ERR_LAB_DAY_CAPACITY)
        other_day = schedule_sample_break(s3["id"], "2026-05-29")
        assert other_day["status"] == "BREAK_SCHEDULED", "each calendar day is an independent bucket"

    def test_lab_day_listing_observes_the_bucket(self, api):
        """PRD §3.5: "The samples at a lab may be listed with an optional
        `break_scheduled_date` filter, which is exactly the day-load
        observation."
        PRD §3.5: "Samples in `CAST`, `REPORTED`, or `DISCARDED` occupy no
        slot."

        Design: Difficulty/resource_temporal_overlap/lab_day_capacity_aggregate_bucket
        """
        ctx, s1, s2, s3 = self._setup_capacity_project(api)
        schedule_sample_break(s1["id"], "2026-05-08")
        resp = api.schedule_break(s2["id"], {"break_scheduled_date": "2026-05-08"}, LAB_ANALYST)
        validate_error(resp, ApiErrorId.ERR_LAB_DAY_CAPACITY)
        schedule_sample_break(s3["id"], "2026-05-29")
        data, meta = validate_paginated(
            api.list_lab_samples(ctx["lab"]["id"], PM,
                                 params={"break_scheduled_date": "2026-05-08"})
        )
        assert len(data) == 1, "only the successfully booked sample occupies the day"
        assert data[0]["id"] == s1["id"]


class TestBreakDueAtComputation:
    def test_break_due_at_computed_from_cast_and_age(self, api):
        """PRD §3.5: "The server computes `break_due_at` as exactly
        `required_break_age_days` days after `cast_at`, and the sample enters
        `CAST` status."

        Design: Corner/entities/lab_sample_computed_break_due_at
        """
        ctx = setup_concrete_assignment(
            fc=4000, required_count=1, work_date="2026-05-01",
            project_overrides={"name": "DueAt", "permit_number": "P-ENT-4"},
        )
        sample = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                             ctx["lab"]["id"], "2026-05-01T08:00:00Z", 7)
        assert sample["status"] == "CAST"
        assert sample["break_due_at"].startswith("2026-05-08T08:00:00"), (
            f"break_due_at must be exactly 7 days after cast_at, got {sample['break_due_at']}"
        )


class TestAcceptanceInputSets:
    def test_high_strength_floor_uses_ratio_not_offset(self, api):
        """PRD §3.5: "The set conforms when the moving average reaches f'c and
        every set average inside the window clears the individual floor: for
        f'c of 5000 psi or less the floor is 500 psi below f'c, and for higher
        strengths it is nine-tenths of f'c rounded half up to a whole psi — so
        a single below-f'c set can still pass."

        Design: Corner/calculations/concrete_high_fc_floor_ratio_applied
        """
        ctx = setup_concrete_assignment(
            fc=6000, acceptance="MOVING_AVERAGE", required_count=3,
            project_overrides={"name": "HighFC", "permit_number": "P-CALC-3"},
        )
        s1, s2, s3 = _cast_three_scheduled(ctx)
        record_sample_break(s1["id"], BROKEN_ON_TIME, [7000])
        record_sample_break(s2["id"], BROKEN_ON_TIME, [7000])
        r3 = record_sample_break(s3["id"], BROKEN_ON_TIME, [5300])
        assert r3["break_result"] == "NONCONFORMING", (
            "moving average 6430 >= 6000 but the 5300 set breaches the "
            "nine-tenths floor of 5400"
        )

    def test_moving_average_window_with_fewer_than_three_sets(self, api):
        """PRD §3.5: "Under the `MOVING_AVERAGE` variant, the server assembles
        the rounded set averages of every reported, non-discarded sample pinned
        to the same scope item — including this one — ordered by `break_due_at`
        ascending and then `created_at` ascending, takes the last three of them
        (or fewer when fewer exist), and averages those on the same 10-psi grid
        to form the moving average."

        Design: Corner/calculations/moving_average_window_two_of_two_sets
        """
        ctx = setup_concrete_assignment(
            fc=4400, acceptance="MOVING_AVERAGE", required_count=2,
            project_overrides={"name": "Win2", "permit_number": "P-CALC-4"},
        )
        s1 = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                         ctx["lab"]["id"], CAST_AT, 28)
        s2 = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                         ctx["lab"]["id"], CAST_AT, 28)
        schedule_sample_break(s1["id"], DUE_DATE)
        schedule_sample_break(s2["id"], DUE_DATE)
        record_sample_break(s1["id"], BROKEN_ON_TIME, [4500])
        r2 = record_sample_break(s2["id"], BROKEN_ON_TIME, [4300])
        assert r2["break_result"] == "CONFORMING", (
            "window of two sets: (4500+4300)/2 = 4400 >= f'c 4400; floor 3900 satisfied"
        )


class TestSampleStateMachine:
    def test_record_break_before_scheduling_rejected(self, api):
        """PRD §3.5: "Recording the break moves the sample `BREAK_SCHEDULED →
        REPORTED` and releases the day-load slot."
        PRD §2.9: "Fourth, state: whether the target resource's current state
        permits the operation (`ERR_INVALID_STATE`), a tier that also carries
        the domain state errors `ERR_PROJECT_COMPLETED`,
        `ERR_LETTER_ALREADY_ISSUED`, `ERR_NO_LETTER_TO_VOID`,
        `ERR_TEST_NOT_VOIDABLE`, and `ERR_NO_RESULT_RECORDED`."

        Design: Corner/state_machines/record_break_before_schedule_rejected
        """
        ctx = setup_concrete_assignment(
            fc=4000, required_count=1, work_date="2026-05-01",
            project_overrides={"name": "EarlyBreak", "permit_number": "P-SM-7"},
        )
        sample = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                             ctx["lab"]["id"], "2026-05-01T08:00:00Z", 7)
        resp = api.record_break(
            sample["id"],
            {"broken_at": "2026-05-08T08:00:00Z", "cylinder_strengths_psi": [5000]},
            LAB_ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_discarded_sample_cannot_be_scheduled(self, api):
        """PRD §3.5: "A cast sample that will never be broken (damaged in
        transit, mislabeled) may be discarded by a `LabAnalyst`, moving `CAST →
        DISCARDED` with no further effect; discarded samples never enter
        acceptance input sets."
        PRD §2.9: "Fourth, state: whether the target resource's current state
        permits the operation (`ERR_INVALID_STATE`), a tier that also carries
        the domain state errors `ERR_PROJECT_COMPLETED`,
        `ERR_LETTER_ALREADY_ISSUED`, `ERR_NO_LETTER_TO_VOID`,
        `ERR_TEST_NOT_VOIDABLE`, and `ERR_NO_RESULT_RECORDED`."

        Design: Corner/state_machines/discard_cast_sample_then_schedule_rejected
        """
        ctx = setup_concrete_assignment(
            fc=4000, required_count=1, work_date="2026-05-01",
            project_overrides={"name": "Discard", "permit_number": "P-SM-8"},
        )
        sample = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                             ctx["lab"]["id"], "2026-05-01T08:00:00Z", 7)
        discarded = discard_sample(sample["id"])
        assert discarded["status"] == "DISCARDED"
        resp = api.schedule_break(
            sample["id"], {"break_scheduled_date": "2026-05-08"}, LAB_ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_schedule_break_on_wrong_date_rejected(self, api):
        """PRD §3.5: "The requested `break_scheduled_date` must equal the
        calendar date of `break_due_at` — a mismatch is rejected with
        `ERR_BREAK_DATE_MISMATCH`."

        Design: Corner/validations/schedule_break_wrong_date_rejected
        """
        ctx = setup_concrete_assignment(
            fc=4000, required_count=1, work_date="2026-05-01",
            project_overrides={"name": "BreakDate", "permit_number": "P-VAL-4"},
        )
        sample = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                             ctx["lab"]["id"], "2026-05-01T08:00:00Z", 7)
        resp = api.schedule_break(
            sample["id"], {"break_scheduled_date": "2026-05-09"}, LAB_ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_BREAK_DATE_MISMATCH)
        after = get_lab_sample(sample["id"])
        assert after["status"] == "CAST", "a rejected booking leaves the sample in CAST"
