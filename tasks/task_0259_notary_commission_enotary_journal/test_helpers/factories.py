"""Payload factories — one per entity, input fields only.

Each factory provides PRD-sensible defaults and accepts **overrides. Only
client-supplied (source: input) fields appear; system/computed fields are
never sent.
"""

DEFAULTS = {
    "STATE_CODE": "TX",
    "BOND_FACE_VALUE_CENTS": 1_000_000,
    "BOND_MINIMUM_CENTS": 500_000,
    "COMMISSION_TERM_MONTHS": 48,
    "RENEWAL_GRACE_DAYS": 30,
    "SESSION_ACT_FEE_CAP_CENTS": 1_200,
    "RON_SURCHARGE_CAP_CENTS": 2_500,
}


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "state_code": DEFAULTS["STATE_CODE"],
        "ron_allowed": True,
        "bond_minimum_cents": DEFAULTS["BOND_MINIMUM_CENTS"],
        "commission_term_months": DEFAULTS["COMMISSION_TERM_MONTHS"],
        "renewal_grace_days": DEFAULTS["RENEWAL_GRACE_DAYS"],
        "session_act_fee_cap_cents": DEFAULTS["SESSION_ACT_FEE_CAP_CENTS"],
        "ron_surcharge_cap_cents": DEFAULTS["RON_SURCHARGE_CAP_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_fee_schedule_payload(act_type: str, max_act_fee_cents: int, **overrides) -> dict:
    payload = {"act_type": act_type, "max_act_fee_cents": max_act_fee_cents}
    payload.update(overrides)
    return payload


def register_notary_payload(jurisdiction_id: str, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "full_name": "Test Notary",
        "email": "notary@example.com",
    }
    payload.update(overrides)
    return payload


def create_bond_payload(notary_id: str, jurisdiction_id: str, **overrides) -> dict:
    payload = {
        "notary_id": notary_id,
        "jurisdiction_id": jurisdiction_id,
        "face_value_cents": DEFAULTS["BOND_FACE_VALUE_CENTS"],
        "coverage_start_at": "2026-06-01T00:00:00Z",
        "coverage_end_at": "2030-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_renewal_payload(notary_id: str, expected_notary_version: int, new_bond_id: str, **overrides) -> dict:
    payload = {
        "notary_id": notary_id,
        "expected_notary_version": expected_notary_version,
        "new_bond_id": new_bond_id,
    }
    payload.update(overrides)
    return payload


def create_session_payload(notary_id: str, scheduled_start_at: str, scheduled_end_at: str, **overrides) -> dict:
    payload = {
        "notary_id": notary_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def create_signer_payload(full_name: str = "Test Signer", **overrides) -> dict:
    payload = {"full_name": full_name}
    payload.update(overrides)
    return payload


def create_document_payload(signer_id: str, act_type: str, requested_fee_cents: int, **overrides) -> dict:
    payload = {
        "signer_id": signer_id,
        "act_type": act_type,
        "requested_fee_cents": requested_fee_cents,
    }
    payload.update(overrides)
    return payload


def create_journal_entry_payload(notary_id: str, act_type: str, signer_name: str,
                                 id_method: str, fee_charged_cents: int, **overrides) -> dict:
    payload = {
        "notary_id": notary_id,
        "act_type": act_type,
        "signer_name": signer_name,
        "id_method": id_method,
        "fee_charged_cents": fee_charged_cents,
    }
    payload.update(overrides)
    return payload


def amend_journal_entry_payload(signer_name: str, fee_charged_cents: int, **overrides) -> dict:
    payload = {"signer_name": signer_name, "fee_charged_cents": fee_charged_cents}
    payload.update(overrides)
    return payload


def create_complaint_payload(notary_id: str, category: str, **overrides) -> dict:
    payload = {"notary_id": notary_id, "category": category}
    payload.update(overrides)
    return payload
