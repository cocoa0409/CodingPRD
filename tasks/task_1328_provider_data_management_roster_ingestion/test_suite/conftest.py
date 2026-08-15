"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def data_steward_headers():
    return TEST_USERS["data_steward_headers"]


@pytest.fixture
def intake_operator_headers():
    return TEST_USERS["intake_operator_headers"]


@pytest.fixture
def intake_operator_2_headers():
    return TEST_USERS["intake_operator_2_headers"]


@pytest.fixture
def distribution_operator_headers():
    return TEST_USERS["distribution_operator_headers"]


@pytest.fixture
def provider_contact_headers():
    return TEST_USERS["provider_contact_headers"]
