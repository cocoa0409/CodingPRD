"""Payload factories — one per entity, PRD input fields only.

Required vs optional follows the PRD:
- Owner: full_name, email, birth_date required; is_veteran, disability_pct optional.
- TaxRoll: tax_year, mill_rate, growth_cap_pct required; prior_roll_id, senior_age_threshold optional.
- Parcel: owner_id, apn, situs_address required; is_primary_residence optional.
- Assessment: parcel_id, tax_roll_id, market_value required; reassessment_event optional.
- Exemption: assessment_id, exemption_type required.
- Appeal: assessment_id, filed_by_owner_id, requested_taxable_value, expected_assessment_version required.
- BoardPanel: name required; setup_buffer_minutes optional.
- Hearing: appeal_id, board_panel_id, hearing_officer_role_user_id, starts_at, ends_at required.
- DeferralAgreement: parcel_id, owner_id, annual_interest_rate required.
- DeferralPayment: amount_cents, expected_deferral_version required.
"""
import itertools

_email_counter = itertools.count(1)
_apn_counter = itertools.count(1)


def unique_email(prefix="owner"):
    return f"{prefix}-{next(_email_counter)}@example.com"


def unique_apn(prefix="APN"):
    return f"{prefix}-{next(_apn_counter)}"


def create_owner_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Owner",
        "email": unique_email(),
        "birth_date": "1980-01-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_tax_roll_payload(**overrides) -> dict:
    payload = {
        "tax_year": 2026,
        "mill_rate": 10.0,
        "growth_cap_pct": 0.02,
    }
    payload.update(overrides)
    return payload


def create_parcel_payload(owner_id, **overrides) -> dict:
    payload = {
        "owner_id": owner_id,
        "apn": unique_apn(),
        "situs_address": "1 Main St",
        "is_primary_residence": False,
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(parcel_id, tax_roll_id, market_value, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "tax_roll_id": tax_roll_id,
        "market_value": market_value,
        "reassessment_event": "NONE",
    }
    payload.update(overrides)
    return payload


def create_exemption_payload(assessment_id, exemption_type, **overrides) -> dict:
    payload = {
        "assessment_id": assessment_id,
        "exemption_type": exemption_type,
    }
    payload.update(overrides)
    return payload


def create_appeal_payload(assessment_id, filed_by_owner_id, requested_taxable_value,
                          expected_assessment_version, **overrides) -> dict:
    payload = {
        "assessment_id": assessment_id,
        "filed_by_owner_id": filed_by_owner_id,
        "requested_taxable_value": requested_taxable_value,
        "expected_assessment_version": expected_assessment_version,
    }
    payload.update(overrides)
    return payload


def create_board_panel_payload(**overrides) -> dict:
    payload = {"name": "Panel A", "setup_buffer_minutes": 15}
    payload.update(overrides)
    return payload


def create_hearing_payload(appeal_id, board_panel_id, hearing_officer_role_user_id,
                           starts_at, ends_at, **overrides) -> dict:
    payload = {
        "appeal_id": appeal_id,
        "board_panel_id": board_panel_id,
        "hearing_officer_role_user_id": hearing_officer_role_user_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def create_deferral_payload(parcel_id, owner_id, annual_interest_rate=0.05, **overrides) -> dict:
    payload = {
        "parcel_id": parcel_id,
        "owner_id": owner_id,
        "annual_interest_rate": annual_interest_rate,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents, expected_deferral_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_deferral_version": expected_deferral_version,
    }
    payload.update(overrides)
    return payload
