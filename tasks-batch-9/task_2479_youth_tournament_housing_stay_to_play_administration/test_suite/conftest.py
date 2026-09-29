"""Shared pytest fixtures for the Youth Tournament Housing test suite."""

import pytest

from test_helpers import (
    EXCEPTION_REVIEWER_2_HEADERS,
    EXCEPTION_REVIEWER_HEADERS,
    HOUSING_MANAGER_HEADERS,
    RIGHTS_HOLDER_2_HEADERS,
    RIGHTS_HOLDER_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared API client. Base URL comes from ``API_BASE_URL``."""
    return api_client


@pytest.fixture
def hm_headers():
    """Headers for the default ``HousingManager`` operator."""
    return HOUSING_MANAGER_HEADERS


@pytest.fixture
def reviewer_headers():
    """Headers for the default ``ExceptionReviewer`` operator."""
    return EXCEPTION_REVIEWER_HEADERS


@pytest.fixture
def other_reviewer_headers():
    """A second ``ExceptionReviewer``, for the appeal independence rule."""
    return EXCEPTION_REVIEWER_2_HEADERS


@pytest.fixture
def rights_holder_headers():
    """Headers for the default ``RightsHolder`` operator."""
    return RIGHTS_HOLDER_HEADERS


@pytest.fixture
def other_rights_holder_headers():
    """A second ``RightsHolder``, for the payout independence rule."""
    return RIGHTS_HOLDER_2_HEADERS
