"""Manifest scheduling guard chain: window-in-past, account-activity ordering,
half-open pickup-route window overlap, and optimistic concurrency on manifest
amendments (PRD §2.4, §2.8, §3.3)."""
from test_helpers import (
    ApiErrorId,
    am_headers,
    new_account,
    new_manifest,
    set_clock,
    validate_error,
    validate_success,
)


class TestWindowInPast:
    def test_schedule_window_in_past_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.3: "The guard chain runs in a fixed order: the manifest must actually be in `DRAFT` (otherwise `ERR_INVALID_STATE`); the owning account must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`); the window's `scheduled_end` must lie strictly after the current logical clock (`ERR_WINDOW_IN_PAST`); and, for `PICKUP` manifests only, the half-open window from `scheduled_start` up to but not including `scheduled_end` must not overlap the window of any other manifest on the same `pickup_route` that is currently `SCHEDULED` or `RECEIVED` (`ERR_ROUTE_WINDOW_CONFLICT`)."

        Design: Corner/validations/window_in_past_rejected
        """
        account = new_account("Past Co", "pa@x.example")
        manifest = new_manifest(
            account,
            scheduled_start="2026-05-10T09:00:00Z",
            scheduled_end="2026-05-10T11:00:00Z",
        )
        # Advance the logical clock past the end of the appointment window.
        set_clock("2026-06-01T00:00:00Z")

        resp = api.schedule_manifest(manifest["id"], logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)
        assert resp.status_code == 422


class TestScheduleGuardOrdering:
    def _suspend_with_past_window(self, api, platform_admin_headers):
        """DRAFT manifest on an account that is then SUSPENDED, with the clock
        advanced beyond the window — both the account-activity and the
        window-in-past conditions hold at schedule time."""
        account = new_account("Susp Co", "s@susp.example")
        manifest = new_manifest(
            account,
            scheduled_start="2026-05-10T09:00:00Z",
            scheduled_end="2026-05-10T11:00:00Z",
        )
        validate_success(
            api.update_account(account["id"], {"status": "SUSPENDED"}, platform_admin_headers)
        )
        set_clock("2026-06-01T00:00:00Z")
        return account, manifest

    def test_schedule_suspended_account_error_beats_past_window(self, api,
                                                                platform_admin_headers,
                                                                logistics_coordinator_headers):
        """PRD §3.3: "The guard chain runs in a fixed order: the manifest must actually be in `DRAFT` (otherwise `ERR_INVALID_STATE`); the owning account must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`); the window's `scheduled_end` must lie strictly after the current logical clock (`ERR_WINDOW_IN_PAST`); and, for `PICKUP` manifests only, the half-open window from `scheduled_start` up to but not including `scheduled_end` must not overlap the window of any other manifest on the same `pickup_route` that is currently `SCHEDULED` or `RECEIVED` (`ERR_ROUTE_WINDOW_CONFLICT`)."

        Design: Difficulty/priority_pair_validation_conflict/manifest_schedule_referential_error_beats_temporal_error
        """
        _account, manifest = self._suspend_with_past_window(api, platform_admin_headers)

        resp = api.schedule_manifest(manifest["id"], logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        assert resp.status_code == 422

    def test_schedule_dual_failure_leaves_manifest_draft(self, api, platform_admin_headers,
                                                         logistics_coordinator_headers):
        """PRD §3.3: "The guard chain runs in a fixed order: the manifest must actually be in `DRAFT` (otherwise `ERR_INVALID_STATE`); the owning account must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`); the window's `scheduled_end` must lie strictly after the current logical clock (`ERR_WINDOW_IN_PAST`); and, for `PICKUP` manifests only, the half-open window from `scheduled_start` up to but not including `scheduled_end` must not overlap the window of any other manifest on the same `pickup_route` that is currently `SCHEDULED` or `RECEIVED` (`ERR_ROUTE_WINDOW_CONFLICT`)."

        Design: Difficulty/priority_pair_validation_conflict/manifest_schedule_referential_error_beats_temporal_error
        """
        _account, manifest = self._suspend_with_past_window(api, platform_admin_headers)

        validate_error(api.schedule_manifest(manifest["id"], logistics_coordinator_headers),
                       ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        manifest = validate_success(api.get_manifest(manifest["id"], logistics_coordinator_headers))
        assert manifest["status"] == "DRAFT"


class TestPickupRouteWindowOverlap:
    def _setup_three_pickup_manifests(self, api):
        account = new_account("Route Co", "r@route.example")
        m1 = new_manifest(account, mode="PICKUP", pickup_route="R-9",
                          scheduled_start="2026-06-01T09:00:00Z",
                          scheduled_end="2026-06-01T11:00:00Z")
        m2 = new_manifest(account, mode="PICKUP", pickup_route="R-9",
                          scheduled_start="2026-06-01T10:00:00Z",
                          scheduled_end="2026-06-01T12:00:00Z")
        m3 = new_manifest(account, mode="PICKUP", pickup_route="R-9",
                          scheduled_start="2026-06-01T11:00:00Z",
                          scheduled_end="2026-06-01T13:00:00Z")
        return account, m1, m2, m3

    def test_overlapping_pickup_window_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.3: "the half-open window from `scheduled_start` up to but not including `scheduled_end` must not overlap the window of any other manifest on the same `pickup_route` that is currently `SCHEDULED` or `RECEIVED` (`ERR_ROUTE_WINDOW_CONFLICT`)."

        Design: Difficulty/resource_temporal_overlap/pickup_route_windows_half_open_overlap
        """
        _account, m1, m2, _m3 = self._setup_three_pickup_manifests(api)
        validate_success(api.schedule_manifest(m1["id"], logistics_coordinator_headers))

        # 10:00-12:00 overlaps the scheduled 09:00-11:00 window.
        resp = api.schedule_manifest(m2["id"], logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT)
        assert resp.status_code == 409

    def test_adjacent_pickup_window_allowed(self, api, logistics_coordinator_headers):
        """PRD §3.3: "Because windows are half-open, pure adjacency — one route window ending exactly when the next begins — is allowed and is not a conflict."

        Design: Difficulty/resource_temporal_overlap/pickup_route_windows_half_open_overlap
        """
        _account, m1, _m2, m3 = self._setup_three_pickup_manifests(api)
        validate_success(api.schedule_manifest(m1["id"], logistics_coordinator_headers))

        # 11:00-13:00 starts exactly when the scheduled 09:00-11:00 window ends.
        data = validate_success(api.schedule_manifest(m3["id"], logistics_coordinator_headers))
        assert data["status"] == "SCHEDULED"


class TestManifestAmendOcc:
    def test_amend_with_stale_version_rejected(self, api):
        """PRD §2.8: "Amending a DRAFT manifest requires the request to carry `expected_manifest_version` holding the manifest `version` the client last observed. If the manifest's current `version` no longer equals the supplied value — because another writer has advanced it since the client's read — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than silently overwriting a change the client never saw."

        Design: Corner/cross_cutting_complexity_layers/occ_manifest_amend_stale_returns_412
        """
        account = new_account("OCC Co", "occ@x.example")
        manifest = new_manifest(account)
        observed_version = manifest["version"]

        amended = validate_success(api.update_manifest(
            manifest["id"],
            {"expected_manifest_version": observed_version, "declared_item_count": 5},
            am_headers(account),
        ))
        assert amended["declared_item_count"] == 5
        assert amended["version"] == observed_version + 1

        resp = api.update_manifest(
            manifest["id"],
            {"expected_manifest_version": observed_version, "declared_item_count": 7},
            am_headers(account),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_rejected_amend_replay_leaves_fields_unchanged(self, api):
        """PRD §2.8: "If the manifest's current `version` no longer equals the supplied value — because another writer has advanced it since the client's read — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than silently overwriting a change the client never saw."

        Design: Corner/cross_cutting_complexity_layers/occ_manifest_amend_stale_returns_412
        """
        account = new_account("OCC Co", "occ@x.example")
        manifest = new_manifest(account)
        observed_version = manifest["version"]

        validate_success(api.update_manifest(
            manifest["id"],
            {"expected_manifest_version": observed_version, "declared_item_count": 5},
            am_headers(account),
        ))
        validate_error(api.update_manifest(
            manifest["id"],
            {"expected_manifest_version": observed_version, "declared_item_count": 7},
            am_headers(account),
        ), ApiErrorId.ERR_STALE_VERSION)

        manifest = validate_success(api.get_manifest(manifest["id"], am_headers(account)))
        assert manifest["declared_item_count"] == 5

    def test_amend_increments_version_by_exactly_one(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that increments by one on every mutation of the resource."
        PRD §3.3: "While the manifest remains `DRAFT`, the account manager may amend its `pickup_route`, `scheduled_start`, `scheduled_end`, or `declared_item_count`."

        Design: Corner/cross_cutting_complexity_layers/occ_manifest_version_increments_on_patch
        """
        account = new_account("OCV Co", "ocv@x.example")
        manifest = new_manifest(account)
        amended = validate_success(api.update_manifest(
            manifest["id"],
            {"expected_manifest_version": manifest["version"],
             "scheduled_end": "2026-06-01T12:00:00Z"},
            am_headers(account),
        ))
        assert amended["version"] == manifest["version"] + 1
        assert amended["scheduled_end"] == "2026-06-01T12:00:00Z"
