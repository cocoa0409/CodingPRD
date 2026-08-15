"""Difficulty queue A — non_linear_state_machine and transitive_cascade instances."""
from test_helpers import (
    assert_instant_equal,
    CLOCK_T0800,
    api_client,
    create_clean_request_payload,
    create_outbreak_event_payload,
    create_placement_demand_payload,
    get_success_data,
    set_clock,
    setup_basic_scenario,
    setup_needs_reclean,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    complete_request,
    create_all_standards,
    create_bed,
    create_request,
    create_standard,
    create_technician,
    create_unit,
    seed_supplies,
    setup_outbreak_active,
    start_request,
    submit_audit,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
IP = TEST_USERS["ip_headers"]
ANY = TEST_USERS["any_headers"]


class TestCleanRequestRecleanCycle:
    def test_reclean_loop_returns_through_assigned_and_verifies(self, api):
        """PRD §3.6: "A **FAIL** cascade opens a reclean loop instead. The
        request moves `PENDING_QA → NEEDS_RECLEAN` and its `reclean_count`
        rises by one; ... The same request — not a new one — is then reassigned
        through the dispatcher path of §3.4 under the second-set-of-hands rule,
        and its next start moves the bed to `CLEAN_IN_PROGRESS` again, at the
        halved consumption of §3.5."
        PRD §3.5: "stamps `first_started_at` as well when it has never been set
        — recleans never overwrite the first start."

        Design: Difficulty/non_linear_state_machine/clean_request_reclean_cycle
        """
        ctx = setup_basic_scenario()
        t2 = create_technician("T2")
        from test_helpers import make_technician_headers

        get_success_data(
            api.clock_in_staff(t2["id"], make_technician_headers(t2["id"]))
        )

        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])
        first_start = get_success_data(api.get_clean_request(req["id"], ANY))[
            "first_started_at"
        ]
        assert_instant_equal(first_start, CLOCK_T0800)

        set_clock("2026-08-01T08:45:00Z")
        complete_request(req["id"], ctx["tech"]["id"])
        submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=300)

        reclean = get_success_data(api.get_clean_request(req["id"], ANY))
        assert reclean["status"] == "NEEDS_RECLEAN"
        assert reclean["reclean_count"] == 1

        # Reclean leg: different technician, fluorescent PASS.
        assign_request(req["id"], t2["id"])
        start_request(req["id"], t2["id"])
        set_clock("2026-08-01T09:10:00Z")
        complete_request(req["id"], t2["id"])
        submit_audit(
            req["id"],
            ctx["auditor"]["id"],
            audit_method="FLUORESCENT_MARKER",
            marker_fraction_removed=0.90,
        )

        final = get_success_data(api.get_clean_request(req["id"], ANY))
        assert final["status"] == "VERIFIED"
        assert final["reclean_count"] == 1
        assert_instant_equal(final["first_started_at"], CLOCK_T0800)

        bed = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
        assert bed["bed_status"] == "READY"

    def test_fail_and_reclean_attribute_counters_to_right_technicians(self, api):
        """PRD §3.6: "the completing technician's `qa_fail_count` rises by one
        with productivity and `stat_eligible` recomputed."
        PRD §3.6: "The completing technician is credited:
        `completed_clean_count` rises by one."

        Design: Difficulty/non_linear_state_machine/clean_request_reclean_cycle
        """
        ctx = setup_basic_scenario()
        t2 = create_technician("T2")
        from test_helpers import make_technician_headers

        get_success_data(
            api.clock_in_staff(t2["id"], make_technician_headers(t2["id"]))
        )

        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])
        set_clock("2026-08-01T08:45:00Z")
        complete_request(req["id"], ctx["tech"]["id"])
        submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=300)

        assign_request(req["id"], t2["id"])
        start_request(req["id"], t2["id"])
        set_clock("2026-08-01T09:10:00Z")
        complete_request(req["id"], t2["id"])
        submit_audit(
            req["id"],
            ctx["auditor"]["id"],
            audit_method="FLUORESCENT_MARKER",
            marker_fraction_removed=0.90,
        )

        t1_after = get_success_data(api.get_staff(ctx["tech"]["id"], ANY))
        assert t1_after["qa_fail_count"] == 1
        t2_after = get_success_data(api.get_staff(t2["id"], ANY))
        assert t2_after["completed_clean_count"] == 1


class TestBedOccupancyFullCycle:
    def test_ready_to_occupied_to_vacant_dirty_spawns_new_request(self, api):
        """PRD §3.3: "When a `BedPlacementCoordinator` discharges a bed, the
        bed must currently be `OCCUPIED` — otherwise the call is rejected with
        `ERR_BED_NOT_OCCUPIED`. The discharge stamps `last_discharge_at` with
        the current clock, moves the bed `OCCUPIED → VACANT_DIRTY`, and
        auto-creates a clean request for it. The request's `clean_type` comes
        from the discharge payload's `clean_type` when one is given; otherwise
        it defaults to `ISOLATION` for an `ISOLATION` bed and to `ROUTINE`
        otherwise."

        Design: Difficulty/non_linear_state_machine/bed_occupancy_full_cycle
        """
        ctx = setup_basic_scenario()
        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])
        set_clock("2026-08-01T08:40:00Z")
        complete_request(req["id"], ctx["tech"]["id"])
        submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=100)

        admitted = get_success_data(api.admit_bed(ctx["bed"]["id"], COORDINATOR))
        assert admitted["bed_status"] == "OCCUPIED"

        discharged = get_success_data(api.discharge_bed(ctx["bed"]["id"], {}, COORDINATOR))
        assert discharged["bed_status"] == "VACANT_DIRTY"
        assert_instant_equal(discharged["last_discharge_at"], "2026-08-01T08:40:00Z")

        reqs, _ = validate_paginated(
            api.list_clean_requests(
                ANY, params={"bed_id": ctx["bed"]["id"], "status": "QUEUED"}
            )
        )
        assert len(reqs) == 1
        r2 = reqs[0]
        assert r2["id"] != req["id"]
        assert r2["clean_type"] == "ROUTINE"
        assert r2["status"] == "QUEUED"

        r1_after = get_success_data(api.get_clean_request(req["id"], ANY))
        assert r1_after["status"] == "VERIFIED"

    def test_cycle_returns_bed_to_initial_state(self, api):
        """PRD §3.1: "A new bed starts its life in `VACANT_DIRTY` status."
        PRD §3.7: "Admitting requires the bed to be `READY` (`ERR_BED_NOT_READY`
        otherwise) and moves it `READY → OCCUPIED`."
        PRD §3.3: "The discharge stamps `last_discharge_at` with the current
        clock, moves the bed `OCCUPIED → VACANT_DIRTY`, and auto-creates a
        clean request for it."

        Design: Difficulty/non_linear_state_machine/bed_occupancy_full_cycle
        """
        ctx = setup_basic_scenario()
        bed0 = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
        assert bed0["bed_status"] == "VACANT_DIRTY"

        req = create_request(ctx["bed"]["id"], "ROUTINE")
        assign_request(req["id"], ctx["tech"]["id"])
        start_request(req["id"], ctx["tech"]["id"])
        set_clock("2026-08-01T08:40:00Z")
        complete_request(req["id"], ctx["tech"]["id"])
        submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=100)
        ready = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
        assert ready["bed_status"] == "READY"

        get_success_data(api.admit_bed(ctx["bed"]["id"], COORDINATOR))
        after = get_success_data(
            api.discharge_bed(ctx["bed"]["id"], {}, COORDINATOR)
        )
        assert after["bed_status"] == "VACANT_DIRTY"
        assert_instant_equal(after["last_discharge_at"], "2026-08-01T08:40:00Z")


class TestMarkSoiledRetractionDepth3:
    def test_mark_soiled_cascades_bed_notification_demand(self, api):
        """PRD §3.7: "Marking soiled likewise requires `READY`
        (`ERR_BED_NOT_READY`) and moves the bed `READY → VACANT_DIRTY`, then
        fires the depth-three retraction cascade: any notification for the bed
        in `SENT` or `ACKNOWLEDGED` status becomes `RETRACTED`; the demand it
        served, if `MATCHED`, returns to `OPEN` with `matched_bed_id` cleared
        and its `priority_score` recomputed; and a fresh `ROUTINE` clean
        request is auto-created for the bed, pinning its standard at creation
        per §3.3."

        Design: Difficulty/transitive_cascade/mark_soiled_retraction_depth3
        """
        ctx = _setup_ready_with_match(api)
        r_mark = get_success_data(api.mark_soiled_bed(ctx["bed"]["id"], COORDINATOR))
        assert r_mark["bed_status"] == "VACANT_DIRTY"

        notif = get_success_data(
            api.get_bed_ready_notification(ctx["notification"]["id"], ANY)
        )
        assert notif["status"] == "RETRACTED"

        demand = get_success_data(api.get_placement_demand(ctx["demand"]["id"], ANY))
        assert demand["status"] == "OPEN"
        assert demand["matched_bed_id"] is None

        queued, _ = validate_paginated(
            api.list_clean_requests(
                ANY, params={"bed_id": ctx["bed"]["id"], "status": "QUEUED"}
            )
        )
        assert len(queued) == 1
        assert queued[0]["clean_type"] == "ROUTINE"

    def test_mark_soiled_leaves_prior_verified_request_untouched(self, api):
        """PRD §2.6: "In-flight work is generally protected from retroactive
        change — pinned time standards and recorded ledgers do not move under
        later edits."
        PRD §3.7: "Marking soiled likewise requires `READY`
        (`ERR_BED_NOT_READY`) and moves the bed `READY → VACANT_DIRTY`."

        Design: Difficulty/transitive_cascade/mark_soiled_retraction_depth3
        """
        ctx = _setup_ready_with_match(api)
        get_success_data(api.mark_soiled_bed(ctx["bed"]["id"], COORDINATOR))
        r1_after = get_success_data(api.get_clean_request(ctx["request"]["id"], ANY))
        assert r1_after["status"] == "VERIFIED"


class TestOutbreakActivationUpgradeDepth2:
    def test_activation_upgrades_queued_isolation_requests_to_terminal(self, api):
        """PRD §3.8: "Activation stamps `activated_at`, flips the unit's
        `outbreak_posture` to `OUTBREAK` — a mutation that increments the
        unit's `version` — and then upgrades in-flight work: every clean
        request in the unit that is still `QUEUED` or `ASSIGNED`, sits on an
        `ISOLATION` bed, and is not already `TERMINAL` has its `clean_type`
        rewritten to `TERMINAL` and its standard re-pinned with the outbreak
        posture applied — `pinned_base_minutes` and
        `pinned_outbreak_multiplier_bps` are recaptured from the `TERMINAL`
        standard row and `pinned_with_outbreak` becomes true — with
        `sla_target_minutes` and `sla_due_at` recomputed from the new pin (the
        due time is again `created_at` plus the new target)."

        Design: Difficulty/transitive_cascade/outbreak_activation_upgrade_depth2
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_all_standards()
        seed_supplies()
        bi1 = create_bed(unit["id"], "BI1", "ISOLATION")
        req = create_request(bi1["id"], "ISOLATION")
        assert req["sla_target_minutes"] == 60

        ob = get_success_data(
            api.create_outbreak_event(
                create_outbreak_event_payload(
                    unit_id=unit["id"], pathogen_class="C_DIFF"
                ),
                IP,
            )
        )
        activated = get_success_data(api.activate_outbreak_event(ob["id"], IP))
        assert activated["status"] == "ACTIVE"

        unit_after = get_success_data(api.get_unit(unit["id"], ANY))
        assert unit_after["outbreak_posture"] == "OUTBREAK"

        req_after = get_success_data(api.get_clean_request(req["id"], ANY))
        assert req_after["clean_type"] == "TERMINAL"
        assert req_after["pinned_base_minutes"] == 90
        assert req_after["pinned_outbreak_multiplier_bps"] == 20000
        assert req_after["pinned_with_outbreak"] is True
        assert req_after["sla_target_minutes"] == 180
        assert_instant_equal(req_after["sla_due_at"], "2026-08-01T11:00:00Z")

    def test_activation_does_not_touch_non_isolation_beds(self, api):
        """PRD §3.8: "Requests already underway — started, pending QA, or
        awaiting reclean — are deliberately not touched; neither are requests
        on non-isolation beds."

        Design: Difficulty/transitive_cascade/outbreak_activation_upgrade_depth2
        """
        set_clock(CLOCK_T0800)
        unit = create_unit()
        create_all_standards()
        seed_supplies()
        std_bed = create_bed(unit["id"], "B1", "STANDARD")
        req = create_request(std_bed["id"], "ROUTINE")
        assert req["sla_target_minutes"] == 45

        setup_outbreak_active(unit["id"], pathogen_class="C_DIFF")

        req_after = get_success_data(api.get_clean_request(req["id"], ANY))
        assert req_after["clean_type"] == "ROUTINE"
        assert req_after["sla_target_minutes"] == 45
        assert req_after["pinned_with_outbreak"] is False


class TestAuditVoidCompensationDepth3:
    def test_void_restores_request_bed_and_reverses_penalty(self, api):
        """PRD §3.6: "A void runs the compensation cascade: the request moves
        `NEEDS_RECLEAN → PENDING_QA`, the bed moves `VACANT_DIRTY →
        `AWAITING_VERIFICATION`, and the completing technician's
        `qa_fail_count` drops by one with productivity recomputed. The audit
        itself becomes `VOIDED`, terminal."

        Design: Difficulty/transitive_cascade/audit_void_compensation_depth3
        """
        ctx = setup_needs_reclean()
        audit_id = ctx["audit"]["id"]

        voided = get_success_data(api.void_quality_audit(audit_id, IP))
        assert voided["audit_status"] == "VOIDED"

        req = get_success_data(api.get_clean_request(ctx["request"]["id"], ANY))
        assert req["status"] == "PENDING_QA"
        bed = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
        assert bed["bed_status"] == "AWAITING_VERIFICATION"
        tech = get_success_data(api.get_staff(ctx["tech"]["id"], ANY))
        assert tech["qa_fail_count"] == 0

    def test_void_retains_reclean_history(self, api):
        """PRD §3.6: "A **FAIL** cascade opens a reclean loop instead. The
        request moves `PENDING_QA → NEEDS_RECLEAN` and its `reclean_count`
        rises by one."
        PRD §3.6: "A void runs the compensation cascade: the request moves
        `NEEDS_RECLEAN → PENDING_QA`, the bed moves `VACANT_DIRTY →
        `AWAITING_VERIFICATION`, and the completing technician's
        `qa_fail_count` drops by one with productivity recomputed."

        Design: Difficulty/transitive_cascade/audit_void_compensation_depth3
        """
        ctx = setup_needs_reclean()
        assert ctx["request"]["reclean_count"] == 1
        get_success_data(api.void_quality_audit(ctx["audit"]["id"], IP))
        req = get_success_data(api.get_clean_request(ctx["request"]["id"], ANY))
        # The fail's effects are compensated; the recorded reclean_count history
        # is retained by the request.
        assert req["reclean_count"] == 1
        assert req["status"] == "PENDING_QA"


def _setup_ready_with_match(api):
    """Drive a bed to READY with an OPEN demand so the match selector fires."""
    ctx = setup_basic_scenario()
    demand = get_success_data(
        api.create_placement_demand(
            create_placement_demand_payload(unit_id=ctx["unit"]["id"]),
            COORDINATOR,
        )
    )
    req = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(req["id"], ctx["tech"]["id"])
    start_request(req["id"], ctx["tech"]["id"])
    set_clock("2026-08-01T08:45:00Z")
    complete_request(req["id"], ctx["tech"]["id"])
    submit_audit(req["id"], ctx["auditor"]["id"], rlu_reading=100)
    notifs, _ = validate_paginated(
        api.list_bed_ready_notifications(ANY, params={"bed_id": ctx["bed"]["id"]})
    )
    assert len(notifs) == 1
    ctx["request"] = get_success_data(api.get_clean_request(req["id"], ANY))
    ctx["demand"] = get_success_data(api.get_placement_demand(demand["id"], ANY))
    ctx["notification"] = notifs[0]
    return ctx
