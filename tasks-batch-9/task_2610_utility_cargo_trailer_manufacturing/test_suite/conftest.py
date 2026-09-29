"""Shared pytest fixtures for the trailer plant suite."""

import pytest

from test_helpers import (
    ASSEMBLY_TECH,
    CERT_OFFICER,
    CERT_OFFICER_2,
    DEALER,
    PLANT_ENGINEER,
    QUALITY_INSPECTOR,
    SALES_ADMIN,
    WELD_SUPERVISOR,
    api_client,
)


@pytest.fixture(scope="session")
def api():
    return api_client


@pytest.fixture
def plant_engineer():
    return PLANT_ENGINEER


@pytest.fixture
def cert_officer():
    return CERT_OFFICER


@pytest.fixture
def cert_officer_2():
    return CERT_OFFICER_2


@pytest.fixture
def weld_supervisor():
    return WELD_SUPERVISOR


@pytest.fixture
def assembly_tech():
    return ASSEMBLY_TECH


@pytest.fixture
def quality_inspector():
    return QUALITY_INSPECTOR


@pytest.fixture
def sales_admin():
    return SALES_ADMIN


@pytest.fixture
def dealer_user():
    return DEALER
