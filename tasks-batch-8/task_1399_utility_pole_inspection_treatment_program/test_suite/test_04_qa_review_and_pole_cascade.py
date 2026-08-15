"""QA review on inspection tasks: rework loop, escalation, segregation of duties,
and the pole classification cascade (PRD §3.4, §3.8)."""
import pytest

from test_helpers import (
    CLOCK_DEFAULT_ISO,
    ApiErrorId,
    assert_instant_equals,
    assert_pole,
    default_photos,
    get_cycle,
    get_pole,
    get_task,
    make_qa_reviewer_headers,
    qa_review_task,
    setup_accepted_pole,
    setup_open_cycle_with_task,
    submit_task,
    validate_error,
    validate_paginated,
    validate_success,
)

SERVICEABLE_READINGS = dict(
    shell_thickness_in=2.50, sound_wood_pct=90, decay_pocket_depth_in=0.0,
    moisture_pct=20,
)
PRIORITY_REJECT_READINGS = dict(
    shell_thickness_in=2.00, sound_wood_pct=30, decay_pocket_depth_in=0.4,
    moisture_pct=25, hazard_flag=True,
    photos=default_photos("GROUNDLINE", "TAG", "DECAY_POCKET"),
)


class TestReworkLoop:
    def _setup_rejected_once(self, api):
        pole, cycle, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-RW"}
        )
        submit_task(task["id"], **SERVICEABLE_READINGS)
        resp = qa_review_task(task["id"], "REJECT", notes="redo boring")
        return pole, cycle, task, resp

    def test_task_reject_loops_to_open_with_cleared_readings(
            self, api, program_manager_headers):
        """PRD §3.4: "While `rework_count` is below two, a reject moves the task to
        `REJECTED`, increments `rework_count` by one, and clears the field readings,
        photos, and computed strength and classification fields back to their null
        defaults; the system then immediately returns the task from `REJECTED` to
        `OPEN`, so the inspector can redo the field work from a clean sheet."

        Design: Difficulty/non_linear_state_machine/task_rework_cycle_then_accept
        """
        _, _, task, resp = self._setup_rejected_once(api)
        assert resp["status"] == "OPEN", (
            f"rejected task must loop straight back to OPEN, got {resp['status']}"
        )
        assert resp["rework_count"] == 1
        after = get_task(task["id"])
        assert after["status"] == "OPEN"
        assert after["rework_count"] == 1
        for field in ("shell_thickness_in", "sound_wood_pct", "decay_pocket_depth_in",
                      "moisture_pct", "rs_conservative_pct", "rs_statistical_pct",
                      "effective_rs_pct", "classification"):
            assert after[field] is None, f"{field} must be cleared to null, got {after[field]}"
        assert after["photos"] == [], "photos must be cleared by the rework loop"

    def test_task_rework_then_accept_completes(self, api, program_manager_headers):
        """PRD §3.4: "An `ACCEPT` decision moves the task to the terminal `ACCEPTED`
        state and runs the pole's classification cascade. The pole's
        `current_classification` takes the task's classification,
        `current_remaining_strength_pct` takes the task's `effective_rs_pct`,
        `last_inspection_date` is set from the logical clock, and the pole's `version`
        increments."

        Design: Difficulty/non_linear_state_machine/task_rework_cycle_then_accept
        """
        pole, _, task, _ = self._setup_rejected_once(api)
        resubmitted = submit_task(task["id"], **SERVICEABLE_READINGS)
        assert resubmitted["status"] == "SUBMITTED"
        accepted = qa_review_task(task["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        after = get_pole(pole["id"])
        assert after["current_classification"] == "SERVICEABLE"
        assert after["current_remaining_strength_pct"] == pytest.approx(100.00, abs=0.005)
        assert_instant_equals(after["last_inspection_date"], CLOCK_DEFAULT_ISO,
                              "last_inspection_date")
        assert after["version"] == pole["version"] + 1


class TestReworkLimitEscalation:
    def test_rework_limit_escalates_to_terminal(self, api, program_manager_headers):
        """PRD §3.4: "When a reject arrives with `rework_count` already at two — the
        third rejection — the task instead moves to the terminal `ESCALATED` state,
        `rework_count` rises to its final value of three, and the cycle's
        `tasks_terminal` is recomputed."
        PRD §3.4: "The review is valid only while the task is `SUBMITTED`; reviewing a
        task in any other state is rejected with `ERR_TASK_NOT_SUBMITTED`."

        Design: Corner/state_machines/rework_limit_escalates_to_terminal
        """
        pole, cycle, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-ESC", "species": "LARCH",
                            "original_class": "2", "install_date": "2001-05-01",
                            "gis_tag": "RURAL", "height_ft": 35}
        )
        readings = dict(shell_thickness_in=2.00, sound_wood_pct=90,
                        decay_pocket_depth_in=0.0, moisture_pct=20)
        for _ in range(2):
            submit_task(task["id"], **readings)
            rejected = qa_review_task(task["id"], "REJECT")
            assert rejected["status"] == "OPEN"
        submit_task(task["id"], **readings)
        escalated = qa_review_task(task["id"], "REJECT")
        assert escalated["status"] == "ESCALATED", (
            "third rejection routes to terminal ESCALATED, not the rework loop"
        )
        assert escalated["rework_count"] == 3

        resp = api.qa_review_inspection_task(
            task["id"], {"decision": "ACCEPT"}, make_qa_reviewer_headers("qa-1")
        )
        validate_error(resp, ApiErrorId.ERR_TASK_NOT_SUBMITTED)


class TestQaReviewPreconditions:
    def test_qa_review_on_open_task_rejected(self, api, qa_reviewer_headers):
        """PRD §3.4: "The review is valid only while the task is `SUBMITTED`; reviewing
        a task in any other state is rejected with `ERR_TASK_NOT_SUBMITTED`."

        Design: Corner/state_machines/qa_review_on_open_task_rejected
        """
        _, _, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-QO", "species": "LARCH",
                            "original_class": "2", "install_date": "2001-05-01",
                            "gis_tag": "RURAL", "height_ft": 35}
        )
        resp = api.qa_review_inspection_task(
            task["id"], {"decision": "ACCEPT"}, qa_reviewer_headers
        )
        validate_error(resp, ApiErrorId.ERR_TASK_NOT_SUBMITTED)
        assert get_task(task["id"])["status"] == "OPEN"

    def test_sod_same_user_qa_rejected(self, api):
        """PRD §3.4: "Segregation of duties is strictly enforced: the reviewer's
        `X-User-ID` must differ from the task's `submitted_by_user_id`, and a
        self-review is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_same_user_qa_rejected
        """
        _, _, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-SOD", "species": "LARCH",
                            "original_class": "2", "install_date": "2001-05-01",
                            "gis_tag": "RURAL", "height_ft": 35}
        )
        submit_task(task["id"], shell_thickness_in=2.25, sound_wood_pct=100,
                    decay_pocket_depth_in=0.0, moisture_pct=20)
        resp = api.qa_review_inspection_task(
            task["id"], {"decision": "ACCEPT"}, make_qa_reviewer_headers("insp-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        after = get_task(task["id"])
        assert after["status"] == "SUBMITTED"
        assert after["qa_reviewed_by_user_id"] is None


class TestCycleCounters:
    def test_cycle_counters_recomputed_after_accept(self, api, program_manager_headers):
        """PRD §3.4: "Every `ACCEPT` — regardless of classification — recomputes the
        cycle's `tasks_terminal` counter."
        PRD §3.1: "System counters `sample_pool_size`, `tasks_total`, `tasks_terminal`,
        and `pending_replacement_count` track its progress".

        Design: Corner/endpoints/cycle_counters_recomputed_after_accept
        """
        pole, cycle, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-CC", "species": "LARCH",
                            "original_class": "2", "install_date": "2001-05-01",
                            "gis_tag": "RURAL", "height_ft": 35}
        )
        submit_task(task["id"], shell_thickness_in=2.25, sound_wood_pct=100,
                    decay_pocket_depth_in=0.0, moisture_pct=20)
        qa_review_task(task["id"], "ACCEPT")
        after = get_cycle(cycle["id"])
        assert after["tasks_total"] == 1
        assert after["tasks_terminal"] == 1, (
            "tasks_terminal must reflect the ACCEPT immediately"
        )


class TestRejectPriorityCascade:
    def _setup_priority_accept(self, api, program_manager_headers):
        pole, cycle, task = setup_open_cycle_with_task(
            pole_overrides={"pole_number": "P-CAS"}
        )
        submit_task(task["id"], **PRIORITY_REJECT_READINGS)
        accepted = qa_review_task(task["id"], "ACCEPT")
        assert accepted["classification"] == "REJECT_PRIORITY"
        assert accepted["effective_rs_pct"] == pytest.approx(28.00, abs=0.005)
        return pole, cycle, task

    def test_accept_reject_priority_pole_cascade(self, api, program_manager_headers):
        """PRD §3.4: "A `REJECT_PRIORITY` classification, accepted against a pole in
        `IN_SERVICE` or `MONITOR`, moves the pole to `PRIORITY_REJECT`".
        PRD §3.4: "The pole's `current_classification` takes the task's classification,
        `current_remaining_strength_pct` takes the task's `effective_rs_pct`,
        `last_inspection_date` is set from the logical clock".

        Design: Difficulty/transitive_cascade/accept_reject_priority_cascade_depth3
        """
        pole, _, _ = self._setup_priority_accept(api, program_manager_headers)
        after = get_pole(pole["id"])
        assert_pole(after)
        assert after["status"] == "PRIORITY_REJECT"
        assert after["current_classification"] == "REJECT_PRIORITY"
        assert after["current_remaining_strength_pct"] == pytest.approx(28.00, abs=0.005)
        assert_instant_equals(after["last_inspection_date"], CLOCK_DEFAULT_ISO,
                              "last_inspection_date")

    def test_accept_reject_priority_order_and_cycle_cascade(
            self, api, program_manager_headers):
        """PRD §3.4: "the system auto-creates a `ReplacementWorkOrder` in `QUEUED`
        status, linked to the task's cycle through `cycle_id`, carrying the program
        default estimate of 250,000 cents in `estimated_cost_cents`, with its
        `priority_score` computed at creation per §3.8, and the owning cycle's
        `pending_replacement_count` increments as the final link of the cascade."

        Design: Difficulty/transitive_cascade/accept_reject_priority_cascade_depth3
        """
        pole, cycle, _ = self._setup_priority_accept(api, program_manager_headers)
        data, _ = validate_paginated(
            api.list_replacement_work_orders(program_manager_headers,
                                             params={"pole_id": pole["id"]})
        )
        assert len(data) == 1, "exactly one replacement order must be auto-created"
        order = data[0]
        assert order["status"] == "QUEUED"
        assert order["cycle_id"] == cycle["id"]
        assert order["estimated_cost_cents"] == 250000
        assert order["escalated_cost_cents"] == 250000, "deferral_count 0 at creation"
        # deficiency = 100 - 28.00 = 72; no deferral / joint-use / age / critical terms.
        assert order["priority_score"] == 72
        cycle_after = get_cycle(cycle["id"])
        assert cycle_after["pending_replacement_count"] == 1


class TestPriorityScoreFloorAndCap:
    def _setup_critical_pole(self, api, program_manager_headers):
        """FEEDER_CRITICAL pole accepted at effective_rs 54.00 (MONITOR)."""
        return setup_accepted_pole(
            pole_overrides={
                "pole_number": "P-CRIT", "species": "SOUTHERN_PINE",
                "original_class": "3", "install_date": "1990-01-01",
                "gis_tag": "FEEDER_CRITICAL", "joint_use": False,
            },
            cycle_overrides={"year": 2026, "cycle_length_years": 10, "sample_pct": 0,
                             "strength_variant_policy": "CONSERVATIVE"},
            submit_overrides=dict(
                shell_thickness_in=1.50, sound_wood_pct=80, decay_pocket_depth_in=1.2,
                moisture_pct=25, hazard_flag=False,
            ),
        )

    def test_priority_score_feeder_critical_floor(self, api, program_manager_headers):
        """PRD §3.8: "Its composition is fixed and evaluated in a pinned order: start
        with a deficiency of 100 minus the pole's `current_remaining_strength_pct`,
        where a null strength counts as 50.00; add a deferral term of 5 points per
        deferral; add 10 points when the pole's `joint_use` flag is true; add 5 points
        when the pole's installation year is 1969 or earlier. That raw sum is then
        subject to the criticality floor — when the pole's `gis_tag` is
        `FEEDER_CRITICAL`, the sum is raised to at least 80 — and finally the score is
        capped at 100. Sum first, then floor, then cap."

        Design: Difficulty/combinatorial_formula/priority_score_nonlinear_floor_and_cap
        """
        pole, _, _ = self._setup_critical_pole(api, program_manager_headers)
        resp = api.create_replacement_work_order(
            {"pole_id": pole["id"], "estimated_cost_cents": 150000},
            program_manager_headers,
        )
        order = validate_success(resp, expected_status=201)
        # raw = deficiency 46.00 -> floored to exactly 80 by the criticality branch.
        assert order["priority_score"] == 80, (
            f"FEEDER_CRITICAL floor must raise raw 46 to 80, got {order['priority_score']}"
        )

    def test_priority_score_floor_pole_cascade_state(self, api, program_manager_headers):
        """PRD §3.4: "A `MONITOR` classification moves an `IN_SERVICE` pole to
        `MONITOR`."
        PRD §3.8: "`priority_score` is an integer computed at creation and again
        whenever a deferred order re-enters the queue at reconcile."

        Design: Difficulty/combinatorial_formula/priority_score_nonlinear_floor_and_cap
        """
        pole, _, accepted = self._setup_critical_pole(api, program_manager_headers)
        assert accepted["effective_rs_pct"] == pytest.approx(54.00, abs=0.005)
        after = get_pole(pole["id"])
        assert after["status"] == "MONITOR"
        assert after["current_classification"] == "MONITOR"
        assert after["current_remaining_strength_pct"] == pytest.approx(54.00, abs=0.005)
