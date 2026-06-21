"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ORG_NAME": "CVO",
    "PROVIDER_NPI": "1234567890",
    "PROVIDER_NAME": "Dr A",
    "PROVIDER_SPECIALTY": "IM",
    "PROVIDER_CAQH": "CAQH-A",
    "LICENSE_ISSUED": "2025-01-01T00:00:00.000Z",
    "LICENSE_EXPIRATION": "2030-01-01T00:00:00.000Z",
    "SOURCE_REFERENCE": "https://lic.example/LIC-1",
    "PAYER_NAME": "Plan X",
    "PANEL_CAPACITY": 5,
}


def create_org_payload(**overrides) -> dict:
    """CredentialingOrg input fields. recred_cycle_days and
    expiring_soon_window_days are optional (server defaults 1095 / 90)."""
    payload = {"name": DEFAULTS["ORG_NAME"]}
    payload.update(overrides)
    return payload


def create_payer_payload(org_id, **overrides) -> dict:
    payload = {
        "org_id": org_id,
        "name": DEFAULTS["PAYER_NAME"],
        "payer_type": "COMMERCIAL",
        "retroactive_allowed": False,
        "panel_capacity": DEFAULTS["PANEL_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_sanctions_source_payload(org_id, **overrides) -> dict:
    payload = {
        "org_id": org_id,
        "source_code": "OIG_LEIE",
        "severity_weight": 3,
    }
    payload.update(overrides)
    return payload


def create_provider_payload(org_id, **overrides) -> dict:
    payload = {
        "org_id": org_id,
        "npi": DEFAULTS["PROVIDER_NPI"],
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "specialty": DEFAULTS["PROVIDER_SPECIALTY"],
        "caqh_id": DEFAULTS["PROVIDER_CAQH"],
    }
    payload.update(overrides)
    return payload


def create_credential_item_payload(**overrides) -> dict:
    payload = {
        "item_type": "STATE_LICENSE",
        "identifier": "LIC-1",
        "issued_date": DEFAULTS["LICENSE_ISSUED"],
        "expiration_date": DEFAULTS["LICENSE_EXPIRATION"],
    }
    payload.update(overrides)
    return payload


def create_verification_request_payload(**overrides) -> dict:
    payload = {
        "method": "PRIMARY_SOURCE",
        "source_reference": DEFAULTS["SOURCE_REFERENCE"],
    }
    payload.update(overrides)
    return payload


def complete_verification_payload(outcome="PASS", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_sanctions_screening_payload(sanctions_source_id, result="HIT", **overrides) -> dict:
    payload = {"sanctions_source_id": sanctions_source_id, "result": result}
    payload.update(overrides)
    return payload


def resolve_screening_payload(resolution_note="cleared", **overrides) -> dict:
    payload = {"resolution_note": resolution_note}
    payload.update(overrides)
    return payload


def create_peer_reviewer_payload(org_id, user_id, **overrides) -> dict:
    payload = {
        "org_id": org_id,
        "user_id": user_id,
        "full_name": f"Reviewer {user_id}",
    }
    payload.update(overrides)
    return payload


def cast_vote_payload(reviewer_id, ballot="YES", **overrides) -> dict:
    payload = {"reviewer_id": reviewer_id, "ballot": ballot}
    payload.update(overrides)
    return payload


def finalize_payload(decision, expected_credentialing_file_version, **overrides) -> dict:
    payload = {
        "decision": decision,
        "expected_credentialing_file_version": expected_credentialing_file_version,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(payer_id, **overrides) -> dict:
    payload = {"payer_id": payer_id}
    payload.update(overrides)
    return payload


def terminate_enrollment_payload(termination_reason="provider left network", **overrides) -> dict:
    payload = {"termination_reason": termination_reason}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
