"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Aeris Holdings LLC",
        "contact_email": "owner@aeris.example",
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(owner_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "tail_number": "N100JX",
        "model": "G650",
        "home_base_icao": "KTEB",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(owner_id, aircraft_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "aircraft_id": aircraft_id,
        "monthly_management_fee_cents": 500000,
        "variable_fee_pct": 0.10,
        "charter_owner_share_pct": 0.85,
        "tax_allocation_method": "FLIGHT_HOURS",
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "fiscal_year": 2026,
        "fuel_cents": 1200000,
        "maintenance_cents": 960000,
        "crew_cents": 2400000,
        "hangar_cents": 600000,
        "insurance_cents": 480000,
        "other_cents": 240000,
    }
    defaults.update(overrides)
    return defaults


def create_expense_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "category": "FUEL",
        "amount_cents": 250000,
        "service_date": "2026-08-05",
        "vendor_name": "Meridian Fuel",
        "tax_use": "OWNER_USE",
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "full_name": "Pat Captain",
        "crew_role": "CAPTAIN",
        "hire_date": "2026-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "trip_use": "OWNER_USE",
        "depart_icao": "KTEB",
        "arrive_icao": "KPBI",
        "departure_at": "2026-08-06T08:00:00Z",
        "block_hours_est": 3.0,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(trip_id, crew_member_id, **overrides) -> dict:
    defaults = {
        "trip_id": trip_id,
        "crew_member_id": crew_member_id,
        "duty_role": "PIC",
        "duty_start_at": "2026-08-06T06:00:00Z",
        "duty_end_at": "2026-08-06T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "program_name": "JetCare hourly",
        "rate_per_hour_cents": 15000,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "event_code": "INSPECTION_100H",
        "interval_hours": 100.0,
        "due_at_aircraft_hours": 350.0,
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "filing_kind": "INSURANCE_COI",
        "authority": "Avemco",
        "reference_no": "COI-1001",
        "valid_until": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "vendor_kind": "HANGAR",
        "vendor_name": "Teterboro Hangars",
        "unit": "MONTH",
        "rate_cents_per_unit": 4500000,
        "term_start": "2026-09-01",
        "term_end": "2027-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(aircraft_id, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "period": "2026-08",
    }
    defaults.update(overrides)
    return defaults
