"""Payload factories — one per create/transition endpoint, input fields only.

Field names match PRD exactly (PRD §3 + §4). Optional fields are omitted from
the default payload so the server's documented defaults apply.
"""
from typing import Optional


# ─── Jurisdiction (PRD §3.1) ──────────────────────────────────────────

def create_jurisdiction_payload(
    state_code: str,
    ban_the_box_enabled: Optional[bool] = None,
    salary_history_ban_enabled: Optional[bool] = None,
    pre_adverse_waiting_days: Optional[int] = None,
):
    payload = {"state_code": state_code}
    if ban_the_box_enabled is not None:
        payload["ban_the_box_enabled"] = ban_the_box_enabled
    if salary_history_ban_enabled is not None:
        payload["salary_history_ban_enabled"] = salary_history_ban_enabled
    if pre_adverse_waiting_days is not None:
        payload["pre_adverse_waiting_days"] = pre_adverse_waiting_days
    return payload


# ─── Applicant (PRD §3.1) ─────────────────────────────────────────────

def create_applicant_payload(
    full_name: str = "Test Applicant",
    email: str = "test@example.com",
    date_of_birth: str = "1990-01-01T00:00:00.000Z",
):
    return {
        "full_name": full_name,
        "email": email,
        "date_of_birth": date_of_birth,
    }


# ─── Application (PRD §3.1) ───────────────────────────────────────────

def create_application_payload(
    applicant_id: str,
    jurisdiction_id: str,
    position_title: str = "Engineer",
    salary_history_disclosed=None,  # optional; default null per PRD §3.1
):
    payload = {
        "applicant_id": applicant_id,
        "jurisdiction_id": jurisdiction_id,
        "position_title": position_title,
    }
    if salary_history_disclosed is not None:
        payload["salary_history_disclosed"] = salary_history_disclosed
    return payload


# ─── ConsentDisclosure (PRD §3.2) ─────────────────────────────────────

def create_consent_payload(
    application_id: str,
    disclosure_text_version: str = "v2024-01",
    signed_at: str = "2026-06-01T10:00:00.000Z",
    ip_address: str = "1.2.3.4",
):
    return {
        "application_id": application_id,
        "disclosure_text_version": disclosure_text_version,
        "signed_at": signed_at,
        "ip_address": ip_address,
    }


# ─── BackgroundCheckOrder (PRD §3.3) ──────────────────────────────────

def create_order_payload(
    application_id: str,
    consent_id: str,
    expected_application_version: int,
):
    return {
        "application_id": application_id,
        "consent_id": consent_id,
        "expected_application_version": expected_application_version,
    }


# ─── Verification (PRD §3.4) ──────────────────────────────────────────

def create_verification_payload(verification_type: str):
    return {"verification_type": verification_type}


def report_verification_payload(
    result: str, expected_verification_version: int, report_payload=None,
):
    return {
        "result": result,
        "report_payload": report_payload if report_payload is not None else {},
        "expected_verification_version": expected_verification_version,
    }


def dispute_verification_payload(
    dispute_reason: str, expected_verification_version: int,
):
    return {
        "dispute_reason": dispute_reason,
        "expected_verification_version": expected_verification_version,
    }


def resolve_verification_payload(
    new_result: str, expected_verification_version: int,
):
    return {
        "new_result": new_result,
        "expected_verification_version": expected_verification_version,
    }
