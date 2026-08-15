"""SeasonSettings singleton optimistic concurrency."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, assert_season_settings,
    ApiErrorId, reset_clock,
)


class TestSeasonSettingsOcc:
    def test_stale_settings_version_rejected(self, api, admin_headers):
        """PRD §2.7: "An update to the `SeasonSettings` singleton must carry
        `expected_settings_version` matching the singleton's current `version`,
        so two admins cannot each believe their own update was the one that
        landed; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.11: "The singleton is auto-created with defaults on the first
        read".

        Design: Corner/cross_cutting_layers/occ_settings_update_stale_version
        """
        reset_clock()
        settings = validate_success(api.get_season_settings(admin_headers))
        assert_season_settings(settings)
        observed_version = settings["version"]
        # First update lands and advances the singleton's version.
        updated = validate_success(api.update_season_settings(
            {"late_donor_grace_hours": 12,
             "expected_settings_version": observed_version}, admin_headers))
        assert updated["late_donor_grace_hours"] == 12
        assert updated["version"] > observed_version
        # A second update replaying the previously observed version is stale.
        res = api.update_season_settings(
            {"late_donor_grace_hours": 24,
             "expected_settings_version": observed_version}, admin_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        current = validate_success(api.get_season_settings(admin_headers))
        assert current["late_donor_grace_hours"] == 12, \
            "the stale update must not overwrite the landed value"
