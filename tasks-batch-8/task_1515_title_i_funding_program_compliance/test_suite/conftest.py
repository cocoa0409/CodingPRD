"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture(autouse=True)
def _drop_stale_connections():
    """Per-test-server isolation SIGKILLs and respawns the API server on the
    same port before every test. Closing the shared session's connection pool
    guarantees no test reuses a stale keep-alive socket bound to the killed
    process (which surfaces as 'Connection reset by peer' /
    'Remote end closed connection without response')."""
    api_client.session.close()
    yield


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def monitor_headers():
    return TEST_USERS["monitor_headers"]


@pytest.fixture
def ombudsman_headers():
    return TEST_USERS["ombudsman_headers"]
