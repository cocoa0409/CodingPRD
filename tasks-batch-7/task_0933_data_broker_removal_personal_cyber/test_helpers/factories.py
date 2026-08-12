"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "OWNER_EMAIL": "owner@example.com",
    "OWNER_NAME": "Dana Owner",
    "PROFILE_NAME": "Dana Owner",
    "PROFILE_DOB": "1984-03-02",
    "PROFILE_ADDRESS": "12 Elm St, Springfield",
    "IDENTIFIER_EMAIL": "dana@example.com",
    "BROKER_NAME": "QuickLookup",
    "SOURCE_URL": "https://quicklookup.example/dana",
}


def create_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "FAMILY",
        "name": "Family Shield",
        "monthly_fee_cents": 2200,
        "max_members": 4,
        "profile_quota_per_cycle": 4,
        "scan_quota_per_cycle": 12,
        "removal_quota_per_cycle": 60,
        "per_member_removal_subcap": 25,
    }
    payload.update(overrides)
    return payload


def create_account_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "primary_member_email": DEFAULTS["OWNER_EMAIL"],
        "primary_member_full_name": DEFAULTS["OWNER_NAME"],
    }
    payload.update(overrides)
    return payload


def invite_member_payload(expected_account_version, **overrides) -> dict:
    payload = {
        "email": "kid@example.com",
        "full_name": "Robin Kid",
        "role_in_family": "MINOR",
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def create_monitored_profile_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "full_name": DEFAULTS["PROFILE_NAME"],
        "date_of_birth": DEFAULTS["PROFILE_DOB"],
        "primary_address": DEFAULTS["PROFILE_ADDRESS"],
    }
    payload.update(overrides)
    return payload


def add_identifier_payload(expected_profile_version, **overrides) -> dict:
    payload = {
        "identifier_type": "EMAIL",
        "identifier_value": DEFAULTS["IDENTIFIER_EMAIL"],
        "expected_profile_version": expected_profile_version,
    }
    payload.update(overrides)
    return payload


def create_broker_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["BROKER_NAME"],
        "opt_out_method": "WEB_FORM",
        "jurisdiction": "OTHER",
        "response_window_days": 30,
        "requires_identity_verification": False,
    }
    payload.update(overrides)
    return payload


def create_identity_document_payload(**overrides) -> dict:
    payload = {
        "document_type": "PASSPORT",
        "document_reference": "PASS-99812",
        "expires_at": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_scan_run_payload(profile_id, kind="INITIAL", **overrides) -> dict:
    payload = {"profile_id": profile_id, "kind": kind}
    payload.update(overrides)
    return payload


def record_finding_payload(broker_id, **overrides) -> dict:
    payload = {
        "broker_id": broker_id,
        "exposure_kind": "PEOPLE_SEARCH",
        "source_url": DEFAULTS["SOURCE_URL"],
    }
    payload.update(overrides)
    return payload


def create_breach_event_payload(**overrides) -> dict:
    payload = {
        "name": "MailVault 2026",
        "breach_date": "2026-04-01T00:00:00Z",
        "disclosed_at": "2026-04-15T00:00:00Z",
        "record_types": ["EMAIL_ADDRESS"],
        "base_severity_points": 10,
    }
    payload.update(overrides)
    return payload


def create_credential_finding_payload(profile_id, finding_type="BREACHED_PASSWORD",
                                      **overrides) -> dict:
    payload = {
        "profile_id": profile_id,
        "finding_type": finding_type,
        "detail": "mail vault",
    }
    payload.update(overrides)
    return payload


def create_addon_payload(**overrides) -> dict:
    payload = {
        "addon_type": "VPN",
        "seats_total": 2,
        "per_seat_fee_cents": 300,
    }
    payload.update(overrides)
    return payload


def create_device_seat_payload(addon_id, member_id, expected_addon_version,
                               **overrides) -> dict:
    payload = {
        "addon_id": addon_id,
        "member_id": member_id,
        "device_label": "Dana Laptop",
        "expected_addon_version": expected_addon_version,
    }
    payload.update(overrides)
    return payload


def plan_change_payload(new_plan_id, change_kind, expected_account_version,
                        **overrides) -> dict:
    payload = {
        "new_plan_id": new_plan_id,
        "change_kind": change_kind,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload
