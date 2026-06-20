"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_npi_counter = itertools.count(1)


def _next_npi() -> str:
    """Generate a distinct 10-digit NPI per call (uniqueness is not asserted but avoids collisions)."""
    n = next(_npi_counter)
    return f"{2000000000 + n:010d}"


def create_agency_payload(**overrides) -> dict:
    """Agency: name, npi, state_code required; base_state_is_no_surprises / charity_fpl_threshold_pct optional."""
    defaults = {
        "name": "Test EMS",
        "npi": _next_npi(),
        "state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(agency_id: str, role: str, **overrides) -> dict:
    """AgencyStaff: agency_id, full_name, role required; pcs_signature_authority optional."""
    defaults = {
        "agency_id": agency_id,
        "full_name": "Test Staff",
        "role": role,
    }
    defaults.update(overrides)
    return defaults


def create_payer_plan_payload(payer_type: str, **overrides) -> dict:
    """PayerPlan: name, payer_type required; qpa_multiplier / allows_balance_billing optional."""
    defaults = {
        "name": f"Test {payer_type} Plan",
        "payer_type": payer_type,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    """Patient: full_name, date_of_birth required; household_size / income / coverages optional."""
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1960-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(agency_id: str, **overrides) -> dict:
    """Vehicle: agency_id, unit_call_sign required; turnaround_minutes optional."""
    defaults = {
        "agency_id": agency_id,
        "unit_call_sign": "Medic-1",
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(agency_id: str, certification: str = "PARAMEDIC", **overrides) -> dict:
    """CrewMember: agency_id, full_name, certification required."""
    defaults = {
        "agency_id": agency_id,
        "full_name": "Test Crew",
        "certification": certification,
    }
    defaults.update(overrides)
    return defaults


def create_unit_assignment_payload(transport_id: str, vehicle_id: str, crew_member_id: str,
                                   window_start_iso: str, window_end_iso: str, **overrides) -> dict:
    """UnitAssignment: transport_id, vehicle_id, crew_member_id, window_start_iso, window_end_iso required."""
    defaults = {
        "transport_id": transport_id,
        "vehicle_id": vehicle_id,
        "crew_member_id": crew_member_id,
        "window_start_iso": window_start_iso,
        "window_end_iso": window_end_iso,
    }
    defaults.update(overrides)
    return defaults


def create_transport_payload(agency_id: str, patient_id: str, run_number: str, **overrides) -> dict:
    """Transport import: agency_id, patient_id, run_number, dispatch_iso, origin_modifier,
    destination_modifier, loaded_miles required; is_rural_pickup / emergency_indicator optional."""
    defaults = {
        "agency_id": agency_id,
        "patient_id": patient_id,
        "run_number": run_number,
        "dispatch_iso": "2026-06-01T08:00:00.000Z",
        "origin_modifier": "S",
        "destination_modifier": "H",
        "loaded_miles": 12.0,
        "emergency_indicator": True,
    }
    defaults.update(overrides)
    return defaults


def code_transport_payload(level_of_service: str, **overrides) -> dict:
    """Coding payload: level_of_service required."""
    defaults = {"level_of_service": level_of_service}
    defaults.update(overrides)
    return defaults


def create_claim_payload(payer_plan_id: str, expected_transport_version: int, **overrides) -> dict:
    """Claim creation: payer_plan_id, expected_transport_version required; prior_claim_id optional."""
    defaults = {
        "payer_plan_id": payer_plan_id,
        "expected_transport_version": expected_transport_version,
    }
    defaults.update(overrides)
    return defaults


def create_remittance_payload(outcome: str, paid_cents: int, **overrides) -> dict:
    """RemittanceLine: outcome, paid_cents required; reported_allowed_cents / denial_reason optional."""
    defaults = {
        "outcome": outcome,
        "paid_cents": paid_cents,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(source: str, amount_cents: int, **overrides) -> dict:
    """Payment: source, amount_cents required; claim_id optional."""
    defaults = {
        "source": source,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(adjustment_type: str, **overrides) -> dict:
    """Adjustment: adjustment_type required; requested_amount_cents for discretionary types."""
    defaults = {"adjustment_type": adjustment_type}
    defaults.update(overrides)
    return defaults
