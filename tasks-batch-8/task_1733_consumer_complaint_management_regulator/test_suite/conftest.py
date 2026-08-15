"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def intake_specialist_headers():
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def case_handler_headers():
    return TEST_USERS["case_handler_headers"]


@pytest.fixture
def qa_reviewer_headers():
    return TEST_USERS["qa_reviewer_headers"]


@pytest.fixture
def remediation_approver_headers():
    return TEST_USERS["remediation_approver_headers"]


@pytest.fixture
def executive_reviewer_headers():
    return TEST_USERS["executive_reviewer_headers"]


@pytest.fixture
def complaint_manager_headers():
    return TEST_USERS["complaint_manager_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
