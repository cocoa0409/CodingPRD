"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    AHJ_ALT_HEADERS,
    AHJ_HEADERS,
    CX_AGENT_HEADERS,
    CX_WITNESS_HEADERS,
    ENGINEER_HEADERS,
    ENGINEER_REVIEWER_HEADERS,
    LANDLORD_HEADERS,
    LANDLORD_NEGOTIATOR_HEADERS,
    LANDLORD_OPS_HEADERS,
    LANDLORD_SIGNER_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def landlord():
    """The asset-management operator who registers and approves base building work."""
    return LANDLORD_HEADERS


@pytest.fixture
def negotiator():
    """A second asset-management operator, used to author negotiation rounds."""
    return LANDLORD_NEGOTIATOR_HEADERS


@pytest.fixture
def signer():
    """A third asset-management operator, used to execute leases."""
    return LANDLORD_SIGNER_HEADERS


@pytest.fixture
def ops():
    """A fourth asset-management operator with no authoring history."""
    return LANDLORD_OPS_HEADERS


@pytest.fixture
def engineer():
    """The engineer of record who measures plates and assesses suitability."""
    return ENGINEER_HEADERS


@pytest.fixture
def reviewer():
    """A second engineer identity, distinct from the engineer of record."""
    return ENGINEER_REVIEWER_HEADERS


@pytest.fixture
def ahj():
    """The permit officer of the authority having jurisdiction."""
    return AHJ_HEADERS


@pytest.fixture
def ahj_alt():
    """A second permit officer identity."""
    return AHJ_ALT_HEADERS


@pytest.fixture
def cx_agent():
    """The independent commissioning agent."""
    return CX_AGENT_HEADERS


@pytest.fixture
def cx_witness():
    """A second commissioning identity, used as an independent witness."""
    return CX_WITNESS_HEADERS
