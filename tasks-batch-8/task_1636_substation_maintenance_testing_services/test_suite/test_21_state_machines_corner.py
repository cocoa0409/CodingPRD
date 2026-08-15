"""Corner coverage — state machines: terminal lockdown, invalid transitions,
precondition enforcement, initial states, and side-effect transitions."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_switching_step,
    api_client,
    approve_outage_window,
    begin_switching,
    build_user_headers,
    create_certified_technician,
    create_defect,
    create_environmental_inspection,
    create_outage_window,
    create_relay_setting_payload,
    create_substation,
    create_test_event,
    create_verified_relay_setting,
    create_work_order,
    execute_step,
    get_success_data,
    schedule_work_order,
    set_clock,
    setup_asset,
    setup_relay_domain,
    setup_switching_window,
    submit_test_event,
    validate_error,
    validate_success,
    verify_step,
)

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]
SUP2 = TEST_USERS["supervisor_alt_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestOutageTerminalLockdown:
    def test_second_cancel_from_cancelled_rejected(self):
        """PRD §3.2: "An `OutageCoordinator` may cancel a window while it is
        `REQUESTED` or `APPROVED`. Cancelling from `REQUESTED` simply
        transitions to `CANCELLED`."
        PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409)"

        Design: Corner/state_machines/outage_terminal_lockdown_cancel_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-09-25T08:00:00Z", "2026-09-25T16:00:00Z", purpose="Lockdown probe",
        )
        cancelled = validate_success(api_client.cancel_outage_window(window["id"], COORD))
        assert cancelled["status"] == "CANCELLED"
        resp = api_client.cancel_outage_window(window["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION, 409)

    def test_approve_already_approved_rejected_without_double_hours(self):
        """PRD §3.2: "Approval is performed by an `OperationsManager` and is a
        different operator from the requester; an approver whose `X-User-ID`
        equals the window's `requested_by` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval enforces, in order,
        that the window is in `REQUESTED`, that `needs_revalidation` is false
        (otherwise `ERR_OUTAGE_NEEDS_REVALIDATION`, HTTP 409), and that no `C1`
        defect in `OPEN`, `WORK_ORDERED`, or `DEFERRED` exists against the
        window's asset (otherwise `ERR_OPEN_CRITICAL_DEFECT`, HTTP 422)."
        PRD §3.2: "A successful approval transitions the window `REQUESTED →
        APPROVED`, stamps `approved_by` from the caller's `X-User-ID`, adds the
        window's `duration_hours` into the asset's `approved_outage_hours`, and
        increments the window's `version`."

        Design: Corner/state_machines/approve_already_approved_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-10-05T08:00:00Z", "2026-10-05T16:00:00Z", purpose="Double approve",
        )
        approve_outage_window(window["id"], "ops-mgr-1")
        # Second approve from APPROVED is a state violation (different approver,
        # so segregation of duties does not fire first).
        resp = api_client.approve_outage_window(
            window["id"], TEST_USERS["ops_manager_alt_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION, 409)
        asset = validate_success(api_client.get_asset(base["asset"]["id"], OPS))
        assert abs(asset["approved_outage_hours"] - 8.00) < 1e-9, (
            "approved hours must be added exactly once"
        )


class TestSwitchingStepOrderingAndSegregation:
    def test_step_execute_out_of_order_rejected(self):
        """PRD §3.3: "Execution is strictly ordered: a step may execute only
        when every sibling step of the same window with a lower `sequence_no`
        is already `VERIFIED`; violating the order is rejected with
        `ERR_STEP_ORDER_VIOLATION` (HTTP 409)."

        Design: Corner/state_machines/step_execute_out_of_order_rejected
        """
        ctx = setup_switching_window(
            "2026-08-16T08:00:00Z", "2026-08-16T16:00:00Z", "2026-08-16T09:00:00Z",
            num_steps=2,
        )
        step2 = ctx["steps"][1]
        resp = api_client.execute_switching_step(step2["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_STEP_ORDER_VIOLATION, 409)

    def test_step_verify_by_same_supervisor_rejected(self):
        """PRD §3.3: "Verification is a second `SwitchingSupervisor` action on
        an `EXECUTED` step; the verifier's `X-User-ID` must differ from
        `executed_by`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
        Verification stamps `verified_by` and `verified_at` from the logical
        clock and transitions the step `EXECUTED → VERIFIED`."

        Design: Corner/state_machines/step_verify_by_same_supervisor_rejected
        """
        ctx = setup_switching_window(
            "2026-08-17T08:00:00Z", "2026-08-17T16:00:00Z", "2026-08-17T09:00:00Z",
            num_steps=1,
        )
        step = ctx["steps"][0]
        execute_step(step["id"], "sup-1")
        resp = api_client.verify_switching_step(step["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        verified = validate_success(api_client.verify_switching_step(step["id"], SUP2))
        assert verified["status"] == "VERIFIED"


class TestOutageApproveSegregation:
    def test_approve_by_requester_rejected(self):
        """PRD §3.2: "Approval is performed by an `OperationsManager` and is a
        different operator from the requester; an approver whose `X-User-ID`
        equals the window's `requested_by` is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/state_machines/outage_approve_by_requester_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-10-10T08:00:00Z", "2026-10-10T16:00:00Z",
            purpose="SoD approve", requester_id="shared-user-1",
        )
        resp = api_client.approve_outage_window(
            window["id"], build_user_headers("shared-user-1", "OperationsManager")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)


class TestTestEventInitialStateAndReturn:
    def test_initial_state_and_return_requires_note(self):
        """PRD §3.4: "The event arrives in `DRAFT` with `result` null."
        PRD §3.4: "A decision of `RETURN` requires `review_note` to be present
        — its absence is rejected with `ERR_VALIDATION` (HTTP 400) — and
        transitions `SUBMITTED → RETURNED`, also stamping `reviewed_by`."

        Design: Corner/state_machines/test_event_initial_state_and_return_requires_note
        """
        base = setup_asset("POWER_TRANSFORMER")
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        event = create_test_event(
            base["asset"]["id"], tech_headers, "OIL_MOISTURE",
            value_primary=10, measured_at="2026-07-10T00:00:00Z",
        )
        assert event["status"] == "DRAFT"
        assert event["result"] is None
        submit_test_event(event["id"], tech_headers)
        resp = api_client.review_test_event(event["id"], {"decision": "RETURN"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_submit_by_non_creator_rejected(self):
        """PRD §3.4: "Only the creator may submit — the caller's `X-User-ID`
        must equal the event's `technician_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/state_machines/test_submit_by_non_creator_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        _, tech_a_headers = create_certified_technician("NETA_LEVEL_2")
        _, tech_b_headers = create_certified_technician("NETA_LEVEL_2")
        event = create_test_event(
            base["asset"]["id"], tech_a_headers, "OIL_MOISTURE",
            value_primary=10, measured_at="2026-07-11T00:00:00Z",
        )
        resp = api_client.submit_test_event(event["id"], tech_b_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)


class TestRelaySettingStates:
    def test_verify_by_author_rejected_despite_certification(self):
        """PRD §3.8: "Verification and rejection are performed by a different
        technician holding an `ACTIVE` `NETA_LEVEL_4` certification; a reviewer
        without that certification is rejected with
        `ERR_CERTIFICATION_REQUIRED` (HTTP 403), and a reviewer whose
        `X-User-ID` equals the author's is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/state_machines/relay_verify_by_author_rejected
        """
        domain = setup_relay_domain()
        # The author ALSO holds NETA_LEVEL_4: the cert gate passes and only
        # segregation of duties can fire.
        author_l4_headers = domain["author_headers"]
        get_success_data(
            api_client.create_certification(
                domain["author"]["id"],
                {
                    "cert_type": "NETA_LEVEL_4",
                    "issued_at": "2025-01-01T00:00:00Z",
                    "expires_at": "2027-01-01T00:00:00Z",
                },
                OPS,
            )
        )
        setting = get_success_data(
            api_client.create_relay_setting(
                create_relay_setting_payload(domain["asset"]["id"], pickup_a=90),
                author_l4_headers,
            )
        )
        get_success_data(api_client.submit_relay_setting(setting["id"], author_l4_headers))
        resp = api_client.verify_relay_setting(setting["id"], author_l4_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    def test_activation_supersedes_prior_active(self):
        """PRD §3.8: "Success transitions the setting `VERIFIED → ACTIVE`,
        transitions any previously `ACTIVE` setting of the same `(asset_id,
        setting_group)` to `SUPERSEDED`, stamps this setting's
        `supersedes_setting_id` to the superseded setting's `id` (null when
        none existed), and increments both the setting's and the asset's
        `version`."
        PRD §2.4: "`version` (an integer that increments by exactly 1 on every
        state transition and on every mutation the platform applies to that
        row)."

        Design: Corner/state_machines/relay_activation_supersedes_prior_active
        """
        domain = setup_relay_domain()
        asset_id = domain["asset"]["id"]
        setting1 = create_verified_relay_setting(
            asset_id, domain["author_headers"], domain["verifier_headers"], pickup_a=80,
        )
        asset = validate_success(api_client.get_asset(asset_id, OPS))
        asset_v1 = asset["version"]
        activated1 = validate_success(
            api_client.activate_relay_setting(
                setting1["id"], {"expected_asset_version": asset_v1},
                domain["verifier_headers"],
            )
        )
        assert activated1["status"] == "ACTIVE"

        setting2 = create_verified_relay_setting(
            asset_id, domain["author_headers"], domain["verifier_headers"],
            pickup_a=85, time_dial=2.2, curve="IEC_VI",
        )
        asset = validate_success(api_client.get_asset(asset_id, OPS))
        asset_v2 = asset["version"]
        assert asset_v2 == asset_v1 + 1, "activation increments the asset version by 1"
        activated2 = validate_success(
            api_client.activate_relay_setting(
                setting2["id"], {"expected_asset_version": asset_v2},
                domain["verifier_headers"],
            )
        )
        assert activated2["status"] == "ACTIVE"
        assert activated2["supersedes_setting_id"] == setting1["id"]
        prior = validate_success(api_client.get_relay_setting(setting1["id"], OPS))
        assert prior["status"] == "SUPERSEDED"


class TestRestoreBlockedByOpenWorkOrder:
    def test_restore_rejected_while_work_order_in_progress(self):
        """PRD §3.3: "Restoring the asset to service requires that no
        `WorkOrder` linked to this window remains in `SCHEDULED` or
        `IN_PROGRESS`; success transitions `CLEARED → RESTORED` and drives the
        asset `OUT_OF_SERVICE → IN_SERVICE`, again incrementing both versions."
        PRD §2.8: "then the state-machine permission check
        (`ERR_STATE_TRANSITION`, HTTP 409)"

        Design: Corner/state_machines/restore_blocked_by_open_work_order_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        tech, tech_headers = create_certified_technician("NETA_LEVEL_2")
        defect = create_defect(base["asset"]["id"], tech_headers, "C2")
        work_order = create_work_order(defect["id"], tech["id"], 2)
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-08-18T08:00:00Z", "2026-08-18T16:00:00Z", purpose="Rewire outage",
        )
        step = add_switching_step(window["id"], 1, "Isolate")
        approved = approve_outage_window(window["id"], "ops-mgr-1")
        schedule_work_order(work_order["id"], window["id"], approved["version"])
        set_clock("2026-08-18T09:00:00Z")
        begin_switching(window["id"], "sup-1")
        execute_step(step["id"], "sup-1")
        verify_step(step["id"], "sup-2")
        cleared = validate_success(api_client.clear_outage_window(window["id"], SUP1))
        assert cleared["status"] == "CLEARED"
        get_success_data(api_client.start_work_order(work_order["id"], tech_headers))
        resp = api_client.restore_outage_window(window["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_STATE_TRANSITION, 409)
        current = validate_success(api_client.get_outage_window(window["id"], OPS))
        assert current["status"] == "CLEARED"


class TestBeginSwitchingClockGate:
    def test_begin_switching_before_window_start_rejected(self):
        """PRD §3.3: "Beginning switching is a `SwitchingSupervisor` action
        gated on four conditions: the window is `APPROVED`;
        `needs_revalidation` is false; the logical clock lies within
        `[start_ts, end_ts)` — that is, at or after `start_ts` and strictly
        before `end_ts`, otherwise `ERR_OUTSIDE_WINDOW` (HTTP 422); and the
        window has at least one switching step."

        Design: Corner/state_machines/begin_switching_outside_window_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-09-30T08:00:00Z", "2026-09-30T16:00:00Z", purpose="Clock gate",
        )
        add_switching_step(window["id"], 1, "Step")
        approve_outage_window(window["id"], "ops-mgr-1")
        # The logical clock is still at its 2026-08-01 startup default.
        resp = api_client.begin_switching(window["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW, 422)


class TestDeferralCap:
    def test_third_deferral_rejected(self):
        """PRD §3.6: "A defect may be deferred at most twice: a deferral
        attempted when `deferral_count` is already 2 is rejected with
        `ERR_DEFERRAL_LIMIT_EXCEEDED` (HTTP 422)."
        PRD §2.7: "any `Defect` in `DEFERRED` whose `deferred_until` is at or
        before the new clock value reopens to `OPEN` and clears its
        `deferred_until`".

        Design: Corner/state_machines/third_deferral_rejected
        """
        base = setup_asset(
            "CIRCUIT_BREAKER", voltage_kv=34.5, install_date="2018-01-01T00:00:00Z"
        )
        tech, tech_headers = create_certified_technician("NETA_LEVEL_2")
        defect = create_defect(
            base["asset"]["id"], tech_headers, "C3",
            title="Cabinet rust", description="Surface rust",
        )
        defect_id = defect["id"]
        validate_success(
            api_client.defer_defect(defect_id, {"deferred_until": "2026-09-01T00:00:00Z"}, OPS)
        )
        set_clock("2026-09-02T00:00:00Z")
        validate_success(
            api_client.defer_defect(defect_id, {"deferred_until": "2026-10-01T00:00:00Z"}, OPS)
        )
        set_clock("2026-10-02T00:00:00Z")
        resp = api_client.defer_defect(defect_id, {"deferred_until": "2026-11-01T00:00:00Z"}, OPS)
        validate_error(resp, ApiErrorId.ERR_DEFERRAL_LIMIT_EXCEEDED, 422)
        current = validate_success(api_client.get_defect(defect_id, OPS))
        assert current["status"] == "OPEN"
        assert current["deferral_count"] == 2


class TestInspectionCloseNote:
    def test_close_deficient_inspection_requires_remediation_note(self):
        """PRD §3.10: "Closing is permitted from `COMPLETED`. When `compliance`
        is `DEFICIENT`, a `remediation_note` must be supplied — its absence is
        rejected with `ERR_VALIDATION` (HTTP 400). Closure transitions
        `COMPLETED → CLOSED`."

        Design: Corner/state_machines/inspection_close_deficient_requires_note
        """
        sub = create_substation()
        inspection = create_environmental_inspection(
            sub["id"],
            inspection_date="2026-07-20T00:00:00Z",
            largest_vessel_gal=1000,
            containment_capacity_gal=900,
            rainfall_freeboard_gal=40,
            method="SPCC_SIMPLE",
        )
        completed = validate_success(
            api_client.complete_environmental_inspection(inspection["id"], COMPLIANCE)
        )
        assert completed["compliance"] == "DEFICIENT"  # 900 < 1.10 * 1000
        resp = api_client.close_environmental_inspection(inspection["id"], {}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
        closed = validate_success(
            api_client.close_environmental_inspection(
                inspection["id"],
                {"remediation_note": "Berm raised to 1200 gal capacity"},
                COMPLIANCE,
            )
        )
        assert closed["status"] == "CLOSED"
