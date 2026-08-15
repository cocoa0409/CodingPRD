"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def state_agency_headers():
    return TEST_USERS["state_agency_headers"]


@pytest.fixture
def mco_encounter_ops_headers():
    return TEST_USERS["mco_encounter_ops_headers"]


@pytest.fixture
def mco_compliance_headers():
    return TEST_USERS["mco_compliance_headers"]


@pytest.fixture
def mco_finance_headers():
    return TEST_USERS["mco_finance_headers"]


@pytest.fixture
def delegated_submitter_headers():
    return TEST_USERS["delegated_submitter_headers"]
