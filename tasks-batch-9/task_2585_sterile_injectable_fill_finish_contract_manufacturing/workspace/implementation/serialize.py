"""Row -> JSON projection.

Two conventions:

  * Datetimes the client supplied are echoed back byte-for-byte (the literal
    string is kept in the row's `_raw` map); datetimes the server generated are
    rendered as ISO 8601 UTC with exactly three fractional digits (PRD 2.4).
  * Derived fields are computed here at read time rather than carried forward,
    which is what makes the ledger identities of PRD 2.6 hold by construction.
"""

from decimal import Decimal

from common import fmt_dt
import calc


def dt_out(row, field):
    raw = row.get("_raw", {}).get(field)
    if raw is not None:
        return raw
    return fmt_dt(row.get(field))


def num_out(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, versioned=True):
    out = {"created_at": dt_out(row, "created_at")}
    if versioned:
        out["updated_at"] = dt_out(row, "updated_at")
        out["version"] = row["version"]
    return out


def project_out(row):
    out = {
        "id": row["id"],
        "client_name": row["client_name"],
        "molecule_name": row["molecule_name"],
        "dosage_form": row["dosage_form"],
        "primary_suite_id": row["primary_suite_id"],
        "target_fill_weight_mg": num_out(row["target_fill_weight_mg"]),
        "historical_reject_rate_ppm": row["historical_reject_rate_ppm"],
        "reserved_unit_budget": row["reserved_unit_budget"],
        "tech_transfer_stage": row["tech_transfer_stage"],
        "analytical_method_transfer_status": row["analytical_method_transfer_status"],
        "status": row["status"],
        "committed_demand_units": calc.committed_demand_units(row["id"]),
        "open_deviation_risk_total": calc.open_deviation_risk_total(row["id"]),
        "last_client_audit_finding_count": calc.last_client_audit_finding_count(row["id"]),
    }
    out.update(_common(row))
    return out


def suite_out(row):
    out = {
        "id": row["id"],
        "suite_code": row["suite_code"],
        "grade": row["grade"],
        "changeover_minutes_same_product": row["changeover_minutes_same_product"],
        "changeover_minutes_product_change": row["changeover_minutes_product_change"],
        "max_committed_minutes": row["max_committed_minutes"],
        "aseptic_qualification_status": row["aseptic_qualification_status"],
        "media_fill_valid_until": dt_out(row, "media_fill_valid_until"),
        "cleaning_validation_status": row["cleaning_validation_status"],
        "last_cleaned_molecule": row["last_cleaned_molecule"],
        "open_action_excursion_count": calc.open_action_excursion_count(row["id"]),
        "qualified_operator_count": calc.qualified_operator_count(row["id"]),
        "committed_minutes": calc.suite_committed_minutes(row["id"]),
        "posture": calc.suite_posture(row),
    }
    out.update(_common(row))
    return out


def media_fill_out(row):
    out = {
        "id": row["id"],
        "suite_id": row["suite_id"],
        "scheduled_run_date": dt_out(row, "scheduled_run_date"),
        "units_filled": row["units_filled"],
        "contaminated_units": row["contaminated_units"],
        "participating_operator_names": list(row["participating_operator_names"]),
        "status": row["status"],
        "read_at": dt_out(row, "read_at"),
        "outcome_reason": row["outcome_reason"],
    }
    out.update(_common(row))
    return out


def qualification_out(row):
    out = {
        "id": row["id"],
        "operator_name": row["operator_name"],
        "suite_id": row["suite_id"],
        "media_fill_id": row["media_fill_id"],
        "qualification_type": row["qualification_type"],
        "expires_on": dt_out(row, "expires_on"),
        "status": row["status"],
        "qualified_at": dt_out(row, "qualified_at"),
    }
    out.update(_common(row))
    return out


def batch_out(row):
    out = {
        "id": row["id"],
        "client_project_id": row["client_project_id"],
        "suite_id": row["suite_id"],
        "lead_operator_qualification_id": row["lead_operator_qualification_id"],
        "batch_number": row["batch_number"],
        "planned_start": dt_out(row, "planned_start"),
        "planned_end": dt_out(row, "planned_end"),
        "target_fill_units": row["target_fill_units"],
        "component_demand_units": row["component_demand_units"],
        "changeover_minutes_applied": row["changeover_minutes_applied"],
        "filled_unit_count": row["filled_unit_count"],
        "quarantined_unit_count": row["quarantined_unit_count"],
        "production_status": row["production_status"],
        "quality_status": row["quality_status"],
        "provisional_releasable_units": row["provisional_releasable_units"],
        "final_releasable_units": row["final_releasable_units"],
        "release_fee_cents": row["release_fee_cents"],
    }
    out.update(_common(row))
    return out


def lot_out(row):
    out = {
        "id": row["id"],
        "client_project_id": row["client_project_id"],
        "component_type": row["component_type"],
        "lot_code": row["lot_code"],
        "quantity_received": row["quantity_received"],
        "quantity_available": row["quantity_available"],
        "sterilization_expiry": dt_out(row, "sterilization_expiry"),
        "sterilization_validation_status": row["sterilization_validation_status"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def reservation_out(row):
    out = {
        "id": row["id"],
        "batch_order_id": row["batch_order_id"],
        "component_lot_id": row["component_lot_id"],
        "quantity_reserved": row["quantity_reserved"],
        "status": row["status"],
        "released_reason": row["released_reason"],
    }
    out.update(_common(row))
    return out


def ipc_out(row):
    out = {
        "id": row["id"],
        "batch_order_id": row["batch_order_id"],
        "check_type": row["check_type"],
        "sample_size": row["sample_size"],
        "reject_unit_count": row["reject_unit_count"],
        "destructive_sample_units": row["destructive_sample_units"],
        "measured_fill_weights_mg": [num_out(v) for v in row["measured_fill_weights_mg"]],
        "result": row["result"],
        "max_absolute_deviation_pct": num_out(row["max_absolute_deviation_pct"]),
    }
    out.update(_common(row))
    return out


def em_sample_out(row):
    out = {
        "id": row["id"],
        "suite_id": row["suite_id"],
        "batch_order_id": row["batch_order_id"],
        "sample_type": row["sample_type"],
        "cfu_count": row["cfu_count"],
        "alert_limit": row["alert_limit"],
        "action_limit": row["action_limit"],
        "classification": row["classification"],
        "risk_index": row["risk_index"],
        "investigation_status": row["investigation_status"],
        "root_cause": row["root_cause"],
    }
    out.update(_common(row))
    return out


def deviation_out(row):
    out = {
        "id": row["id"],
        "batch_order_id": row["batch_order_id"],
        "em_sample_id": row["em_sample_id"],
        "opened_by_user_id": row["opened_by_user_id"],
        "summary": row["summary"],
        "classification": row["classification"],
        "capa_rejection_count": row["capa_rejection_count"],
        "risk_score": row["risk_score"],
        "status": row["status"],
        "capa_summary": row["capa_summary"],
    }
    out.update(_common(row))
    return out


def review_out(row):
    out = {
        "id": row["id"],
        "batch_order_id": row["batch_order_id"],
        "reviewer_user_id": row["reviewer_user_id"],
        "open_findings_count": row["open_findings_count"],
        "status": row["status"],
        "closed_at": dt_out(row, "closed_at"),
    }
    out.update(_common(row))
    return out


def qp_decision_out(row):
    out = {
        "id": row["id"],
        "batch_order_id": row["batch_order_id"],
        "qp_user_id": row["qp_user_id"],
        "decision": row["decision"],
        "rationale": row["rationale"],
        "released_unit_count": row["released_unit_count"],
        "fee_cents": row["fee_cents"],
    }
    out.update(_common(row, versioned=False))
    return out


def engagement_out(row):
    out = {
        "id": row["id"],
        "client_project_id": row["client_project_id"],
        "audit_kind": row["audit_kind"],
        "requested_window_start": dt_out(row, "requested_window_start"),
        "status": row["status"],
        "finding_count": row["finding_count"],
        "hosted_at": dt_out(row, "hosted_at"),
    }
    out.update(_common(row))
    return out
