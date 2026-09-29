"""Entity -> response payload projections (one function per entity)."""

from services import engine


def _common(row, data):
    data["id"] = row["id"]
    data["created_at"] = row["created_at"]
    data["updated_at"] = row["updated_at"]
    data["version"] = row["version"]
    return data


def life_support_system(row):
    return _common(row, {
        "system_code": row["system_code"],
        "system_type": row["system_type"],
        "design_habitat": row["design_habitat"],
        "redundancy_class": row["redundancy_class"],
        "redundancy_test_interval_days": row["redundancy_test_interval_days"],
        "last_redundancy_test_at": row["last_redundancy_test_at"],
        "last_redundancy_test_result": row["last_redundancy_test_result"],
        "redundancy_overdue": engine.redundancy_overdue(row),
        "alarm_state": row["alarm_state"],
        "consecutive_normal_readings": row["consecutive_normal_readings"],
        "consecutive_breach_readings": row["consecutive_breach_readings"],
        "water_quality_index": row["water_quality_index"],
    })


def water_quality_reading(row):
    return {
        "id": row["id"],
        "life_support_system_id": row["life_support_system_id"],
        "taken_at": row["taken_at"],
        "temperature_c": row["temperature_c"],
        "salinity_ppt": row["salinity_ppt"],
        "ph": row["ph"],
        "dissolved_oxygen_mg_l": row["dissolved_oxygen_mg_l"],
        "ammonia_mg_l": row["ammonia_mg_l"],
        "nitrite_mg_l": row["nitrite_mg_l"],
        "severity": row["severity"],
        "breach_parameters": list(row["breach_parameters"]),
        "water_quality_index_snapshot": row["water_quality_index_snapshot"],
        "created_at": row["created_at"],
    }


def exhibit(row):
    return _common(row, {
        "exhibit_code": row["exhibit_code"],
        "name": row["name"],
        "habitat_type": row["habitat_type"],
        "life_support_system_id": row["life_support_system_id"],
        "display_volume_liters": row["display_volume_liters"],
        "bioload_capacity_units": row["bioload_capacity_units"],
        "occupied_bioload_units": row["occupied_bioload_units"],
        "bioload_utilization_pct": row["bioload_utilization_pct"],
        "posture": row["posture"],
        "last_posture_reason": row["last_posture_reason"],
        "interaction_program_enabled": row["interaction_program_enabled"],
        "suspended_session_count": row["suspended_session_count"],
    })


def species(row):
    return _common(row, {
        "scientific_name": row["scientific_name"],
        "common_name": row["common_name"],
        "taxon_group": row["taxon_group"],
        "protection_status": row["protection_status"],
        "sustainability_rating": row["sustainability_rating"],
        "bioload_units_per_specimen": row["bioload_units_per_specimen"],
        "base_quarantine_days": row["base_quarantine_days"],
        "wild_take_quota_annual": row["wild_take_quota_annual"],
        "wild_take_quota_reserved": row["wild_take_quota_reserved"],
        "permit_required": row["permit_required"],
    })


def institution(row):
    return _common(row, {
        "name": row["name"],
        "institution_code": row["institution_code"],
        "accreditation_status": row["accreditation_status"],
        "welfare_audit_score": row["welfare_audit_score"],
        "last_audit_at": row["last_audit_at"],
        "is_receiving_eligible": row["is_receiving_eligible"],
    })


def collection_plan_entry(row):
    return _common(row, {
        "exhibit_id": row["exhibit_id"],
        "species_id": row["species_id"],
        "planned_count": row["planned_count"],
        "sustainability_requirement": row["sustainability_requirement"],
        "status": row["status"],
        "approved_by_user_id": row["approved_by_user_id"],
        "approved_at": row["approved_at"],
        "superseded_by_entry_id": row["superseded_by_entry_id"],
        "suspension_reason": row["suspension_reason"],
    })


def acquisition_request(row):
    return _common(row, {
        "collection_plan_entry_id": row["collection_plan_entry_id"],
        "source_type": row["source_type"],
        "source_institution_id": row["source_institution_id"],
        "requested_count": row["requested_count"],
        "justification": row["justification"],
        "status": row["status"],
        "permit_required": row["permit_required"],
        "permit_deadline_at": row["permit_deadline_at"],
        "sustainability_score": row["sustainability_score"],
        "sustainability_score_variant": row["sustainability_score_variant"],
        "quota_units_reserved": row["quota_units_reserved"],
        "fulfilled_count": row["fulfilled_count"],
        "cleared_by_user_id": row["cleared_by_user_id"],
        "cleared_at": row["cleared_at"],
        "closure_reason": row["closure_reason"],
    })


def permit(row):
    return _common(row, {
        "acquisition_request_id": row["acquisition_request_id"],
        "permit_type": row["permit_type"],
        "authority_reference": row["authority_reference"],
        "document_codes": list(row["document_codes"]),
        "status": row["status"],
        "submission_round": row["submission_round"],
        "missing_document_codes": list(row["missing_document_codes"]),
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "issued_at": row["issued_at"],
        "decision_reason": row["decision_reason"],
    })


def specimen(row):
    return _common(row, {
        "accession_code": row["accession_code"],
        "species_id": row["species_id"],
        "acquisition_request_id": row["acquisition_request_id"],
        "exhibit_id": row["exhibit_id"],
        "holding_area": row["holding_area"],
        "arrival_at": row["arrival_at"],
        "disposition_status": row["disposition_status"],
        "health_status": row["health_status"],
        "pre_transfer_disposition": row["pre_transfer_disposition"],
        "bioload_units": row["bioload_units"],
        "quarantine_required_days": row["quarantine_required_days"],
        "welfare_score": row["welfare_score"],
        "welfare_score_variant": row["welfare_score_variant"],
        "sire_specimen_id": row["sire_specimen_id"],
        "dam_specimen_id": row["dam_specimen_id"],
        "captive_bred": row["captive_bred"],
        "treatment_withdrawal_until": row["treatment_withdrawal_until"],
    })


def quarantine_case(row):
    return _common(row, {
        "specimen_id": row["specimen_id"],
        "protocol_days": row["protocol_days"],
        "started_at": row["started_at"],
        "projected_release_at": row["projected_release_at"],
        "status": row["status"],
        "extension_count": row["extension_count"],
        "total_extension_days": row["total_extension_days"],
        "clearance_exam_count": engine.clearance_exam_count(row),
        "cleared_by_user_id": row["cleared_by_user_id"],
        "cleared_at": row["cleared_at"],
        "failure_reason": row["failure_reason"],
    })


def husbandry_log(row):
    return {
        "id": row["id"],
        "specimen_id": row["specimen_id"],
        "log_type": row["log_type"],
        "logged_at": row["logged_at"],
        "appetite_score": row["appetite_score"],
        "behavior_code": row["behavior_code"],
        "feed_grams": row["feed_grams"],
        "weight_grams": row["weight_grams"],
        "note": row["note"],
        "recorded_by_user_id": row["recorded_by_user_id"],
        "created_at": row["created_at"],
    }


def veterinary_case(row):
    return _common(row, {
        "specimen_id": row["specimen_id"],
        "case_type": row["case_type"],
        "opened_at": row["opened_at"],
        "treatment_start_at": row["treatment_start_at"],
        "withdrawal_days": row["withdrawal_days"],
        "diagnosis_code": row["diagnosis_code"],
        "status": row["status"],
        "outcome": row["outcome"],
        "findings_severity": row["findings_severity"],
        "opened_by_user_id": row["opened_by_user_id"],
        "closed_by_user_id": row["closed_by_user_id"],
        "closed_at": row["closed_at"],
    })


def transfer_request(row):
    return _common(row, {
        "specimen_id": row["specimen_id"],
        "receiving_institution_id": row["receiving_institution_id"],
        "transport_permit_id": row["transport_permit_id"],
        "proposed_transfer_at": row["proposed_transfer_at"],
        "welfare_conditions": list(row["welfare_conditions"]),
        "counter_conditions": list(row["counter_conditions"]),
        "status": row["status"],
        "negotiation_round": row["negotiation_round"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": row["decided_at"],
        "completed_at": row["completed_at"],
        "decline_reason": row["decline_reason"],
    })


def interaction_session(row):
    return _common(row, {
        "exhibit_id": row["exhibit_id"],
        "program_type": row["program_type"],
        "starts_at": row["starts_at"],
        "ends_at": row["ends_at"],
        "max_guests": row["max_guests"],
        "guest_count": row["guest_count"],
        "safety_briefing_confirmed": row["safety_briefing_confirmed"],
        "status": row["status"],
        "suspension_reason": row["suspension_reason"],
    })


def accreditation_audit(row):
    subscores = row["domain_subscores"]
    return _common(row, {
        "audit_code": row["audit_code"],
        "scope": row["scope"],
        "scheduled_for": row["scheduled_for"],
        "status": row["status"],
        "readiness_score": row["readiness_score"],
        "domain_subscores": dict(subscores) if subscores is not None else None,
        "blocking_finding_count": row["blocking_finding_count"],
        "opened_by_user_id": row["opened_by_user_id"],
        "closed_by_user_id": row["closed_by_user_id"],
        "started_at": row["started_at"],
        "closed_at": row["closed_at"],
        "determination_note": row["determination_note"],
    })
