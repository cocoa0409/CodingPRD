"""Entity serializers.

Derived fields are computed at serialization time so that every read reflects
the current logical clock (PRD section 2.4). `Food` and `Hazard` are immutable
and therefore carry neither `updated_at` nor `version` (PRD section 2.5).
"""
import core
from response import iso_ms


def _stamps(row):
    out = {"id": row["id"], "created_at": iso_ms(row["created_at"])}
    if "version" in row:
        out["updated_at"] = iso_ms(row["updated_at"])
        out["version"] = row["version"]
    return out


def importer_out(row):
    out = _stamps(row)
    out.update(
        {
            "legal_name": row["legal_name"],
            "dnb_number": row["dnb_number"],
            "unique_facility_identifier": row["unique_facility_identifier"],
            "small_importer_flag": row["small_importer_flag"],
            "record_retention_months": row["record_retention_months"],
        }
    )
    out.update(core.importer_rollup(row))
    return out


def qi_out(row):
    out = _stamps(row)
    out.update(
        {
            "importer_id": row["importer_id"],
            "full_name": row["full_name"],
            "email": row["email"],
            "qualification_summary": row["qualification_summary"],
            "training_completed_at": iso_ms(row["training_completed_at"]),
            "training_valid_until": iso_ms(core.qi_training_valid_until(row)),
            "concurrent_activity_capacity": row["concurrent_activity_capacity"],
            "status": row["status"],
            "active_assignment_count": core.qi_active_assignment_count(row),
        }
    )
    return out


def supplier_out(row):
    final, weight_total = core.supplier_performance_final(row)
    out = _stamps(row)
    out.update(
        {
            "importer_id": row["importer_id"],
            "name": row["name"],
            "country_code": row["country_code"],
            "facility_registration_number": row["facility_registration_number"],
            "regulatory_compliance_status": row["regulatory_compliance_status"],
            "compliance_status_source_reference": row["compliance_status_source_reference"],
            "performance_score_provisional": core.fnum(core.supplier_performance_provisional(row)),
            "performance_score_final": core.fnum(final),
            "performance_sample_weight_total": core.fnum(weight_total),
            "status": row["status"],
            "last_evaluated_at": iso_ms(row["last_evaluated_at"]),
            "open_corrective_action_count": core.supplier_open_corrective_action_count(row),
        }
    )
    return out


def food_out(row):
    out = _stamps(row)
    out.update(
        {
            "importer_id": row["importer_id"],
            "food_name": row["food_name"],
            "fda_product_code": row["fda_product_code"],
            "is_raw_agricultural_commodity": row["is_raw_agricultural_commodity"],
            "intended_consumer_group": row["intended_consumer_group"],
            "process_control_category": row["process_control_category"],
            "ready_to_eat": row["ready_to_eat"],
        }
    )
    return out


def pair_out(row):
    risk = core.pair_risk(row)
    out = _stamps(row)
    out.update(
        {
            "importer_id": row["importer_id"],
            "supplier_id": row["supplier_id"],
            "food_id": row["food_id"],
            "designated_qi_id": row["designated_qi_id"],
            "active_hazard_analysis_id": row["active_hazard_analysis_id"],
            "verification_status": row["verification_status"],
            "entry_eligibility_status": row["entry_eligibility_status"],
            "exemption_status": row["exemption_status"],
            "exemption_type": row["exemption_type"],
            "modified_requirements_only": core.pair_modified_requirements_only(row),
            "hazard_analysis_count": core.pair_hazard_analysis_count(row),
            "composite_hazard_risk": core.fnum(risk["composite_hazard_risk"]),
            "risk_tier": risk["risk_tier"],
            "required_annual_frequency": risk["required_annual_frequency"],
            "required_coverage": core.fnum(risk["required_coverage"]),
            "adequacy_score_planned": core.fnum(core.pair_adequacy_planned(row)),
            "adequacy_score_realized": core.fnum(core.pair_adequacy_realized(row)),
            "uncontrolled_significant_hazard_count": core.pair_uncontrolled_significant_hazard_count(
                row
            ),
            "last_reassessed_at": iso_ms(row["last_reassessed_at"]),
            "reassessment_due_at": iso_ms(core.pair_reassessment_due_at(row)),
        }
    )
    return out


def analysis_out(row):
    out = _stamps(row)
    out.update(
        {
            "pair_id": row["pair_id"],
            "authored_by_qi_id": row["authored_by_qi_id"],
            "methodology_note": row["methodology_note"],
            "pair_version_at_create": row["pair_version_at_create"],
            "status": row["status"],
            "hazard_count": core.analysis_hazard_count(row),
            "significant_hazard_count": core.analysis_significant_hazard_count(row),
            "risk_total": core.fnum(core.analysis_risk_total(row)),
            "approved_at": iso_ms(row["approved_at"]),
        }
    )
    return out


def hazard_out(row):
    out = _stamps(row)
    out.update(
        {
            "hazard_analysis_id": row["hazard_analysis_id"],
            "hazard_type": row["hazard_type"],
            "hazard_name": row["hazard_name"],
            "severity": row["severity"],
            "probability": row["probability"],
            "control_owner": row["control_owner"],
            "risk_score": core.fnum(row["risk_score"]),
            "requires_control": row["requires_control"],
        }
    )
    return out


def activity_out(row):
    out = _stamps(row)
    out.update(
        {
            "pair_id": row["pair_id"],
            "proposed_by_qi_id": row["proposed_by_qi_id"],
            "assigned_qi_id": row["assigned_qi_id"],
            "reviewed_by_qi_id": row["reviewed_by_qi_id"],
            "activity_type": row["activity_type"],
            "frequency_per_year": row["frequency_per_year"],
            "justification_text": row["justification_text"],
            "window_start": iso_ms(row["window_start"]),
            "window_end": iso_ms(row["window_end"]),
            "status": row["status"],
            "revision_count": row["revision_count"],
            "coverage_weight": core.fnum(core.activity_coverage_weight(row)),
        }
    )
    return out


def record_out(row, as_of=None):
    out = _stamps(row)
    out.update(
        {
            "activity_id": row["activity_id"],
            "submitted_by_qi_id": row["submitted_by_qi_id"],
            "attested_by_qi_id": row["attested_by_qi_id"],
            "outcome": row["outcome"],
            "performed_start": iso_ms(row["performed_start"]),
            "performed_end": iso_ms(row["performed_end"]),
            "findings_count": row["findings_count"],
            "document_reference": row["document_reference"],
            "record_status": row["record_status"],
            "weight": core.fnum(core.record_weight(row)),
            "record_points": core.fnum(core.record_points(row)),
            "retained_until": iso_ms(core.record_retained_until(row)),
            "available_for_inspection": core.record_available(row, as_of),
        }
    )
    return out


def action_out(row):
    out = _stamps(row)
    out.update(
        {
            "supplier_id": row["supplier_id"],
            "pair_id": row["pair_id"],
            "trigger_reason": row["trigger_reason"],
            "status": row["status"],
            "decision": row["decision"],
            "rationale": row["rationale"],
            "decided_at": iso_ms(row["decided_at"]),
            "closed_at": iso_ms(row["closed_at"]),
            "pre_action_blocked_pair_count": row["pre_action_blocked_pair_count"],
            "supplier_version_at_decision": row["supplier_version_at_decision"],
        }
    )
    return out


def entry_out(row):
    out = _stamps(row)
    out.update(
        {
            "pair_id": row["pair_id"],
            "entry_number": row["entry_number"],
            "entry_line_number": row["entry_line_number"],
            "dnb_number_submitted": row["dnb_number_submitted"],
            "ufi_submitted": row["ufi_submitted"],
            "arrival_date": iso_ms(row["arrival_date"]),
            "identifier_match": row["identifier_match"],
            "filed_by_user_id": row["filed_by_user_id"],
            "status": row["status"],
            "held_reason": row["held_reason"],
        }
    )
    return out


SERIALIZERS = {
    "importer": importer_out,
    "qi": qi_out,
    "supplier": supplier_out,
    "food": food_out,
    "pair": pair_out,
    "analysis": analysis_out,
    "hazard": hazard_out,
    "activity": activity_out,
    "record": record_out,
    "action": action_out,
    "entry": entry_out,
}
