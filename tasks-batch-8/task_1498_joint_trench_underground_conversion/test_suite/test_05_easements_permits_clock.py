"""Easement negotiation cycles, posture derivation, permit lazy expiry,
optimistic concurrency, and the restoration warranty clock.

PRD §3.2 (easements/permits), §2.5 (logical clock), §2.7 (posture),
§2.8 (OCC), §3.8 (warranty).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_instant_equal,
    create_project,
    create_parcel,
    create_easement_payload,
    create_restoration_task_payload,
    create_issued_permit,
    setup_mobilized_project,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]
ROW = TEST_USERS["row_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]


class TestEasementRenegotiation:
    def _setup(self, api):
        project = create_project(name="Easement Project", rule20_credit_cents=0,
                                 estimated_total_cost_cents=500000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        parcel = create_parcel(project["id"], address="3 Elm St", owner_name="Owner Three",
                               existing_panel_amps=100, load_calc_amps=60)
        es = validate_success(api.create_easement(
            create_easement_payload(parcel["id"], easement_type="TRENCH"), ROW), 201)
        return project, parcel, es

    def test_refused_easement_reopens_with_refreshed_request(self, api):
        """PRD §3.2: "Refusal is not the end of negotiation — `REFUSED →
        REQUESTED` reopens the easement, refreshes `requested_on` to the clock,
        and recomputes posture again."
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Difficulty/non_linear_state_machine/easement_refusal_renegotiation_cycle
        """
        _project, _parcel, es = self._setup(api)
        req1 = validate_success(api.transition_easement(es["id"], {"to": "REQUESTED"}, ROW), 200)
        assert_instant_equal(req1["requested_on"], "2026-08-01T00:00:00Z",
                             "requested_on at the startup clock")
        validate_success(api.transition_easement(es["id"], {"to": "REFUSED"}, ROW), 200)

        validate_success(api.set_clock("2026-08-05T00:00:00Z", PM), 200)
        req2 = validate_success(api.transition_easement(es["id"], {"to": "REQUESTED"}, ROW), 200)
        assert req2["status"] == "REQUESTED", (
            f"REFUSED -> REQUESTED loop-back reopens negotiation, got {req2['status']}"
        )
        assert_instant_equal(req2["requested_on"], "2026-08-05T00:00:00Z",
                             "renegotiation refreshes requested_on")

    def test_cycle_terminates_at_recorded(self, api):
        """PRD §3.2: "The easement lifecycle runs `DRAFT → REQUESTED → SIGNED →
        RECORDED`, with each step stamping the clock onto `requested_on`,
        `signed_on`, and `recorded_on` respectively, and `RECORDED` terminal."

        Design: Difficulty/non_linear_state_machine/easement_refusal_renegotiation_cycle
        """
        _project, _parcel, es = self._setup(api)
        validate_success(api.transition_easement(es["id"], {"to": "REQUESTED"}, ROW), 200)
        validate_success(api.transition_easement(es["id"], {"to": "REFUSED"}, ROW), 200)
        validate_success(api.set_clock("2026-08-05T00:00:00Z", PM), 200)
        validate_success(api.transition_easement(es["id"], {"to": "REQUESTED"}, ROW), 200)
        validate_success(api.transition_easement(es["id"], {"to": "SIGNED"}, ROW), 200)
        rec = validate_success(api.transition_easement(es["id"], {"to": "RECORDED"}, ROW), 200)
        assert rec["status"] == "RECORDED"
        assert_instant_equal(rec["recorded_on"], "2026-08-05T00:00:00Z",
                             "recorded_on stamps the clock")

    def test_easement_draft_to_signed_rejected(self, api):
        """PRD §3.2: "The easement lifecycle runs `DRAFT → REQUESTED → SIGNED →
        RECORDED`, with each step stamping the clock onto `requested_on`,
        `signed_on`, and `recorded_on` respectively, and `RECORDED` terminal."
        PRD §2.10: "Every state machine in the system also observes terminal
        lockdown: once an entity reaches a terminal state, every further
        transition request on it is rejected with `ERR_INVALID_STATE`."
        DRAFT -> SIGNED skips REQUESTED and is not a declared step.

        Design: Corner/state_machines/easement_draft_to_signed_rejected
        """
        _project, _parcel, es = self._setup(api)
        resp = api.transition_easement(es["id"], {"to": "SIGNED"}, ROW)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_easement(es["id"], ROW), 200)
        assert after["status"] == "DRAFT", "rejection leaves the easement in DRAFT"


class TestPostureOnRefusal:
    def test_posture_conditional_on_refused_easement(self, api):
        """PRD §2.7: "The derivation is ordered: the posture is `FROZEN`
        whenever any change order of the project is `APPROVED`; otherwise it is
        `CONDITIONAL` whenever any `TRENCH` easement on any parcel of the
        project is `REFUSED`, or whenever any participation's `variance_flag`
        is true; otherwise it is `CLEAR`."

        Design: Corner/calculations/posture_conditional_on_refused_easement
        """
        project = create_project(name="C1", rule20_credit_cents=0,
                                 estimated_total_cost_cents=500000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        parcel = create_parcel(project["id"], address="4 B St", owner_name="O",
                               existing_panel_amps=100, load_calc_amps=50)
        es = validate_success(api.create_easement(
            create_easement_payload(parcel["id"], easement_type="TRENCH"), ROW), 201)
        validate_success(api.transition_easement(es["id"], {"to": "REQUESTED"}, ROW), 200)
        validate_success(api.transition_easement(es["id"], {"to": "REFUSED"}, ROW), 200)
        proj = validate_success(api.get_project(project["id"], PM), 200)
        assert proj["posture"] == "CONDITIONAL", (
            f"REFUSED TRENCH easement drops posture to CONDITIONAL, got {proj['posture']}"
        )


class TestPermitLazyExpiry:
    def test_permit_lazy_expiry_on_clock_advance(self, api):
        """PRD §2.5: "First, permit expiry is lazy: an `ISSUED` permit flips to
        `EXPIRED` whenever it is read or referenced while the clock has passed
        its `valid_to`, and advancing the clock triggers a sweep that applies
        this transition to every overdue permit."

        Design: Corner/cross_cutting_layers/permit_lazy_expiry_on_clock_advance
        """
        project = create_project(name="L1", rule20_credit_cents=0,
                                 estimated_total_cost_cents=1000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        perm = create_issued_permit(project["id"],
                                    valid_from="2026-08-01T00:00:00Z",
                                    valid_to="2026-09-01T00:00:00Z")
        assert perm["status"] == "ISSUED"
        validate_success(api.set_clock("2026-09-02T00:00:00Z", PM), 200)
        after = validate_success(api.get_permit(perm["id"], ROW), 200)
        assert after["status"] == "EXPIRED", (
            f"read after the clock passes valid_to flips ISSUED -> EXPIRED, got {after['status']}"
        )


class TestOptimisticConcurrency:
    def test_occ_replan_stale_version_rejected(self, api):
        """PRD §2.8: "Replanning a project's cutover date likewise requires
        `expected_project_version`, and a mismatch with the project's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "All three protected operations increment the parent
        resource's `version` by one on success, so every successful write
        invalidates the version the next writer may be holding."

        Design: Corner/cross_cutting_layers/occ_replan_stale_version_rejected
        """
        project = create_project(name="OCC1", rule20_credit_cents=0,
                                 estimated_total_cost_cents=1000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        v1 = project["version"]
        resp = api.replan_project(
            project["id"],
            {"new_target_cutover_on": "2027-01-15T00:00:00Z",
             "expected_project_version": v1},
            PM,
        )
        replanned = validate_success(resp, 200)
        assert replanned["version"] == v1 + 1, (
            f"successful replan increments the version by one: {v1} -> {replanned['version']}"
        )
        assert_instant_equal(replanned["target_cutover_on"], "2027-01-15T00:00:00Z",
                             "target_cutover_on replaced")

        resp = api.replan_project(
            project["id"],
            {"new_target_cutover_on": "2027-02-01T00:00:00Z",
             "expected_project_version": v1},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_segment_version_rejected_on_schedule(self, api):
        """PRD §2.8: "Scheduling or rescheduling a trench segment requires
        `expected_trench_segment_version`, equal to the segment's current
        `version`. A mismatch with the segment's current `version` is rejected
        with `ERR_STALE_VERSION` (HTTP 412), because a reschedule legitimately
        replaces the current excavation window and a stale writer would
        silently discard a window it never saw."
        PRD §2.8: "All three protected operations increment the parent
        resource's `version` by one on success, so every successful write
        invalidates the version the next writer may be holding."

        Design: Corner/validations/stale_segment_version_rejected_on_schedule
        """
        project, _parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 9999, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 1, "sequence_order": 2},
            ],
            name="V4", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        seg = validate_success(api.create_trench_segment(
            {"project_id": project["id"], "segment_code": "SEG-1", "length_ft": 100,
             "max_depth_inches": 60}, PM), 201)
        v1 = seg["version"]
        scheduled = validate_success(api.schedule_trench_segment(
            seg["id"],
            {"excavation_start_on": "2026-09-01T00:00:00Z",
             "excavation_end_on": "2026-09-10T00:00:00Z",
             "expected_trench_segment_version": v1},
            PM,
        ), 200)
        assert scheduled["version"] == v1 + 1, (
            f"first schedule increments the version: {v1} -> {scheduled['version']}"
        )

        resp = api.schedule_trench_segment(
            seg["id"],
            {"excavation_start_on": "2026-09-02T00:00:00Z",
             "excavation_end_on": "2026-09-11T00:00:00Z",
             "expected_trench_segment_version": v1},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestWarrantyClock:
    def test_warranty_claim_exactly_at_expiry(self, api):
        """PRD §3.8: "The contractor works the task (`OPEN → IN_WORK`) and
        reports completion (`IN_WORK → COMPLETE`), which stamps `completed_on`
        with the clock and sets `warranty_expires_on` exactly one hundred
        eighty days later."
        PRD §3.8: "While the logical clock has not passed `warranty_expires_on`
        — the expiry instant itself is still claimable — the `ProgramManager`
        may open a warranty claim (`ACCEPTED → WARRANTY_CLAIM`); one second
        past expiry the attempt fails with `ERR_WARRANTY_EXPIRED`."

        Design: Corner/calculations/warranty_claim_exactly_at_expiry
        """
        project = create_project(name="C2", rule20_credit_cents=0,
                                 estimated_total_cost_cents=1000000,
                                 target_cutover_on="2026-12-31T00:00:00Z",
                                 contingency_days=0)
        parcel = create_parcel(project["id"], address="5 B St", owner_name="O",
                               existing_panel_amps=100, load_calc_amps=50)
        seg = validate_success(api.create_trench_segment(
            {"project_id": project["id"], "segment_code": "SEG-1", "length_ft": 100,
             "max_depth_inches": 60, "parcel_ids": [parcel["id"]]}, PM), 201)

        def _accepted_task(task_type):
            rt = validate_success(api.create_restoration_task(
                create_restoration_task_payload(seg["id"], parcel["id"], task_type=task_type),
                CONTRACTOR), 201)
            validate_success(api.transition_restoration_task(rt["id"], {"to": "IN_WORK"}, CONTRACTOR), 200)
            completed = validate_success(
                api.transition_restoration_task(rt["id"], {"to": "COMPLETE"}, CONTRACTOR), 200)
            validate_success(api.transition_restoration_task(rt["id"], {"to": "ACCEPTED"}, PM), 200)
            return rt["id"], completed

        rt1, completed1 = _accepted_task("HARDSCAPE")
        rt2, _ = _accepted_task("LANDSCAPE")

        assert_instant_equal(
            completed1["warranty_expires_on"], "2027-01-28T00:00:00Z",
            "completed at the 2026-08-01 startup clock + 180 days",
        )

        validate_success(api.set_clock("2027-01-28T00:00:00Z", PM), 200)
        resp = api.transition_restoration_task(rt1, {"to": "WARRANTY_CLAIM"}, PM)
        claim = validate_success(resp, 200)
        assert claim["status"] == "WARRANTY_CLAIM", (
            "claim at the exact expiry instant is valid"
        )

        validate_success(api.set_clock("2027-01-28T00:00:01Z", PM), 200)
        resp = api.transition_restoration_task(rt2, {"to": "WARRANTY_CLAIM"}, PM)
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)
