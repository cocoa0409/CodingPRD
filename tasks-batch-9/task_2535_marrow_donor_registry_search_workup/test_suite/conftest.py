"""Pytest fixtures exposing the test_helpers infrastructure.

The runner puts the task directory on `PYTHONPATH`, so `test_helpers` imports
without any `sys.path` manipulation.
"""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_center_ops_headers,
    make_liaison_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# One fixture per operator role
# ---------------------------------------------------------------------------

@pytest.fixture
def coordinator_headers():
    """The TransplantCoordinator that owns every patient these tests create."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def other_coordinator_headers():
    """A second, unrelated TransplantCoordinator identity."""
    return TEST_USERS["other_coordinator_headers"]


@pytest.fixture
def physician_headers():
    """The MedicalDirector that records clearance results."""
    return TEST_USERS["physician_headers"]


@pytest.fixture
def second_physician_headers():
    """A distinct MedicalDirector, required by the two-physician rule."""
    return TEST_USERS["second_physician_headers"]


@pytest.fixture
def operations_headers():
    """The RegistryOperations operator."""
    return TEST_USERS["operations_headers"]


@pytest.fixture
def liaison_headers():
    """An unbound DonorRegistryLiaison, for calls that never reach an
    ownership comparison. Registry-scoped writes must use
    `make_liaison_headers(registry_id)` instead."""
    return TEST_USERS["liaison_headers"]


@pytest.fixture
def center_ops_headers():
    """An unbound CollectionCenterOps operator, for calls that never reach an
    ownership comparison. Centre-scoped writes must use
    `make_center_ops_headers(center_id)` instead."""
    return TEST_USERS["center_ops_headers"]


@pytest.fixture
def liaison_headers_for():
    """Factory: headers for the DonorRegistryLiaison of a given registry."""
    return make_liaison_headers


@pytest.fixture
def center_ops_headers_for():
    """Factory: headers for the CollectionCenterOps operator of a given centre."""
    return make_center_ops_headers
