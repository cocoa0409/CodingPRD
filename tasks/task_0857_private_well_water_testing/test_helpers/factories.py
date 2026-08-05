"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the source=input fields the corresponding POST
endpoint consumes. Callers override any field via keyword arguments.
"""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def aquifer_payload(**overrides) -> dict:
    d = {
        "name": _uniq("Basin"),
        "sensitivity": "HIGH",
        "min_setback_septic_ft": 50,
        "min_setback_property_line_ft": 10,
        "min_well_depth_ft": 20,
    }
    d.update(overrides)
    return d


def applicant_payload(**overrides) -> dict:
    d = {
        "full_name": "Test Owner",
        "email": f"{_uniq('owner')}@example.com",
        "mailing_state": "CA",
    }
    d.update(overrides)
    return d


def driller_payload(**overrides) -> dict:
    d = {
        "license_number": _uniq("DRL"),
        "license_state": "CA",
        "license_expires_on": "2030-01-01T00:00:00Z",
    }
    d.update(overrides)
    return d


def well_payload(applicant_id, aquifer_id, **overrides) -> dict:
    d = {
        "applicant_id": applicant_id,
        "aquifer_id": aquifer_id,
        "latitude": 34.0,
        "longitude": -118.2,
        "parcel_apn": _uniq("APN"),
        "intended_use": "DOMESTIC",
    }
    d.update(overrides)
    return d


def construction_permit_payload(well_id, applicant_id, driller_id, **overrides) -> dict:
    d = {
        "well_id": well_id,
        "applicant_id": applicant_id,
        "driller_id": driller_id,
        "proposed_depth_ft": 250,
        "setback_septic_ft": 60,
        "setback_property_line_ft": 15,
        "scheduled_start": "2026-05-10T08:00:00Z",
        "scheduled_end": "2026-05-11T17:00:00Z",
    }
    d.update(overrides)
    return d


def driller_log_payload(construction_permit_id, driller_id, **overrides) -> dict:
    d = {
        "construction_permit_id": construction_permit_id,
        "driller_id": driller_id,
        "total_depth_ft": 320,
        "static_water_level_ft": 40,
        "casing_depth_ft": 20,
        "grout_type": "BENTONITE",
        "completed_on": "2026-05-11T18:00:00Z",
    }
    d.update(overrides)
    return d


def water_sample_payload(well_id, submitted_by_applicant_id, **overrides) -> dict:
    d = {
        "well_id": well_id,
        "submitted_by_applicant_id": submitted_by_applicant_id,
        "sample_type": "ROUTINE",
        "requested_analytes": ["NITRATE"],
        "collected_on": "2026-05-12T00:00:00Z",
        "chain_of_custody_id": _uniq("COC"),
    }
    d.update(overrides)
    return d


def sample_result_payload(water_sample_id, **overrides) -> dict:
    d = {
        "water_sample_id": water_sample_id,
        "bacteria_coliform": "ABSENT",
        "ecoli": "ABSENT",
        "nitrate_mg_l": 2.0,
        "lead_ppb": 2.0,
        "analyzed_on": "2026-05-13T00:00:00Z",
    }
    d.update(overrides)
    return d


def advisory_payload(well_id, **overrides) -> dict:
    d = {
        "well_id": well_id,
        "advisory_type": "NITRATE",
        "effective_from": "2026-06-01T00:00:00Z",
        "effective_to": "2026-06-30T00:00:00Z",
        "reason": "elevated reading",
    }
    d.update(overrides)
    return d


def contamination_case_payload(well_id, **overrides) -> dict:
    d = {
        "well_id": well_id,
        "severity": "HIGH",
    }
    d.update(overrides)
    return d


def abandonment_permit_payload(well_id, applicant_id, driller_id, **overrides) -> dict:
    d = {
        "well_id": well_id,
        "applicant_id": applicant_id,
        "driller_id": driller_id,
        "reason": "DRY",
        "method": "PERFORATE_FILL",
    }
    d.update(overrides)
    return d


def real_estate_requirement_payload(well_id, applicant_id, **overrides) -> dict:
    d = {
        "well_id": well_id,
        "applicant_id": applicant_id,
        "transaction_type": "SALE",
        "closing_date": "2026-07-30T00:00:00Z",
    }
    d.update(overrides)
    return d
