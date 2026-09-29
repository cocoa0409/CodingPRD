"""Protective measures: escort buffers, area ceilings, coverage arithmetic and the revocation cascade."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    add_escort_action,
    add_restriction_action,
    assert_case_action,
    assert_case_state,
    assert_escort_ledger,
    assert_protection,
    assert_restriction_counters,
    assert_total_count,
    build_access_restriction,
    build_closure,
    build_escort_action,
    build_protective_action,
    build_revocation,
    read_case,
    read_employee,
    read_work_area,
    setup_employee,
    setup_monitoring_case,
    setup_monitoring_case_with_escort,
)

#: The standard fourteen-day protection window opened by the decision.
WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-15T00:00:00Z"


def _case_actions(api: ApiClient, ctx, **params):
    query = {"case_id": ctx["case"]["id"]}
    query.update(params)
    return api.list_case_actions(ctx["headers"]["security_coordinator"], query)


class TestFullWindowEscortRevocation:
    """Revoking the only covering measure credits the ledger, reopens the gap and blocks closure."""

    def _covered_case(self, api: ApiClient):
        ctx = setup_monitoring_case_with_escort(api)
        ctx["escort_action"] = add_escort_action(api, ctx, WINDOW_START, WINDOW_END)
        return ctx

    def _revoke(self, api: ApiClient, ctx):
        return get_success_data(
            api.revoke_case_action(
                ctx["escort_action"]["id"],
                build_revocation(
                    revocation_reason="Escort reassigned to another site at short notice."
                ),
                ctx["headers"]["security_coordinator"],
            )
        )

    def test_revocation_credits_the_ledger_back_and_reopens_the_whole_window(
        self, api: ApiClient
    ) -> None:
        """A 20,160-minute escort covers the window; revoking it returns the ledger to zero and the gap to 336.00.

        PRD: "The compensation is exact: a `SECURITY_ESCORT` credits `escort_committed_minutes` back by precisely `duration_minutes`, and an `ACCESS_RESTRICTION` decrements both `restricted_employee_count` and `active_restriction_count` by one."
        Design: Difficulty/transitive_cascade/revoke_full_window_escort_cascades_four_hops_and_blocks_close
        """
        ctx = self._covered_case(api)
        assert_case_action(ctx["escort_action"], status="SCHEDULED", duration_minutes=20160)
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 20160)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=0.00, protection_status="COVERED"
        )

        revoked = self._revoke(api, ctx)

        assert_case_action(revoked, status="REVOKED", duration_minutes=20160)
        assert revoked["revoked_at"] == "2026-08-01T00:00:00Z"
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 0)
        assert_protection(
            read_case(api, ctx), coverage_gap_hours=336.00, protection_status="GAP"
        )

    def test_the_auto_generated_safety_plan_review_blocks_the_closure(
        self, api: ApiClient
    ) -> None:
        """The flip to GAP appends one SAFETY_PLAN_REVIEW due 24 hours out, so closing reports open actions.

        PRD: "And if it does flip to `GAP` while the case is `MONITORING`, the system appends a compensating `POST_INCIDENT` action of type `SAFETY_PLAN_REVIEW` with `auto_generated` true, `assigned_employee_id` set to the case's `lead_employee_id` and `due_at` 24 hours after the logical clock — raising `open_action_count` and thereby blocking closure with `ERR_OPEN_ACTIONS_BLOCK_CLOSE` until somebody attends to the newly uncovered time."
        Design: Difficulty/transitive_cascade/revoke_full_window_escort_cascades_four_hops_and_blocks_close
        """
        ctx = self._covered_case(api)
        self._revoke(api, ctx)

        auto_rows = get_success_data(_case_actions(api, ctx, auto_generated=True))
        assert len(auto_rows) == 1, "exactly one compensating review must be appended"
        auto = auto_rows[0]
        assert auto["action_class"] == "POST_INCIDENT"
        assert auto["action_type"] == "SAFETY_PLAN_REVIEW"
        assert auto["assigned_employee_id"] == ctx["lead"]["id"]
        assert auto["due_at"] == "2026-08-02T00:00:00Z"
        assert_case_action(auto, status="PENDING", duration_minutes=0, auto_generated=True)
        assert_case_state(read_case(api, ctx), status="MONITORING", open_action_count=1)

        validate_error(
            api.close_threat_case(
                ctx["case"]["id"],
                build_closure(),
                ctx["headers"]["threat_team_lead"],
            ),
            ApiErrorId.OPEN_ACTIONS_BLOCK_CLOSE,
            409,
        )
        assert_total_count(_case_actions(api, ctx, auto_generated=True), 1)


class TestEscortDoubleBookingBuffer:
    """The thirty-minute buffer is symmetric, so escorts that merely touch still collide."""

    def _booked_escort(self, api: ApiClient):
        ctx = setup_monitoring_case_with_escort(api)
        ctx["escort_action"] = add_escort_action(
            api, ctx, "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"
        )
        return ctx

    def test_a_second_escort_inside_the_buffer_is_refused_and_moves_no_minutes(
        self, api: ApiClient
    ) -> None:
        """A booking starting 20 minutes after the first ends still falls inside the widened interval.

        PRD: "Next, a `SECURITY_ESCORT` may not double-book its escort: the requested interval, widened by 30 minutes on **each** side to allow for travel, must not overlap any other `SECURITY_ESCORT` in `SCHEDULED` or `ACTIVE` status naming the same `escort_employee_id`."
        Design: Difficulty/resource_temporal_overlap/escort_double_booking_blocked_by_thirty_minute_symmetric_buffer
        """
        ctx = self._booked_escort(api)
        assert_case_action(ctx["escort_action"], status="SCHEDULED", duration_minutes=240)
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 240)

        response = api.create_case_action(
            build_escort_action(
                ctx["case"]["id"],
                ctx["rep"]["id"],
                ctx["escort"]["id"],
                "2026-08-02T12:20:00Z",
                "2026-08-02T14:00:00Z",
            ),
            ctx["headers"]["security_coordinator"],
        )

        validate_error(response, ApiErrorId.ESCORT_DOUBLE_BOOKED, 409)
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 240)
        assert_total_count(_case_actions(api, ctx), 1)

    def test_a_second_escort_clear_of_the_buffer_accrues_the_ledger(
        self, api: ApiClient
    ) -> None:
        """A booking a full hour after the first ends is accepted and lifts the ledger to 300 minutes.

        PRD: "A `SECURITY_ESCORT` immediately increments the escort's `escort_committed_minutes` by `duration_minutes`; an `ACCESS_RESTRICTION` immediately increments both the area's `restricted_employee_count` and the subject's `active_restriction_count` by one."
        Design: Difficulty/resource_temporal_overlap/escort_double_booking_blocked_by_thirty_minute_symmetric_buffer
        """
        ctx = self._booked_escort(api)

        second = add_escort_action(api, ctx, "2026-08-02T13:00:00Z", "2026-08-02T14:00:00Z")

        assert_case_action(second, status="SCHEDULED", duration_minutes=60)
        assert_escort_ledger(read_employee(api, ctx["escort"]["id"]), 300)
        assert_total_count(_case_actions(api, ctx), 2)


class TestAreaRestrictionCeiling:
    """An occupancy cap of eight tolerates exactly one other overlapping restriction."""

    def _two_overlapping_restrictions(self, api: ApiClient):
        ctx = setup_monitoring_case(api)
        ctx["second_subject"] = setup_employee(
            api,
            ctx["worksite"]["id"],
            ctx["work_area"]["id"],
            full_name="Tom Reyes",
            job_function="CASH_HANDLING",
        )
        ctx["third_subject"] = setup_employee(
            api,
            ctx["worksite"]["id"],
            ctx["work_area"]["id"],
            full_name="Iris Wong",
            job_function="CASH_HANDLING",
        )
        add_restriction_action(api, ctx, "2026-08-05T00:00:00Z", "2026-08-10T00:00:00Z")
        add_restriction_action(
            api,
            ctx,
            "2026-08-05T00:00:00Z",
            "2026-08-10T00:00:00Z",
            subject_id=ctx["second_subject"]["id"],
        )
        return ctx

    def test_a_third_overlapping_restriction_reaches_the_area_ceiling(
        self, api: ApiClient
    ) -> None:
        """With two live restrictions already overlapping, the third is refused and no counter moves.

        PRD: "Finally, `ACCESS_RESTRICTION` respects an area ceiling: the number of *other* access restrictions in `SCHEDULED` or `ACTIVE` status on the same `work_area_id` whose half-open interval overlaps the requested one must stay **below** one quarter of the area's `occupancy_cap` with any fraction discarded, subject to a hard minimum of one — so an area with an `occupancy_cap` of 4 or fewer tolerates no concurrent overlapping restriction at all, one with a cap of 8 tolerates one, and one with a cap of 12 tolerates two."
        Design: Difficulty/resource_temporal_overlap/work_area_restriction_aggregate_cap_with_unbuffered_half_open_overlap
        """
        ctx = self._two_overlapping_restrictions(api)
        assert_restriction_counters(
            read_work_area(api, ctx["work_area"]["id"]),
            read_employee(api, ctx["third_subject"]["id"]),
            2,
            0,
        )

        response = api.create_case_action(
            build_access_restriction(
                ctx["case"]["id"],
                ctx["third_subject"]["id"],
                ctx["work_area"]["id"],
                "2026-08-06T00:00:00Z",
                "2026-08-08T00:00:00Z",
            ),
            ctx["headers"]["security_coordinator"],
        )

        validate_error(response, ApiErrorId.AREA_RESTRICTION_CAPACITY, 409)
        assert_restriction_counters(
            read_work_area(api, ctx["work_area"]["id"]),
            read_employee(api, ctx["third_subject"]["id"]),
            2,
            0,
        )
        assert_total_count(_case_actions(api, ctx), 2)

    def test_a_restriction_starting_the_instant_the_others_end_does_not_conflict(
        self, api: ApiClient
    ) -> None:
        """Half-open intervals meeting endpoint-to-endpoint are accepted, unlike the buffered escort rule.

        PRD: "Note the deliberate asymmetry with the escort rule: this check uses plain half-open overlap with no buffer, so a new restriction starting at exactly the instant a previous one ends does **not** conflict, whereas two escorts in that position do."
        Design: Difficulty/resource_temporal_overlap/work_area_restriction_aggregate_cap_with_unbuffered_half_open_overlap
        """
        ctx = self._two_overlapping_restrictions(api)

        third = add_restriction_action(
            api,
            ctx,
            "2026-08-10T00:00:00Z",
            "2026-08-12T00:00:00Z",
            subject_id=ctx["third_subject"]["id"],
        )

        assert_case_action(third, status="SCHEDULED", duration_minutes=2880)
        assert_restriction_counters(
            read_work_area(api, ctx["work_area"]["id"]),
            read_employee(api, ctx["third_subject"]["id"]),
            3,
            1,
        )
        assert_total_count(_case_actions(api, ctx), 3)


class TestEffectiveMeasureSet:
    """Restraining-order support is legal assistance and never counts as covered time."""

    def test_a_case_with_no_measures_shows_the_entire_window_as_a_gap(
        self, api: ApiClient
    ) -> None:
        """The half-open fourteen-day window is 20,160 minutes, so the untouched gap is 336.00 hours.

        PRD: "A case with no protective measures at all therefore shows the full 336.00 hours as a gap, and a single measure covering only the window's first day shows 312.00."
        Design: Difficulty/boundary_precision_check/empty_effective_measure_set_yields_full_window_gap
        """
        ctx = setup_monitoring_case(api)

        case = read_case(api, ctx)

        assert case["protection_window_start"] == WINDOW_START
        assert case["protection_window_end"] == WINDOW_END
        assert_protection(case, coverage_gap_hours=336.00, protection_status="GAP")
        assert_case_state(case, status="MONITORING", open_action_count=0)
        assert_total_count(_case_actions(api, ctx), 0)

    def test_restraining_order_support_spanning_the_window_leaves_the_gap_untouched(
        self, api: ApiClient
    ) -> None:
        """A measure over the whole window is recorded at 20,160 minutes yet the gap stays 336.00 hours.

        PRD: "The candidate measures are the case's `PROTECTIVE` actions whose `status` is `SCHEDULED` or `ACTIVE`, **excluding** `RESTRAINING_ORDER_SUPPORT`, which is legal assistance rather than physical coverage and never counts as time covered."
        Design: Difficulty/boundary_precision_check/empty_effective_measure_set_yields_full_window_gap
        """
        ctx = setup_monitoring_case(api)

        order = get_success_data(
            api.create_case_action(
                build_protective_action(
                    ctx["case"]["id"],
                    "RESTRAINING_ORDER_SUPPORT",
                    ctx["rep"]["id"],
                    WINDOW_START,
                    WINDOW_END,
                    note="Counsel is assisting with the petition.",
                ),
                ctx["headers"]["security_coordinator"],
            )
        )

        assert_case_action(order, status="SCHEDULED", duration_minutes=20160)
        case = read_case(api, ctx)
        assert_protection(case, coverage_gap_hours=336.00, protection_status="GAP")
        assert_case_state(case, status="MONITORING", open_action_count=0)
