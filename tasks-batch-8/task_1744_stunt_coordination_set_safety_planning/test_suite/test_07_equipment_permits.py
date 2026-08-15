"""Equipment, inspections, and permits: the quarantine cascade, inspection
currency boundary, permit adjudication states, and the readiness permit gate
(PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    EXEC,
    INSPECTOR,
    SAFETY,
    create_inspection_payload,
    create_permit_payload,
    create_production,
    hold_safety_meeting,
    schedule_rehearsal,
    set_clock,
    setup_locked_with_rehearsals,
    setup_ready_sequence,
    validate_error,
    validate_success,
)

RIGGING_SPEC = {
    "name": "Descender rig",
    "equipment_type": "RIGGING",
    "serial_number": "RG-001",
    "inspection_interval_hours": 72,
}


class TestQuarantineCascade:
    """Inspection(FAILED) -> QUARANTINED -> dependent READY sequence held ->
    its SCHEDULED rehearsals cancelled (PRD §3.5, §2.8)."""

    def _setup_ready_requiring_equipment(self, api):
        ctx = setup_ready_sequence(
            name="Rig", hazard_class="FIGHT", risk_category="LOW",
            equipment_specs=[dict(RIGGING_SPEC)],
        )
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        perf_id = ctx["performer"]["id"]
        # A post-readiness rehearsal that the hold must cancel.
        extra = schedule_rehearsal(prod_id, seq_id, perf_id,
                                   start="2026-08-04T10:00:00Z", end="2026-08-04T11:00:00Z")
        return ctx, ctx["equipment"][0], extra

    def test_failed_inspection_quarantines_equipment(self, api):
        """PRD §3.5: "`FAILED` does not update `last_passed_inspection_at` at
        all; instead it moves an `IN_SERVICE` item to `QUARANTINED`."

        Design: Difficulty/transitive_cascade/tc_inspection_quarantine_cascade
        """
        _, eq, _ = self._setup_ready_requiring_equipment(api)
        insp = validate_success(
            api.create_inspection(create_inspection_payload(eq["id"], outcome="FAILED", notes="frayed cable"),
                                  INSPECTOR),
            201,
        )
        assert insp["outcome"] == "FAILED"
        assert insp["inspected_at"], "inspected_at is stamped with the logical clock"
        eq_read = validate_success(api.get_equipment(eq["id"], SAFETY))
        assert eq_read["status"] == "QUARANTINED"

    def test_quarantine_holds_sequence_and_cancels_rehearsal(self, api):
        """PRD §3.5: "Quarantine is a cascade source per §2.8: every `READY`
        sequence whose `required_equipment_ids` contains the failed item drops
        to `SAFETY_HOLD`, and each such sequence's `SCHEDULED` rehearsals are
        cancelled."

        Design: Difficulty/transitive_cascade/tc_inspection_quarantine_cascade
        """
        ctx, eq, extra = self._setup_ready_requiring_equipment(api)
        assert ctx["sequence"]["status"] == "READY"
        validate_success(
            api.create_inspection(create_inspection_payload(eq["id"], outcome="FAILED", notes="frayed cable"),
                                  INSPECTOR),
            201,
        )
        seq_read = validate_success(api.get_sequence(ctx["sequence"]["id"], SAFETY))
        assert seq_read["status"] == "SAFETY_HOLD", "hold is caused by the quarantine"
        reh_read = validate_success(api.get_rehearsal(extra["id"], SAFETY))
        assert reh_read["status"] == "CANCELLED", "cancellation is caused by the sequence hold"


class TestInspectionCurrencyBoundary:
    def test_exact_interval_elapsed_is_stale(self, api):
        """PRD §3.5: "`inspection_current` is true exactly when that timestamp
        exists and the moment `inspection_interval_hours` hours after it is
        still strictly in the future; at the exact instant the interval elapses,
        the inspection is already stale."
        PRD §3.6: "Equipment readiness: every element of `required_equipment_ids`
        must reference an item in `IN_SERVICE` status whose `inspection_current`
        is true; a quarantined, retired, never-inspected, or stale-inspected
        item fails with `ERR_EQUIPMENT_NOT_READY`."

        Design: Corner/calculations/calc_inspection_staleness_equality
        """
        ctx = setup_locked_with_rehearsals(
            name="Stale", hazard_class="FIGHT", risk_category="LOW",
            equipment_specs=[dict(RIGGING_SPEC)],
        )
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        eq = ctx["equipment"][0]
        # The baseline PASSED inspection was recorded at the startup default
        # 2026-08-01T00:00:00Z; interval 72h elapses exactly at 2026-08-04T00:00:00Z.
        hold_safety_meeting(prod_id, seq_id)
        set_clock("2026-08-04T00:00:00Z")
        resp = api.mark_ready(seq_id, COORD)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_READY)
        # A fresh PASSED inspection at that instant restores currency.
        validate_success(
            api.create_inspection(create_inspection_payload(eq["id"], outcome="PASSED", notes="re-inspection"),
                                  INSPECTOR),
            201,
        )
        ready = validate_success(api.mark_ready(seq_id, COORD))
        assert ready["status"] == "READY"


class TestPermitStates:
    def test_grant_denied_permit_rejected(self, api):
        """PRD §3.5: "A `ProductionExecutive` grants (`APPLIED → GRANTED`) or
        denies (`APPLIED → DENIED`) the application, and either adjudication
        from any other state is rejected with `ERR_PERMIT_INVALID_STATE`."

        Design: Corner/state_machines/sm_permit_grant_denied_rejected
        """
        prod = create_production(name="P", budget=5000000)
        permit = validate_success(api.create_permit(create_permit_payload(prod["id"]), EXEC), 201)
        denied = validate_success(api.deny_permit(permit["id"], EXEC))
        assert denied["status"] == "DENIED"
        resp = api.grant_permit(permit["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE)


class TestReadinessPermitGate:
    def test_pyro_sequence_without_any_permit_rejected(self, api):
        """PRD §3.6: "Permit coverage: for each permit type required of the
        sequence — derived from its `hazard_class` together with the
        `equipment_type` of its required equipment — there must exist a
        `GRANTED` permit of this production whose validity window covers the
        scheduled execution: `valid_from` at or before
        `scheduled_execution_start` and `valid_until` at or after
        `scheduled_execution_end`, else `ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH`."

        Design: Corner/errors/err_permit_missing_at_readiness
        """
        # PYRO hazard, no permits of any type exist for the production.
        ctx = setup_locked_with_rehearsals(
            name="Pyro NoPermit", hazard_class="PYRO", risk_category="LOW",
            severity=2, likelihood=2, discipline="PYRO",
        )
        hold_safety_meeting(ctx["production"]["id"], ctx["sequence"]["id"])
        resp = api.mark_ready(ctx["sequence"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_PERMIT_MISSING_OR_WINDOW_MISMATCH)
