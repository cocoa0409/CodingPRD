"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_facility_payload(**overrides) -> dict:
    defaults = {"name": "Test Vault", "total_units": 10}
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": _uniq("U"),
        "unit_class": "STANDARD",
        "monthly_rate_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "email": _uniq("member") + "@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "make": "Ferrari",
        "model": "F8",
        "model_year": 2022,
        "vin": _uniq("VIN"),
        "fuel_type": "ICE",
        "declared_value_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_coi_payload(**overrides) -> dict:
    defaults = {
        "policy_number": _uniq("POL"),
        "carrier": "ACME Insurance",
        "coverage_amount_cents": 10_000_000,
        "effective_at": "2026-05-01T00:00:00Z",
        "expiry_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(member_id: str, vehicle_id: str, unit_id: str,
                             expected_unit_version: int, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "vehicle_id": vehicle_id,
        "unit_id": unit_id,
        "move_in_at": "2026-06-01T00:00:00Z",
        "planned_move_out_at": "2026-12-01T00:00:00Z",
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_payload(**overrides) -> dict:
    defaults = {"monitor_type": "BATTERY_TENDER", "monthly_fee_cents": 5000}
    defaults.update(overrides)
    return defaults


def create_service_order_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "service_type": "DETAIL",
        "estimated_labor_hours": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_transporter_payload(**overrides) -> dict:
    defaults = {"name": _uniq("Transporter")}
    defaults.update(overrides)
    return defaults


def create_delivery_job_payload(vehicle_id: str, transporter_id: str, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "transporter_id": transporter_id,
        "event_name": "Concours",
        "pickup_at": "2026-06-20T09:00:00Z",
        "dropoff_at": "2026-06-20T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_payload(member_id: str, facility_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "facility_id": facility_id,
        "desired_unit_class": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(vehicle_id: str, **overrides) -> dict:
    defaults = {"vehicle_id": vehicle_id, "inspection_type": "INTAKE"}
    defaults.update(overrides)
    return defaults


def generate_invoice_payload(member_id: str, agreement_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "agreement_id": agreement_id,
        "period_start_at": "2026-06-01T00:00:00Z",
        "period_end_at": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
