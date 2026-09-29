"""Shared pytest fixtures.

The helper package lives one directory up, so it is put on the import path
before anything else happens.
"""

import sys
from pathlib import Path

import pytest

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from test_helpers import ApiClient, TEST_USERS, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client, shared for the whole session."""
    return api_client


@pytest.fixture
def royalty_admin_headers() -> dict:
    return TEST_USERS["royalty_admin_headers"]


@pytest.fixture
def rights_ops_analyst_headers() -> dict:
    return TEST_USERS["rights_ops_analyst_headers"]


@pytest.fixture
def regulatory_officer_headers() -> dict:
    return TEST_USERS["regulatory_officer_headers"]


@pytest.fixture
def rights_holder_user_headers() -> dict:
    """Fallback RightsHolderUser headers.

    Only for calls that never reach an ownership check. Any ownership-gated
    call must use ``make_rights_holder_user_headers(holder["id"])``.
    """
    return TEST_USERS["rights_holder_user_headers"]


@pytest.fixture
def fuzzy_matcher_headers() -> dict:
    """The analyst who runs matching and therefore may not approve the claims
    their sub-perfect provisional matches enable."""
    return TEST_USERS["fuzzy_matcher_headers"]


@pytest.fixture
def reviewer_headers() -> dict:
    """A second analyst, distinct from the matcher, who reviews and approves."""
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def settling_admin_headers() -> dict:
    """An admin distinct from the user who recorded an audit finding."""
    return TEST_USERS["settling_admin_headers"]
