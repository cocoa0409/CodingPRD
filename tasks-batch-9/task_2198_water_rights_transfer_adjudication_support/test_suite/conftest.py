"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def claimant_headers():
    """PRD §2.1 — the `Claimant` role. Ownership-gated calls need the real
    `Claimant.id`, so use `make_claimant_headers()` for those."""
    return TEST_USERS["claimant_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_alt_headers():
    return TEST_USERS["analyst_alt_headers"]


@pytest.fixture
def hearing_officer_headers():
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def hearing_officer_alt_headers():
    return TEST_USERS["hearing_officer_alt_headers"]


@pytest.fixture
def decision_authority_headers():
    return TEST_USERS["decision_authority_headers"]


@pytest.fixture
def decision_authority_alt_headers():
    return TEST_USERS["decision_authority_alt_headers"]


@pytest.fixture
def basin_adjudicator_headers():
    return TEST_USERS["basin_adjudicator_headers"]
