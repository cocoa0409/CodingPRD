"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    DIRECTOR_HEADERS_2,
    FINANCE_HEADERS,
    FINANCE_HEADERS_2,
    REGISTRAR_HEADERS,
    REGISTRAR_HEADERS_2,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return ApiClient()


@pytest.fixture
def director_headers():
    return DIRECTOR_HEADERS


@pytest.fixture
def director_headers_2():
    return DIRECTOR_HEADERS_2


@pytest.fixture
def registrar_headers():
    return REGISTRAR_HEADERS


@pytest.fixture
def registrar_headers_2():
    return REGISTRAR_HEADERS_2


@pytest.fixture
def finance_headers():
    return FINANCE_HEADERS


@pytest.fixture
def finance_headers_2():
    return FINANCE_HEADERS_2
