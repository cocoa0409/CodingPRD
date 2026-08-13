"""Installation work orders: parallel schedule/review dimensions, half-open
crew conflict arithmetic, blocked-review schedule pull, temporal gates, and
the install cascade (PRD §2.10, §3.7, §3.8)."""
from test_helpers import (
    TE,
    ApiErrorId,
    api_client,
    build_certified_request,
    cast_vote,
    create_funding_cycle,
    create_schedule_payload,
    create_work_order,
    drive_funded_request_to_ballot_open,
    get_request,
    get_work_order,
    mark_installed,
    publish_ranking,
    review_work_order,
    schedule_work_order,
    set_clock,
    setup_installation_planned,
    setup_installed,
    validate_error,
    validate_success,
)


class TestParallelDimensions:
    """schedule_status and emergency_review_status advance independently, but
    mark-installed is gated by both."""

    def _setup(self):
        return setup_installation_planned(
            name="Cedar Ct",
            resident_prefix="nsm2",
            requested_budget_cents=10000,
            crew_ref="CREW-9",
            close_date="2026-08-10T00:00:00Z",
            sweep_to="2026-08-11T00:00:00Z",
            estimated_cost_cents=12000,
        )

    def test_schedule_succeeds_while_review_pending(self):
        """PRD §3.7: "The order is born carrying two parallel status dimensions that advance independently: `schedule_status` starts `UNSCHEDULED`, and `emergency_review_status` starts `PENDING_REVIEW`."
        PRD §3.7: "The order must be `UNSCHEDULED` (otherwise `ERR_WORK_ORDER_INVALID_STATE`), and scheduling is refused outright while the emergency review dimension is `BLOCKED`, with `ERR_EMERGENCY_REVIEW_BLOCKED`."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_dimensions_independent
        """
        ctx = self._setup()
        wo = ctx["work_order"]
        assert wo["schedule_status"] == "UNSCHEDULED"
        assert wo["emergency_review_status"] == "PENDING_REVIEW"

        scheduled = schedule_work_order(wo["id"], "2026-08-15", 2)
        assert scheduled["schedule_status"] == "SCHEDULED", (
            "scheduling must succeed while review is still PENDING_REVIEW"
        )
        assert scheduled["emergency_review_status"] == "PENDING_REVIEW", (
            "scheduling must not disturb the review dimension"
        )

    def test_mark_installed_gated_by_review_then_succeeds(self):
        """PRD §3.7: "Marking the treatment installed is the final step and carries three preconditions: the order must be `SCHEDULED` (otherwise `ERR_WORK_ORDER_INVALID_STATE`); its emergency review dimension must be `CLEARED` (otherwise `ERR_EMERGENCY_REVIEW_NOT_CLEARED`); and the logical clock must have reached midnight at the start of the `scheduled_date` — marking earlier fails with `ERR_INSTALLATION_DATE_NOT_REACHED`. Success fires the two-link installation cascade: link one stamps the work order's `installed_at` from the logical clock and moves it from `SCHEDULED` to `INSTALLED`; link two bubbles upward, moving the request from `INSTALLATION_PLANNED` to `INSTALLED` and stamping the request's own `installed_at` with the same instant."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_dimensions_independent
        """
        ctx = self._setup()
        wo = ctx["work_order"]
        schedule_work_order(wo["id"], "2026-08-15", 2)

        early = api_client.mark_work_order_installed(wo["id"], TE)
        validate_error(early, ApiErrorId.ERR_EMERGENCY_REVIEW_NOT_CLEARED)

        reviewed = review_work_order(wo["id"], "CLEARED")
        assert reviewed["emergency_review_status"] == "CLEARED"
        assert reviewed["schedule_status"] == "SCHEDULED", (
            "clearing the review must not disturb the schedule dimension"
        )

        set_clock("2026-08-15T00:00:00Z")
        installed = mark_installed(wo["id"])
        assert installed["schedule_status"] == "INSTALLED"
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "INSTALLED", (
            f"the install cascade must bubble the request to INSTALLED, "
            f"got {req['status']}"
        )


class TestCrewScheduleHalfOpen:
    """Crew CREW-9 holds [2026-09-01, 2026-09-04) on one request; a second
    work order for the same crew probes the interval arithmetic."""

    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = build_certified_request(name="Seg C1", resident_prefix="c1")
        ctx2 = build_certified_request(name="Seg C2", resident_prefix="c2")
        cycle = create_funding_cycle(2026, 100000)
        publish_ranking(cycle["id"])
        d1 = drive_funded_request_to_ballot_open(
            ctx1["request"]["id"], close_date="2026-08-03T00:00:00Z"
        )
        d2 = drive_funded_request_to_ballot_open(
            ctx2["request"]["id"], close_date="2026-08-03T00:00:00Z"
        )
        cast_vote(d1["ballot"]["id"], ctx1["residents"][0]["id"], "FOR")
        cast_vote(d2["ballot"]["id"], ctx2["residents"][0]["id"], "FOR")
        set_clock("2026-08-04T00:00:00Z")
        wo1 = create_work_order(ctx1["request"]["id"], "CREW-9")
        schedule_work_order(wo1["id"], "2026-09-01", 3)
        wo2 = create_work_order(ctx2["request"]["id"], "CREW-9")
        return wo1, wo2

    def test_interior_overlap_rejected(self):
        """PRD §3.7: "Crew capacity is then enforced as a half-open interval check: the new engagement occupies the days from `scheduled_date` up to but not including `scheduled_date` plus `duration_days`, and it conflicts with any other `SCHEDULED` work order carrying the same `crew_ref` — on any request in the city — when the new engagement's start falls before the existing engagement's end and the existing engagement's start falls before the new engagement's end."
        PRD §3.7: "A genuine overlap is rejected with `ERR_CREW_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crew_schedule_half_open_adjacency
        """
        _, wo2 = self._setup()
        resp = api_client.schedule_work_order(
            wo2["id"],
            create_schedule_payload(
                scheduled_date="2026-09-03", duration_days=3
            ),
            TE,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT)

    def test_back_to_back_adjacency_allowed(self):
        """PRD §3.7: "Back-to-back bookings are explicitly allowed: a new engagement that starts exactly on the day another ends, or ends exactly on the day another starts, is not a conflict."

        Design: Difficulty/resource_temporal_overlap/crew_schedule_half_open_adjacency
        """
        _, wo2 = self._setup()
        conflict = api_client.schedule_work_order(
            wo2["id"],
            create_schedule_payload(
                scheduled_date="2026-09-03", duration_days=3
            ),
            TE,
        )
        validate_error(conflict, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT)
        ok = api_client.schedule_work_order(
            wo2["id"],
            create_schedule_payload(
                scheduled_date="2026-09-04", duration_days=2
            ),
            TE,
        )
        scheduled = validate_success(ok, expected_status=200)
        assert scheduled["schedule_status"] == "SCHEDULED"
        assert scheduled["scheduled_date"] == "2026-09-04"


class TestValidationTierOrdering:
    """PRD §2.10 evaluates the nine tiers strictly in order; the earliest
    failing tier produces the rejection."""

    def test_state_gate_beats_temporal_gate_on_reschedule(self):
        """PRD §2.10: "Every incoming call is validated against nine tiers, evaluated strictly in the order below; the earliest failing tier produces the rejection, and later tiers are not consulted."
        PRD §2.10: "5. **State preconditions.** The target resource must be in the stage the operation requires — request stage, study status, plan status, ballot openness, cycle status, both work-order dimensions, removal status"

        Design: Difficulty/priority_pair_validation_conflict/reschedule_state_beats_temporal
        """
        ctx = setup_installation_planned(
            name="Ash Blvd", resident_prefix="pv1", crew_ref="CREW-11",
            close_date="2026-08-06T00:00:00Z", sweep_to="2026-08-07T00:00:00Z",
            estimated_cost_cents=9000,
        )
        wo = ctx["work_order"]
        schedule_work_order(wo["id"], "2026-08-20", 1)
        # Already SCHEDULED (tier 5) AND 2026-08-06 is in the past (tier 7).
        resp = api_client.schedule_work_order(
            wo["id"],
            create_schedule_payload(
                scheduled_date="2026-08-06", duration_days=1
            ),
            TE,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_INVALID_STATE)

    def test_rejected_reschedule_leaves_work_order_untouched(self):
        """PRD §3.7: "A successful scheduling stamps `scheduled_date` and `duration_days` onto the order and moves it from `UNSCHEDULED` to `SCHEDULED`."

        Design: Difficulty/priority_pair_validation_conflict/reschedule_state_beats_temporal
        """
        ctx = setup_installation_planned(
            name="Ash Blvd", resident_prefix="pv1", crew_ref="CREW-11",
            close_date="2026-08-06T00:00:00Z", sweep_to="2026-08-07T00:00:00Z",
            estimated_cost_cents=9000,
        )
        wo = ctx["work_order"]
        schedule_work_order(wo["id"], "2026-08-20", 1)
        api_client.schedule_work_order(
            wo["id"],
            create_schedule_payload(
                scheduled_date="2026-08-06", duration_days=1
            ),
            TE,
        )
        after = get_work_order(wo["id"])
        assert after["schedule_status"] == "SCHEDULED"
        assert after["scheduled_date"] == "2026-08-20", (
            "the rejected call must not restamp scheduled_date"
        )

    def _setup_two_work_orders(self):
        set_clock("2026-08-01T00:00:00Z")
        ctx1 = build_certified_request(name="Seg P1", resident_prefix="p1")
        ctx2 = build_certified_request(name="Seg P2", resident_prefix="p2")
        cycle = create_funding_cycle(2026, 100000)
        publish_ranking(cycle["id"])
        d1 = drive_funded_request_to_ballot_open(
            ctx1["request"]["id"], close_date="2026-08-05T00:00:00Z",
            estimated_cost_cents=10000,
        )
        d2 = drive_funded_request_to_ballot_open(
            ctx2["request"]["id"], close_date="2026-08-05T00:00:00Z",
            estimated_cost_cents=10000,
        )
        cast_vote(d1["ballot"]["id"], ctx1["residents"][0]["id"], "FOR")
        cast_vote(d2["ballot"]["id"], ctx2["residents"][0]["id"], "FOR")
        set_clock("2026-08-06T00:00:00Z")
        wo1 = create_work_order(ctx1["request"]["id"], "CREW-7")
        schedule_work_order(wo1["id"], "2026-08-07", 10)
        wo2 = create_work_order(ctx2["request"]["id"], "CREW-7")
        return wo2

    def test_temporal_gate_beats_constraint_gate_on_schedule(self):
        """PRD §2.10: "Every incoming call is validated against nine tiers, evaluated strictly in the order below; the earliest failing tier produces the rejection, and later tiers are not consulted."
        PRD §2.10: "7. **Temporal gates against the logical clock.** Observation dates must lie inside the study window (`ERR_OBSERVATION_OUTSIDE_WINDOW`), a scheduled date must not be in the past (`ERR_SCHEDULE_DATE_IN_PAST`), installation cannot be marked before the scheduled date (`ERR_INSTALLATION_DATE_NOT_REACHED`), a post-installation study cannot start before the thirty-day settling period (`ERR_POST_STUDY_TOO_EARLY`), and a removal filing cannot arrive before the one-year mark (`ERR_REMOVAL_MIN_AGE_NOT_MET`) — all 409."

        Design: Difficulty/priority_pair_validation_conflict/schedule_temporal_beats_constraint
        """
        wo2 = self._setup_two_work_orders()
        # 2026-08-05 is in the past (tier 7) AND [08-05, 08-15) overlaps
        # CREW-7's [08-07, 08-17) (tier 8): the temporal error wins.
        resp = api_client.schedule_work_order(
            wo2["id"],
            create_schedule_payload(
                scheduled_date="2026-08-05", duration_days=10
            ),
            TE,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_DATE_IN_PAST)

    def test_rejected_schedule_leaves_second_work_order_unscheduled(self):
        """PRD §3.7: "A successful scheduling stamps `scheduled_date` and `duration_days` onto the order and moves it from `UNSCHEDULED` to `SCHEDULED`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_temporal_beats_constraint
        """
        wo2 = self._setup_two_work_orders()
        api_client.schedule_work_order(
            wo2["id"],
            create_schedule_payload(
                scheduled_date="2026-08-05", duration_days=10
            ),
            TE,
        )
        after = get_work_order(wo2["id"])
        assert after["schedule_status"] == "UNSCHEDULED", (
            f"the rejected call must leave the order UNSCHEDULED, "
            f"got {after['schedule_status']}"
        )
        assert after.get("scheduled_date") is None
        assert after.get("duration_days") is None


class TestEmergencyReviewBlocking:
    def test_blocked_pulls_schedule_and_rereview_allows_reschedule(self):
        """PRD §3.7: "Blocking carries a scheduling consequence: a work order that is `SCHEDULED` when it is blocked is pulled from the schedule, returning its `schedule_status` to `UNSCHEDULED` and clearing its `scheduled_date` and `duration_days`, so a blocked treatment can never quietly remain on the calendar."
        PRD §3.7: "An `EmergencyReviewer` records a `decision` of `CLEARED` or `BLOCKED` whenever the review dimension is `PENDING_REVIEW` or `BLOCKED` — re-review of a blocked order is explicitly allowed"
        PRD §3.7: "scheduling is refused outright while the emergency review dimension is `BLOCKED`, with `ERR_EMERGENCY_REVIEW_BLOCKED`."

        Design: Corner/state_machines/work_order_blocked_pulls_schedule_and_rereview_allows_reschedule
        """
        ctx = setup_installation_planned(
            name="Block Ave", resident_prefix="blk", crew_ref="CREW-4",
            estimated_cost_cents=8000,
        )
        wo = ctx["work_order"]
        schedule_work_order(wo["id"], "2026-08-20", 2)

        blocked = review_work_order(wo["id"], "BLOCKED")
        assert blocked["emergency_review_status"] == "BLOCKED"
        assert blocked["schedule_status"] == "UNSCHEDULED", (
            "blocking must pull the order from the schedule"
        )
        assert blocked.get("scheduled_date") is None
        assert blocked.get("duration_days") is None

        refused = api_client.schedule_work_order(
            wo["id"],
            create_schedule_payload(
                scheduled_date="2026-08-25", duration_days=2
            ),
            TE,
        )
        validate_error(refused, ApiErrorId.ERR_EMERGENCY_REVIEW_BLOCKED)

        cleared = review_work_order(wo["id"], "CLEARED")
        assert cleared["emergency_review_status"] == "CLEARED"

        rescheduled = schedule_work_order(wo["id"], "2026-08-25", 2)
        assert rescheduled["schedule_status"] == "SCHEDULED"
        assert rescheduled["scheduled_date"] == "2026-08-25"


class TestTemporalGates:
    def test_schedule_date_in_past_rejected_today_allowed(self):
        """PRD §3.7: "The supplied `scheduled_date` must not be earlier than the logical current date — today is acceptable, yesterday is `ERR_SCHEDULE_DATE_IN_PAST`"

        Design: Corner/validations/schedule_date_in_past_rejected
        """
        ctx = setup_installation_planned(
            name="Past Ave", resident_prefix="pst", crew_ref="CREW-6",
            close_date="2026-08-06T00:00:00Z", sweep_to="2026-08-07T00:00:00Z",
        )
        wo = ctx["work_order"]
        yesterday = api_client.schedule_work_order(
            wo["id"],
            create_schedule_payload(
                scheduled_date="2026-08-06", duration_days=1
            ),
            TE,
        )
        validate_error(yesterday, ApiErrorId.ERR_SCHEDULE_DATE_IN_PAST)

        today = schedule_work_order(wo["id"], "2026-08-07", 1)
        assert today["schedule_status"] == "SCHEDULED", (
            "scheduling exactly today must be allowed (>= boundary)"
        )

    def test_mark_installed_before_scheduled_date_rejected(self):
        """PRD §3.7: "the logical clock must have reached midnight at the start of the `scheduled_date` — marking earlier fails with `ERR_INSTALLATION_DATE_NOT_REACHED`"

        Design: Corner/validations/mark_installed_before_scheduled_date_rejected
        """
        ctx = setup_installation_planned(
            name="Soon Ave", resident_prefix="soon", crew_ref="CREW-5",
            close_date="2026-08-06T00:00:00Z", sweep_to="2026-08-07T00:00:00Z",
        )
        wo = ctx["work_order"]
        schedule_work_order(wo["id"], "2026-08-20", 1)
        review_work_order(wo["id"], "CLEARED")
        set_clock("2026-08-19T00:00:00Z")
        resp = api_client.mark_work_order_installed(
            wo["id"], TE
        )
        validate_error(resp, ApiErrorId.ERR_INSTALLATION_DATE_NOT_REACHED)
        assert get_work_order(wo["id"])["schedule_status"] == "SCHEDULED"

    def test_post_installation_study_too_early_rejected(self):
        """PRD §3.8: "Once the request is `INSTALLED` — a stage reachable only through the installation cascade, so the work order's completion is implied — and the logical clock has reached or passed the instant exactly thirty days after `installed_at`, a `TrafficEngineer` may commission the post-installation study; attempting it earlier fails with `ERR_POST_STUDY_TOO_EARLY`"

        Design: Corner/validations/post_installation_study_too_early_rejected
        """
        ctx = setup_installed(
            name="Early Ave", resident_prefix="ear", crew_ref="CREW-2",
            close_date="2026-08-06T00:00:00Z", sweep_to="2026-08-07T00:00:00Z",
            scheduled_date="2026-08-15",
        )
        # installed_at is 2026-08-15T00:00:00Z; +30 days is 2026-09-14.
        set_clock("2026-09-13T00:00:00Z")
        resp = api_client.create_speed_study(
            ctx["request"]["id"],
            {
                "study_type": "POST_INSTALLATION",
                "window_start_date": "2026-09-14",
                "window_end_date": "2026-09-16",
            },
            TE,
        )
        validate_error(resp, ApiErrorId.ERR_POST_STUDY_TOO_EARLY)
