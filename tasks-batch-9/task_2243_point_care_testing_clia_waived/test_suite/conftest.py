"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """`ProgramAdmin` headers; the identifier is opaque (PRD 2.1)."""
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def coordinator_headers():
    """`QualityCoordinator` headers; the identifier is opaque (PRD 2.1)."""
    return TEST_USERS["quality_coordinator_headers"]


@pytest.fixture
def surveyor_headers():
    """`Surveyor` headers for the issuing surveyor."""
    return TEST_USERS["surveyor_headers"]


@pytest.fixture
def surveyor_beta_headers():
    """A second `Surveyor` identity, for duty-separation scenarios (PRD 2.8)."""
    return TEST_USERS["surveyor_beta_headers"]
