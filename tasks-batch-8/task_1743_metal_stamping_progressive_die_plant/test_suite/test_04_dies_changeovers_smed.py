"""Die lifecycle, changeover calendar discipline, and SMED variance (PRD §2.10, §3.3, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_run,
    create_assignment,
    create_customer,
    create_die,
    create_die_change_event_payload,
    create_part,
    create_press,
    get_die,
    get_success_data,
    install_die_on_press,
    schedule_run,
    set_clock,
    setup_completed_run,
    setup_runnable,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_LEAD = TEST_USERS["setup_lead_headers"]


class TestChangeoverStateMachine:
    def test_complete_from_planned_is_invalid_transition(self, api, setup_lead_headers):
        """PRD §3.6: "Completing the changeover moves `IN_PROGRESS` to the terminal `COMPLETED`."
        PRD §2.5: "4. **State-machine precondition.** The target resource's current state permits the requested action — a run must be `RUNNING` to complete, a coil must be `APPROVED` to feed a run start, and so on through every state machine in §3. Failure: `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/die_change_complete_from_planned_rejected
        """
        press = create_press(press_code="PR-IV")
        die = create_die(die_code="D-IV", rated_tonnage=300, min_bed_width_mm=1800)
        event = get_success_data(
            api.create_die_change_event(
                create_die_change_event_payload(
                    press["id"], die["id"],
                    planned_start="2026-08-01T06:00:00Z",
                    planned_end="2026-08-01T07:00:00Z",
                ),
                setup_lead_headers,
            )
        )
        assert event["status"] == "PLANNED"
        resp = api.complete_die_change_event(event["id"], setup_lead_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_die_change_event(event["id"], setup_lead_headers))
        assert after["status"] == "PLANNED"

    def test_undersized_press_rejected_at_changeover_start(self, api, setup_lead_headers):
        """PRD §3.6: "the press must physically fit the die, `tonnage` at least the die's `rated_tonnage` and `bed_width_mm` at least the die's `min_bed_width_mm`, else `ERR_PRESS_CAPACITY_INSUFFICIENT`."

        Design: Corner/validations/press_capacity_fit_enforced_at_changeover_start
        """
        press = create_press(press_code="PR-SMALL", tonnage=200, bed_width_mm=2500)
        die = create_die(die_code="D-BIG", rated_tonnage=400, min_bed_width_mm=1500)
        event = get_success_data(
            api.create_die_change_event(
                create_die_change_event_payload(press["id"], die["id"]),
                setup_lead_headers,
            )
        )
        resp = api.start_die_change_event(event["id"], setup_lead_headers)
        validate_error(resp, ApiErrorId.ERR_PRESS_CAPACITY_INSUFFICIENT)
        after = validate_success(api.get_die_change_event(event["id"], setup_lead_headers))
        assert after["status"] == "PLANNED", "a rejected start must not move the event"


class TestSmedVariance:
    def _setup_two_completed_changeovers(self, api):
        """Two COMPLETED changeovers on one press with sub-minute actual durations
        (47min30s against a 45-minute target; 38min20s against a 42-minute target)."""
        set_clock()
        press = create_press(press_code="PR-X")
        die1 = create_die(die_code="D-X1", rated_tonnage=300, min_bed_width_mm=1800)
        die2 = create_die(die_code="D-X2", rated_tonnage=350, min_bed_width_mm=1900)

        e1 = get_success_data(api.create_die_change_event(
            create_die_change_event_payload(
                press["id"], die1["id"],
                planned_start="2026-08-01T10:00:00Z",
                planned_end="2026-08-01T11:00:00Z",
                smed_target_minutes=45,
            ),
            SETUP_LEAD,
        ))
        set_clock("2026-08-01T10:00:00Z")
        get_success_data(api.start_die_change_event(e1["id"], SETUP_LEAD))
        set_clock("2026-08-01T10:47:30Z")
        e1_done = get_success_data(api.complete_die_change_event(e1["id"], SETUP_LEAD))

        e2 = get_success_data(api.create_die_change_event(
            create_die_change_event_payload(
                press["id"], die2["id"], from_die_id=die1["id"],
                planned_start="2026-08-01T12:00:00Z",
                planned_end="2026-08-01T13:00:00Z",
                smed_target_minutes=42,
            ),
            SETUP_LEAD,
        ))
        set_clock("2026-08-01T12:00:00Z")
        get_success_data(api.start_die_change_event(e2["id"], SETUP_LEAD))
        set_clock("2026-08-01T12:38:20Z")
        e2_done = get_success_data(api.complete_die_change_event(e2["id"], SETUP_LEAD))
        return press, e1_done, e2_done

    def test_first_event_variance_truncates_seconds_before_subtracting(self, api):
        """PRD §3.6: "Completion also computes `variance_minutes`: the elapsed time between `actual_start` and `actual_end`, truncated down to a whole number of minutes, minus the `smed_target_minutes`."
        PRD §2.7: "Changeover performance uses whole minutes per event — elapsed seconds are truncated down to whole minutes — while the rolling SMED performance average is rounded to 2 decimal places, round half up."

        Design: Difficulty/combinatorial_formula/smed_rolling_average_of_truncated_variances
        """
        _press, e1_done, _e2_done = self._setup_two_completed_changeovers(api)
        # 47min30s truncates to 47 whole minutes; 47 - 45 = +2.
        assert e1_done["status"] == "COMPLETED"
        assert e1_done["variance_minutes"] == 2, (
            f"expected variance_minutes == 2 (floor(47min30s)=47 minus target 45), "
            f"got {e1_done['variance_minutes']}"
        )

    def test_second_event_variance_goes_negative_on_truncated_minutes(self, api):
        """PRD §3.6: "Completion also computes `variance_minutes`: the elapsed time between `actual_start` and `actual_end`, truncated down to a whole number of minutes, minus the `smed_target_minutes`."
        PRD §2.7: "Changeover performance uses whole minutes per event — elapsed seconds are truncated down to whole minutes — while the rolling SMED performance average is rounded to 2 decimal places, round half up."

        Design: Difficulty/combinatorial_formula/smed_rolling_average_of_truncated_variances
        """
        _press, _e1_done, e2_done = self._setup_two_completed_changeovers(api)
        # 38min20s truncates to 38 whole minutes; 38 - 42 = -4 (crew beat target).
        assert e2_done["status"] == "COMPLETED"
        assert e2_done["variance_minutes"] == -4, (
            f"expected variance_minutes == -4 (floor(38min20s)=38 minus target 42), "
            f"got {e2_done['variance_minutes']}"
        )


class TestChangeoverTeardownBuffer:
    def test_new_changeover_buffer_overlapping_existing_run_rejected(self, api, setup_lead_headers):
        """PRD §3.6: "A planned event starts in `PLANNED` and is subject at creation time to the press-calendar rule of §2.10: its window, extended thirty minutes past `planned_end` for teardown, must not overlap any other `PLANNED` or `IN_PROGRESS` changeover or any `SCHEDULED` or `RUNNING` run on the same press, on pain of `ERR_CHANGEOVER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/changeover_teardown_buffer_overlap
        """
        # Die install happens 04:00-05:00; the run under test sits 07:15-08:00.
        ctx = setup_runnable(
            quantity_ordered=100, coil_weight_kg=2000,
            changeover_start="2026-08-01T04:00:00Z",
            changeover_end="2026-08-01T05:00:00Z",
        )
        schedule_run(ctx, "2026-08-01T07:15:00Z", "2026-08-01T08:00:00Z")

        # New changeover planned 06:00-07:00: its teardown-extended window
        # [06:00, 07:30) overlaps the run's [07:15, 08:00) on the same press.
        resp = api.create_die_change_event(
            create_die_change_event_payload(
                ctx["press"]["id"], ctx["die"]["id"],
                planned_start="2026-08-01T06:00:00Z",
                planned_end="2026-08-01T07:00:00Z",
            ),
            setup_lead_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_CONFLICT)

        # Control: the identical window on a different press is accepted.
        other_press = create_press()
        ok = api.create_die_change_event(
            create_die_change_event_payload(
                other_press["id"], ctx["die"]["id"],
                planned_start="2026-08-01T06:00:00Z",
                planned_end="2026-08-01T07:00:00Z",
            ),
            setup_lead_headers,
        )
        validate_success(ok, expected_status=201)

    def test_overlapping_changeovers_on_same_press_rejected(self, api, setup_lead_headers):
        """PRD §2.10: "A new die changeover's occupancy runs from its `planned_start` to thirty minutes after its `planned_end`, and that extended window must not overlap any `PLANNED` or `IN_PROGRESS` changeover on the same press, nor the window of any `SCHEDULED` or `RUNNING` production run on that press. A violation is rejected with `ERR_CHANGEOVER_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/changeover_teardown_buffer_overlap
        """
        press = create_press()
        die_a = create_die()
        die_b = create_die()
        die_c = create_die()
        c1 = api.create_die_change_event(
            create_die_change_event_payload(
                press["id"], die_a["id"],
                planned_start="2026-08-01T06:00:00Z",
                planned_end="2026-08-01T07:00:00Z",
            ),
            setup_lead_headers,
        )
        validate_success(c1, expected_status=201)

        # C2's window [06:30, 07:30) overlaps C1 (PLANNED) on the same press.
        conflict = api.create_die_change_event(
            create_die_change_event_payload(
                press["id"], die_b["id"],
                planned_start="2026-08-01T06:30:00Z",
                planned_end="2026-08-01T07:30:00Z",
            ),
            setup_lead_headers,
        )
        validate_error(conflict, ApiErrorId.ERR_CHANGEOVER_CONFLICT)

        # Control: C3 starts strictly after C1's occupancy including teardown ends.
        clear = api.create_die_change_event(
            create_die_change_event_payload(
                press["id"], die_c["id"],
                planned_start="2026-08-01T07:45:00Z",
                planned_end="2026-08-01T08:15:00Z",
            ),
            setup_lead_headers,
        )
        validate_success(clear, expected_status=201)


class TestDieRepairCycle:
    def test_repair_cycle_preserves_lifetime_shots_and_resets_counter(self, api, toolroom_manager_headers):
        """PRD §3.3: "Two counters age the die: `total_shots_lifetime`, the cumulative strokes across every production run that ever used it, and `shots_since_repair`, the strokes since the last completed repair — both start at 0."
        PRD §3.3: "Completing the repair returns the die from `IN_REPAIR` to `AVAILABLE` and resets `shots_since_repair` to 0."

        Design: Difficulty/compensating_invariant/die_shot_lifetime_conservation_under_repair_cycle
        """
        ctx = setup_completed_run(
            shots_recorded=120, quantity_ordered=500, coil_weight_kg=1000,
            die_overrides={"die_code": "D-17", "repair_threshold_shots": 100},
        )
        die_mid = get_die(ctx["die"]["id"])
        assert die_mid["total_shots_lifetime"] == 120
        assert die_mid["shots_since_repair"] == 120

        validate_success(api.send_die_to_repair(ctx["die"]["id"], toolroom_manager_headers))
        repaired = validate_success(api.complete_die_repair(ctx["die"]["id"], toolroom_manager_headers))
        assert repaired["status"] == "AVAILABLE"
        assert repaired["shots_since_repair"] == 0, "only the per-repair counter resets"
        assert repaired["total_shots_lifetime"] == 120, (
            "the conserved lifetime counter is NOT reset by the repair pair"
        )

    def test_send_to_repair_below_threshold_rejected(self, api, toolroom_manager_headers):
        """PRD §3.3: "A `ToolroomManager` may send a die to repair from either `AVAILABLE` or `ASSIGNED`, but only once its `shots_since_repair` has reached or exceeded its `repair_threshold_shots`; attempting repair earlier violates the transition's precondition and is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/compensating_invariant/die_shot_lifetime_conservation_under_repair_cycle
        """
        die = create_die(die_code="D-EARLY", repair_threshold_shots=1000)
        resp = api.send_die_to_repair(die["id"], toolroom_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_die(die["id"])["status"] == "AVAILABLE"

    def test_die_at_threshold_blocked_from_changeover_start(self, api, setup_lead_headers):
        """PRD §3.6: "the incoming die must be `AVAILABLE` and below its repair threshold — a die whose `shots_since_repair` has reached or exceeded its `repair_threshold_shots` is rejected with `ERR_QUALITY_HOLD`"
        PRD §3.3: "Symmetrically, the threshold policy also blocks the other direction: a die that is at or beyond its repair threshold cannot be scheduled into new work — starting a changeover with it or running against it is rejected with `ERR_QUALITY_HOLD` (§3.6, §3.7)."

        Design: Corner/complexity_layers/rate_threshold_die_repair_gate
        """
        # Die D-TH1 (threshold 100) accumulates exactly 100 shots; die D-TH2
        # (threshold 101) accumulates 100 shots and remains schedulable.
        ctx = setup_runnable(
            quantity_ordered=500, coil_weight_kg=1000,
            die_overrides={"die_code": "D-TH1", "repair_threshold_shots": 100},
        )
        die2 = create_die(die_code="D-TH2", rated_tonnage=300, min_bed_width_mm=1800,
                          repair_threshold_shots=101)

        run1 = schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z")
        start_run(run1["id"])
        complete_run(run1["id"], 100, ctx["coil"]["id"])
        assert get_die(ctx["die"]["id"])["shots_since_repair"] == 100

        # Swap the press to die2 (one shot below its own threshold after its run).
        install_die_on_press(
            ctx["press"]["id"], die2["id"],
            planned_start="2026-08-01T10:00:00Z", planned_end="2026-08-01T11:00:00Z",
            from_die_id=ctx["die"]["id"],
        )
        create_assignment(ctx["part"]["id"], die2["id"])
        run2 = schedule_run(ctx, "2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z",
                            die_id=die2["id"])
        start_run(run2["id"])
        complete_run(run2["id"], 100, ctx["coil"]["id"])
        assert get_die(die2["id"])["shots_since_repair"] == 100

        # D-TH1 at exactly 100 >= 100 cannot be installed again.
        event = get_success_data(api.create_die_change_event(
            create_die_change_event_payload(
                ctx["press"]["id"], ctx["die"]["id"], from_die_id=die2["id"],
                planned_start="2026-08-01T14:00:00Z",
                planned_end="2026-08-01T15:00:00Z",
            ),
            setup_lead_headers,
        ))
        resp = api.start_die_change_event(event["id"], setup_lead_headers)
        validate_error(resp, ApiErrorId.ERR_QUALITY_HOLD)
        assert get_die(ctx["die"]["id"])["status"] == "AVAILABLE", (
            "a blocked changeover must not assign the die"
        )

    def test_die_retire_deletes_part_die_assignments(self, api, toolroom_manager_headers, process_engineer_headers):
        """PRD §3.3: "Retirement is allowed only from `AVAILABLE` and only while no `SCHEDULED` or `RUNNING` production run references the die; retiring moves the die to the terminal `RETIRED` state and deletes all of its part–die assignments."

        Design: Corner/state_machines/die_retire_deletes_assignments
        """
        customer = create_customer(name="Ret Co", customer_code="RET")
        part = create_part(customer["id"], part_number="P-RET")
        die = create_die(die_code="D-RET")
        create_assignment(part["id"], die["id"])
        retired = validate_success(api.retire_die(die["id"], toolroom_manager_headers))
        assert retired["status"] == "RETIRED"
        rows, meta = validate_paginated(
            api.list_part_die_assignments_filtered(
                process_engineer_headers, params={"die_id": die["id"]}
            )
        )
        assert rows == [], f"retiring the die must delete its assignments, got {len(rows)}"
