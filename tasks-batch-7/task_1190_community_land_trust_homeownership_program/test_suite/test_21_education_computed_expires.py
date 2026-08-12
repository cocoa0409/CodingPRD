"""EducationCompletion computed expires_at field."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_education_completion_payload,
    create_education_course_payload,
    get_success_data,
    setup_household,
    setup_program,
)


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _pga():
    return TEST_USERS["program_admin_headers"]


def test_education_completion_expires_at_computed_from_validity():
    """PRD §3.2: "The completion's `expires_at` is computed as `completed_at`
    plus the course's `validity_months`."

    Design: Corner/entities/education_completion_expires_at_computed_from_validity
    """
    prog = setup_program(name="P-EXP")
    hh = setup_household(prog["id"])
    course = get_success_data(
        api_client.create_education_course(
            prog["id"],
            create_education_course_payload(validity_months=12),
            _pga(),
        )
    )
    comp = get_success_data(
        api_client.create_education_completion(
            prog["id"],
            hh["id"],
            create_education_completion_payload(
                course_id=course["id"],
                completed_at="2026-01-15T00:00:00Z",
                score_pct=0.9,
            ),
            _is(),
        )
    )
    # 2026-01-15 + 12 months = 2027-01-15
    assert comp["expires_at"].startswith("2027-01-15"), (
        f"Expected expires_at on 2027-01-15, got {comp['expires_at']}"
    )
