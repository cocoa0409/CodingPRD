"""Pytest fixtures exposing test_helpers infrastructure for the SNF-MDS suite."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def administrator_headers():
    return TEST_USERS["administrator_headers"]


@pytest.fixture
def admissions_coordinator_headers():
    return TEST_USERS["admissions_coordinator_headers"]


@pytest.fixture
def mds_coordinator_headers():
    return TEST_USERS["mds_coordinator_headers"]


@pytest.fixture
def therapist_headers():
    return TEST_USERS["therapist_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def billing_analyst_headers():
    return TEST_USERS["billing_analyst_headers"]
