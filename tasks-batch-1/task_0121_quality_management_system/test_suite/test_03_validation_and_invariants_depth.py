"""Depth tests for validation precedence, cross-entity state dependency,
temporal overlap, and compensating invariants (queue A — Difficulty).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)
from test_helpers import fixtures as fx


# ==========================================================================
# Difficulty/priority_pair_validation_conflict/disposition_state_beats_segregation_of_duties
# ==========================================================================
def test_disposition_state_check_beats_segregation_of_duties(api):
    """PRD 2.10: "On a disposition, for example, this means the state check is
    evaluated before the segregation-of-duties check, which is evaluated before
    the deviation-required check for USE_AS_IS, which is evaluated before the
    source check for RETURN_TO_SUPPLIER."
    PRD 2.10: "Only after these pass is the target's state checked against the
    requested transition, yielding ERR_INVALID_STATE if the transition is not
    defined from the current state."

    Design: Difficulty/priority_pair_validation_conflict/disposition_state_beats_segregation_of_duties
    """
    # Acting QM raised the NCR (created_by == them) AND the NCR is still DRAFT.
    # Both p6(state) and p8(SoD) fail; the lower-priority state check wins.
    qm = fx.create_personnel(role="QUALITY_MANAGER")
    sup = fx.create_supplier()
    # raise as engineer-role-call but stamp created_by to the QM's own id (shared raise).
    draft = get_success_data(api.create_ncr(
        {"title": "draft ncr", "source": "SUPPLIER", "severity": "MAJOR", "defect_qty": 2,
         "unit_cost_cents": 1000, "part_number": "P-P5A", "supplier_id": sup["id"]},
        fx.make_engineer_headers(qm["id"])))
    resp = api.disposition_ncr(draft["id"], {"disposition": "REWORK"}, fx.make_manager_headers(qm["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value


def test_disposition_on_draft_self_authored_reports_invalid_state_not_sod(api):
    """PRD 2.10: "the state check is evaluated before the segregation-of-duties
    check, which is evaluated before the deviation-required check for USE_AS_IS,
    which is evaluated before the source check for RETURN_TO_SUPPLIER."

    Design: Difficulty/priority_pair_validation_conflict/disposition_state_beats_segregation_of_duties
    """
    qm = fx.create_personnel(role="QUALITY_MANAGER")
    sup = fx.create_supplier()
    draft = get_success_data(api.create_ncr(
        {"title": "draft ncr 2", "source": "SUPPLIER", "severity": "MAJOR", "defect_qty": 2,
         "unit_cost_cents": 1000, "part_number": "P-P5A2", "supplier_id": sup["id"]},
        fx.make_engineer_headers(qm["id"])))
    resp = api.disposition_ncr(draft["id"], {"disposition": "REWORK"}, fx.make_manager_headers(qm["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ==========================================================================
# Difficulty/priority_pair_validation_conflict/scar_ack_state_beats_resource_owner
# ==========================================================================
def test_scar_ack_state_check_beats_resource_owner(api):
    """PRD 2.10: "Only after these pass is the target's state checked against the
    requested transition, yielding ERR_INVALID_STATE if the transition is not
    defined from the current state. Resource-ownership checks
    (ERR_NOT_RESOURCE_OWNER) and then segregation-of-duties checks
    (ERR_SEGREGATION_OF_DUTIES) follow ..."

    Design: Difficulty/priority_pair_validation_conflict/scar_ack_state_beats_resource_owner
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    owner = fx.create_supplier()
    other = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=owner["id"], severity="MAJOR", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-P5B")
    scar = fx.open_scar(mgr["id"], ncr["id"], owner["id"])
    # cancel the SCAR -> CANCELLED (state no longer OPEN)
    get_success_data(api.transition_scar(scar["id"], {"action": "CANCEL"}, fx.make_manager_headers(mgr["id"])))
    # the WRONG supplier tries to ACKNOWLEDGE a CANCELLED scar: p6(state) beats p7(owner)
    resp = api.transition_scar(scar["id"], {"action": "ACKNOWLEDGE"}, fx.make_supplier_user_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_NOT_RESOURCE_OWNER.value


def test_scar_ack_on_cancelled_by_nonowner_yields_state_not_owner(api):
    """PRD 2.10: "Resource-ownership checks (ERR_NOT_RESOURCE_OWNER) and then
    segregation-of-duties checks (ERR_SEGREGATION_OF_DUTIES) follow, and only
    after all of these do the remaining business rules specific to each operation
    apply."

    Design: Difficulty/priority_pair_validation_conflict/scar_ack_state_beats_resource_owner
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    owner = fx.create_supplier()
    other = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=owner["id"], severity="MAJOR", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-P5B2")
    scar = fx.open_scar(mgr["id"], ncr["id"], owner["id"])
    get_success_data(api.transition_scar(scar["id"], {"action": "CANCEL"}, fx.make_manager_headers(mgr["id"])))
    resp = api.transition_scar(scar["id"], {"action": "ACKNOWLEDGE"}, fx.make_supplier_user_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ==========================================================================
# Difficulty/cross_entity_state_dependency/finding_close_requires_escalated_ncr_closed
# ==========================================================================
def test_finding_close_blocked_while_escalated_ncr_open(api):
    """PRD 3.8: "A finding in NCR_RAISED can be closed only once the
    nonconformance escalated from it (the one referenced by its raised_ncr_id)
    has reached CLOSED; closing it before then is rejected with
    ERR_FINDING_NCR_OPEN (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/finding_close_requires_escalated_ncr_closed
    """
    auditor, engineer, audit, finding, ncr = fx.setup_audit_finding_with_open_ncr()
    # finding is NCR_RAISED, escalated NCR is OPEN (not CLOSED)
    resp = api.transition_audit_finding(finding["id"], {"action": "CLOSE"}, fx.make_auditor_headers(auditor["id"]))
    validate_error(resp, ApiErrorId.ERR_FINDING_NCR_OPEN.value, 409)
    after = validate_success(api.get_audit_finding(finding["id"], fx.make_auditor_headers(auditor["id"])))
    assert after["status"] == "NCR_RAISED"


def test_finding_remains_ncr_raised_after_blocked_close(api):
    """PRD 3.8: "A finding in NCR_RAISED can be closed only once the
    nonconformance escalated from it (the one referenced by its raised_ncr_id)
    has reached CLOSED; closing it before then is rejected with
    ERR_FINDING_NCR_OPEN (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/finding_close_requires_escalated_ncr_closed
    """
    auditor, engineer, audit, finding, ncr = fx.setup_audit_finding_with_open_ncr()
    resp = api.transition_audit_finding(finding["id"], {"action": "CLOSE"}, fx.make_auditor_headers(auditor["id"]))
    validate_error(resp, ApiErrorId.ERR_FINDING_NCR_OPEN.value, 409)


# ==========================================================================
# Difficulty/cross_entity_state_dependency/use_as_is_disposition_requires_approved_in_window_deviation
# ==========================================================================
def test_use_as_is_succeeds_with_approved_in_window_deviation(api):
    """PRD 3.3: "A choice of USE_AS_IS is permitted only when an APPROVED
    deviation exists for this report whose max_qty is at least the report's
    defect_qty and whose validity window contains the current server clock — that
    is, the clock is at or after the deviation's valid_from and strictly before
    its valid_to; absent such a deviation the request is rejected with
    ERR_DEVIATION_REQUIRED (HTTP 409)."
    PRD 3.3: "When USE_AS_IS succeeds, the report's deviation_id is set to the id
    of the approving deviation."

    Design: Difficulty/cross_entity_state_dependency/use_as_is_disposition_requires_approved_in_window_deviation
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    fx.set_clock("2026-06-15T00:00:00Z")
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=4,
                             unit_cost_cents=1000, part_number="P-C72")
    dev = fx.approved_deviation(eng["id"], mgr["id"], ncr["id"], sup["id"], "P-C72",
                                valid_from="2026-06-01T00:00:00Z", valid_to="2026-12-01T00:00:00Z", max_qty=5)
    assert dev["status"] == "APPROVED"
    disp = validate_success(api.disposition_ncr(ncr["id"], {"disposition": "USE_AS_IS"}, fx.make_manager_headers(mgr["id"])))
    assert disp["status"] == "DISPOSITIONED"
    assert disp["disposition"] == "USE_AS_IS"
    assert disp["deviation_id"] == dev["id"]
    # USE_AS_IS cost: 4 * round_half_up(round_half_up(1000*0.30)*0.5) = 4 * 150 = 600
    assert disp["cost_of_quality_cents"] == 600


def test_use_as_is_sets_deviation_id_to_approving_deviation(api):
    """PRD 3.3: "When USE_AS_IS succeeds, the report's deviation_id is set to the
    id of the approving deviation."

    Design: Difficulty/cross_entity_state_dependency/use_as_is_disposition_requires_approved_in_window_deviation
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    fx.set_clock("2026-06-15T00:00:00Z")
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=4,
                             unit_cost_cents=1000, part_number="P-C72b")
    dev = fx.approved_deviation(eng["id"], mgr["id"], ncr["id"], sup["id"], "P-C72b",
                                valid_from="2026-06-01T00:00:00Z", valid_to="2026-12-01T00:00:00Z", max_qty=5)
    disp = validate_success(api.disposition_ncr(ncr["id"], {"disposition": "USE_AS_IS"}, fx.make_manager_headers(mgr["id"])))
    assert disp["deviation_id"] == dev["id"]


# ==========================================================================
# Difficulty/resource_temporal_overlap/deviation_half_open_window_overlap_rejected
# ==========================================================================
def test_deviation_overlapping_window_rejected(api):
    """PRD 3.9: "Approving it moves it from REQUESTED to APPROVED and stamps
    approved_by_personnel_id with the acting manager, but only if the new waiver
    does not overlap an existing APPROVED deviation for the same supplier_id and
    part_number. Two half-open windows overlap when the first's valid_from is
    strictly before the second's valid_to and the second's valid_from is strictly
    before the first's valid_to; an overlap is rejected with
    ERR_DEVIATION_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/deviation_half_open_window_overlap_rejected
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    fx.set_clock("2026-06-15T00:00:00Z")
    ncra = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=2,
                              unit_cost_cents=500, part_number="P-O1")
    ncrb = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=2,
                              unit_cost_cents=500, part_number="P-O1")
    # Deviation A approved: [2026-06-01, 2026-09-01)
    fx.approved_deviation(eng["id"], mgr["id"], ncra["id"], sup["id"], "P-O1",
                          valid_from="2026-06-01T00:00:00Z", valid_to="2026-09-01T00:00:00Z", max_qty=5)
    # Deviation B requested: [2026-08-01, 2026-10-01) overlaps A
    devb = fx.request_deviation(eng["id"], ncrb["id"], sup["id"], "P-O1",
                                valid_from="2026-08-01T00:00:00Z", valid_to="2026-10-01T00:00:00Z", max_qty=5)
    resp = api.transition_deviation(devb["id"], {"action": "APPROVE"}, fx.make_manager_headers(mgr["id"]))
    validate_error(resp, ApiErrorId.ERR_DEVIATION_OVERLAP.value, 409)
    after = validate_success(api.get_deviation(devb["id"], fx.make_manager_headers(mgr["id"])))
    assert after["status"] == "REQUESTED"


def test_deviation_overlap_leaves_second_requested(api):
    """PRD 3.9: "Two half-open windows overlap when the first's valid_from is
    strictly before the second's valid_to and the second's valid_from is strictly
    before the first's valid_to; an overlap is rejected with
    ERR_DEVIATION_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/deviation_half_open_window_overlap_rejected
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    fx.set_clock("2026-06-15T00:00:00Z")
    ncra = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=2,
                              unit_cost_cents=500, part_number="P-O1b")
    ncrb = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MINOR", defect_qty=2,
                              unit_cost_cents=500, part_number="P-O1b")
    fx.approved_deviation(eng["id"], mgr["id"], ncra["id"], sup["id"], "P-O1b",
                          valid_from="2026-06-01T00:00:00Z", valid_to="2026-09-01T00:00:00Z", max_qty=5)
    devb = fx.request_deviation(eng["id"], ncrb["id"], sup["id"], "P-O1b",
                                valid_from="2026-08-01T00:00:00Z", valid_to="2026-10-01T00:00:00Z", max_qty=5)
    resp = api.transition_deviation(devb["id"], {"action": "APPROVE"}, fx.make_manager_headers(mgr["id"]))
    validate_error(resp, ApiErrorId.ERR_DEVIATION_OVERLAP.value, 409)


# ==========================================================================
# Difficulty/resource_temporal_overlap/auditor_buffered_window_double_booking_rejected
# ==========================================================================
def test_auditor_buffered_window_double_booking_rejected(api):
    """PRD 3.8: "Starting is rejected with ERR_AUDITOR_DOUBLE_BOOKED (HTTP 409)
    if the audit's window, expanded by a 24-hour buffer on both sides, collides
    with the window of any other non-closed audit (one that is PLANNED or
    IN_PROGRESS) belonging to the same lead_auditor_id."
    PRD 3.8: "Because the buffer is inclusive, windows that merely touch within
    the 24-hour margin do conflict."

    Design: Difficulty/resource_temporal_overlap/auditor_buffered_window_double_booking_rejected
    """
    auditor = fx.create_auditor()
    audit_a = fx.create_in_progress_audit(auditor["id"], title="audit A",
                                          scheduled_from="2026-07-01T00:00:00Z", scheduled_to="2026-07-02T00:00:00Z")
    audit_b = fx.create_planned_audit(auditor["id"], title="audit B",
                                      scheduled_from="2026-07-02T12:00:00Z", scheduled_to="2026-07-03T00:00:00Z")
    resp = api.transition_audit(audit_b["id"], {"action": "START"}, fx.make_auditor_headers(auditor["id"]))
    validate_error(resp, ApiErrorId.ERR_AUDITOR_DOUBLE_BOOKED.value, 409)
    after = validate_success(api.get_audit(audit_b["id"], fx.make_auditor_headers(auditor["id"])))
    assert after["status"] == "PLANNED"


def test_auditor_double_booking_leaves_second_planned(api):
    """PRD 3.8: "Concretely, a collision exists when this audit's scheduled_from
    is at or before the other audit's scheduled_to plus 24 hours, and the other
    audit's scheduled_from is at or before this audit's scheduled_to plus 24
    hours."

    Design: Difficulty/resource_temporal_overlap/auditor_buffered_window_double_booking_rejected
    """
    auditor = fx.create_auditor()
    audit_a = fx.create_in_progress_audit(auditor["id"], title="audit A2",
                                          scheduled_from="2026-07-01T00:00:00Z", scheduled_to="2026-07-02T00:00:00Z")
    audit_b = fx.create_planned_audit(auditor["id"], title="audit B2",
                                      scheduled_from="2026-07-02T12:00:00Z", scheduled_to="2026-07-03T00:00:00Z")
    resp = api.transition_audit(audit_b["id"], {"action": "START"}, fx.make_auditor_headers(auditor["id"]))
    validate_error(resp, ApiErrorId.ERR_AUDITOR_DOUBLE_BOOKED.value, 409)


# ==========================================================================
# Difficulty/compensating_invariant/ncr_open_then_void_conserves_supplier_ncrs_attributed
# ==========================================================================
def test_ncr_open_then_void_conserves_ncrs_attributed(api):
    """PRD 3.2: "If the report's source is SUPPLIER, opening it increments the
    referenced supplier's ncrs_attributed and recomputes that supplier's quality
    rating."
    PRD 3.2: "Voiding an open report releases its reserved budget to zero and, in
    addition, reverses the attribution side effects that opening created: a
    SUPPLIER-sourced report decrements the supplier's ncrs_attributed and
    recomputes the supplier's rating ..."

    Design: Difficulty/compensating_invariant/ncr_open_then_void_conserves_supplier_ncrs_attributed
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-I1")
    mid = validate_success(api.get_supplier(sup["id"], fx.make_manager_headers(mgr["id"])))
    assert mid["ncrs_attributed"] == 1
    assert mid["quality_rating"] == pytest.approx(96.00, abs=0.001)
    # void the OPEN NCR (no CAPA) — QM may void OPEN->VOID
    voided = validate_success(api.void_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    assert voided["status"] == "VOID"
    after = validate_success(api.get_supplier(sup["id"], fx.make_manager_headers(mgr["id"])))
    assert after["ncrs_attributed"] == 0
    assert after["quality_rating"] == pytest.approx(100.00, abs=0.001)
    assert after["approval_status"] == "APPROVED"


def test_ncr_void_restores_supplier_rating_to_100(api):
    """PRD 3.2: "Voiding an open report releases its reserved budget to zero and,
    in addition, reverses the attribution side effects that opening created: a
    SUPPLIER-sourced report decrements the supplier's ncrs_attributed and
    recomputes the supplier's rating ..."

    Design: Difficulty/compensating_invariant/ncr_open_then_void_conserves_supplier_ncrs_attributed
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    ncr = fx.create_open_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=2,
                             unit_cost_cents=1000, part_number="P-I1b")
    validate_success(api.void_ncr(ncr["id"], fx.make_manager_headers(mgr["id"])))
    after = validate_success(api.get_supplier(sup["id"], fx.make_manager_headers(mgr["id"])))
    assert after["quality_rating"] == pytest.approx(100.00, abs=0.001)


# ==========================================================================
# Difficulty/compensating_invariant/scar_open_then_cancel_conserves_supplier_open_scar_count
# ==========================================================================
def test_scar_open_then_cancel_conserves_open_scar_count(api):
    """PRD 3.5: "A new SCAR begins in OPEN status; opening it increments the
    supplier's open_scar_count and recomputes the supplier's quality rating."
    PRD 3.5: "A QualityManager may cancel a SCAR while it is still OPEN, moving
    it from OPEN to CANCELLED, which decrements the supplier's open_scar_count and
    recomputes the supplier's rating."

    Design: Difficulty/compensating_invariant/scar_open_then_cancel_conserves_supplier_open_scar_count
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    # DRAFT NCR (never opened) so ncrs_attributed stays 0
    draft = fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=2,
                                unit_cost_cents=1000, part_number="P-I2")
    scar = fx.open_scar(mgr["id"], draft["id"], sup["id"])
    mid = validate_success(api.get_supplier(sup["id"], fx.make_manager_headers(mgr["id"])))
    assert mid["open_scar_count"] == 1
    assert mid["quality_rating"] == pytest.approx(95.00, abs=0.001)
    cancelled = validate_success(api.transition_scar(scar["id"], {"action": "CANCEL"}, fx.make_manager_headers(mgr["id"])))
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_supplier(sup["id"], fx.make_manager_headers(mgr["id"])))
    assert after["open_scar_count"] == 0
    assert after["ncrs_attributed"] == 0
    assert after["quality_rating"] == pytest.approx(100.00, abs=0.001)


def test_scar_cancel_restores_supplier_rating(api):
    """PRD 3.5: "A QualityManager may cancel a SCAR while it is still OPEN, moving
    it from OPEN to CANCELLED, which decrements the supplier's open_scar_count and
    recomputes the supplier's rating."

    Design: Difficulty/compensating_invariant/scar_open_then_cancel_conserves_supplier_open_scar_count
    """
    eng = fx.create_engineer()
    mgr = fx.create_manager()
    sup = fx.create_supplier()
    draft = fx.create_draft_ncr(eng["id"], supplier_id=sup["id"], severity="MAJOR", defect_qty=2,
                                unit_cost_cents=1000, part_number="P-I2b")
    scar = fx.open_scar(mgr["id"], draft["id"], sup["id"])
    validate_success(api.transition_scar(scar["id"], {"action": "CANCEL"}, fx.make_manager_headers(mgr["id"])))
    after = validate_success(api.get_supplier(sup["id"], fx.make_manager_headers(mgr["id"])))
    assert after["open_scar_count"] == 0
    assert after["quality_rating"] == pytest.approx(100.00, abs=0.001)
