"""Entity assertions and domain invariant checkers.

Every one of the twelve persisted resource types carries `id`, `created_at`,
`updated_at` and `version` (PRD §2.4), so the shared helper below is applied to
all of them.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS


# --------------------------------------------------------------------------- #
# Shared system-managed properties
# --------------------------------------------------------------------------- #
def assert_common_fields(data: dict) -> None:
    """`id` is a server-minted UUID with no type prefix; `created_at` and
    `updated_at` are ISO 8601 UTC; `version` is a monotonically increasing
    counter."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #
def assert_student(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["student_number"], str) and 1 <= len(data["student_number"]) <= 20
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["race_ethnicity_code"] in [
        "AIAN",
        "ASIAN",
        "BLACK",
        "HISPANIC",
        "MULTI",
        "NHPI",
        "WHITE",
        "UNKNOWN",
    ]
    assert isinstance(data["first_generation"], bool)
    assert isinstance(data["pell_eligible"], bool)
    assert data["el_status"] in ["NOT_EL", "EL_ACTIVE", "EL_EXITED"]
    assert data["hs_transcript_status"] in ["NONE", "SELF_REPORTED", "VERIFIED"]
    if data.get("hs_gpa") is not None:
        assert 0.00 <= float(data["hs_gpa"]) <= 4.50
    if data.get("self_guided_pathway") is not None:
        assert data["self_guided_pathway"] in ["STEM", "BSTEM", "NON_STEM"]
    assert data["placement_status"] in ["UNPLACED", "PROVISIONAL", "FINAL"]
    assert isinstance(data["advising_hold"], bool)
    assert_retake_budget_invariant(data)


def assert_course(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["course_code"], str) and 2 <= len(data["course_code"]) <= 16
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["subject_area"] in ["MATH", "ENGLISH", "ESL", "OTHER"]
    assert 1 <= data["level_rank"] <= 100
    assert 0.5 <= float(data["units"]) <= 6.0
    assert isinstance(data["is_support_course"], bool)
    assert isinstance(data["transfer_level"], bool)
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert data["enrolled_count"] >= 0
    assert data["success_count"] >= 0


def assert_course_requisite(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["requisite_course_id"])
    assert data["requisite_type"] in ["PREREQUISITE", "COREQUISITE", "ADVISORY"]
    assert data["min_grade"] in ["A", "B", "C", "P"]
    assert data["enforcement"] in ["BLOCKING", "WARNING"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_placement_rule(data: dict) -> None:
    assert_common_fields(data)
    assert data["subject_area"] in ["MATH", "ENGLISH", "ESL"]
    assert data["measure_type"] in ["TRANSCRIPT_GPA", "TEST_SCORE", "SELF_GUIDED"]
    assert is_valid_uuid(data["target_course_id"])
    assert isinstance(data["coreq_required"], bool)
    assert 1 <= data["priority_rank"] <= 999
    assert is_iso8601_timestamp(data["effective_from"])
    assert isinstance(data["version_label"], str) and len(data["version_label"]) > 0
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED"]


def assert_test_administration(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["room_code"], str) and len(data["room_code"]) > 0
    assert data["subject_area"] in ["MATH", "ENGLISH", "ESL"]
    assert isinstance(data["proctor_user_id"], str) and len(data["proctor_user_id"]) > 0
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert 1 <= data["seat_capacity"] <= 200
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert data["duration_minutes"] <= THRESHOLDS["MAX_SESSION_MINUTES"]
    assert data["seats_booked"] >= 0
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED", "CANCELLED"]


def assert_test_attempt(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["administration_id"])
    assert data["subject_area"] in ["MATH", "ENGLISH", "ESL"]
    assert data["state"] in ["BOOKED", "CHECKED_IN", "SCORED", "VOIDED", "NO_SHOW"]
    assert isinstance(data["irregularity_flag"], bool)
    if data.get("raw_score") is not None:
        assert 0 <= data["raw_score"] <= 160
    if data.get("scaled_score") is not None:
        assert 0 <= data["scaled_score"] <= 1000
    if data.get("void_reason") is not None:
        assert data["void_reason"] in ["IRREGULARITY", "PROCTOR_ERROR", "ADMIN_CORRECTION"]


def assert_placement_determination(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["subject_area"] in ["MATH", "ENGLISH", "ESL"]
    assert data["measure_type_used"] in [
        "TRANSCRIPT_GPA",
        "TEST_SCORE",
        "SELF_GUIDED",
        "APPEAL_OVERRIDE",
    ]
    assert is_valid_uuid(data["placed_course_id"])
    assert data["validity_days"] in [180, 365, 730]
    assert is_iso8601_timestamp(data["expires_at"])
    assert is_iso8601_timestamp(data["determined_at"])
    assert 0.0 <= float(data["base_confidence_score"]) <= 100.0
    assert 0.0 <= float(data["staleness_penalty"]) <= THRESHOLDS["STALENESS_CAP"]
    assert 0.0 <= float(data["confidence_score"]) <= 100.0
    assert data["placement_state"] in ["PROVISIONAL", "FINAL", "APPEALED", "SUPERSEDED"]
    assert data["evidence_state"] in ["UNVERIFIED", "VERIFIED", "DISPUTED"]
    if data["measure_type_used"] == "APPEAL_OVERRIDE":
        assert data["applied_rule_id"] is None, (
            "applied_rule_id is null exactly when the determination was minted "
            "by a granted appeal"
        )


def assert_placement_appeal(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["determination_id"])
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["requested_course_id"])
    assert data["grounds"] in ["NEW_TRANSCRIPT", "TEST_IRREGULARITY", "EL_PATHWAY", "OTHER"]
    assert isinstance(data["statement"], str) and 1 <= len(data["statement"]) <= 2000
    assert 0 <= data["revision_round"] <= THRESHOLDS["APPEAL_ROUND_LIMIT"]
    assert is_iso8601_timestamp(data["filed_at"])
    assert data["state"] in [
        "SUBMITTED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "INSTRUCTOR_ENDORSED",
        "GRANTED",
        "DENIED",
        "WITHDRAWN",
    ]


def assert_section(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["course_id"])
    assert isinstance(data["term_code"], str) and 5 <= len(data["term_code"]) <= 10
    assert isinstance(data["room_code"], str) and len(data["room_code"]) > 0
    assert is_iso8601_timestamp(data["meets_start_at"])
    assert is_iso8601_timestamp(data["meets_end_at"])
    assert 1 <= data["seat_capacity"] <= 300
    assert data["status"] in ["PLANNED", "OPEN", "CLOSED", "CANCELLED"]
    assert data["pairing_state"] in ["UNPAIRED", "PAIRED", "PAIR_BROKEN"]
    assert data["role_in_pair"] in ["NONE", "PRIMARY", "SUPPORT"]
    assert_section_seat_counters(data)


def assert_registration(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["section_id"])
    assert data["prerequisite_status"] in ["SATISFIED", "OVERRIDDEN", "UNMET"]
    assert data["state"] in [
        "PENDING",
        "ENROLLED",
        "WAITLISTED",
        "DENIED",
        "DROPPED",
        "COMPLETED",
    ]
    assert isinstance(data["success"], bool)
    if data.get("final_grade") is not None:
        assert data["final_grade"] in ["A", "B", "C", "D", "F", "P", "NP", "W"]
    if data.get("denial_reason") is not None:
        assert data["denial_reason"] in [
            "PLACEMENT_SUPERSEDED",
            "EVIDENCE_DISPUTED",
            "SECTION_CANCELLED",
        ]
    if data.get("term_units_at_confirm") is not None:
        assert 0.0 <= float(data["term_units_at_confirm"]) <= THRESHOLDS["MAX_TERM_UNITS"]


def assert_prerequisite_override(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["requisite_id"])
    assert isinstance(data["justification"], str) and 10 <= len(data["justification"]) <= 1000
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["issued_by_user_id"], str) and len(data["issued_by_user_id"]) > 0
    assert data["state"] in ["ISSUED", "CONSUMED", "REVOKED", "EXPIRED"]
    assert_override_redemption_invariant(data)


def assert_validation_study(data: dict) -> None:
    assert_common_fields(data)
    assert data["subject_area"] in ["MATH", "ENGLISH", "ESL"]
    assert is_valid_uuid(data["candidate_rule_id"])
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert data["strict_cohort_size"] >= 0
    assert data["strict_success_count"] >= 0
    assert data["inclusive_cohort_size"] >= 0
    assert data["inclusive_success_count"] >= 0
    assert data["run_count"] >= 0
    assert data["state"] in [
        "DRAFT",
        "RUNNING",
        "COMPLETED",
        "APPROVED",
        "REJECTED",
        "WITHDRAWN",
    ]
    assert isinstance(data["proposed_by_user_id"], str)


# --------------------------------------------------------------------------- #
# Conserved-quantity invariants (PRD §2.12)
# --------------------------------------------------------------------------- #
def assert_section_seat_counters(section: dict) -> None:
    """`seats_taken` never exceeds `seat_capacity`, and every seat counter is a
    non-negative integer that floors at zero."""
    assert section["seats_taken"] >= 0, "seats_taken floors at zero"
    assert section["seats_held"] >= 0, "seats_held floors at zero"
    assert section["waitlist_count"] >= 0, "waitlist_count floors at zero"
    assert section["available_seats"] >= 0, "available_seats floors at zero"
    assert (
        section["seats_taken"] <= section["seat_capacity"]
    ), "seats_taken never exceeds seat_capacity"


def assert_section_seat_ledger(section: dict, registrations: list) -> None:
    """The sum of `seats_taken`, `seats_held` and `waitlist_count` plus the
    number of `DENIED`/`DROPPED` registrations equals the total number of
    registrations attached to the section; `seats_taken` equals the number in
    `ENROLLED` or `COMPLETED`."""
    assert_section_seat_counters(section)
    enrolled = [r for r in registrations if r["state"] in ("ENROLLED", "COMPLETED")]
    pending = [r for r in registrations if r["state"] == "PENDING"]
    waitlisted = [r for r in registrations if r["state"] == "WAITLISTED"]
    closed = [r for r in registrations if r["state"] in ("DENIED", "DROPPED")]
    assert section["seats_taken"] == len(enrolled), (
        f"seats_taken {section['seats_taken']} must equal the number of ENROLLED or "
        f"COMPLETED registrations {len(enrolled)}"
    )
    assert section["seats_held"] == len(pending)
    assert section["waitlist_count"] == len(waitlisted)
    total = (
        section["seats_taken"]
        + section["seats_held"]
        + section["waitlist_count"]
        + len(closed)
    )
    assert total == len(registrations), (
        f"seat ledger total {total} must equal the number of registrations "
        f"{len(registrations)} attached to the section"
    )


def assert_retake_budget_invariant(student: dict) -> None:
    """For every student and subject pair, `attempt_counts` plus
    `remaining_attempts` for that subject always equals three."""
    counts = student["attempt_counts"]
    remaining = student["remaining_attempts"]
    for subject in ("MATH", "ENGLISH", "ESL"):
        assert subject in counts, f"attempt_counts must carry {subject}"
        assert subject in remaining, f"remaining_attempts must carry {subject}"
        assert counts[subject] >= 0
        assert remaining[subject] >= 0
        assert (
            counts[subject] + remaining[subject]
            == THRESHOLDS["MAX_ATTEMPTS_PER_SUBJECT"]
        ), (
            f"attempt_counts + remaining_attempts for {subject} must equal "
            f"{THRESHOLDS['MAX_ATTEMPTS_PER_SUBJECT']}, got "
            f"{counts[subject]} + {remaining[subject]}"
        )


def assert_override_redemption_invariant(override: dict) -> None:
    """For every override in state `ISSUED`, `consumed_by_registration_id` is
    null."""
    if override["state"] == "ISSUED":
        assert override["consumed_by_registration_id"] is None, (
            "an ISSUED override must carry a null consumed_by_registration_id, got "
            f"{override['consumed_by_registration_id']!r}"
        )
    if override["state"] == "CONSUMED":
        assert override["consumed_by_registration_id"] is not None, (
            "a CONSUMED override must name the registration that consumed it"
        )
