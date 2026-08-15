"""Containment design/verification (negative-air sizing, pressure boundary,
OCC revision), air-test phase gating, the clearance threshold, the
re-occupancy gate, and the clearance-failure reclean cycle."""
from test_helpers import (
    ADMIN,
    IH,
    ApiErrorId,
    add_supervisor,
    api_client,
    assert_air_test,
    assert_containment,
    complete_work,
    create_air_test_entity,
    create_containment_entity,
    create_containment_payload,
    create_relocation_entity,
    create_unit_entity,
    get_project,
    install_containment,
    list_project_air_tests,
    list_project_containments,
    list_project_relocations,
    make_industrial_hygienist_headers,
    make_supervisor_headers,
    record_clearance_result,
    revise_containment,
    set_clock,
    setup_acknowledged_notification,
    setup_assessed_project,
    setup_awaiting_clearance_project,
    setup_in_progress_project,
    setup_supervisor_coverage,
    setup_verified_containment,
    start_project,
    supervisor_headers,
    validate_error,
    validate_paginated,
    verify_containment,
)


class TestContainmentDesign:
    def test_second_containment_rejected(self):
        """PRD section 3.4: "A `Supervisor` designs the project's single
        **containment** by supplying the `project_id` (the project must be
        `ASSESSED`, otherwise `ERR_INVALID_STATE`; a second containment for
        the same project is rejected with `ERR_CONTAINMENT_ALREADY_EXISTS`)"

        Design: Corner/validations/create_second_containment_rejected
        """
        ctx = setup_assessed_project(name="P-V2", base_abatement_cost_cents=1_000)
        supervisor = add_supervisor()
        create_containment_entity(ctx["project"]["id"], supervisor["id"])
        resp = api_client.create_containment(
            create_containment_payload(
                ctx["project"]["id"], work_area_volume_cuft=1000,
                containment_class="GLOVE_BAG"),
            make_supervisor_headers(supervisor["id"]))
        validate_error(resp, ApiErrorId.ERR_CONTAINMENT_ALREADY_EXISTS)

    def test_verify_designed_containment_rejected(self):
        """PRD section 3.4: "Verification — whether from `INSTALLED` or, after
        a clearance failure, from `RECLEAN_REQUIRED` — moves it to
        `VERIFIED`."
        PRD section 2.10: "any attempt to act on a resource from a state that
        does not permit the transition — terminal or otherwise — is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/verify_designed_containment_rejected
        """
        ctx = setup_assessed_project(name="P-SM6", base_abatement_cost_cents=1_000)
        supervisor = add_supervisor()
        containment = create_containment_entity(ctx["project"]["id"],
                                                supervisor["id"])
        resp = api_client.verify_containment(
            containment["id"], {"pressure_reading_inwg": -0.03},
            make_supervisor_headers(supervisor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        listing = list_project_containments(ctx["project"]["id"])
        assert listing[0]["status"] == "DESIGNED", \
            "containment must remain DESIGNED after a rejected verify"

    def test_pressure_boundary_minus_0020(self):
        """PRD section 3.4: "The verifying `Supervisor` supplies a
        `pressure_reading_inwg`, which must be at or below -0.020 inches of
        water gauge; equality passes, and anything higher (insufficient
        negative pressure) fails with `ERR_PRESSURE_INSUFFICIENT` (422)."
        PRD section 3.4: "A successful verification records the reading in
        `last_pressure_reading_inwg`, stamps `verified_by_user_id` with the
        verifier's `X-User-ID`, and sets `last_verified_at` to the current
        logical time."

        Design: Corner/calculations/containment_pressure_boundary_minus_0020
        """
        ctx = setup_assessed_project(name="P-C2", base_abatement_cost_cents=1_000)
        supervisor = add_supervisor()
        containment = create_containment_entity(ctx["project"]["id"],
                                                supervisor["id"])
        install_containment(containment["id"], supervisor["id"])

        resp = api_client.verify_containment(
            containment["id"], {"pressure_reading_inwg": -0.019},
            make_supervisor_headers(supervisor["id"]))
        validate_error(resp, ApiErrorId.ERR_PRESSURE_INSUFFICIENT)
        listing = list_project_containments(ctx["project"]["id"])
        assert listing[0]["status"] == "INSTALLED", \
            "-0.019 is insufficient: containment must stay INSTALLED"

        verified = verify_containment(containment["id"], supervisor["id"],
                                      pressure=-0.020)
        assert_containment(verified)
        assert verified["status"] == "VERIFIED", \
            "exactly -0.020 must pass (equality allowed)"
        assert verified["last_pressure_reading_inwg"] == -0.020
        assert verified["verified_by_user_id"] == supervisor["id"], \
            "the verifier's X-User-ID must be recorded"
        assert verified["last_verified_at"].startswith("2026-08-01T00:00:00"), \
            "last_verified_at must be stamped from the logical clock"

    def test_revise_containment_stale_version_rejected(self):
        """PRD section 3.4: "Because a revision recomputes the machine count
        from design inputs, the request must carry
        `expected_containment_version` matching the containment's current
        `version`; a stale revision is rejected with `ERR_STALE_VERSION`
        (412) instead of silently overwriting another designer's work."

        Design: Corner/cross_cutting_layers/revise_containment_stale_version_rejected
        """
        ctx = setup_assessed_project(name="P-L2", base_abatement_cost_cents=1_000)
        supervisor = add_supervisor()
        containment = create_containment_entity(ctx["project"]["id"],
                                                supervisor["id"])
        assert containment["machines_required"] == 8
        stale_version = containment["version"] - 1
        resp = api_client.revise_containment(
            containment["id"],
            {"work_area_volume_cuft": 120000,
             "expected_containment_version": stale_version},
            make_supervisor_headers(supervisor["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        listing = list_project_containments(ctx["project"]["id"])
        assert listing[0]["machines_required"] == 8, \
            "a stale revision must leave machines_required untouched"
        assert listing[0]["version"] == containment["version"], \
            "a stale revision must not advance the containment version"


class TestNegativeAirSizing:
    def test_full_containment_machine_count_ceil(self):
        """PRD section 3.4: "Otherwise the machine count is the work-area
        volume multiplied by the air-changes-per-hour figure, divided by the
        hourly throughput of one machine — each machine moves 2,000 cubic feet
        per minute, hence 120,000 cubic feet per hour — with the quotient
        rounded up to a whole number, and the result then raised to at least 1
        machine: the ceiling is applied first, then the floor of one machine."
        PRD section 3.4: "The required `air_changes_per_hour` is 4 for a
        `FULL` containment, 6 for a `MINI_ENCLOSURE`, and 0 for a
        `GLOVE_BAG`."

        Design: Difficulty/combinatorial_formula/negative_air_machines_class_volume_branching
        """
        ctx = setup_assessed_project(name="P-CF1")
        supervisor = add_supervisor()
        containment = create_containment_entity(
            ctx["project"]["id"], supervisor["id"],
            work_area_volume_cuft=240_000, containment_class="FULL")
        assert containment["air_changes_per_hour"] == 4
        assert containment["machines_required"] == 8, (
            f"ceil(240000*4/120000) == 8, got "
            f"{containment['machines_required']}"
        )
        revised = revise_containment(
            containment["id"], supervisor["id"],
            containment["version"], work_area_volume_cuft=120_000)
        assert revised["machines_required"] == 4, (
            f"ceil(120000*4/120000) == 4, got {revised['machines_required']}"
        )
        assert revised["version"] == containment["version"] + 1

        # MINI_ENCLOSURE branch: ACH 6 on the same volume.
        ctx2 = setup_assessed_project(name="P-CF1B")
        mini = create_containment_entity(
            ctx2["project"]["id"], add_supervisor()["id"],
            work_area_volume_cuft=240_000, containment_class="MINI_ENCLOSURE")
        assert mini["air_changes_per_hour"] == 6
        assert mini["machines_required"] == 12, (
            f"ceil(240000*6/120000) == 12, got {mini['machines_required']}"
        )

    def test_glove_bag_short_circuits_to_zero_machines(self):
        """PRD section 3.4: "A glove-bag operation needs no negative-air
        machines at all, so `machines_required` is 0."
        PRD section 3.4: "While the containment remains `DESIGNED`, the
        supervisor may revise it, supplying a new `work_area_volume_cuft`, a
        new `containment_class`, or both."

        Design: Difficulty/combinatorial_formula/negative_air_machines_class_volume_branching
        """
        ctx = setup_assessed_project(name="P-CF1C")
        supervisor = add_supervisor()
        containment = create_containment_entity(
            ctx["project"]["id"], supervisor["id"],
            work_area_volume_cuft=240_000, containment_class="FULL")
        revised = revise_containment(
            containment["id"], supervisor["id"], containment["version"],
            work_area_volume_cuft=120_000)
        assert revised["machines_required"] == 4
        revised2 = revise_containment(
            containment["id"], supervisor["id"], revised["version"],
            containment_class="GLOVE_BAG")
        assert revised2["machines_required"] == 0, \
            "GLOVE_BAG must short-circuit to zero machines"
        assert revised2["air_changes_per_hour"] == 0
        assert revised2["status"] == "DESIGNED", \
            "a successful revision stays in DESIGNED"


class TestAirTestPhaseGating:
    def test_air_tests_list_phase_filter(self):
        """PRD section 3.6: "The project's air-test listing supports an
        optional `phase` filter alongside pagination."
        PRD section 3.6: "Each phase is gated on the project's status: a
        `BASELINE` test requires the project to be `ASSESSED`; a `DAILY` test
        requires `IN_PROGRESS`, `SUSPENDED`, or `RECLEANING`; a `CLEARANCE`
        test requires `AWAITING_CLEARANCE`."

        Design: Corner/endpoints/air_tests_list_phase_filter
        """
        # BASELINE must be collected while the project is ASSESSED.
        ctx = setup_assessed_project(name="P-E2")
        supervisor = add_supervisor()
        baseline = create_air_test_entity(
            ctx["project"]["id"], "BASELINE", "2026-08-01T06:00:00Z",
            supervisor_headers(supervisor))
        assert baseline["status"] == "COLLECTED"
        ctx["supervisor"] = supervisor
        ctx["containment"] = setup_verified_containment(
            ctx["project"]["id"], supervisor["id"])
        ctx["notification"] = setup_acknowledged_notification(
            ctx["project"]["id"])
        ctx["assignment"] = setup_supervisor_coverage(
            ctx["project"]["id"], supervisor["id"])
        start_project(ctx)
        daily = create_air_test_entity(
            ctx["project"]["id"], "DAILY", "2026-08-11T12:00:00Z",
            supervisor_headers(supervisor))
        assert daily["status"] == "COLLECTED"

        resp = api_client.list_project_air_tests(
            ctx["project"]["id"], ADMIN, params={"phase": "DAILY"})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, "phase=DAILY must return exactly the DAILY row"
        assert data[0]["phase"] == "DAILY"
        assert data[0]["id"] == daily["id"]
        assert meta["total_count"] == 1

    def test_supervisor_cannot_create_clearance_air_test(self):
        """PRD section 3.6: "`Supervisor` and `IndustrialHygienist` may
        collect `BASELINE` and `DAILY` tests, but only an
        `IndustrialHygienist` may collect a `CLEARANCE` test — a `Supervisor`
        attempting one is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."

        Design: Corner/rbac/supervisor_cannot_create_clearance_air_test
        """
        ctx = setup_awaiting_clearance_project(name="P-R5")
        resp = api_client.create_air_test(
            {"project_id": ctx["project"]["id"], "phase": "CLEARANCE",
             "collected_at": "2026-08-12T08:00:00Z"},
            supervisor_headers(ctx["supervisor"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_clearance_result_by_containment_verifier_rejected(self):
        """PRD section 3.6: "Segregation of duties guards the clearance
        verdict: the hygienist recording a `CLEARANCE` result must not be the
        same `X-User-ID` recorded as the containment's
        `verified_by_user_id`; a match is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (409)."

        Design: Corner/validations/clearance_result_by_containment_verifier_rejected
        """
        ctx = setup_awaiting_clearance_project(name="P-V9")
        test = create_air_test_entity(
            ctx["project"]["id"], "CLEARANCE", "2026-08-12T08:00:00Z", IH)
        # The hygienist presents the SAME X-User-ID that verified the
        # containment (the supervisor's worker id).
        resp = api_client.record_air_test_result(
            test["id"], {"result_f_cc": 0.008},
            make_industrial_hygienist_headers(ctx["supervisor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        listing = list_project_air_tests(ctx["project"]["id"])
        mine = [t for t in listing if t["id"] == test["id"]]
        assert mine and mine[0]["status"] == "COLLECTED", \
            "a rejected result must not persist; the test stays COLLECTED"


class TestClearanceThreshold:
    def test_0009_passes(self):
        """PRD section 3.6: "For a `CLEARANCE` test, the `outcome` is `PASS`
        when `result_f_cc` is strictly below 0.010 fibers per cubic centimeter
        and `FAIL` otherwise — a result of exactly 0.010 is a `FAIL` — with
        the comparison made at three decimal places."

        Design: Difficulty/boundary_precision_check/clearance_threshold_exactly_010_fails
        """
        ctx = setup_awaiting_clearance_project(name="P-BND1A")
        reported = record_clearance_result(ctx, "2026-08-12T08:00:00Z", 0.009)
        assert_air_test(reported)
        assert reported["outcome"] == "PASS", "0.009 < 0.010 must PASS"
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "AWAITING_CLEARANCE", \
            "a PASS must not fire the reclean cascade"

    def test_0010_fails_and_triggers_reclean(self):
        """PRD section 3.6: "For a `CLEARANCE` test, the `outcome` is `PASS`
        when `result_f_cc` is strictly below 0.010 fibers per cubic centimeter
        and `FAIL` otherwise — a result of exactly 0.010 is a `FAIL` — with
        the comparison made at three decimal places."
        PRD section 3.6: "A failed clearance cascades through three links."

        Design: Difficulty/boundary_precision_check/clearance_threshold_exactly_010_fails
        """
        ctx = setup_awaiting_clearance_project(name="P-BND1B")
        reported = record_clearance_result(ctx, "2026-08-12T09:00:00Z", 0.010)
        assert reported["outcome"] == "FAIL", \
            "exactly 0.010 is NOT strictly below 0.010 and must FAIL"
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "RECLEANING", \
            "the FAIL cascade must move the project to RECLEANING"


class TestReoccupancyGate:
    def test_single_pass_clearance_still_blocked(self):
        """PRD section 3.6: "The `reoccupancy_status` is `OPEN` exactly when
        there are zero fails and at least 2 passes in that window; otherwise
        it is `BLOCKED`."

        Design: Corner/calculations/single_pass_clearance_still_blocked
        """
        ctx = setup_awaiting_clearance_project(name="P-C4")
        reported = record_clearance_result(ctx, "2026-08-12T08:00:00Z", 0.008)
        assert reported["outcome"] == "PASS"
        project = get_project(ctx["project"]["id"])
        assert project["reoccupancy_status"] == "BLOCKED", \
            "1 PASS is below the required 2 passes: gate stays BLOCKED"


class TestRecleanCycle:
    def test_clearance_fail_cycles_containment_and_project(self):
        """PRD section 3.6: "Link 1 moves the project's containment from
        `VERIFIED` to `RECLEAN_REQUIRED`. Link 2 moves the project from
        `AWAITING_CLEARANCE` to `RECLEANING`, recomputes its
        `reoccupancy_status` to `BLOCKED`, and increments the project's
        `version` by 1."
        PRD section 3.4: "When the verification comes from
        `RECLEAN_REQUIRED`, it additionally returns the project from
        `RECLEANING` to `AWAITING_CLEARANCE`."

        Design: Difficulty/non_linear_state_machine/containment_reclean_verify_cycle
        """
        ctx = setup_awaiting_clearance_project(name="P-NSM1")
        reported = record_clearance_result(ctx, "2026-08-12T08:00:00Z", 0.012)
        assert reported["outcome"] == "FAIL"
        containment = list_project_containments(ctx["project"]["id"])[0]
        assert containment["status"] == "RECLEAN_REQUIRED", \
            "link 1: containment must enter RECLEAN_REQUIRED"
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "RECLEANING", \
            "link 2: project must enter RECLEANING"
        assert project["reoccupancy_status"] == "BLOCKED"

        re_verified = verify_containment(
            ctx["containment"]["id"], ctx["supervisor"]["id"], pressure=-0.025)
        assert re_verified["status"] == "VERIFIED", \
            "re-verify from RECLEAN_REQUIRED closes the cycle"
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "AWAITING_CLEARANCE", \
            "re-verification must return the project to AWAITING_CLEARANCE"

    def test_only_tests_collected_after_reverification_count(self):
        """PRD section 3.6: "Let the verification instant be the containment's
        `last_verified_at`, treating it as unset if the containment was never
        verified. Count the project's `CLEARANCE`-phase tests in `REPORTED`
        status whose `collected_at` is strictly after that verification
        instant — a test collected at the exact same instant as the
        verification does not count, and if the containment was never verified
        every reported clearance test counts — splitting them into passes
        (`outcome` `PASS`) and fails (`outcome` `FAIL`)."
        PRD section 3.6: "The `reoccupancy_status` is `OPEN` exactly when
        there are zero fails and at least 2 passes in that window; otherwise
        it is `BLOCKED`."

        Design: Difficulty/non_linear_state_machine/containment_reclean_verify_cycle
        """
        ctx = setup_awaiting_clearance_project(name="P-NSM1B")
        reported = record_clearance_result(ctx, "2026-08-12T08:00:00Z", 0.012)
        assert reported["outcome"] == "FAIL"
        # Re-verify at a logical instant AFTER the failed test's collection,
        # so the FAIL predates the new window boundary.
        set_clock("2026-08-12T12:00:00Z")
        verify_containment(ctx["containment"]["id"], ctx["supervisor"]["id"],
                           pressure=-0.025)
        record_clearance_result(ctx, "2026-08-13T08:00:00Z", 0.008)
        record_clearance_result(ctx, "2026-08-13T09:00:00Z", 0.009)
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "AWAITING_CLEARANCE"
        assert project["reoccupancy_status"] == "OPEN", (
            "two passes collected after the new last_verified_at must open "
            "the gate; the pre-verification FAIL is excluded"
        )


class TestClearanceFailCascade:
    def test_fail_cascades_containment_project_and_reoccupancy(self):
        """PRD section 3.6: "A failed clearance cascades through three links.
        Link 1 moves the project's containment from `VERIFIED` to
        `RECLEAN_REQUIRED`. Link 2 moves the project from
        `AWAITING_CLEARANCE` to `RECLEANING`, recomputes its
        `reoccupancy_status` to `BLOCKED`, and increments the project's
        `version` by 1."

        Design: Difficulty/transitive_cascade/clearance_fail_transitive_reclean_extension_chain
        """
        ctx = setup_awaiting_clearance_project(name="P-TC1")
        version_before = ctx["project"]["version"]
        reported = record_clearance_result(ctx, "2026-08-12T08:00:00Z", 0.012)
        assert reported["outcome"] == "FAIL"
        containment = list_project_containments(ctx["project"]["id"])[0]
        assert containment["status"] == "RECLEAN_REQUIRED"
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "RECLEANING"
        assert project["reoccupancy_status"] == "BLOCKED"
        assert project["version"] == version_before + 1, \
            "link 2 must increment the project version by 1"

    def test_fail_cascades_relocation_extension(self):
        """PRD section 3.6: "Link 3 transitions every relocation record of the
        project still in `HOUSED` status to `EXTENDED`, incrementing each
        record's `extension_count` by 1 — the occupants cannot come home
        yet."

        Design: Difficulty/transitive_cascade/clearance_fail_transitive_reclean_extension_chain
        """
        ctx = setup_in_progress_project(name="P-TC1C")
        unit = create_unit_entity(unit_label="U1", capacity_persons=4)
        relocation = create_relocation_entity(
            ctx["project"]["id"], unit["id"], household_name="Household H",
            persons=3, move_out_at="2026-08-10T00:00:00Z")
        assert relocation["status"] == "HOUSED"
        complete_work(ctx)
        reported = record_clearance_result(ctx, "2026-08-12T08:00:00Z", 0.012)
        assert reported["outcome"] == "FAIL"
        relocations = list_project_relocations(ctx["project"]["id"])
        mine = [r for r in relocations if r["id"] == relocation["id"]]
        assert mine and mine[0]["status"] == "EXTENDED", \
            "link 3: the HOUSED record must transition to EXTENDED"
        assert mine[0]["extension_count"] == 1, \
            "link 3: extension_count must increment by 1"
