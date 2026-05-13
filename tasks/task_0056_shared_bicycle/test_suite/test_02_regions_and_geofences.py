"""Region creation, density posture, and geofence configuration.

Covers PRD §2.7 (density posture), §3.1 (region configuration and
geofences), and §3.13 OCC behavior on PATCH /regions.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_density_posture_matches,
    assert_geofence,
    assert_region,
    create_geofence,
    create_geofence_payload,
    create_region,
    create_region_payload,
    get_region,
    make_square_polygon,
    patch_region,
    patch_region_payload,
    setup_region_at_posture,
    setup_region_with_bikes,
    validate_error,
    validate_success,
    ADMIN,
)


class TestRegionCreation:
    def test_create_region_initial_state(self, api, admin_headers):
        """PRD §3.1: 'Once created, the region's clock_minutes begins at
        0 and its density_posture starts at NORMAL (because both
        deployed_count and available_count start at 0).'"""
        region = create_region()
        assert_region(region)
        assert region["clock_minutes"] == 0, (
            "PRD §3.1: clock_minutes begins at 0"
        )
        assert region["deployed_count"] == 0
        assert region["available_count"] == 0

    def test_default_incentive_amounts_are_zero(self, api):
        """PRD §3.1: 'Both incentives default to 0 when the region is
        created without them.'"""
        region = create_region(
            in_zone_return_reward_cents=None,
            out_of_zone_penalty_cents=None,
        )
        assert region["in_zone_return_reward_cents"] == 0, (
            "PRD §3.1: in_zone_return_reward_cents defaults to 0"
        )
        assert region["out_of_zone_penalty_cents"] == 0

    def test_high_threshold_must_be_strictly_greater_than_low(
        self, api, admin_headers,
    ):
        """PRD §3.1: 'high_density_threshold must be strictly greater
        than low_density_threshold.'"""
        payload = create_region_payload(
            low_density_threshold=5,
            high_density_threshold=5,
        )
        resp = api.create_region(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


class TestDensityPosture:
    """PRD §2.7: 'The posture is LOW when available_count is less than
    or equal to low_density_threshold, HIGH when available_count is
    greater than or equal to high_density_threshold, and NORMAL
    otherwise. The inclusive boundaries on both ends are deliberate.'"""

    def test_low_boundary_inclusive(self, api):
        """PRD §2.7: 'The posture is LOW when available_count is less
        than or equal to low_density_threshold.'"""
        region, _ = setup_region_at_posture(
            "LOW", deployment_quota=20,
            low_density_threshold=3, high_density_threshold=10,
            available_count_override=3,
        )
        assert_density_posture_matches(region, "LOW")

    def test_high_boundary_inclusive(self, api):
        """PRD §2.7: 'HIGH when available_count is greater than or equal
        to high_density_threshold.'"""
        region, _ = setup_region_at_posture(
            "HIGH", deployment_quota=20,
            low_density_threshold=2, high_density_threshold=5,
            available_count_override=5,
        )
        assert_density_posture_matches(region, "HIGH")

    def test_normal_between_thresholds(self, api):
        region, _ = setup_region_at_posture(
            "NORMAL", deployment_quota=20,
            low_density_threshold=2, high_density_threshold=10,
            available_count_override=5,
        )
        assert_density_posture_matches(region, "NORMAL")


class TestRegionPatchOcc:
    def test_patch_region_increments_version(self, api):
        """PRD §2.4: 'a monotonically increasing integer version that
        starts at 1 on creation and increments by exactly one on every
        mutation.'"""
        region = create_region()
        v0 = region["version"]
        updated = patch_region(region["id"], deployment_quota=100)
        assert updated["version"] == v0 + 1, (
            f"version must increment by exactly one, "
            f"got {v0} → {updated['version']}"
        )
        assert updated["deployment_quota"] == 100

    def test_patch_region_stale_version_rejected(self, api, admin_headers):
        """PRD §2.4: 'when present, the server compares it to the current
        server-side version for that entity and rejects the write with
        ERR_VERSION_CONFLICT (HTTP 409) on mismatch.'"""
        region = create_region()
        # Bump the version once.
        patch_region(region["id"], deployment_quota=99)
        resp = api.patch_region(
            region["id"],
            patch_region_payload(deployment_quota=50, version=region["version"]),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value, 409)

    def test_patch_region_without_version_skips_check(self, api):
        """PRD §2.4: 'Omitting version from the request body skips the
        optimistic check entirely — the write proceeds against whatever
        the current version is.'"""
        region = create_region()
        patch_region(region["id"], deployment_quota=42)
        # Refetch and patch again without version — should succeed
        again = patch_region(region["id"], deployment_quota=43)
        assert again["deployment_quota"] == 43

    def test_patch_region_recomputes_posture_against_new_thresholds(self, api):
        """PRD §3.1: 'on success the posture is recomputed against the
        new thresholds.'"""
        region, _ = setup_region_with_bikes(
            deployment_quota=20,
            low_density_threshold=10,
            high_density_threshold=15,
            num_bikes=5,
        )
        # available_count=5, low=10, high=15 → posture=LOW
        region = get_region(region["id"])
        assert region["density_posture"] == "LOW"
        # Now widen the thresholds so 5 sits in NORMAL band
        updated = patch_region(
            region["id"],
            low_density_threshold=2,
            high_density_threshold=10,
        )
        assert updated["density_posture"] == "NORMAL", (
            "PRD §3.1: on success the posture is recomputed against the "
            "new thresholds"
        )


class TestGeofenceCreation:
    def test_create_geofence_active_default_true(self, api):
        """PRD §3.1: 'an optional active flag (defaulting to true).'"""
        region = create_region()
        fence = create_geofence(region["id"], active=None)
        assert fence["active"] is True, (
            "PRD §3.1: active flag defaults to true"
        )

    def test_geofence_starts_revision_1(self, api):
        """PRD §2.4: 'Geofence ... carries a revision field with the
        same monotonically-increasing-on-mutation semantics — it starts
        at 1 and increments on every shape or active-flag mutation.'"""
        region = create_region()
        fence = create_geofence(region["id"])
        assert fence["revision"] == 1, (
            "PRD §2.4: revision starts at 1"
        )

    def test_polygon_under_three_vertices_rejected(self, api, admin_headers):
        """PRD §3.1: 'A polygon with fewer than 3 or more than 32
        vertices ... is rejected with ERR_INVALID_POLYGON (HTTP 422).'"""
        region = create_region()
        bad_polygon = [{"lat": 30.0, "lng": 120.0},
                       {"lat": 30.1, "lng": 120.1}]
        resp = api.create_geofence(
            region["id"],
            create_geofence_payload(polygon=bad_polygon),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_POLYGON.value, 422)

    def test_polygon_over_thirty_two_vertices_rejected(self, api, admin_headers):
        """PRD §3.1: 'A polygon with fewer than 3 or more than 32
        vertices ... is rejected with ERR_INVALID_POLYGON (HTTP 422).'"""
        region = create_region()
        many = [{"lat": 30.0 + i * 0.001, "lng": 120.0 + i * 0.0001}
                for i in range(33)]
        resp = api.create_geofence(
            region["id"],
            create_geofence_payload(polygon=many),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_POLYGON.value, 422)

    def test_polygon_duplicate_vertex_rejected(self, api, admin_headers):
        """PRD §3.1: 'A polygon ... with any duplicate vertex ... is
        rejected with ERR_INVALID_POLYGON (HTTP 422).'"""
        region = create_region()
        dup = [{"lat": 30.0, "lng": 120.0},
               {"lat": 30.0, "lng": 120.0},
               {"lat": 30.1, "lng": 120.1}]
        resp = api.create_geofence(
            region["id"],
            create_geofence_payload(polygon=dup),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_POLYGON.value, 422)


class TestGeofencePatch:
    def test_patch_geofence_active_increments_revision(
        self, api, admin_headers,
    ):
        """PRD §3.1: 'any such mutation increments revision by one.'"""
        region = create_region()
        fence = create_geofence(region["id"], active=True)
        r0 = fence["revision"]
        from test_helpers import patch_geofence_payload
        resp = api.patch_geofence(
            fence["id"], patch_geofence_payload(active=False), admin_headers,
        )
        updated = validate_success(resp, expected_status=200)
        assert updated["revision"] == r0 + 1, (
            "PRD §3.1: 'any such mutation increments revision by one.'"
        )
        assert updated["active"] is False


class TestClockAdvance:
    def test_clock_advance_returns_new_minutes(self, api):
        """PRD §2.6: 'The clock-advance capability accepts a single
        non-negative integer minutes parameter and returns the new
        clock_minutes.'"""
        region = create_region()
        result = advance_clock(15)
        # The clock is global — verify region reads the bumped value.
        region = get_region(region["id"])
        assert region["clock_minutes"] >= 15, (
            f"clock_minutes should be advanced by 15, got "
            f"{region['clock_minutes']}"
        )
