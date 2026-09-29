"""Resource serializers."""

from decimal import Decimal

from store import fmt_iso


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_iso(rec["created_at"]),
        "updated_at": fmt_iso(rec["updated_at"]),
        "version": rec["version"],
    }


def program(rec):
    out = _common(rec)
    out.update(
        {
            "org_name": rec["org_name"],
            "org_type": rec["org_type"],
            "exposure_ceiling_cents": rec["exposure_ceiling_cents"],
            "posture": rec["posture"],
            "consent_gap_count": rec["consent_gap_count"],
            "gated_asset_count": rec["gated_asset_count"],
            "open_deletion_obligation_count": rec["open_deletion_obligation_count"],
            "pra_exposure_cents": rec["pra_exposure_cents"],
            "inventory_completeness_pct": _num(rec["inventory_completeness_pct"]),
        }
    )
    return out


def jurisdiction(rec):
    out = _common(rec)
    out.update(
        {
            "program_id": rec["program_id"],
            "state_code": rec["state_code"],
            "statute_name": rec["statute_name"],
            "private_right_of_action": rec["private_right_of_action"],
            "damages_model": rec["damages_model"],
            "requires_written_release": rec["requires_written_release"],
            "translation_required": rec["translation_required"],
            "required_locales": list(rec["required_locales"]),
            "retention_max_days": rec["retention_max_days"],
            "notice_lead_days": rec["notice_lead_days"],
            "per_violation_negligent_cents": rec["per_violation_negligent_cents"],
            "per_violation_reckless_cents": rec["per_violation_reckless_cents"],
            "cure_period_days": rec["cure_period_days"],
            "statutory_cap_cents": rec["statutory_cap_cents"],
        }
    )
    return out


def vendor(rec):
    out = _common(rec)
    out.update(
        {
            "program_id": rec["program_id"],
            "name": rec["name"],
            "sells_biometric_data": rec["sells_biometric_data"],
            "subprocessor_count": rec["subprocessor_count"],
            "subprocessor_disclosure_complete": rec["subprocessor_disclosure_complete"],
            "deletion_sla_days": rec["deletion_sla_days"],
            "attestation_status": rec["attestation_status"],
            "risk_score": _num(rec["risk_score"]),
        }
    )
    return out


def contract(rec):
    out = _common(rec)
    out.update(
        {
            "vendor_id": rec["vendor_id"],
            "prohibits_sale": rec["prohibits_sale"],
            "restricts_disclosure": rec["restricts_disclosure"],
            "requires_deletion_on_termination": rec["requires_deletion_on_termination"],
            "deletion_deadline_days": rec["deletion_deadline_days"],
            "indemnity_cap_cents": rec["indemnity_cap_cents"],
            "effective_from": fmt_iso(rec["effective_from"]),
            "compliance_score": _num(rec["compliance_score"]),
            "status": rec["status"],
            "drafted_by_user_id": rec["drafted_by_user_id"],
            "approved_by_user_id": rec["approved_by_user_id"],
            "terminated_at": fmt_iso(rec["terminated_at"]),
            "deletion_deadline_at": fmt_iso(rec["deletion_deadline_at"]),
            "deletion_certificate_ref": rec["deletion_certificate_ref"],
        }
    )
    return out


def policy(rec):
    out = _common(rec)
    out.update(
        {
            "program_id": rec["program_id"],
            "version_label": rec["version_label"],
            "retention_days": rec["retention_days"],
            "destruction_trigger": rec["destruction_trigger"],
            "release_language_included": rec["release_language_included"],
            "jurisdiction_scope": list(rec["jurisdiction_scope"]),
            "status": rec["status"],
            "published_at": fmt_iso(rec["published_at"]),
            "submitted_by_user_id": rec["submitted_by_user_id"],
            "published_by_user_id": rec["published_by_user_id"],
            "revision_count": rec["revision_count"],
        }
    )
    return out


def notice(rec):
    out = _common(rec)
    out.update(
        {
            "program_id": rec["program_id"],
            "jurisdiction_id": rec["jurisdiction_id"],
            "policy_id": rec["policy_id"],
            "audience": rec["audience"],
            "locales": list(rec["locales"]),
            "accommodation_channel": rec["accommodation_channel"],
            "effective_from": fmt_iso(rec["effective_from"]),
            "effective_to": fmt_iso(rec["effective_to"]),
            "status": rec["status"],
            "published_at": fmt_iso(rec["published_at"]),
            "consent_eligible_from": fmt_iso(rec["consent_eligible_from"]),
        }
    )
    return out


def asset(rec):
    out = _common(rec)
    out.update(
        {
            "program_id": rec["program_id"],
            "jurisdiction_id": rec["jurisdiction_id"],
            "vendor_id": rec["vendor_id"],
            "pinned_policy_id": rec["pinned_policy_id"],
            "system_category": rec["system_category"],
            "modality": rec["modality"],
            "subject_class": rec["subject_class"],
            "template_storage_location": rec["template_storage_location"],
            "declared_retention_days": rec["declared_retention_days"],
            "retention_basis": rec["retention_basis"],
            "status": rec["status"],
            "collection_started_at": fmt_iso(rec["collection_started_at"]),
            "purpose_satisfied_at": fmt_iso(rec["purpose_satisfied_at"]),
            "destruction_due_at": fmt_iso(rec["destruction_due_at"]),
            "templates_destroyed_at": fmt_iso(rec["templates_destroyed_at"]),
            "enrolled_subject_count": rec["enrolled_subject_count"],
            "consent_gap_count": rec["consent_gap_count"],
        }
    )
    return out


def subject(rec):
    out = _common(rec)
    out.update(
        {
            "program_id": rec["program_id"],
            "jurisdiction_id": rec["jurisdiction_id"],
            "subject_type": rec["subject_type"],
            "external_ref": rec["external_ref"],
            "preferred_locale": rec["preferred_locale"],
            "accommodation_needed": rec["accommodation_needed"],
            "enrollment_status": rec["enrollment_status"],
            "active_accommodation_count": rec["active_accommodation_count"],
        }
    )
    return out


def consent(rec):
    out = _common(rec)
    out.update(
        {
            "data_subject_id": rec["data_subject_id"],
            "asset_id": rec["asset_id"],
            "pinned_policy_id": rec["pinned_policy_id"],
            "locale": rec["locale"],
            "status": rec["status"],
            "written_release_acknowledged": rec["written_release_acknowledged"],
            "signature_ref": rec["signature_ref"],
            "signed_at": fmt_iso(rec["signed_at"]),
            "pinned_retention_days": rec["pinned_retention_days"],
            "record_retention_until": fmt_iso(rec["record_retention_until"]),
            "decline_reason": rec["decline_reason"],
            "revocation_reason": rec["revocation_reason"],
            "solicitation_round": rec["solicitation_round"],
        }
    )
    return out


def accommodation(rec):
    out = _common(rec)
    out.update(
        {
            "data_subject_id": rec["data_subject_id"],
            "asset_id": rec["asset_id"],
            "created_from_consent_id": rec["created_from_consent_id"],
            "method": rec["method"],
            "starts_at": fmt_iso(rec["starts_at"]),
            "ends_at": fmt_iso(rec["ends_at"]),
            "status": rec["status"],
            "sla_due_at": fmt_iso(rec["sla_due_at"]),
            "sla_breached": rec["sla_breached"],
            "origin": rec["origin"],
        }
    )
    return out


def incident(rec):
    out = _common(rec)
    out.update(
        {
            "program_id": rec["program_id"],
            "affected_asset_ids": list(rec["affected_asset_ids"]),
            "exposure_vector": rec["exposure_vector"],
            "description": rec["description"],
            "discovered_at": fmt_iso(rec["discovered_at"]),
            "exposed_subject_count": rec["exposed_subject_count"],
            "heightened_tier": rec["heightened_tier"],
            "notification_due_at": fmt_iso(rec["notification_due_at"]),
            "containment_status": rec["containment_status"],
            "notification_status": rec["notification_status"],
            "translation_locale_count": rec["translation_locale_count"],
            "gross_notice_cents": rec["gross_notice_cents"],
            "regulator_surcharge_cents": rec["regulator_surcharge_cents"],
            "vendor_indemnity_credit_cents": rec["vendor_indemnity_credit_cents"],
            "net_incident_cost_cents": rec["net_incident_cost_cents"],
            "notified_subject_count": rec["notified_subject_count"],
            "notified_at": fmt_iso(rec["notified_at"]),
            "late_notification": rec["late_notification"],
            "exemption_basis": rec["exemption_basis"],
            "containment_note": rec["containment_note"],
        }
    )
    return out


def assessment(rec):
    out = _common(rec)
    out.update(
        {
            "program_id": rec["program_id"],
            "jurisdiction_id": rec["jurisdiction_id"],
            "incident_id": rec["incident_id"],
            "variant": rec["variant"],
            "status": rec["status"],
            "negligent_unit_count": rec["negligent_unit_count"],
            "reckless_unit_count": rec["reckless_unit_count"],
            "base_cents": rec["base_cents"],
            "notice_gap_multiplier": _num(rec["notice_gap_multiplier"]),
            "cure_credit_pct": _num(rec["cure_credit_pct"]),
            "exposure_cents": rec["exposure_cents"],
            "created_by_user_id": rec["created_by_user_id"],
            "finalized_by_user_id": rec["finalized_by_user_id"],
            "void_reason": rec["void_reason"],
        }
    )
    return out
