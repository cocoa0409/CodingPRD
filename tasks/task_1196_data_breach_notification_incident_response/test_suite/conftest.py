"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def incident_commander_headers():
    return TEST_USERS["incident_commander_headers"]


@pytest.fixture
def forensic_lead_headers():
    return TEST_USERS["forensic_lead_headers"]


@pytest.fixture
def privacy_counsel_headers():
    return TEST_USERS["privacy_counsel_headers"]


@pytest.fixture
def general_counsel_headers():
    return TEST_USERS["general_counsel_headers"]


@pytest.fixture
def data_analyst_headers():
    return TEST_USERS["data_analyst_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def affected_subject_headers():
    return TEST_USERS["affected_subject_headers"]
