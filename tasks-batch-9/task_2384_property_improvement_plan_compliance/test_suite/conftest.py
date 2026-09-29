"""Shared pytest fixtures for the Property Improvement Plan Compliance suite."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    BRAND_MANAGER_HEADERS,
    INSPECTOR_HEADERS,
    OTHER_BRAND_MANAGER_HEADERS,
    OTHER_INSPECTOR_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The endpoint-per-method client, pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def brand_manager():
    """Headers for the brand's compliance and franchising operator."""
    return BRAND_MANAGER_HEADERS


@pytest.fixture
def other_brand_manager():
    """A second, differently identified brand operator, for duty-separation checks."""
    return OTHER_BRAND_MANAGER_HEADERS


@pytest.fixture
def brand_inspector():
    """Headers for the brand's field inspector."""
    return INSPECTOR_HEADERS


@pytest.fixture
def other_brand_inspector():
    """A second field inspector, for assigned-inspector checks."""
    return OTHER_INSPECTOR_HEADERS
