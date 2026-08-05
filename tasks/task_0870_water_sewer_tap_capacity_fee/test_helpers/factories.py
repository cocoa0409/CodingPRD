"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import FEE_SCHEDULE, METER_ONE


def create_meter_size_schedule_payload(**overrides) -> dict:
    defaults = dict(METER_ONE)
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "is_active": True,
        "water_capacity_fee_per_eru_cents": FEE_SCHEDULE["WATER_CAPACITY_FEE_PER_ERU_CENTS"],
        "sewer_capacity_fee_per_eru_cents": FEE_SCHEDULE["SEWER_CAPACITY_FEE_PER_ERU_CENTS"],
        "use_multipliers": {
            "RESIDENTIAL": FEE_SCHEDULE["USE_MULT_RESIDENTIAL"],
            "COMMERCIAL": FEE_SCHEDULE["USE_MULT_COMMERCIAL"],
            "IRRIGATION": FEE_SCHEDULE["USE_MULT_IRRIGATION"],
        },
        "admin_fee_pct": FEE_SCHEDULE["ADMIN_FEE_PCT"],
        "admin_fee_cap_cents": FEE_SCHEDULE["ADMIN_FEE_CAP_CENTS"],
        "volume_discount_threshold_cents": FEE_SCHEDULE["VOLUME_DISCOUNT_THRESHOLD_CENTS"],
        "volume_discount_pct": FEE_SCHEDULE["VOLUME_DISCOUNT_PCT"],
        "pavement_cut_surcharge_cents": FEE_SCHEDULE["PAVEMENT_CUT_SURCHARGE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {"name": "Test Inspector"}
    defaults.update(overrides)
    return defaults


def create_meter_crew_payload(**overrides) -> dict:
    defaults = {"name": "Test Crew"}
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "parcel_id": "APN-TEST",
        "service_type": "WATER",
        "meter_size": "ONE",
        "use_type": "RESIDENTIAL",
    }
    defaults.update(overrides)
    return defaults


def create_availability_payload(application_id: str, distance_to_main_ft: float, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "distance_to_main_ft": distance_to_main_ft,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(application_id: str, developer_user_id: str = "dev-1", **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "developer_user_id": developer_user_id,
        "length_ft": 400,
        "estimated_cost_cents": 4000000,
        "total_assessable_front_ft": 500,
        "total_assessable_area_sqft": 100000,
        "reimbursement_cap_cents": 6000000,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(main_extension_project_id: str, developer_user_id: str = "dev-1", **overrides) -> dict:
    defaults = {
        "main_extension_project_id": main_extension_project_id,
        "developer_user_id": developer_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_escrow_transaction_payload(txn_type: str, amount_cents: int,
                                      expected_developer_agreement_version: int, **overrides) -> dict:
    defaults = {
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "expected_developer_agreement_version": expected_developer_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(application_id: str, inspector_id: str, inspection_type: str,
                              scheduled_start: str, scheduled_end: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "inspector_id": inspector_id,
        "inspection_type": inspection_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_meter_set_payload(application_id: str, crew_id: str,
                             appointment_start: str, appointment_end: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "crew_id": crew_id,
        "appointment_start": appointment_start,
        "appointment_end": appointment_end,
    }
    defaults.update(overrides)
    return defaults


def create_latecomer_payload(main_extension_project_id: str, benefiting_application_id: str,
                             method: str, parcel_front_ft: float, parcel_area_sqft: float,
                             expected_main_extension_project_version: int, **overrides) -> dict:
    defaults = {
        "main_extension_project_id": main_extension_project_id,
        "benefiting_application_id": benefiting_application_id,
        "method": method,
        "parcel_front_ft": parcel_front_ft,
        "parcel_area_sqft": parcel_area_sqft,
        "expected_main_extension_project_version": expected_main_extension_project_version,
    }
    defaults.update(overrides)
    return defaults
