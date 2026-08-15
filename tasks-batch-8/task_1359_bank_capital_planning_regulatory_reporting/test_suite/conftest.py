"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]


@pytest.fixture
def capital_analyst_headers():
    return TEST_USERS["capital_analyst_headers"]


@pytest.fixture
def regulator_reviewer_headers():
    return TEST_USERS["regulator_reviewer_headers"]


@pytest.fixture
def board_approver_headers():
    return TEST_USERS["board_approver_headers"]


@pytest.fixture
def external_auditor_headers():
    return TEST_USERS["external_auditor_headers"]
