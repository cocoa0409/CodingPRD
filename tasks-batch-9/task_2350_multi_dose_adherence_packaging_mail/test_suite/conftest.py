"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    admin_headers,
    ops_headers,
    patient_headers,
    pharmacist_headers,
    prescriber_headers,
    technician_headers,
    unauthenticated_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin():
    """Headers for a PlatformAdmin caller."""
    return admin_headers()


@pytest.fixture
def ops():
    """Headers for a PharmacyOperations caller."""
    return ops_headers()


@pytest.fixture
def pharmacist():
    """Headers for a VerifyingPharmacist caller."""
    return pharmacist_headers()


@pytest.fixture
def technician():
    """Headers for a PackagingTechnician caller."""
    return technician_headers()


@pytest.fixture
def prescriber():
    """Headers for a Prescriber caller."""
    return prescriber_headers()


@pytest.fixture
def anonymous():
    """Headers carrying neither identity nor role."""
    return unauthenticated_headers()


@pytest.fixture
def as_patient():
    """Builder for headers belonging to a specific patient."""
    return patient_headers
