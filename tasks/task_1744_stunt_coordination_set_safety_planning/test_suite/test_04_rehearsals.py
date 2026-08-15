"""Rehearsal scheduling: cross-entity sequence gating, performer overlap
semantics, clock gates, posture gates, validation ordering, and the
completed-minutes invariant with its void compensation (PRD §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    SAFETY,
    create_active_production,
    create_certification,
    create_locked_sequence,
    create_performer,
    create_production,
    create_qualified_performer,
    create_rehearsal_payload,
    create_sequence,
    schedule_rehearsal,
    set_clock,
    stop_production,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCrossEntitySequenceGate:
    """Rehearsal creation gated on the sequence's state (PRD §3.3)."""

    def _setup(self, api):
        prod = create_active_production(name="XDep Prod", budget=10000000)
        seq = create_sequence(prod["id"], name="XDep Seq", hazard_class="FIGHT", risk_category="LOW")
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT")
        return prod, seq, perf

    def test_rehearsal_rejected_while_sequence_draft(self, api):
        """PRD §3.3: "Scheduling one requires posture `ACTIVE` and not
        `STOPPED`, the sequence in `DESIGN_LOCKED` or `READY`
        (`ERR_SEQUENCE_INVALID_STATE` otherwise)"

        Design: Difficulty/cross_entity_state_dependency/xdep_rehearsal_requires_locked_sequence
        """
        prod, seq, perf = self._setup(api)
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-02T10:00:00Z", scheduled_end="2026-08-02T11:00:00Z",
        )
        resp = api.create_rehearsal(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_INVALID_STATE)

    def test_rehearsal_allowed_after_lock(self, api):
        """PRD §3.3: "Scheduling one requires posture `ACTIVE` and not
        `STOPPED`, the sequence in `DESIGN_LOCKED` or `READY`
        (`ERR_SEQUENCE_INVALID_STATE` otherwise)" and "A new rehearsal starts
        `SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/xdep_rehearsal_requires_locked_sequence
        """
        prod, seq, perf = self._setup(api)
        # Lock the design (approved assessment inside) and retry the same booking.
        from test_helpers import create_approved_assessment, lock_design
        create_approved_assessment(prod["id"], seq["id"], 2, 2)
        lock_design(seq["id"])
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-02T10:00:00Z", scheduled_end="2026-08-02T11:00:00Z",
        )
        data = validate_success(api.create_rehearsal(payload, COORD), 201)
        assert data["status"] == "SCHEDULED"


class TestPerformerOverlapHalfOpen:
    def _setup(self, api):
        prod = create_active_production(name="Overlap Prod", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="Ov Seq", hazard_class="FIGHT", risk_category="LOW")
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT")
        first = schedule_rehearsal(prod["id"], seq["id"], perf["id"],
                                   start="2026-08-02T10:00:00Z", end="2026-08-02T11:00:00Z")
        return prod, seq, perf, first

    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "across all sequences of the production, the performer must
        have no existing rehearsal in `SCHEDULED` or `COMPLETED` whose window
        overlaps the new one, where two windows overlap exactly when the new
        start falls before the existing end and the existing start falls before
        the new end; touching windows — one beginning precisely when the other
        ends — are allowed. A violation is rejected with
        `ERR_REHEARSAL_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/ro_rehearsal_performer_half_open
        """
        prod, seq, perf, _ = self._setup(api)
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-02T10:30:00Z", scheduled_end="2026-08-02T11:30:00Z",
        )
        resp = api.create_rehearsal(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_REHEARSAL_CONFLICT)

    def test_exact_adjacency_allowed(self, api):
        """PRD §3.3: "touching windows — one beginning precisely when the other
        ends — are allowed."

        Design: Difficulty/resource_temporal_overlap/ro_rehearsal_performer_half_open
        """
        prod, seq, perf, _ = self._setup(api)
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-02T11:00:00Z", scheduled_end="2026-08-02T12:00:00Z",
        )
        data = validate_success(api.create_rehearsal(payload, COORD), 201)
        assert data["status"] == "SCHEDULED", "11:00 == existing end is allowed (half-open)"


class TestClockGates:
    def test_rehearsal_in_past_rejected(self, api):
        """PRD §3.3: "The start must lie strictly in the future of the logical
        clock (`ERR_REHEARSAL_IN_PAST`)"

        Design: Corner/validations/val_rehearsal_in_past_rejected
        """
        prod = create_active_production(name="P", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="Past Seq", hazard_class="FIGHT", risk_category="LOW")
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT")
        # The logical clock is at the startup default 2026-08-01T00:00:00Z.
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-07-31T10:00:00Z", scheduled_end="2026-07-31T11:00:00Z",
        )
        resp = api.create_rehearsal(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_REHEARSAL_IN_PAST)

    def test_complete_and_missed_time_gates(self, api):
        """PRD §3.3: "Completing a rehearsal (the owner coordinator of the
        sequence; `SCHEDULED → COMPLETED`) may not occur before
        `scheduled_start`: completion at or after the start is permitted, and an
        earlier attempt is rejected with `ERR_REHEARSAL_TIME_GATE`." and
        "Marking a rehearsal missed (owner coordinator) moves `SCHEDULED →
        MISSED` and requires the logical clock to be strictly past
        `scheduled_end`; marking at or before the end is rejected with
        `ERR_REHEARSAL_TIME_GATE`"

        Design: Corner/validations/val_rehearsal_time_gates
        """
        prod = create_active_production(name="P", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="Gate Seq", hazard_class="FIGHT", risk_category="LOW")
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT")
        reh = schedule_rehearsal(prod["id"], seq["id"], perf["id"],
                                 start="2026-08-02T10:00:00Z", end="2026-08-02T11:00:00Z")
        set_clock("2026-08-02T09:00:00Z")
        resp_complete = api.complete_rehearsal(reh["id"], COORD)
        validate_error(resp_complete, ApiErrorId.ERR_REHEARSAL_TIME_GATE)
        resp_missed = api.mark_rehearsal_missed(reh["id"], COORD)
        validate_error(resp_missed, ApiErrorId.ERR_REHEARSAL_TIME_GATE)


class TestPostureGate:
    def test_rehearsal_in_setup_posture_rejected(self, api):
        """PRD §2.7: "Rehearsal scheduling, completion, missed-marking,
        cancellation, and voiding; safety-meeting scheduling, starting,
        completing, and adjourning; signoff signing and refusal; inspection
        recording; take attempts, completions, and aborts; marking ready and
        reverifying readiness; and review opening and closing require `ACTIVE`
        and are blocked while `STOPPED` (`ERR_PRODUCTION_STOPPED`) or in any
        other non-`ACTIVE` posture (`ERR_PRODUCTION_NOT_ACTIVE`)."

        Design: Corner/errors/err_rehearsal_setup_posture_rejected
        """
        # Production stays in SETUP; design work is allowed there, operational
        # endpoints are not.
        prod = create_production(name="P", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="Setup Seq", hazard_class="FIGHT", risk_category="LOW")
        assert seq["status"] == "DESIGN_LOCKED", "design lock is allowed in SETUP"
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT")
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-02T10:00:00Z", scheduled_end="2026-08-02T11:00:00Z",
        )
        resp = api.create_rehearsal(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_ACTIVE)


class TestValidationPriorityPairs:
    def test_stopped_posture_beats_certification(self, api):
        """PRD §2.7: "Requests that are structurally sound are then evaluated
        against the domain rule tiers below, in this order; the first failing
        tier determines the rejection." with the posture gate at tier 5
        ("blocked while `STOPPED` (`ERR_PRODUCTION_STOPPED`)") ahead of the
        certification discipline check at tier 7
        (`ERR_CERTIFICATION_MISSING_OR_EXPIRED`).

        Design: Difficulty/priority_pair_validation_conflict/pp_state_vs_safety_on_rehearsal_create
        """
        prod = create_active_production(name="Prio A Prod", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="Prio Seq", hazard_class="FIGHT", risk_category="LOW")
        # Performer with NO certifications: would fail the tier-7 safety check.
        perf = create_performer(prod["id"], first_name="Guy", last_name="Sev")
        stop_production(prod["id"], reason="weather")
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-04T10:00:00Z", scheduled_end="2026-08-04T11:00:00Z",
        )
        resp = api.create_rehearsal(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_STOPPED)

    def test_stopped_posture_first_tier_creates_nothing(self, api):
        """PRD §2.7: "Requests that are structurally sound are then evaluated
        against the domain rule tiers below, in this order; the first failing
        tier determines the rejection." — the tier-5 posture rejection
        (`ERR_PRODUCTION_STOPPED`) pre-empts every later tier, so no rehearsal
        is recorded.

        Design: Difficulty/priority_pair_validation_conflict/pp_state_vs_safety_on_rehearsal_create
        """
        prod = create_active_production(name="Prio A Prod", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="Prio Seq", hazard_class="FIGHT", risk_category="LOW")
        perf = create_performer(prod["id"], first_name="Guy", last_name="Sev")
        stop_production(prod["id"], reason="weather")
        payload = create_rehearsal_payload(
            prod["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-04T10:00:00Z", scheduled_end="2026-08-04T11:00:00Z",
        )
        validate_error(api.create_rehearsal(payload, COORD), ApiErrorId.ERR_PRODUCTION_STOPPED)
        items, meta = validate_paginated(api.list_rehearsals(COORD, params={"production_id": prod["id"]}))
        assert meta["total_count"] == 0 and items == [], "rejected create must not record a rehearsal"

    def test_certification_beats_cross_production(self, api):
        """PRD §2.7: "Requests that are structurally sound are then evaluated
        against the domain rule tiers below, in this order; the first failing
        tier determines the rejection." with the certification check at tier 7
        (`ERR_CERTIFICATION_MISSING_OR_EXPIRED`) ahead of cross-production
        referential integrity at tier 11 (`ERR_CROSS_PRODUCTION_REFERENCE`).

        Design: Difficulty/priority_pair_validation_conflict/pp_safety_vs_referential_on_rehearsal_create
        """
        p1 = create_active_production(name="P1 Safety", budget=10000000)
        p2 = create_production(name="P2 Safety", budget=10000000)
        seq = create_locked_sequence(p1["id"], name="P1 Seq", hazard_class="FIGHT", risk_category="LOW")
        # Performer belongs to P2 AND holds only a HEIGHT certification (the
        # sequence is FIGHT): both tier 7 and tier 11 are violated.
        perf = create_performer(p2["id"], first_name="Ivy", last_name="Nin")
        create_certification(perf["id"], discipline="HEIGHT", level="BASIC")
        payload = create_rehearsal_payload(
            p1["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-04T10:00:00Z", scheduled_end="2026-08-04T11:00:00Z",
        )
        resp = api.create_rehearsal(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING_OR_EXPIRED)

    def test_certification_first_tier_creates_nothing(self, api):
        """PRD §2.7: "Requests that are structurally sound are then evaluated
        against the domain rule tiers below, in this order; the first failing
        tier determines the rejection." — the tier-7 certification rejection
        (`ERR_CERTIFICATION_MISSING_OR_EXPIRED`) pre-empts the tier-11
        referential check, so no rehearsal is recorded for either production.

        Design: Difficulty/priority_pair_validation_conflict/pp_safety_vs_referential_on_rehearsal_create
        """
        p1 = create_active_production(name="P1 Safety", budget=10000000)
        p2 = create_production(name="P2 Safety", budget=10000000)
        seq = create_locked_sequence(p1["id"], name="P1 Seq", hazard_class="FIGHT", risk_category="LOW")
        perf = create_performer(p2["id"], first_name="Ivy", last_name="Nin")
        create_certification(perf["id"], discipline="HEIGHT", level="BASIC")
        payload = create_rehearsal_payload(
            p1["id"], seq["id"], perf["id"],
            scheduled_start="2026-08-04T10:00:00Z", scheduled_end="2026-08-04T11:00:00Z",
        )
        validate_error(api.create_rehearsal(payload, COORD), ApiErrorId.ERR_CERTIFICATION_MISSING_OR_EXPIRED)
        _, meta1 = validate_paginated(api.list_rehearsals(COORD, params={"production_id": p1["id"]}))
        _, meta2 = validate_paginated(api.list_rehearsals(COORD, params={"production_id": p2["id"]}))
        assert meta1["total_count"] == 0 and meta2["total_count"] == 0


class TestRehearsalMinutesInvariant:
    """Invariant I2: completed rehearsal counters on the sequence and the
    performer track the COMPLETED rehearsals exactly (PRD §3.3)."""

    def _setup_completed_rehearsal(self, api):
        prod = create_active_production(name="Time Prod", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="Time Seq", hazard_class="FIGHT", risk_category="LOW")
        perf, _ = create_qualified_performer(prod["id"], discipline="FIGHT")
        reh = schedule_rehearsal(prod["id"], seq["id"], perf["id"],
                                 start="2026-08-02T10:00:00Z", end="2026-08-02T11:30:00Z")
        set_clock("2026-08-02T10:30:00Z")
        completed = validate_success(api.complete_rehearsal(reh["id"], COORD))
        return prod, seq, perf, completed

    def test_completion_feeds_sequence_and_performer_counters(self, api):
        """PRD §3.3: "Each completion feeds invariant I2: the sequence's
        `completed_rehearsal_count` increments by one, the sequence's
        `completed_rehearsal_minutes` grows by `duration_minutes`, and the
        performer's `completed_rehearsal_minutes` grows by the same amount."

        Design: Difficulty/compensating_invariant/ci_rehearsal_minutes_conservation
        """
        prod, seq, perf, completed = self._setup_completed_rehearsal(api)
        assert completed["status"] == "COMPLETED"
        assert completed["duration_minutes"] == 90
        seq_read = validate_success(api.get_sequence(seq["id"], COORD))
        assert seq_read["completed_rehearsal_count"] == 1
        assert seq_read["completed_rehearsal_minutes"] == 90
        perf_read = validate_success(api.get_performer(perf["id"], COORD))
        assert perf_read["completed_rehearsal_minutes"] == 90

    def test_void_completion_compensates_counters(self, api):
        """PRD §3.3: "A `SafetyOfficer` may void a `COMPLETED` rehearsal — from
        any other state, `ERR_REHEARSAL_INVALID_STATE` — recording the supplied
        `reason` into `void_reason` and running the compensating action for
        invariant I2: the sequence's `completed_rehearsal_count` decrements by
        one and both minute counters shrink by the rehearsal's
        `duration_minutes`."

        Design: Difficulty/compensating_invariant/ci_rehearsal_minutes_conservation
        """
        prod, seq, perf, completed = self._setup_completed_rehearsal(api)
        voided = validate_success(
            api.void_rehearsal_completion(completed["id"], {"reason": "logged in error"}, SAFETY)
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "logged in error"
        seq_read = validate_success(api.get_sequence(seq["id"], COORD))
        assert seq_read["completed_rehearsal_count"] == 0
        assert seq_read["completed_rehearsal_minutes"] == 0
        perf_read = validate_success(api.get_performer(perf["id"], COORD))
        assert perf_read["completed_rehearsal_minutes"] == 0
