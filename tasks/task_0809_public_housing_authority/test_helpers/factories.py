"""Payload factories — one per entity, input fields only."""
from .constants import FAR_FUTURE_EXPIRY, HIGH_INCOME_LIMIT_CENTS


def applicant_payload(household_name="Test Household", **overrides):
    payload = {"household_name": household_name}
    payload.update(overrides)
    return payload


def member_payload(full_name="Member One", relationship="HEAD", **overrides):
    payload = {"full_name": full_name, "relationship": relationship}
    payload.update(overrides)
    return payload


def preference_claim_payload(preference_type="VETERAN", **overrides):
    payload = {"preference_type": preference_type}
    payload.update(overrides)
    return payload


def waitlist_payload(site_name="Site A", bedroom_size=2, **overrides):
    payload = {"site_name": site_name, "bedroom_size": bedroom_size}
    payload.update(overrides)
    return payload


def unit_payload(address_label="Unit-1", bedroom_size=2,
                 income_limit_cents=HIGH_INCOME_LIMIT_CENTS, **overrides):
    payload = {
        "address_label": address_label,
        "bedroom_size": bedroom_size,
        "income_limit_cents": income_limit_cents,
    }
    payload.update(overrides)
    return payload


def offer_payload(waitlist_entry_id, unit_id, expires_at=FAR_FUTURE_EXPIRY, **overrides):
    payload = {
        "waitlist_entry_id": waitlist_entry_id,
        "unit_id": unit_id,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def certification_payload(cert_type, effective_date, expected_tenancy_version, **overrides):
    payload = {
        "cert_type": cert_type,
        "effective_date": effective_date,
        "expected_tenancy_version": expected_tenancy_version,
    }
    payload.update(overrides)
    return payload


def interim_change_payload(change_type, effective_date, **overrides):
    payload = {"change_type": change_type, "effective_date": effective_date}
    payload.update(overrides)
    return payload


def grievance_payload(grievance_type, reason="filed reason", **overrides):
    payload = {"grievance_type": grievance_type, "reason": reason}
    payload.update(overrides)
    return payload
