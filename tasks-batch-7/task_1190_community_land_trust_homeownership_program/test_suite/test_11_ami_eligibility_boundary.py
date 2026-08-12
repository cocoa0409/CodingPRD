"""AMI eligibility inclusive boundary — ami_pct == max_eligibility_ami_pct passes."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_household_payload,
    create_income_certification_payload,
    create_program_payload,
    get_success_data,
)


def _pa():
    return TEST_USERS["platform_admin_headers"]


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _co():
    return TEST_USERS["compliance_officer_headers"]


def _pga():
    return TEST_USERS["program_admin_headers"]


def _setup_household_at_ami(prog_id: str, income_cents: int, legal_name: str):
    """Create household + cert approved; returns household dict after approval."""
    hh = get_success_data(
        api_client.create_household(
            prog_id,
            create_household_payload(
                legal_name=legal_name,
                household_size=4,
                annual_gross_income_cents=income_cents,
            ),
            _is(),
        )
    )
    # Add required course + completion so eligibility gate is AMI-driven only.
    course = get_success_data(
        api_client.create_education_course(
            prog_id,
            {
                "code": f"C-{legal_name.replace(' ', '')}",
                "title": "Basics",
                "credit_hours": 8,
                "is_required": True,
                "validity_months": 24,
            },
            _pga(),
        )
    )
    get_success_data(
        api_client.create_education_completion(
            prog_id,
            hh["id"],
            {
                "course_id": course["id"],
                "completed_at": "2026-04-01T00:00:00Z",
                "score_pct": 0.9,
            },
            _is(),
        )
    )
    cert = get_success_data(
        api_client.create_income_certification(
            prog_id,
            hh["id"],
            create_income_certification_payload(
                reported_annual_income_cents=income_cents,
                verified_annual_income_cents=income_cents,
                household_size_at_cert=4,
            ),
            _is(),
        )
    )
    get_success_data(
        api_client.start_review_income_certification(prog_id, hh["id"], cert["id"], _co())
    )
    get_success_data(
        api_client.approve_income_certification(prog_id, hh["id"], cert["id"], _co())
    )
    return get_success_data(api_client.get_household(prog_id, hh["id"], _co()))


def test_ami_at_080_inclusive_boundary_remains_eligible():
    """PRD §3.2: "If the household's AMI fraction exceeds the program's
    `max_eligibility_ami_pct`, the household transitions to `INELIGIBLE`
    (whether it was `PENDING` or `ELIGIBLE`); boundary-inclusive, exactly
    `0.80` against a `0.80` ceiling remains `ELIGIBLE`."

    Design: Difficulty/boundary_precision_check/ami_pct_max_eligibility_inclusive_boundary
    """
    prog = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-BND1",
                max_eligibility_ami_pct=0.80,
                area_median_income_cents=10_000_000,
            ),
            _pa(),
        )
    )
    # ami = 8_000_000 / (10_000_000 * 1.00) = 0.8000 — exactly at the ceiling.
    hh = _setup_household_at_ami(prog["id"], 8_000_000, "H At")
    assert hh["ami_pct"] == pytest.approx(0.8000, abs=1e-9)
    assert hh["eligibility_status"] == "ELIGIBLE"


def test_ami_at_08001_above_boundary_transitions_to_ineligible():
    """PRD §3.2: "If the household's AMI fraction exceeds the program's
    `max_eligibility_ami_pct`, the household transitions to `INELIGIBLE`
    (whether it was `PENDING` or `ELIGIBLE`); boundary-inclusive, exactly
    `0.80` against a `0.80` ceiling remains `ELIGIBLE`."

    Design: Difficulty/boundary_precision_check/ami_pct_max_eligibility_inclusive_boundary
    """
    prog = get_success_data(
        api_client.create_program(
            create_program_payload(
                name="P-BND2",
                max_eligibility_ami_pct=0.80,
                area_median_income_cents=10_000_000,
            ),
            _pa(),
        )
    )
    # ami = 8_001_000 / (10_000_000 * 1.00) = 0.8001 — just above the ceiling.
    hh = _setup_household_at_ami(prog["id"], 8_001_000, "H Over")
    assert hh["ami_pct"] == pytest.approx(0.8001, abs=1e-9)
    assert hh["eligibility_status"] == "INELIGIBLE"
