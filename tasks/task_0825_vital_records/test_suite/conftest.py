"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_facility_filer_headers,
    make_medical_certifier_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def facility_filer_headers():
    """Shared FacilityFiler fallback. Use ONLY for calls that do not exercise
    the entity_backed:Facility ownership check. Ownership-gated calls MUST use
    make_facility_filer_headers(<Facility.id>)."""
    return TEST_USERS["facility_filer_headers"]


@pytest.fixture
def medical_certifier_headers():
    """Shared MedicalCertifier fallback. Use ONLY for non-ownership-gated calls.
    Ownership-gated calls MUST use make_medical_certifier_headers(<Certifier.id>)."""
    return TEST_USERS["medical_certifier_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing per-identity header builders for entity_backed roles."""
    return {
        "facility_filer": make_facility_filer_headers,
        "medical_certifier": make_medical_certifier_headers,
    }
