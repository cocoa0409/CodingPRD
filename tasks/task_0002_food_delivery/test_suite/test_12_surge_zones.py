"""Tests for surge zone management and surge pricing.

Covers: PRD Section 2.8 (Surge Pricing), Table 6 (ERR_INVALID_SURGE_MULTIPLIER, ERR_SURGE_ZONE_NOT_FOUND).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_surge_zone, create_surge_zone_payload,
    create_active_surge_zone,
    MIN_SURGE_MULTIPLIER, MAX_SURGE_MULTIPLIER,
)


_admin = TEST_USERS["admin_headers"]
_customer = TEST_USERS["customer_headers"]


class TestSurgeZoneCreation:
    """PRD 2.8: Admin creates surge zones."""

    def test_create_surge_zone_success(self):
        """Create an ACTIVE surge zone with valid multiplier."""
        payload = create_surge_zone_payload(surge_multiplier=1.5)
        resp = api_client.create_surge_zone(payload, _admin)
        data = validate_success(resp, 201)
        assert_surge_zone(data)
        assert data["status"] == "ACTIVE"
        assert data["surge_multiplier"] == pytest.approx(1.5, abs=0.01)

    def test_surge_multiplier_at_minimum_boundary(self):
        """Boundary: surge_multiplier = 1.0 is valid."""
        payload = create_surge_zone_payload(surge_multiplier=1.0)
        resp = api_client.create_surge_zone(payload, _admin)
        data = validate_success(resp, 201)
        assert data["surge_multiplier"] == pytest.approx(1.0, abs=0.01)

    def test_surge_multiplier_at_maximum_boundary(self):
        """Boundary: surge_multiplier = 3.0 is valid."""
        payload = create_surge_zone_payload(surge_multiplier=3.0)
        resp = api_client.create_surge_zone(payload, _admin)
        data = validate_success(resp, 201)
        assert data["surge_multiplier"] == pytest.approx(3.0, abs=0.01)

    def test_surge_multiplier_below_minimum(self):
        """ERR_INVALID_SURGE_MULTIPLIER when multiplier < 1.0."""
        payload = create_surge_zone_payload(surge_multiplier=0.9)
        resp = api_client.create_surge_zone(payload, _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_SURGE_MULTIPLIER)

    def test_surge_multiplier_above_maximum(self):
        """ERR_INVALID_SURGE_MULTIPLIER when multiplier > 3.0."""
        payload = create_surge_zone_payload(surge_multiplier=3.1)
        resp = api_client.create_surge_zone(payload, _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_SURGE_MULTIPLIER)

    def test_create_surge_zone_forbidden_for_customer(self):
        """Only platform_admin can create surge zones."""
        resp = api_client.create_surge_zone(create_surge_zone_payload(), _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSurgeZoneUpdate:
    """PRD Section 4: Update surge zone."""

    def test_update_surge_multiplier(self):
        """Update surge_multiplier."""
        zone = create_active_surge_zone()
        resp = api_client.update_surge_zone(
            zone["id"], {"surge_multiplier": 2.0}, _admin
        )
        data = validate_success(resp)
        assert data["surge_multiplier"] == pytest.approx(2.0, abs=0.01)

    def test_update_surge_multiplier_invalid(self):
        """ERR_INVALID_SURGE_MULTIPLIER on update with invalid value."""
        zone = create_active_surge_zone()
        resp = api_client.update_surge_zone(
            zone["id"], {"surge_multiplier": 3.5}, _admin
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SURGE_MULTIPLIER)

    def test_surge_zone_not_found(self):
        """ERR_SURGE_ZONE_NOT_FOUND for non-existent zone."""
        resp = api_client.update_surge_zone(
            NON_EXISTENT_UUID, {"surge_multiplier": 1.5}, _admin
        )
        validate_error(resp, ApiErrorId.ERR_SURGE_ZONE_NOT_FOUND)

    def test_surge_zone_version_conflict(self):
        """OCC: stale version on surge zone update triggers ERR_VERSION_CONFLICT."""
        zone = create_active_surge_zone()
        stale_version = zone["version"]
        get_success_data(api_client.update_surge_zone(
            zone["id"], {"surge_multiplier": 2.0}, _admin
        ))
        resp = api_client.update_surge_zone(
            zone["id"], {"surge_multiplier": 2.5, "version": stale_version}, _admin
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)
