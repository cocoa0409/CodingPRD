"""Composite setup helpers.

Every helper builds preconditions from scratch through the public API and uses
the lenient get_success_data validator so a setup failure surfaces as a clear
"Setup failed" assertion instead of a confusing envelope error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AGREEMENT_FROM,
    AGREEMENT_TO,
    MFG_DEFAULT,
    PROTOCOL_WINDOW_END,
    PROTOCOL_WINDOW_START,
    UDI_VALID,
)
from .factories import (
    create_agreement_payload,
    create_audit_completion_payload,
    create_audit_payload,
    create_capa_payload,
    create_complaint_payload,
    create_component_payload,
    create_disposition_payload,
    create_dmr_payload,
    create_field_action_payload,
    create_label_payload,
    create_line_payload,
    create_lot_payload,
    create_ncr_payload,
    create_part_payload,
    create_protocol_payload,
    create_receive_payload,
    create_revision_payload,
    create_scn_payload,
    create_sterility_payload,
    create_study_payload,
    create_supplier_payload,
)
from .test_users import (
    ADMIN_1,
    PO_1,
    QE_ALICE,
    QM_BOB,
    RA_1,
    SQE_1,
    make_production_operator_headers,
    make_quality_engineer_headers,
    make_quality_manager_headers,
    make_qms_admin_headers,
    make_regulatory_affairs_headers,
    make_supplier_quality_engineer_headers,
)


def _ok(resp, what: str):
    data = get_success_data(resp)
    assert isinstance(data, dict) and data, f"Setup failed: {what} returned no data ({resp.status_code})"
    return data


# ---------------------------------------------------------------------------
# Role header shorthands bound to the canonical operator ids
# ---------------------------------------------------------------------------

def qe(user_id: str = QE_ALICE) -> dict:
    return make_quality_engineer_headers(user_id)


def qm(user_id: str = QM_BOB) -> dict:
    return make_quality_manager_headers(user_id)


def po(user_id: str = PO_1) -> dict:
    return make_production_operator_headers(user_id)


def sqe(user_id: str = SQE_1) -> dict:
    return make_supplier_quality_engineer_headers(user_id)


def ra(user_id: str = RA_1) -> dict:
    return make_regulatory_affairs_headers(user_id)


def admin(user_id: str = ADMIN_1) -> dict:
    return make_qms_admin_headers(user_id)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_line(line_code: str = "L-1", changeover_buffer_hours: int = 24) -> dict:
    resp = api_client.create_line(
        create_line_payload(line_code=line_code, changeover_buffer_hours=changeover_buffer_hours),
        admin(),
    )
    return _ok(resp, f"create manufacturing line {line_code}")


def create_dmr_draft(
    device_code: str = "DEV-1",
    revision_code: str = "A",
    sterile: bool = True,
    shelf_life_claim_months: int = 20,
    author: str = QE_ALICE,
) -> dict:
    resp = api_client.create_dmr(
        create_dmr_payload(
            device_code=device_code,
            revision_code=revision_code,
            sterile=sterile,
            shelf_life_claim_months=shelf_life_claim_months,
        ),
        qe(author),
    )
    return _ok(resp, f"create DMR {device_code}/{revision_code}")


def approve_dmr(dmr_id: str, approver: str = QM_BOB) -> dict:
    resp = api_client.approve_dmr(dmr_id, qm(approver))
    return _ok(resp, f"approve DMR {dmr_id}")


def create_approved_dmr(device_code: str = "DEV-1", **kwargs) -> dict:
    dmr = create_dmr_draft(device_code=device_code, **kwargs)
    return approve_dmr(dmr["id"])


def create_dmr_revision(parent: dict, revision_code: str = "B", **overrides) -> dict:
    resp = api_client.create_dmr_revision(
        parent["id"],
        create_revision_payload(parent["version"], revision_code=revision_code, **overrides),
        qe(),
    )
    return _ok(resp, f"create revision {revision_code} of {parent['device_code']}")


def create_protocol(
    protocol_code: str,
    dmr_id: str,
    line_id: str,
    planned_start: str = PROTOCOL_WINDOW_START,
    planned_end: str = PROTOCOL_WINDOW_END,
) -> dict:
    resp = api_client.create_protocol(
        create_protocol_payload(
            dmr_id,
            line_id,
            protocol_code=protocol_code,
            planned_start=planned_start,
            planned_end=planned_end,
        ),
        qe(),
    )
    return _ok(resp, f"create protocol {protocol_code}")


def walk_protocol_to_validated(
    protocol_id: str, executor: str = QE_ALICE, approver: str = QM_BOB
) -> dict:
    """Walk a protocol DRAFT -> IQ/OQ/PQ -> VALIDATED (three submit/approve gates)."""
    resp = api_client.execute_phase(protocol_id, qe(executor))
    _ok(resp, f"execute-phase on {protocol_id}")
    for _phase in ("iq", "oq", "pq"):
        resp = api_client.submit_phase_review(protocol_id, qe(executor))
        _ok(resp, f"submit-phase-review on {protocol_id}")
        resp = api_client.approve_phase(protocol_id, qm(approver))
        _ok(resp, f"approve-phase on {protocol_id}")
    return _ok(api_client.get_protocol(protocol_id, qm()), f"get protocol {protocol_id}")


def create_validated_protocol(
    protocol_code: str, dmr_id: str, line_id: str, **window
) -> dict:
    protocol = create_protocol(protocol_code, dmr_id, line_id, **window)
    return walk_protocol_to_validated(protocol["id"])


def create_validated_stack(prefix: str = "DEV-1", claim_months: int = 20) -> dict:
    """Line + APPROVED DMR + VALIDATED protocol. Returns a dict of the three."""
    line = create_line(line_code=f"L-{prefix}")
    dmr = create_approved_dmr(device_code=prefix, shelf_life_claim_months=claim_months)
    protocol = create_validated_protocol(f"VP-{prefix}", dmr["id"], line["id"])
    return {"line": line, "dmr": dmr, "protocol": protocol}


# ---------------------------------------------------------------------------
# Suppliers, agreements, parts
# ---------------------------------------------------------------------------

def create_supplier(supplier_code: str = "SUP-1", name: str = "Test Supplier") -> dict:
    resp = api_client.create_supplier(
        create_supplier_payload(supplier_code=supplier_code, name=name), sqe()
    )
    return _ok(resp, f"create supplier {supplier_code}")


def create_agreement(
    supplier: dict,
    agreement_code: str = "QA-1",
    effective_from: str = AGREEMENT_FROM,
    effective_to: str = AGREEMENT_TO,
    audit_notice_days: int = 30,
    change_notice_days: int = 90,
) -> dict:
    resp = api_client.create_agreement(
        supplier["id"],
        create_agreement_payload(
            supplier["version"],
            agreement_code=agreement_code,
            effective_from=effective_from,
            effective_to=effective_to,
            audit_notice_days=audit_notice_days,
            change_notice_days=change_notice_days,
        ),
        sqe(),
    )
    return _ok(resp, f"create agreement {agreement_code}")


def activate_agreement(agreement_id: str) -> dict:
    resp = api_client.activate_agreement(agreement_id, sqe())
    return _ok(resp, f"activate agreement {agreement_id}")


def create_active_agreement(supplier: dict, **kwargs) -> dict:
    agreement = create_agreement(supplier, **kwargs)
    return activate_agreement(agreement["id"])


def create_qualified_supplier(supplier_code: str = "SUP-1", name: str = "Test Supplier", **agr) -> dict:
    """Supplier + ACTIVE agreement + qualify. Returns {'supplier', 'agreement'}."""
    supplier = create_supplier(supplier_code, name)
    agreement = create_active_agreement(
        supplier, agreement_code=f"QA-{supplier_code}", **agr
    )
    resp = api_client.qualify_supplier(supplier["id"], sqe())
    supplier = _ok(resp, f"qualify supplier {supplier_code}")
    return {"supplier": supplier, "agreement": agreement}


def create_part(
    supplier_id: str,
    part_number: str = "PN-1",
    critical: bool = False,
    receive_qty: int = 0,
    description: str = "component",
) -> dict:
    resp = api_client.create_part(
        supplier_id,
        create_part_payload(part_number=part_number, critical=critical, description=description),
        sqe(),
    )
    part = _ok(resp, f"create part {part_number}")
    if receive_qty:
        resp = api_client.receive_part(part["id"], create_receive_payload(quantity=receive_qty), sqe())
        part = _ok(resp, f"receive {receive_qty} of {part_number}")
    return part


def get_supplier(supplier_id: str) -> dict:
    return _ok(api_client.get_supplier(supplier_id, sqe()), f"get supplier {supplier_id}")


def get_part(part_id: str) -> dict:
    return _ok(api_client.get_part(part_id, sqe()), f"get part {part_id}")


def get_lot(lot_id: str) -> dict:
    return _ok(api_client.get_lot(lot_id, qm()), f"get lot {lot_id}")


# ---------------------------------------------------------------------------
# Lots, components, labels
# ---------------------------------------------------------------------------

def create_lot(
    lot_number: str,
    dmr_id: str,
    protocol_id: str,
    quantity: int = 10,
    manufactured_at: str = MFG_DEFAULT,
) -> dict:
    resp = api_client.create_lot(
        create_lot_payload(
            dmr_id,
            protocol_id,
            lot_number=lot_number,
            quantity=quantity,
            manufactured_at=manufactured_at,
        ),
        po(),
    )
    return _ok(resp, f"create lot {lot_number}")


def add_component(
    lot_id: str, part_id: str, quantity_used: int = 10, supplier_lot_number: str = "SL-1"
) -> dict:
    resp = api_client.create_component(
        lot_id,
        create_component_payload(
            part_id, quantity_used=quantity_used, supplier_lot_number=supplier_lot_number
        ),
        po(),
    )
    return _ok(resp, f"add component {supplier_lot_number} to lot {lot_id}")


def complete_lot(lot_id: str) -> dict:
    resp = api_client.complete_lot(lot_id, po())
    return _ok(resp, f"complete lot {lot_id}")


def record_sterility(lot_id: str, result: str = "PASSED") -> dict:
    resp = api_client.record_sterility_result(lot_id, create_sterility_payload(result=result), qe())
    return _ok(resp, f"record sterility {result} on lot {lot_id}")


def create_label(lot_id: str, udi_di: str = UDI_VALID) -> dict:
    resp = api_client.create_label(lot_id, create_label_payload(udi_di=udi_di), po())
    return _ok(resp, f"create label on lot {lot_id}")


def approve_label(label_id: str) -> dict:
    resp = api_client.approve_label(label_id, qm())
    return _ok(resp, f"approve label {label_id}")


def print_label(label_id: str) -> dict:
    resp = api_client.print_label(label_id, po())
    return _ok(resp, f"print label {label_id}")


def release_lot(lot_id: str) -> dict:
    resp = api_client.release_lot(lot_id, qm())
    return _ok(resp, f"release lot {lot_id}")


def create_completed_lot(
    stack: dict,
    part: dict,
    lot_number: str = "LT-1",
    quantity: int = 10,
    manufactured_at: str = MFG_DEFAULT,
    supplier_lot_number: str = "SL-1",
    component_qty: int = None,
) -> dict:
    """Lot IN_PRODUCTION + one component + complete -> COMPLETED."""
    lot = create_lot(
        lot_number,
        stack["dmr"]["id"],
        stack["protocol"]["id"],
        quantity=quantity,
        manufactured_at=manufactured_at,
    )
    add_component(
        lot["id"],
        part["id"],
        quantity_used=component_qty if component_qty is not None else quantity,
        supplier_lot_number=supplier_lot_number,
    )
    return complete_lot(lot["id"])


def create_releasable_lot(
    stack: dict,
    part: dict,
    lot_number: str = "LT-1",
    quantity: int = 10,
    manufactured_at: str = MFG_DEFAULT,
    supplier_lot_number: str = "SL-1",
    udi_di: str = UDI_VALID,
) -> dict:
    """COMPLETED lot with sterility PASSED and a PRINTED label — every release
    gate except the release call itself. Returns {'lot', 'label'}."""
    lot = create_completed_lot(
        stack,
        part,
        lot_number=lot_number,
        quantity=quantity,
        manufactured_at=manufactured_at,
        supplier_lot_number=supplier_lot_number,
    )
    lot = record_sterility(lot["id"], "PASSED")
    label = create_label(lot["id"], udi_di)
    approve_label(label["id"])
    print_label(label["id"])
    return {"lot": get_lot(lot["id"]), "label": label}


def create_released_lot(stack: dict, part: dict, **kwargs) -> dict:
    """create_releasable_lot + release. Returns {'lot', 'label'}."""
    bundle = create_releasable_lot(stack, part, **kwargs)
    bundle["lot"] = release_lot(bundle["lot"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Studies
# ---------------------------------------------------------------------------

def create_study(dmr_id: str, study_type: str = "ACCELERATED", claimed_months: int = 20) -> dict:
    resp = api_client.create_study(
        create_study_payload(dmr_id, study_type=study_type, claimed_months=claimed_months), qe()
    )
    return _ok(resp, f"create study on DMR {dmr_id}")


def complete_study(study_id: str, passed: bool, result_months_confirmed: int = None) -> dict:
    payload = {"passed": passed}
    if result_months_confirmed is not None:
        payload["result_months_confirmed"] = result_months_confirmed
    resp = api_client.complete_study(study_id, payload, qm())
    return _ok(resp, f"complete study {study_id} passed={passed}")


# ---------------------------------------------------------------------------
# NCRs
# ---------------------------------------------------------------------------

def create_ncr(
    ncr_code: str = "NCR-1",
    severity: str = "MINOR",
    lot_id: str = None,
    supplier_part_id: str = None,
    description: str = "nonconformance",
    author: str = QE_ALICE,
) -> dict:
    payload = create_ncr_payload(
        ncr_code=ncr_code, severity=severity, description=description
    )
    if lot_id is not None:
        payload["lot_id"] = lot_id
    if supplier_part_id is not None:
        payload["supplier_part_id"] = supplier_part_id
    resp = api_client.create_ncr(payload, qe(author))
    return _ok(resp, f"create NCR {ncr_code}")


def contain_ncr(ncr_id: str) -> dict:
    resp = api_client.contain_ncr(ncr_id, qe())
    return _ok(resp, f"contain NCR {ncr_id}")


def disposition_ncr(ncr_id: str, disposition: str, fault: str) -> dict:
    resp = api_client.disposition_ncr(
        ncr_id, create_disposition_payload(disposition=disposition, fault=fault), qe()
    )
    return _ok(resp, f"disposition NCR {ncr_id} as {disposition}/{fault}")


def close_ncr(ncr_id: str, closer: str = QM_BOB) -> dict:
    resp = api_client.close_ncr(ncr_id, qm(closer))
    return _ok(resp, f"close NCR {ncr_id}")


def create_dispositioned_ncr(
    ncr_code: str, severity: str, fault: str, disposition: str = "RETURN_TO_SUPPLIER", **refs
) -> dict:
    ncr = create_ncr(ncr_code=ncr_code, severity=severity, **refs)
    contain_ncr(ncr["id"])
    return disposition_ncr(ncr["id"], disposition, fault)


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

def create_complaint(
    complaint_code: str, lot_id: str, severity: str = "MINOR", description: str = "field complaint"
) -> dict:
    resp = api_client.create_complaint(
        create_complaint_payload(
            lot_id, complaint_code=complaint_code, severity=severity, description=description
        ),
        ra(),
    )
    return _ok(resp, f"create complaint {complaint_code}")


def investigate_complaint(complaint_id: str, confirmed: bool, investigator: str = RA_1) -> dict:
    resp = api_client.start_complaint_investigation(complaint_id, ra(investigator))
    _ok(resp, f"start investigation on complaint {complaint_id}")
    resp = api_client.complete_complaint_investigation(complaint_id, {"confirmed": confirmed}, ra(investigator))
    return _ok(resp, f"complete investigation on complaint {complaint_id}")


# ---------------------------------------------------------------------------
# CAPAs
# ---------------------------------------------------------------------------

def create_capa(
    capa_code: str,
    dmr_id: str,
    source_type: str = "MANUAL",
    process_change: bool = False,
    initiator: str = QE_ALICE,
    **links,
) -> dict:
    resp = api_client.create_capa(
        create_capa_payload(
            dmr_id, capa_code=capa_code, source_type=source_type, process_change=process_change, **links
        ),
        qe(initiator),
    )
    return _ok(resp, f"create CAPA {capa_code}")


def walk_capa_to_effectiveness_check(capa_id: str, action_summary: str = "corrective plan") -> dict:
    resp = api_client.begin_capa_investigation(capa_id, qe())
    _ok(resp, f"begin CAPA investigation {capa_id}")
    resp = api_client.plan_capa_actions(capa_id, {"action_summary": action_summary}, qe())
    _ok(resp, f"plan CAPA actions {capa_id}")
    resp = api_client.implement_capa(capa_id, qe())
    _ok(resp, f"implement CAPA {capa_id}")
    resp = api_client.complete_capa_implementation(capa_id, qe())
    return _ok(resp, f"complete CAPA implementation {capa_id}")


def verify_capa(capa_id: str, effective: bool, verifier: str = QM_BOB) -> dict:
    resp = api_client.verify_capa_effectiveness(capa_id, {"effective": effective}, qm(verifier))
    return _ok(resp, f"verify CAPA {capa_id} effective={effective}")


def find_capa_by_source_complaint(complaint_id: str) -> dict:
    resp = api_client.list_capas(qe(), params={"source_complaint_id": complaint_id})
    body = get_success_data(resp)
    assert isinstance(body, list) and body, (
        f"Setup failed: expected an auto-created CAPA for complaint {complaint_id}"
    )
    return body[0]


# ---------------------------------------------------------------------------
# Field actions
# ---------------------------------------------------------------------------

def create_field_action(
    action_code: str,
    dmr_id: str,
    reason_complaint_id: str,
    scope_mfg_start: str = "2026-08-01T00:00:00Z",
    scope_mfg_end: str = "2026-08-31T23:59:59Z",
    action_type: str = "REMOVAL",
) -> dict:
    resp = api_client.create_field_action(
        create_field_action_payload(
            dmr_id,
            reason_complaint_id,
            action_code=action_code,
            action_type=action_type,
            scope_mfg_start=scope_mfg_start,
            scope_mfg_end=scope_mfg_end,
        ),
        ra(),
    )
    return _ok(resp, f"create field action {action_code}")


# ---------------------------------------------------------------------------
# Audits and SCNs
# ---------------------------------------------------------------------------

def create_audit(
    supplier_id: str,
    scheduled_start: str = "2026-09-10T00:00:00Z",
    scheduled_end: str = "2026-09-11T00:00:00Z",
) -> dict:
    resp = api_client.create_audit(
        supplier_id,
        create_audit_payload(scheduled_start=scheduled_start, scheduled_end=scheduled_end),
        sqe(),
    )
    return _ok(resp, f"create audit on supplier {supplier_id}")


def complete_audit(audit_id: str, findings_count: int = 0, major_findings_count: int = 0) -> dict:
    resp = api_client.complete_audit(
        audit_id,
        create_audit_completion_payload(
            findings_count=findings_count, major_findings_count=major_findings_count
        ),
        sqe(),
    )
    return _ok(resp, f"complete audit {audit_id}")


def create_scn(
    supplier_id: str,
    impact_class: str = "MINOR",
    proposed_effective_date: str = "2026-12-01T00:00:00Z",
    supplier_part_id: str = None,
    change_description: str = "process change",
) -> dict:
    payload = create_scn_payload(
        change_description=change_description,
        impact_class=impact_class,
        proposed_effective_date=proposed_effective_date,
    )
    if supplier_part_id is not None:
        payload["supplier_part_id"] = supplier_part_id
    resp = api_client.create_scn(supplier_id, payload, sqe())
    return _ok(resp, f"create SCN on supplier {supplier_id}")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, admin())
    return _ok(resp, f"set clock to {to_iso8601}")
