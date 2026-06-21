"""Serialize stored records to API output shapes.

Each serializer projects the exact set of fields the PRD/scaffold declares for
that entity, in addition to the common fields already on the record. Decimal
values are emitted as floats with the declared precision.
"""


def _num(value):
    """Emit a Decimal/number as a JSON number with no spurious precision."""
    if value is None:
        return None
    return float(value)


def personnel_out(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "role": r["role"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def supplier_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "code": r["code"],
        "quality_rating": _num(r["quality_rating"]),
        "approval_status": r["approval_status"],
        "open_scar_count": r["open_scar_count"],
        "lots_inspected": r["lots_inspected"],
        "lots_rejected": r["lots_rejected"],
        "ncrs_attributed": r["ncrs_attributed"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ncr_out(r):
    return {
        "id": r["id"],
        "title": r["title"],
        "source": r["source"],
        "supplier_id": r["supplier_id"],
        "audit_finding_id": r["audit_finding_id"],
        "inspection_lot_id": r["inspection_lot_id"],
        "part_number": r["part_number"],
        "severity": r["severity"],
        "defect_qty": r["defect_qty"],
        "unit_cost_cents": r["unit_cost_cents"],
        "rework_hours": _num(r["rework_hours"]),
        "status": r["status"],
        "disposition": r["disposition"],
        "deviation_id": r["deviation_id"],
        "cost_of_quality_cents": r["cost_of_quality_cents"],
        "budget_reserved_cents": r["budget_reserved_cents"],
        "created_by_personnel_id": r["created_by_personnel_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def capa_out(r):
    return {
        "id": r["id"],
        "ncr_id": r["ncr_id"],
        "title": r["title"],
        "current_step": r["current_step"],
        "status": r["status"],
        "rework_loops": r["rework_loops"],
        "provisional_effectiveness": _num(r["provisional_effectiveness"]),
        "final_effectiveness": _num(r["final_effectiveness"]),
        "authored_by_personnel_id": r["authored_by_personnel_id"],
        "verified_by_personnel_id": r["verified_by_personnel_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def eightd_step_out(r):
    # Append-only journal entry: only id + created_at common fields (PRD 2.4).
    return {
        "id": r["id"],
        "capa_id": r["capa_id"],
        "discipline": r["discipline"],
        "narrative": r["narrative"],
        "containment_count": r["containment_count"],
        "recurred_defects": r["recurred_defects"],
        "recorded_by_personnel_id": r["recorded_by_personnel_id"],
        "created_at": r["created_at"],
    }


def scar_out(r):
    return {
        "id": r["id"],
        "ncr_id": r["ncr_id"],
        "supplier_id": r["supplier_id"],
        "due_at": r["due_at"],
        "status": r["status"],
        "response_narrative": r["response_narrative"],
        "rejection_count": r["rejection_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def inspection_plan_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "control_plan_id": r["control_plan_id"],
        "part_number": r["part_number"],
        "lot_size": r["lot_size"],
        "aql_pct": _num(r["aql_pct"]),
        "inspection_level": r["inspection_level"],
        "severity_mode": r["severity_mode"],
        "consecutive_rejects": r["consecutive_rejects"],
        "needs_review": r["needs_review"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def inspection_lot_out(r):
    return {
        "id": r["id"],
        "inspection_plan_id": r["inspection_plan_id"],
        "supplier_id": r["supplier_id"],
        "actual_lot_size": r["actual_lot_size"],
        "sample_size": r["sample_size"],
        "acceptance_number": r["acceptance_number"],
        "rejection_number": r["rejection_number"],
        "defects_found": r["defects_found"],
        "severity_mode_used": r["severity_mode_used"],
        "status": r["status"],
        "inspected_by_personnel_id": r["inspected_by_personnel_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def audit_out(r):
    return {
        "id": r["id"],
        "title": r["title"],
        "lead_auditor_id": r["lead_auditor_id"],
        "scheduled_from": r["scheduled_from"],
        "scheduled_to": r["scheduled_to"],
        "clause_scope": r["clause_scope"],
        "status": r["status"],
        "open_finding_count": r["open_finding_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def audit_finding_out(r):
    return {
        "id": r["id"],
        "audit_id": r["audit_id"],
        "clause": r["clause"],
        "grade": r["grade"],
        "description": r["description"],
        "status": r["status"],
        "raised_ncr_id": r["raised_ncr_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def deviation_out(r):
    return {
        "id": r["id"],
        "ncr_id": r["ncr_id"],
        "supplier_id": r["supplier_id"],
        "part_number": r["part_number"],
        "valid_from": r["valid_from"],
        "valid_to": r["valid_to"],
        "max_qty": r["max_qty"],
        "status": r["status"],
        "approved_by_personnel_id": r["approved_by_personnel_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def control_plan_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "part_number": r["part_number"],
        "current_revision_no": r["current_revision_no"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def control_plan_revision_out(r):
    return {
        "id": r["id"],
        "control_plan_id": r["control_plan_id"],
        "revision_no": r["revision_no"],
        "change_summary": r["change_summary"],
        "source_capa_id": r["source_capa_id"],
        "status": r["status"],
        "approved_by_personnel_id": r["approved_by_personnel_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
