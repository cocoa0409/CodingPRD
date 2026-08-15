"""Takes, incidents, stoppages, and post-stunt reviews: take-number uniqueness,
execution OCC, the safety-abort chain, the incident stoppage cascade, and the
reshoot/deficiency loops (PRD §2.8, §3.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    SAFETY,
    attempt_take,
    create_active_production,
    create_execution_payload,
    create_review_payload,
    report_incident,
    schedule_rehearsal,
    setup_executed_sequence,
    setup_ready_sequence,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestIncidentStoppageCascade:
    """Incident(SERIOUS) -> production STOPPED -> READY sequence SAFETY_HOLD ->
    its SCHEDULED rehearsals CANCELLED (PRD §3.8, §2.8)."""

    def _setup(self, api):
        ctx = setup_ready_sequence(name="Cascade", hazard_class="FIGHT", risk_category="LOW")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        # An extra rehearsal still SCHEDULED when the cascade fires.
        extra = schedule_rehearsal(prod_id, seq_id, ctx["performer"]["id"],
                                   start="2026-08-04T10:00:00Z", end="2026-08-04T11:00:00Z")
        incident = report_incident(
            prod_id, severity="SERIOUS", sequence_id=seq_id,
            occurred_at="2026-08-02T12:00:00Z",
            description="Performer twisted ankle on wire descent",
        )
        return ctx, extra, incident

    def test_serious_incident_stops_production_and_holds_sequence(self, api):
        """PRD §3.8: "Reporting a `SERIOUS` or `CRITICAL` incident while the
        production is `ACTIVE` stops the production exactly as a manual stoppage
        does." and "Either path records `stopped_at` as the current logical time
        and `stop_reason` as the request's reason or the triggering incident's
        id, pushes every `READY` sequence of the production to `SAFETY_HOLD`"

        Design: Difficulty/transitive_cascade/tc_incident_stoppage_cascade
        """
        ctx, _, incident = self._setup(api)
        assert incident["status"] == "REPORTED"
        prod_read = validate_success(api.get_production(ctx["production"]["id"], SAFETY))
        assert prod_read["posture"] == "STOPPED", "link 1: incident -> stoppage"
        seq_read = validate_success(api.get_sequence(ctx["sequence"]["id"], SAFETY))
        assert seq_read["status"] == "SAFETY_HOLD", "link 2: stoppage -> hold"

    def test_hold_cascades_to_scheduled_rehearsal(self, api):
        """PRD §3.8: "pushes every `READY` sequence of the production to
        `SAFETY_HOLD`, cancels those held sequences' `SCHEDULED` rehearsals,
        adjourns their `SCHEDULED` or `IN_SESSION` safety meetings, and
        increments the production's `version` by one."

        Design: Difficulty/transitive_cascade/tc_incident_stoppage_cascade
        """
        ctx, extra, _ = self._setup(api)
        reh_read = validate_success(api.get_rehearsal(extra["id"], SAFETY))
        assert reh_read["status"] == "CANCELLED", "link 3: hold -> rehearsal cancellation"


class TestSafetyAbortCascade:
    def test_safety_related_abort_creates_incident_and_stops_production(self, api):
        """PRD §3.8: "When `safety_related` is true, the payload must also
        include `incident_severity` — its absence is rejected with
        `ERR_VALIDATION` — and the system auto-creates an incident in `REPORTED`
        status whose `severity` equals `incident_severity` and whose
        `sequence_id` is the take's sequence; if that severity is `SERIOUS` or
        `CRITICAL`, the production-stoppage cascade fires, the chain running
        from the abort to the incident to `STOPPED` to `SAFETY_HOLD`."

        Design: Corner/cross_cutting_complexity_layers/cc_safety_abort_cascade
        """
        ctx = setup_ready_sequence(name="Abort", hazard_class="FIGHT", risk_category="LOW")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        take = attempt_take(prod_id, seq_id, 1)
        aborted = validate_success(
            api.abort_execution(
                take["id"],
                {"abort_reason": "wire snap mid-gag", "safety_related": True, "incident_severity": "SERIOUS"},
                COORD,
            )
        )
        assert aborted["status"] == "ABORTED"
        incidents, meta = validate_paginated(
            api.list_incidents(SAFETY, params={"production_id": prod_id, "sequence_id": seq_id})
        )
        assert meta["total_count"] == 1, "exactly one incident is auto-created"
        assert incidents[0]["severity"] == "SERIOUS"
        assert incidents[0]["status"] == "REPORTED"
        assert validate_success(api.get_production(prod_id, SAFETY))["posture"] == "STOPPED"
        assert validate_success(api.get_sequence(seq_id, SAFETY))["status"] == "SAFETY_HOLD"


class TestExecutionOcc:
    def test_take_with_stale_sequence_version_rejected(self, api):
        """PRD §2.6: "Second, attempting a take likewise requires
        `expected_sequence_version` matching the sequence's current `version`; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Between the
        coordinator's readiness read and the take attempt, another writer may
        have created a superseding risk assessment — which advances the
        sequence's `version` while the sequence legitimately remains `READY` —
        and the stale-version check is what rejects the take."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_execution_stale_rejected
        """
        ctx = setup_ready_sequence(name="OCC Ex", hazard_class="FIGHT", risk_category="LOW")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        ready_version = ctx["sequence"]["version"]
        first = attempt_take(prod_id, seq_id, 1)
        assert first["status"] == "ATTEMPTED", "take 1 succeeds and bumps the sequence version"
        # The sequence is still READY (take 1 was never completed), but the
        # version captured at mark-ready is now stale.
        seq_now = validate_success(api.get_sequence(seq_id, COORD))
        assert seq_now["status"] == "READY"
        assert seq_now["version"] > ready_version
        payload = create_execution_payload(prod_id, seq_id, 2, ready_version)
        resp = api.create_execution(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestTakeNumberUniqueness:
    def test_duplicate_take_number_rejected_even_after_abort(self, api):
        """PRD §3.8: "`take_number` must be unique across all executions of the
        sequence regardless of their status — a reused number is rejected with
        `ERR_DUPLICATE_TAKE_NUMBER` even if the earlier take was aborted."

        Design: Corner/errors/err_duplicate_take_number_rejected
        """
        ctx = setup_ready_sequence(name="Take", hazard_class="FIGHT", risk_category="LOW")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        take1 = attempt_take(prod_id, seq_id, 1)
        aborted = validate_success(
            api.abort_execution(take1["id"], {"abort_reason": "camera not rolling", "safety_related": False}, COORD)
        )
        assert aborted["status"] == "ABORTED"
        # Sequence remains READY (nothing completed); retry take_number 1 with a
        # current OCC version so only the uniqueness rule can fail.
        seq_now = validate_success(api.get_sequence(seq_id, COORD))
        assert seq_now["status"] == "READY"
        payload = create_execution_payload(prod_id, seq_id, 1, seq_now["version"])
        resp = api.create_execution(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAKE_NUMBER)


class TestExecutionTerminalLockdown:
    def test_complete_aborted_take_rejected(self, api):
        """PRD §3.8: "Completing a take — `ATTEMPTED → COMPLETED`, with any
        other state rejected as `ERR_EXECUTION_INVALID_STATE`"

        Design: Corner/state_machines/sm_execution_terminal_lockdown_rejected
        """
        ctx = setup_ready_sequence(name="Ex", hazard_class="FIGHT", risk_category="LOW")
        take = attempt_take(ctx["production"]["id"], ctx["sequence"]["id"], 1)
        aborted = validate_success(
            api.abort_execution(take["id"], {"abort_reason": "camera not rolling", "safety_related": False}, COORD)
        )
        assert aborted["status"] == "ABORTED"
        resp = api.complete_execution(take["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_EXECUTION_INVALID_STATE)


class TestIncidentWorkflow:
    def test_close_requires_under_investigation(self, api):
        """PRD §3.8: "opening an investigation requires `REPORTED`
        (`ERR_INCIDENT_INVALID_STATE` otherwise) and moves the incident to
        `UNDER_INVESTIGATION`; closing requires `UNDER_INVESTIGATION` (again
        `ERR_INCIDENT_INVALID_STATE`)"

        Design: Corner/state_machines/sm_incident_close_requires_investigation_rejected
        """
        prod = create_active_production(name="P", budget=5000000)
        incident = report_incident(prod["id"], severity="MINOR", occurred_at="2026-08-01T06:00:00Z",
                                   description="bruised knuckle")
        assert incident["status"] == "REPORTED"
        assert validate_success(api.get_production(prod["id"], SAFETY))["posture"] == "ACTIVE", (
            "a MINOR incident does not stop the production"
        )
        resp = api.close_incident(incident["id"], {"corrective_action": "taped gloves"}, SAFETY)
        validate_error(resp, ApiErrorId.ERR_INCIDENT_INVALID_STATE)


class TestPostStuntReviews:
    def test_second_open_review_rejected(self, api):
        """PRD §3.8: "After execution, a `SafetyOfficer` opens a post-stunt
        review with `production_id` and `sequence_id`; the sequence must be
        `EXECUTED` (`ERR_SEQUENCE_INVALID_STATE` otherwise), at most one review
        may stand `OPEN` per sequence (`ERR_REVIEW_ALREADY_OPEN`)"

        Design: Corner/errors/err_review_already_open_rejected
        """
        ctx = setup_executed_sequence(name="Rev", hazard_class="FIGHT", risk_category="LOW")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        first = validate_success(api.create_review(create_review_payload(prod_id, seq_id), SAFETY), 201)
        assert first["status"] == "OPEN"
        resp = api.create_review(create_review_payload(prod_id, seq_id), SAFETY)
        validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_OPEN)

    def test_reshoot_loop_bumps_revision_and_invalidates_meeting(self, api):
        """PRD §3.8: "`RESHOOT_REQUIRED` returns it `EXECUTED → DESIGN_LOCKED`
        with `design_revision` incremented by one — meetings and signoffs pinned
        to the old revision no longer satisfy readiness — while
        `current_assessment_id` is retained."
        PRD §3.6: "Meeting satisfaction: there must exist a safety meeting of
        this sequence in `COMPLETED` status whose pinned `design_revision`
        equals the sequence's current `design_revision`"

        Design: Corner/state_machines/sm_reshoot_loop_bumps_revision_invalidates_meeting
        """
        ctx = setup_executed_sequence(name="Reshoot", hazard_class="FIGHT", risk_category="LOW")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        pinned_assessment = ctx["sequence"]["current_assessment_id"]
        assert ctx["meeting"]["design_revision"] == 1, "meeting pinned the design revision at creation"
        review = validate_success(api.create_review(create_review_payload(prod_id, seq_id), SAFETY), 201)
        validate_success(
            api.close_review(review["id"], {"outcome": "RESHOOT_REQUIRED", "findings": "camera missed the gag"},
                             SAFETY)
        )
        seq = validate_success(api.get_sequence(seq_id, SAFETY))
        assert seq["status"] == "DESIGN_LOCKED"
        assert seq["design_revision"] == 2
        assert seq["current_assessment_id"] == pinned_assessment, "RESHOOT_REQUIRED retains the assessment"
        resp = api.mark_ready(seq_id, COORD)
        validate_error(resp, ApiErrorId.ERR_MEETING_REQUIREMENT_UNSATISFIED)

    def test_safety_deficiency_supersedes_assessment(self, api):
        """PRD §3.8: "`SAFETY_DEFICIENCY` likewise returns it to `DESIGN_LOCKED`
        with `design_revision` incremented, but additionally clears
        `current_assessment_id` and moves the previously pinned `APPROVED`
        assessment to `SUPERSEDED`, so a fresh assessment must be approved and
        the design re-locked before the sequence can be marked ready again."
        PRD §3.2: "It requires at least one `APPROVED` assessment of the
        sequence (absent that, `ERR_SEQUENCE_INVALID_STATE`)"

        Design: Corner/state_machines/sm_review_safety_deficiency_supersedes_assessment
        """
        ctx = setup_executed_sequence(name="Def", hazard_class="FIGHT", risk_category="LOW")
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        pinned_assessment = ctx["sequence"]["current_assessment_id"]
        review = validate_success(api.create_review(create_review_payload(prod_id, seq_id), SAFETY), 201)
        validate_success(
            api.close_review(review["id"], {"outcome": "SAFETY_DEFICIENCY", "findings": "spotter lanyard unrated"},
                             SAFETY)
        )
        ra = validate_success(api.get_risk_assessment(pinned_assessment, SAFETY))
        assert ra["status"] == "SUPERSEDED"
        seq = validate_success(api.get_sequence(seq_id, SAFETY))
        assert seq["status"] == "DESIGN_LOCKED"
        assert seq["current_assessment_id"] is None
        resp = api.lock_design(seq_id, COORD)
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_INVALID_STATE)
