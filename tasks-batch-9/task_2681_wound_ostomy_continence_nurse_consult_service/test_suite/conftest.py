"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def director_headers():
    """`WocProgramDirector` — an opaque operator identifier."""
    return TEST_USERS["director_headers"]


@pytest.fixture
def materials_headers():
    """`MaterialsCoordinator` — an opaque operator identifier."""
    return TEST_USERS["materials_headers"]


@pytest.fixture
def system_operator_headers():
    """`SystemOperator` — an opaque operator identifier."""
    return TEST_USERS["system_operator_headers"]


@pytest.fixture
def nurse_headers():
    """`WocNurse` placeholder identity, for calls that never reach an ownership
    comparison. Ownership-gated calls must use make_nurse_headers(nurse_id)."""
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def unit_charge_headers():
    """`UnitCharge` placeholder identity, for calls that never reach an ownership
    comparison. Ownership-gated calls must use make_unit_charge_headers(unit_id)."""
    return TEST_USERS["unit_charge_headers"]
