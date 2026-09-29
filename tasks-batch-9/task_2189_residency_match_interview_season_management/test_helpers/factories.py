"""Request-payload factories.

Each factory returns only the client-supplied input fields declared for the
endpoint by PRD §4 — never a system-managed or computed field — and accepts
``**overrides`` so a test can vary one value without restating the payload.
"""

from typing import Any

from .constants import (
    DEFAULT_SALARY_CENTS,
    DIRECTOR_NAME,
    LEAD_INTERVIEWER_NAME,
    PATHOLOGY_PROGRAM_CODE,
    PATHOLOGY_PROGRAM_NAME,
    PATHOLOGY_SPECIALTY,
    PROGRAM_CODE,
    PROGRAM_NAME,
    PROGRAM_SPECIALTY,
    SLOT_END_AT,
    SLOT_ROOM_LABEL,
    SLOT_START_AT,
    WAVE_INVITE_RELEASE_AT,
    WAVE_RESPONSE_DEADLINE_AT,
)
from .types import (
    Ballot,
    CommunicationChannel,
    MedicalSchoolType,
    PanelRole,
    ScreeningDecision,
    VisaStatus,
)


def _merge(payload: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Apply overrides, letting a caller drop a key entirely by passing ``None``.

    Keys whose override value is the sentinel string ``"__omit__"`` are removed
    from the payload, which is how tests exercise a missing required input.
    """
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v != "__omit__"}


OMIT = "__omit__"


# ----------------------------------------------------------------------
# Program
# ----------------------------------------------------------------------
def build_program_payload(**overrides) -> dict[str, Any]:
    return _merge(
        {
            "name": PROGRAM_NAME,
            "nrmp_program_code": PROGRAM_CODE,
            "specialty_code": PROGRAM_SPECIALTY,
            "quota_positions": 2,
            "visa_sponsorship_allowed": True,
            "soap_participating": True,
            "min_step2_score": 220,
            "img_accepted": True,
        },
        overrides,
    )


def build_pathology_program_payload(**overrides) -> dict[str, Any]:
    return build_program_payload(
        **{
            "name": PATHOLOGY_PROGRAM_NAME,
            "nrmp_program_code": PATHOLOGY_PROGRAM_CODE,
            "specialty_code": PATHOLOGY_SPECIALTY,
            "quota_positions": 1,
            **overrides,
        }
    )


def build_minimal_program_payload(**overrides) -> dict[str, Any]:
    """Only the four required inputs, so the declared defaults apply."""
    return _merge(
        {
            "name": PATHOLOGY_PROGRAM_NAME,
            "nrmp_program_code": PATHOLOGY_PROGRAM_CODE,
            "specialty_code": PATHOLOGY_SPECIALTY,
            "quota_positions": 1,
        },
        overrides,
    )


def build_advance_phase_payload(to_phase: str, **overrides) -> dict[str, Any]:
    return _merge({"to_phase": to_phase}, overrides)


# ----------------------------------------------------------------------
# Applicant
# ----------------------------------------------------------------------
def build_applicant_payload(**overrides) -> dict[str, Any]:
    return _merge(
        {
            "eras_id": "E-9001",
            "full_name": "Nia Patel",
            "medical_school_type": MedicalSchoolType.US_MD,
            "visa_status": VisaStatus.US_CITIZEN,
            "step2_score": 251,
            "pipeline_program_alum": True,
            "self_identified_group": "GROUP_A",
        },
        overrides,
    )


def build_second_applicant_payload(**overrides) -> dict[str, Any]:
    return build_applicant_payload(
        **{
            "eras_id": "E-9002",
            "full_name": "Omar Diaz",
            "step2_score": 240,
            "pipeline_program_alum": False,
            "self_identified_group": "GROUP_B",
            **overrides,
        }
    )


def build_third_applicant_payload(**overrides) -> dict[str, Any]:
    return build_applicant_payload(
        **{
            "eras_id": "E-9003",
            "full_name": "Priya Rao",
            "medical_school_type": MedicalSchoolType.US_DO,
            "step2_score": 232,
            "pipeline_program_alum": False,
            "self_identified_group": "GROUP_A",
            **overrides,
        }
    )


# ----------------------------------------------------------------------
# Application, reviews, screening
# ----------------------------------------------------------------------
def build_application_payload(program_id: str, applicant_id: str, **overrides):
    return _merge(
        {"program_id": program_id, "applicant_id": applicant_id}, overrides
    )


def build_application_review_payload(**overrides) -> dict[str, Any]:
    return _merge(
        {"academic_points": 30, "experience_points": 20, "holistic_points": 20},
        overrides,
    )


def build_screen_payload(decision: str = ScreeningDecision.ADVANCE, **overrides):
    return _merge({"decision": decision}, overrides)


def build_withdraw_payload(
    withdrawn_reason: str = "Accepted a position elsewhere", **overrides
):
    return _merge({"withdrawn_reason": withdrawn_reason}, overrides)


# ----------------------------------------------------------------------
# FacultyMember
# ----------------------------------------------------------------------
def build_faculty_member_payload(program_id: str, **overrides) -> dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "full_name": LEAD_INTERVIEWER_NAME,
            "is_program_director": False,
            "is_committee_member": True,
            "conflict_applicant_ids": [],
        },
        overrides,
    )


def build_director_payload(program_id: str, **overrides) -> dict[str, Any]:
    return build_faculty_member_payload(
        program_id,
        **{
            "full_name": DIRECTOR_NAME,
            "is_program_director": True,
            "is_committee_member": False,
            **overrides,
        },
    )


# ----------------------------------------------------------------------
# InterviewWave / InterviewSlot / invitations / assignments
# ----------------------------------------------------------------------
def build_interview_wave_payload(program_id: str, **overrides) -> dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "wave_index": 1,
            "invite_release_at": WAVE_INVITE_RELEASE_AT,
            "response_deadline_at": WAVE_RESPONSE_DEADLINE_AT,
            "seat_capacity": 4,
        },
        overrides,
    )


def build_interview_slot_payload(wave_id: str, **overrides) -> dict[str, Any]:
    return _merge(
        {
            "wave_id": wave_id,
            "start_at": SLOT_START_AT,
            "end_at": SLOT_END_AT,
            "room_label": SLOT_ROOM_LABEL,
            "applicant_capacity": 1,
        },
        overrides,
    )


def build_invitation_payload(
    application_id: str, expected_wave_version: int, **overrides
):
    return _merge(
        {
            "application_id": application_id,
            "expected_wave_version": expected_wave_version,
        },
        overrides,
    )


def build_accept_invitation_payload(slot_id: str, **overrides) -> dict[str, Any]:
    return _merge({"slot_id": slot_id}, overrides)


def build_interview_assignment_payload(
    slot_id: str, faculty_member_id: str, panel_role: str = PanelRole.LEAD, **overrides
):
    return _merge(
        {
            "slot_id": slot_id,
            "faculty_member_id": faculty_member_id,
            "panel_role": panel_role,
        },
        overrides,
    )


def build_complete_slot_payload(no_show_application_ids=None, **overrides):
    payload: dict[str, Any] = {}
    if no_show_application_ids is not None:
        payload["no_show_application_ids"] = no_show_application_ids
    return _merge(payload, overrides)


# ----------------------------------------------------------------------
# ScoreCard
# ----------------------------------------------------------------------
def build_score_card_payload(
    assignment_id: str,
    application_id: str,
    scores: tuple[int, int, int, int] = (8, 9, 9, 9),
    **overrides,
):
    communication, clinical, professionalism, teamwork = scores
    return _merge(
        {
            "assignment_id": assignment_id,
            "application_id": application_id,
            "communication_score": communication,
            "clinical_reasoning_score": clinical,
            "professionalism_score": professionalism,
            "teamwork_score": teamwork,
        },
        overrides,
    )


def build_revise_score_card_payload(
    scores: tuple[int, int, int, int] = (6, 6, 6, 6), **overrides
):
    communication, clinical, professionalism, teamwork = scores
    return _merge(
        {
            "communication_score": communication,
            "clinical_reasoning_score": clinical,
            "professionalism_score": professionalism,
            "teamwork_score": teamwork,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# RankList and committee
# ----------------------------------------------------------------------
def build_rank_list_payload(program_id: str, **overrides) -> dict[str, Any]:
    return _merge({"program_id": program_id}, overrides)


def build_rank_list_entry_payload(
    application_id: str,
    rank_position: int,
    expected_rank_list_version: int,
    **overrides,
):
    return _merge(
        {
            "application_id": application_id,
            "rank_position": rank_position,
            "expected_rank_list_version": expected_rank_list_version,
        },
        overrides,
    )


def build_committee_vote_payload(
    faculty_member_id: str, ballot: str = Ballot.APPROVE, **overrides
):
    return _merge({"faculty_member_id": faculty_member_id, "ballot": ballot}, overrides)


def build_certify_payload(certified_by_faculty_id: str, **overrides) -> dict[str, Any]:
    return _merge({"certified_by_faculty_id": certified_by_faculty_id}, overrides)


# ----------------------------------------------------------------------
# SOAP, contracts, credentials
# ----------------------------------------------------------------------
def build_soap_offer_payload(
    program_id: str, application_id: str, soap_round: int = 1, **overrides
):
    return _merge(
        {
            "program_id": program_id,
            "application_id": application_id,
            "soap_round": soap_round,
        },
        overrides,
    )


def build_contract_payload(
    match_result_id: str, salary_cents: int = DEFAULT_SALARY_CENTS, **overrides
):
    return _merge(
        {"match_result_id": match_result_id, "salary_cents": salary_cents}, overrides
    )


def build_reason_payload(reason: str, **overrides) -> dict[str, Any]:
    return _merge({"reason": reason}, overrides)


def build_credential_submit_payload(
    reference_number: str = "LIC-778812", **overrides
):
    return _merge({"reference_number": reference_number}, overrides)


# ----------------------------------------------------------------------
# CommunicationLog
# ----------------------------------------------------------------------
def build_communication_log_payload(
    application_id: str,
    body: str,
    channel: str = CommunicationChannel.EMAIL,
    author_faculty_id: str | None = None,
    **overrides,
):
    payload: dict[str, Any] = {
        "application_id": application_id,
        "channel": channel,
        "body": body,
    }
    if author_faculty_id is not None:
        payload["author_faculty_id"] = author_faculty_id
    return _merge(payload, overrides)


def build_resolve_payload(resolution_note: str, **overrides) -> dict[str, Any]:
    return _merge({"resolution_note": resolution_note}, overrides)


# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------
def build_clock_payload(current_utc: str, **overrides) -> dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)
