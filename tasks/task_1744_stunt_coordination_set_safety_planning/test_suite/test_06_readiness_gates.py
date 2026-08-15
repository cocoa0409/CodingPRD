"""The mark-ready readiness gate: rehearsal quota boundary, medic standby,
insurance acknowledgement, and the lock-design quota/medic computation
(PRD §3.2, §3.6)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    create_approved_assessment,
    create_equipment,
    create_production,
    create_sequence,
    hold_safety_meeting,
    lock_design,
    schedule_rehearsal,
    set_clock,
    setup_locked_with_rehearsals,
    validate_error,
    validate_success,
)


class TestRehearsalQuotaBoundary:
    """HIGH category -> base quota 3; the gate passes at exact equality."""

    def _setup_high_sequence_with_rehearsals(self, api):
        ctx = setup_locked_with_rehearsals(
            name="Quota", hazard_class="FIGHT", risk_category="HIGH",
            severity=3, likelihood=4, acknowledge=True, rehearsals_completed=0,
        )
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        perf_id = ctx["performer"]["id"]
        assert ctx["sequence"]["required_rehearsal_count"] == 3, "HIGH base quota, no special equipment"
        # Three adjacent one-hour bookings; clock moved past all starts.
        r1 = schedule_rehearsal(prod_id, seq_id, perf_id, start="2026-08-02T09:00:00Z", end="2026-08-02T10:00:00Z")
        r2 = schedule_rehearsal(prod_id, seq_id, perf_id, start="2026-08-02T10:00:00Z", end="2026-08-02T11:00:00Z")
        r3 = schedule_rehearsal(prod_id, seq_id, perf_id, start="2026-08-02T11:00:00Z", end="2026-08-02T12:00:00Z")
        set_clock("2026-08-02T12:30:00Z")
        for r in (r1, r2):
            validate_success(api.complete_rehearsal(r["id"], COORD))
        return ctx, r3

    def test_quota_shortfall_rejected(self, api):
        """PRD §3.6: "Rehearsal quota: the sequence's `completed_rehearsal_count`
        must be at least its `required_rehearsal_count`, with exact equality
        passing, else `ERR_REHEARSAL_QUOTA_NOT_MET`."

        Design: Difficulty/boundary_precision_check/bp_rehearsal_quota_exact_equality
        """
        ctx, _ = self._setup_high_sequence_with_rehearsals(api)
        assert validate_success(api.get_sequence(ctx["sequence"]["id"], COORD))["completed_rehearsal_count"] == 2
        resp = api.mark_ready(ctx["sequence"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_REHEARSAL_QUOTA_NOT_MET)

    def test_quota_exact_equality_passes(self, api):
        """PRD §3.6: "Rehearsal quota: the sequence's `completed_rehearsal_count`
        must be at least its `required_rehearsal_count`, with exact equality
        passing, else `ERR_REHEARSAL_QUOTA_NOT_MET`."

        Design: Difficulty/boundary_precision_check/bp_rehearsal_quota_exact_equality
        """
        ctx, r3 = self._setup_high_sequence_with_rehearsals(api)
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        validate_error(api.mark_ready(seq_id, COORD), ApiErrorId.ERR_REHEARSAL_QUOTA_NOT_MET)
        validate_success(api.complete_rehearsal(r3["id"], COORD))
        # HIGH category -> medic standby is required, so the meeting's fan-out
        # includes MEDIC; every signoff is signed.
        hold_safety_meeting(prod_id, seq_id)
        ready = validate_success(api.mark_ready(seq_id, COORD))
        assert ready["status"] == "READY"
        assert ready["completed_rehearsal_count"] == 3, "count 3 == quota 3 passes at equality"


class TestInsuranceAcknowledgementGate:
    def test_high_risk_requires_acknowledged_insurance(self, api):
        """PRD §3.6: "Insurance acknowledgement: when the sequence's
        `risk_category` is `HIGH` or `CRITICAL`, the production's
        `insurance_status` must be `ACKNOWLEDGED`, else
        `ERR_INSURANCE_NOT_ACKNOWLEDGED`."

        Design: Corner/errors/err_insurance_not_acknowledged_rejected
        """
        # Insurance FILED (activation-legal) but never ACKNOWLEDGED.
        ctx = setup_locked_with_rehearsals(
            name="Ins", hazard_class="FIGHT", risk_category="HIGH",
            severity=3, likelihood=4, acknowledge=False,
        )
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        hold_safety_meeting(prod_id, seq_id)
        resp = api.mark_ready(seq_id, COORD)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_ACKNOWLEDGED)


class TestMedicStandbyGate:
    def test_medic_refusal_blocks_readiness_with_own_error(self, api):
        """PRD §3.6: "Medic standby: when `medic_standby_required` is true, the
        qualifying completed meeting — the one the next gate looks for — must
        have its `MEDIC` signoff in `SIGNED` or `SIGNED_WITH_CONDITIONS`, else
        `ERR_MEDIC_STANDBY_NOT_CONFIRMED`. This check is deliberately evaluated
        before the meeting-satisfaction gate, so a missing medic confirmation
        surfaces as its own error rather than being masked by the broader
        meeting failure."

        Design: Corner/errors/err_medic_not_confirmed_rejected
        """
        ctx = setup_locked_with_rehearsals(
            name="Medic", hazard_class="FIGHT", risk_category="HIGH",
            severity=3, likelihood=4, acknowledge=True,
        )
        prod_id = ctx["production"]["id"]
        seq_id = ctx["sequence"]["id"]
        meeting, decisions = hold_safety_meeting(prod_id, seq_id, refuse_departments=("MEDIC",))
        assert meeting["status"] == "COMPLETED", "all signoffs decided; MEDIC refused"
        assert decisions["MEDIC"] == "REFUSED"
        resp = api.mark_ready(seq_id, COORD)
        validate_error(resp, ApiErrorId.ERR_MEDIC_STANDBY_NOT_CONFIRMED)


class TestLockDesignComputations:
    def test_special_equipment_quota_adder_and_medic_flag(self, api):
        """PRD §3.2: "`required_rehearsal_count` is the category quota — 1 for
        `LOW`, 2 for `MEDIUM`, 3 for `HIGH`, 4 for `CRITICAL` — plus one
        additional rehearsal when any element of `required_equipment_ids` has
        `equipment_type` `PYRO_DEVICE` or `CRANE`. `medic_standby_required` is
        true exactly when the `risk_category` is `HIGH` or `CRITICAL` or the
        `hazard_class` is `FIRE`, `PYRO`, `VEHICLE`, or `WATER`."
        PRD §3.2: "plus a hazard weight of 6 for `PYRO`, 5 for `FIRE`, 4 each
        for `HEIGHT`, `VEHICLE`, and `AERIAL`, 3 for `WATER`, and 2 for
        `FIGHT`, minus a mitigation credit of 3 when `mitigation_notes` is
        non-empty."

        Design: Corner/calculations/calc_special_equipment_quota_adder
        """
        prod = create_production(name="P", budget=10000000)
        eq = create_equipment(prod["id"], name="Squib rig", equipment_type="PYRO_DEVICE", serial_number="PX-1",
                              inspection_interval_hours=48)
        seq = create_sequence(prod["id"], name="Adder Seq", hazard_class="VEHICLE", risk_category="HIGH",
                              equipment_ids=[eq["id"]])
        create_approved_assessment(prod["id"], seq["id"], 3, 4, mitigation_notes="roll cage")
        locked = lock_design(seq["id"])
        assert locked["required_rehearsal_count"] == 4, "HIGH base 3 + 1 for PYRO_DEVICE"
        assert locked["medic_standby_required"] is True, "VEHICLE hazard class requires medic standby"
        assert locked["board_score"] == 13, "3x4 + 4 (VEHICLE) - 3 (mitigation) = 13"
