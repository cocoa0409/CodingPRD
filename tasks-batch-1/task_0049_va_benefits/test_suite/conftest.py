"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every pytest test, so every test begins
against an empty database and constructs its own preconditions via test_helpers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """ClaimsAdmin headers (opaque role)."""
    return TEST_USERS["claims_admin_headers"]


@pytest.fixture
def rater_headers():
    """RatingSpecialist headers (opaque role)."""
    return TEST_USERS["rating_specialist_headers"]


@pytest.fixture
def sco_headers():
    """SchoolCertifyingOfficial headers (opaque role)."""
    return TEST_USERS["school_official_headers"]


@pytest.fixture
def veteran_fallback_headers():
    """Veteran headers with a placeholder X-User-ID.

    Only safe for tests that do not exercise ownership. Ownership-gated Veteran
    calls must use make_veteran_headers(veteran_id) with the real Veteran.id.
    """
    return TEST_USERS["veteran_headers"]
