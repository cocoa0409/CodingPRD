"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL into the environment and adds the project
root to PYTHONPATH before invoking pytest, so test_helpers imports cleanly.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


# ─── One thin fixture per opaque role from TEST_USERS ───


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["coach_headers"]


@pytest.fixture
def nil_reviewer_headers():
    return TEST_USERS["nil_reviewer_headers"]


@pytest.fixture
def eligibility_center_headers():
    return TEST_USERS["eligibility_center_headers"]


@pytest.fixture
def student_athlete_headers_fallback():
    """Fallback StudentAthlete headers; safe only for tests where the
    rejection IS "not the owner". Most StudentAthlete-role tests should
    use `make_student_athlete_headers(athlete_id)` from test_helpers."""
    return TEST_USERS["student_athlete_headers"]
