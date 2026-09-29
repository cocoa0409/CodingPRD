"""Pytest wiring. Every fixture below is a thin view onto ``test_helpers``."""

from __future__ import annotations

from typing import Dict

import pytest

from test_helpers import (
    ADMIN_PAT,
    ADMIN_ZOE,
    COMPLIANCE_CARL,
    FINANCE_FRANK,
    OPS_ALICE,
    OPS_DANA,
    REVIEWER_BOB,
    REVIEWER_ERIN,
    TEST_USERS,
    ApiClient,
    api_client,
)

Headers = Dict[str, str]


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture(scope="session")
def users() -> Dict[str, Headers]:
    return TEST_USERS


@pytest.fixture
def ops() -> Headers:
    """The primary export operations coordinator."""
    return OPS_ALICE


@pytest.fixture
def ops_other() -> Headers:
    """A second coordinator, for duty separations that need two preparers."""
    return OPS_DANA


@pytest.fixture
def compliance() -> Headers:
    return COMPLIANCE_CARL


@pytest.fixture
def reviewer() -> Headers:
    """A credit reviewer who prepares no documents at all."""
    return REVIEWER_BOB


@pytest.fixture
def reviewer_other() -> Headers:
    return REVIEWER_ERIN


@pytest.fixture
def finance() -> Headers:
    return FINANCE_FRANK


@pytest.fixture
def admin() -> Headers:
    return ADMIN_PAT


@pytest.fixture
def admin_other() -> Headers:
    return ADMIN_ZOE
