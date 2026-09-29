"""Shared fixtures for the Aegis CNP fraud-prevention suite.

Each test runs against a freshly started server with an empty database, so every
precondition is built inside the test from the documented endpoints.
"""

from __future__ import annotations

from typing import Dict

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_checkout_service_headers,
    make_platform_admin_headers,
    make_policy_engineer_approver_headers,
    make_policy_engineer_author_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared API client."""
    return api_client


@pytest.fixture
def checkout() -> Dict[str, str]:
    """Headers for the storefront integration, which opens and scores orders."""
    return make_checkout_service_headers()


@pytest.fixture
def admin() -> Dict[str, str]:
    """Headers for the platform administrator, who owns the roster and the clock."""
    return make_platform_admin_headers()


@pytest.fixture
def engineer() -> Dict[str, str]:
    """Headers for the policy engineer who authors packs and models."""
    return make_policy_engineer_author_headers()


@pytest.fixture
def engineer_approver() -> Dict[str, str]:
    """Headers for a second policy engineer, eligible to activate an authored pack."""
    return make_policy_engineer_approver_headers()
