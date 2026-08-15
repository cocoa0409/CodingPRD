"""Layered audit escalation, the heat-lot quarantine cascade, and validation
pipeline ordering between state and quality gates (PRD §2.5, §3.7, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_audit,
    create_press,
    get_coil,
    get_order,
    get_press,
    get_run,
    get_success_data,
    make_qe_dispositioner_headers,
    record_audit,
    record_tier3_fail,
    setup_completed_run,
    setup_running_run,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuditEscalation:
    def test_tier1_fail_creates_tier2_audit(self, api, quality_engineer_headers):
        """PRD §3.9: "When an audit at tier 1 or tier 2 fails, the system automatically creates a new layered audit for the same press at the next tier up, with `escalated_from_id` pointing back to the failed audit."
        PRD §3.9: "The audit's `result` starts `PENDING`, its `findings_count` starts 0, and its `escalated_from_id` is null for a normally scheduled audit."

        Design: Corner/state_machines/audit_fail_escalates_tier1_to_tier2
        """
        press = create_press(press_code="PR-ESC")
        audit1 = create_audit(press["id"], audit_tier=1)
        recorded = record_audit(audit1["id"], "FAIL", 2)
        assert recorded["result"] == "FAIL"

        rows, _meta = validate_paginated(
            api.list_press_layered_audits(
                press["id"], quality_engineer_headers, params={"audit_tier": 2}
            )
        )
        assert len(rows) == 1, f"exactly one tier-2 escalation audit must exist, got {len(rows)}"
        assert rows[0]["escalated_from_id"] == audit1["id"]
        assert rows[0]["result"] == "PENDING"
        assert rows[0]["press_id"] == press["id"]

    def test_fail_without_findings_rejected(self, api, quality_engineer_headers):
        """PRD §3.9: "A `FAIL` recorded with fewer than 1 finding is rejected with `ERR_AUDIT_FINDINGS_REQUIRED` (422)."

        Design: Corner/validations/audit_fail_without_findings_rejected
        """
        press = create_press(press_code="PR-FND")
        audit = create_audit(press["id"], audit_tier=1)
        resp = api.record_layered_audit(
            audit["id"], {"result": "FAIL", "findings_count": 0},
            make_qe_dispositioner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_FINDINGS_REQUIRED)
        after = validate_success(api.get_layered_audit(audit["id"], quality_engineer_headers))
        assert after["result"] == "PENDING"


class TestQuarantineCascade:
    def test_tier3_fail_quarantines_coil_and_aborts_run(self, api, quality_engineer_headers):
        """PRD §3.9: "Every steel coil whose `heat_lot_number` was consumed by runs on that press — runs in `COMPLETED` or `RUNNING` status within the audit window — and which still stands `APPROVED` transitions to `QUARANTINED`; the quarantine applies lot-wide, to every `APPROVED` coil sharing an implicated `heat_lot_number`, not merely the coils physically consumed on that press."
        PRD §3.9: "From there the damage propagates through the schedule: every `SCHEDULED` production run referencing a quarantined coil is aborted; every `RUNNING` run referencing one is aborted with its `good_count` preserved; and the parent order of each aborted run, if it stood `IN_PROGRESS`, reverts to `RELEASED`."

        Design: Difficulty/transitive_cascade/heat_lot_quarantine_cascade_depth4
        """
        ctx = setup_running_run(quantity_ordered=100, coil_weight_kg=1000,
                                heat_lot_number="HL-Z")
        audit = record_tier3_fail(ctx["press"]["id"], findings_count=3,
                                  scheduled_date="2026-08-01T09:00:00Z")
        assert audit["result"] == "FAIL"
        coil_after = get_coil(ctx["coil"]["id"])
        assert coil_after["status"] == "QUARANTINED", "hop 2: the implicated coil quarantines"
        run_after = get_run(ctx["run"]["id"])
        assert run_after["status"] == "ABORTED", "hop 3: the RUNNING run on the coil aborts"

    def test_cascade_reverts_order_and_frees_press(self, api):
        """PRD §3.9: "From there the damage propagates through the schedule: every `SCHEDULED` production run referencing a quarantined coil is aborted; every `RUNNING` run referencing one is aborted with its `good_count` preserved; and the parent order of each aborted run, if it stood `IN_PROGRESS`, reverts to `RELEASED`."
        PRD §3.7: "Aborting a `RUNNING` run — whether by operator action or by a system cascade such as the die-repair pull or the heat-lot quarantine — returns the press to `IDLE`, preserves the `good_count` counted so far, and deliberately does not decrement the coil for steel consumed up to that point (scrap-in-place, per §2.9); if no other run of the same order then remains `SCHEDULED` or `RUNNING`, the order reverts from `IN_PROGRESS` to `RELEASED`."

        Design: Difficulty/transitive_cascade/heat_lot_quarantine_cascade_depth4
        """
        ctx = setup_running_run(quantity_ordered=100, coil_weight_kg=1000,
                                heat_lot_number="HL-Z2")
        record_tier3_fail(ctx["press"]["id"], findings_count=3,
                          scheduled_date="2026-08-01T09:00:00Z")
        order_after = get_order(ctx["order"]["id"])
        assert order_after["status"] == "RELEASED", (
            "hop 4: with no run left active the order reverts IN_PROGRESS -> RELEASED"
        )
        press_after = get_press(ctx["press"]["id"])
        assert press_after["status"] == "IDLE", "the abort returns the press to IDLE"

    def test_order_reverts_to_released_after_cascade(self, api, quality_engineer_headers):
        """PRD §3.5: "an `IN_PROGRESS` order that loses all active runs — every one aborted, none left `SCHEDULED` or `RUNNING` — reverts automatically to `RELEASED`."
        PRD §3.9: "From there the damage propagates through the schedule: every `SCHEDULED` production run referencing a quarantined coil is aborted; every `RUNNING` run referencing one is aborted with its `good_count` preserved; and the parent order of each aborted run, if it stood `IN_PROGRESS`, reverts to `RELEASED`."

        Design: Difficulty/non_linear_state_machine/production_order_in_progress_revert_cycle
        """
        ctx = setup_running_run(quantity_ordered=100, coil_weight_kg=1000,
                                heat_lot_number="HL-Q")
        assert get_order(ctx["order"]["id"])["status"] == "IN_PROGRESS"
        record_tier3_fail(ctx["press"]["id"], findings_count=2,
                          scheduled_date="2026-08-01T09:00:00Z")
        assert get_coil(ctx["coil"]["id"])["status"] == "QUARANTINED"
        assert get_run(ctx["run"]["id"])["status"] == "ABORTED"
        assert get_order(ctx["order"]["id"])["status"] == "RELEASED", (
            "cyclic revert: IN_PROGRESS -> RELEASED when the cascade kills the last active run"
        )

    def test_tier3_fail_creates_no_tier4_escalation(self, api, quality_engineer_headers):
        """PRD §3.9: "There is no tier above 3, so a tier-3 failure escalates differently: it detonates the heat-lot quarantine cascade."

        Design: Difficulty/non_linear_state_machine/production_order_in_progress_revert_cycle
        """
        ctx = setup_running_run(quantity_ordered=100, coil_weight_kg=1000,
                                heat_lot_number="HL-Q4")
        audit = record_tier3_fail(ctx["press"]["id"], findings_count=2,
                                  scheduled_date="2026-08-01T09:00:00Z")
        assert audit["result"] == "FAIL"
        rows, _meta = validate_paginated(
            api.list_layered_audits(
                quality_engineer_headers,
                params={"escalated_from_id": audit["id"]},
            )
        )
        assert rows == [], "tier 3 is the ceiling: no tier-4 escalation audit may be created"


class TestStateBeatsQualityGate:
    def _setup_completed_then_quarantined(self):
        """A COMPLETED run on a press whose coil heat lot is then implicated by a
        tier-3 audit FAIL."""
        ctx = setup_completed_run(shots_recorded=10, quantity_ordered=10,
                                  coil_weight_kg=1000, heat_lot_number="HL-T")
        record_tier3_fail(ctx["press"]["id"], findings_count=1,
                          scheduled_date="2026-08-01T10:00:00Z")
        return ctx

    def test_start_of_completed_run_reports_invalid_state(self, api, press_operator_headers):
        """PRD §2.5: "When several checks could reject the same request, the server evaluates them in a single, fixed pipeline order, and the first failing check determines the response."
        PRD §2.5: "4. **State-machine precondition.** The target resource's current state permits the requested action — a run must be `RUNNING` to complete, a coil must be `APPROVED` to feed a run start, and so on through every state machine in §3. Failure: `ERR_INVALID_STATE` (409)."
        PRD §2.5: "5. **Quality and compliance gates.** A quarantined coil blocks any run start; a die at or beyond its repair threshold blocks scheduling; and the compliance character of PPAP approval and audit recording is enforced at this tier. These gates guard run start, die-change start, die scheduling, PPAP approval, and audit recording. Failure: `ERR_QUALITY_HOLD` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_run_start
        """
        ctx = self._setup_completed_then_quarantined()
        resp = api.start_production_run(ctx["run"]["id"], press_operator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_start_leaves_run_and_press_untouched(self, api, press_operator_headers):
        """PRD §2.5: "When several checks could reject the same request, the server evaluates them in a single, fixed pipeline order, and the first failing check determines the response."
        PRD §2.5: "4. **State-machine precondition.** The target resource's current state permits the requested action — a run must be `RUNNING` to complete, a coil must be `APPROVED` to feed a run start, and so on through every state machine in §3. Failure: `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_run_start
        """
        ctx = self._setup_completed_then_quarantined()
        resp = api.start_production_run(ctx["run"]["id"], press_operator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_run(ctx["run"]["id"])["status"] == "COMPLETED"
        assert get_press(ctx["press"]["id"])["status"] == "IDLE"
