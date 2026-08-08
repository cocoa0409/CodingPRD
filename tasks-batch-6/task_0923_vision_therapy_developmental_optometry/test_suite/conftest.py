"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_billing_specialist_headers,
    make_clinic_admin_headers,
    make_front_desk_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def clinic_admin_headers():
    return make_clinic_admin_headers()


@pytest.fixture
def front_desk_headers():
    return make_front_desk_headers()


@pytest.fixture
def billing_specialist_headers():
    return make_billing_specialist_headers()


@pytest.fixture
def optometrist_headers():
    return TEST_USERS["optometrist_headers"]


@pytest.fixture
def vision_therapist_headers():
    return TEST_USERS["vision_therapist_headers"]


@pytest.fixture
def therapy_assistant_headers():
    return TEST_USERS["therapy_assistant_headers"]


@pytest.fixture
def patient_user_headers():
    return TEST_USERS["patient_user_headers"]
