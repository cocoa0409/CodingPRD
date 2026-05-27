"""Payload factories — one per writeable entity, input fields only.

All factories accept **overrides so tests can pin specific fields when their
assertions depend on a particular value.
"""
import uuid


# ─── Counter to keep unique values across a single test run ──────
# Each factory call gets a fresh suffix; this avoids UNIQUE-constraint
# collisions on alien_number, email, and bar_number.

def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _alien_number() -> str:
    """A-Number matching ^A\\d{9}$ (PRD §2.6)."""
    # 9 digits derived from uuid (digits only)
    digits = "".join(c for c in uuid.uuid4().hex if c.isdigit())
    digits = (digits + "000000000")[:9]
    return f"A{digits}"


def _bar_number() -> str:
    return f"BAR-{_suffix()}"


def _email(local: str = "user") -> str:
    return f"{local}-{_suffix()}@example.com"


# ─── Applicant ──────────────────────────────────────────────────


def create_applicant_payload(**overrides) -> dict:
    """Payload for POST /uscis/applicants/register.

    Required fields per PRD §3.1: alien_number, full_name, date_of_birth,
    country_of_chargeability, email.
    """
    defaults = {
        "alien_number": _alien_number(),
        "full_name": "Test Applicant",
        "date_of_birth": "1990-01-01",
        "country_of_chargeability": "WORLDWIDE",
        "email": _email("applicant"),
    }
    defaults.update(overrides)
    return defaults


# ─── Attorney ───────────────────────────────────────────────────


def create_attorney_payload(**overrides) -> dict:
    """Payload for POST /uscis/attorneys/register.

    Required: bar_number, full_name, firm_name (PRD §3.1).
    """
    defaults = {
        "bar_number": _bar_number(),
        "full_name": "Test Attorney",
        "firm_name": "Test & Co LLP",
    }
    defaults.update(overrides)
    return defaults


# ─── Case ───────────────────────────────────────────────────────


def create_case_payload(applicant_id: str, case_type: str = "I-130",
                        preference_category=None, attorney_id=None, **overrides) -> dict:
    """Payload for POST /uscis/cases.

    Required: applicant_id, case_type. preference_category is required for I-130
    and ignored otherwise (PRD §3.1).
    """
    payload = {
        "applicant_id": applicant_id,
        "case_type": case_type,
    }
    if attorney_id is not None:
        payload["attorney_id"] = attorney_id
    # I-130 requires preference_category per PRD §3.1.
    if case_type == "I-130" and preference_category is None:
        preference_category = "IR"
    if preference_category is not None:
        payload["preference_category"] = preference_category
    payload.update(overrides)
    return payload


# ─── BiometricsAppointment ──────────────────────────────────────


def create_biometrics_payload(scheduled_at: str,
                              asc_location_code: str = "ASC-SF-01",
                              **overrides) -> dict:
    """Payload for POST /uscis/cases/{id}/biometrics. (PRD §3.3)"""
    payload = {
        "scheduled_at": scheduled_at,
        "asc_location_code": asc_location_code,
    }
    payload.update(overrides)
    return payload


def reschedule_biometrics_payload(new_scheduled_at: str,
                                  new_asc_location_code: str = "ASC-SF-02",
                                  **overrides) -> dict:
    """Payload for POST /uscis/biometrics/{id}/reschedule. (PRD §3.3)"""
    payload = {
        "new_scheduled_at": new_scheduled_at,
        "new_asc_location_code": new_asc_location_code,
    }
    payload.update(overrides)
    return payload


# ─── RFE ────────────────────────────────────────────────────────


def issue_rfe_payload(evidence_items_requested=None, **overrides) -> dict:
    """Payload for POST /uscis/cases/{id}/rfes. (PRD §3.5)"""
    payload = {
        "evidence_items_requested": (
            evidence_items_requested
            if evidence_items_requested is not None
            else ["proof_of_relationship"]
        ),
    }
    payload.update(overrides)
    return payload


def rfe_respond_payload(expected_case_version: int,
                        response_summary: str = "Evidence submitted.",
                        **overrides) -> dict:
    """Payload for POST /uscis/rfes/{id}/respond. (PRD §3.6, §2.10)"""
    payload = {
        "expected_case_version": expected_case_version,
        "response_summary": response_summary,
    }
    payload.update(overrides)
    return payload


# ─── InterviewAppointment ───────────────────────────────────────


def schedule_interview_payload(scheduled_at: str,
                               field_office_code: str = "FO-SFR",
                               **overrides) -> dict:
    """Payload for POST /uscis/cases/{id}/interviews. (PRD §3.5)"""
    payload = {
        "scheduled_at": scheduled_at,
        "field_office_code": field_office_code,
    }
    payload.update(overrides)
    return payload


def complete_interview_payload(decision_after_interview: str, **overrides) -> dict:
    """Payload for POST /uscis/interviews/{id}/complete. (PRD §3.7)"""
    payload = {"decision_after_interview": decision_after_interview}
    payload.update(overrides)
    return payload


# ─── Decide ─────────────────────────────────────────────────────


def decide_case_payload(decision: str, expected_case_version: int, **overrides) -> dict:
    """Payload for POST /uscis/cases/{id}/decide. (PRD §3.5, §3.7, §2.10)

    decision ∈ {APPROVE, DENY, REOPEN}.
    """
    payload = {
        "decision": decision,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


# ─── VisaBulletinEntry ──────────────────────────────────────────


def visa_bulletin_payload(bulletin_month: str,
                          preference_category: str,
                          country: str,
                          chart_type: str,
                          cutoff_date: str,
                          **overrides) -> dict:
    """Payload for POST /uscis/visa-bulletin. (PRD §3.4)"""
    payload = {
        "bulletin_month": bulletin_month,
        "preference_category": preference_category,
        "country": country,
        "chart_type": chart_type,
        "cutoff_date": cutoff_date,
    }
    payload.update(overrides)
    return payload


# ─── Clock ──────────────────────────────────────────────────────


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    """Payload for POST /uscis/_clock/set_current_utc. (PRD §2.5)"""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
