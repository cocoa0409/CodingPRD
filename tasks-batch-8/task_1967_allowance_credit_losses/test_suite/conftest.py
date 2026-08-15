"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def credit_analyst_headers():
    return TEST_USERS["credit_analyst_headers"]


@pytest.fixture
def model_validator_headers():
    return TEST_USERS["model_validator_headers"]


@pytest.fixture
def chief_credit_officer_headers():
    return TEST_USERS["chief_credit_officer_headers"]


@pytest.fixture
def external_auditor_headers():
    return TEST_USERS["external_auditor_headers"]
