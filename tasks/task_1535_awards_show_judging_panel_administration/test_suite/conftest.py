"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def vendor_headers():
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def entrant_headers():
    # Entrant is entity-backed (PRD §2.1): usable only for calls that are not
    # ownership-gated. Ownership-gated calls build per-instance headers.
    return TEST_USERS["entrant_headers"]


@pytest.fixture
def judge_headers():
    # Judge is entity-backed (PRD §2.1): usable only for calls that are not
    # ownership-gated. Ownership-gated calls build per-instance headers.
    return TEST_USERS["judge_headers"]
