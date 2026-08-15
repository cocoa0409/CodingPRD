"""Pytest fixtures exposing test_helpers infrastructure.

Entity-backed roles (Prescriber, Pharmacist, PharmacyTechnician, Nurse) must
resolve to an existing, active StaffMember whose staff_role matches the header
(PRD §2.1), so these fixtures register a fresh StaffMember per test and return
headers carrying its real id. PharmacyAdmin and DiversionOfficer are opaque
roles; the shared TEST_USERS constants are their canonical form.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client
from test_helpers import fixtures as th_fixtures


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def diversion_officer_headers():
    return TEST_USERS["diversion_officer_headers"]


@pytest.fixture
def prescriber_headers():
    _, headers = th_fixtures.make_prescriber()
    return headers


@pytest.fixture
def pharmacist_headers():
    _, headers = th_fixtures.make_pharmacist()
    return headers


@pytest.fixture
def technician_headers():
    _, headers = th_fixtures.make_technician()
    return headers


@pytest.fixture
def nurse_headers():
    _, headers = th_fixtures.make_nurse()
    return headers
