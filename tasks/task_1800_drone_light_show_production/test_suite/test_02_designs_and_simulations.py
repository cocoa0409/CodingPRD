"""Design revisions, simulation verdicts, design locking, and the show OCC
guard on lock."""
from test_helpers import (
    ApiErrorId,
    create_design,
    create_show,
    create_show_design_payload,
    create_site,
    get_show,
    get_success_data,
    lock_design,
    record_simulation,
    set_clock,
    setup_authorized_show,
    setup_show_with_locked_design,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PLANNER = TEST_USERS["planner_headers"]


class TestSimulationRuns:
    def test_simulation_run_immutable_without_version(self, api):
        """PRD: "Three record types are immutable telemetry and carry only `id`
        and `created_at`: a **SimulationRun**, a **WeatherReading**, and a
        **FlightLog** have neither `updated_at` nor `version`."
        PRD: "`PASS` when the observed separation is at least the design's
        guaranteed `min_separation_m` (the boundary is inclusive — equality
        passes), the battery draw is at most 80 percent, and the speed is at
        most 12.0 meters per second; any shortfall yields `FAIL`."

        Design: Corner/entities/simulation_run_immutable_without_version
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        design = create_design(show["id"])
        run = validate_success(api.create_simulation_run(
            {"show_design_id": design["id"], "min_separation_observed_m": 3.5,
             "battery_draw_pct": 55, "max_speed_mps": 9.0}, PLANNER), 201)
        assert run["verdict"] == "PASS"
        assert "version" not in run and "updated_at" not in run
        assert run["id"] and run["created_at"]

        fetched = validate_success(api.get_simulation_run(run["id"], PLANNER))
        assert fetched["verdict"] == "PASS"
        assert "version" not in fetched and "updated_at" not in fetched

    def test_simulation_verdict_inclusive_thresholds(self, api):
        """PRD: "`PASS` when the observed separation is at least the design's
        guaranteed `min_separation_m` (the boundary is inclusive — equality
        passes), the battery draw is at most 80 percent, and the speed is at
        most 12.0 meters per second; any shortfall yields `FAIL`."
        PRD: "runs recorded against a `SIMULATED` design are stored without
        further state change, which is what makes the revision loop possible."

        Design: Corner/calculations/simulation_verdict_inclusive_thresholds
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        design = create_design(show["id"], min_separation_m=3.0)

        def run(sep, draw, speed):
            return validate_success(api.create_simulation_run(
                {"show_design_id": design["id"], "min_separation_observed_m": sep,
                 "battery_draw_pct": draw, "max_speed_mps": speed}, PLANNER),
                201)["verdict"]

        # Every threshold exactly at its boundary passes (inclusive).
        assert run(3.0, 80, 12.0) == "PASS"
        # Each metric independently failing yields FAIL.
        assert run(2.99, 50, 9.0) == "FAIL"    # separation shortfall
        assert run(3.5, 81, 9.0) == "FAIL"     # draw above 80
        assert run(3.5, 50, 12.5) == "FAIL"    # speed above 12.0


class TestDesignRevisionLoop:
    def test_lock_with_failing_latest_simulation_rejected_then_revision_loop(
            self, api):
        """PRD: "Locking requires the design to be `SIMULATED` (else
        `ERR_INVALID_STATE`), requires the most recent simulation run for the
        design — the latest by `created_at` — to hold a `PASS` verdict (else
        `ERR_SIMULATION_NOT_PASSING`)"
        PRD: "revising a `SIMULATED` design returns it to `DRAFT` for another
        round of simulation (any other from-state is `ERR_INVALID_STATE`)."

        Design: Difficulty/non_linear_state_machine/design_revision_loop_and_supersede_cycle
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        design = create_design(show["id"])
        fail_run = record_simulation(design["id"], min_separation_observed_m=2.5)
        assert fail_run["verdict"] == "FAIL", "2.5 < 3.0 guaranteed separation"

        show_now = get_show(show["id"])
        resp = api.lock_design(
            design["id"], {"expected_show_event_version": show_now["version"]},
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_SIMULATION_NOT_PASSING)

        revised = validate_success(api.revise_design(design["id"], PLANNER))
        assert revised["status"] == "DRAFT", "SIMULATED reverts to DRAFT"

        pass_run = record_simulation(design["id"], min_separation_observed_m=3.5)
        assert pass_run["verdict"] == "PASS"
        locked = lock_design(show["id"], design["id"])
        assert locked["status"] == "LOCKED"

    def test_second_lock_supersedes_prior_locked_design(self, api):
        """PRD: "Any other design for the same show that was `LOCKED` is
        automatically moved to `SUPERSEDED` with its own version incremented —
        a `LOCKED` design has no manual transitions out, only this automatic
        supersession."
        PRD: "Each design receives a `design_version_no`, a per-show monotone
        counter that starts at 1 and is assigned in creation order: the number
        is one more than the count of designs already existing for that show,
        regardless of those designs' statuses."

        Design: Difficulty/non_linear_state_machine/design_revision_loop_and_supersede_cycle
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        d1 = create_design(show["id"])
        record_simulation(d1["id"])
        lock_design(show["id"], d1["id"])

        d2 = create_design(show["id"], max_altitude_ft=320)
        record_simulation(d2["id"])
        lock_design(show["id"], d2["id"])

        assert d1["design_version_no"] == 1 and d2["design_version_no"] == 2
        d1_after = validate_success(api.get_show_design(d1["id"], PLANNER))
        assert d1_after["status"] == "SUPERSEDED", \
            "the prior LOCKED design is superseded by the new lock"


class TestDesignRelockCascade:
    def test_relock_supersedes_design(self, api):
        """PRD: "Any other design for the same show that was `LOCKED` is
        automatically moved to `SUPERSEDED` with its own version incremented"

        Design: Difficulty/transitive_cascade/design_relock_repin_downgrade_cascade
        """
        ctx = setup_authorized_show()
        show_id = ctx["show"]["id"]
        d1 = ctx["design"]

        d2 = create_design(show_id, max_altitude_ft=320)
        record_simulation(d2["id"])
        locked = lock_design(show_id, d2["id"])
        assert locked["status"] == "LOCKED"

        d1_after = validate_success(api.get_show_design(d1["id"], PLANNER))
        assert d1_after["status"] == "SUPERSEDED", \
            "link 1: locking D2 supersedes the currently LOCKED D1"

    def test_relock_repins_show_and_downgrades_from_authorized(self, api):
        """PRD: "The parent show's `pinned_design_id` is set to the newly locked
        design, and the show's lifecycle moves to `DESIGN_LOCKED` from whichever
        of `PLANNING`, `AUTHORIZED`, or `READY` it occupied: re-pinning a new
        design invalidates the authorization readiness built on the old one."

        Design: Difficulty/transitive_cascade/design_relock_repin_downgrade_cascade
        """
        ctx = setup_authorized_show()
        show = ctx["show"]
        assert show["lifecycle_status"] == "AUTHORIZED", "setup held"
        assert show["pinned_design_id"] == ctx["design"]["id"]

        d2 = create_design(show["id"], max_altitude_ft=320)
        record_simulation(d2["id"])
        lock_design(show["id"], d2["id"])

        after = get_show(show["id"])
        assert after["pinned_design_id"] == d2["id"], "link 2: show re-pinned to D2"
        assert after["lifecycle_status"] == "DESIGN_LOCKED", \
            "re-pin downgraded AUTHORIZED back to DESIGN_LOCKED"
        assert after["readiness_posture"] == "NOT_READY", \
            "grid gate g5 fails (no assignments), so posture is NOT_READY"


class TestDesignListing:
    def test_designs_filtered_by_show_reverse_lookup(self, api):
        """PRD section 4: "List designs (filterable by `show_event_id`,
        `status`; paginated)".

        Design: Corner/entities/designs_filtered_by_show_reverse_lookup
        """
        site = create_site()
        set_clock()
        show_a = create_show(site["id"], name="Show A")
        show_b = create_show(site["id"], name="Show B",
                             window_start="2026-08-12T19:00:00Z",
                             window_end="2026-08-12T19:30:00Z",
                             drone_count_planned=5)
        create_design(show_a["id"])
        create_design(show_a["id"], max_altitude_ft=320)
        create_design(show_b["id"], drone_count=5, max_altitude_ft=250,
                      duration_sec=300)

        data, meta = validate_paginated(
            api.list_show_designs(PLANNER, params={"show_event_id": show_a["id"]}))
        assert meta["total_count"] == 2, "exactly show A's two designs"
        assert all(row["show_event_id"] == show_a["id"] for row in data)


class TestDesignLockOcc:
    def test_design_lock_stale_show_version_rejected(self, api):
        """PRD: "locking a show design re-pins the show while superseding the
        previously locked design; in both cases the request body must carry
        `expected_show_event_version` holding the show's `version` as the caller
        last read it. If the show's current `version` does not match the
        supplied value — because the caller's view of the show is stale relative
        to writes it has not observed — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and no supersession or re-pin occurs."

        Design: Corner/cross_cutting_layers/occ_stale_version_design_lock
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        stale_version = show["version"]
        design = create_design(show["id"])
        record_simulation(design["id"])
        # A payment mutation advances the show's version after our read.
        get_success_data(api.record_payment(
            show["id"], {"kind": "DEPOSIT",
                         "amount_cents": show["deposit_cents"]}, PLANNER))

        resp = api.lock_design(
            design["id"], {"expected_show_event_version": stale_version}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_show(show["id"])["version"]
        locked = validate_success(api.lock_design(
            design["id"], {"expected_show_event_version": fresh_version}, PLANNER))
        assert locked["status"] == "LOCKED", "the fresh version locks cleanly"
