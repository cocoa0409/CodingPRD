"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import DEFAULT_PLAN, GROSS_CHARGE_CENTS

_npi_counter = itertools.count(1000000001)
_member_counter = itertools.count(1)


def create_procedure_payload(**overrides) -> dict:
    defaults = {
        "code_system": "CPT",
        "code": "70450",
        "description": "CT Head w/o contrast",
        "setting": "OUTPATIENT",
        "gross_charge_cents": GROSS_CHARGE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_payer_contract_payload(**overrides) -> dict:
    defaults = {
        "payer_name": "Acme Health",
        "payer_type": "COMMERCIAL",
        "methodology": "FEE_SCHEDULE",
        "effective_date": "2026-01-01T00:00:00Z",
        "expiration_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_negotiated_rate_payload(contract_id, procedure_id, expected_contract_version,
                                   rate_type="FLAT", flat_amount_cents=200000,
                                   percent_of_charge=None, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "procedure_id": procedure_id,
        "rate_type": rate_type,
        "expected_contract_version": expected_contract_version,
    }
    if rate_type == "FLAT":
        payload["flat_amount_cents"] = flat_amount_cents
    else:
        payload["percent_of_charge"] = percent_of_charge
    payload.update(overrides)
    return payload


def create_benefit_plan_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_PLAN)
    defaults.update(overrides)
    return defaults


def create_patient_payload(benefit_plan_id, **overrides) -> dict:
    n = next(_member_counter)
    defaults = {
        "name": f"Pat {n}",
        "member_id": f"M-{n}",
        "benefit_plan_id": benefit_plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "name": "Dr Ray",
        "npi": str(next(_npi_counter)),
        "specialty": "Radiology",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": "CT-1",
        "room_type": "IMAGING",
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(patient_id, expected_patient_version,
                            estimate_type="GFE_INSURED", contract_id=None,
                            **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "estimate_type": estimate_type,
        "expected_patient_version": expected_patient_version,
    }
    if contract_id is not None:
        payload["contract_id"] = contract_id
    payload.update(overrides)
    return payload


def create_line_payload(procedure_id, **overrides) -> dict:
    payload = {"procedure_id": procedure_id}
    payload.update(overrides)
    return payload


def create_prior_authorization_payload(estimate_id, procedure_code="70450",
                                       requested_units=1, **overrides) -> dict:
    payload = {
        "estimate_id": estimate_id,
        "procedure_code": procedure_code,
        "requested_units": requested_units,
    }
    payload.update(overrides)
    return payload


def approve_prior_authorization_payload(auth_number="AUTH-1", approved_units=1,
                                        expiration_date="2026-12-31T00:00:00Z",
                                        **overrides) -> dict:
    payload = {
        "auth_number": auth_number,
        "approved_units": approved_units,
        "expiration_date": expiration_date,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(patient_id, estimate_id, provider_id, room_id,
                               scheduled_start, scheduled_end,
                               prior_auth_id=None, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "estimate_id": estimate_id,
        "provider_id": provider_id,
        "room_id": room_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    if prior_auth_id is not None:
        payload["prior_auth_id"] = prior_auth_id
    payload.update(overrides)
    return payload


def create_dispute_payload(estimate_id, reason="Estimate too high",
                           disputed_amount_cents=5000, **overrides) -> dict:
    payload = {
        "estimate_id": estimate_id,
        "reason": reason,
        "disputed_amount_cents": disputed_amount_cents,
    }
    payload.update(overrides)
    return payload
