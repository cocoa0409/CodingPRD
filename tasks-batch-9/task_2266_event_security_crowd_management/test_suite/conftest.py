"""Pytest fixtures exposing the Event Security & Crowd Management helpers.

The runner puts the task directory on ``PYTHONPATH``, so ``test_helpers`` is
importable without path juggling. It also restarts the service before every
individual test, which means each test starts against an empty database and
builds whatever state it needs through the declared endpoints.
"""

import pytest

from test_helpers import (
    ANALYST_2_HEADERS,
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    COMMANDER_2_HEADERS,
    COMMANDER_HEADERS,
    COORDINATOR_2_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_2_HEADERS,
    DIRECTOR_HEADERS,
    NO_AUTH_HEADERS,
    OPERATOR_HEADERS,
    ApiClient,
)


@pytest.fixture()
def api() -> ApiClient:
    """Client pointed at the service under test."""
    return ApiClient()


@pytest.fixture()
def director_headers():
    return DIRECTOR_HEADERS


@pytest.fixture()
def second_director_headers():
    return DIRECTOR_2_HEADERS


@pytest.fixture()
def analyst_headers():
    return ANALYST_HEADERS


@pytest.fixture()
def second_analyst_headers():
    return ANALYST_2_HEADERS


@pytest.fixture()
def coordinator_headers():
    return COORDINATOR_HEADERS


@pytest.fixture()
def second_coordinator_headers():
    return COORDINATOR_2_HEADERS


@pytest.fixture()
def auditor_headers():
    return AUDITOR_HEADERS


@pytest.fixture()
def commander_headers():
    return COMMANDER_HEADERS


@pytest.fixture()
def second_commander_headers():
    return COMMANDER_2_HEADERS


@pytest.fixture()
def operator_headers():
    return OPERATOR_HEADERS


@pytest.fixture()
def no_auth_headers():
    return NO_AUTH_HEADERS
