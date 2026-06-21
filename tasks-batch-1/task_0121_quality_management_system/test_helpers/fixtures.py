"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness starts each test against an empty database). Helpers use
get_success_data() internally so setup failures surface as clear "Setup step
failed" errors. Identity is threaded: entity_backed actors always act under
make_<role>_headers(entity_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_engineer_headers,
    make_manager_headers,
    make_inspector_headers,
    make_auditor_headers,
    make_supplier_user_headers,
)

OPERATOR = TEST_USERS["manager_headers"]


# ==========================================================================
# Tier 0 — atomic genesis helpers
# ==========================================================================
def create_personnel(role="QUALITY_ENGINEER", **overrides) -> dict:
    """Register a Personnel actor. Returns the Personnel record."""
    resp = api_client.create_personnel(f.create_personnel_payload(role=role, **overrides), OPERATOR)
    return get_success_data(resp)


def create_supplier(**overrides) -> dict:
    """Create a Supplier. Returns the Supplier record."""
    resp = api_client.create_supplier(f.create_supplier_payload(**overrides), OPERATOR)
    return get_success_data(resp)


def create_control_plan(**overrides) -> dict:
    """Create a ControlPlan. Returns the ControlPlan record."""
    resp = api_client.create_control_plan(f.create_control_plan_payload(**overrides), OPERATOR)
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    """Advance the server clock (operator call)."""
    return api_client.set_clock({"to_iso8601": to_iso8601}, OPERATOR)


def create_engineer():
    return create_personnel(role="QUALITY_ENGINEER")


def create_manager():
    return create_personnel(role="QUALITY_MANAGER")


def create_inspector():
    return create_personnel(role="INSPECTOR")


def create_auditor():
    return create_personnel(role="AUDITOR")


# ==========================================================================
# Tier 1 — NCR lifecycle progression
# ==========================================================================
def create_draft_ncr(engineer_id, supplier_id=None, **ncr_overrides) -> dict:
    """Create a DRAFT NCR raised by the given engineer. Returns the NCR."""
    payload = f.create_ncr_payload(**ncr_overrides)
    if supplier_id is not None and "supplier_id" not in ncr_overrides:
        payload["supplier_id"] = supplier_id
    resp = api_client.create_ncr(payload, make_engineer_headers(engineer_id))
    return get_success_data(resp)


def create_open_ncr(engineer_id, supplier_id=None, **ncr_overrides) -> dict:
    """Create + open an NCR (DRAFT->OPEN). Returns the OPEN NCR."""
    ncr = create_draft_ncr(engineer_id, supplier_id=supplier_id, **ncr_overrides)
    resp = api_client.open_ncr(ncr["id"], make_engineer_headers(engineer_id))
    return get_success_data(resp)


def create_dispositioned_ncr(engineer_id, manager_id, supplier_id=None,
                             disposition="REWORK", **ncr_overrides) -> dict:
    """Create -> open -> disposition an NCR. manager_id must differ from engineer_id (SoD).
    Returns the DISPOSITIONED NCR."""
    ncr = create_open_ncr(engineer_id, supplier_id=supplier_id, **ncr_overrides)
    resp = api_client.disposition_ncr(
        ncr["id"], {"disposition": disposition}, make_manager_headers(manager_id)
    )
    return get_success_data(resp)


# ==========================================================================
# Tier 2 — CAPA lifecycle helpers
# ==========================================================================
def open_capa(engineer_id, ncr_id, **overrides) -> dict:
    """Open a CAPA against a DISPOSITIONED NCR. Returns the CAPA."""
    resp = api_client.create_capa(f.create_capa_payload(ncr_id, **overrides), make_engineer_headers(engineer_id))
    return get_success_data(resp)


def record_step(actor_id, capa_id, role="engineer", **step_overrides):
    """Record an 8D step. role in {'engineer','manager'}. Returns the step."""
    headers = make_engineer_headers(actor_id) if role == "engineer" else make_manager_headers(actor_id)
    resp = api_client.create_capa_step(capa_id, f.create_step_payload(**step_overrides), headers)
    return get_success_data(resp)


def capa_to_verification(engineer_id, manager_id, supplier_id, containment_count=3,
                         defect_qty=5, **ncr_overrides):
    """Build a CAPA driven to VERIFICATION (provisional_effectiveness computed).

    Steps: create dispositioned NCR (REWORK) -> open CAPA -> D1 + D4(containment)
    -> ADVANCE (OPEN->ROOT_CAUSE) -> ADVANCE (ROOT_CAUSE->VERIFICATION).
    Returns (ncr, capa).
    """
    ncr = create_dispositioned_ncr(
        engineer_id, manager_id, supplier_id=supplier_id,
        disposition="REWORK", defect_qty=defect_qty, rework_hours=2.0, **ncr_overrides
    )
    capa = open_capa(engineer_id, ncr["id"])
    eh = make_engineer_headers(engineer_id)
    get_success_data(api_client.create_capa_step(capa["id"], f.create_step_payload(discipline="D1", narrative="team"), eh))
    get_success_data(api_client.create_capa_step(
        capa["id"], f.create_step_payload(discipline="D4", narrative="root cause", containment_count=containment_count), eh))
    get_success_data(api_client.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    capa = get_success_data(api_client.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    return ncr, capa


def capa_to_effectiveness_check(engineer_id, manager_id, supplier_id, containment_count=3,
                                recurred_defects=0, defect_qty=5, **ncr_overrides):
    """Build a CAPA driven to EFFECTIVENESS_CHECK (verified by manager).

    Records D1/D4(containment)/D8(recurred) BEFORE advancing, advances to
    VERIFICATION, then VERIFY (provisional>=0.50 required). Returns (ncr, capa).
    """
    ncr = create_dispositioned_ncr(
        engineer_id, manager_id, supplier_id=supplier_id,
        disposition="REWORK", defect_qty=defect_qty, rework_hours=2.0, **ncr_overrides
    )
    capa = open_capa(engineer_id, ncr["id"])
    eh = make_engineer_headers(engineer_id)
    get_success_data(api_client.create_capa_step(capa["id"], f.create_step_payload(discipline="D1", narrative="team"), eh))
    get_success_data(api_client.create_capa_step(
        capa["id"], f.create_step_payload(discipline="D4", narrative="root cause", containment_count=containment_count), eh))
    get_success_data(api_client.create_capa_step(
        capa["id"], f.create_step_payload(discipline="D8", narrative="monitor", recurred_defects=recurred_defects), eh))
    get_success_data(api_client.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    get_success_data(api_client.transition_capa(capa["id"], {"action": "ADVANCE"}, eh))
    capa = get_success_data(api_client.transition_capa(capa["id"], {"action": "VERIFY"}, make_manager_headers(manager_id)))
    return ncr, capa


# ==========================================================================
# Tier 3 — SCAR lifecycle helpers
# ==========================================================================
def open_scar(manager_id, ncr_id, supplier_id, **overrides) -> dict:
    """Open a SCAR (QualityManager). Returns the SCAR."""
    resp = api_client.create_scar(
        f.create_scar_payload(ncr_id, supplier_id, **overrides), make_manager_headers(manager_id)
    )
    return get_success_data(resp)


def scar_to_accepted_response(manager_id, supplier_id, ncr_id):
    """Drive a SCAR OPEN -> ACK -> RESPONDED -> ACCEPTED_RESPONSE. Returns the SCAR."""
    scar = open_scar(manager_id, ncr_id, supplier_id)
    su = make_supplier_user_headers(supplier_id)
    mh = make_manager_headers(manager_id)
    get_success_data(api_client.transition_scar(scar["id"], {"action": "ACKNOWLEDGE"}, su))
    get_success_data(api_client.transition_scar(scar["id"], {"action": "RESPOND", "response_narrative": "fixed"}, su))
    scar = get_success_data(api_client.transition_scar(scar["id"], {"action": "ACCEPT_RESPONSE"}, mh))
    return scar


# ==========================================================================
# Tier 4 — Inspection plan / lot helpers + threshold targeting
# ==========================================================================
def setup_inspection_plan(lot_size=120, aql_pct=4.0, inspection_level="GII"):
    """Create inspector + supplier + control plan + inspection plan.
    Returns (inspector, supplier, control_plan, inspection_plan)."""
    inspector = create_inspector()
    supplier = create_supplier()
    cp = create_control_plan()
    ip = get_success_data(api_client.create_inspection_plan(
        f.create_inspection_plan_payload(cp["id"], lot_size=lot_size, aql_pct=aql_pct,
                                         inspection_level=inspection_level),
        OPERATOR,
    ))
    return inspector, supplier, cp, ip


def create_pending_lot(inspector_id, inspection_plan_id, supplier_id, actual_lot_size=120) -> dict:
    resp = api_client.create_inspection_lot(
        f.create_inspection_lot_payload(inspection_plan_id, supplier_id, actual_lot_size=actual_lot_size),
        make_inspector_headers(inspector_id),
    )
    return get_success_data(resp)


def create_in_inspection_lot(inspector_id, inspection_plan_id, supplier_id, actual_lot_size=120) -> dict:
    """Create a lot and START it (PENDING->IN_INSPECTION). Returns the lot (sampling frozen)."""
    lot = create_pending_lot(inspector_id, inspection_plan_id, supplier_id, actual_lot_size)
    resp = api_client.transition_inspection_lot(lot["id"], {"action": "START"}, make_inspector_headers(inspector_id))
    return get_success_data(resp)


def disposition_lot(inspector_id, lot_id, defects_found) -> dict:
    resp = api_client.transition_inspection_lot(
        lot_id, {"action": "DISPOSITION", "defects_found": defects_found}, make_inspector_headers(inspector_id)
    )
    return get_success_data(resp)


def run_lot(inspector_id, inspection_plan_id, supplier_id, defects_found, actual_lot_size=120) -> dict:
    """Create -> START -> DISPOSITION a single lot. Returns the terminal lot."""
    lot = create_in_inspection_lot(inspector_id, inspection_plan_id, supplier_id, actual_lot_size)
    return disposition_lot(inspector_id, lot["id"], defects_found)


def setup_plan_with_n_rejected_lots(n, lot_size=120, aql_pct=4.0, inspection_level="GII",
                                    reject_defects=3):
    """Create plan and push n lots to REJECTED (each defects_found high enough to reject).

    With lot_size=120 (letter F), aql_pct=4.0, NORMAL Ac=2: defects_found=3 rejects.
    After 2 rejects the plan flips to TIGHTENED. Returns
    (inspector, supplier, control_plan, inspection_plan)."""
    inspector, supplier, cp, ip = setup_inspection_plan(lot_size, aql_pct, inspection_level)
    for _ in range(n):
        run_lot(inspector["id"], ip["id"], supplier["id"], reject_defects)
    return inspector, supplier, cp, ip


# ==========================================================================
# Tier 5 — Audit / finding helpers
# ==========================================================================
def create_planned_audit(auditor_id, **overrides) -> dict:
    resp = api_client.create_audit(f.create_audit_payload(auditor_id, **overrides), make_auditor_headers(auditor_id))
    return get_success_data(resp)


def create_in_progress_audit(auditor_id, **overrides) -> dict:
    """Create + START an audit (PLANNED->IN_PROGRESS). Returns the audit."""
    audit = create_planned_audit(auditor_id, **overrides)
    resp = api_client.transition_audit(audit["id"], {"action": "START"}, make_auditor_headers(auditor_id))
    return get_success_data(resp)


def add_finding(auditor_id, audit_id, grade="MAJOR", **overrides) -> dict:
    resp = api_client.create_audit_finding(
        audit_id, f.create_finding_payload(grade=grade, **overrides), make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def setup_audit_with_open_finding(grade="MAJOR"):
    """Auditor + IN_PROGRESS audit + one OPEN finding of the given grade.
    Returns (auditor, audit, finding)."""
    auditor = create_auditor()
    audit = create_in_progress_audit(auditor["id"])
    finding = add_finding(auditor["id"], audit["id"], grade=grade)
    return auditor, audit, finding


def setup_audit_finding_with_open_ncr():
    """IN_PROGRESS audit with a MAJOR finding escalated to NCR_RAISED via an OPEN
    AUDIT-source NCR (NCR is OPEN, not closed). Returns
    (auditor, engineer, audit, finding, ncr)."""
    auditor, audit, finding = setup_audit_with_open_finding(grade="MAJOR")
    engineer = create_engineer()
    ncr = create_open_ncr(engineer["id"], source="AUDIT", audit_finding_id=finding["id"], supplier_id=None)
    return auditor, engineer, audit, finding, ncr


# ==========================================================================
# Tier 6 — Deviation helpers
# ==========================================================================
def request_deviation(engineer_id, ncr_id, supplier_id, part_number, **overrides) -> dict:
    resp = api_client.create_deviation(
        f.create_deviation_payload(ncr_id, supplier_id, part_number, **overrides),
        make_engineer_headers(engineer_id),
    )
    return get_success_data(resp)


def approved_deviation(engineer_id, manager_id, ncr_id, supplier_id, part_number, **overrides) -> dict:
    """Request + approve a deviation. Returns the APPROVED deviation."""
    dev = request_deviation(engineer_id, ncr_id, supplier_id, part_number, **overrides)
    resp = api_client.transition_deviation(dev["id"], {"action": "APPROVE"}, make_manager_headers(manager_id))
    return get_success_data(resp)


# ==========================================================================
# Tier 7 — Control-plan revision / OCC helpers
# ==========================================================================
def read_control_plan_version(control_plan_id) -> int:
    data = get_success_data(api_client.get_control_plan(control_plan_id, OPERATOR))
    return data["version"]


def create_revision(engineer_id, control_plan_id, revision_no, expected_version, **overrides) -> dict:
    resp = api_client.create_control_plan_revision(
        f.create_revision_payload(control_plan_id, revision_no, expected_version, **overrides),
        make_engineer_headers(engineer_id),
    )
    return get_success_data(resp)


def create_and_approve_revision(engineer_id, manager_id, control_plan_id, revision_no) -> dict:
    """Create a DRAFT revision (with the freshly read version) and approve it.
    Returns the APPROVED revision."""
    ver = read_control_plan_version(control_plan_id)
    rev = create_revision(engineer_id, control_plan_id, revision_no, ver)
    resp = api_client.approve_control_plan_revision(rev["id"], make_manager_headers(manager_id))
    return get_success_data(resp)


def setup_control_plan_with_rev1_and_inspection_plan(engineer_id, manager_id):
    """Control plan with APPROVED revision #1 and a linked InspectionPlan
    (needs_review=false). Returns (control_plan, rev1, inspection_plan)."""
    cp = create_control_plan()
    rev1 = create_and_approve_revision(engineer_id, manager_id, cp["id"], 1)
    ip = get_success_data(api_client.create_inspection_plan(
        f.create_inspection_plan_payload(cp["id"]), OPERATOR
    ))
    return cp, rev1, ip
