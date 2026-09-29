"""Wire representations. Field sets follow the scaffold entity tables exactly."""
from db import db
from helpers import fmt_date, fmt_instant

CERT_SLOT_STATUSES = ("SUBMITTED", "ACTIVE", "UNDER_AUDIT")
CERT_LIVE_STATUSES = ("ACTIVE", "UNDER_AUDIT")


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "updated_at": fmt_instant(row["updated_at"]),
        "version": row["version"],
    }


def _evidence(row):
    return {"id": row["id"], "created_at": fmt_instant(row["created_at"])}


# --------------------------------------------------------------------------- #
def program_config(row):
    out = _common(row)
    from db import CONFIG_FIELDS

    for field in CONFIG_FIELDS:
        out[field] = row[field]
    return out


def dealer(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "franchise_code": row["franchise_code"],
            "region_code": row["region_code"],
            "privilege_status": row["privilege_status"],
            "privilege_reason": row["privilege_reason"],
            "lifetime_submitted_count": row["lifetime_submitted_count"],
            "lifetime_activated_count": row["lifetime_activated_count"],
            "window_activated_count": row["window_activated_count"],
            "active_certification_count": row["active_certification_count"],
            "approved_claim_count_lifetime": row["approved_claim_count_lifetime"],
            "approved_claim_count_window": row["approved_claim_count_window"],
            "claim_ratio_variant": row["claim_ratio_variant"],
            "claim_ratio_effective": row["claim_ratio_effective"],
            "audit_sample_count": row["audit_sample_count"],
            "audit_fail_count": row["audit_fail_count"],
            "audit_fail_rate": row["audit_fail_rate"],
            "risk_score": row["risk_score"],
            "fee_billed_cents_total": row["fee_billed_cents_total"],
            "fee_credited_cents_total": row["fee_credited_cents_total"],
            "fee_balance_cents": row["fee_balance_cents"],
        }
    )
    return out


def technician(row):
    completed = sum(
        1
        for i in db.inspections.values()
        if i["technician_id"] == row["id"] and i["status"] in ("PASSED", "FAILED")
    )
    out = _common(row)
    out.update(
        {
            "dealer_id": row["dealer_id"],
            "name": row["name"],
            "credential_id": row["credential_id"],
            "credential_expires_at": fmt_instant(row["credential_expires_at"]),
            "credential_status": row["credential_status"],
            "completed_inspection_count": completed,
        }
    )
    return out


def vehicle(row):
    certs = [c for c in db.certifications.values() if c["vehicle_id"] == row["id"]]
    active_count = sum(1 for c in certs if c["status"] in CERT_SLOT_STATUSES)
    certified_id = None
    for c in certs:
        if c["status"] in CERT_LIVE_STATUSES:
            certified_id = c["id"]
            break
    out = _common(row)
    out.update(
        {
            "vin": row["vin"],
            "model_year": row["model_year"],
            "in_service_date": fmt_date(row["in_service_date"]),
            "odometer_miles": row["odometer_miles"],
            "title_brand": row["title_brand"],
            "prior_use": row["prior_use"],
            "owner_count": row["owner_count"],
            "cpo_state": row["cpo_state"],
            "inventory_state": row["inventory_state"],
            "active_certification_count": active_count,
            "certified_certification_id": certified_id,
            "decertified_at": fmt_instant(row["decertified_at"]),
            "last_history_event_type": row["last_history_event_type"],
            "last_history_event_at": fmt_instant(row["last_history_event_at"]),
        }
    )
    return out


def checklist_template(row):
    items = [i for i in db.checklist_items.values() if i["template_id"] == row["id"]]
    out = _common(row)
    out.update(
        {
            "code": row["code"],
            "effective_from": fmt_date(row["effective_from"]),
            "status": row["status"],
            "published_at": fmt_instant(row["published_at"]),
            "point_count": len(items),
            "critical_item_count": sum(1 for i in items if i["severity"] == "CRITICAL"),
        }
    )
    return out


def checklist_item(row):
    out = _evidence(row)
    out.update(
        {
            "template_id": row["template_id"],
            "item_code": row["item_code"],
            "category": row["category"],
            "severity": row["severity"],
            "pass_criteria": row["pass_criteria"],
            "min_measure": row["min_measure"],
            "max_measure": row["max_measure"],
            "reconditioning_allowed": row["reconditioning_allowed"],
            "max_reconditioning_cost_cents": row["max_reconditioning_cost_cents"],
        }
    )
    return out


def inspection(row):
    out = _common(row)
    out.update(
        {
            "vehicle_id": row["vehicle_id"],
            "dealer_id": row["dealer_id"],
            "technician_id": row["technician_id"],
            "template_id": row["template_id"],
            "parent_inspection_id": row["parent_inspection_id"],
            "complaint_id": row["complaint_id"],
            "purpose": row["purpose"],
            "status": row["status"],
            "started_at": fmt_instant(row["started_at"]),
            "slot_end_at": fmt_instant(row["slot_end_at"]),
            "odometer_at_inspection": row["odometer_at_inspection"],
            "vehicle_age_days_at_inspection": row["vehicle_age_days_at_inspection"],
            "attempt_count": row["attempt_count"],
            "recorded_item_count": row["recorded_item_count"],
            "failed_critical_count": row["failed_critical_count"],
            "failed_recon_count": row["failed_recon_count"],
            "total_recon_cost_cents": row["total_recon_cost_cents"],
            "total_reimbursable_cents": row["total_reimbursable_cents"],
            "submitted_at": fmt_instant(row["submitted_at"]),
            "failure_reason": row["failure_reason"],
        }
    )
    return out


def inspection_result(row):
    out = _evidence(row)
    out.update(
        {
            "inspection_id": row["inspection_id"],
            "item_code": row["item_code"],
            "outcome": row["outcome"],
            "measured_value": row["measured_value"],
            "attempt_index": row["attempt_index"],
            "recorded_by_technician_id": row["recorded_by_technician_id"],
            "recorded_at": fmt_instant(row["recorded_at"]),
        }
    )
    return out


def reconditioning_item(row):
    out = _common(row)
    out.update(
        {
            "inspection_id": row["inspection_id"],
            "item_code": row["item_code"],
            "severity": row["severity"],
            "status": row["status"],
            "actual_cost_cents": row["actual_cost_cents"],
            "reimbursable_cents": row["reimbursable_cents"],
            "waiver_reason": row["waiver_reason"],
            "completed_at": fmt_instant(row["completed_at"]),
            "closed_by_user_id": row["closed_by_user_id"],
        }
    )
    return out


def certification(row):
    docs = [d for d in db.documents.values() if d["certification_id"] == row["id"]]
    samples = [s for s in db.audit_samples.values() if s["certification_id"] == row["id"]]
    approved = [
        c
        for c in db.claims.values()
        if c["certification_id"] == row["id"] and c["status"] == "APPROVED"
    ]
    out = _common(row)
    out.update(
        {
            "vehicle_id": row["vehicle_id"],
            "inspection_id": row["inspection_id"],
            "dealer_id": row["dealer_id"],
            "certification_number": row["certification_number"],
            "status": row["status"],
            "submitted_at": fmt_instant(row["submitted_at"]),
            "activated_at": fmt_instant(row["activated_at"]),
            "decertified_at": fmt_instant(row["decertified_at"]),
            "rejection_reason": row["rejection_reason"],
            "decertification_reason": row["decertification_reason"],
            "program_config_version": row["program_config_version"],
            "fee_surcharge_cents": row["fee_surcharge_cents"],
            "fee_discount_cents": row["fee_discount_cents"],
            "fee_charged_cents": row["fee_charged_cents"],
            "fee_credited_cents": row["fee_credited_cents"],
            "warranty_anchor_variant": row["warranty_anchor_variant"],
            "warranty_start_date": fmt_date(row["warranty_start_date"]),
            "warranty_end_date": fmt_date(row["warranty_end_date"]),
            "warranty_end_miles": row["warranty_end_miles"],
            "retention_expires_at": fmt_date(row["retention_expires_at"]),
            "audit_sampled": row["audit_sampled"],
            "audit_sample_count": len(samples),
            "document_count": len(docs),
            "approved_claim_count": len(approved),
            "approved_claim_amount_cents": sum(
                c["approved_amount_cents"] for c in approved
            ),
            "listing_syndicated_at": fmt_instant(row["listing_syndicated_at"]),
        }
    )
    return out


def certification_document(row):
    out = _evidence(row)
    out.update(
        {
            "certification_id": row["certification_id"],
            "doc_type": row["doc_type"],
            "reference": row["reference"],
            "uploaded_at": fmt_instant(row["uploaded_at"]),
            "retained_until": fmt_date(row["retained_until"]),
        }
    )
    return out


def audit_sample(row):
    out = _common(row)
    out.update(
        {
            "certification_id": row["certification_id"],
            "audit_run_id": row["audit_run_id"],
            "selection_rank": row["selection_rank"],
            "status": row["status"],
            "finding_code": row["finding_code"],
            "reviewed_at": fmt_instant(row["reviewed_at"]),
            "reviewer_user_id": row["reviewer_user_id"],
        }
    )
    return out


def warranty_claim(row):
    out = _common(row)
    out.update(
        {
            "certification_id": row["certification_id"],
            "component_category": row["component_category"],
            "repair_date": fmt_date(row["repair_date"]),
            "repair_odometer_miles": row["repair_odometer_miles"],
            "claimed_amount_cents": row["claimed_amount_cents"],
            "status": row["status"],
            "dealer_ratio_snapshot_before": row["dealer_ratio_snapshot_before"],
            "approved_amount_cents": row["approved_amount_cents"],
            "denial_reason": row["denial_reason"],
            "adjudicated_at": fmt_instant(row["adjudicated_at"]),
        }
    )
    return out


def listing(row):
    out = _common(row)
    out.update(
        {
            "certification_id": row["certification_id"],
            "channel": row["channel"],
            "price_cents": row["price_cents"],
            "disclosure_fields": list(row["disclosure_fields"]),
            "status": row["status"],
            "syndicated_at": fmt_instant(row["syndicated_at"]),
            "syndicated_snapshot_version": row["syndicated_snapshot_version"],
            "withdrawn_at": fmt_instant(row["withdrawn_at"]),
            "withdrawal_reason": row["withdrawal_reason"],
            "removal_due_at": fmt_instant(row["removal_due_at"]),
        }
    )
    return out


def complaint(row):
    out = _common(row)
    out.update(
        {
            "certification_id": row["certification_id"],
            "customer_reference": row["customer_reference"],
            "category": row["category"],
            "description": row["description"],
            "status": row["status"],
            "filed_at": fmt_instant(row["filed_at"]),
            "reinspection_deadline_at": fmt_instant(row["reinspection_deadline_at"]),
            "reinspection_ordered_at": fmt_instant(row["reinspection_ordered_at"]),
            "resolved_at": fmt_instant(row["resolved_at"]),
        }
    )
    return out
