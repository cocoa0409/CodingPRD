"""Pytest fixtures exposing the shared test helpers.

Every test runs against a freshly started server with an empty database, so the
fixtures here hand out clients and identities only -- all business state is built
inside each test through the helper functions.
"""

from typing import Dict

import pytest

from test_helpers import ApiClient
from test_helpers.test_users import (
    CHANGE_APPROVER,
    COMPLIANCE_OFFICER,
    DUAL_ROLE_APPROVER,
    DUAL_ROLE_ENGINEER,
    ENGINEER,
    OTHER_ENGINEER,
    PLATFORM_ADMIN,
    RELEASE_MANAGER,
    SECOND_CHANGE_APPROVER,
    SRE,
)


@pytest.fixture
def api() -> ApiClient:
    """The endpoint client, pointed at the server under test.

    Function-scoped on purpose: the harness restarts the server before every
    test, so a session-scoped client would carry pooled keep-alive sockets that
    the restart has already closed.
    """
    return ApiClient()


@pytest.fixture(scope="session")
def platform_admin() -> Dict[str, str]:
    return PLATFORM_ADMIN


@pytest.fixture(scope="session")
def release_manager() -> Dict[str, str]:
    return RELEASE_MANAGER


@pytest.fixture(scope="session")
def engineer() -> Dict[str, str]:
    return ENGINEER


@pytest.fixture(scope="session")
def other_engineer() -> Dict[str, str]:
    return OTHER_ENGINEER


@pytest.fixture(scope="session")
def change_approver() -> Dict[str, str]:
    return CHANGE_APPROVER


@pytest.fixture(scope="session")
def second_change_approver() -> Dict[str, str]:
    return SECOND_CHANGE_APPROVER


@pytest.fixture(scope="session")
def compliance_officer() -> Dict[str, str]:
    return COMPLIANCE_OFFICER


@pytest.fixture(scope="session")
def sre() -> Dict[str, str]:
    return SRE


@pytest.fixture(scope="session")
def dual_role_engineer() -> Dict[str, str]:
    """An operator id that authors changes and also holds the approver role."""
    return DUAL_ROLE_ENGINEER


@pytest.fixture(scope="session")
def dual_role_approver() -> Dict[str, str]:
    """The same operator id as ``dual_role_engineer``, acting as ChangeApprover."""
    return DUAL_ROLE_APPROVER
