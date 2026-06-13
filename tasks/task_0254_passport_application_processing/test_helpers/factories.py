"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the input fields for a create/transition call and
accepts **overrides for the values individual tests need to control. Emails are
randomized by default because the applicant email is a unique handle and each
test runs against a fresh database, so a fixed email would only be safe within a
single test but a unique generator keeps fixtures composable.
"""
import uuid

# A square 600x600 photo with a 0.60 head fraction on a white background — a PASS.
PASS_PHOTO = {
    "width_px": 600,
    "height_px": 600,
    "head_height_fraction": 0.60,
    "background_is_white": True,
}


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_legal_name": "Test Applicant",
        "date_of_birth": "1990-01-01",
        "email": unique_email("applicant"),
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, application_type="NEW",
                               product_type="BOOK", **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "application_type": application_type,
        "product_type": product_type,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(doc_category="IDENTITY", doc_kind="DRIVERS_LICENSE",
                            **overrides) -> dict:
    defaults = {
        "doc_category": doc_category,
        "doc_kind": doc_kind,
    }
    defaults.update(overrides)
    return defaults


def create_photo_payload(**overrides) -> dict:
    defaults = dict(PASS_PHOTO)
    defaults.update(overrides)
    return defaults


def create_acceptance_facility_payload(**overrides) -> dict:
    defaults = {"name": "Downtown Facility", "state_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_urgent_travel_counter_payload(**overrides) -> dict:
    defaults = {"name": "Urgent Counter"}
    defaults.update(overrides)
    return defaults


def create_acceptance_agent_payload(facility_id, **overrides) -> dict:
    defaults = {
        "name": "Acceptance Agent",
        "badge_number": f"BADGE-{uuid.uuid4().hex[:8]}",
        "facility_id": facility_id,
    }
    defaults.update(overrides)
    return defaults


def create_adjudicator_payload(**overrides) -> dict:
    defaults = {
        "name": "Adjudicator Officer",
        "passport_office_code": f"OFF-{uuid.uuid4().hex[:8]}",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(application_id, resource_kind, expected_application_version,
                               start_utc, end_utc, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "resource_kind": resource_kind,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def submit_payload(expected_application_version) -> dict:
    return {"expected_application_version": expected_application_version}


def pay_payload(amount_tendered_cents) -> dict:
    return {"amount_tendered_cents": amount_tendered_cents}


def verify_payload(outcome) -> dict:
    return {"outcome": outcome}


def adjudicate_payload(decision, reason_code=None) -> dict:
    payload = {"decision": decision}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return payload


def name_change_decide_payload(decision) -> dict:
    return {"decision": decision}
