"""Payload factories — one per resource, carrying only client-supplied fields."""

import itertools

_SEQ = itertools.count(1)


def _next() -> int:
    return next(_SEQ)


# --------------------------------------------------------------------------
# Network and fleet program
# --------------------------------------------------------------------------

def service_location_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "name": f"Commercial Tire Center {n}",
        "location_code": f"LOC{n:04d}",
        "state_code": "OH",
        "road_service_response_minutes_committed": 120,
        "scrap_permit_number": f"OH-SCRAP-{n:04d}",
        "scrap_permit_expires_on": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def fleet_account_payload(home_location_id: str, **overrides) -> dict:
    n = _next()
    payload = {
        "name": f"Freight Lines {n}",
        "account_type": "SINGLE_LOCATION",
        "home_location_id": home_location_id,
        "billing_mode": "DIRECT",
    }
    payload.update(overrides)
    return payload


def fleet_status_payload(status: str, status_reason: str = "Administrative action") -> dict:
    return {"status": status, "status_reason": status_reason}


def national_agreement_payload(fleet_account_id: str, **overrides) -> dict:
    n = _next()
    payload = {
        "fleet_account_id": fleet_account_id,
        "agreement_code": f"AGR-{n:04d}",
        "effective_from": "2026-07-01",
        "effective_to": "2026-12-31",
        "tier_discount_pct": 0.125,
        "casing_credit_rate_cents": 15000,
        "emergency_response_minutes": 90,
        "emergency_labor_rate_cents_per_hour": 13000,
    }
    payload.update(overrides)
    return payload


def tire_policy_payload(**overrides) -> dict:
    payload = {
        "position": "DRIVE",
        "target_pressure_psi": 100,
        "pressure_tolerance_pct": 0.10,
        "min_tread_depth_32nds": 4,
        "pull_point_32nds": 6,
        "max_retread_count": 3,
        "approved_brands": ["Bridgestone"],
        "new_tire_tread_depth_32nds": 24,
        "casing_spec_code": "ANY",
    }
    payload.update(overrides)
    return payload


def vehicle_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "unit_number": f"T-{n:04d}",
        "vehicle_type": "TRACTOR",
        "current_odometer_miles": 100000,
    }
    payload.update(overrides)
    return payload


def odometer_payload(odometer_miles: int, reading_at: str, **overrides) -> dict:
    payload = {"odometer_miles": odometer_miles, "reading_at": reading_at}
    payload.update(overrides)
    return payload


def technician_payload(**overrides) -> dict:
    n = _next()
    payload = {"name": f"Technician {n}", "certification_level": "LEVEL_2"}
    payload.update(overrides)
    return payload


def technician_status_payload(status: str) -> dict:
    return {"status": status}


def retread_line_payload(**overrides) -> dict:
    n = _next()
    payload = {"line_code": f"LN-{n:04d}"}
    payload.update(overrides)
    return payload


def retread_line_status_payload(status: str) -> dict:
    return {"status": status}


# --------------------------------------------------------------------------
# Casings, assets and surveys
# --------------------------------------------------------------------------

def casing_payload(fleet_account_id: str, **overrides) -> dict:
    n = _next()
    payload = {
        "fleet_account_id": fleet_account_id,
        "casing_serial": f"CS-{n:05d}",
        "brand": "Bridgestone",
        "casing_spec_code": "ANY",
        "intended_position": "DRIVE",
        "scrap_weight_lbs": 125,
    }
    payload.update(overrides)
    return payload


def collect_casing_payload(collected_at_location_id: str, **overrides) -> dict:
    payload = {"collected_at_location_id": collected_at_location_id}
    payload.update(overrides)
    return payload


def inspect_casing_payload(grade: str, expected_casing_version: int, **overrides) -> dict:
    payload = {"grade": grade, "expected_casing_version": expected_casing_version}
    payload.update(overrides)
    return payload


def reject_casing_payload(rejection_reason: str = "Sidewall separation") -> dict:
    return {"rejection_reason": rejection_reason}


def tire_asset_payload(fleet_account_id: str, casing_id: str, **overrides) -> dict:
    payload = {
        "fleet_account_id": fleet_account_id,
        "casing_id": casing_id,
        "brand": "Bridgestone",
        "cost_basis_cents": 50000,
    }
    payload.update(overrides)
    return payload


def mount_payload(
    vehicle_id: str,
    mounted_at: str,
    odometer_at_mount: int,
    tread_depth_at_mount_32nds: int,
    position: str = "DRIVE",
    **overrides,
) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "position": position,
        "mounted_at": mounted_at,
        "odometer_at_mount": odometer_at_mount,
        "tread_depth_at_mount_32nds": tread_depth_at_mount_32nds,
    }
    payload.update(overrides)
    return payload


def pull_payload(pull_reason: str = "Worn out") -> dict:
    return {"pull_reason": pull_reason}


def survey_payload(
    surveyed_at: str,
    pressure_psi: float,
    tread_depth_32nds: int,
    odometer_miles: int,
    **overrides,
) -> dict:
    payload = {
        "surveyed_at": surveyed_at,
        "pressure_psi": pressure_psi,
        "tread_depth_32nds": tread_depth_32nds,
        "odometer_miles": odometer_miles,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Retread jobs
# --------------------------------------------------------------------------

def retread_job_payload(
    casing_id: str,
    retread_line_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    **overrides,
) -> dict:
    payload = {
        "casing_id": casing_id,
        "retread_line_id": retread_line_id,
        "tread_design_code": "TD-HWY-1",
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def start_job_payload(started_at: str) -> dict:
    return {"started_at": started_at}


def complete_job_payload(completed_at: str, cost_basis_cents: int) -> dict:
    return {"completed_at": completed_at, "cost_basis_cents": cost_basis_cents}


def fail_cure_payload(failure_reason: str, **overrides) -> dict:
    payload = {"failure_reason": failure_reason}
    payload.update(overrides)
    return payload


def reschedule_job_payload(
    scheduled_start_at: str, scheduled_end_at: str, **overrides
) -> dict:
    payload = {
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def cancel_job_payload(reason: str = "Customer withdrew the carcass") -> dict:
    return {"reason": reason}


# --------------------------------------------------------------------------
# Road service
# --------------------------------------------------------------------------

def road_service_call_payload(
    fleet_account_id: str,
    vehicle_id: str,
    service_location_id: str,
    reported_at: str,
    priority: str = "NORMAL",
    **overrides,
) -> dict:
    payload = {
        "fleet_account_id": fleet_account_id,
        "vehicle_id": vehicle_id,
        "service_location_id": service_location_id,
        "priority": priority,
        "complaint": "Slow leak on the drive axle",
        "reported_at": reported_at,
    }
    payload.update(overrides)
    return payload


def dispatch_payload(dispatched_at: str, dispatch_miles: int, **overrides) -> dict:
    payload = {"dispatched_at": dispatched_at, "dispatch_miles": dispatch_miles}
    payload.update(overrides)
    return payload


def arrive_payload(arrived_at: str) -> dict:
    return {"arrived_at": arrived_at}


def complete_call_payload(closed_at: str, labor_hours: float, **overrides) -> dict:
    payload = {"closed_at": closed_at, "labor_hours": labor_hours}
    payload.update(overrides)
    return payload


def cancel_call_payload(cancel_reason: str = "Fleet resolved it in house") -> dict:
    return {"cancel_reason": cancel_reason}


# --------------------------------------------------------------------------
# Scrap compliance
# --------------------------------------------------------------------------

def scrap_manifest_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "hauler_permit_number": f"HAUL-{n:04d}",
        "hauler_capacity_lbs": 500,
    }
    payload.update(overrides)
    return payload


def manifest_line_payload(casing_id: str) -> dict:
    return {"casing_id": casing_id}


def sign_manifest_payload(signed_at: str) -> dict:
    return {"signed_at": signed_at}


def transport_manifest_payload(transported_at: str, **overrides) -> dict:
    payload = {"transported_at": transported_at, "hauler_vehicle_id": "HAULER-TRUCK-1"}
    payload.update(overrides)
    return payload


def certify_destruction_payload(certified_at: str, **overrides) -> dict:
    payload = {"certified_at": certified_at, "destruction_facility_code": "PROC-9"}
    payload.update(overrides)
    return payload


def void_manifest_payload(void_reason: str = "Load rebuilt") -> dict:
    return {"void_reason": void_reason}


# --------------------------------------------------------------------------
# Billing
# --------------------------------------------------------------------------

def invoice_payload(
    fleet_account_id: str,
    billing_period_start: str,
    billing_period_end: str,
    expected_fleet_account_version: int,
    **overrides,
) -> dict:
    payload = {
        "fleet_account_id": fleet_account_id,
        "billing_period_start": billing_period_start,
        "billing_period_end": billing_period_end,
        "expected_fleet_account_version": expected_fleet_account_version,
    }
    payload.update(overrides)
    return payload


def settle_invoice_payload(paid_amount_cents: int) -> dict:
    return {"paid_amount_cents": paid_amount_cents}


def dispute_invoice_payload(dispute_reason: str = "Line items contested") -> dict:
    return {"dispute_reason": dispute_reason}


def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
