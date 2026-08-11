"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import MODEL_STRAIGHT, MEASURE_STRAIGHT

_serial_counter = itertools.count(1)


def next_serial(prefix="SN"):
    return f"{prefix}-{next(_serial_counter):06d}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "date_of_birth": "1950-01-01",
        "home_region_code": "NORTH",
    }
    defaults.update(overrides)
    return defaults


def create_product_model_payload(**overrides) -> dict:
    defaults = dict(MODEL_STRAIGHT)
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(model_code=MODEL_STRAIGHT["model_code"], **overrides) -> dict:
    defaults = {
        "model_code": model_code,
        "serial_number": next_serial(),
    }
    defaults.update(overrides)
    return defaults


def create_home_assessment_payload(**overrides) -> dict:
    defaults = {"scheduled_date": "2026-06-02"}
    defaults.update(overrides)
    return defaults


def create_measure_payload(**overrides) -> dict:
    defaults = dict(MEASURE_STRAIGHT)
    defaults.update(overrides)
    return defaults


def create_approve_payload(model_code=MODEL_STRAIGHT["model_code"], **overrides) -> dict:
    defaults = {"model_code": model_code}
    defaults.update(overrides)
    return defaults


def create_quote_payload(home_assessment_id, model_code=MODEL_STRAIGHT["model_code"],
                         acquisition_mode="PURCHASE", **overrides) -> dict:
    defaults = {
        "home_assessment_id": home_assessment_id,
        "model_code": model_code,
        "acquisition_mode": acquisition_mode,
    }
    defaults.update(overrides)
    return defaults


def create_accept_payload(equipment_unit_id, expected_customer_version, **overrides) -> dict:
    defaults = {
        "equipment_unit_id": equipment_unit_id,
        "expected_customer_version": expected_customer_version,
    }
    defaults.update(overrides)
    return defaults


def create_funding_application_payload(**overrides) -> dict:
    defaults = {
        "source_kind": "STATE_GRANT",
        "requested_cents": 100000,
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(decision="APPROVED", **overrides) -> dict:
    defaults = {
        "decision": decision,
        "decision_reason": "funding decision recorded",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, expected_agreement_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(technician_crew_id="CREW-1", **overrides) -> dict:
    defaults = {
        "technician_crew_id": technician_crew_id,
        "scheduled_start_utc": "2026-06-10T09:00:00Z",
        "scheduled_end_utc": "2026-06-10T13:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_complete_install_payload(measured_labor_hours=4, installed_rail_length_m=4.00,
                                    **overrides) -> dict:
    defaults = {
        "measured_labor_hours": measured_labor_hours,
        "installed_rail_length_m": installed_rail_length_m,
    }
    defaults.update(overrides)
    return defaults


def create_service_plan_payload(tier="BASIC", **overrides) -> dict:
    defaults = {"tier": tier}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(service_plan_id, claim_kind="MECHANICAL",
                                  claimed_cents=5000, **overrides) -> dict:
    defaults = {
        "service_plan_id": service_plan_id,
        "claim_kind": claim_kind,
        "claimed_cents": claimed_cents,
    }
    defaults.update(overrides)
    return defaults


def create_adjudication_payload(decision="APPROVED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_removal_job_payload(technician_crew_id="CREW-R1", **overrides) -> dict:
    defaults = {
        "technician_crew_id": technician_crew_id,
        "scheduled_start_utc": "2026-08-01T09:00:00Z",
        "scheduled_end_utc": "2026-08-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults
