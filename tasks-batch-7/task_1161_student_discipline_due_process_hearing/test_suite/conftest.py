"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def school_referrer_headers():
    return TEST_USERS["school_referrer_headers"]


@pytest.fixture
def school_classifier_headers():
    return TEST_USERS["school_classifier_headers"]


@pytest.fixture
def hearing_officer_headers():
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def parent_guardian_headers():
    return TEST_USERS["parent_guardian_headers"]


@pytest.fixture
def student_services_headers():
    return TEST_USERS["student_services_headers"]
