"""Resource serializers. Datetime fields are emitted as millisecond ISO 8601 UTC."""

from timeutil import fmt


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt(row["created_at"]),
        "updated_at": fmt(row["updated_at"]),
        "version": row["version"],
    }


def clinician(row):
    out = _common(row)
    out.update(
        {
            "full_name": row["full_name"],
            "staff_role": row["staff_role"],
            "license_number": row["license_number"],
            "booked_docket_minutes": row["booked_docket_minutes"],
        }
    )
    return out


def unit(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "gender_mixing_policy": row["gender_mixing_policy"],
            "seclusion_room_count": row["seclusion_room_count"],
            "licensed_placement_bed_count": row["licensed_placement_bed_count"],
            "raw_available_bed_count": row["raw_available_bed_count"],
            "posture": row["posture"],
            "effective_available_bed_count": row["effective_available_bed_count"],
            "occupied_bed_count": row["occupied_bed_count"],
            "active_seclusion_count": row["active_seclusion_count"],
            "open_rights_violation_count": row["open_rights_violation_count"],
        }
    )
    return out


def bed(row):
    out = _common(row)
    out.update(
        {
            "unit_id": row["unit_id"],
            "room_number": row["room_number"],
            "wing_code": row["wing_code"],
            "bed_label": row["bed_label"],
            "bed_type": row["bed_type"],
            "status": row["status"],
        }
    )
    return out


def patient(row):
    out = _common(row)
    out.update(
        {
            "mrn": row["mrn"],
            "legal_name": row["legal_name"],
            "age_years": row["age_years"],
            "is_minor": row["is_minor"],
            "gender_care_category": row["gender_care_category"],
            "active_hold_count": row["active_hold_count"],
        }
    )
    return out


def evaluation(row):
    out = _common(row)
    out.update(
        {
            "patient_id": row["patient_id"],
            "evaluating_clinician_id": row["evaluating_clinician_id"],
            "evaluation_started_at": fmt(row["evaluation_started_at"]),
            "danger_to_self": row["danger_to_self"],
            "danger_to_others": row["danger_to_others"],
            "grave_disability": row["grave_disability"],
            "capacity_present": row["capacity_present"],
            "clinical_summary": row["clinical_summary"],
            "prior_admission_count_30d": row["prior_admission_count_30d"],
            "acuity_score": row["acuity_score"],
            "acuity_tier": row["acuity_tier"],
            "recommended_status": row["recommended_status"],
            "status": row["status"],
            "signed_at": fmt(row["signed_at"]),
        }
    )
    return out


def hold(row):
    out = _common(row)
    out.update(
        {
            "patient_id": row["patient_id"],
            "evaluation_id": row["evaluation_id"],
            "predecessor_hold_id": row["predecessor_hold_id"],
            "initiated_by_clinician_id": row["initiated_by_clinician_id"],
            "certifying_clinician_id": row["certifying_clinician_id"],
            "hold_type": row["hold_type"],
            "statutory_hours": row["statutory_hours"],
            "clock_started_at": fmt(row["clock_started_at"]),
            "certification_deadline_at": fmt(row["certification_deadline_at"]),
            "release_deadline_at": fmt(row["release_deadline_at"]),
            "petition_filing_deadline_at": fmt(row["petition_filing_deadline_at"]),
            "certified_at": fmt(row["certified_at"]),
            "status": row["status"],
            "closure_reason": row["closure_reason"],
        }
    )
    return out


def petition(row):
    out = _common(row)
    out.update(
        {
            "hold_id": row["hold_id"],
            "petitioning_clinician_id": row["petitioning_clinician_id"],
            "requested_hold_type": row["requested_hold_type"],
            "petition_grounds": row["petition_grounds"],
            "filed_at": fmt(row["filed_at"]),
            "continuance_count": row["continuance_count"],
            "status": row["status"],
        }
    )
    return out


def hearing(row):
    out = _common(row)
    out.update(
        {
            "petition_id": row["petition_id"],
            "advocate_clinician_id": row["advocate_clinician_id"],
            "scheduled_start_at": fmt(row["scheduled_start_at"]),
            "duration_minutes": row["duration_minutes"],
            "scheduled_end_at": fmt(row["scheduled_end_at"]),
            "status": row["status"],
            "outcome": row["outcome"],
            "findings_note": row["findings_note"],
        }
    )
    return out


def admission(row):
    out = _common(row)
    out.update(
        {
            "patient_id": row["patient_id"],
            "evaluation_id": row["evaluation_id"],
            "unit_id": row["unit_id"],
            "bed_id": row["bed_id"],
            "admitting_clinician_id": row["admitting_clinician_id"],
            "search_performed_by_clinician_id": row["search_performed_by_clinician_id"],
            "search_witness_clinician_id": row["search_witness_clinician_id"],
            "legal_status": row["legal_status"],
            "placement_status": row["placement_status"],
            "acuity_tier": row["acuity_tier"],
            "admitted_at": fmt(row["admitted_at"]),
            "placed_at": fmt(row["placed_at"]),
            "discharged_at": fmt(row["discharged_at"]),
            "safety_search_status": row["safety_search_status"],
            "search_type": row["search_type"],
            "search_items_secured_count": row["search_items_secured_count"],
            "contraband_found": row["contraband_found"],
            "capacity_present": row["capacity_present"],
            "discharge_plan_status": row["discharge_plan_status"],
            "follow_up_provider_name": row["follow_up_provider_name"],
            "follow_up_appointment_at": fmt(row["follow_up_appointment_at"]),
            "follow_up_guarantee_days": row["follow_up_guarantee_days"],
            "follow_up_guarantee_deadline_at": fmt(row["follow_up_guarantee_deadline_at"]),
            "observation_staff_quarter_hours": row["observation_staff_quarter_hours"],
            "rights_violation_flag": row["rights_violation_flag"],
            "discharge_summary": row["discharge_summary"],
        }
    )
    return out


def restraint(row):
    out = _common(row)
    out.update(
        {
            "admission_id": row["admission_id"],
            "ordered_by_clinician_id": row["ordered_by_clinician_id"],
            "face_to_face_clinician_id": row["face_to_face_clinician_id"],
            "intervention_type": row["intervention_type"],
            "ordered_duration_minutes": row["ordered_duration_minutes"],
            "clinical_justification": row["clinical_justification"],
            "started_at": fmt(row["started_at"]),
            "authorized_until_at": fmt(row["authorized_until_at"]),
            "face_to_face_deadline_at": fmt(row["face_to_face_deadline_at"]),
            "face_to_face_at": fmt(row["face_to_face_at"]),
            "released_at": fmt(row["released_at"]),
            "actual_duration_minutes": row["actual_duration_minutes"],
            "monitoring_interval_minutes": row["monitoring_interval_minutes"],
            "required_check_count": row["required_check_count"],
            "monitoring_check_log": [
                {
                    "recorded_at": fmt(entry["recorded_at"]),
                    "check_type": entry["check_type"],
                    "recorded_by_clinician_id": entry["recorded_by_clinician_id"],
                    "note": entry["note"],
                }
                for entry in row["monitoring_check_log"]
            ],
            "grid_satisfied_slot_count": row["grid_satisfied_slot_count"],
            "grid_compliance_pct": row["grid_compliance_pct"],
            "raw_compliance_pct": row["raw_compliance_pct"],
            "status": row["status"],
            "debrief_completed_at": fmt(row["debrief_completed_at"]),
            "patient_participated_in_debrief": row["patient_participated_in_debrief"],
            "staff_participants_count": row["staff_participants_count"],
        }
    )
    return out


def capacity_determination(row):
    out = _common(row)
    out.update(
        {
            "admission_id": row["admission_id"],
            "determined_by_clinician_id": row["determined_by_clinician_id"],
            "capacity_present": row["capacity_present"],
            "surrogate_name": row["surrogate_name"],
            "surrogate_relationship": row["surrogate_relationship"],
            "surrogate_authority_scope": row["surrogate_authority_scope"],
            "determined_at": fmt(row["determined_at"]),
            "status": row["status"],
        }
    )
    return out


def medication_consent(row):
    out = _common(row)
    out.update(
        {
            "admission_id": row["admission_id"],
            "capacity_determination_id": row["capacity_determination_id"],
            "prescribing_clinician_id": row["prescribing_clinician_id"],
            "medication_name": row["medication_name"],
            "consent_basis": row["consent_basis"],
            "emergency_justification": row["emergency_justification"],
            "expires_at": fmt(row["expires_at"]),
            "status": row["status"],
        }
    )
    return out


def discharge_request(row):
    out = _common(row)
    out.update(
        {
            "admission_id": row["admission_id"],
            "recorded_by_clinician_id": row["recorded_by_clinician_id"],
            "responding_clinician_id": row["responding_clinician_id"],
            "requested_by": row["requested_by"],
            "requested_at": fmt(row["requested_at"]),
            "response_deadline_at": fmt(row["response_deadline_at"]),
            "decision": row["decision"],
            "status": row["status"],
            "response_note": row["response_note"],
        }
    )
    return out
