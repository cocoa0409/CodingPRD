"""Request-payload builders.

Every builder returns a valid minimal payload and accepts ``**overrides`` so a
test can bend exactly one field.  Passing ``None`` for an override removes the
key entirely, which is how a missing-required-field case is expressed.
"""

from typing import Any, Dict, List, Optional

# A description narrating what a mentoring contact covered, comfortably above
# the 20-character floor.
CONTACT_DESCRIPTION = (
    "Weekly one-on-one planning conference with the novice teacher and "
    "formative data review"
)

# A narrative comfortably above the 120-character floor for submitted feedback.
FEEDBACK_NARRATIVE = (
    "The novice opened with a clearly posted objective, circulated purposefully "
    "during independent practice, and used exit ticket data to close the lesson "
    "with targeted reteaching for the small group that struggled with "
    "proportional reasoning."
)

VERIFY_NOTE = "Minutes corroborated by the site sign-in sheet"


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides into a payload; an override of None drops the key."""
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def site_payload(**overrides: Any) -> Dict[str, Any]:
    """A district school site. site_code is uppercase alphanumeric, 3 to 10 chars."""
    return _apply(
        {
            "name": "Northgate High",
            "site_code": "NG001",
            "region_code": "NORTH",
            "mentor_slot_cap": 6,
        },
        overrides,
    )


def cohort_payload(**overrides: Any) -> Dict[str, Any]:
    """An induction cohort for a program year and region."""
    return _apply(
        {
            "name": "Induction 2026-27",
            "program_year": 2026,
            "region_code": "NORTH",
            "seminar_sessions_required": 1,
        },
        overrides,
    )


def mentor_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    """A veteran teacher registered against a site."""
    return _apply(
        {
            "site_id": site_id,
            "full_name": "Rosa Alvarez",
            "subject_endorsements": ["MATH"],
            "caseload_cap": 2,
        },
        overrides,
    )


def training_credit_payload(
    module_code: str = "FOUNDATIONS", hours: float = 8.00, **overrides: Any
) -> Dict[str, Any]:
    """One posted mentor-training credit."""
    return _apply(
        {
            "module_code": module_code,
            "hours": hours,
            "completed_on": "2026-07-10",
        },
        overrides,
    )


def certification_payload(action: str = "CERTIFY", **overrides: Any) -> Dict[str, Any]:
    """A mentor certification lifecycle action."""
    return _apply({"action": action}, overrides)


def novice_payload(site_id: str, cohort_id: str, **overrides: Any) -> Dict[str, Any]:
    """A new teacher enrolled into a cohort at a site."""
    return _apply(
        {
            "site_id": site_id,
            "cohort_id": cohort_id,
            "full_name": "Dana Pike",
            "subject_area": "MATH",
            "induction_year": 1,
        },
        overrides,
    )


def match_payload(
    novice_id: str,
    expected_mentor_version: int,
    mentor_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A proposed mentor-novice pairing; mentor_id is optional."""
    payload: Dict[str, Any] = {
        "novice_id": novice_id,
        "expected_mentor_version": expected_mentor_version,
    }
    if mentor_id is not None:
        payload["mentor_id"] = mentor_id
    return _apply(payload, overrides)


def disposition_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """A match disposition: ACTIVATE, REJECT, SUSPEND, RESUME or END."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision in ("REJECT", "SUSPEND", "END"):
        payload["reason"] = "District reassigned the mentoring relationship"
    return _apply(payload, overrides)


def contact_log_payload(
    match_id: str,
    contact_date: str,
    minutes: int = 60,
    contact_type: str = "ONE_ON_ONE",
    **overrides: Any,
) -> Dict[str, Any]:
    """A mentoring contact record against a live relationship."""
    return _apply(
        {
            "match_id": match_id,
            "contact_date": contact_date,
            "minutes": minutes,
            "contact_type": contact_type,
            "description": CONTACT_DESCRIPTION,
        },
        overrides,
    )


def review_payload(decision: str, note: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """A contact-log review: VERIFY, DISPUTE or REJECT."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "VERIFY":
        payload["note"] = note if note is not None else VERIFY_NOTE
    elif decision == "DISPUTE":
        payload["note"] = note if note is not None else "Minutes claimed exceed the sign-in sheet"
    elif decision == "REJECT":
        payload["note"] = note if note is not None else "Contact could not be corroborated at all"
    elif note is not None:
        payload["note"] = note
    return _apply(payload, overrides)


def resubmit_payload(
    minutes: int = 45, contact_type: str = "ONE_ON_ONE", **overrides: Any
) -> Dict[str, Any]:
    """Replacement values for a disputed contact log."""
    return _apply(
        {
            "minutes": minutes,
            "contact_type": contact_type,
            "description": (
                "Corrected duration after checking the sign-in sheet for the "
                "planning conference"
            ),
        },
        overrides,
    )


def void_payload(**overrides: Any) -> Dict[str, Any]:
    """A void of an already verified contact log."""
    return _apply(
        {"void_reason": "Model lesson was delivered by a different mentor"}, overrides
    )


def observation_cycle_payload(
    match_id: str,
    cycle_index: int,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A booked classroom observation window."""
    return _apply(
        {
            "match_id": match_id,
            "cycle_index": cycle_index,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def advance_payload(to_phase: str, **overrides: Any) -> Dict[str, Any]:
    """A phase advance request."""
    payload: Dict[str, Any] = {"to_phase": to_phase}
    if to_phase == "ABANDONED":
        payload["reason"] = "The novice was absent on the booked observation day"
    return _apply(payload, overrides)


def feedback_payload(
    submit: bool = True,
    narrative: str = FEEDBACK_NARRATIVE,
    growth_area_codes: Optional[List[str]] = None,
    rubric_scores: Optional[Dict[str, int]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A written feedback package for an observation cycle."""
    return _apply(
        {
            "narrative": narrative,
            "growth_area_codes": list(growth_area_codes or ["PLANNING", "INSTRUCTION"]),
            "rubric_scores": dict(
                rubric_scores
                or {"planning": 3, "instruction": 3, "environment": 3, "assessment": 3}
            ),
            "submit": submit,
        },
        overrides,
    )


def feedback_review_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """A feedback review decision: RETURN or ACCEPT."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "RETURN":
        payload["return_reason"] = "Add evidence for the assessment dimension"
    return _apply(payload, overrides)


def milestone_payload(
    code: str,
    sequence_index: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A milestone definition; code is uppercase snake case."""
    return _apply(
        {
            "code": code,
            "title": f"Induction milestone {sequence_index}",
            "sequence_index": sequence_index,
            "required_contact_minutes": 0,
            "required_observation_cycles": 0,
            "required_credited_seminars": 0,
            "license_stage_unlocked": "PROVISIONAL",
        },
        overrides,
    )


def attainment_payload(novice_id: str, milestone_id: str, **overrides: Any) -> Dict[str, Any]:
    """An explicitly opened milestone attainment row."""
    return _apply({"novice_id": novice_id, "milestone_id": milestone_id}, overrides)


def attainment_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """An attainment decision: ATTEST, REVOKE or REOPEN."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "REVOKE":
        payload["revoke_reason"] = "Evidence file could not be reconciled at audit"
    return _apply(payload, overrides)


def seminar_session_payload(
    cohort_id: str,
    session_index: int,
    scheduled_start: str,
    scheduled_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A scheduled cohort seminar session."""
    return _apply(
        {
            "cohort_id": cohort_id,
            "session_index": session_index,
            "topic": "Classroom routines and formative assessment",
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
        },
        overrides,
    )


def session_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    """A seminar session resolution: HELD or CANCELLED."""
    payload: Dict[str, Any] = {"status": status}
    if status == "CANCELLED":
        payload["cancel_reason"] = "Facilitator unavailable and no substitute was found"
    return _apply(payload, overrides)


def attendance_payload(
    session_id: str,
    novice_id: str,
    attendance_status: str = "PRESENT",
    minutes_attended: int = 120,
    **overrides: Any,
) -> Dict[str, Any]:
    """One novice's attendance at one seminar session."""
    return _apply(
        {
            "session_id": session_id,
            "novice_id": novice_id,
            "attendance_status": attendance_status,
            "minutes_attended": minutes_attended,
        },
        overrides,
    )


def disbursement_payload(
    mentor_id: str,
    expected_mentor_version: int,
    period_code: str = "2026-Q3",
    period_start: str = "2026-07-01T00:00:00Z",
    period_end: str = "2026-09-30T23:59:59Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A stipend disbursement draft for a closed quarterly period."""
    return _apply(
        {
            "mentor_id": mentor_id,
            "period_code": period_code,
            "period_start": period_start,
            "period_end": period_end,
            "expected_mentor_version": expected_mentor_version,
        },
        overrides,
    )


def disbursement_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    """A disbursement status change: APPROVED, PAID or CLAWED_BACK."""
    payload: Dict[str, Any] = {"status": status}
    if status == "PAID":
        payload["payment_reference"] = "ACH-2026-Q3-0001"
    elif status == "CLAWED_BACK":
        payload["clawback_reason"] = (
            "District audit reversed the quarter after a duplicate payment was found"
        )
    return _apply(payload, overrides)


def packet_payload(novice_id: str, expected_novice_version: int, **overrides: Any) -> Dict[str, Any]:
    """A completion certification packet assembled for a novice."""
    return _apply(
        {"novice_id": novice_id, "expected_novice_version": expected_novice_version},
        overrides,
    )


def packet_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    """A district-side packet action: SUBMIT, REOPEN or WITHDRAW."""
    payload: Dict[str, Any] = {"action": action}
    if action == "WITHDRAW":
        payload["reason"] = "District withdrew the packet pending an evidence review"
    return _apply(payload, overrides)


def state_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    """A state-side packet decision: ACCEPT or RETURN."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "ACCEPT":
        payload["state_file_number"] = "SF-2026-000123"
    else:
        payload["return_reason"] = "Observation evidence is missing from the packet"
    return _apply(payload, overrides)


def close_site_payload(**overrides: Any) -> Dict[str, Any]:
    """A one-way site closure."""
    return _apply({"reason": "Campus consolidated into the neighbouring site"}, overrides)


def close_cohort_payload(target_status: str = "CLOSED", **overrides: Any) -> Dict[str, Any]:
    """A cohort lifecycle move."""
    return _apply({"target_status": target_status}, overrides)


def withdraw_novice_payload(**overrides: Any) -> Dict[str, Any]:
    """A novice withdrawal from the induction program."""
    return _apply({"reason": "Teacher resigned mid-year for family reasons"}, overrides)


def retention_outcome_payload(
    retention_outcome: str = "RETAINED_SAME_SITE",
    observed_on: str = "2027-08-15T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """The observed retention outcome one year after induction."""
    return _apply(
        {"retention_outcome": retention_outcome, "observed_on": observed_on}, overrides
    )
