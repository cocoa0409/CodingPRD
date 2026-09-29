"""Shared pytest fixtures for the inclusive-access billing test suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    make_bursar_officer_headers,
    make_compliance_officer_headers,
    make_faculty_headers,
    make_program_admin_headers,
    make_registrar_headers,
)


@pytest.fixture(scope="session")
def api():
    """HTTP client for the API under test."""
    return ApiClient()


@pytest.fixture
def program_admin():
    return make_program_admin_headers()


@pytest.fixture
def second_program_admin():
    """A ProgramAdmin distinct from the default one, for segregation of duties."""
    return make_program_admin_headers("pa-2")


@pytest.fixture
def faculty():
    return make_faculty_headers()


@pytest.fixture
def registrar():
    return make_registrar_headers()


@pytest.fixture
def bursar_officer():
    return make_bursar_officer_headers()


@pytest.fixture
def compliance_officer():
    return make_compliance_officer_headers()
