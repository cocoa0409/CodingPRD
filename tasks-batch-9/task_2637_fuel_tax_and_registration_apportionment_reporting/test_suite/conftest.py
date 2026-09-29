"""Shared pytest fixtures for the apportionment test suite."""
import os
import sys

import pytest

# The helper package lives beside this directory.
_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.api_client import ApportionmentClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ANALYST_1_HEADERS,
    ANALYST_2_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
    PREPARER_2_HEADERS,
)


@pytest.fixture
def client():
    """A client pointed at the server under test.

    The database is empty at the start of every test, so each test builds the
    preconditions it needs through the published write endpoints.
    """
    return ApportionmentClient()


@pytest.fixture
def officer_headers():
    return OFFICER_1_HEADERS


@pytest.fixture
def second_officer_headers():
    return OFFICER_2_HEADERS


@pytest.fixture
def analyst_headers():
    return ANALYST_1_HEADERS


@pytest.fixture
def second_analyst_headers():
    return ANALYST_2_HEADERS


@pytest.fixture
def preparer_headers():
    return PREPARER_1_HEADERS


@pytest.fixture
def second_preparer_headers():
    return PREPARER_2_HEADERS
