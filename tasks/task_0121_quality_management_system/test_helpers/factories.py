"""Payload factories — one per entity, input fields only.

Each factory provides sensible required-field defaults and applies **overrides
last so a test can pin or omit (via override=None then pop) any field.
"""
import uuid


def _unique_email(prefix="user"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@x.com"


def _unique_code(prefix="SUP"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# --------------------------------------------------------------------------
# Personnel
# --------------------------------------------------------------------------
def create_personnel_payload(role="QUALITY_ENGINEER", **overrides) -> dict:
    payload = {
        "full_name": "Test Person",
        "email": _unique_email("p"),
        "role": role,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Supplier
# --------------------------------------------------------------------------
def create_supplier_payload(**overrides) -> dict:
    payload = {
        "name": "Test Supplier",
        "code": _unique_code("SUP"),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# NonconformanceReport
#   Required: title, source, severity, defect_qty, unit_cost_cents, part_number
#   Conditional/optional: supplier_id, audit_finding_id, inspection_lot_id, rework_hours
# --------------------------------------------------------------------------
def create_ncr_payload(
    source="SUPPLIER",
    severity="MAJOR",
    defect_qty=2,
    unit_cost_cents=1000,
    part_number="P-100",
    **overrides,
) -> dict:
    payload = {
        "title": "Test NCR",
        "source": source,
        "severity": severity,
        "defect_qty": defect_qty,
        "unit_cost_cents": unit_cost_cents,
        "part_number": part_number,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Capa
# --------------------------------------------------------------------------
def create_capa_payload(ncr_id, **overrides) -> dict:
    payload = {
        "ncr_id": ncr_id,
        "title": "Test CAPA",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# EightDStep
#   Required: discipline, narrative
#   Optional: containment_count (default 0), recurred_defects (default 0)
# --------------------------------------------------------------------------
def create_step_payload(discipline="D1", narrative="step narrative", **overrides) -> dict:
    payload = {
        "discipline": discipline,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Scar
# --------------------------------------------------------------------------
def create_scar_payload(ncr_id, supplier_id, due_at="2026-09-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "ncr_id": ncr_id,
        "supplier_id": supplier_id,
        "due_at": due_at,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# ControlPlan
# --------------------------------------------------------------------------
def create_control_plan_payload(part_number="P-CP", **overrides) -> dict:
    payload = {
        "name": "Test Control Plan",
        "part_number": part_number,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# ControlPlanRevision
#   Required: control_plan_id, revision_no, change_summary, expected_control_plan_version
#   Optional: source_capa_id
# --------------------------------------------------------------------------
def create_revision_payload(
    control_plan_id, revision_no, expected_control_plan_version, **overrides
) -> dict:
    payload = {
        "control_plan_id": control_plan_id,
        "revision_no": revision_no,
        "change_summary": "Test revision",
        "expected_control_plan_version": expected_control_plan_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# InspectionPlan
#   Required: name, control_plan_id, part_number, lot_size, aql_pct
#   Optional: inspection_level (default GII)
# --------------------------------------------------------------------------
def create_inspection_plan_payload(
    control_plan_id, part_number="P-IP", lot_size=120, aql_pct=4.0, **overrides
) -> dict:
    payload = {
        "name": "Test Inspection Plan",
        "control_plan_id": control_plan_id,
        "part_number": part_number,
        "lot_size": lot_size,
        "aql_pct": aql_pct,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# InspectionLot
# --------------------------------------------------------------------------
def create_inspection_lot_payload(inspection_plan_id, supplier_id, actual_lot_size=120, **overrides) -> dict:
    payload = {
        "inspection_plan_id": inspection_plan_id,
        "supplier_id": supplier_id,
        "actual_lot_size": actual_lot_size,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Audit
#   Required: title, lead_auditor_id, scheduled_from, scheduled_to
#   Optional: clause_scope
# --------------------------------------------------------------------------
def create_audit_payload(
    lead_auditor_id,
    scheduled_from="2026-07-01T00:00:00Z",
    scheduled_to="2026-07-02T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "title": "Test Audit",
        "lead_auditor_id": lead_auditor_id,
        "scheduled_from": scheduled_from,
        "scheduled_to": scheduled_to,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# AuditFinding
# --------------------------------------------------------------------------
def create_finding_payload(clause="8.5.1", grade="MAJOR", description="Test finding", **overrides) -> dict:
    payload = {
        "clause": clause,
        "grade": grade,
        "description": description,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Deviation
# --------------------------------------------------------------------------
def create_deviation_payload(
    ncr_id,
    supplier_id,
    part_number,
    valid_from="2026-06-01T00:00:00Z",
    valid_to="2026-12-01T00:00:00Z",
    max_qty=5,
    **overrides,
) -> dict:
    payload = {
        "ncr_id": ncr_id,
        "supplier_id": supplier_id,
        "part_number": part_number,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "max_qty": max_qty,
    }
    payload.update(overrides)
    return payload
