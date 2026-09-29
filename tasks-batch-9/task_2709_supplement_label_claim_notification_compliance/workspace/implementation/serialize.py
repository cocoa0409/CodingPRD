"""Resource serializers.  Every resource carries id, created_at, updated_at, version."""

import calc
import db


def _common(row):
    return {
        "id": row["id"],
        "created_at": db.iso(row["created_at"]),
        "updated_at": db.iso(row["updated_at"]),
        "version": row["version"],
    }


def product(row):
    data = _common(row)
    data.update(
        {
            "brand_name": row["brand_name"],
            "product_name": row["product_name"],
            "net_quantity_g": row["net_quantity_g"],
            "servings_per_container": row["servings_per_container"],
            "lifecycle_status": row["lifecycle_status"],
            "label_posture": row["label_posture"],
            "marketing_start_date": db.iso_date(row["marketing_start_date"]),
            "serious_ae_count": row["serious_ae_count"],
            "nonserious_ae_count": row["nonserious_ae_count"],
            "late_notification_count": row["late_notification_count"],
            "rejected_coa_count": row["rejected_coa_count"],
            "compliance_risk_index": row["compliance_risk_index"],
            "active_claim_count": row["active_claim_count"],
            "withdrawn_claim_count": row["withdrawn_claim_count"],
            "requires_label_revision": row["requires_label_revision"],
        }
    )
    return data


def ingredient(row):
    data = _common(row)
    data.update(
        {
            "ingredient_name": row["ingredient_name"],
            "ingredient_class": row["ingredient_class"],
            "pre_dshea_marketed": row["pre_dshea_marketed"],
            "chemical_alteration": row["chemical_alteration"],
            "daily_intake_mg": row["daily_intake_mg"],
            "rdi_mg": row["rdi_mg"],
            "allergen_code": row["allergen_code"],
            "contraindication_code": row["contraindication_code"],
            "predecessor_ingredient_id": row["predecessor_ingredient_id"],
            "eligibility_status": row["eligibility_status"],
            "ndi_notification_required": row["ndi_notification_required"],
            "determined_at": db.iso(row["determined_at"]),
        }
    )
    return data


def product_ingredient(row):
    data = _common(row)
    data.update(
        {
            "product_id": row["product_id"],
            "ingredient_id": row["ingredient_id"],
            "amount_per_serving_mg": row["amount_per_serving_mg"],
            "panel_position": row["panel_position"],
            "line_status": row["line_status"],
            "percent_dv_declared": row["percent_dv_declared"],
            "dv_established": row["dv_established"],
        }
    )
    return data


def ndi_notification(row):
    data = _common(row)
    data.update(
        {
            "ingredient_id": row["ingredient_id"],
            "submitter_reference": row["submitter_reference"],
            "safety_narrative": row["safety_narrative"],
            "notification_status": row["notification_status"],
            "submitted_at": db.iso(row["submitted_at"]),
            "waiting_period_end": db.iso(row["waiting_period_end"]),
            "agency_response_at": db.iso(row["agency_response_at"]),
            "agency_objection_reason": row["agency_objection_reason"],
        }
    )
    return data


def claim(row):
    data = _common(row)
    data.update(
        {
            "product_id": row["product_id"],
            "ingredient_id": row["ingredient_id"],
            "claim_text": row["claim_text"],
            "claim_type": row["claim_type"],
            "substantiation_status": row["substantiation_status"],
            "notification_status": row["notification_status"],
            "authored_by_user_id": row["authored_by_user_id"],
            "approved_by_user_id": row["approved_by_user_id"],
            "approved_at": db.iso(row["approved_at"]),
            "notification_due_date": db.iso_date(row["notification_due_date"]),
            "notification_due_basis": row["notification_due_basis"],
            "notified_at": db.iso(row["notified_at"]),
            "submission_reference": row["submission_reference"],
            "revision_round": row["revision_round"],
            "requires_recheck": row["requires_recheck"],
            "withdrawal_reason": row["withdrawal_reason"],
        }
    )
    return data


def dossier(row):
    data = _common(row)
    data.update(
        {
            "claim_id": row["claim_id"],
            "dossier_summary": row["dossier_summary"],
            "authored_by_user_id": row["authored_by_user_id"],
            "dossier_status": row["dossier_status"],
            "evidence_studies": [dict(s) for s in row["evidence_studies"]],
            "study_count": row["study_count"],
            "screening_score": calc.num2(row["screening_score"]),
            "final_score": None if row["final_score"] is None else calc.num2(row["final_score"]),
            "reviewed_by_user_id": row["reviewed_by_user_id"],
            "reviewed_at": db.iso(row["reviewed_at"]),
            "review_decision": row["review_decision"],
            "rejection_reason": row["rejection_reason"],
        }
    )
    return data


def panel(row):
    data = _common(row)
    data.update(
        {
            "product_id": row["product_id"],
            "supersedes_panel_id": row["supersedes_panel_id"],
            "panel_format": row["panel_format"],
            "serving_size_text": row["serving_size_text"],
            "serving_weight_g": row["serving_weight_g"],
            "servings_per_container_declared": row["servings_per_container_declared"],
            "effective_from": db.iso_date(row["effective_from"]),
            "effective_until": db.iso_date(row["effective_until"]),
            "declared_warning_codes": list(row["declared_warning_codes"]),
            "disclaimer_text": row["disclaimer_text"],
            "panel_status": row["panel_status"],
            "required_warning_codes": list(row["required_warning_codes"]),
            "panel_lines_required": row["panel_lines_required"],
            "panel_lines_allowed": row["panel_lines_allowed"],
            "panel_total_dv_coverage_pct": row["panel_total_dv_coverage_pct"],
            "validated_at": db.iso(row["validated_at"]),
            "locked_at": db.iso(row["locked_at"]),
        }
    )
    return data


def aer(row):
    data = _common(row)
    data.update(
        {
            "product_id": row["product_id"],
            "reporter_type": row["reporter_type"],
            "received_date": db.iso_date(row["received_date"]),
            "narrative": row["narrative"],
            "outcome_codes": list(row["outcome_codes"]),
            "is_serious": row["is_serious"],
            "aer_status": row["aer_status"],
            "submission_due_date": db.iso_date(row["submission_due_date"]),
            "submitted_at": db.iso(row["submitted_at"]),
            "submission_timeliness": row["submission_timeliness"],
            "submission_reference": row["submission_reference"],
            "retention_until": db.iso_date(row["retention_until"]),
            "triaged_at": db.iso(row["triaged_at"]),
        }
    )
    return data


def supplier(row):
    data = _common(row)
    data.update(
        {
            "supplier_name": row["supplier_name"],
            "country_code": row["country_code"],
            "qualification_status": row["qualification_status"],
            "audit_score": row["audit_score"],
            "coa_rejection_count": row["coa_rejection_count"],
            "total_released_kg": calc.num2(row["total_released_kg"]),
            "remediation_reference": row["remediation_reference"],
            "last_decision_at": db.iso(row["last_decision_at"]),
        }
    )
    return data


def lot(row):
    data = _common(row)
    data.update(
        {
            "supplier_id": row["supplier_id"],
            "ingredient_id": row["ingredient_id"],
            "lot_code": row["lot_code"],
            "quantity_kg": calc.num2(row["quantity_kg"]),
            "quarantined_quantity_kg": calc.num2(row["quarantined_quantity_kg"]),
            "released_quantity_kg": calc.num2(row["released_quantity_kg"]),
            "rejected_quantity_kg": calc.num2(row["rejected_quantity_kg"]),
            "lot_status": row["lot_status"],
            "identity_verified": row["identity_verified"],
            "released_at": db.iso(row["released_at"]),
            "recalled_at": db.iso(row["recalled_at"]),
            "recall_reason": row["recall_reason"],
        }
    )
    return data


def coa(row):
    data = _common(row)
    data.update(
        {
            "lot_id": row["lot_id"],
            "lab_name": row["lab_name"],
            "identity_test_method": row["identity_test_method"],
            "identity_match": row["identity_match"],
            "assay_percent_of_label": row["assay_percent_of_label"],
            "heavy_metals_pass": row["heavy_metals_pass"],
            "microbial_pass": row["microbial_pass"],
            "coa_acceptable": row["coa_acceptable"],
            "coa_status": row["coa_status"],
            "review_decision": row["review_decision"],
            "reviewed_by_user_id": row["reviewed_by_user_id"],
            "reviewed_at": db.iso(row["reviewed_at"]),
            "rejection_reason": row["rejection_reason"],
        }
    )
    return data


def risk_profile(row, base, surcharge, supplier_ids):
    """Computed read of PRD 3.3: counters, index, surcharge tier, derived supplier set."""
    return {
        "product_id": row["id"],
        "id": row["id"],
        "serious_ae_count": row["serious_ae_count"],
        "nonserious_ae_count": row["nonserious_ae_count"],
        "late_notification_count": row["late_notification_count"],
        "rejected_coa_count": row["rejected_coa_count"],
        "base_score": base,
        "escalation_surcharge": surcharge,
        "compliance_risk_index": row["compliance_risk_index"],
        "derived_supplier_set": list(supplier_ids),
        "derived_supplier_ids": list(supplier_ids),
        "label_posture": row["label_posture"],
        "requires_label_revision": row["requires_label_revision"],
        "lifecycle_status": row["lifecycle_status"],
    }
