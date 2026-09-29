"""Suite-wide wiring.

The runner restarts the API server before each test, so no cleanup fixture is
needed: every test observes a freshly empty database and builds the state it
needs through the endpoints the PRD declares.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import *  # noqa: F401,F403,E402
from test_helpers import TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api():
    """The shared HTTP client aimed at ``API_BASE_URL``."""
    return api_client


@pytest.fixture
def admin():
    return TEST_USERS["admin"]


@pytest.fixture
def registrar():
    return TEST_USERS["registrar"]


@pytest.fixture
def analyst():
    return TEST_USERS["analyst"]


@pytest.fixture
def analyst_2():
    return TEST_USERS["analyst_2"]


@pytest.fixture
def liaison():
    return TEST_USERS["liaison"]


@pytest.fixture
def liaison_2():
    return TEST_USERS["liaison_2"]


@pytest.fixture
def reviewer():
    return TEST_USERS["reviewer"]
