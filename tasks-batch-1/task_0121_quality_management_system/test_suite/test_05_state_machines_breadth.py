"""Breadth tests for state machines: initial states, valid/invalid transitions,
terminal lockdown, idempotency, side effects, sweeps (queue B — Corner,
section state_machines).
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
# Corner/state_machines/ncr_initial_state_draft
# ==========================================================================
def test_ncr_initial_state_draft(api):
    """PRD 3.2: "Raising one creates a NonconformanceReport in DRAFT status with
    its created_by_personnel_id stamped to the acting engineer's X-User-ID and its
    budget_reserved_cents at 0."

    Design: Corner/state_machines/ncr_initial_state_draft
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    ncr = fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=1,
                              unit_cost_cents=100, part_number="P-IS")
    assert ncr["status"] == "DRAFT"
    assert ncr["disposition"] is None


# ==========================================================================
# Corner/state_machines/capa_initial_state_open_step_d1
# ==========================================================================
def test_capa_initial_state_open_step_d1(api):
    """PRD 3.4: "A new CAPA starts in OPEN status with its current_step at D1 and
    its authored_by_personnel_id stamped to the opening engineer."

    Design: Corner/state_machines/capa_initial_state_open_step_d1
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_dispositioned_ncr(eng["id"], mgr["id"], supplier_id=sup["id"],
                                      disposition="REWORK", defect_qty=5, unit_cost_cents=1000,
                                      rework_hours=2.0, part_number="P-CI")
    resp = api.create_capa({"ncr_id": ncr["id"], "title": "init capa"}, fx.make_engineer_headers(eng["id"]))
    capa = validate_success(resp, 201)
    assert capa["status"] == "OPEN"
    assert capa["current_step"] == "D1"
    assert capa["rework_loops"] == 0


# ==========================================================================
# Corner/state_machines/ncr_draft_to_open_valid_transition
# ==========================================================================
def test_ncr_draft_to_open_valid_transition(api):
    """PRD 3.2: "Opening the report advances it from DRAFT to OPEN, and is
    permitted only while it is in DRAFT."

    Design: Corner/state_machines/ncr_draft_to_open_valid_transition
    """
    eng = fx.create_engineer()
    sup = fx.create_supplier()
    ncr = fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=1,
                              unit_cost_cents=100, part_number="P-VT")
    resp = api.open_ncr(ncr["id"], fx.make_engineer_headers(eng["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "OPEN"


# ==========================================================================
# Corner/state_machines/scar_ack_to_responded_valid_transition
# ==========================================================================
def test_scar_ack_to_responded_valid_transition(api):
    """PRD 3.5: "Acknowledging moves the SCAR from OPEN to ACK. Responding from
    ACK moves it to RESPONDED and requires a non-empty response_narrative."

    Design: Corner/state_machines/scar_ack_to_responded_valid_transition
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=1,
                             unit_cost_cents=100, part_number="P-SR")
    scar = fx.open_scar(mgr["id"], ncr["id"], sup["id"])
    su = fx.make_supplier_user_headers(sup["id"])
    get_success_data(api.transition_scar(scar["id"], {"action": "ACKNOWLEDGE"}, su))
    resp = api.transition_scar(scar["id"], {"action": "RESPOND", "response_narrative": "we retooled the press"}, su)
    data = validate_success(resp, 200)
    assert data["status"] == "RESPONDED"


# ==========================================================================
# Corner/state_machines/deviation_requested_to_rejected_valid_transition
# ==========================================================================
def test_deviation_requested_to_rejected_valid_transition(api):
    """PRD 3.9: "Rejecting a deviation moves it from REQUESTED to REJECTED."

    Design: Corner/state_machines/deviation_requested_to_rejected_valid_transition
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=2,
                             unit_cost_cents=500, part_number="P-DVR")
    dev = fx.request_deviation(eng["id"], ncr["id"], sup["id"], "P-DVR")
    resp = api.transition_deviation(dev["id"], {"action": "REJECT"}, fx.make_manager_headers(mgr["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"


# ==========================================================================
# Corner/state_machines/ncr_open_audit_source_sets_finding_ncr_raised
# ==========================================================================
def test_open_audit_source_ncr_sets_finding_ncr_raised(api):
    """PRD 3.2: "If the source is AUDIT, the precondition is that the referenced
    audit finding resolves and is currently OPEN; opening the report drives that
    finding from OPEN to NCR_RAISED and records the new report's id in the
    finding's raised_ncr_id."

    Design: Corner/state_machines/ncr_open_audit_source_sets_finding_ncr_raised
    """
    auditor, audit, finding = fx.setup_audit_with_open_finding(grade="MAJOR")
    eng = fx.create_engineer()
    ncr = fx.create_draft_ncr(eng["id"], source="AUDIT", audit_finding_id=finding["id"],
                              severity="MAJOR", defect_qty=2, unit_cost_cents=1000, part_number="P-SE")
    opened = validate_success(api.open_ncr(ncr["id"], fx.make_engineer_headers(eng["id"])))
    assert opened["status"] == "OPEN"
    finding_after = validate_success(api.get_audit_finding(finding["id"], fx.make_auditor_headers(auditor["id"])))
    assert finding_after["status"] == "NCR_RAISED"
    assert finding_after["raised_ncr_id"] == ncr["id"]


# ==========================================================================
# Corner/state_machines/scar_open_increments_open_scar_count_and_rating
# ==========================================================================
def test_scar_open_increments_open_scar_count_and_rating(api):
    """PRD 3.5: "A new SCAR begins in OPEN status; opening it increments the
    supplier's open_scar_count and recomputes the supplier's quality rating."
    PRD 3.7: "An open-SCAR penalty caps outstanding accountability: it is the
    open_scar_count multiplied by a per-SCAR step of 0.05, but never more than a
    ceiling of 0.20."

    Design: Corner/state_machines/scar_open_increments_open_scar_count_and_rating
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    draft = fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=2,
                                unit_cost_cents=1000, part_number="P-SO")
    fx.open_scar(mgr["id"], draft["id"], sup["id"])
    s = validate_success(api.get_supplier(sup["id"], fx.make_manager_headers(mgr["id"])))
    assert s["open_scar_count"] == 1
    # base 1.0, penalty 0.05 -> raw 0.95 -> 95.00
    assert s["quality_rating"] == pytest.approx(95.00, abs=0.001)


# ==========================================================================
# Corner/state_machines/ncr_open_from_dispositioned_invalid_state
# ==========================================================================
def test_open_dispositioned_ncr_invalid_state(api):
    """PRD 3.2: "Opening the report advances it from DRAFT to OPEN, and is
    permitted only while it is in DRAFT."
    PRD 3.2: "Any transition attempted from a status that does not define it is
    rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/ncr_open_from_dispositioned_invalid_state
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_dispositioned_ncr(eng["id"], mgr["id"], supplier_id=sup["id"],
                                      disposition="SCRAP", defect_qty=2, unit_cost_cents=1000,
                                      part_number="P-IV")
    resp = api.open_ncr(ncr["id"], fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "DISPOSITIONED"


# ==========================================================================
# Corner/state_machines/capa_advance_from_open_without_d1_step_invalid_state
# ==========================================================================
def test_capa_advance_without_d1_step_invalid_state(api):
    """PRD 3.4: "Advancing from OPEN to ROOT_CAUSE requires that at least one step
    with a discipline of D1, D2, or D3 already exists for the CAPA; this advance
    sets current_step to D4."
    PRD 3.4: "Any of these transition actions attempted from a status that does
    not define them is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/capa_advance_from_open_without_d1_step_invalid_state
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_dispositioned_ncr(eng["id"], mgr["id"], supplier_id=sup["id"],
                                      disposition="REWORK", defect_qty=5, unit_cost_cents=1000,
                                      rework_hours=2.0, part_number="P-CA")
    capa = fx.open_capa(eng["id"], ncr["id"])
    resp = api.transition_capa(capa["id"], {"action": "ADVANCE"}, fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_capa(capa["id"], fx.make_engineer_headers(eng["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/state_machines/scar_respond_from_open_without_ack_invalid_state
# ==========================================================================
def test_scar_respond_from_open_invalid_state(api):
    """PRD 3.5: "Acknowledging moves the SCAR from OPEN to ACK. Responding from
    ACK moves it to RESPONDED and requires a non-empty response_narrative."
    PRD 3.5: "Any SCAR action attempted from a status that does not define it is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/scar_respond_from_open_without_ack_invalid_state
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=1,
                             unit_cost_cents=100, part_number="P-SX")
    scar = fx.open_scar(mgr["id"], ncr["id"], sup["id"])
    resp = api.transition_scar(scar["id"], {"action": "RESPOND", "response_narrative": "premature"},
                               fx.make_supplier_user_headers(sup["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_scar(scar["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/state_machines/deviation_approve_from_rejected_terminal_lockdown
# ==========================================================================
def test_deviation_approve_from_rejected_terminal_lockdown(api):
    """PRD 3.9: "its status ranges over REQUESTED, APPROVED, and the terminal
    REJECTED, EXPIRED, and REVOKED"
    PRD 3.9: "A transition attempted from a status that does not define it is
    rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/deviation_approve_from_rejected_terminal_lockdown
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=2,
                             unit_cost_cents=500, part_number="P-TL")
    dev = fx.request_deviation(eng["id"], ncr["id"], sup["id"], "P-TL")
    get_success_data(api.transition_deviation(dev["id"], {"action": "REJECT"}, fx.make_manager_headers(mgr["id"])))
    resp = api.transition_deviation(dev["id"], {"action": "APPROVE"}, fx.make_manager_headers(mgr["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_deviation(dev["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "REJECTED"


# ==========================================================================
# Corner/state_machines/audit_close_from_closed_terminal_lockdown
# ==========================================================================
def test_audit_close_from_closed_terminal_lockdown(api):
    """PRD 3.8: "its status ranges over PLANNED, IN_PROGRESS, and the terminal
    CLOSED"
    PRD 3.6: "A disposition attempted on a lot that is not IN_INSPECTION, or a
    start attempted on a lot that is not PENDING, is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/audit_close_from_closed_terminal_lockdown
    """
    auditor = fx.create_auditor()
    audit = fx.create_in_progress_audit(auditor["id"])
    get_success_data(api.transition_audit(audit["id"], {"action": "CLOSE"}, fx.make_auditor_headers(auditor["id"])))
    resp = api.transition_audit(audit["id"], {"action": "CLOSE"}, fx.make_auditor_headers(auditor["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_audit(audit["id"], fx.make_auditor_headers(auditor["id"])))
    assert after["status"] == "CLOSED"


# ==========================================================================
# Corner/state_machines/ncr_open_twice_second_invalid_state
# ==========================================================================
def test_ncr_open_twice_second_invalid_state(api):
    """PRD 3.2: "Opening the report advances it from DRAFT to OPEN, and is
    permitted only while it is in DRAFT."
    PRD 3.2: "Any transition attempted from a status that does not define it is
    rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/ncr_open_twice_second_invalid_state
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=1,
                             unit_cost_cents=100, part_number="P-ID")
    resp = api.open_ncr(ncr["id"], fx.make_engineer_headers(eng["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/state_machines/capa_open_bubbles_ncr_to_capa_in_progress
# ==========================================================================
def test_capa_open_bubbles_ncr_to_capa_in_progress(api):
    """PRD 3.4: "The first CAPA opened against a report has a side effect on the
    report itself: the system advances that report from DISPOSITIONED to
    CAPA_IN_PROGRESS."

    Design: Corner/state_machines/capa_open_bubbles_ncr_to_capa_in_progress
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_dispositioned_ncr(eng["id"], mgr["id"], supplier_id=sup["id"],
                                      disposition="REWORK", defect_qty=5, unit_cost_cents=1000,
                                      rework_hours=2.0, part_number="P-BU")
    capa = validate_success(api.create_capa({"ncr_id": ncr["id"], "title": "bu 8d"},
                                            fx.make_engineer_headers(eng["id"])), 201)
    after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "CAPA_IN_PROGRESS"


# ==========================================================================
# Corner/state_machines/revision_approve_supersedes_prior_and_flags_inspection_plans
# ==========================================================================
def test_revision_approve_supersedes_prior_and_flags_plans(api):
    """PRD 3.10: "On approval the system sets the parent control plan's
    current_revision_no to the approved revision_no, cascades a needs_review of
    true onto every inspection plan whose control_plan_id points at that control
    plan, and supersedes any prior APPROVED revision of the same plan by moving it
    from APPROVED to SUPERSEDED."

    Design: Corner/state_machines/revision_approve_supersedes_prior_and_flags_inspection_plans
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    cp, rev1, ip = fx.setup_control_plan_with_rev1_and_inspection_plan(eng["id"], mgr["id"])
    rev2 = fx.create_and_approve_revision(eng["id"], mgr["id"], cp["id"], 2)
    cp_after = validate_success(api.get_control_plan(cp["id"], fx.make_manager_headers(mgr["id"])))
    assert cp_after["current_revision_no"] == 2
    assert rev2["status"] == "APPROVED"
    rev1_after = next(
        r for r in validate_paginated(api.list_control_plan_revisions(cp["id"], fx.make_manager_headers(mgr["id"])))[0]
        if r["id"] == rev1["id"]
    )
    assert rev1_after["status"] == "SUPERSEDED"
    ip_after = validate_success(api.get_inspection_plan(ip["id"], fx.make_manager_headers(mgr["id"])))
    assert ip_after["needs_review"] is True


# ==========================================================================
# Corner/state_machines/clock_sweep_expires_approved_deviation_past_valid_to
# ==========================================================================
def test_clock_sweep_expires_approved_deviation(api):
    """PRD 3.9: "When the server clock is advanced (see below), the system sweeps
    every APPROVED deviation whose valid_to is at or before the new clock value
    and transitions each from APPROVED to EXPIRED."

    Design: Corner/state_machines/clock_sweep_expires_approved_deviation_past_valid_to
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    fx.set_clock("2026-06-15T00:00:00Z")
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=2,
                             unit_cost_cents=500, part_number="P-EX")
    dev = fx.approved_deviation(eng["id"], mgr["id"], ncr["id"], sup["id"], "P-EX",
                                valid_from="2026-06-01T00:00:00Z", valid_to="2026-07-01T00:00:00Z", max_qty=5)
    assert dev["status"] == "APPROVED"
    fx.set_clock("2026-07-02T00:00:00Z")
    after = validate_success(api.get_deviation(dev["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "EXPIRED"


# ==========================================================================
# Corner/state_machines/deviation_revoke_blocked_when_bound_to_live_use_as_is_ncr
# ==========================================================================
def test_deviation_revoke_blocked_when_bound_to_live_use_as_is(api):
    """PRD 3.9: "Revoking an approved deviation moves it from APPROVED to REVOKED,
    but is blocked if the deviation is still in live use — that is, if any
    nonconformance has its deviation_id pointing at this deviation, was
    dispositioned USE_AS_IS, and is not yet CLOSED or VOID — in which case the
    revoke is rejected with ERR_DEVIATION_IN_USE (HTTP 409)."

    Design: Corner/state_machines/deviation_revoke_blocked_when_bound_to_live_use_as_is_ncr
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    fx.set_clock("2026-06-15T00:00:00Z")
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=4,
                             unit_cost_cents=1000, part_number="P-DU")
    dev = fx.approved_deviation(eng["id"], mgr["id"], ncr["id"], sup["id"], "P-DU",
                                valid_from="2026-06-01T00:00:00Z", valid_to="2026-12-01T00:00:00Z", max_qty=5)
    get_success_data(api.disposition_ncr(ncr["id"], {"disposition": "USE_AS_IS"}, fx.make_manager_headers(mgr["id"])))
    resp = api.transition_deviation(dev["id"], {"action": "REVOKE"}, fx.make_manager_headers(mgr["id"]))
    validate_error(resp, ApiErrorId.ERR_DEVIATION_IN_USE.value, 409)
    after = validate_success(api.get_deviation(dev["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "APPROVED"


# ==========================================================================
# Corner/state_machines/finding_close_open_non_observation_requires_ncr
# ==========================================================================
def test_finding_close_open_major_requires_ncr(api):
    """PRD 3.8: "A finding still in OPEN may be closed directly only when its
    grade is OBSERVATION — observations alone may close without an escalated
    nonconformance — and an attempt to close a non-observation finding directly
    from OPEN is rejected with ERR_FINDING_REQUIRES_NCR (HTTP 409)."

    Design: Corner/state_machines/finding_close_open_non_observation_requires_ncr
    """
    auditor, audit, finding = fx.setup_audit_with_open_finding(grade="MAJOR")
    resp = api.transition_audit_finding(finding["id"], {"action": "CLOSE"}, fx.make_auditor_headers(auditor["id"]))
    validate_error(resp, ApiErrorId.ERR_FINDING_REQUIRES_NCR.value, 409)
    after = validate_success(api.get_audit_finding(finding["id"], fx.make_auditor_headers(auditor["id"])))
    assert after["status"] == "OPEN"


# ==========================================================================
# Corner/state_machines/finding_close_open_observation_succeeds_decrements_count
# ==========================================================================
def test_finding_close_open_observation_decrements_count(api):
    """PRD 3.8: "A finding still in OPEN may be closed directly only when its
    grade is OBSERVATION — observations alone may close without an escalated
    nonconformance ..."
    PRD 3.8: "Each of closing from NCR_RAISED, closing an observation from OPEN,
    and voiding from OPEN decrements the parent audit's open_finding_count."

    Design: Corner/state_machines/finding_close_open_observation_succeeds_decrements_count
    """
    auditor, audit, finding = fx.setup_audit_with_open_finding(grade="OBSERVATION")
    closed = validate_success(api.transition_audit_finding(finding["id"], {"action": "CLOSE"}, fx.make_auditor_headers(auditor["id"])))
    assert closed["status"] == "CLOSED"
    audit_after = validate_success(api.get_audit(audit["id"], fx.make_auditor_headers(auditor["id"])))
    assert audit_after["open_finding_count"] == 0


# ==========================================================================
# Corner/state_machines/finding_void_from_open_decrements_count
# ==========================================================================
def test_finding_void_from_open_decrements_count(api):
    """PRD 3.8: "A finding in OPEN may also be voided."
    PRD 3.8: "Each of closing from NCR_RAISED, closing an observation from OPEN,
    and voiding from OPEN decrements the parent audit's open_finding_count."

    Design: Corner/state_machines/finding_void_from_open_decrements_count
    """
    auditor, audit, finding = fx.setup_audit_with_open_finding(grade="MINOR")
    voided = validate_success(api.transition_audit_finding(finding["id"], {"action": "VOID"}, fx.make_auditor_headers(auditor["id"])))
    assert voided["status"] == "VOID"
    audit_after = validate_success(api.get_audit(audit["id"], fx.make_auditor_headers(auditor["id"])))
    assert audit_after["open_finding_count"] == 0


# ==========================================================================
# Corner/state_machines/scar_reject_response_cycles_back_to_responded
# ==========================================================================
def test_scar_reject_response_cycles_back_to_responded(api):
    """PRD 3.5: "rejects it, moving it from RESPONDED to REJECTED_RESPONSE and
    incrementing rejection_count by one. A rejected SCAR loops back: the owning
    SupplierUser may respond again, moving it from REJECTED_RESPONSE to RESPONDED,
    once more requiring a non-empty response_narrative."

    Design: Corner/state_machines/scar_reject_response_cycles_back_to_responded
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=1,
                             unit_cost_cents=100, part_number="P-SC")
    scar = fx.open_scar(mgr["id"], ncr["id"], sup["id"])
    su = fx.make_supplier_user_headers(sup["id"])
    mh = fx.make_manager_headers(mgr["id"])
    get_success_data(api.transition_scar(scar["id"], {"action": "ACKNOWLEDGE"}, su))
    get_success_data(api.transition_scar(scar["id"], {"action": "RESPOND", "response_narrative": "first attempt"}, su))
    get_success_data(api.transition_scar(scar["id"], {"action": "REJECT_RESPONSE"}, mh))
    looped = validate_success(api.transition_scar(scar["id"], {"action": "RESPOND", "response_narrative": "second attempt"}, su))
    assert looped["status"] == "RESPONDED"
    assert looped["rejection_count"] == 1


# ==========================================================================
# Corner/state_machines/capa_close_ineffective_no_ncr_cascade
# ==========================================================================
def test_capa_close_ineffective_no_ncr_cascade(api):
    """PRD 3.4: "Closing the CAPA as ineffective carries no effectiveness
    threshold and no NCR cascade: the CAPA moves from EFFECTIVENESS_CHECK to
    CLOSED_INEFFECTIVE, the final effectiveness is still computed and recorded,
    but the parent report remains in CAPA_IN_PROGRESS."

    Design: Corner/state_machines/capa_close_ineffective_no_ncr_cascade
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # recurred_defects=2, defect_qty=5 -> final = 1 - 2/5 = 0.60
    ncr, capa = fx.capa_to_effectiveness_check(eng["id"], mgr["id"], sup["id"],
                                               containment_count=3, recurred_defects=2,
                                               defect_qty=5, part_number="P-IN")
    closed = validate_success(api.transition_capa(capa["id"], {"action": "CLOSE_INEFFECTIVE"}, fx.make_manager_headers(mgr["id"])))
    assert closed["status"] == "CLOSED_INEFFECTIVE"
    assert closed["final_effectiveness"] == 0.60
    ncr_after = validate_success(api.get_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert ncr_after["status"] == "CAPA_IN_PROGRESS"
