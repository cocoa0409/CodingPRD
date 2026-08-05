"""Payload factories — one per entity, input fields only."""


def create_practice_payload(**overrides) -> dict:
    payload = {
        "name": "Test Clinic",
        "npi": "1111111111",
        "tax_id": "22-3333333",
        "billing_fee_pct": 0.06,
    }
    payload.update(overrides)
    return payload


def create_payer_payload(**overrides) -> dict:
    payload = {
        "name": "BlueCo",
        "payer_type": "COMMERCIAL",
        "timely_filing_days": 90,
        "appeal_window_days": 60,
    }
    payload.update(overrides)
    return payload


def create_provider_payload(practice_id, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "npi": "2222222222",
        "first_name": "Ann",
        "last_name": "Lee",
        "specialty": "IM",
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(provider_id, payer_id, effective_date="2026-01-01T00:00:00Z",
                              **overrides) -> dict:
    payload = {
        "provider_id": provider_id,
        "payer_id": payer_id,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def create_fee_schedule_payload(practice_id, effective_date="2026-01-01T00:00:00Z",
                                **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def create_fee_schedule_line_payload(cpt_code="99213", allowed_amount_cents=10000,
                                     **overrides) -> dict:
    payload = {
        "cpt_code": cpt_code,
        "allowed_amount_cents": allowed_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(practice_id, provider_id, payer_id,
                         service_date="2026-05-15T00:00:00Z",
                         deductible_remaining_cents=0, coinsurance_pct=0.20,
                         copay_cents=0, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "provider_id": provider_id,
        "payer_id": payer_id,
        "service_date": service_date,
        "deductible_remaining_cents": deductible_remaining_cents,
        "coinsurance_pct": coinsurance_pct,
        "copay_cents": copay_cents,
    }
    payload.update(overrides)
    return payload


def create_claim_line_payload(cpt_code="99213", units=1, charge_amount_cents=15000,
                              **overrides) -> dict:
    payload = {
        "cpt_code": cpt_code,
        "units": units,
        "charge_amount_cents": charge_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_denial_payload(denial_code="CO-97", denied_amount_cents=5000,
                          denial_date="2026-05-20T00:00:00Z", **overrides) -> dict:
    payload = {
        "denial_code": denial_code,
        "denied_amount_cents": denied_amount_cents,
        "denial_date": denial_date,
    }
    payload.update(overrides)
    return payload


def create_appeal_payload(level=1, narrative="Records support medical necessity.",
                          **overrides) -> dict:
    payload = {
        "level": level,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def create_remittance_payload(payer_id, remittance_ref="RA-1", total_amount_cents=10000,
                              **overrides) -> dict:
    payload = {
        "payer_id": payer_id,
        "remittance_ref": remittance_ref,
        "total_amount_cents": total_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_posting_payload(claim_id, expected_claim_version, insurance_paid_cents=0,
                           patient_responsibility_cents=0, adjustment_cents=0,
                           **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "insurance_paid_cents": insurance_paid_cents,
        "patient_responsibility_cents": patient_responsibility_cents,
        "adjustment_cents": adjustment_cents,
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def create_statement_payload(claim_id, **overrides) -> dict:
    payload = {"claim_id": claim_id}
    payload.update(overrides)
    return payload
