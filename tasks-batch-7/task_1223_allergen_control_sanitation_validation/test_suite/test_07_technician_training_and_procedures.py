"""Technician training scores, suspension threshold, audit finding lifecycle,
and changeover procedure approval/retirement including OCC and supersession."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_allergen, create_line, create_matrix_entry, create_product,
    create_run, create_changeover, create_technician,
    create_procedure, approve_procedure, create_and_approve_procedure,
    setup_technician_pair, record_finding, record_finding_ok, get_technician,
    set_clock,
    MANAGER, SUPERVISOR, OPERATOR,
)


def _build_score_39_technician():
    """Tech with CRITICAL x3 + MAJOR x2 + MINOR x3 findings: 100-61 = 39."""
    allergen, auditee, auditor = setup_technician_pair("PEANUT")
    for severity, ftype in (
        ("CRITICAL", "PROCEDURE_DEVIATION"),
        ("CRITICAL", "DOCUMENTATION_GAP"),
        ("CRITICAL", "SWAB_TECHNIQUE"),
        ("MAJOR", "TRAINING_DEFICIENCY"),
        ("MINOR", "LABEL_CONTROL"),
        ("MAJOR", "PROCEDURE_DEVIATION"),
        ("MINOR", "DOCUMENTATION_GAP"),
        ("MINOR", "SWAB_TECHNIQUE"),
    ):
        record_finding_ok(auditee, auditor, severity=severity, finding_type=ftype)
    return auditee, auditor


class TestTrainingScoreAggregationAndReinstate:
    def test_aggregated_score_auto_suspends_below_60(self, api):
        """PRD §3.9: "It starts from 100; every finding standing at `OPEN`,
        `OVERDUE`, or `RESOLVED` subtracts its `points_deducted`; every finding
        standing at `OVERDUE` subtracts a further 3-point overdue penalty on
        top; and a `WAIVED` finding deducts nothing, its points having been
        refunded."
        PRD §3.9: "The score floors at 0, ceilings at 100, and is stored as an
        integer. When a recomputation leaves the score below 60, the technician
        flips automatically from `ACTIVE` to `SUSPENDED`."
        PRD §3.9: "The severity fixes the computed `points_deducted` — 2 points
        for `MINOR`, 5 for `MAJOR`, 15 for `CRITICAL`".

        Design: Difficulty/dual_variant_calc/training_score_floor_vs_reinstate_reset
        """
        auditee, auditor = _build_score_39_technician()
        tech = get_technician(auditee["id"])
        # 100 - (15+15+15+5+2+5+2+2) = 39.
        assert tech["training_score"] == 39, (
            f"Expected 39, got {tech['training_score']}")
        assert tech["status"] == "SUSPENDED", "score below 60 must auto-suspend"

    def test_reinstate_resets_score_to_floor_75(self, api):
        """PRD §3.9: "Reinstatement moves `SUSPENDED` → `ACTIVE` (the
        technician must be `SUSPENDED`, failing with `ERR_TECH_NOT_SUSPENDED`)
        and resets the `training_score` to a floor of 75."

        Design: Difficulty/dual_variant_calc/training_score_floor_vs_reinstate_reset
        """
        auditee, auditor = _build_score_39_technician()
        tech = get_technician(auditee["id"])
        assert tech["status"] == "SUSPENDED"
        reinstated = validate_success(
            api.reinstate_technician(auditee["id"], MANAGER), 200)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["training_score"] == 75, (
            f"Reinstate must reset the score to 75, got "
            f"{reinstated['training_score']}")


class TestTrainingScoreWaiveRefund:
    def test_minor_finding_deducts_two_points(self, api):
        """PRD §3.9: "The severity fixes the computed `points_deducted` — 2
        points for `MINOR`, 5 for `MAJOR`, 15 for `CRITICAL` — and the
        technician's `training_score` is recomputed immediately".
        PRD §3.9: "A new technician starts with a `training_score` of 100 and
        a `status` of `ACTIVE`."

        Design: Difficulty/compensating_invariant/training_score_conservation_waive_refund
        """
        allergen, auditee, auditor = setup_technician_pair("MILK")
        assert auditee["training_score"] == 100
        finding = record_finding_ok(auditee, auditor, severity="MINOR",
                                    finding_type="DOCUMENTATION_GAP")
        assert finding["points_deducted"] == 2
        assert get_technician(auditee["id"])["training_score"] == 98

    def test_waive_refunds_exactly_the_deducted_points(self, api):
        """PRD §3.9: "A `QaManager` may instead waive a finding, but only one
        standing at `OPEN` (`ERR_FINDING_NOT_OPEN`) and only when its severity
        is `MINOR` (`ERR_FINDING_NOT_MINOR`, HTTP 422); waiving refunds the
        `points_deducted` to the technician's score and lands the finding at
        `WAIVED`."

        Design: Difficulty/compensating_invariant/training_score_conservation_waive_refund
        """
        allergen, auditee, auditor = setup_technician_pair("MILK")
        finding = record_finding_ok(auditee, auditor, severity="MINOR",
                                    finding_type="DOCUMENTATION_GAP")
        assert get_technician(auditee["id"])["training_score"] == 98
        waived = validate_success(api.waive_audit_finding(finding["id"], MANAGER), 200)
        assert waived["status"] == "WAIVED"
        assert get_technician(auditee["id"])["training_score"] == 100, (
            "Waive must refund exactly the deducted points — no drift")


class TestOverduePenalty:
    def test_major_deduction_and_overdue_penalty_constants(self, api):
        """PRD §3.9: "When the clock passes a finding's
        `corrective_action_due_utc` while the finding still stands `OPEN`, the
        finding flips automatically to `OVERDUE` and a further 3-point penalty
        is deducted from the technician's score."
        PRD §2.4: "Advancing the clock sweeps every `OPEN` audit finding whose
        `corrective_action_due_utc` lies before the new clock instant into the
        `OVERDUE` state".

        Design: Corner/calculations/audit_finding_points_deduction_constants
        """
        allergen, auditee, auditor = setup_technician_pair("MILK")
        finding = record_finding_ok(auditee, auditor, severity="MAJOR",
                                    finding_type="PROCEDURE_DEVIATION",
                                    due="2026-06-15T00:00:00Z")
        assert finding["points_deducted"] == 5
        assert get_technician(auditee["id"])["training_score"] == 95

        set_clock("2026-06-16T00:00:00Z")
        finding_after = validate_success(
            api.get_audit_finding(finding["id"], MANAGER), 200)
        assert finding_after["status"] == "OVERDUE"
        assert get_technician(auditee["id"])["training_score"] == 92, (
            "95 - 3 overdue penalty = 92")


class TestSuspensionThreshold:
    def test_score_60_stays_active_58_suspends(self, api):
        """PRD §3.9: "When a recomputation leaves the score below 60, the
        technician flips automatically from `ACTIVE` to `SUSPENDED`."

        Design: Corner/cross_cutting_layers/suspension_threshold_auto_transition
        """
        allergen, auditee, auditor = setup_technician_pair("MILK")
        for ftype in ("PROCEDURE_DEVIATION", "PROCEDURE_DEVIATION",
                      "DOCUMENTATION_GAP", "DOCUMENTATION_GAP",
                      "SWAB_TECHNIQUE", "SWAB_TECHNIQUE",
                      "TRAINING_DEFICIENCY", "TRAINING_DEFICIENCY"):
            record_finding_ok(auditee, auditor, severity="MAJOR", finding_type=ftype)
        tech = get_technician(auditee["id"])
        # 100 - 8*5 = 60; 60 is not below 60.
        assert tech["training_score"] == 60
        assert tech["status"] == "ACTIVE"

        record_finding_ok(auditee, auditor, severity="MINOR", finding_type="LABEL_CONTROL")
        tech = get_technician(auditee["id"])
        # 60 - 2 = 58 < 60.
        assert tech["training_score"] == 58
        assert tech["status"] == "SUSPENDED"


class TestFindingStateGates:
    def test_waive_non_minor_rejected(self, api):
        """PRD §3.9: "A `QaManager` may instead waive a finding, but only one
        standing at `OPEN` (`ERR_FINDING_NOT_OPEN`) and only when its severity
        is `MINOR` (`ERR_FINDING_NOT_MINOR`, HTTP 422)".

        Design: Corner/state_machines/audit_finding_waive_non_minor_rejected
        """
        allergen, auditee, auditor = setup_technician_pair("MILK")
        finding = record_finding_ok(auditee, auditor, severity="MAJOR",
                                    finding_type="PROCEDURE_DEVIATION")
        res = api.waive_audit_finding(finding["id"], MANAGER)
        validate_error(res, "ERR_FINDING_NOT_MINOR")

    def test_reinstate_active_technician_rejected(self, api):
        """PRD §3.9: "Reinstatement moves `SUSPENDED` → `ACTIVE` (the
        technician must be `SUSPENDED`, failing with
        `ERR_TECH_NOT_SUSPENDED`)".

        Design: Corner/state_machines/technician_reinstate_requires_suspended
        """
        allergen, auditee, auditor = setup_technician_pair("MILK")
        assert auditee["status"] == "ACTIVE"
        res = api.reinstate_technician(auditee["id"], MANAGER)
        validate_error(res, "ERR_TECH_NOT_SUSPENDED")


class TestProcedureRetireGate:
    def test_retire_procedure_referenced_by_planned_changeover_rejected(self, api):
        """PRD §3.3: "A `QaManager` may retire a procedure only while it stands
        at `APPROVED` (`ERR_PROCEDURE_NOT_APPROVED` otherwise), and only while
        no changeover in `PLANNED`, `IN_EXECUTION`, `SWAB_PENDING`, or
        `REWORK_REQUIRED` still references it — an active reference blocks
        retirement with `ERR_PROCEDURE_IN_USE` (HTTP 409)."

        Design: Corner/state_machines/procedure_retire_in_use_rejected
        """
        allergen = create_allergen("SOY")
        line = create_line("LINE-S4", "WET_WASH")
        create_matrix_entry(line["id"], allergen["id"],
                            handling="REQUIRES_CHANGEOVER", changeover_minutes=10)
        product = create_product("P-S4", ["SOY"])
        procedure = create_and_approve_procedure(allergen["id"], "COP-S4",
                                                 min_swab_zones=1)
        run = create_run(line["id"], product["id"],
                         "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
        changeover = create_changeover(line["id"], run["id"], procedure["id"], 10)
        assert changeover["status"] == "PLANNED"
        res = api.retire_procedure(procedure["id"], MANAGER)
        validate_error(res, "ERR_PROCEDURE_IN_USE")


class TestProcedureOccAndSupersession:
    def test_approve_with_stale_procedure_version_rejected(self, api):
        """PRD §2.7: "Approving a changeover procedure requires the request to
        carry `expected_procedure_version`, holding the procedure `version` the
        client last observed. Approving from a stale observation risks
        double-superseding a sibling version that has already been superseded
        by a prior approval, so a mismatch with the procedure's current
        `version` is rejected with `ERR_STALE_PROCEDURE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_procedure_version_on_approve
        """
        allergen = create_allergen("MILK")
        proc = create_procedure(allergen["id"], "COP-OCC2", min_swab_zones=1)
        res = api.approve_procedure(
            proc["id"], {"expected_procedure_version": proc["version"] + 1}, MANAGER)
        validate_error(res, "ERR_STALE_PROCEDURE_VERSION")

    def test_family_approval_supersedes_prior_version(self, api):
        """PRD §3.3: "When approval succeeds, the newly approved row moves to
        `APPROVED` and becomes the family's current row (`is_current` true),
        any previously `APPROVED` sibling with the same `procedure_code` is
        pushed to `SUPERSEDED` and loses currency, and the procedure's own
        `version` increments by one."

        Design: Corner/cross_cutting_layers/occ_stale_procedure_version_on_approve
        """
        allergen = create_allergen("MILK")
        p1 = create_procedure(allergen["id"], "COP-OCC2", min_swab_zones=1)
        p2 = create_procedure(allergen["id"], "COP-OCC2", method="DRY_SCRAPE",
                              min_swab_zones=2, atp_action_level_rlu=100,
                              allergen_action_level_ppm=1.0)
        approved1 = approve_procedure(p1)
        assert approved1["status"] == "APPROVED"
        assert approved1["is_current"] is True

        approved2 = approve_procedure(p2)
        assert approved2["status"] == "APPROVED"
        assert approved2["is_current"] is True

        p1_after = validate_success(api.get_changeover_procedure(p1["id"], MANAGER), 200)
        assert p1_after["status"] == "SUPERSEDED"
        assert p1_after["is_current"] is False
