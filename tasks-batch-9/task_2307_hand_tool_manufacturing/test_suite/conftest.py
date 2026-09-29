"""Shared pytest fixtures for the ToolWorks suite.

This module is a thin bridge onto ``test_helpers``: the API client singleton and
the pre-built role headers described in PRD §2.1. Every test starts against an
empty database, so no fixture here seeds data.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The ToolWorks API client, mounted under /toolworks."""
    return api_client


@pytest.fixture
def channel_manager_headers() -> dict:
    """ChannelManager owns the commercial surface."""
    return TEST_USERS["channel_manager_headers"]


@pytest.fixture
def production_planner_headers() -> dict:
    """ProductionPlanner owns the shop floor."""
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def quality_engineer_headers() -> dict:
    """QualityEngineer owns qualification."""
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def warranty_administrator_headers() -> dict:
    """WarrantyAdministrator owns warranty administration."""
    return TEST_USERS["warranty_administrator_headers"]


@pytest.fixture
def brand_protection_analyst_headers() -> dict:
    """BrandProtectionAnalyst owns counterfeit detection."""
    return TEST_USERS["brand_protection_analyst_headers"]


@pytest.fixture
def platform_admin_headers() -> dict:
    """PlatformAdmin appears on every endpoint so that a single caller can
    compose an end-to-end chain."""
    return TEST_USERS["platform_admin_headers"]
