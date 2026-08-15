"""Entity serializers — public field sets exactly per SCAFFOLD §1.1."""

import calc


def ser_base(r):
    return {
        "id": r["id"], "name": r["name"], "region": r["region"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_aircraft(r):
    return {
        "id": r["id"], "base_id": r["base_id"], "tail_number": r["tail_number"],
        "aircraft_class": r["aircraft_class"], "medical_config": r["medical_config"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_crew_member(r):
    return {
        "id": r["id"], "base_id": r["base_id"], "full_name": r["full_name"],
        "crew_role": r["crew_role"], "status": r["status"],
        "deficiency_points_90d": calc.deficiency_points_90d(r["id"]),
        "duty_minutes_calendar_day": calc.duty_minutes_calendar_day(r["id"]),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_crew_shift(r):
    return {
        "id": r["id"], "crew_member_id": r["crew_member_id"],
        "planned_start_iso": r["planned_start_iso"],
        "planned_end_iso": r["planned_end_iso"],
        "actual_end_iso": r["actual_end_iso"],
        "planned_minutes": r["planned_minutes"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_patient(r):
    return {
        "id": r["id"], "full_name": r["full_name"],
        "date_of_birth": r["date_of_birth"], "weight_kg": r["weight_kg"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_membership(r):
    return {
        "id": r["id"], "patient_id": r["patient_id"], "tier": r["tier"],
        "effective_from": r["effective_from"], "status": r["status"],
        "lapsed_at": r["lapsed_at"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_mission_request(r):
    return {
        "id": r["id"], "patient_id": r["patient_id"],
        "transport_class": r["transport_class"],
        "origin_facility": r["origin_facility"],
        "destination_facility": r["destination_facility"],
        "destination_country": r["destination_country"],
        "reported_cardio": r["reported_cardio"],
        "reported_resp": r["reported_resp"],
        "reported_neuro": r["reported_neuro"],
        "reported_interventions": r["reported_interventions"],
        "onset_iso": r["onset_iso"],
        "triage_acuity_score": r["triage_acuity_score"],
        "acceptance_acuity_score": r["acceptance_acuity_score"],
        "acuity_tier": r["acuity_tier"],
        "emergency_override": r["emergency_override"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_mission(r):
    return {
        "id": r["id"], "mission_request_id": r["mission_request_id"],
        "aircraft_id": r["aircraft_id"],
        "transport_class": r["transport_class"],
        "acuity_tier": r["acuity_tier"],
        "destination_facility": r["destination_facility"],
        "estimated_loaded_miles": r["estimated_loaded_miles"],
        "planned_launch_iso": r["planned_launch_iso"],
        "planned_duration_min": r["planned_duration_min"],
        "alternate_destination": r["alternate_destination"],
        "launched_at": r["launched_at"],
        "completed_at": r["completed_at"],
        "last_weather_decision": r["last_weather_decision"],
        "ground_coordination_status": r["ground_coordination_status"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_crew_assignment(r):
    return {
        "id": r["id"], "mission_id": r["mission_id"],
        "crew_member_id": r["crew_member_id"],
        "role_in_mission": r["role_in_mission"], "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_weather_assessment(r):
    # Immutable observation: id + created_at only from the standard set.
    return {
        "id": r["id"], "mission_id": r["mission_id"],
        "ceiling_ft": r["ceiling_ft"], "visibility_sm": r["visibility_sm"],
        "wind_kt": r["wind_kt"], "precip": r["precip"],
        "day_night": r["day_night"], "terrain": r["terrain"],
        "decision": r["decision"], "assessed_at": r["assessed_at"],
        "created_at": r["created_at"],
    }


def ser_ground_leg(r):
    return {
        "id": r["id"], "mission_id": r["mission_id"], "leg_type": r["leg_type"],
        "provider_name": r["provider_name"],
        "scheduled_pickup_iso": r["scheduled_pickup_iso"],
        "estimated_ground_miles": r["estimated_ground_miles"],
        "bed_reservation_id": r["bed_reservation_id"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_bed_reservation(r):
    return {
        "id": r["id"], "mission_id": r["mission_id"],
        "facility_name": r["facility_name"], "bed_type": r["bed_type"],
        "hold_until_iso": r["hold_until_iso"], "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_insurance_authorization(r):
    return {
        "id": r["id"], "mission_id": r["mission_id"],
        "payer_name": r["payer_name"], "policy_number": r["policy_number"],
        "approved_amount_cents": r["approved_amount_cents"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_invoice(r):
    return {
        "id": r["id"], "mission_id": r["mission_id"],
        "membership_id": r["membership_id"],
        "estimated_loaded_miles": r["estimated_loaded_miles"],
        "actual_loaded_miles": r["actual_loaded_miles"],
        "base_line_cents": r["base_line_cents"],
        "mileage_line_cents": r["mileage_line_cents"],
        "fuel_line_cents": r["fuel_line_cents"],
        "acuity_line_cents": r["acuity_line_cents"],
        "logistics_line_cents": r["logistics_line_cents"],
        "ground_line_cents": r["ground_line_cents"],
        "provisional_total_cents": r["provisional_total_cents"],
        "final_total_cents": r["final_total_cents"],
        "insurer_paid_cents": r["insurer_paid_cents"],
        "contractual_adjustment_cents": r["contractual_adjustment_cents"],
        "member_writeoff_cents": r["member_writeoff_cents"],
        "patient_responsibility_cents": r["patient_responsibility_cents"],
        "appeal_count": r["appeal_count"],
        "claim_status": r["claim_status"],
        "member_adjustment_status": r["member_adjustment_status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_repatriation_case(r):
    return {
        "id": r["id"], "mission_id": r["mission_id"],
        "destination_country": r["destination_country"],
        "receiving_facility": r["receiving_facility"],
        "documents": [dict(d) for d in r["documents"]],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_pcr(r):
    return {
        "id": r["id"], "mission_id": r["mission_id"],
        "author_crew_id": r["author_crew_id"],
        "vitals_summary": r["vitals_summary"],
        "interventions_summary": r["interventions_summary"],
        "meds_summary": r["meds_summary"],
        "last_review_points": r["last_review_points"],
        "submitted_at": r["submitted_at"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }
