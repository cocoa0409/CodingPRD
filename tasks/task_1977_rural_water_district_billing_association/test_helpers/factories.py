"""Payload factories — one per entity, input fields only."""
from .constants import CYCLE_1, SCHEDULE_S1


def create_district_payload(**overrides) -> dict:
    defaults = {
        "district_name": "Test District",
        "usda_loan_principal_cents": 5_000_000,
        "annual_debt_service_cents": 120_000,
    }
    defaults.update(overrides)
    return defaults


def create_service_area_payload(**overrides) -> dict:
    defaults = {"area_name": "Area A", "boundary_acres": 640}
    defaults.update(overrides)
    return defaults


def create_member_payload(service_area_id, **overrides) -> dict:
    defaults = {"legal_name": "Test Member", "service_area_id": service_area_id}
    defaults.update(overrides)
    return defaults


def create_tap_payload(member_id, **overrides) -> dict:
    defaults = {"member_id": member_id, "meter_size": "FIVE_EIGHTS_INCH"}
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = dict(SCHEDULE_S1)
    defaults["tap_fee_schedule"] = dict(SCHEDULE_S1["tap_fee_schedule"])
    defaults.update(overrides)
    return defaults


def create_billing_cycle_payload(**overrides) -> dict:
    defaults = dict(CYCLE_1)
    defaults.update(overrides)
    return defaults


def create_meter_reading_payload(tap_id, cycle_id, reading_gallons, **overrides) -> dict:
    defaults = {
        "tap_id": tap_id,
        "cycle_id": cycle_id,
        "reading_gallons": reading_gallons,
        "reading_type": "ACTUAL",
    }
    defaults.update(overrides)
    return defaults


def create_master_meter_reading_payload(cycle_id, master_gallons, **overrides) -> dict:
    defaults = {"cycle_id": cycle_id, "master_gallons": master_gallons}
    defaults.update(overrides)
    return defaults


def create_payment_payload(member_id, invoice_id, amount_cents, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_board_resolution_payload(resolution_type, subject_id, **overrides) -> dict:
    defaults = {
        "resolution_type": resolution_type,
        "subject_id": subject_id,
        "payload": {},
    }
    defaults.update(overrides)
    return defaults


def create_annexation_petition_payload(parent_service_area_id, **overrides) -> dict:
    defaults = {
        "petitioner_name": "Test Petitioner",
        "parcel_acres": 40,
        "parent_service_area_id": parent_service_area_id,
        "deposit_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_boil_order_payload(**overrides) -> dict:
    defaults = {"reason": "Main break loss of pressure"}
    defaults.update(overrides)
    return defaults


def create_notification_payload(member_id, **overrides) -> dict:
    defaults = {"member_id": member_id, "channel": "DOOR_HANGER"}
    defaults.update(overrides)
    return defaults


def create_compliance_sample_payload(boil_order_id, collected_utc, **overrides) -> dict:
    defaults = {
        "boil_order_id": boil_order_id,
        "sample_point": "SP-1",
        "collected_utc": collected_utc,
    }
    defaults.update(overrides)
    return defaults
