"""Shared pytest fixtures for the optical laboratory suite.

The API server is restarted with an empty database before each test, so no
fixture here caches domain state — only the client and the header sets.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_client  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    BENEFITS_A_HEADERS,
    INSPECTOR_A_HEADERS,
    INSPECTOR_B_HEADERS,
    MANAGER_A_HEADERS,
    OPTICIAN_A_HEADERS,
    OPTICIAN_B_HEADERS,
    TECHNICIAN_A_HEADERS,
    TECHNICIAN_B_HEADERS,
)


@pytest.fixture(scope="session")
def api():
    return api_client


@pytest.fixture
def optician():
    return OPTICIAN_A_HEADERS


@pytest.fixture
def optician_b():
    return OPTICIAN_B_HEADERS


@pytest.fixture
def technician():
    return TECHNICIAN_A_HEADERS


@pytest.fixture
def technician_b():
    return TECHNICIAN_B_HEADERS


@pytest.fixture
def inspector():
    return INSPECTOR_A_HEADERS


@pytest.fixture
def inspector_b():
    return INSPECTOR_B_HEADERS


@pytest.fixture
def manager():
    return MANAGER_A_HEADERS


@pytest.fixture
def benefits():
    return BENEFITS_A_HEADERS
