"""Shared fixtures for the payment-card security assessment suite."""

import pytest

from test_helpers.api_errors import register_error_status_map
from test_helpers.fixtures import (
    api,
    engagement_with_gap,
    engagement_with_in_place_requirement,
    fieldwork_engagement,
    registry,
    roc_in_drafting,
    roc_in_qa,
    sampled_engagement,
    scoping_engagement,
    validated_cde_engagement,
)

__all__ = [
    "api",
    "registry",
    "scoping_engagement",
    "validated_cde_engagement",
    "sampled_engagement",
    "fieldwork_engagement",
    "engagement_with_in_place_requirement",
    "engagement_with_gap",
    "roc_in_drafting",
    "roc_in_qa",
]


@pytest.fixture(autouse=True)
def _error_status_map():
    """Load the PRD's error-to-status table before every test."""
    register_error_status_map()
    yield
