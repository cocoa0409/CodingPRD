"""Donor lifecycle: the inactivity-window lapse boundary and the automatic
PROSPECT -> ACTIVE transition on first acknowledgement.

Difficulty queue: resource_temporal_overlap (lapse window). Corner queue:
state_machines (donor first acknowledge).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_open_campaign, create_donor, create_acknowledged_gift, set_clock,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


# ---------------------------------------------------------------------------
# Difficulty Rule 8 — lapse window elapsed-duration inclusive boundary
# ---------------------------------------------------------------------------
class TestLapseWindowBoundary:
    def test_lapse_at_exactly_threshold_days_succeeds(self, api):
        """PRD §3.7: "the transition `ACTIVE → LAPSED` is permitted only when the
        elapsed time from the donor's `last_gift_at` to the current clock is at least
        the donor's `lapse_threshold_days` days".

        last_gift_at 2026-01-01, threshold 30 days, clock exactly 2026-01-31 (30 days
        elapsed) -> the donor may lapse (inclusive boundary).

        Design: Difficulty/resource_temporal_overlap/lapse_window_inactivity_threshold_inclusive
        """
        set_clock("2026-01-01T00:00:00Z")
        camp = create_open_campaign(starts_on="2025-12-01T00:00:00Z", ends_on="2026-12-31T00:00:00Z")
        donor = create_donor(lapse_threshold_days=30)
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=5000)
        set_clock("2026-01-31T00:00:00Z")  # exactly 30 days elapsed
        data = validate_success(api.flag_lapsed_donor(donor["id"], DR))
        assert data["lifecycle_status"] == "LAPSED", "at exactly the threshold day the donor may lapse"

    def test_lapse_one_day_before_threshold_rejected(self, api):
        """PRD §3.7: "a request that does not meet that window is rejected with
        `ERR_LAPSE_WINDOW_NOT_MET` (HTTP 409)."

        29 days elapsed (one short of the 30-day threshold) -> rejected.

        Design: Difficulty/resource_temporal_overlap/lapse_window_inactivity_threshold_inclusive
        """
        set_clock("2026-01-01T00:00:00Z")
        camp = create_open_campaign(starts_on="2025-12-01T00:00:00Z", ends_on="2026-12-31T00:00:00Z")
        donor = create_donor(lapse_threshold_days=30)
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=5000)
        set_clock("2026-01-30T00:00:00Z")  # 29 days elapsed
        validate_error(api.flag_lapsed_donor(donor["id"], DR), ApiErrorId.ERR_LAPSE_WINDOW_NOT_MET.value)


# ---------------------------------------------------------------------------
# Corner — donor first acknowledge sets ACTIVE
# ---------------------------------------------------------------------------
class TestDonorFirstAcknowledge:
    def test_first_acknowledge_sets_active_and_last_gift_at(self, api):
        """PRD §3.7: "A `PROSPECT` donor becomes `ACTIVE` automatically the first time
        a gift for that donor is acknowledged (the same step that first sets
        `last_gift_at`)."

        Design: Corner/state_machines/donor_first_acknowledge_sets_active
        """
        camp = create_open_campaign(goal_cents=1000000)
        donor = create_donor()
        assert donor["lifecycle_status"] == "PROSPECT"
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=5000)
        data = validate_success(api.get_donor(donor["id"], GA))
        assert data["lifecycle_status"] == "ACTIVE", "first acknowledgement auto-activates the donor"
        assert data["last_gift_at"] is not None, "last_gift_at is stamped on first acknowledgement"
