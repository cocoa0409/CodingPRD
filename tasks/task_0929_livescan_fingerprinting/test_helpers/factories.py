"""Payload factories — one per resource, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def next_seq() -> int:
    return next(_counter)


def unique_account_code() -> str:
    return f"ACC-{next_seq():05d}"


def unique_ori_code() -> str:
    """A nine-character ORI code, unique across the process."""
    return f"CA{next_seq():07d}"


def unique_serial_number() -> str:
    return f"DEV-{next_seq():05d}"


def create_agency_payload(**overrides) -> dict:
    payload = {
        "name": "Metro PD",
        "account_code": unique_account_code(),
        "payer_regime_default": "APPLICANT_PAID",
        "invoice_terms_days": 30,
    }
    payload.update(overrides)
    return payload


def create_ori_payload(agency_id: str, **overrides) -> dict:
    payload = {
        "agency_id": agency_id,
        "ori_code": unique_ori_code(),
        "statutory_authority": "CRIMINAL_JUSTICE",
        "fee_waiver_eligible": False,
    }
    payload.update(overrides)
    return payload


def create_service_type_payload(ori_id: str, **overrides) -> dict:
    payload = {
        "ori_id": ori_id,
        "code": f"SVC{next_seq():04d}",
        "applicant_type": "TEACHER",
        "slot_duration_minutes": TEST_DEFAULTS["SLOT_DURATION_MINUTES"],
        "required_document_codes": ["PHOTO_ID"],
        "accepted_id_document_types": ["DRIVER_LICENSE"],
        "state_fee_cents": TEST_DEFAULTS["STATE_FEE_CENTS"],
        "federal_fee_cents": TEST_DEFAULTS["FEDERAL_FEE_CENTS"],
        "retention_offered": True,
    }
    payload.update(overrides)
    return payload


def create_fixed_site_payload(**overrides) -> dict:
    payload = {
        "site_kind": "FIXED",
        "name": "Downtown",
        "concurrent_capacity": TEST_DEFAULTS["CONCURRENT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_mobile_event_payload(host_agency_id: str, **overrides) -> dict:
    payload = {
        "site_kind": "MOBILE_EVENT",
        "name": "Onsite Event Day",
        "concurrent_capacity": 4,
        "host_agency_id": host_agency_id,
        "event_window_start": "2026-06-02T09:00:00Z",
        "event_window_end": "2026-06-02T17:00:00Z",
        "min_billable_prints": 1,
    }
    payload.update(overrides)
    return payload


def create_device_payload(home_site_id: str, **overrides) -> dict:
    payload = {
        "serial_number": unique_serial_number(),
        "home_site_id": home_site_id,
        "calibrated_at": TEST_DEFAULTS["CALIBRATED_AT"],
    }
    payload.update(overrides)
    return payload


def create_device_assignment_payload(device_id: str, site_id: str, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "site_id": site_id,
        "window_start": "2026-06-02T09:00:00Z",
        "window_end": "2026-06-02T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ann Lee",
        "date_of_birth": "1990-04-02",
        "sex": "F",
        "place_of_birth": "CA",
        "id_document_type": "DRIVER_LICENSE",
        "id_document_expires_on": "2030-01-01",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(applicant_id, site_id, service_type_id, scheduled_start, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "site_id": site_id,
        "service_type_id": service_type_id,
        "scheduled_start": scheduled_start,
        "booking_channel": "BOOKED",
    }
    payload.update(overrides)
    return payload


def check_in_payload(**overrides) -> dict:
    payload = {
        "presented_document_type": "DRIVER_LICENSE",
        "presented_documents": ["PHOTO_ID"],
    }
    payload.update(overrides)
    return payload


def create_card_payload(appointment_id: str, device_id: str, **overrides) -> dict:
    payload = {"appointment_id": appointment_id, "device_id": device_id}
    payload.update(overrides)
    return payload


def create_submission_payload(card_id, expected_card_version, retention_requested=False, **overrides) -> dict:
    payload = {
        "card_id": card_id,
        "retention_requested": retention_requested,
        "expected_card_version": expected_card_version,
    }
    payload.update(overrides)
    return payload


def destination_result_payload(destination, result_code, **overrides) -> dict:
    payload = {"destination": destination, "result_code": result_code}
    payload.update(overrides)
    return payload


def create_determination_payload(submission_id, expected_submission_version, outcome="FIT", **overrides) -> dict:
    payload = {
        "submission_id": submission_id,
        "outcome": outcome,
        "expected_submission_version": expected_submission_version,
    }
    payload.update(overrides)
    return payload


def create_notification_payload(ori_code, subject_submission_tcn, **overrides) -> dict:
    payload = {
        "ori_code": ori_code,
        "subject_submission_tcn": subject_submission_tcn,
        "event_type": "ARREST",
        "event_date": "2026-06-05",
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(agency_id, expected_agency_version, period_key="2026-06", **overrides) -> dict:
    payload = {
        "agency_id": agency_id,
        "period_key": period_key,
        "expected_agency_version": expected_agency_version,
    }
    payload.update(overrides)
    return payload
