"""Label reconciliation verdicts and precedence, escalation to incidents,
incident lifecycle gates, and derived line posture ordering."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_allergen, create_line, create_product, create_run, schedule_run,
    create_incident_ok, drive_incident_to_contained, get_line,
    set_clock, MANAGER, SUPERVISOR, OPERATOR,
)


class TestVerdictPrecedence:
    def test_undeclared_allergen_outranks_revision_mismatch(self, api):
        """PRD §3.6: "The `verdict` is computed under a pinned precedence —
        undeclared allergens outrank everything. When `missing_allergens` is
        non-empty the verdict is `UNDECLARED_ALLERGEN`. Failing that, when
        `printed_label_revision` differs from `expected_label_revision` the
        verdict is `REVISION_MISMATCH`."
        PRD §3.6: "`missing_allergens`, the codes in the product's
        `allergen_set` that the label failed to declare".

        Design: Corner/calculations/label_reconciliation_verdict_precedence_undeclared_over_revision
        """
        allergen = create_allergen("PEANUT")
        line = create_line("LINE-C2", "ALLERGEN_DEDICATED")
        product = create_product("P-C2", ["PEANUT"], label_revision=3)
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        assert run["label_revision_snapshot"] == 3
        res = api.create_label_reconciliation(
            {"run_id": run["id"], "printed_label_revision": 2,
             "declared_allergens_on_label": []},
            SUPERVISOR)
        recon = validate_success(res, 201)
        assert recon["missing_allergens"] == ["PEANUT"]
        assert recon["verdict"] == "UNDECLARED_ALLERGEN", (
            "UNDECLARED_ALLERGEN must win over REVISION_MISMATCH")


class TestResolveGate:
    def test_non_match_reconciliation_cannot_resolve(self, api):
        """PRD §3.6: "A `QaSupervisor` may resolve it — `OPEN` → `RESOLVED` —
        only while it is `OPEN` (`ERR_RECON_NOT_OPEN`) and only when the verdict
        is `MATCH`; attempting to resolve a non-`MATCH` reconciliation directly
        is rejected with `ERR_RECON_NOT_MATCH` (HTTP 409)".

        Design: Corner/state_machines/label_reconciliation_non_match_cannot_resolve
        """
        line = create_line("LINE-S5", "ALLERGEN_DEDICATED")
        product = create_product("P-S5", [], label_revision=1)
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        res = api.create_label_reconciliation(
            {"run_id": run["id"], "printed_label_revision": 2,
             "declared_allergens_on_label": []},
            SUPERVISOR)
        recon = validate_success(res, 201)
        assert recon["verdict"] == "REVISION_MISMATCH"
        res = api.resolve_label_reconciliation(recon["id"], SUPERVISOR)
        validate_error(res, "ERR_RECON_NOT_MATCH")


class TestEscalationConsistency:
    def test_escalate_creates_critical_incident_and_holds_line(self, api):
        """PRD §3.6: "Escalation moves `OPEN` → `ESCALATED` (again requiring
        `OPEN`, failing with `ERR_RECON_NOT_OPEN`) and raises an incident
        automatically: `incident_type` `UNDECLARED_ALLERGEN` at `severity`
        `CRITICAL` when `missing_allergens` is non-empty, otherwise
        `LABEL_MISMATCH` at `severity` `HIGH`, with the incident's
        `source_label_reconciliation_id` recording the reconciliation that
        spawned it."
        PRD §3.6: "The `CRITICAL` branch bites immediately — the line's
        `posture` drops to `HOLD`, and any `IN_PROGRESS` run on the line is
        force-paused: it cannot complete until the incident reaches
        `CONTAINED`."

        Design: Corner/consistency_model/escalate_immediately_creates_incident_and_holds_line
        """
        allergen = create_allergen("PEANUT")
        line = create_line("LINE-CONS", "WET_WASH")
        product = create_product("P-CONS", ["PEANUT"])
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        recon = validate_success(
            api.create_label_reconciliation(
                {"run_id": run["id"], "printed_label_revision": 1,
                 "declared_allergens_on_label": []},
                SUPERVISOR), 201)
        escalated = validate_success(
            api.escalate_label_reconciliation(recon["id"], SUPERVISOR), 200)
        assert escalated["status"] == "ESCALATED"

        incidents, meta = validate_paginated(api.list_incidents(SUPERVISOR))
        assert meta["total_count"] == 1
        assert incidents[0]["incident_type"] == "UNDECLARED_ALLERGEN"
        assert incidents[0]["severity"] == "CRITICAL"

        line_after = get_line(line["id"])
        assert line_after["posture"] == "HOLD", (
            "The CRITICAL escalation must drop the line posture to HOLD immediately")


class TestCompleteGate:
    def test_open_reconciliation_blocks_run_completion(self, api):
        """PRD §3.4: "every label reconciliation raised for the run must either
        carry the verdict `MATCH` or stand in `RESOLVED` status — any
        reconciliation still `OPEN` blocks completion with
        `ERR_LABEL_RECONCILIATION_OPEN` (HTTP 409)".

        Design: Corner/errors/error_label_reconciliation_open_blocks_complete
        """
        line = create_line("LINE-ER4", "ALLERGEN_DEDICATED")
        product = create_product("P-ER4", [], label_revision=1)
        run = create_run(line["id"], product["id"],
                         "2026-05-01T00:00:00Z", "2026-05-01T02:00:00Z")
        run = schedule_run(run)
        # Default logical clock equals the planned start, so the run is due.
        started = validate_success(api.start_run(run["id"], OPERATOR), 200)
        assert started["status"] == "IN_PROGRESS"
        recon = validate_success(
            api.create_label_reconciliation(
                {"run_id": run["id"], "printed_label_revision": 9,
                 "declared_allergens_on_label": []},
                SUPERVISOR), 201)
        assert recon["verdict"] == "REVISION_MISMATCH"
        res = api.complete_run(run["id"], OPERATOR)
        validate_error(res, "ERR_LABEL_RECONCILIATION_OPEN")


class TestSupplierAllergenChange:
    def test_supplier_change_bumps_revision_raises_incident_and_stale_pins(self, api):
        """PRD §3.2: "the manager records the notification through the
        supplier-allergen-change flow, supplying the `new_allergen_set` and a
        `supplier_notice_ref` for traceability; the product's `allergen_set` is
        replaced and its `label_revision` is incremented by one automatically."
        PRD §3.2: "an incident of `incident_type` `SUPPLIER_ALLERGEN_CHANGE`
        with `severity` `MEDIUM` is auto-created against the product, with
        `product_id` populated and `allergen_id` left null. Runs already
        sitting in `DRAFT` or `SCHEDULED` for that product keep the
        `label_revision_snapshot` they pinned at creation — a deliberate
        stale-pin — so any label reconciliation performed for those runs
        afterwards will flag a `REVISION_MISMATCH`".

        Design: Corner/cross_cutting_layers/supplier_allergen_change_creates_incident_and_stale_pins
        """
        milk = create_allergen("MILK")
        soy = create_allergen("SOY")
        line = create_line("LINE-SUP", "ALLERGEN_DEDICATED")
        product = create_product("P-SUP", ["MILK"], label_revision=1)
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        assert run["label_revision_snapshot"] == 1

        updated = validate_success(
            api.supplier_allergen_change(
                product["id"],
                {"new_allergen_set": ["SOY"], "supplier_notice_ref": "SN-001"},
                MANAGER), 200)
        assert updated["label_revision"] == 2

        # The pre-existing run keeps its pinned snapshot.
        run_after = validate_success(api.get_production_run(run["id"], SUPERVISOR), 200)
        assert run_after["label_revision_snapshot"] == 1

        incidents, meta = validate_paginated(api.list_incidents(MANAGER))
        assert meta["total_count"] == 1
        assert incidents[0]["incident_type"] == "SUPPLIER_ALLERGEN_CHANGE"
        assert incidents[0]["severity"] == "MEDIUM"
        assert incidents[0]["product_id"] == product["id"]

        # Printing the new revision against the stale snapshot flags a mismatch.
        recon = validate_success(
            api.create_label_reconciliation(
                {"run_id": run["id"], "printed_label_revision": 2,
                 "declared_allergens_on_label": ["SOY"]},
                SUPERVISOR), 201)
        assert recon["expected_label_revision"] == 1
        assert recon["verdict"] == "REVISION_MISMATCH"


class TestIncidentLifecycleGates:
    def test_contain_open_incident_rejected(self, api):
        """PRD §3.8: "Containment moves `INVESTIGATING` → `CONTAINED` under the
        same role: the incident must be `INVESTIGATING`
        (`ERR_INCIDENT_NOT_INVESTIGATING`)".

        Design: Corner/state_machines/incident_close_without_containment_rejected
        """
        incident = create_incident_ok("LABEL_MISMATCH", "LOW", description="t")
        assert incident["status"] == "OPEN"
        res = api.contain_incident(incident["id"], {"containment_action": "x"}, SUPERVISOR)
        validate_error(res, "ERR_INCIDENT_NOT_INVESTIGATING")

    def test_close_without_root_cause_rejected(self, api):
        """PRD §3.8: "Closure is reserved for a `QaManager`, moving `CONTAINED`
        → `CLOSED`. The incident must be `CONTAINED`
        (`ERR_INCIDENT_NOT_CONTAINED`), a non-empty `root_cause` narrative is
        mandatory (`ERR_INVALID_REQUEST` without it)".

        Design: Corner/errors/error_incident_close_requires_root_cause
        """
        incident = create_incident_ok("LABEL_MISMATCH", "LOW", description="t")
        drive_incident_to_contained(incident["id"])
        res = api.close_incident(incident["id"], {}, MANAGER)
        validate_error(res, "ERR_INVALID_REQUEST")


class TestLinePostureEvaluationOrder:
    def _setup(self):
        line = create_line("LINE-3", "DRY_CLEAN")
        inc_high = create_incident_ok("UNDECLARED_ALLERGEN", "HIGH",
                                      line_id=line["id"], description="high sev test")
        inc_crit = create_incident_ok("UNDECLARED_ALLERGEN", "CRITICAL",
                                      line_id=line["id"], description="critical sev test")
        return line, inc_high, inc_crit

    def test_critical_and_high_open_yields_hold(self, api):
        """PRD §2.5: "The recomputation follows a pinned evaluation order — the
        HOLD condition is checked first, then RESTRICTED, then OPEN. If any
        incident on the line has `severity` `CRITICAL` while standing in
        `OPEN`, `INVESTIGATING`, or `CONTAINED`, or if any changeover on the
        line stands at `FAILED`, the posture is `HOLD`. Failing that, if any
        incident on the line has `severity` `HIGH` in those same three
        non-final statuses, or any changeover on the line stands at
        `REWORK_REQUIRED`, the posture is `RESTRICTED`."

        Design: Difficulty/combinatorial_formula/line_posture_circular_eval_order_pinned
        """
        line, inc_high, inc_crit = self._setup()
        posture = get_line(line["id"])["posture"]
        assert posture == "HOLD", (
            "With both CRITICAL and HIGH incidents open, HOLD must win")

    def test_closing_critical_with_high_open_relaxes_to_restricted(self, api):
        """PRD §2.5: "Only when neither condition holds does the line read
        `OPEN`."
        PRD §3.8: "When the incident being closed was the last non-`CLOSED`,
        non-`VOID` `CRITICAL` incident on its line, the posture is recomputed
        again."

        Design: Difficulty/combinatorial_formula/line_posture_circular_eval_order_pinned
        """
        line, inc_high, inc_crit = self._setup()
        assert get_line(line["id"])["posture"] == "HOLD"
        drive_incident_to_contained(inc_crit["id"])
        closed = validate_success(
            api.close_incident(inc_crit["id"], {"root_cause": "supplier mislabel"},
                               MANAGER), 200)
        assert closed["status"] == "CLOSED"
        posture = get_line(line["id"])["posture"]
        assert posture == "RESTRICTED", (
            "With the CRITICAL closed and the HIGH still OPEN, posture must be "
            f"RESTRICTED, got {posture}")


class TestSegregationOfDuties:
    def _setup(self):
        allergen = create_allergen("MILK")
        from test_helpers import create_technician
        tech1 = create_technician("TECH-700", [allergen["id"]])
        tech2 = create_technician("TECH-701", [allergen["id"]])
        return tech1, tech2

    def test_self_audit_rejected(self, api):
        """PRD §3.9: "Segregation of duties applies at creation: the
        `auditor_id` must differ from the `technician_id`, failing with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/cross_entity_state_dependency/incident_close_segregation_of_duties_against_recorder
        """
        from test_helpers import make_auditor_headers
        tech1, tech2 = self._setup()
        res = api.create_audit_finding(
            {"technician_id": tech1["id"], "auditor_id": tech1["id"],
             "finding_type": "PROCEDURE_DEVIATION", "severity": "MINOR",
             "corrective_action_due_utc": "2026-12-01T00:00:00Z"},
            make_auditor_headers(tech1["id"]))
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_peer_audit_succeeds(self, api):
        """PRD §3.9: "An `Auditor` records a finding against a technician by
        supplying the `technician_id` audited, the `auditor_id` performing the
        audit, a `finding_type` of `PROCEDURE_DEVIATION`, `DOCUMENTATION_GAP`,
        `TRAINING_DEFICIENCY`, `SWAB_TECHNIQUE`, or `LABEL_CONTROL`, a
        `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and the
        `corrective_action_due_utc` deadline."
        PRD §3.9: "Segregation of duties applies at creation: the `auditor_id`
        must differ from the `technician_id`, failing with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/cross_entity_state_dependency/incident_close_segregation_of_duties_against_recorder
        """
        from test_helpers import make_auditor_headers
        tech1, tech2 = self._setup()
        res = api.create_audit_finding(
            {"technician_id": tech1["id"], "auditor_id": tech2["id"],
             "finding_type": "PROCEDURE_DEVIATION", "severity": "MINOR",
             "corrective_action_due_utc": "2026-12-01T00:00:00Z"},
            make_auditor_headers(tech2["id"]))
        finding = validate_success(res, 201)
        assert finding["status"] == "OPEN"
