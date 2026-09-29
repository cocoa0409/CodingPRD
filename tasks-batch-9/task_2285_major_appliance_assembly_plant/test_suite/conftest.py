"""Shared pytest fixtures for the assembly plant test suite.

The server is restarted with an empty database before every individual test, so
each test builds the whole plant it needs from scratch through public endpoints.
"""

import pytest

from test_helpers import (
    ENGINEERING_LEAD_HEADERS,
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    PRODUCTION_PLANNER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
    TEST_USERS,
    WARRANTY_ANALYST_HEADERS,
    api_client,
)


@pytest.fixture()
def api():
    """The typed HTTP client, one method per documented endpoint.

    ``api_client`` is a module-level singleton, so its ``requests.Session``
    outlives the per-test server restart the runner performs before this
    fixture is evaluated.  Any keep-alive socket still pooled from the previous
    test points at a process that has since been SIGKILLed, and reusing it
    surfaces as ``ConnectionResetError`` on the first call of the new test.
    Dropping the pools here costs one TCP handshake and removes that race;
    ``requests`` rebuilds them lazily on the next call.
    """
    api_client.session.close()
    return api_client


@pytest.fixture()
def users():
    """Header sets for the six plant-internal roles, keyed by role name."""
    return TEST_USERS


@pytest.fixture()
def admin():
    return PLANT_ADMIN_HEADERS


@pytest.fixture()
def planner():
    return PRODUCTION_PLANNER_HEADERS


@pytest.fixture()
def operator():
    return LINE_OPERATOR_HEADERS


@pytest.fixture()
def inspector():
    return QUALITY_INSPECTOR_HEADERS


@pytest.fixture()
def engineer():
    return ENGINEERING_LEAD_HEADERS


@pytest.fixture()
def analyst():
    return WARRANTY_ANALYST_HEADERS
