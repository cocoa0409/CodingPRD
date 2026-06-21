"""Breadth tests for endpoints (computed reads, reverse-reachability, action
endpoints), RBAC (forbidden role, ownership, SoD), cross-cutting layers (OCC,
derived fields, rate thresholds), and consistency model (queue B — Corner).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
)
from test_helpers import fixtures as fx


# ==========================================================================
# Corner/endpoints/computed_read_supplier_summary_counters
# ==========================================================================
def test_supplier_summary_counters_computed_read(api):
    """PRD 3.7: "The lot factor rewards a clean acceptance history: if
    lots_inspected is zero it is 1.0, otherwise it is one minus the ratio of
    lots_rejected to lots_inspected, with the result floored at 0.0."
    PRD 3.7: "a rating of at least 70.00 yields APPROVED"

    Design: Corner/endpoints/computed_read_supplier_summary_counters
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=0)  # ACCEPTED
    fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=3)  # REJECTED
    s = validate_success(api.get_supplier(supplier["id"], fx.TEST_USERS["manager_headers"]))
    assert s["lots_inspected"] == 2
    assert s["lots_rejected"] == 1
    # lot_factor=0.5 -> base=0.6*0.5+0.4*1.0=0.70 -> 70.00 (APPROVED at inclusive 70)
    assert s["quality_rating"] == pytest.approx(70.00, abs=0.001)
    assert s["approval_status"] == "APPROVED"


# ==========================================================================
# Corner/endpoints/list_capas_for_ncr_reverse_reachability
# ==========================================================================
def test_list_capas_for_ncr_reverse_reachability(api):
    """PRD 2.6: "These nested listings exist so that a foreign key pointing from
    child to parent can be traversed in reverse; the child's link to its parent is
    never declared as a navigable field on the parent, only resolved through the
    listing."

    Design: Corner/endpoints/list_capas_for_ncr_reverse_reachability
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_dispositioned_ncr(eng["id"], mgr["id"], supplier_id=sup["id"],
                                      disposition="REWORK", defect_qty=5, unit_cost_cents=1000,
                                      rework_hours=2.0, part_number="P-LC")
    capa = fx.open_capa(eng["id"], ncr["id"])
    data, meta = validate_paginated(api.list_ncr_capas(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert len(data) == 1
    assert data[0]["id"] == capa["id"]
    assert data[0]["ncr_id"] == ncr["id"]


# ==========================================================================
# Corner/endpoints/list_ncrs_filtered_by_audit_finding_id
# ==========================================================================
def test_list_ncrs_filtered_by_audit_finding_id(api):
    """PRD 2.6: "These nested listings exist so that a foreign key pointing from
    child to parent can be traversed in reverse; the child's link to its parent is
    never declared as a navigable field on the parent, only resolved through the
    listing."
    PRD 3.2: "opening the report drives that finding from OPEN to NCR_RAISED and
    records the new report's id in the finding's raised_ncr_id."

    Design: Corner/endpoints/list_ncrs_filtered_by_audit_finding_id
    """
    auditor, audit, finding = fx.setup_audit_with_open_finding(grade="MAJOR")
    eng = fx.create_engineer()
    ncr = fx.create_open_ncr(eng["id"], source="AUDIT", audit_finding_id=finding["id"],
                             severity="MAJOR", defect_qty=2, unit_cost_cents=1000, part_number="P-LF")
    data, meta = validate_paginated(api.list_ncrs(fx.TEST_USERS["manager_headers"], params={"audit_finding_id": finding["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == ncr["id"]
    assert data[0]["audit_finding_id"] == finding["id"]


# ==========================================================================
# Corner/endpoints/action_disposition_missing_defects_found_invalid_request
# ==========================================================================
def test_lot_disposition_missing_defects_found_invalid_request(api):
    """PRD 3.6: "Dispositioning the lot moves it from IN_INSPECTION to a terminal
    state and requires the inspector to supply defects_found (the number of
    defective units found in the sample, never negative)."

    Design: Corner/endpoints/action_disposition_missing_defects_found_invalid_request
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    lot = fx.create_in_inspection_lot(inspector["id"], ip["id"], supplier["id"], actual_lot_size=120)
    resp = api.transition_inspection_lot(lot["id"], {"action": "DISPOSITION"}, fx.make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    after = validate_success(api.get_inspection_lot(lot["id"], fx.make_inspector_headers(inspector["id"])))
    assert after["status"] == "IN_INSPECTION"


# ==========================================================================
# Corner/rbac/inspector_cannot_create_supplier_forbidden_role
# ==========================================================================
def test_inspector_cannot_create_supplier_forbidden_role(api):
    """PRD 2.1: "Once authenticated, the role must be permitted to invoke the
    requested operation; a recognized role attempting an operation outside its
    authority is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/inspector_cannot_create_supplier_forbidden_role
    """
    inspector = fx.create_inspector()
    resp = api.create_supplier({"name": "Denied Co", "code": fx.f._unique_code("DEN")},
                               fx.make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ==========================================================================
# Corner/rbac/quality_engineer_cannot_disposition_forbidden_role
# ==========================================================================
def test_quality_engineer_cannot_disposition_forbidden_role(api):
    """PRD 2.10: "Next the role's authority for the endpoint is checked, yielding
    ERR_FORBIDDEN_ROLE if the role is not permitted."

    Design: Corner/rbac/quality_engineer_cannot_disposition_forbidden_role
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-RD2")
    resp = api.disposition_ncr(ncr["id"], {"disposition": "REWORK"}, fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    after = validate_success(api.get_ncr(ncr["id"], fx.make_engineer_headers(eng["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/rbac/scar_acknowledge_wrong_supplier_not_owner
# ==========================================================================
def test_scar_acknowledge_wrong_supplier_not_owner(api):
    """PRD 2.9: "a SupplierUser acting on a SCAR must have an X-User-ID equal to
    that SCAR's supplier_id ...; a violation is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/scar_acknowledge_wrong_supplier_not_owner
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    owner = fx.create_supplier()
    other = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=owner["id"], severity="MAJOR", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-NO")
    scar = fx.open_scar(mgr["id"], ncr["id"], owner["id"])
    resp = api.transition_scar(scar["id"], {"action": "ACKNOWLEDGE"}, fx.make_supplier_user_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    after = validate_success(api.get_scar(scar["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/rbac/audit_start_non_lead_auditor_not_owner
# ==========================================================================
def test_audit_start_non_lead_auditor_not_owner(api):
    """PRD 2.9: "an Auditor driving an audit's lifecycle must have an X-User-ID
    equal to that audit's lead_auditor_id; a violation is rejected with
    ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/audit_start_non_lead_auditor_not_owner
    """
    lead = fx.create_auditor()
    other = fx.create_auditor()
    audit = fx.create_planned_audit(lead["id"])
    resp = api.transition_audit(audit["id"], {"action": "START"}, fx.make_auditor_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    after = validate_success(api.get_audit(audit["id"], fx.make_auditor_headers(lead["id"])))
    assert after["status"] == "PLANNED"


# ==========================================================================
# Corner/rbac/disposition_by_ncr_author_segregation_of_duties
# ==========================================================================
def test_disposition_by_ncr_author_segregation_of_duties(api):
    """PRD 2.9: "the manager dispositioning a nonconformance must not be the
    engineer recorded in its created_by_personnel_id ...; a violation is rejected
    with ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Corner/rbac/disposition_by_ncr_author_segregation_of_duties
    """
    qm = fx.create_personnel(role="QUALITY_MANAGER")
    sup = fx.create_supplier()
    # The QM raises the NCR (created_by == them) and opens it.
    ncr = get_success_data(api.create_ncr(
        {"title": "sod ncr", "source": "SUPPLIER", "severity": "MAJOR", "defect_qty": 2,
         "unit_cost_cents": 1000, "part_number": "P-SOD", "supplier_id": sup["id"]},
        fx.make_engineer_headers(qm["id"])))
    get_success_data(api.open_ncr(ncr["id"], fx.make_engineer_headers(qm["id"])))
    resp = api.disposition_ncr(ncr["id"], {"disposition": "REWORK"}, fx.make_manager_headers(qm["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(qm["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/rbac/capa_verify_by_author_segregation_of_duties
# ==========================================================================
def test_capa_verify_by_author_segregation_of_duties(api):
    """PRD 2.9: "the manager verifying, rejecting verification of, or closing a
    CAPA (whether effective or ineffective) must not be the engineer recorded in
    its authored_by_personnel_id; a violation is rejected with
    ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Corner/rbac/capa_verify_by_author_segregation_of_duties
    """
    qm_auth = fx.create_personnel(role="QUALITY_MANAGER")
    qm_ind = fx.create_personnel(role="QUALITY_MANAGER")
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    # independent QM dispositions; qm_auth opens & advances the CAPA (author).
    ncr = fx.create_dispositioned_ncr(eng["id"], qm_ind["id"], supplier_id=sup["id"],
                                      disposition="REWORK", defect_qty=5, unit_cost_cents=1000,
                                      rework_hours=2.0, part_number="P-VFA")
    capa = fx.open_capa(qm_auth["id"], ncr["id"])
    eh = fx.make_engineer_headers(qm_auth["id"])
    get_success_data(api.create_capa_step(capa["id"], {"discipline": "D1", "narrative": "team"}, eh))
    get_success_data(api.create_capa_step(capa["id"], {"discipline": "D4", "narrative": "rc", "containment_count": 3}, eh))
    get_success_data(api.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    advanced = get_success_data(api.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    assert advanced["provisional_effectiveness"] == 0.60
    # The author (qm_auth) attempts VERIFY -> SoD violation.
    resp = api.transition_capa(capa["id"], {"action": "VERIFY"}, fx.make_manager_headers(qm_auth["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    after = validate_success(api.get_capa(capa["id"], fx.make_manager_headers(qm_ind["id"])))
    assert after["status"] == "VERIFICATION"


# ==========================================================================
# Corner/cross_cutting_layers/occ_stale_control_plan_version_rejected
# ==========================================================================
def test_occ_stale_control_plan_version_rejected(api):
    """PRD 2.7: "The server compares that value to the control plan's current
    version; if they do not match — because some other writer has advanced the
    control plan since the client read it — the create is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_control_plan_version_rejected
    """
    eng = fx.create_engineer()
    cp = fx.create_control_plan()
    v0 = fx.read_control_plan_version(cp["id"])
    # first create with v0 succeeds and bumps version
    get_success_data(api.create_control_plan_revision(
        {"control_plan_id": cp["id"], "revision_no": 1, "change_summary": "first",
         "expected_control_plan_version": v0},
        fx.make_engineer_headers(eng["id"])))
    # second create still carrying stale v0 is rejected
    resp = api.create_control_plan_revision(
        {"control_plan_id": cp["id"], "revision_no": 1, "change_summary": "stale second",
         "expected_control_plan_version": v0},
        fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


# ==========================================================================
# Corner/cross_cutting_layers/occ_fresh_control_plan_version_succeeds_increments
# ==========================================================================
def test_occ_fresh_version_succeeds_and_increments(api):
    """PRD 2.7: "A request to create a revision must carry an
    expected_control_plan_version field holding the version of the target control
    plan that the client last observed."
    PRD 3.10: "a successful create advances the control plan's version."

    Design: Corner/cross_cutting_layers/occ_fresh_control_plan_version_succeeds_increments
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    cp = fx.create_control_plan()
    # rev #1 created + approved (current_revision_no=1), version re-read.
    fx.create_and_approve_revision(eng["id"], mgr["id"], cp["id"], 1)
    v1 = fx.read_control_plan_version(cp["id"])
    rev2 = get_success_data(api.create_control_plan_revision(
        {"control_plan_id": cp["id"], "revision_no": 2, "change_summary": "rev2",
         "expected_control_plan_version": v1},
        fx.make_engineer_headers(eng["id"])))
    assert rev2["status"] == "DRAFT"
    v2 = fx.read_control_plan_version(cp["id"])
    assert v2 > v1


# ==========================================================================
# Corner/cross_cutting_layers/derived_needs_review_set_on_control_plan_revision_approve
# ==========================================================================
def test_derived_needs_review_set_on_revision_approve(api):
    """PRD 3.10: "On approval the system sets the parent control plan's
    current_revision_no to the approved revision_no, cascades a needs_review of
    true onto every inspection plan whose control_plan_id points at that control
    plan ..."

    Design: Corner/cross_cutting_layers/derived_needs_review_set_on_control_plan_revision_approve
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    cp, rev1, ip = fx.setup_control_plan_with_rev1_and_inspection_plan(eng["id"], mgr["id"])
    before = validate_success(api.get_inspection_plan(ip["id"], fx.make_manager_headers(mgr["id"])))
    assert before["needs_review"] is False
    fx.create_and_approve_revision(eng["id"], mgr["id"], cp["id"], 2)
    after = validate_success(api.get_inspection_plan(ip["id"], fx.make_manager_headers(mgr["id"])))
    assert after["needs_review"] is True


# ==========================================================================
# Corner/cross_cutting_layers/rate_threshold_one_reject_stays_normal
# ==========================================================================
def test_rate_threshold_one_reject_stays_normal(api):
    """PRD 3.6: "if the running consecutive_rejects reaches 2, the plan's
    severity_mode switches from NORMAL to TIGHTENED."

    Design: Corner/cross_cutting_layers/rate_threshold_one_reject_stays_normal
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    lot = fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=3)
    assert lot["status"] == "REJECTED"
    plan = validate_success(api.get_inspection_plan(ip["id"], fx.make_inspector_headers(inspector["id"])))
    assert plan["consecutive_rejects"] == 1
    assert plan["severity_mode"] == "NORMAL"


# ==========================================================================
# Corner/cross_cutting_layers/rate_threshold_accept_resets_consecutive_rejects
# ==========================================================================
def test_rate_threshold_accept_resets_consecutive_rejects(api):
    """PRD 3.6: "the lot is ACCEPTED: this increments the supplier's
    lots_inspected, resets the inspection plan's consecutive_rejects to 0, and
    recomputes the supplier's quality rating."

    Design: Corner/cross_cutting_layers/rate_threshold_accept_resets_consecutive_rejects
    """
    inspector, supplier, cp, ip = fx.setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII")
    fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=3)  # reject -> cr=1
    accepted = fx.run_lot(inspector["id"], ip["id"], supplier["id"], defects_found=0)  # accept -> cr=0
    assert accepted["status"] == "ACCEPTED"
    plan = validate_success(api.get_inspection_plan(ip["id"], fx.make_inspector_headers(inspector["id"])))
    assert plan["consecutive_rejects"] == 0


# ==========================================================================
# Corner/consistency_model/immediate_consistency_disposition_response_reflects_computed_cost
# ==========================================================================
def test_immediate_consistency_disposition_response_reflects_cost(api):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD 3.3: "for SCRAP, the base component is the full unit_cost_cents, since the
    entire unit value is lost and no rework labour is incurred"

    Design: Corner/consistency_model/immediate_consistency_disposition_response_reflects_computed_cost
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=2,
                             unit_cost_cents=500, part_number="P-IM2")
    # SCRAP MAJOR: 2 * round_half_up(500*1.0) = 1000
    immediate = validate_success(api.disposition_ncr(ncr["id"], {"disposition": "SCRAP"}, fx.make_manager_headers(mgr["id"])))
    assert immediate["cost_of_quality_cents"] == 1000
    reread = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert reread["cost_of_quality_cents"] == 1000
