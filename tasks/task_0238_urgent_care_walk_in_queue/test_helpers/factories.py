"""Payload factories — one per entity, input fields only."""


def create_clinic_payload(**overrides) -> dict:
    """POST /clinics. Required: name, exam_room_capacity.
    Optional: surge_threshold, diversion_threshold, avg_provider_minutes_per_esi,
    self_pay_discount_pct."""
    defaults = {
        "name": "Test Clinic",
        "exam_room_capacity": 4,
    }
    defaults.update(overrides)
    return defaults


def create_exam_room_payload(**overrides) -> dict:
    """POST /clinics/{id}/exam-rooms. Required: room_label. Optional: room_type."""
    defaults = {
        "room_label": "Room A",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    """POST /clinics/{id}/providers. Required: full_name, credential.
    Optional: on_shift, max_concurrent_visits."""
    defaults = {
        "full_name": "Dr Test",
        "credential": "MD",
    }
    defaults.update(overrides)
    return defaults


def create_queue_entry_payload(arrival_channel="WALK_IN", chief_complaint="cough", **overrides) -> dict:
    """POST /clinics/{id}/queue-entries. Required: arrival_channel, chief_complaint."""
    defaults = {
        "arrival_channel": arrival_channel,
        "chief_complaint": chief_complaint,
    }
    defaults.update(overrides)
    return defaults


def triage_payload(esi_level=3, **overrides) -> dict:
    """POST .../triage and .../re-triage. Required: esi_level. Optional: airborne_precaution."""
    defaults = {"esi_level": esi_level}
    defaults.update(overrides)
    return defaults


def create_patient_payload(queue_entry_id, legal_name="Test Patient",
                           date_of_birth="1990-01-01", **overrides) -> dict:
    """POST /patients. Required: queue_entry_id, legal_name, date_of_birth.
    Optional: guarantor_name, consent_signed."""
    defaults = {
        "queue_entry_id": queue_entry_id,
        "legal_name": legal_name,
        "date_of_birth": date_of_birth,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_payload(patient_id, coverage_type="SELF_PAY", **overrides) -> dict:
    """POST /coverages. Required: patient_id, coverage_type.
    Optional: payer_name, member_id, copay_cents."""
    defaults = {
        "patient_id": patient_id,
        "coverage_type": coverage_type,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(queue_entry_id, provider_id, exam_room_id,
                         expected_clinic_version, **overrides) -> dict:
    """POST /visits. Required: queue_entry_id, provider_id, exam_room_id,
    expected_clinic_version. Optional: override."""
    defaults = {
        "queue_entry_id": queue_entry_id,
        "provider_id": provider_id,
        "exam_room_id": exam_room_id,
        "expected_clinic_version": expected_clinic_version,
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(cpt_code="99213", amount_cents=10000, **overrides) -> dict:
    """POST /visits/{id}/charges. Required: cpt_code, amount_cents. Optional: source_type."""
    defaults = {
        "cpt_code": cpt_code,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def complete_charting_payload(chart_note="Encounter complete.", **overrides) -> dict:
    """POST /visits/{id}/complete-charting. Required: chart_note."""
    defaults = {"chart_note": chart_note}
    defaults.update(overrides)
    return defaults


def transfer_payload(destination_facility="County ER",
                     transfer_reason="ACUITY_ESCALATION", **overrides) -> dict:
    """POST /visits/{id}/transfer. Required: destination_facility, transfer_reason.
    Optional: mode."""
    defaults = {
        "destination_facility": destination_facility,
        "transfer_reason": transfer_reason,
    }
    defaults.update(overrides)
    return defaults


def settle_payload(expected_visit_version, **overrides) -> dict:
    """POST /visits/{id}/settle. Required: expected_visit_version."""
    defaults = {"expected_visit_version": expected_visit_version}
    defaults.update(overrides)
    return defaults


def verify_payload(outcome="ELIGIBLE", **overrides) -> dict:
    """POST /coverages/{id}/verify. Required: outcome."""
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_occ_health_order_payload(queue_entry_id, order_type, employer_name,
                                    scheduled_start, collector_id, **overrides) -> dict:
    """POST /occ-health-orders. Required: queue_entry_id, order_type, employer_name,
    scheduled_start, collector_id. Optional: room_id, duration_minutes."""
    defaults = {
        "queue_entry_id": queue_entry_id,
        "order_type": order_type,
        "employer_name": employer_name,
        "scheduled_start": scheduled_start,
        "collector_id": collector_id,
    }
    defaults.update(overrides)
    return defaults


def occ_result_payload(result="NEGATIVE", **overrides) -> dict:
    """POST /occ-health-orders/{id}/result. Required: result."""
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def create_discharge_instruction_payload(instructions_text="Rest and fluids.", **overrides) -> dict:
    """POST /visits/{id}/discharge-instructions. Required: instructions_text.
    Optional: follow_up_within_days."""
    defaults = {"instructions_text": instructions_text}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    """POST /_clock/set."""
    return {"to_iso8601": to_iso8601}


def seed_queue_depth_payload(clinic_id, count) -> dict:
    """POST /_seed/queue-depth."""
    return {"clinic_id": clinic_id, "count": count}
