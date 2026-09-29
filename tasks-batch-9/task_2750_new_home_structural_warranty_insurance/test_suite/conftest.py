"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def underwriting_officer_headers():
    return TEST_USERS["underwriting_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def second_claims_adjuster_headers():
    return TEST_USERS["second_claims_adjuster_headers"]


@pytest.fixture
def third_claims_adjuster_headers():
    return TEST_USERS["third_claims_adjuster_headers"]


@pytest.fixture
def builder_principal_headers():
    """Fallback BuilderPrincipal identity. Ownership-gated calls must instead
    use make_builder_principal_headers(builder["id"])."""
    return TEST_USERS["builder_principal_headers"]


@pytest.fixture
def homeowner_headers():
    """Fallback Homeowner identity. Ownership-gated calls must instead use
    make_homeowner_headers(homeowner["id"])."""
    return TEST_USERS["homeowner_headers"]
