"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL into the environment and adds the project root
to PYTHONPATH before invoking pytest, so test_helpers imports cleanly.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


# One fixture per role from TEST_USERS — kept thin; complex role builders live
# in test_helpers.test_users.

@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def servicer_alt_headers():
    return TEST_USERS["servicer_alt_headers"]


@pytest.fixture
def pslf_adjudicator_headers():
    return TEST_USERS["pslf_adjudicator_headers"]


@pytest.fixture
def pslf_adjudicator_alt_headers():
    return TEST_USERS["pslf_adjudicator_alt_headers"]


@pytest.fixture
def va_officer_headers():
    return TEST_USERS["va_officer_headers"]


@pytest.fixture
def borrower_headers_fallback():
    """Fallback Borrower-role headers for tests where the rejection is
    "not the owner" / "no such borrower" and the literal X-User-ID doesn't
    need to match any real entity."""
    return TEST_USERS["borrower_headers"]
