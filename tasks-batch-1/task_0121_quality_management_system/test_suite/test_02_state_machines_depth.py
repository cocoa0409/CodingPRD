"""Depth tests for state-machine behaviour and cascades (queue A — Difficulty).

Covers the cyclic CAPA back-edge, the NCR disposition branching fork, the
depth-3 CAPA-close cascade, the depth-2 lot-reject tightening cascade, and the
AQL accept/audit-close boundary edges.
"""
import pytest

from test_helpers import validate_success, get_success_data
from test_helpers import fixtures as fx


# ==========================================================================
# Difficulty/non_linear_state_machine/capa_verification_cycle_back_to_root_cause
# ==========================================================================
def test_reject_verification_cycles_capa_back_to_root_cause(api):
    """PRD 3.4: "From VERIFICATION, a manager may reject the verification,
    looping the CAPA back from VERIFICATION to ROOT_CAUSE: this increments
    rework_loops by one, resets current_step to D4, and clears
    provisional_effectiveness back to null."

    Design: Difficulty/non_linear_state_machine/capa_verification_cycle_back_to_root_cause
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr, capa = fx.capa_to_verification(eng["id"], mgr["id"], sup["id"],
                                        containment_count=3, defect_qty=5, part_number="P-V")
    assert capa["provisional_effectiveness"] == 0.60

    rejected = validate_success(api.transition_capa(
        capa["id"], {"action": "REJECT_VERIFICATION"}, fx.make_manager_headers(mgr["id"])))
    assert rejected["status"] == "ROOT_CAUSE"
    assert rejected["current_step"] == "D4"
    assert rejected["rework_loops"] == 1
    assert rejected["provisional_effectiveness"] is None


def test_reject_verification_increments_rework_loops_from_zero(api):
    """PRD 3.4: "From VERIFICATION, a manager may reject the verification,
    looping the CAPA back from VERIFICATION to ROOT_CAUSE: this increments
    rework_loops by one, resets current_step to D4, and clears
    provisional_effectiveness back to null."

    Design: Difficulty/non_linear_state_machine/capa_verification_cycle_back_to_root_cause
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr, capa = fx.capa_to_verification(eng["id"], mgr["id"], sup["id"],
                                        containment_count=3, defect_qty=5, part_number="P-V2")
    assert capa["rework_loops"] == 0
    rejected = validate_success(api.transition_capa(
        capa["id"], {"action": "REJECT_VERIFICATION"}, fx.make_manager_headers(mgr["id"])))
    assert rejected["rework_loops"] == 1


# ==========================================================================
# Difficulty/non_linear_state_machine/ncr_disposition_branching_fork_divergent_cost
# ==========================================================================
def test_disposition_fork_scrap_vs_return_to_supplier_diverge(api):
    """PRD 3.3: "for SCRAP, the base component is the full unit_cost_cents, since
    the entire unit value is lost and no rework labour is incurred"
    PRD 3.3: "for RETURN_TO_SUPPLIER, the base component is the unit_cost_cents
    multiplied by a handling factor of 0.10 and rounded half-up to whole cents,
    representing handling and freight only."

    Design: Difficulty/non_linear_state_machine/ncr_disposition_branching_fork_divergent_cost
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # identical inputs: MAJOR, defect_qty=10, unit_cost_cents=500
    ncr1 = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=10,
                              unit_cost_cents=500, part_number="P-F1")
    ncr2 = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=10,
                              unit_cost_cents=500, part_number="P-F2")
    d1 = validate_success(api.disposition_ncr(ncr1["id"], {"disposition": "SCRAP"}, fx.make_manager_headers(mgr["id"])))
    d2 = validate_success(api.disposition_ncr(ncr2["id"], {"disposition": "RETURN_TO_SUPPLIER"}, fx.make_manager_headers(mgr["id"])))
    # SCRAP: 10 * round_half_up(500*1.0) = 5000
    assert d1["disposition"] == "SCRAP"
    assert d1["cost_of_quality_cents"] == 5000
    # RETURN_TO_SUPPLIER: 10 * round_half_up(round_half_up(500*0.10)*1.0) = 10*50 = 500
    assert d2["disposition"] == "RETURN_TO_SUPPLIER"
    assert d2["cost_of_quality_cents"] == 500
    assert d1["cost_of_quality_cents"] != d2["cost_of_quality_cents"]


def test_disposition_scrap_cost_is_full_unit_value(api):
    """PRD 3.3: "for SCRAP, the base component is the full unit_cost_cents, since
    the entire unit value is lost and no rework labour is incurred"

    Design: Difficulty/non_linear_state_machine/ncr_disposition_branching_fork_divergent_cost
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=10,
                             unit_cost_cents=500, part_number="P-F3")
    d = validate_success(api.disposition_ncr(ncr["id"], {"disposition": "SCRAP"}, fx.make_manager_headers(mgr["id"])))
    assert d["cost_of_quality_cents"] == 5000


# ==========================================================================
# Difficulty/transitive_cascade/capa_close_cascades_ncr_scar_supplier_depth3
# ==========================================================================
def test_capa_close_cascades_through_ncr_scar_supplier(api):
    """PRD 3.4: "on success the CAPA moves from EFFECTIVENESS_CHECK to
    CLOSED_EFFECTIVE and cascades a closure onto its parent report, driving that
    report from CAPA_IN_PROGRESS to CLOSED."
    PRD 3.4: "When the parent report is driven to CLOSED, its reserved budget is
    released to zero, and a further cascade may follow: if the report's source is
    SUPPLIER and a SCAR exists for the report in ACCEPTED_RESPONSE status, that
    SCAR is itself resolved as described next."
    PRD 3.5: "when the parent report referenced by the SCAR's ncr_id reaches
    CLOSED while the SCAR is in ACCEPTED_RESPONSE, the SCAR transitions from
    ACCEPTED_RESPONSE to RESOLVED, decrements the supplier's open_scar_count, and
    recomputes the supplier's rating."

    Design: Difficulty/transitive_cascade/capa_close_cascades_ncr_scar_supplier_depth3
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # SUPPLIER NCR (defect_qty=5) opened -> ncrs_attributed=1; dispositioned REWORK; CAPA opened.
    ncr = fx.create_dispositioned_ncr(eng["id"], mgr["id"], supplier_id=sup["id"],
                                      disposition="REWORK", defect_qty=5, unit_cost_cents=1000,
                                      rework_hours=2.0, severity="MAJOR", part_number="P-T3")
    capa = fx.open_capa(eng["id"], ncr["id"])
    # SCAR opened (open_scar_count=1) and driven to ACCEPTED_RESPONSE.
    scar = fx.scar_to_accepted_response(mgr["id"], sup["id"], ncr["id"])
    # Drive CAPA to EFFECTIVENESS_CHECK (provisional 0.60), then close effective.
    eh = fx.make_engineer_headers(eng["id"])
    fx.record_step(eng["id"], capa["id"], discipline="D1", narrative="team")
    fx.record_step(eng["id"], capa["id"], discipline="D4", narrative="rc", containment_count=3)
    fx.record_step(eng["id"], capa["id"], discipline="D8", narrative="mon", recurred_defects=0)
    get_success_data(api.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    get_success_data(api.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    get_success_data(api.transition_capa(capa["id"], {"action": "VERIFY"}, fx.make_manager_headers(mgr["id"])))

    closed = validate_success(api.transition_capa(capa["id"], {"action": "CLOSE_EFFECTIVE"}, fx.make_manager_headers(mgr["id"])))
    assert closed["status"] == "CLOSED_EFFECTIVE"

    ncr_after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert ncr_after["status"] == "CLOSED"
    assert ncr_after["budget_reserved_cents"] == 0

    scar_after = validate_success(api.get_scar(scar["id"], fx.make_manager_headers(mgr["id"])))
    assert scar_after["status"] == "RESOLVED"

    sup_after = validate_success(api.get_supplier(sup["id"], fx.make_manager_headers(mgr["id"])))
    assert sup_after["open_scar_count"] == 0
    # ncrs_attributed=1 still; lots none; open_scar_count back to 0 -> rating 96.00
    assert sup_after["quality_rating"] == pytest.approx(96.00, abs=0.001)


def test_capa_close_releases_ncr_budget_to_zero(api):
    """PRD 3.4: "When the parent report is driven to CLOSED, its reserved budget
    is released to zero, and a further cascade may follow: if the report's source
    is SUPPLIER and a SCAR exists for the report in ACCEPTED_RESPONSE status, that
    SCAR is itself resolved as described next."

    Design: Difficulty/transitive_cascade/capa_close_cascades_ncr_scar_supplier_depth3
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_dispositioned_ncr(eng["id"], mgr["id"], supplier_id=sup["id"],
                                      disposition="REWORK", defect_qty=5, unit_cost_cents=1000,
                                      rework_hours=2.0, severity="MAJOR", part_number="P-T3b")
    capa = fx.open_capa(eng["id"], ncr["id"])
    eh = fx.make_engineer_headers(eng["id"])
    fx.record_step(eng["id"], capa["id"], discipline="D1", narrative="team")
    fx.record_step(eng["id"], capa["id"], discipline="D4", narrative="rc", containment_count=3)
    fx.record_step(eng["id"], capa["id"], discipline="D8", narrative="mon", recurred_defects=0)
    get_success_data(api.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    get_success_data(api.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    get_success_data(api.transition_capa(capa["id"], {"action": "VERIFY"}, fx.make_manager_headers(mgr["id"])))
    validate_success(api.transition_capa(capa["id"], {"action": "CLOSE_EFFECTIVE"}, fx.make_manager_headers(mgr["id"])))
    ncr_after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert ncr_after["status"] == "CLOSED"
    assert ncr_after["budget_reserved_cents"] == 0


# ==========================================================================
# Difficulty/transitive_cascade/lot_reject_cascades_consecutive_then_tightened_depth2
# ==========================================================================
def test_second_reject_tightens_plan(api):
    """PRD 3.6: "If defects_found is at least the rejection_number — equality at
    the acceptance number plus one rejects — the lot is REJECTED: this increments
    both the supplier's lots_inspected and lots_rejected, increments the plan's
    consecutive_rejects, and recomputes the supplier's rating; and if the running
    consecutive_rejects reaches 2, the plan's severity_mode switches from NORMAL
    to TIGHTENED."

    Design: Difficulty/transitive_cascade/lot_reject_cascades_consecutive_then_tightened_depth2
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    # first reject -> consecutive_rejects=1, still NORMAL
    fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=3)
    plan_mid = validate_success(api.get_inspection_plan(ip["id"], fx.make_inspector_headers(inspector["id"])))
    assert plan_mid["consecutive_rejects"] == 1
    assert plan_mid["severity_mode"] == "NORMAL"
    # second reject -> consecutive_rejects=2, flips TIGHTENED
    lot2 = fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=3)
    assert lot2["status"] == "REJECTED"
    plan_after = validate_success(api.get_inspection_plan(ip["id"], fx.make_inspector_headers(inspector["id"])))
    assert plan_after["consecutive_rejects"] == 2
    assert plan_after["severity_mode"] == "TIGHTENED"


def test_consecutive_rejects_increments_on_each_reject(api):
    """PRD 3.6: "If defects_found is at least the rejection_number — equality at
    the acceptance number plus one rejects — the lot is REJECTED: this increments
    both the supplier's lots_inspected and lots_rejected, increments the plan's
    consecutive_rejects, and recomputes the supplier's rating; and if the running
    consecutive_rejects reaches 2, the plan's severity_mode switches from NORMAL
    to TIGHTENED."

    Design: Difficulty/transitive_cascade/lot_reject_cascades_consecutive_then_tightened_depth2
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=3)
    lot2 = fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=3)
    assert lot2["status"] == "REJECTED"
    plan_after = validate_success(api.get_inspection_plan(ip["id"], fx.make_inspector_headers(inspector["id"])))
    assert plan_after["consecutive_rejects"] == 2


# ==========================================================================
# Difficulty/boundary_precision_check/lot_defects_equal_acceptance_number_accepts
# ==========================================================================
@pytest.mark.parametrize("defects_found,expected_status", [
    (1, "ACCEPTED"),   # below Ac
    (2, "ACCEPTED"),   # == Ac (boundary accepts)
    (3, "REJECTED"),   # == Ac+1 (boundary rejects)
])
def test_lot_acceptance_boundary_at_acceptance_number(api, defects_found, expected_status):
    """PRD 3.6: "If defects_found is at most the acceptance_number — equality at
    the acceptance number still accepts — the lot is ACCEPTED ..."
    PRD 3.6: "If defects_found is at least the rejection_number — equality at the
    acceptance number plus one rejects — the lot is REJECTED ..."
    PRD 3.6: "the resolved acceptance_number is the table's acceptance number,
    and the rejection_number is the acceptance number plus one."

    Design: Difficulty/boundary_precision_check/lot_defects_equal_acceptance_number_accepts
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    lot = fx.create_in_inspection_lot(inspector["id"], ip["id"], supplier["id"], actual_lot_size=120)
    assert lot["acceptance_number"] == 2
    assert lot["rejection_number"] == 3
    disp = validate_success(api.transition_inspection_lot(
        lot["id"], {"action": "DISPOSITION", "defects_found": defects_found}, fx.make_inspector_headers(inspector["id"])))
    assert disp["status"] == expected_status
    assert disp["defects_found"] == defects_found


def test_lot_defects_equal_acceptance_number_accepts(api):
    """PRD 3.6: "If defects_found is at most the acceptance_number — equality at
    the acceptance number still accepts — the lot is ACCEPTED ..."

    Design: Difficulty/boundary_precision_check/lot_defects_equal_acceptance_number_accepts
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    lot = fx.create_in_inspection_lot(inspector["id"], ip["id"], supplier["id"], actual_lot_size=120)
    assert lot["acceptance_number"] == 2
    disp = validate_success(api.transition_inspection_lot(
        lot["id"], {"action": "DISPOSITION", "defects_found": 2}, fx.make_inspector_headers(inspector["id"])))
    assert disp["status"] == "ACCEPTED"


# ==========================================================================
# Difficulty/boundary_precision_check/audit_close_with_zero_open_findings_succeeds
# ==========================================================================
def test_audit_close_with_zero_open_findings_succeeds(api):
    """PRD 3.8: "Closing the audit itself moves it from IN_PROGRESS to CLOSED and
    requires that its open_finding_count be exactly zero — every finding CLOSED or
    VOID — failing which the close is rejected with ERR_AUDIT_HAS_OPEN_FINDINGS
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/audit_close_with_zero_open_findings_succeeds
    """
    auditor = fx.create_auditor()
    audit = fx.create_in_progress_audit(auditor["id"])
    assert audit["open_finding_count"] == 0
    closed = validate_success(api.transition_audit(audit["id"], {"action": "CLOSE"}, fx.make_auditor_headers(auditor["id"])))
    assert closed["status"] == "CLOSED"


def test_audit_close_succeeds_when_no_findings_recorded(api):
    """PRD 3.8: "Closing the audit itself moves it from IN_PROGRESS to CLOSED and
    requires that its open_finding_count be exactly zero — every finding CLOSED or
    VOID — failing which the close is rejected with ERR_AUDIT_HAS_OPEN_FINDINGS
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/audit_close_with_zero_open_findings_succeeds
    """
    auditor = fx.create_auditor()
    audit = fx.create_in_progress_audit(auditor["id"])
    closed = validate_success(api.transition_audit(audit["id"], {"action": "CLOSE"}, fx.make_auditor_headers(auditor["id"])))
    assert closed["status"] == "CLOSED"
    assert closed["open_finding_count"] == 0
