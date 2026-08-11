"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    CMRA_OPERATOR,
    COMPLIANCE_OFFICER,
    NOTARY,
    PLATFORM_ADMIN,
    SECOND_COMPLIANCE_OFFICER,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin():
    return PLATFORM_ADMIN


@pytest.fixture
def cmra_operator():
    return CMRA_OPERATOR


@pytest.fixture
def compliance_officer():
    return COMPLIANCE_OFFICER


@pytest.fixture
def second_compliance_officer():
    return SECOND_COMPLIANCE_OFFICER


@pytest.fixture
def notary():
    return NOTARY


@pytest.fixture
def box_holder_fallback():
    """Shared BoxHolder headers; only for calls that do not exercise ownership."""
    return TEST_USERS["box_holder_headers"]


@pytest.fixture
def recipient_fallback():
    """Shared Recipient headers; only for calls that do not exercise ownership."""
    return TEST_USERS["recipient_headers"]
