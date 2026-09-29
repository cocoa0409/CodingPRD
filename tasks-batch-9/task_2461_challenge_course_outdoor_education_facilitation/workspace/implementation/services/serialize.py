"""Entity -> JSON serialisation.  Derived counters are computed on read so that a
read immediately following a write always observes the settled world."""
from db import store, fmt_instant
from validation import fmt_date
from services import constants as C
from services import derive


def course(row):
    course_id = row["id"]
    return {
        "id": course_id,
        "course_name": row["course_name"],
        "ems_response_minutes": row["ems_response_minutes"],
        "ems_access_note": row["ems_access_note"],
        "posture": row["posture"],
        "posture_reason": row["posture_reason"],
        "lightning_hold_until": fmt_instant(row["lightning_hold_until"]),
        "latest_wind_speed_kph": derive.latest_wind_speed_kph(course_id),
        "latest_air_temp_c": derive.latest_air_temp_c(course_id),
        "latest_lightning_distance_km": derive.latest_lightning_distance_km(course_id),
        "latest_observation_at": fmt_instant(derive.latest_observation_at(course_id)),
        "restricted_element_count": derive.restricted_element_count(course_id),
        "out_of_service_element_count": derive.out_of_service_element_count(course_id),
        "quarantined_equipment_count": derive.quarantined_equipment_count(course_id),
        "rescue_ready_facilitator_count": derive.rescue_ready_facilitator_count(course_id),
        "rescue_readiness_ok": derive.rescue_readiness_ok(row),
        "next_professional_inspection_due_on": fmt_date(
            derive.course_next_professional_inspection_due_on(course_id)
        ),
        "at_risk_booking_count": derive.at_risk_booking_count(course_id),
        "daily_open_index": row["daily_open_index"],
        "last_daily_open_date": fmt_date(row["last_daily_open_date"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def element(row):
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "element_name": row["element_name"],
        "element_type": row["element_type"],
        "installed_on": fmt_date(row["installed_on"]),
        "design_life_years": row["design_life_years"],
        "cycle_life_limit": row["cycle_life_limit"],
        "cumulative_cycle_count": row["cumulative_cycle_count"],
        "calendar_life_forecast_date": fmt_date(row["calendar_life_forecast_date"]),
        "usage_life_forecast_date": fmt_date(row["usage_life_forecast_date"]),
        "retirement_forecast_date": fmt_date(row["retirement_forecast_date"]),
        "retirement_basis": row["retirement_basis"],
        "min_participant_weight_kg": row["min_participant_weight_kg"],
        "max_participant_weight_kg": row["max_participant_weight_kg"],
        "next_professional_inspection_due_on": fmt_date(row["next_professional_inspection_due_on"]),
        "latest_inspection_outcome": derive.latest_inspection_outcome(row),
        "consecutive_conditional_count": row["consecutive_conditional_count"],
        "required_belay_set_count": row["required_belay_set_count"],
        "belay_ready": derive.belay_ready(row),
        "last_clear_log_date": fmt_date(derive.last_clear_log_date(row["id"])),
        "status": row["status"],
        "restricting_log_id": row["restricting_log_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def facilitator(row):
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "full_name": row["full_name"],
        "staff_type": row["staff_type"],
        "certification_level": row["certification_level"],
        "is_operator_employee": row["is_operator_employee"],
        "cert_expires_on": fmt_date(row["cert_expires_on"]),
        "refresher_hours_24mo": derive.refresher_hours_24mo(row),
        "rescue_drill_last_passed_on": fmt_date(derive.rescue_drill_last_passed_on(row)),
        "cert_status": row["cert_status"],
        "supervision_capacity": C.SUPERVISION_CAPACITY_BY_LEVEL[row["certification_level"]],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def training_record(row):
    return {
        "id": row["id"],
        "facilitator_id": row["facilitator_id"],
        "kind": row["kind"],
        "hours": row["hours"],
        "completed_on": fmt_date(row["completed_on"]),
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


def professional_inspection(row):
    return {
        "id": row["id"],
        "element_id": row["element_id"],
        "inspector_id": row["inspector_id"],
        "performed_on": fmt_date(row["performed_on"]),
        "findings_note": row["findings_note"],
        "outcome": row["outcome"],
        "status": row["status"],
        "disposition_note": row["disposition_note"],
        "disposed_on": fmt_instant(row["disposed_on"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def operational_log(row):
    return {
        "id": row["id"],
        "element_id": row["element_id"],
        "facilitator_id": row["facilitator_id"],
        "log_date": fmt_date(row["log_date"]),
        "result": row["result"],
        "defect_note": row["defect_note"],
        "caused_restriction": row["caused_restriction"],
        "created_at": row["created_at"],
    }


def group_client(row):
    return {
        "id": row["id"],
        "client_name": row["client_name"],
        "org_type": row["org_type"],
        "tier": row["tier"],
        "payments_received_cents": row["payments_received_cents"],
        "credit_balance_cents": row["credit_balance_cents"],
        "late_cancellation_count": derive.late_cancellation_count(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def booking(row):
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "group_client_id": row["group_client_id"],
        "program_date": fmt_date(row["program_date"]),
        "expected_participant_count": row["expected_participant_count"],
        "status": row["status"],
        "roster_status": derive.roster_status(row),
        "billable_head_count": row["billable_head_count"],
        "required_chaperone_count": row["required_chaperone_count"],
        "raw_subtotal_cents": row["raw_subtotal_cents"],
        "high_element_surcharge_cents": row["high_element_surcharge_cents"],
        "quoted_total_cents": row["quoted_total_cents"],
        "deposit_required_cents": row["deposit_required_cents"],
        "deposit_allocated_cents": row["deposit_allocated_cents"],
        "cancellation_fee_cents": row["cancellation_fee_cents"],
        "retained_cents": row["retained_cents"],
        "refund_cents": row["refund_cents"],
        "cancellation_variant": row["cancellation_variant"],
        "notice_days_at_cancel": row["notice_days_at_cancel"],
        "quote_index": row["quote_index"],
        "block_count": derive.block_count(row["id"]),
        "blocked_block_count": derive.blocked_block_count(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def participant(row):
    owning = store.bookings.get(row["booking_id"])
    return {
        "id": row["id"],
        "booking_id": row["booking_id"],
        "full_name": row["full_name"],
        "birth_date": fmt_date(row["birth_date"]),
        "weight_kg": row["weight_kg"],
        "is_chaperone": row["is_chaperone"],
        "age_years": derive.age_years(row, owning) if owning else None,
        "is_minor": derive.is_minor(row, owning) if owning else None,
        "health_form_status": row["health_form_status"],
        "health_flags": list(row["health_flags"]),
        "agreement_signed": row["agreement_signed"],
        "guardian_signature_provided": row["guardian_signature_provided"],
        "medical_clearance_granted": row["medical_clearance_granted"],
        "screening_status": derive.screening_status(row, owning) if owning else "BLOCKED",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def program_block(row):
    return {
        "id": row["id"],
        "booking_id": row["booking_id"],
        "element_id": row["element_id"],
        "sequence_index": row["sequence_index"],
        "phase": row["phase"],
        "planned_start_at": fmt_instant(row["planned_start_at"]),
        "planned_end_at": fmt_instant(row["planned_end_at"]),
        "status": row["status"],
        "required_facilitator_count": derive.required_facilitator_count(row),
        "assigned_facilitator_count": derive.assigned_facilitator_count(row["id"]),
        "actual_head_count": row["actual_head_count"],
        "debrief_completed": row["debrief_completed"],
        "started_at": fmt_instant(row["started_at"]),
        "completed_at": fmt_instant(row["completed_at"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def block_assignment(row):
    return {
        "id": row["id"],
        "program_block_id": row["program_block_id"],
        "facilitator_id": row["facilitator_id"],
        "assignment_role": row["assignment_role"],
        "rescue_current_at_assignment": row["rescue_current_at_assignment"],
        "created_at": row["created_at"],
    }


def belay_equipment(row):
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "assigned_element_id": row["assigned_element_id"],
        "equipment_kind": row["equipment_kind"],
        "serial_number": row["serial_number"],
        "manufactured_on": fmt_date(row["manufactured_on"]),
        "first_use_on": fmt_date(row["first_use_on"]),
        "usage_cycles": row["usage_cycles"],
        "max_cycles": row["max_cycles"],
        "mfg_life_forecast_date": fmt_date(row["mfg_life_forecast_date"]),
        "service_life_forecast_date": fmt_date(row["service_life_forecast_date"]),
        "retirement_forecast_date": fmt_date(row["retirement_forecast_date"]),
        "retirement_basis": row["retirement_basis"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def weather_observation(row):
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "observed_at": fmt_instant(row["observed_at"]),
        "lightning_distance_km": row["lightning_distance_km"],
        "wind_speed_kph": row["wind_speed_kph"],
        "air_temp_c": row["air_temp_c"],
        "resulting_posture": row["resulting_posture"],
        "resulting_posture_reason": row["resulting_posture_reason"],
        "hold_until": fmt_instant(row["hold_until"]),
        "created_at": row["created_at"],
    }


def incident(row):
    return {
        "id": row["id"],
        "course_id": row["course_id"],
        "element_id": row["element_id"],
        "participant_id": row["participant_id"],
        "reported_by_facilitator_id": row["reported_by_facilitator_id"],
        "occurred_at": fmt_instant(row["occurred_at"]),
        "severity": row["severity"],
        "narrative": row["narrative"],
        "ems_activated": row["ems_activated"],
        "status": row["status"],
        "corrective_action": row["corrective_action"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }
