"""Request-payload builders.

Each builder returns a dict carrying exactly the fields the operation requires,
with sensible defaults for the optional ones, and accepts ``**overrides`` so a
test can vary one field without restating the rest.  Passing ``None`` for an
override removes the key entirely, which is how tests exercise omitted-field
validation.
"""

from typing import Any, Dict, List, Optional

from . import constants as C


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides, dropping any key whose override value is ``None``."""
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ----------------------------------------------------------------------
# Agencies
# ----------------------------------------------------------------------
def agency_payload(
    legal_name: str = "Sunrise Education Consultants",
    home_country_code: str = "IN",
    **overrides: Any,
) -> Dict[str, Any]:
    """A registration body with the due-diligence checklist left at defaults."""
    return _apply(
        {"legal_name": legal_name, "home_country_code": home_country_code}, overrides
    )


def complete_diligence_agency_payload(
    legal_name: str = "Sunrise Education Consultants",
    home_country_code: str = "IN",
    **overrides: Any,
) -> Dict[str, Any]:
    """A registration body whose checklist already satisfies the clearance gate."""
    return _apply(
        {
            "legal_name": legal_name,
            "home_country_code": home_country_code,
            "ownership_disclosed": True,
            "beneficial_owner_count": 2,
            "sanctions_screen_passed": True,
            "reference_check_count": 3,
        },
        overrides,
    )


def vetting_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"action": action}, overrides)


def posture_action_payload(action: str, reason: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"action": action, "reason": reason}, overrides)


def certification_payload(
    module_code: str = C.MODULE_PROGRAM_ACCURACY,
    score: int = 92,
    issued_on: str = C.DEFAULT_CLOCK_DATE,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {"module_code": module_code, "score": score, "issued_on": issued_on}, overrides
    )


def scorecard_payload(
    period_start_date: str, period_end_date: str, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {"period_start_date": period_start_date, "period_end_date": period_end_date},
        overrides,
    )


# ----------------------------------------------------------------------
# Programs
# ----------------------------------------------------------------------
def program_payload(
    code: str = "MSCS-2026",
    name: str = "MSc Computer Science",
    level: str = C.LEVEL_POSTGRADUATE,
    annual_tuition_cents: int = 2845700,
    term_start_date: str = "2026-09-01",
    census_date: str = "2026-09-30",
    persistence_check_date: str = "2027-02-15",
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "code": code,
            "name": name,
            "level": level,
            "annual_tuition_cents": annual_tuition_cents,
            "term_start_date": term_start_date,
            "census_date": census_date,
            "persistence_check_date": persistence_check_date,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Contracts
# ----------------------------------------------------------------------
def contract_payload(
    agency_id: str,
    contract_ref: str = "CTR-2026-001",
    exclusivity_model: str = C.EXCLUSIVITY_EXCLUSIVE_ALLOWED,
    term_start_date: str = "2026-08-01",
    term_end_date: str = "2027-07-31",
    annual_commission_cap_cents: int = 5000000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "agency_id": agency_id,
            "contract_ref": contract_ref,
            "exclusivity_model": exclusivity_model,
            "term_start_date": term_start_date,
            "term_end_date": term_end_date,
            "annual_commission_cap_cents": annual_commission_cap_cents,
        },
        overrides,
    )


def lifecycle_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"action": action}, overrides)


def termination_payload(
    reason_code: str,
    effective_date: str,
    transition_note: str,
    successor_agency_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reason_code": reason_code,
        "effective_date": effective_date,
        "transition_note": transition_note,
    }
    if successor_agency_id is not None:
        payload["successor_agency_id"] = successor_agency_id
    return _apply(payload, overrides)


def territory_payload(
    country_code: str = "IN",
    exclusivity: str = C.TERRITORY_EXCLUSIVE,
    start_date: str = "2026-08-01",
    end_date: str = "2027-07-31",
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "country_code": country_code,
            "exclusivity": exclusivity,
            "start_date": start_date,
            "end_date": end_date,
        },
        overrides,
    )


def schedule_payload(
    expected_contract_version: int,
    effective_from: str = "2026-08-01",
    effective_to: str = "2027-07-31",
    deposit_rate_bps: int = 400,
    enrollment_rate_bps: int = 500,
    census_rate_bps: int = 200,
    persistence_rate_bps: int = 150,
    rate_cap_bps: int = 600,
    per_milestone_cap_cents: int = 150000,
    clawback_window_days: int = 120,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "expected_contract_version": expected_contract_version,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "deposit_rate_bps": deposit_rate_bps,
            "enrollment_rate_bps": enrollment_rate_bps,
            "census_rate_bps": census_rate_bps,
            "persistence_rate_bps": persistence_rate_bps,
            "rate_cap_bps": rate_cap_bps,
            "per_milestone_cap_cents": per_milestone_cap_cents,
            "clawback_window_days": clawback_window_days,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Student applications
# ----------------------------------------------------------------------
def application_payload(
    agency_id: str,
    program_id: str,
    student_ref: str = "STU-0001",
    student_residence_country: str = "IN",
    student_us_person: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "agency_id": agency_id,
            "program_id": program_id,
            "student_ref": student_ref,
            "student_residence_country": student_residence_country,
            "student_us_person": student_us_person,
        },
        overrides,
    )


def disclosure_issue_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply({"action": C.DISCLOSURE_ACTION_ISSUE}, overrides)


def disclosure_acknowledge_payload(token: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"action": C.DISCLOSURE_ACTION_ACKNOWLEDGE, "ack_token": token}, overrides
    )


def decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)


def milestone_payload(
    milestone: str, event_date: str, expected_application_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "milestone": milestone,
            "event_date": event_date,
            "expected_application_version": expected_application_version,
        },
        overrides,
    )


def withdrawal_payload(
    withdrawal_date: str, reason: str = "Student deferred to next intake", **overrides: Any
) -> Dict[str, Any]:
    return _apply({"withdrawal_date": withdrawal_date, "reason": reason}, overrides)


# ----------------------------------------------------------------------
# Supporting documents
# ----------------------------------------------------------------------
def document_payload(
    doc_type: str = C.DOC_PASSPORT,
    content_hash: str = "hash-passport-0001",
    issuer_name: Optional[str] = "MEA India",
    declared_signals: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_type": doc_type,
        "content_hash": content_hash,
        "declared_signals": list(declared_signals or []),
    }
    if issuer_name is not None:
        payload["issuer_name"] = issuer_name
    return _apply(payload, overrides)


def verification_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"outcome": outcome}, overrides)


# ----------------------------------------------------------------------
# Integrity incidents
# ----------------------------------------------------------------------
def incident_payload(
    agency_id: str,
    category: str = C.INCIDENT_MISREPRESENTATION,
    severity: str = C.SEVERITY_HIGH,
    occurred_on: str = C.DEFAULT_CLOCK_DATE,
    source: str = C.SOURCE_AUDIT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "agency_id": agency_id,
            "category": category,
            "severity": severity,
            "occurred_on": occurred_on,
            "source": source,
        },
        overrides,
    )


def resolution_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"outcome": outcome}, overrides)


# ----------------------------------------------------------------------
# Commission ledger
# ----------------------------------------------------------------------
def disposition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"action": action}, overrides)
