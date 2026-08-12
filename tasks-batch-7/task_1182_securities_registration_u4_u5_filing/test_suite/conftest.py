"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed externally; tests assume the API is reachable.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (server lifecycle owned by the runner)."""
    return api_client


@pytest.fixture
def registration_principal_headers():
    return TEST_USERS["registration_principal_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def finance_clerk_headers():
    return TEST_USERS["finance_clerk_headers"]


@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]
