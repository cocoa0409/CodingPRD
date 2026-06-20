"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def care_assessor_headers():
    return TEST_USERS["care_assessor_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]
