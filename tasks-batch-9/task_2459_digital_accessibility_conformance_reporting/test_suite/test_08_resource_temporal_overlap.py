"""Two shared resources booked under opposite interval semantics: a bench whose
busy interval is half-open and inflated by a reconfiguration buffer, and a
release train whose closed calendar window may not even touch its neighbour."""

from test_helpers import (
    LEAD,
    TESTER,
    create_component,
    create_environment,
    create_product,
    create_release_train,
    create_standard,
    read_component,
    read_environment,
    read_release_train,
    release_train_payload,
    run_payload,
    schedule_run,
    validate_error,
    validate_success,
)

# The bench is booked from 09:00 to 12:00 and carries a 30-minute reconfiguration
# buffer, so it is occupied over the half-open interval [09:00, 12:30).
FIRST_BOOKING = ("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")
INSIDE_THE_BUFFER = ("2026-08-03T12:15:00Z", "2026-08-03T13:15:00Z")
AT_THE_BUFFER_END = ("2026-08-03T12:30:00Z", "2026-08-03T13:30:00Z")

# The September train occupies the closed window 2026-09-01..2026-09-30, so a
# window opening on 2026-10-01 touches it and one opening on 2026-10-02 does not.
TOUCHING_START = "2026-10-01"
GAPPED_START = "2026-10-02"


def build_bench_booked_from_nine_to_twelve():
    standard = create_standard(
        code="WCAG_2_2", title="WCAG 2.2", surface_scope="WEB", max_target_level="AAA"
    )
    product = create_product(
        standard["id"],
        name="Insight Portal",
        version_label="7.0",
        target_level="AA",
        surface_type="WEB",
    )
    component = create_component(
        product["id"],
        name="Web UI",
        component_type="WEB_UI",
        in_scope=True,
        assessment_scope="FULL",
        applicable_criteria_count=40,
        user_reach_pct=60,
    )
    bench = create_environment(
        name="NVDA Bench 1", at_profile="SCREEN_READER", reconfiguration_buffer_minutes=30
    )
    first = schedule_run(
        component["id"],
        bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        scheduled_start=FIRST_BOOKING[0],
        scheduled_end=FIRST_BOOKING[1],
        criteria_exercised=40,
        disability_categories_validated=["VISION", "COGNITIVE"],
    )
    return {
        "standard": standard,
        "product": product,
        "component": component,
        "bench": bench,
        "first": first,
    }


def build_train_occupying_september():
    train = create_release_train(
        name="Train 2026.09",
        window_start="2026-09-01",
        window_end="2026-09-30",
        freeze_days=5,
        effort_capacity_points=10,
        remediation_budget_cents=60327,
    )
    return {"train": train}


class TestBenchOccupationIntervalIsHalfOpen:
    """12:15 collides with the buffered booking; 12:30 is its excluded endpoint."""

    def test_a_booking_inside_the_reconfiguration_buffer_is_refused(self, api):
        """PRD §3.3: "And the bench must be free: the new run's half-open window,
        from its `scheduled_start` up to but not including its `scheduled_end`,
        must not intersect the occupation window of any other run on the same
        bench whose `status` is `SCHEDULED` or `COMPLETED`, where each existing
        run's occupation window runs from its own `scheduled_start` up to but not
        including its `scheduled_end` extended forward by that bench's
        `reconfiguration_buffer_minutes`."
        PRD §3.3: "Any intersection is `ERR_ENVIRONMENT_WINDOW_CONFLICT`."
        PRD §3.3: "The run is created with `status` at `SCHEDULED`, with no
        `defects_found`, no `void_reason` and no `completed_at`; nothing is
        credited to coverage until the run is completed."

        Design: Difficulty/resource_temporal_overlap/environment_reconfiguration_buffer_is_half_open
        """
        ctx = build_bench_booked_from_nine_to_twelve()

        assert ctx["first"]["status"] == "SCHEDULED", (
            f"the incumbent booking holds the bench, got {ctx['first']['status']}"
        )

        validate_error(
            api.create_run(
                run_payload(
                    ctx["component"]["id"],
                    ctx["bench"]["id"],
                    method="AUTOMATED",
                    at_profile="SCREEN_READER",
                    scheduled_start=INSIDE_THE_BUFFER[0],
                    scheduled_end=INSIDE_THE_BUFFER[1],
                    criteria_exercised=10,
                    disability_categories_validated=["VISION"],
                ),
                TESTER,
            ),
            "ERR_ENVIRONMENT_WINDOW_CONFLICT",
            409,
        )

        component = read_component(ctx["component"]["id"])
        assert component["evidence_units_total"] == 0, (
            "scheduling alone credits no coverage, and the refused booking credits nothing "
            f"either, got {component['evidence_units_total']}"
        )

    def test_a_booking_starting_exactly_at_the_buffer_end_is_admitted(self, api):
        """PRD §3.3: "And the bench must be free: the new run's half-open window,
        from its `scheduled_start` up to but not including its `scheduled_end`,
        must not intersect the occupation window of any other run on the same
        bench whose `status` is `SCHEDULED` or `COMPLETED`, where each existing
        run's occupation window runs from its own `scheduled_start` up to but not
        including its `scheduled_end` extended forward by that bench's
        `reconfiguration_buffer_minutes`."
        PRD §3.3: "Each newly scheduled run also raises the bench's
        `scheduled_run_count` by 1."
        PRD §3.3: "A bench also reports a derived `scheduled_run_count`, being the
        number of runs on it whose `status` is either `SCHEDULED` or `COMPLETED`."

        Design: Difficulty/resource_temporal_overlap/environment_reconfiguration_buffer_is_half_open
        """
        ctx = build_bench_booked_from_nine_to_twelve()
        validate_error(
            api.create_run(
                run_payload(
                    ctx["component"]["id"],
                    ctx["bench"]["id"],
                    method="AUTOMATED",
                    at_profile="SCREEN_READER",
                    scheduled_start=INSIDE_THE_BUFFER[0],
                    scheduled_end=INSIDE_THE_BUFFER[1],
                    criteria_exercised=10,
                    disability_categories_validated=["VISION"],
                ),
                TESTER,
            ),
            "ERR_ENVIRONMENT_WINDOW_CONFLICT",
            409,
        )

        accepted = validate_success(
            api.create_run(
                run_payload(
                    ctx["component"]["id"],
                    ctx["bench"]["id"],
                    method="AUTOMATED",
                    at_profile="SCREEN_READER",
                    scheduled_start=AT_THE_BUFFER_END[0],
                    scheduled_end=AT_THE_BUFFER_END[1],
                    criteria_exercised=10,
                    disability_categories_validated=["VISION"],
                ),
                TESTER,
            ),
            201,
        )

        assert accepted["status"] == "SCHEDULED", (
            "the busy interval excludes its own endpoint, so 12:30 is free, got "
            f"{accepted['status']}"
        )
        assert accepted["scheduled_start"] == AT_THE_BUFFER_END[0], (
            f"the accepted booking keeps its declared start, got {accepted['scheduled_start']}"
        )
        assert accepted["environment_id"] == ctx["bench"]["id"], (
            "the accepted booking sits on the very bench that refused the earlier attempt"
        )
        bench = read_environment(ctx["bench"]["id"])
        assert bench["scheduled_run_count"] == 2, (
            "the bench now holds two scheduled bookings and no refused one, got "
            f"{bench['scheduled_run_count']}"
        )
        component = read_component(ctx["component"]["id"])
        assert component["evidence_units_total"] == 0, (
            f"neither run has been completed, got {component['evidence_units_total']}"
        )


class TestReleaseTrainWindowsMustNotTouch:
    """The inverse rule: closed windows need a full calendar day of daylight."""

    def test_a_window_opening_the_day_after_an_existing_one_ends_is_refused(self, api):
        """PRD §3.9: "Trains must be genuinely separated in time: a new train's
        closed window must neither overlap an existing train's closed window nor
        merely touch it — at least one full calendar day of gap is required on
        both sides — and a violation is `ERR_TRAIN_WINDOW_ADJACENT`."
        PRD §3.9: "A release train is the remediation roadmap's unit of delivery,
        created by an `AccessibilityLead` with a globally unique `name` of 1 to
        120 characters (a repeat is `ERR_DUPLICATE_TRAIN_NAME`), a closed delivery
        window from `window_start` to `window_end` inclusive where `window_end` is
        on or after `window_start`, optional trailing `freeze_days` between 0 and
        60 which must be fewer than the number of days in the window and default
        to 0, an `effort_capacity_points` figure from 1 to 1000, and a
        `remediation_budget_cents` figure from 0 to 100000000."

        Design: Difficulty/resource_temporal_overlap/release_train_windows_require_a_full_day_gap
        """
        ctx = build_train_occupying_september()

        assert ctx["train"]["window_end"] == "2026-09-30", (
            f"the incumbent train closes on the last day of September, got {ctx['train']['window_end']}"
        )

        validate_error(
            api.create_release_train(
                release_train_payload(
                    name="Train 2026.10 touching",
                    window_start=TOUCHING_START,
                    window_end="2026-10-31",
                    freeze_days=5,
                    effort_capacity_points=10,
                    remediation_budget_cents=0,
                ),
                LEAD,
            ),
            "ERR_TRAIN_WINDOW_ADJACENT",
            409,
        )

        incumbent = read_release_train(ctx["train"]["id"])
        assert incumbent["window_end"] == "2026-09-30", (
            f"the refused create leaves the incumbent untouched, got {incumbent['window_end']}"
        )
        assert incumbent["unallocated_cents"] == 60327, (
            "the incumbent's whole budget is still unallocated, got "
            f"{incumbent['unallocated_cents']}"
        )

    def test_a_window_opening_after_one_clear_day_is_admitted(self, api):
        """PRD §3.9: "Trains must be genuinely separated in time: a new train's
        closed window must neither overlap an existing train's closed window nor
        merely touch it — at least one full calendar day of gap is required on
        both sides — and a violation is `ERR_TRAIN_WINDOW_ADJACENT`."
        PRD §3.9: "A new train reports `committed_effort_points` of 0,
        `unallocated_cents` equal to its whole `remediation_budget_cents`, and
        `allocation_state` of `UNALLOCATED`."

        Design: Difficulty/resource_temporal_overlap/release_train_windows_require_a_full_day_gap
        """
        ctx = build_train_occupying_september()
        validate_error(
            api.create_release_train(
                release_train_payload(
                    name="Train 2026.10 touching",
                    window_start=TOUCHING_START,
                    window_end="2026-10-31",
                    freeze_days=5,
                    effort_capacity_points=10,
                    remediation_budget_cents=0,
                ),
                LEAD,
            ),
            "ERR_TRAIN_WINDOW_ADJACENT",
            409,
        )

        accepted = validate_success(
            api.create_release_train(
                release_train_payload(
                    name="Train 2026.10 gapped",
                    window_start=GAPPED_START,
                    window_end="2026-10-31",
                    freeze_days=5,
                    effort_capacity_points=10,
                    remediation_budget_cents=0,
                ),
                LEAD,
            ),
            201,
        )

        assert accepted["window_start"] == GAPPED_START, (
            "one clear calendar day of gap is enough, got "
            f"{accepted['window_start']}"
        )
        assert accepted["allocation_state"] == "UNALLOCATED"
        assert accepted["unallocated_cents"] == 0, (
            "a zero budget leaves nothing unallocated, got "
            f"{accepted['unallocated_cents']}"
        )
        assert accepted["committed_effort_points"] == 0
        assert read_release_train(ctx["train"]["id"])["window_end"] == "2026-09-30", (
            "neither attempt moved the incumbent's window"
        )
