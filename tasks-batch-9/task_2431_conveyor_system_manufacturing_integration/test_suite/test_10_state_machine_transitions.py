"""Declared transitions, their side effects, and the transitions that do not exist."""

from test_helpers import (
    CUSTOMER_REP,
    DESIGN_ENGINEER,
    PROJECT_DIRECTOR,
    SHOP_SUPERVISOR,
    SITE_MANAGER,
    TEST_INSTANTS,
    ApiErrorId,
    assert_acceptance_certificate,
    assert_change_order,
    assert_simulation_run,
    create_acceptance_certificate_payload,
    create_cutover_window_payload,
    decide_change_order,
    is_iso8601_timestamp,
    make_change_order,
    make_fat_passed_lot,
    make_frozen_project,
    make_linear_design,
    make_planned_lot,
    make_project,
    make_scheduled_window,
    make_site_zone,
    make_staging_bay,
    make_submitted_change_order,
    read_change_order,
    read_lot,
    read_project,
    read_window,
    record_fat_test,
    record_ramp,
    run_simulation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestChangeOrderInitialStateAndSubmission:
    """A drafted order is inert until it is submitted."""

    def test_a_drafted_order_starts_in_draft_at_round_one(self, api):
        """DRAFT, round 1, no reviewer, no comment, and a still-clean project.

        PRD §3.8: "A drafted order starts with `status` `DRAFT`, `round_no` 1, and both
        `decision_comment` and `reviewed_by_user_id` null, and drafting one increments the
        project's `version` by 1."

        Design: Corner/state_machines/change_order_starts_in_draft_at_round_one
        """
        project = make_project(api)
        created = make_change_order(
            api,
            project["id"],
            title="Add spur to dock 4",
            scope_delta_cph=0,
            price_delta_cents=1_000_000,
            schedule_delta_days=5,
        )

        assert_change_order(created)
        assert created["status"] == "DRAFT"
        assert created["round_no"] == 1
        assert created["reviewed_by_user_id"] is None
        assert created["decision_comment"] is None

        after = read_project(api, project["id"])
        assert after["commercial_status"] == "CLEAN"
        assert after["contract_value_cents"] == 243_600_000

    def test_submission_moves_the_order_and_the_commercial_dimension_only(self, api):
        """The order becomes SUBMITTED and the project becomes CHANGE_PENDING.

        PRD §3.8: "Submission advances the order to `SUBMITTED`, moves the project's
        `commercial_status` from `CLEAN` to `CHANGE_PENDING` if it was `CLEAN`, and
        increments both the order's `version` and the project's `version` by 1."

        Design: Corner/state_machines/change_order_submit_moves_draft_to_submitted_and_project_to_change_pending
        """
        project = make_project(api)
        submitted = make_submitted_change_order(
            api,
            project["id"],
            title="Add spur to dock 4",
            scope_delta_cph=0,
            price_delta_cents=1_000_000,
            schedule_delta_days=5,
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["round_no"] == 1

        after = read_project(api, project["id"])
        assert after["commercial_status"] == "CHANGE_PENDING"
        assert after["delivery_status"] == "DESIGN"
        assert after["contract_value_cents"] == 243_600_000

    def test_submitting_a_rejected_order_again_is_refused(self, api):
        """REJECTED is terminal and the rejected price never reaches the ledger.

        PRD §3.8: "Critically, `contract_value_cents` is **not** recomputed by a
        rejection — a rejected order's `price_delta_cents` never enters the subtotal, so
        the contract ledger is left exactly as it was."

        Design: Corner/state_machines/change_order_submit_after_rejection_returns_change_order_invalid_state
        """
        project = make_project(api)
        change_order = make_submitted_change_order(
            api,
            project["id"],
            title="Second sorter bank",
            scope_delta_cph=150,
            price_delta_cents=18_000_000,
            schedule_delta_days=21,
        )
        rejected = decide_change_order(
            api,
            project["id"],
            change_order["id"],
            "REJECT",
            headers=CUSTOMER_REP,
            decision_comment="Out of budget this fiscal year",
        )
        assert rejected["status"] == "REJECTED"

        response = api.submit_change_order(change_order["id"], PROJECT_DIRECTOR)
        validate_error(response, ApiErrorId.ERR_CHANGE_ORDER_INVALID_STATE.value)

        stored = read_change_order(api, change_order["id"])
        assert stored["status"] == "REJECTED"
        assert stored["reviewed_by_user_id"] == CUSTOMER_REP["X-User-ID"]

        after = read_project(api, project["id"])
        assert after["contract_value_cents"] == 243_600_000
        assert after["escalation_fee_cents"] == 3_600_000
        assert after["commercial_status"] == "CLEAN"
        assert after["delivery_status"] == "DESIGN"
        assert after["design_version"] == 1


class TestSimulationSupersessionAndTheFreezeGate:
    """Runs supersede by method, and only the degraded method gates a freeze."""

    def test_a_second_run_of_the_same_method_supersedes_the_first(self, api):
        """Supersession is keyed on method, not on any change of result.

        PRD §3.3: "A completed run also supersedes its predecessor of the same `method`:
        the prior run of that project and that `method` whose `status` was `COMPLETE`
        becomes `SUPERSEDED`, and its own `version` increments by 1."

        Design: Corner/state_machines/second_simulation_of_the_same_method_supersedes_the_prior_complete_run
        """
        design = make_linear_design(api)
        project_id = design["project"]["id"]
        first = run_simulation(api, project_id, "DETERMINISTIC_STEADY_STATE")
        second = run_simulation(api, project_id, "DETERMINISTIC_STEADY_STATE")

        assert_simulation_run(second)
        assert second["status"] == "COMPLETE"
        assert second["effective_throughput_cph"] == 1400

        runs, meta = validate_paginated(api.list_simulation_runs(project_id, DESIGN_ENGINEER))
        assert meta["total_count"] == 2
        assert runs[0]["id"] == second["id"]
        by_id = {run["id"]: run for run in runs}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[first["id"]]["effective_throughput_cph"] == 1400
        assert by_id[first["id"]]["version"] == 2

        complete, complete_meta = validate_paginated(
            api.list_simulation_runs(project_id, DESIGN_ENGINEER, params={"status": "COMPLETE"})
        )
        assert complete_meta["total_count"] == 1
        assert [run["id"] for run in complete] == [second["id"]]

    def test_a_deterministic_run_alone_cannot_gate_the_freeze(self, api):
        """1400 clears 1250, but the gate only reads the degraded method.

        PRD §3.4: "There must exist a simulation run of this project whose `method` is
        `DEGRADED_AVAILABILITY`, whose `status` is `COMPLETE`, and whose
        `design_version_at_run` equals the project's current `design_version`; if no such
        run exists — because none was ever run under that method, or because the latest
        one was superseded, or because a design edit turned it `STALE` — the freeze is
        rejected with `ERR_SIMULATION_STALE_OR_MISSING`."

        Design: Corner/state_machines/design_freeze_with_only_a_deterministic_run_returns_simulation_stale_or_missing
        """
        design = make_linear_design(api)
        project_id = design["project"]["id"]
        deterministic = run_simulation(api, project_id, "DETERMINISTIC_STEADY_STATE")

        response = api.design_freeze(project_id, PROJECT_DIRECTOR)
        validate_error(response, ApiErrorId.ERR_SIMULATION_STALE_OR_MISSING.value)

        assert deterministic["effective_throughput_cph"] == 1400
        assert deterministic["shortfall_cph"] == 0
        after = read_project(api, project_id)
        assert after["delivery_status"] == "DESIGN"
        assert after["design_frozen_at"] is None


class TestZonedCutoverProgression:
    """The share ledger and the delivery dimension follow the zones."""

    def _two_zone_project(self, api, bay_code="BAY-3", lot_code="LOT-300"):
        state = make_fat_passed_lot(
            api,
            bay=make_staging_bay(api, bay_code=bay_code, concurrent_capacity=2),
            segment_codes=["IB-01", "TR-02"],
            lot_code=lot_code,
            measured_cph=1313,
            defect_count=0,
        )
        project_id = state["project"]["id"]
        state["zone_in"] = make_site_zone(
            api, project_id, zone_code="Z-INBOUND", throughput_share_bps=6000
        )
        state["zone_out"] = make_site_zone(
            api, project_id, zone_code="Z-OUTBOUND", throughput_share_bps=4000
        )
        return state

    def _zone_status(self, api, project_id):
        zones = validate_success(api.list_site_zones(project_id, SITE_MANAGER))
        return {zone["zone_code"]: zone["ops_status"] for zone in zones}

    def test_starting_one_zone_window_moves_only_that_zone_s_share(self, api):
        """Six thousand basis points leave legacy service; four thousand stay.

        PRD §2.9: "Starting a cutover window subtracts that zone's share from
        `legacy_share_bps` and adds the identical amount to `in_transition_share_bps`."

        Design: Corner/state_machines/cutover_window_start_moves_the_share_ledger_from_legacy_to_in_transition
        """
        state = self._two_zone_project(api)
        window = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(
                    state["project"]["id"], state["zone_in"]["id"], state["lot"]["id"]
                ),
                SITE_MANAGER,
            ),
            expected_status=201,
        )
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])

        started = validate_success(api.start_cutover_window(window["id"], SITE_MANAGER))
        assert started["status"] == "IN_PROGRESS"
        assert is_iso8601_timestamp(started["started_at"])
        assert started["started_at"].startswith(TEST_INSTANTS["WINDOW_DUE_UTC"][:19])

        statuses = self._zone_status(api, state["project"]["id"])
        assert statuses["Z-INBOUND"] == "CUTOVER_IN_PROGRESS"
        assert statuses["Z-OUTBOUND"] == "LIVE_LEGACY"

        project = read_project(api, state["project"]["id"])
        assert project["legacy_share_bps"] == 4000
        assert project["in_transition_share_bps"] == 6000
        assert project["cutover_share_bps"] == 0
        assert (
            project["legacy_share_bps"]
            + project["in_transition_share_bps"]
            + project["cutover_share_bps"]
            == 10000
        )
        assert project["delivery_status"] == "CUTOVER"
        assert read_lot(api, state["lot"]["id"])["status"] == "FAT_PASSED"

    def test_commissioning_waits_for_the_last_zone(self, api):
        """The first completion leaves CUTOVER; the second bubbles up to COMMISSIONING.

        PRD §3.6: "and if every site zone of the project has now reached
        `CUTOVER_COMPLETE`, the project bubbles up from `CUTOVER` to `COMMISSIONING`."

        Design: Corner/state_machines/project_bubbles_to_commissioning_only_when_every_zone_is_cutover_complete
        """
        state = self._two_zone_project(api, bay_code="BAY-4", lot_code="LOT-401")
        project_id = state["project"]["id"]
        second_lot = make_planned_lot(
            api,
            frozen=state,
            bay=state["bay"],
            segment_codes=["TR-02"],
            lot_code="LOT-402",
        )["lot"]
        validate_success(api.start_fabrication(second_lot["id"], SHOP_SUPERVISOR))
        staged = validate_success(api.stage_fabrication_lot(second_lot["id"], SHOP_SUPERVISOR))
        record_fat_test(api, staged, measured_cph=1320, defect_count=1)

        first_window = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(
                    project_id, state["zone_in"]["id"], state["lot"]["id"]
                ),
                SITE_MANAGER,
            ),
            expected_status=201,
        )
        second_window = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(
                    project_id, state["zone_out"]["id"], second_lot["id"]
                ),
                SITE_MANAGER,
            ),
            expected_status=201,
        )
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])

        validate_success(api.start_cutover_window(first_window["id"], SITE_MANAGER))
        validate_success(api.complete_cutover_window(first_window["id"], SITE_MANAGER))

        midway = read_project(api, project_id)
        assert midway["delivery_status"] == "CUTOVER"
        assert midway["cutover_share_bps"] == 6000
        assert midway["in_transition_share_bps"] == 0
        assert midway["legacy_share_bps"] == 4000

        validate_success(api.start_cutover_window(second_window["id"], SITE_MANAGER))
        validate_success(api.complete_cutover_window(second_window["id"], SITE_MANAGER))

        after = read_project(api, project_id)
        assert after["delivery_status"] == "COMMISSIONING"
        assert after["cutover_share_bps"] == 10000
        assert after["legacy_share_bps"] == 0
        assert after["in_transition_share_bps"] == 0
        assert after["acceptance_ready"] is False

        statuses = self._zone_status(api, project_id)
        assert statuses == {"Z-INBOUND": "CUTOVER_COMPLETE", "Z-OUTBOUND": "CUTOVER_COMPLETE"}
        assert read_lot(api, state["lot"]["id"])["status"] == "INSTALLED"
        assert read_lot(api, second_lot["id"])["status"] == "INSTALLED"

    def test_completing_a_scheduled_window_is_not_a_declared_transition(self, api):
        """Completion is only defined from IN_PROGRESS.

        PRD §3.6: "Completing a window is the hand-over. It requires the window to be
        `IN_PROGRESS`, otherwise `ERR_WINDOW_INVALID_STATE`."

        Design: Corner/state_machines/cutover_window_complete_from_scheduled_returns_window_invalid_state
        """
        state = make_scheduled_window(
            api,
            state=make_fat_passed_lot(
                api,
                bay=make_staging_bay(api, bay_code="BAY-5", concurrent_capacity=2),
                segment_codes=["IB-01", "TR-02"],
                lot_code="LOT-500",
                measured_cph=1313,
                defect_count=0,
            ),
        )
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])

        response = api.complete_cutover_window(state["window"]["id"], SITE_MANAGER)
        validate_error(response, ApiErrorId.ERR_WINDOW_INVALID_STATE.value)

        window = read_window(api, state["window"]["id"])
        assert window["status"] == "SCHEDULED"
        assert window["closed_at"] is None
        assert self._zone_status(api, state["project"]["id"])["Z-INBOUND"] == "LIVE_LEGACY"
        assert read_lot(api, state["lot"]["id"])["status"] == "FAT_PASSED"

        project = read_project(api, state["project"]["id"])
        assert project["legacy_share_bps"] == 10000
        assert project["cutover_share_bps"] == 0
        assert project["delivery_status"] == "IN_FABRICATION"


class TestLotReleaseIsNotIdempotent:
    """A repeated release is rejected rather than silently replayed."""

    def test_a_second_start_fabrication_is_refused(self, api):
        """Release is defined from PLANNED and from FAT_FAILED, not from FABRICATING.

        PRD §3.4: "A supervisor releases a lot to the floor, advancing it from `PLANNED`
        to `FABRICATING`; this requires the project's `delivery_status` to be either
        `DESIGN_FROZEN` or `IN_FABRICATION`, otherwise `ERR_DESIGN_NOT_FROZEN`, and when
        the project was still `DESIGN_FROZEN` the first such release bubbles it up to
        `IN_FABRICATION`."

        PRD §2.12: "**State admissibility** — the target resource and its gating relatives
        are in states that admit the operation."

        Design: Corner/state_machines/second_start_fabrication_on_a_fabricating_lot_returns_lot_invalid_state
        """
        state = make_planned_lot(
            api,
            bay=make_staging_bay(api, bay_code="BAY-6", concurrent_capacity=2),
            segment_codes=["IB-01"],
            lot_code="LOT-600",
        )
        validate_success(api.start_fabrication(state["lot"]["id"], SHOP_SUPERVISOR))

        response = api.start_fabrication(state["lot"]["id"], SHOP_SUPERVISOR)
        validate_error(response, ApiErrorId.ERR_LOT_INVALID_STATE.value)

        lot = read_lot(api, state["lot"]["id"])
        assert lot["status"] == "FABRICATING"
        assert lot["version"] == 2
        assert lot["fat_attempt_count"] == 0
        assert read_project(api, state["project"]["id"])["delivery_status"] == "IN_FABRICATION"


class TestAcceptanceCertificateSnapshot:
    """Issuance freezes the settlement baseline from the newest passing evidence."""

    def test_issuance_snapshots_the_latest_full_rate_ramp_and_the_deadline(self, api):
        """Two passing full-rate steps: the later 1260 wins, deadline is 30 days out.

        PRD §3.7: "Its `accepted_throughput_cph` is the `measured_cph` of the project's
        ramp step whose `verdict` is `PASS` and whose `step_pct` is 100; where more than
        one such step exists across the whole project history, the one with the greatest
        `created_at` wins, and failing steps and lower levels are excluded from
        consideration entirely."

        Design: Corner/state_machines/acceptance_certificate_issuance_snapshots_retention_and_dispute_deadline
        """
        frozen = make_frozen_project(api)
        state = make_scheduled_window(
            api,
            state=make_fat_passed_lot(
                api,
                staged=None,
                measured_cph=1313,
                defect_count=0,
                frozen=frozen,
                bay=make_staging_bay(api, bay_code="BAY-7", concurrent_capacity=2),
                segment_codes=["IB-01", "TR-02"],
                lot_code="LOT-700",
            ),
        )
        project_id = state["project"]["id"]
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])
        validate_success(api.start_cutover_window(state["window"]["id"], SITE_MANAGER))
        validate_success(api.complete_cutover_window(state["window"]["id"], SITE_MANAGER))

        record_ramp(api, project_id, 50, 700, 30)
        record_ramp(api, project_id, 75, 1000, 60)
        record_ramp(api, project_id, 100, 1255, 120)
        record_ramp(api, project_id, 100, 1260, 120)

        certificate = validate_success(
            api.create_acceptance_certificate(
                create_acceptance_certificate_payload(project_id), PROJECT_DIRECTOR
            ),
            expected_status=201,
        )
        assert_acceptance_certificate(certificate)
        assert certificate["status"] == "ISSUED"
        assert certificate["accepted_throughput_cph"] == 1260
        assert certificate["bottleneck_availability_pct"] == 95
        assert certificate["retention_amount_cents"] == 12_180_000
        assert certificate["retention_release_cents"] == 0
        assert certificate["issued_by_user_id"] == PROJECT_DIRECTOR["X-User-ID"]
        assert certificate["dispute_deadline_utc"].startswith("2026-09-09T20:00:00")

        project = read_project(api, project_id)
        assert project["delivery_status"] == "ACCEPTED"
        assert project["commercial_status"] == "CLEAN"
        assert frozen["simulation"]["effective_throughput_cph"] == 1330
        assert frozen["simulation"]["bottleneck_availability_pct"] == 95
