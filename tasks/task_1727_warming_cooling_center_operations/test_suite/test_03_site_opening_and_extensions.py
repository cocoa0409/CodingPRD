"""Site-activation opening gates (coverage, lead containment, episode state),
bed-capacity pinning, and OCC-guarded writes (PRD §2.8, §3.2, §3.3, §3.8)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    create_site,
    extension_payload,
    get_episode,
    get_site_activation,
    make_site_lead_headers,
    parse_instant,
    setup_activating_episode_with_site,
    setup_active_episode_for_extensions,
    setup_capacity_override_open_scene,
    setup_lead_coverage_missing_scene,
    setup_overnight_gap_contrast_scene,
    site_patch_payload,
    validate_error,
    validate_success,
)


class TestOvernightCoverageBoundary:
    def test_overnight_shift_ending_exactly_0600_allows_open(self, api):
        """PRD §3.3: "`lead_coverage_ok` is true exactly when some `CONFIRMED`
        shift with `role_on_shift` `SITE_LEAD` fully contains the window,
        meaning its `start_at` is at or before 22:00 and its `end_at` is at or
        after 06:00 the next day."
        PRD §2.4: "Time-window fields throughout the API are half-open
        intervals: the start instant is inclusive and the end instant is
        exclusive."

        Design: Difficulty/boundary_precision_check/overnight_shift_end_at_exactly_0600_covers_0559_fails
        """
        ws = setup_overnight_gap_contrast_scene()
        resp = api.open_site_activation(
            ws["sa_a"]["id"], make_site_lead_headers(ws["lead1"]["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "OPEN"
        assert data["overnight_coverage_gap_minutes"] == 0
        assert data["lead_coverage_ok"] is True

    def test_overnight_shift_ending_0559_rejected_with_gap(self, api):
        """PRD §3.2: "The overnight coverage gap must be fully closed —
        `overnight_coverage_gap_minutes` exactly zero — else
        `ERR_OVERNIGHT_COVERAGE_GAP`; this check is evaluated before the
        lead-coverage check."

        Design: Difficulty/boundary_precision_check/overnight_shift_end_at_exactly_0600_covers_0559_fails
        """
        ws = setup_overnight_gap_contrast_scene()
        # Site B's lead shift ends one minute before the window's exclusive
        # 06:00 end: 479 of 480 minutes covered.
        before = get_site_activation(ws["sa_b"]["id"])
        assert before["overnight_coverage_gap_minutes"] == 1
        assert before["lead_coverage_ok"] is False
        resp = api.open_site_activation(
            ws["sa_b"]["id"], make_site_lead_headers(ws["lead3"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OVERNIGHT_COVERAGE_GAP,
                       expected_status=409)
        assert get_site_activation(ws["sa_b"]["id"])["status"] == "OPENING"


class TestOpeningGates:
    def test_open_without_lead_coverage_rejected_despite_zero_gap(self, api):
        """PRD §3.2: "A confirmed site-lead shift must fully contain tonight's
        overnight window — `lead_coverage_ok` true — else
        `ERR_LEAD_COVERAGE_MISSING`."
        PRD §3.3: "the non-empty pieces are merged as half-open intervals —
        overlapping or merely touching pieces merge seamlessly — and
        `overnight_coverage_gap_minutes` is 480 minus the total covered
        minutes."

        Design: Corner/validations/open_without_lead_coverage_rejected_despite_zero_gap
        """
        ws = setup_lead_coverage_missing_scene()
        before = get_site_activation(ws["site_activation"]["id"])
        assert before["overnight_coverage_gap_minutes"] == 0
        assert before["lead_coverage_ok"] is False
        resp = api.open_site_activation(
            ws["site_activation"]["id"], ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_LEAD_COVERAGE_MISSING,
                       expected_status=409)
        assert (get_site_activation(ws["site_activation"]["id"])["status"]
                == "OPENING")

    def test_open_before_episode_active_rejected(self, api):
        """PRD §3.2: "The episode must be `ACTIVE`, else
        `ERR_EPISODE_NOT_ACTIVE`."

        Design: Corner/validations/open_before_episode_active_rejected
        """
        # Episode is ACTIVATING (trigger met, never activated); coverage and
        # lead containment are already satisfied.
        ws = setup_activating_episode_with_site()
        assert get_episode(ws["episode"]["id"])["status"] == "ACTIVATING"
        resp = api.open_site_activation(
            ws["site_activation"]["id"], ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_ACTIVE,
                       expected_status=409)
        assert (get_site_activation(ws["site_activation"]["id"])["status"]
                == "OPENING")


class TestBedCapacityPinning:
    def test_site_capacity_override_pins_beds_effective_against_later_patch(
            self, api, eoc_manager_headers):
        """PRD §2.6: "`beds_effective` itself is pinned the first time the
        activation opens: it takes the designated `capacity_override` when one
        was supplied, otherwise the site's `bed_capacity` at that moment, and
        a later amendment of the site's registry capacity does not
        retro-change an already-pinned value."

        Design: Corner/entities/site_capacity_override_pins_beds_effective_against_later_patch
        """
        ws = setup_capacity_override_open_scene()
        sa_id = ws["site_activation"]["id"]
        assert get_site_activation(sa_id)["beds_effective"] == 2

        patch = api.patch_site(
            ws["site"]["id"],
            site_patch_payload(ws["site"]["version"], bed_capacity=50),
            eoc_manager_headers)
        patched = validate_success(patch, 200)
        assert patched["bed_capacity"] == 50

        after = get_site_activation(sa_id)
        assert after["beds_effective"] == 2
        assert after["beds_free"] == 2


class TestOptimisticConcurrency:
    def test_occ_episode_extension_stale_version_rejected(self, api,
                                                          eoc_manager_headers):
        """PRD §2.8: "`POST /api/episodes/{episode_id}/extensions` requires
        `expected_episode_version`, compared against the episode's current
        `version`."
        PRD §2.8: "When the supplied value does not match the entity's current
        `version` — because another writer has advanced the version since the
        client last read the entity — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "A successful extension replaces `scheduled_end_at`,
        increments `extension_count` by one, and advances the episode's
        `version` by one."

        Design: Corner/complexity_layers/occ_episode_extension_stale_version_rejected
        """
        ws = setup_active_episode_for_extensions()
        ep_id = ws["episode"]["id"]
        observed_version = get_episode(ep_id)["version"]

        first = api.extend_episode(
            ep_id, extension_payload("2026-08-13T00:00:00Z", observed_version),
            eoc_manager_headers)
        data = validate_success(first, 200)
        assert data["extension_count"] == 1

        # Replaying the same last-observed version is now stale.
        second = api.extend_episode(
            ep_id, extension_payload("2026-08-14T00:00:00Z", observed_version),
            eoc_manager_headers)
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        ep = get_episode(ep_id)
        assert ep["extension_count"] == 1
        assert parse_instant(ep["scheduled_end_at"]) == datetime(
            2026, 8, 13, tzinfo=timezone.utc)

    def test_occ_site_patch_stale_version_rejected(self, api,
                                                   eoc_manager_headers):
        """PRD §2.8: "`PATCH /api/sites/{site_id}` requires
        `expected_site_version`, compared against the site's current
        `version`."
        PRD §2.8: "When the supplied value does not match the entity's current
        `version` — because another writer has advanced the version since the
        client last read the entity — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_site_patch_stale_version_rejected
        """
        site = create_site()
        observed_version = site["version"]

        first = api.patch_site(
            site["id"],
            site_patch_payload(observed_version, bed_capacity=6),
            eoc_manager_headers)
        assert validate_success(first, 200)["bed_capacity"] == 6

        second = api.patch_site(
            site["id"],
            site_patch_payload(observed_version, bed_capacity=8),
            eoc_manager_headers)
        validate_error(second, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        reloaded = validate_success(api.get_site(site["id"], eoc_manager_headers))
        assert reloaded["bed_capacity"] == 6

    def test_extension_must_move_scheduled_end_forward(self, api,
                                                       eoc_manager_headers):
        """PRD §3.8: "an `EOCManager` supplies a `new_scheduled_end_at` that
        must be strictly later than the current `scheduled_end_at`, else
        `ERR_INVALID_WINDOW`, together with the OCC guard
        `expected_episode_version` (§2.8), whose mismatch is rejected with
        `ERR_STALE_VERSION`."

        Design: Corner/validations/extension_must_move_scheduled_end_forward
        """
        ws = setup_active_episode_for_extensions()
        ep_id = ws["episode"]["id"]
        observed_version = get_episode(ep_id)["version"]

        # The OCC version matches; only the backwards window fails.
        resp = api.extend_episode(
            ep_id, extension_payload("2026-08-11T00:00:00Z", observed_version),
            eoc_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW, expected_status=422)

        ep = get_episode(ep_id)
        assert ep["extension_count"] == 0
        assert parse_instant(ep["scheduled_end_at"]) == datetime(
            2026, 8, 12, tzinfo=timezone.utc)
