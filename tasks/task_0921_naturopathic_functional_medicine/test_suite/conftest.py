"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import NO_AUTH_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def nd_headers():
    return TEST_USERS["naturopathic_doctor_headers"]


@pytest.fixture
def coach_headers():
    return TEST_USERS["health_coach_headers"]


@pytest.fixture
def tech_headers():
    return TEST_USERS["dispensary_tech_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["clinical_director_headers"]


@pytest.fixture
def patient_headers():
    return TEST_USERS["patient_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
