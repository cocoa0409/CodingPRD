"""Shared fixtures for the deposit-insurance resolution suite.

The server lifecycle belongs to the runner: it is relaunched before each test, so
every test starts against an empty database, with the logical clock reading
`2026-08-01T00:00:00Z`, and builds only the rows it needs.
"""
import pytest
from test_helpers import ApiClient, api_client
from test_helpers import fixtures as X
from test_helpers.test_users import (
    CLAIMS_AGENT,
    CLAIMS_CERTIFIER,
    CLOSING_MANAGER,
    RECEIVERSHIP_TRUSTEE,
    RESOLUTION_ANALYST,
)


@pytest.fixture(scope="session")
def client() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def closing_manager():
    """Headers for a `ClosingManager` operator (opaque identifier)."""
    return CLOSING_MANAGER


@pytest.fixture
def claims_agent():
    """Headers for a `ClaimsAgent` operator, recorded as `prepared_by_user_id`."""
    return CLAIMS_AGENT


@pytest.fixture
def claims_certifier():
    """Headers for a `ClaimsCertifier` operator, recorded as `certified_by_user_id`."""
    return CLAIMS_CERTIFIER


@pytest.fixture
def resolution_analyst():
    """Headers for a `ResolutionAnalyst` operator (opaque identifier)."""
    return RESOLUTION_ANALYST


@pytest.fixture
def receivership_trustee():
    """Headers for a `ReceivershipTrustee` operator (opaque identifier)."""
    return RECEIVERSHIP_TRUSTEE


@pytest.fixture
def pooled_estate(client):
    """A closed estate holding the PRD's worked two-account depositor."""
    return X.pooled_estate(client)


@pytest.fixture
def certified_estate(client):
    """That same estate carried through certification."""
    return X.certified_pooled_estate(client)
