"""Payload factories — one per entity, input fields only."""
import itertools

# Monotonic counters so factory-built unique fields (email, vin, oem) don't
# collide within a single test. The DB is reset per test, but a single test may
# build several customers/vehicles/parts.
_email_counter = itertools.count(1)
_vin_counter = itertools.count(1)
_oem_counter = itertools.count(1)


def unique_email() -> str:
    return f"cust{next(_email_counter)}@example.com"


def unique_vin() -> str:
    # VIN must be exactly 17 chars. Build a 17-char deterministic VIN.
    n = next(_vin_counter)
    return f"1HGCM82633A{n:06d}"


def unique_oem() -> str:
    return f"FW{next(_oem_counter):06d}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": unique_email(),
        "phone": "555-0100",
        "service_address_state": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "vin": unique_vin(),
        "make": "Honda",
        "model": "Accord",
        "model_year": 2021,
        "adas_equipped": False,
        "glass_part_number": unique_oem(),
    }
    defaults.update(overrides)
    return defaults


def create_glass_part_payload(**overrides) -> dict:
    defaults = {
        "oem_part_number": unique_oem(),
        "description": "Test windshield",
        "adas_compatible": False,
        "unit_price_cents": 30000,
        "on_hand_qty": 5,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Technician",
        "can_mobile": True,
        "adas_certified": False,
        "home_state": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_service_bay_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Bay",
        "bay_type": "INSTALL",
        "cleanroom": False,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
    }
    defaults.update(overrides)
    return defaults


def create_damage_assessment_payload(**overrides) -> dict:
    # Defaults render a clearly-repairable reading (REPAIR recommendation).
    defaults = {
        "chip_count": 1,
        "longest_crack_mm": 20,
        "in_driver_primary_view": False,
        "edge_distance_mm": 80,
    }
    defaults.update(overrides)
    return defaults


def replace_assessment_payload(**overrides) -> dict:
    # A clearly REPLACE reading (driver primary view forces REPLACE).
    defaults = {
        "chip_count": 0,
        "longest_crack_mm": 300,
        "in_driver_primary_view": True,
        "edge_distance_mm": 5,
    }
    defaults.update(overrides)
    return defaults


def create_part_order_payload(work_order_id, glass_part_id, expected_work_order_version, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "glass_part_id": glass_part_id,
        "quantity": 1,
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_service_appointment_payload(work_order_id, technician_id, service_location, start_at, end_at, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "technician_id": technician_id,
        "service_location": service_location,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_recalibration_job_payload(work_order_id, technician_id, calibration_type, start_at, end_at, expected_work_order_version, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "technician_id": technician_id,
        "calibration_type": calibration_type,
        "start_at": start_at,
        "end_at": end_at,
        "expected_work_order_version": expected_work_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(work_order_id, amount_cents, method="CARD", **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults
