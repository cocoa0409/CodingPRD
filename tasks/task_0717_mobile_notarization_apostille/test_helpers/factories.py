"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying sensible defaults for every required input
field, overridable via keyword arguments.
"""

DEFAULTS = {
    "ORG_NAME": "Acme Notary",
    "STATE_CODE": "CA",
    "NOTARY_NAME": "Nora Public",
    "SIGNER_NAME": "Sam Signer",
    "SIGNER_EMAIL": "sam@x.com",
    "COMMISSION_EXPIRES_AT": "2027-01-01T00:00:00Z",
}


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE_CODE"],
        "per_stamp_cents": 1500,
        "travel_base_cents": 4000,
        "travel_per_mile_cents": 100,
        "ron_surcharge_cents": 2500,
        "state_cap_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "org_name": DEFAULTS["ORG_NAME"],
        "default_state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_notary_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "full_name": DEFAULTS["NOTARY_NAME"],
        "commission_state": DEFAULTS["STATE_CODE"],
        "commission_expires_at": DEFAULTS["COMMISSION_EXPIRES_AT"],
        "ron_authorized": True,
        "nsa_certified": True,
    }
    defaults.update(overrides)
    return defaults


def create_signer_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "full_name": DEFAULTS["SIGNER_NAME"],
        "email": DEFAULTS["SIGNER_EMAIL"],
        "id_doc_type": "DRIVERS_LICENSE",
    }
    defaults.update(overrides)
    return defaults


def create_request_payload(account_id, signer_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "signer_id": signer_id,
        "state_code": DEFAULTS["STATE_CODE"],
        "doc_category": "GENERAL",
        "delivery_mode": "MOBILE",
        "expected_stamp_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(request_id, **overrides) -> dict:
    defaults = {
        "request_id": request_id,
        "title": "Document A",
        "doc_type": "AFFIDAVIT",
        "signing_fee_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_ron_session_payload(request_id, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "request_id": request_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_id_verification_payload(request_id, signer_id,
                                   kba_score=80, credential_score=90,
                                   biometric_score=80, **overrides) -> dict:
    defaults = {
        "request_id": request_id,
        "signer_id": signer_id,
        "kba_score": kba_score,
        "credential_score": credential_score,
        "biometric_score": biometric_score,
    }
    defaults.update(overrides)
    return defaults


def create_journal_entry_payload(request_id, document_id, act_type="ACKNOWLEDGMENT", **overrides) -> dict:
    defaults = {
        "request_id": request_id,
        "document_id": document_id,
        "act_type": act_type,
    }
    defaults.update(overrides)
    return defaults


def create_apostille_order_payload(document_id, destination_country="FR",
                                   sos_office_state="CA", **overrides) -> dict:
    defaults = {
        "document_id": document_id,
        "destination_country": destination_country,
        "sos_office_state": sos_office_state,
    }
    defaults.update(overrides)
    return defaults


def create_loan_package_payload(request_id, lender_ref="LN-1", **overrides) -> dict:
    defaults = {
        "request_id": request_id,
        "lender_ref": lender_ref,
    }
    defaults.update(overrides)
    return defaults
