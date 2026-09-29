"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers():
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def review_manager_headers():
    return TEST_USERS["review_manager_headers"]


@pytest.fixture
def second_review_manager_headers():
    return TEST_USERS["second_review_manager_headers"]


@pytest.fixture
def manual_reviewer_headers():
    return TEST_USERS["manual_reviewer_headers"]


@pytest.fixture
def second_manual_reviewer_headers():
    return TEST_USERS["second_manual_reviewer_headers"]


@pytest.fixture
def inclusion_reviewer_headers():
    return TEST_USERS["inclusion_reviewer_headers"]


@pytest.fixture
def client_integrator_headers():
    """Fallback ClientIntegrator identity.

    Only safe where the request is expected to fail before any ownership
    comparison; ownership-gated calls build headers from the acting client's id.
    """
    return TEST_USERS["client_integrator_headers"]
