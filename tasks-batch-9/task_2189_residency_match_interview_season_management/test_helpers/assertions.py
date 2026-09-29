"""Reusable domain assertions.

Shape assertions check that a resource body carries every field the PRD
declares for it, plus the four system-managed fields required of every
resource (PRD §2.6). Invariant assertions check the conserved quantities and
pinned rounding rules the PRD states (PRD §2.8, §2.10).
"""

import math
from decimal import ROUND_HALF_UP, Decimal

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ACADEMIC_WEIGHT,
    COMMITTEE_QUORUM_PCT,
    EXPERIENCE_WEIGHT,
    HOLISTIC_WEIGHT,
    LEAD_LOAD_FACTOR,
    MEMBER_LOAD_FACTOR,
    PIPELINE_ALUM_BONUS,
    SCORE_CEILING,
    STEP2_BANDS,
)
from .types import PanelRole

#: Tolerance for two-decimal monetary/score comparisons.
SCORE_TOLERANCE = 0.01


def round_half_up(value: float, places: int) -> float:
    """Round half up, as every score in this specification is rounded."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------
# Generic shape helpers
# ----------------------------------------------------------------------
def assert_system_fields(data: dict, label: str = "resource") -> None:
    """Every resource carries id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in data, f"{label} is missing the system field '{field}'"
        assert data[field] is not None, f"{label}.{field} must not be null"
    assert is_valid_uuid(data["id"]), f"{label}.id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(
        data["created_at"]
    ), f"{label}.created_at is not ISO 8601: {data['created_at']!r}"
    assert is_iso8601_timestamp(
        data["updated_at"]
    ), f"{label}.updated_at is not ISO 8601: {data['updated_at']!r}"
    assert isinstance(
        data["version"], int
    ), f"{label}.version must be an integer, got {type(data['version']).__name__}"
    assert data["version"] >= 1, f"{label}.version must start at 1, got {data['version']}"


def assert_has_fields(data: dict, fields, label: str) -> None:
    missing = [f for f in fields if f not in data]
    assert not missing, f"{label} is missing declared field(s) {missing}"


def _shape(data: dict, label: str, fields) -> dict:
    assert_system_fields(data, label)
    assert_has_fields(data, fields, label)
    return data


# ----------------------------------------------------------------------
# Per-resource shape assertions
# ----------------------------------------------------------------------
def assert_program(data: dict) -> dict:
    return _shape(
        data,
        "Program",
        (
            "name",
            "nrmp_program_code",
            "specialty_code",
            "quota_positions",
            "season_phase",
            "visa_sponsorship_allowed",
            "soap_participating",
            "min_step2_score",
            "img_accepted",
            "matched_count",
            "unfilled_positions",
            "invited_count",
            "soap_offer_budget",
            "rank_list_certified_at",
        ),
    )


def assert_applicant(data: dict) -> dict:
    return _shape(
        data,
        "Applicant",
        (
            "eras_id",
            "full_name",
            "medical_school_type",
            "visa_status",
            "step2_score",
            "pipeline_program_alum",
            "self_identified_group",
        ),
    )


def assert_application(data: dict) -> dict:
    return _shape(
        data,
        "Application",
        (
            "program_id",
            "applicant_id",
            "screening_status",
            "interview_status",
            "review_count",
            "provisional_screen_score",
            "final_screen_score",
            "committee_score",
            "withdrawn_reason",
        ),
    )


def assert_faculty_member(data: dict) -> dict:
    return _shape(
        data,
        "FacultyMember",
        (
            "program_id",
            "full_name",
            "is_program_director",
            "is_committee_member",
            "conflict_applicant_ids",
            "scheduled_load",
            "realized_load",
        ),
    )


def assert_application_review(data: dict) -> dict:
    return _shape(
        data,
        "ApplicationReview",
        (
            "application_id",
            "reviewer_id",
            "academic_points",
            "experience_points",
            "holistic_points",
        ),
    )


def assert_interview_wave(data: dict) -> dict:
    return _shape(
        data,
        "InterviewWave",
        (
            "program_id",
            "wave_index",
            "invite_release_at",
            "response_deadline_at",
            "seat_capacity",
            "status",
            "issued_count",
        ),
    )


def assert_interview_slot(data: dict) -> dict:
    return _shape(
        data,
        "InterviewSlot",
        (
            "wave_id",
            "start_at",
            "end_at",
            "room_label",
            "applicant_capacity",
            "booked_count",
            "status",
        ),
    )


def assert_interview_invitation(data: dict) -> dict:
    return _shape(
        data,
        "InterviewInvitation",
        (
            "application_id",
            "wave_id",
            "slot_id",
            "status",
            "issued_at",
            "expires_at",
            "responded_at",
        ),
    )


def assert_interview_assignment(data: dict) -> dict:
    return _shape(
        data,
        "InterviewAssignment",
        ("slot_id", "faculty_member_id", "panel_role", "status"),
    )


def assert_score_card(data: dict) -> dict:
    return _shape(
        data,
        "ScoreCard",
        (
            "assignment_id",
            "application_id",
            "communication_score",
            "clinical_reasoning_score",
            "professionalism_score",
            "teamwork_score",
            "domain_average",
            "status",
        ),
    )


def assert_rank_list(data: dict) -> dict:
    return _shape(
        data,
        "RankList",
        (
            "program_id",
            "status",
            "entry_count",
            "review_round",
            "approved_at",
            "certified_by_faculty_id",
        ),
    )


def assert_rank_list_entry(data: dict) -> dict:
    return _shape(
        data,
        "RankListEntry",
        ("rank_list_id", "application_id", "rank_position", "tie_group_anchor_entry_id"),
    )


def assert_committee_vote(data: dict) -> dict:
    return _shape(
        data,
        "CommitteeVote",
        ("rank_list_id", "faculty_member_id", "review_round", "ballot", "comment"),
    )


def assert_match_result(data: dict) -> dict:
    return _shape(
        data,
        "MatchResult",
        (
            "program_id",
            "application_id",
            "outcome",
            "matched_rank_position",
            "published_at",
        ),
    )


def assert_soap_offer(data: dict) -> dict:
    return _shape(
        data,
        "SoapOffer",
        (
            "program_id",
            "application_id",
            "soap_round",
            "status",
            "offered_at",
            "expires_at",
        ),
    )


def assert_contract(data: dict) -> dict:
    return _shape(
        data,
        "Contract",
        (
            "match_result_id",
            "salary_cents",
            "status",
            "issued_at",
            "signed_at",
            "mandatory_credential_count",
            "verified_credential_count",
        ),
    )


def assert_credential_item(data: dict) -> dict:
    return _shape(
        data,
        "CredentialItem",
        (
            "contract_id",
            "credential_type",
            "is_mandatory",
            "status",
            "reference_number",
            "verified_at",
        ),
    )


def assert_communication_log(data: dict) -> dict:
    return _shape(
        data,
        "CommunicationLog",
        (
            "application_id",
            "author_faculty_id",
            "channel",
            "body",
            "contains_ranking_intent",
            "compliance_status",
            "sent_at",
        ),
    )


# ----------------------------------------------------------------------
# Numeric helpers
# ----------------------------------------------------------------------
def assert_score_equals(actual, expected: float, label: str) -> None:
    """Compare a two-decimal score with the tolerance the PRD's precision allows."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(
        expected, abs=SCORE_TOLERANCE
    ), f"{label} should be {expected}, got {actual}"


def assert_one_decimal(value, expected: float, label: str) -> None:
    assert value is not None, f"{label} must not be null"
    assert value == pytest.approx(
        expected, abs=0.01
    ), f"{label} should be {expected} to one decimal place, got {value}"


# ----------------------------------------------------------------------
# Screening composite (PRD §3.2)
# ----------------------------------------------------------------------
def expected_provisional_score(reviews) -> float:
    """Mean over reviews of the weighted three-domain sum, to two decimals."""
    totals = [
        academic * ACADEMIC_WEIGHT
        + experience * EXPERIENCE_WEIGHT
        + holistic * HOLISTIC_WEIGHT
        for academic, experience, holistic in reviews
    ]
    return round_half_up(sum(totals) / len(totals), 2)


def expected_step2_bonus(step2_score: int) -> float:
    for threshold, bonus in STEP2_BANDS:
        if step2_score >= threshold:
            return bonus
    return 0.0


def expected_final_score(
    reviews, step2_score: int, pipeline_program_alum: bool
) -> float:
    total = expected_provisional_score(reviews) + expected_step2_bonus(step2_score)
    if pipeline_program_alum:
        total += PIPELINE_ALUM_BONUS
    return round_half_up(min(total, SCORE_CEILING), 2)


def assert_provisional_score(application: dict, reviews) -> None:
    assert_score_equals(
        application["provisional_screen_score"],
        expected_provisional_score(reviews),
        "Application.provisional_screen_score",
    )


# ----------------------------------------------------------------------
# Interviewer load (PRD §3.4)
# ----------------------------------------------------------------------
def panel_role_factor(panel_role: str) -> float:
    return LEAD_LOAD_FACTOR if panel_role == PanelRole.LEAD else MEMBER_LOAD_FACTOR


def expected_scheduled_load(seats) -> float:
    """Sum over open panel seats of slot duration in hours times the role factor."""
    return round_half_up(
        sum(hours * panel_role_factor(role) for hours, role in seats), 2
    )


def expected_realized_load(seats) -> float:
    """Scheduled contribution scaled by each slot's attendance factor."""
    return round_half_up(
        sum(
            hours * panel_role_factor(role) * (booked / capacity if capacity else 0.0)
            for hours, role, booked, capacity in seats
        ),
        2,
    )


def assert_load(faculty_member: dict, scheduled: float, realized: float) -> None:
    assert_score_equals(
        faculty_member["scheduled_load"], scheduled, "FacultyMember.scheduled_load"
    )
    assert_score_equals(
        faculty_member["realized_load"], realized, "FacultyMember.realized_load"
    )


# ----------------------------------------------------------------------
# Committee roll-up and quorum (PRD §3.6)
# ----------------------------------------------------------------------
def expected_domain_average(scores) -> float:
    """Mean of the four rubric domains, rounded to one decimal place."""
    return round_half_up(sum(scores) / 4.0, 1)


def expected_committee_score(cards) -> float:
    """Mean of the already one-decimal card averages, rounded to two decimals."""
    averages = [expected_domain_average(scores) for scores in cards]
    return round_half_up(sum(averages) / len(averages), 2)


def expected_quorum_threshold(electorate_size: int) -> int:
    """Ballots needed to approve: ceiling of electorate times the quorum fraction."""
    return math.ceil(electorate_size * COMMITTEE_QUORUM_PCT)


# ----------------------------------------------------------------------
# Conserved quantities (PRD §2.10)
# ----------------------------------------------------------------------
def assert_wave_seat_conservation(wave: dict, expected_issued: int) -> None:
    assert (
        wave["issued_count"] == expected_issued
    ), f"InterviewWave.issued_count should be {expected_issued}, got {wave['issued_count']}"
    assert (
        wave["issued_count"] <= wave["seat_capacity"]
    ), "InterviewWave.issued_count must never exceed seat_capacity"


def assert_slot_booking(slot: dict, expected_booked: int, expected_status: str) -> None:
    assert (
        slot["booked_count"] == expected_booked
    ), f"InterviewSlot.booked_count should be {expected_booked}, got {slot['booked_count']}"
    assert (
        slot["status"] == expected_status
    ), f"InterviewSlot.status should be {expected_status}, got {slot['status']}"
    assert (
        slot["booked_count"] <= slot["applicant_capacity"]
    ), "InterviewSlot.booked_count must never exceed applicant_capacity"


def assert_position_conservation(
    program: dict, expected_matched: int, expected_unfilled: int
) -> None:
    assert (
        program["matched_count"] == expected_matched
    ), f"Program.matched_count should be {expected_matched}, got {program['matched_count']}"
    assert (
        program["unfilled_positions"] == expected_unfilled
    ), (
        f"Program.unfilled_positions should be {expected_unfilled}, "
        f"got {program['unfilled_positions']}"
    )
    assert (
        program["matched_count"] + program["unfilled_positions"]
        == program["quota_positions"]
    ), (
        "matched_count + unfilled_positions must equal quota_positions "
        f"({program['matched_count']} + {program['unfilled_positions']} != "
        f"{program['quota_positions']})"
    )


def assert_credential_counters(
    contract: dict, expected_mandatory: int, expected_verified: int
) -> None:
    assert contract["mandatory_credential_count"] == expected_mandatory, (
        f"Contract.mandatory_credential_count should be {expected_mandatory}, "
        f"got {contract['mandatory_credential_count']}"
    )
    assert contract["verified_credential_count"] == expected_verified, (
        f"Contract.verified_credential_count should be {expected_verified}, "
        f"got {contract['verified_credential_count']}"
    )


# ----------------------------------------------------------------------
# SOAP offer budget (PRD §3.8)
# ----------------------------------------------------------------------
def expected_soap_reserve_credit(base_vacancy: int) -> int:
    """Strict cascade selecting the reserve credit from the base vacancy."""
    if base_vacancy >= 6:
        return 3
    if base_vacancy >= 3:
        return 2
    if base_vacancy >= 1:
        return 1
    return 0


def expected_soap_offer_budget(quota_positions: int, matched_count: int) -> int:
    """Base vacancy plus the reserve credit selected from that base vacancy.

    The tier is keyed on the base vacancy and is never re-derived from the
    resulting budget, so this is a single pass with no fixed-point iteration.
    """
    base_vacancy = quota_positions - matched_count
    return base_vacancy + expected_soap_reserve_credit(base_vacancy)


# ----------------------------------------------------------------------
# Collection helpers
# ----------------------------------------------------------------------
def find_by(rows, **criteria):
    """Return the single row matching every keyword criterion."""
    matches = [r for r in rows if all(r.get(k) == v for k, v in criteria.items())]
    assert len(matches) == 1, (
        f"expected exactly one row matching {criteria}, found {len(matches)} "
        f"in {[{k: r.get(k) for k in criteria} for r in rows]}"
    )
    return matches[0]


def assert_ordered_by(rows, field: str, ascending: bool = True) -> None:
    values = [r[field] for r in rows]
    expected = sorted(values) if ascending else sorted(values, reverse=True)
    assert values == expected, (
        f"rows are not ordered by {field} "
        f"{'ascending' if ascending else 'descending'}: {values}"
    )
