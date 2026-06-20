"""Public serializers — strip internal fields from stored entities."""

# Internal-only keys never exposed in the API response
_INTERNAL = {"_seq", "_prior_status"}


def _clean(ent):
    return {k: v for k, v in ent.items() if k not in _INTERNAL}


def ser_program(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "description": p.get("description"),
        "current_date": p["current_date"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_jurisdiction(j):
    return {
        "id": j["id"],
        "program_id": j["program_id"],
        "name": j["name"],
        "fips_code": j["fips_code"],
        "active_monitoring_count": j["active_monitoring_count"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def ser_condition(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "condition_code": c["condition_code"],
        "display_name": c["display_name"],
        "presymptomatic_days": c["presymptomatic_days"],
        "infectious_tail_days": c["infectious_tail_days"],
        "quarantine_days": c["quarantine_days"],
        "test_based_release_days": c["test_based_release_days"],
        "test_release_earliest_offset_days": c["test_release_earliest_offset_days"],
        "isolation_min_days": c["isolation_min_days"],
        "fever_free_days": c["fever_free_days"],
        "cluster_min_cases": c["cluster_min_cases"],
        "cluster_window_days": c["cluster_window_days"],
        "requires_lab_confirmation": c["requires_lab_confirmation"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_case(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "jurisdiction_id": c["jurisdiction_id"],
        "condition_code": c["condition_code"],
        "patient_reference": c["patient_reference"],
        "source_lab_result_id": c.get("source_lab_result_id"),
        "source_contact_id": c.get("source_contact_id"),
        "symptom_onset_date": c.get("symptom_onset_date"),
        "specimen_collection_date": c.get("specimen_collection_date"),
        "last_symptomatic_date": c.get("last_symptomatic_date"),
        "is_symptomatic": c["is_symptomatic"],
        "interview_completed": c["interview_completed"],
        "infectious_start_date": c.get("infectious_start_date"),
        "infectious_end_date": c.get("infectious_end_date"),
        "isolation_end_date": c.get("isolation_end_date"),
        "completeness_score": c["completeness_score"],
        "contact_count": c["contact_count"],
        "linked_positive_count": c["linked_positive_count"],
        "cluster_id": c.get("cluster_id"),
        "exposure_setting_location_id": c.get("exposure_setting_location_id"),
        "classification": c["classification"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_lab_result(l):
    return {
        "id": l["id"],
        "program_id": l["program_id"],
        "jurisdiction_id": l["jurisdiction_id"],
        "condition_code": l["condition_code"],
        "patient_reference": l["patient_reference"],
        "result_value": l["result_value"],
        "specimen_collection_date": l.get("specimen_collection_date"),
        "linked_case_id": l.get("linked_case_id"),
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_contact(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "source_case_id": c["source_case_id"],
        "monitoring_jurisdiction_id": c["monitoring_jurisdiction_id"],
        "contact_reference": c["contact_reference"],
        "exposure_setting": c["exposure_setting"],
        "proximity_meters": c["proximity_meters"],
        "cumulative_exposure_minutes": c["cumulative_exposure_minutes"],
        "is_high_risk_contact": c["is_high_risk_contact"],
        "last_exposure_date": c.get("last_exposure_date"),
        "priority_score": c["priority_score"],
        "priority_band": c["priority_band"],
        "quarantine_release_basis": c["quarantine_release_basis"],
        "quarantine_end_date": c.get("quarantine_end_date"),
        "has_qualifying_negative_test": c["has_qualifying_negative_test"],
        "notification_attempts": c["notification_attempts"],
        "promoted_case_id": c.get("promoted_case_id"),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_exposure_event(e):
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "contact_id": e["contact_id"],
        "case_id": e["case_id"],
        "encounter_date": e.get("encounter_date"),
        "setting_note": e.get("setting_note"),
        "created_at": e["created_at"],
    }


def ser_monitoring_period(m):
    return {
        "id": m["id"],
        "program_id": m["program_id"],
        "contact_id": m["contact_id"],
        "jurisdiction_id": m["jurisdiction_id"],
        "monitoring_type": m["monitoring_type"],
        "start_date": m.get("start_date"),
        "end_date": m.get("end_date"),
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_transfer(t):
    return {
        "id": t["id"],
        "program_id": t["program_id"],
        "case_id": t["case_id"],
        "from_jurisdiction_id": t["from_jurisdiction_id"],
        "to_jurisdiction_id": t["to_jurisdiction_id"],
        "expected_case_version": t["expected_case_version"],
        "reason": t.get("reason"),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_cluster(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "condition_code": c["condition_code"],
        "exposure_setting_location_id": c["exposure_setting_location_id"],
        "anchor_case_id": c["anchor_case_id"],
        "member_case_count": c["member_case_count"],
        "earliest_onset_date": c.get("earliest_onset_date"),
        "latest_onset_date": c.get("latest_onset_date"),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_export(e):
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "case_id": e["case_id"],
        "snapshot_classification": e["snapshot_classification"],
        "snapshot_completeness_score": e["snapshot_completeness_score"],
        "nedss_message_id": e["nedss_message_id"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }
