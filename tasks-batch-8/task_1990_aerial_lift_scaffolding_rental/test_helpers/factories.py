"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_customer_account_payload(company_name="Test Renter Co",
                                    contact_email="ops@renter.example",
                                    credit_limit_cents=100_000_000,
                                    **overrides) -> dict:
    payload = {
        "company_name": company_name,
        "contact_email": contact_email,
        "credit_limit_cents": credit_limit_cents,
    }
    payload.update(overrides)
    return payload


def create_equipment_class_payload(class_code="S19",
                                   category="AERIAL_LIFT",
                                   max_working_height_ft=25,
                                   min_rental_days=1,
                                   daily_rate_cents=14500,
                                   weekly_rate_cents=43500,
                                   monthly_rate_cents=99000,
                                   replacement_value_cents=2_500_000,
                                   requires_familiarization=False,
                                   requires_engineering=False,
                                   **overrides) -> dict:
    payload = {
        "class_code": class_code,
        "category": category,
        "max_working_height_ft": max_working_height_ft,
        "min_rental_days": min_rental_days,
        "daily_rate_cents": daily_rate_cents,
        "weekly_rate_cents": weekly_rate_cents,
        "monthly_rate_cents": monthly_rate_cents,
        "replacement_value_cents": replacement_value_cents,
        "requires_familiarization": requires_familiarization,
        "requires_engineering": requires_engineering,
    }
    payload.update(overrides)
    return payload


def create_equipment_unit_payload(class_id, serial_number="SN-0001",
                                  ansi_standard_ref="ANSI A92.22",
                                  **overrides) -> dict:
    payload = {
        "class_id": class_id,
        "serial_number": serial_number,
        "ansi_standard_ref": ansi_standard_ref,
    }
    payload.update(overrides)
    return payload


def create_rental_contract_payload(customer_id, jobsite_address="100 Main St",
                                   damage_waiver_elected=False,
                                   **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "jobsite_address": jobsite_address,
        "damage_waiver_elected": damage_waiver_elected,
    }
    payload.update(overrides)
    return payload


def create_rental_line_payload(contract_id, unit_id,
                               requested_start_date, requested_end_date,
                               required_working_height_ft,
                               expected_contract_version,
                               engineering_plan_ref=None,
                               **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "unit_id": unit_id,
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
        "required_working_height_ft": required_working_height_ft,
        "expected_contract_version": expected_contract_version,
    }
    if engineering_plan_ref is not None:
        payload["engineering_plan_ref"] = engineering_plan_ref
    payload.update(overrides)
    return payload


def create_delivery_trip_payload(contract_id, line_id, trip_type, driver_id,
                                 planned_start_utc, planned_end_utc,
                                 **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "line_id": line_id,
        "trip_type": trip_type,
        "driver_id": driver_id,
        "planned_start_utc": planned_start_utc,
        "planned_end_utc": planned_end_utc,
    }
    payload.update(overrides)
    return payload


def create_trip_completion_payload(standby_minutes=0, crew_labor_hours=0,
                                   **overrides) -> dict:
    payload = {
        "standby_minutes": standby_minutes,
        "crew_labor_hours": crew_labor_hours,
    }
    payload.update(overrides)
    return payload


def create_trip_failure_payload(failure_reason="jobsite gate locked",
                                **overrides) -> dict:
    payload = {"failure_reason": failure_reason}
    payload.update(overrides)
    return payload


def create_trip_reschedule_payload(planned_start_utc, planned_end_utc,
                                   **overrides) -> dict:
    payload = {
        "planned_start_utc": planned_start_utc,
        "planned_end_utc": planned_end_utc,
    }
    payload.update(overrides)
    return payload


def create_inspection_record_payload(unit_id, inspection_date,
                                     ansi_standard_ref="ANSI A92.22",
                                     result="PASS", **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "inspection_date": inspection_date,
        "ansi_standard_ref": ansi_standard_ref,
        "result": result,
    }
    payload.update(overrides)
    return payload


def create_training_record_payload(customer_id, class_id,
                                   trainee_name="Op One",
                                   trained_at="2026-08-01T10:00:00Z",
                                   **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "class_id": class_id,
        "trainee_name": trainee_name,
        "trained_at": trained_at,
    }
    payload.update(overrides)
    return payload


def create_damage_claim_payload(line_id, claim_type="DAMAGE",
                                description="jobsite damage", **overrides) -> dict:
    payload = {
        "line_id": line_id,
        "claim_type": claim_type,
        "description": description,
    }
    payload.update(overrides)
    return payload


def create_claim_assessment_payload(repair_estimate_cents=None,
                                    **overrides) -> dict:
    payload = {}
    if repair_estimate_cents is not None:
        payload["repair_estimate_cents"] = repair_estimate_cents
    payload.update(overrides)
    return payload


def create_claim_resolution_payload(decision="UPHOLD", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
