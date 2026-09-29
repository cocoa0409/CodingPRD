"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture(scope="session")
def warranty_admin_headers() -> dict:
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture(scope="session")
def claim_adjudicator_headers() -> dict:
    return TEST_USERS["claim_adjudicator_headers"]


@pytest.fixture(scope="session")
def claim_adjudicator_alt_headers() -> dict:
    return TEST_USERS["claim_adjudicator_alt_headers"]


@pytest.fixture(scope="session")
def adjudication_manager_headers() -> dict:
    return TEST_USERS["adjudication_manager_headers"]


@pytest.fixture(scope="session")
def field_auditor_headers() -> dict:
    return TEST_USERS["field_auditor_headers"]


@pytest.fixture(scope="session")
def audit_manager_headers() -> dict:
    return TEST_USERS["audit_manager_headers"]


@pytest.fixture(scope="session")
def appeal_reviewer_headers() -> dict:
    return TEST_USERS["appeal_reviewer_headers"]


@pytest.fixture(scope="session")
def dealer_warranty_admin_headers() -> dict:
    return TEST_USERS["dealer_warranty_admin_headers"]
