"""Which of two simultaneous violations the admission ladder reports first."""

from test_helpers import (
    ApiErrorId,
    FIELD_TECHNICIAN,
    NETWORK_ENGINEER,
    SYSTEM_CONTROLLER,
    api_client,
    assert_loop_state,
    assert_plan_metrics,
    assert_segment_condition,
    campus_dispatch_stack,
    create_plan,
    create_segment,
    create_work_order,
    decide_permit,
    decommit_plan,
    get_success_data,
    industrial_boundary_stack,
    optimize_plan,
    plan_review_payload,
    read_asset,
    read_loop,
    read_plan,
    read_work_order,
    submit_permit,
    submit_plan,
    validate_error,
)


def _read_segment(segment_id):
    return get_success_data(api_client.get_pipe_segment(segment_id, NETWORK_ENGINEER))


def _approve(plan_id, note):
    return api_client.review_dispatch_plan(
        plan_id, plan_review_payload("APPROVE", review_note=note), SYSTEM_CONTROLLER
    )


class TestStateGateBeatsReserveMargin:
    """A draft plan that also fails the reserve floor reports the state problem."""

    def _thin_reserve_plan(self):
        stack = industrial_boundary_stack()
        plan = create_plan(stack["loop"]["id"], stack["forecast"]["id"])
        optimize_plan(plan["id"])
        stack["plan"] = read_plan(plan["id"])
        return stack

    def test_the_optimised_plan_really_does_fail_the_reserve_floor(self):
        """The fixture is only interesting if both violations are genuinely present.

        PRD: "`reserve_margin_pct` is then that N-1 capacity less the forecast's
        `coincident_demand_kw`, divided by that same demand, multiplied by 100, and
        rounded half-up to two decimal places".

        Design: Difficulty/priority_pair_validation_conflict/plan_state_beats_reserve_margin_on_review_of_draft_plan
        """
        stack = self._thin_reserve_plan()

        assert_plan_metrics(
            stack["plan"],
            plan_state="DRAFT",
            unserved_demand_kw=0.00,
            reserve_margin_pct=12.09,
            fuel_diversity_hhi=0.3395,
        )

    def test_reviewing_a_draft_plan_reports_the_state_gate_not_the_margin(self):
        """The state gate sits above the operational safety gates on the ladder.

        PRD: "**State gates.** The target must be in the from-state the requested
        transition declares: `ERR_PLAN_STATE_INVALID`, `ERR_FORECAST_STATE_INVALID`,
        `ERR_AGREEMENT_STATE_INVALID`, `ERR_INVOICE_STATE_INVALID`,
        `ERR_WORK_ORDER_STATE_INVALID`, `ERR_PROJECT_STATE_INVALID`,
        `ERR_METER_STATE_INVALID` and `ERR_AVAILABILITY_STATE_INVALID` — all 409."

        Design: Difficulty/priority_pair_validation_conflict/plan_state_beats_reserve_margin_on_review_of_draft_plan
        """
        stack = self._thin_reserve_plan()

        response = _approve(stack["plan"]["id"], "attempted approval from DRAFT")

        validate_error(response, ApiErrorId.PLAN_STATE_INVALID)

    def test_submitting_removes_only_the_state_violation(self):
        """Submission is legal despite the thin reserve, which review alone polices.

        PRD: "**Submission** advances the plan from `DRAFT` to `SUBMITTED` and
        accepts an optional `submission_note`."

        Design: Difficulty/priority_pair_validation_conflict/plan_state_beats_reserve_margin_on_review_of_draft_plan
        """
        stack = self._thin_reserve_plan()
        _approve(stack["plan"]["id"], "attempted approval from DRAFT")

        submitted = submit_plan(stack["plan"]["id"], "now submitted")

        assert_plan_metrics(submitted, plan_state="SUBMITTED", reserve_margin_pct=12.09)

    def test_the_same_review_call_now_reports_the_reserve_margin(self):
        """With the state satisfied the safety gate finally becomes visible.

        PRD: "the plan's `reserve_margin_pct` must be at or above 15.00 percent, or
        the approval is refused with `ERR_RESERVE_MARGIN_INSUFFICIENT`".

        Design: Difficulty/priority_pair_validation_conflict/plan_state_beats_reserve_margin_on_review_of_draft_plan
        """
        stack = self._thin_reserve_plan()
        _approve(stack["plan"]["id"], "attempted approval from DRAFT")
        submit_plan(stack["plan"]["id"], "now submitted")

        response = _approve(stack["plan"]["id"], "attempted approval from SUBMITTED")

        validate_error(response, ApiErrorId.RESERVE_MARGIN_INSUFFICIENT)

    def test_neither_refusal_records_a_reviewer_or_advances_the_plan(self):
        """Two rejected approvals leave the plan submitted and unsigned.

        PRD: "either branch stores the reviewing `X-User-ID` into
        `reviewed_by_user_id` and increments the plan's `version` by 1, and both
        require the plan to be `SUBMITTED` and the reviewer to differ from
        `authored_by_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/plan_state_beats_reserve_margin_on_review_of_draft_plan
        """
        stack = self._thin_reserve_plan()
        _approve(stack["plan"]["id"], "attempted approval from DRAFT")
        submit_plan(stack["plan"]["id"], "now submitted")
        _approve(stack["plan"]["id"], "attempted approval from SUBMITTED")

        assert_plan_metrics(
            read_plan(stack["plan"]["id"]),
            plan_state="SUBMITTED",
            reviewed_by_user_id=None,
        )


class TestSafetyGateBeatsWorkWindow:
    """An excavation blocked by a live commitment reports isolation, not timing."""

    def _committed_loop_with_scheduled_dig(self):
        stack = campus_dispatch_stack(plan_state="COMMITTED")
        segment = create_segment(
            stack["loop"]["id"],
            code="SEG-C1",
            length_m=600.0,
            diameter_mm=250,
            install_year=2006,
            insulation_class="B",
            buried_depth_m=1.4,
        )
        order = create_work_order(
            segment["id"],
            stack["loop"]["id"],
            "2026-09-01T08:00:00Z",
            "2026-09-01T16:00:00Z",
            reporter_headers=FIELD_TECHNICIAN,
            work_type="VALVE_REPLACEMENT",
            requires_isolation=True,
        )
        submit_permit(order["id"], FIELD_TECHNICIAN)
        decide_permit(order["id"], "GRANTED", decision_note="permit issued")
        stack["segment"] = segment
        stack["order"] = order
        return stack

    def test_breaking_ground_under_a_committed_plan_reports_isolation_clearance(self):
        """The safety gate fires even though the clock is a month early.

        PRD: "When `requires_isolation` is true, no dispatch plan on the loop may be
        in `plan_state` `COMMITTED` — you do not isolate a loop that the plant is
        actively serving — and a violation is refused with
        `ERR_ISOLATION_CLEARANCE_DENIED`."

        Design: Difficulty/priority_pair_validation_conflict/isolation_clearance_beats_outside_work_window_on_begin_excavation
        """
        stack = self._committed_loop_with_scheduled_dig()

        response = api_client.begin_excavation(
            stack["order"]["id"], {}, FIELD_TECHNICIAN
        )

        validate_error(response, ApiErrorId.ISOLATION_CLEARANCE_DENIED)

    def test_withdrawing_the_commitment_clears_the_loop_for_the_dig(self):
        """Decommitment removes the safety violation and nothing else.

        PRD: "**Decommitment** is the exact compensating move, available to a
        `SystemController` on a `COMMITTED` plan with an optional `reason`."

        Design: Difficulty/priority_pair_validation_conflict/isolation_clearance_beats_outside_work_window_on_begin_excavation
        """
        stack = self._committed_loop_with_scheduled_dig()
        api_client.begin_excavation(stack["order"]["id"], {}, FIELD_TECHNICIAN)

        withdrawn = decommit_plan(stack["plan"]["id"], "clearing the loop for excavation")

        assert_plan_metrics(withdrawn, plan_state="DRAFT")
        assert read_asset(stack["storage"]["id"])["state_of_charge_kwh"] == 4000.0

    def test_the_same_call_then_reports_the_work_window(self):
        """With the loop free the temporal gate one rung below finally speaks.

        PRD: "And the logical clock must sit at or after the order's `window_start`
        and at or before its `window_end`, or the request is refused with
        `ERR_OUTSIDE_WORK_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/isolation_clearance_beats_outside_work_window_on_begin_excavation
        """
        stack = self._committed_loop_with_scheduled_dig()
        api_client.begin_excavation(stack["order"]["id"], {}, FIELD_TECHNICIAN)
        decommit_plan(stack["plan"]["id"], "clearing the loop for excavation")

        response = api_client.begin_excavation(
            stack["order"]["id"], {}, FIELD_TECHNICIAN
        )

        validate_error(response, ApiErrorId.OUTSIDE_WORK_WINDOW)

    def test_two_refused_digs_leave_the_ground_the_segment_and_the_loop_untouched(self):
        """Nothing was excavated, so nothing was cascaded.

        PRD: "On success the order becomes `EXCAVATING` and the segment's
        `condition` is cascaded to `UNDER_REPAIR` with the segment's `version`
        incremented by 1, from whichever band it held".

        Design: Difficulty/priority_pair_validation_conflict/isolation_clearance_beats_outside_work_window_on_begin_excavation
        """
        stack = self._committed_loop_with_scheduled_dig()
        api_client.begin_excavation(stack["order"]["id"], {}, FIELD_TECHNICIAN)
        decommit_plan(stack["plan"]["id"], "clearing the loop for excavation")
        api_client.begin_excavation(stack["order"]["id"], {}, FIELD_TECHNICIAN)

        assert read_work_order(stack["order"]["id"])["work_state"] == "SCHEDULED"
        assert_segment_condition(_read_segment(stack["segment"]["id"]), condition="SOUND")
        assert_loop_state(
            read_loop(stack["loop"]["id"]), posture="NORMAL", open_isolation_count=0
        )
