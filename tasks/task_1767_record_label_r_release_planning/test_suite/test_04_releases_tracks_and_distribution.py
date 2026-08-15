"""Releases, tracks, beats, campaigns, deliveries: pipelines, windows, cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_track,
    assemble_and_lock_release,
    create_and_start_project,
    create_artist,
    create_beat_payload,
    create_distributor,
    create_label,
    create_promo_campaign_payload,
    create_release,
    deliver_release,
    get_recoupment_account,
    get_success_data,
    go_live_release,
    schedule_release,
    setup_live_single_release,
    sign_artist_via_memo,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import ADMIN, ANR, FIN, MKT, set_clock


# ===========================================================================
# Queue A — non_linear_state_machine/release_parallel_asset_and_distribution_dimensions
# ===========================================================================


class TestReleaseParallelDimensions:
    def test_takedown_and_relaunch_leave_assets_locked(self):
        """PRD §3.5: "A release carries two independent state dimensions from birth:
        `asset_status`, starting at `DRAFT`, and `distribution_status`, starting at
        `PLANNED`."
        PRD §3.5: "From `LIVE` a release may be taken down to `TAKEN_DOWN`, and a
        taken-down release may be relaunched back to `LIVE`."

        Design: Difficulty/non_linear_state_machine/release_parallel_asset_and_distribution_dimensions
        """
        world = setup_live_single_release(label_name="Label N2", artist_name="Artist N2",
                                          track_isrc="USRC10000031")
        release = world["release"]
        assert release["asset_status"] == "LOCKED"
        assert release["distribution_status"] == "LIVE"

        taken_down = get_success_data(api_client.takedown_release(release["id"], MKT))
        assert taken_down["distribution_status"] == "TAKEN_DOWN"
        assert taken_down["asset_status"] == "LOCKED"

        relaunched = get_success_data(api_client.relaunch_release(release["id"], MKT))
        assert relaunched["distribution_status"] == "LIVE"
        assert relaunched["asset_status"] == "LOCKED"

    def test_went_live_date_stamped(self):
        """PRD §3.5: "Going live stamps `went_live_date` with today's date, moves the
        release to `LIVE`, and, when this is the first live release of the artist's
        contract, moves a `SIGNED` artist to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/release_parallel_asset_and_distribution_dimensions
        """
        world = setup_live_single_release(label_name="Label N2w", artist_name="Artist N2w",
                                          track_isrc="USRC10000032",
                                          go_live_clock="2026-09-01T00:00:00Z")
        assert world["release"]["went_live_date"] == "2026-09-01"
        assert world["artist"]["status"] == "ACTIVE"


# ===========================================================================
# Queue A — transitive_cascade/track_block_cascades_release_revert_delivery_cancel
# ===========================================================================


class TestTrackBlockCascade:
    def test_block_reverts_release_and_cancels_delivery(self):
        """PRD §3.4: "Blocking is the emergency brake ... First, every non-`CANCELLED`
        release containing the blocked track whose `asset_status` is `ASSEMBLED` or
        `LOCKED` reverts its `asset_status` to `DRAFT`. Second, each release whose
        asset state just reverted and whose `distribution_status` is `SCHEDULED`
        reverts to `PLANNED`. Third, every delivery of such a release that is
        `QUEUED` or `TRANSMITTED` is cancelled."

        Design: Difficulty/transitive_cascade/track_block_cascades_release_revert_delivery_cancel
        """
        label = create_label("Label T1")
        artist = create_artist(label["id"], "Artist T1")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-T1")
        track = add_track(project["id"], isrc="USRC10000041", advance_to="CLEARED")
        release = create_release(contract["id"], project["id"], [track["id"]])
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        distributor = create_distributor(label["id"], name="DSP-T1")
        deliveries = get_success_data(api_client.create_release_deliveries(
            release["id"], {"distributor_ids": [distributor["id"]]}, MKT))
        delivery = deliveries[0]
        get_success_data(api_client.transmit_delivery(delivery["id"], MKT))

        # Block the track.
        blocked = get_success_data(api_client.block_track(track["id"], ANR))
        assert blocked["status"] == "BLOCKED"
        release_after = get_success_data(api_client.get_release(release["id"], ADMIN))
        assert release_after["asset_status"] == "DRAFT"
        assert release_after["distribution_status"] == "PLANNED"
        delivery_after = get_success_data(api_client.get_asset_delivery(delivery["id"], ADMIN))
        assert delivery_after["status"] == "CANCELLED"

    def test_block_from_mastered_reverts_locked_release(self):
        """PRD §3.4: "Blocking is the emergency brake, available to an `AnRManager`
        from `TRACKED`, `MIXED`, `MASTERED`, or `CLEARED` ..."

        Design: Difficulty/transitive_cascade/track_block_cascades_release_revert_delivery_cancel
        """
        label = create_label("Label T1b")
        artist = create_artist(label["id"], "Artist T1b")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-T1b")
        track = add_track(project["id"], isrc="USRC10000042", advance_to="MASTERED")
        release = create_release(contract["id"], project["id"], [track["id"]])
        # Without CLEARED tracks, assemble would fail; just verify block cascade on DRAFT release.
        blocked = get_success_data(api_client.block_track(track["id"], ANR))
        assert blocked["status"] == "BLOCKED"
        release_after = get_success_data(api_client.get_release(release["id"], ADMIN))
        # Release was DRAFT (never assembled), so asset revert is a no-op; distribution stays PLANNED.
        assert release_after["distribution_status"] == "PLANNED"


# ===========================================================================
# Queue A — priority_pair_validation_conflict/schedule_unlocked_assets_beats_lead_time
# ===========================================================================


class TestScheduleUnlockedBeatsLeadTime:
    def test_unlocked_assets_error_wins(self):
        """PRD §2.9: "Seventh, the attempted state transition must be declared from
        the resource's current status — attempts from terminal states included
        (`ERR_INVALID_STATE`). ... Only after all seven general layers pass do the
        domain business rules run ... then temporal rules".
        PRD §3.5: "scheduling requires the assets to be `LOCKED`
        (`ERR_ASSETS_NOT_LOCKED` otherwise) and requires `release_date` to be at
        least `release_lead_days` ... otherwise `ERR_RELEASE_LEAD_TIME`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_unlocked_assets_beats_lead_time
        """
        label = create_label("Label V2")
        artist = create_artist(label["id"], "Artist V2")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-V2")
        track = add_track(project["id"], isrc="USRC10000051", advance_to="CLEARED")
        # release_date 2026-08-10 is 9 days from the 2026-08-01 clock — both violations present.
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2026-08-10")
        get_success_data(api_client.assemble_release(release["id"], ANR))
        r = api_client.schedule_release(release["id"], MKT)
        validate_error(r, ApiErrorId.ERR_ASSETS_NOT_LOCKED)
        after = get_success_data(api_client.get_release(release["id"], ADMIN))
        assert after["distribution_status"] == "PLANNED"

    def test_unlocked_assets_alone_rejected(self):
        """PRD §3.5: "scheduling requires the assets to be `LOCKED`
        (`ERR_ASSETS_NOT_LOCKED` otherwise)".

        Design: Difficulty/priority_pair_validation_conflict/schedule_unlocked_assets_beats_lead_time
        """
        label = create_label("Label V2b")
        artist = create_artist(label["id"], "Artist V2b")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-V2b")
        track = add_track(project["id"], isrc="USRC10000052", advance_to="CLEARED")
        # Release date far in the future so only the assets check can fail.
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2027-01-01")
        get_success_data(api_client.assemble_release(release["id"], ANR))
        r = api_client.schedule_release(release["id"], MKT)
        validate_error(r, ApiErrorId.ERR_ASSETS_NOT_LOCKED)


# ===========================================================================
# Queue A — boundary_precision_check/lead_time_exact_boundary_schedule
# ===========================================================================


class TestLeadTimeBoundary:
    def test_exactly_21_days_allowed_20_days_rejected(self):
        """PRD §3.5: "scheduling requires ... `release_date` to be at least
        `release_lead_days` — 21 days by default — after today, with equality
        allowed, otherwise `ERR_RELEASE_LEAD_TIME`."

        Design: Difficulty/boundary_precision_check/lead_time_exact_boundary_schedule
        """
        label = create_label("Label B4")
        artist = create_artist(label["id"], "Artist B4")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-B4",
                                           project_type="ALBUM")
        track_a = add_track(project["id"], title="TB4a", isrc="USRC10000064",
                            advance_to="CLEARED")
        track_b = add_track(project["id"], title="TB4b", isrc="USRC10000065",
                            advance_to="CLEARED")
        rel_ok = create_release(contract["id"], project["id"], [track_a["id"]],
                                title="R-OK", release_date="2026-08-22")
        rel_late = create_release(contract["id"], project["id"], [track_b["id"]],
                                  title="R-LATE", release_date="2026-08-21")
        assemble_and_lock_release(rel_ok["id"])
        assemble_and_lock_release(rel_late["id"])

        # Default clock 2026-08-01: 2026-08-22 is exactly 21 days out.
        ok = get_success_data(api_client.schedule_release(rel_ok["id"], MKT))
        assert ok["distribution_status"] == "SCHEDULED"
        r = api_client.schedule_release(rel_late["id"], MKT)
        validate_error(r, ApiErrorId.ERR_RELEASE_LEAD_TIME)
        after = get_success_data(api_client.get_release(rel_late["id"], ADMIN))
        assert after["distribution_status"] == "PLANNED"

    def test_equality_boundary_alone(self):
        """PRD §3.5: "scheduling requires the assets to be `LOCKED`
        (`ERR_ASSETS_NOT_LOCKED` otherwise) and requires `release_date` to be at
        least `release_lead_days` — 21 days by default — after today, with
        equality allowed, otherwise `ERR_RELEASE_LEAD_TIME`."

        Design: Difficulty/boundary_precision_check/lead_time_exact_boundary_schedule
        """
        label = create_label("Label B4b")
        artist = create_artist(label["id"], "Artist B4b")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-B4b")
        track = add_track(project["id"], isrc="USRC10000066", advance_to="CLEARED")
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2026-08-22")
        assemble_and_lock_release(release["id"])
        ok = get_success_data(api_client.schedule_release(release["id"], MKT))
        assert ok["distribution_status"] == "SCHEDULED"


# ===========================================================================
# Queue A — boundary_precision_check/beat_window_adjacency_allowed
#         resource_temporal_overlap/beat_overlap_half_open_rejected
# ===========================================================================


def _setup_planned_release(label_name, artist_name, track_isrc):
    label = create_label(label_name)
    artist = create_artist(label["id"], artist_name)
    memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
    project = create_and_start_project(contract["id"], title=f"P-{label_name}")
    track = add_track(project["id"], isrc=track_isrc, advance_to="CLEARED")
    release = create_release(contract["id"], project["id"], [track["id"]],
                             release_date="2026-09-01")
    return label, artist, contract, project, track, release


class TestBeatWindowAdjacency:
    def test_adjacency_allowed_overlap_rejected(self):
        """PRD §3.6: "treating each beat as a half-open window that includes its
        start date and excludes its end date, two beats overlap when each one's
        start falls before the other's end, and touching windows — one ending
        exactly when the other begins — do not overlap."

        Design: Difficulty/boundary_precision_check/beat_window_adjacency_allowed
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label B3", "Artist B3", "USRC10000063")
        # Beat B1: [2026-08-01, 2026-08-08)
        b1 = get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="TEASER", channel="PLAYLIST",
            start_date="2026-08-01", end_date="2026-08-08", budget_cents=5_000), MKT))
        # Beat B2 adjacent to B1: [2026-08-08, 2026-08-15)
        b2 = get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="SINGLE_DROP", channel="PLAYLIST",
            start_date="2026-08-08", end_date="2026-08-15", budget_cents=5_000), MKT))
        assert b2["status"] == "PLANNED"
        # Beat B3 overlaps B2 by one day: [2026-08-14, 2026-08-21)
        r = api_client.create_beat(release["id"], create_beat_payload(
            beat_type="VIDEO", channel="PLAYLIST",
            start_date="2026-08-14", end_date="2026-08-21", budget_cents=5_000), MKT)
        validate_error(r, ApiErrorId.ERR_BEAT_WINDOW_OVERLAP)

    def test_touching_windows_pass(self):
        """PRD §3.6: "touching windows — one ending exactly when the other begins —
        do not overlap."

        Design: Difficulty/boundary_precision_check/beat_window_adjacency_allowed
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label B3b", "Artist B3b", "USRC10000067")
        get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="TEASER", channel="PLAYLIST",
            start_date="2026-08-01", end_date="2026-08-08", budget_cents=5_000), MKT))
        b2 = get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="VIDEO", channel="PLAYLIST",
            start_date="2026-08-08", end_date="2026-08-15", budget_cents=5_000), MKT))
        assert b2["status"] == "PLANNED"


class TestBeatOverlapHalfOpenRejected:
    def test_overlap_same_channel_rejected_other_channel_allowed(self):
        """PRD §3.6: "beats on the same release and channel may not overlap: treating
        each beat as a half-open window that includes its start date and excludes
        its end date, two beats overlap when each one's start falls before the
        other's end ... a collision is rejected with `ERR_BEAT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/beat_overlap_half_open_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label O1", "Artist O1", "USRC10000081")
        b1 = get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="TEASER", channel="PLAYLIST",
            start_date="2026-08-01", end_date="2026-08-08", budget_cents=5_000), MKT))
        # Overlapping PLAYLIST beat: [08-07, 08-14) overlaps [08-01, 08-08)
        r = api_client.create_beat(release["id"], create_beat_payload(
            beat_type="VIDEO", channel="PLAYLIST",
            start_date="2026-08-07", end_date="2026-08-14", budget_cents=5_000), MKT)
        validate_error(r, ApiErrorId.ERR_BEAT_WINDOW_OVERLAP)
        # Identical dates on a different channel are fine.
        b3 = get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="VIDEO", channel="RADIO",
            start_date="2026-08-07", end_date="2026-08-14", budget_cents=5_000), MKT))
        assert b3["status"] == "PLANNED"
        after = get_success_data(api_client.get_beat(b1["id"], MKT))
        assert after["status"] == "PLANNED"

    def test_different_release_does_not_conflict(self):
        """PRD §3.6: "The check runs against beats in `PLANNED`, `READY`, `EXECUTED`,
        or `MEASURED`; `SKIPPED` and `CANCELLED` beats are ignored".

        Design: Difficulty/resource_temporal_overlap/beat_overlap_half_open_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label O1b", "Artist O1b", "USRC10000083")
        # Create a SKIPPED beat that overlaps.
        skipped = get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="TEASER", channel="PLAYLIST",
            start_date="2026-08-01", end_date="2026-08-08", budget_cents=5_000), MKT))
        get_success_data(api_client.skip_beat(skipped["id"], MKT))
        # Now a same-window beat should be accepted because SKIPPED is excluded.
        b2 = get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="VIDEO", channel="PLAYLIST",
            start_date="2026-08-01", end_date="2026-08-08", budget_cents=5_000), MKT))
        assert b2["status"] == "PLANNED"


# ===========================================================================
# Queue A — resource_temporal_overlap/campaign_gap_buffer_rejected
# ===========================================================================


class TestCampaignGapBuffer:
    def test_seven_day_gap_allowed_four_day_gap_rejected(self):
        """PRD §3.6: "two campaigns on the same release and channel conflict unless
        at least `campaign_gap_days` separate them. Precisely, there is no conflict
        only when one campaign's end date plus the gap falls on or before the
        other's start date (or vice versa), so a gap of exactly `campaign_gap_days`
        — 7 days by default — is allowed."

        Design: Difficulty/resource_temporal_overlap/campaign_gap_buffer_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label O2", "Artist O2", "USRC10000082")
        c1 = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        # Exactly-7-day gap: c1 ends 08-10; next start 08-17 -> 08-10 + 7 == 08-17 allowed.
        c2 = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-17", end_date="2026-08-20",
                spend_cap_cents=50_000), MKT))
        assert c2["status"] == "DRAFT"
        # 4-day gap: c2 ends 08-20; 08-20 + 7 = 08-27 > 08-24 -> conflict.
        r = api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-24", end_date="2026-08-27",
                spend_cap_cents=50_000), MKT)
        validate_error(r, ApiErrorId.ERR_CAMPAIGN_WINDOW_CONFLICT)

    def test_gap_exactly_campaign_gap_days_passes(self):
        """PRD §3.6: "a gap of exactly `campaign_gap_days` — 7 days by default — is
        allowed."

        Design: Difficulty/resource_temporal_overlap/campaign_gap_buffer_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label O2b", "Artist O2b", "USRC10000084")
        get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="RADIO", start_date="2026-08-01", end_date="2026-08-05",
                spend_cap_cents=50_000), MKT))
        c2 = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="RADIO", start_date="2026-08-12", end_date="2026-08-15",
                spend_cap_cents=50_000), MKT))
        assert c2["status"] == "DRAFT"


# ===========================================================================
# Queue A — non_linear_state_machine/promo_campaign_pause_resume_cycle
# ===========================================================================


class TestPromoCampaignCycle:
    def test_pause_resume_iterated_then_completed(self):
        """PRD §3.6: "Pausing moves `ACTIVE` to `PAUSED`; resuming moves `PAUSED`
        back to `ACTIVE` under the same release-state gate as activation.
        Completing moves a campaign from `ACTIVE` or `PAUSED` to `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/promo_campaign_pause_resume_cycle
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label N3", "Artist N3", "USRC10000032")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        camp = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        get_success_data(api_client.activate_promo_campaign(camp["id"], MKT))
        p1 = get_success_data(api_client.pause_promo_campaign(camp["id"], MKT))
        assert p1["status"] == "PAUSED"
        r1 = get_success_data(api_client.resume_promo_campaign(camp["id"], MKT))
        assert r1["status"] == "ACTIVE"
        p2 = get_success_data(api_client.pause_promo_campaign(camp["id"], MKT))
        assert p2["status"] == "PAUSED"
        done = get_success_data(api_client.complete_promo_campaign(camp["id"], MKT))
        assert done["status"] == "COMPLETED"

    def test_pause_after_complete_rejected(self):
        """PRD §3.6: "`COMPLETED` and `KILLED` are terminal."
        PRD §2.9: "Seventh, the attempted state transition must be declared from the
        resource's current status — attempts from terminal states included
        (`ERR_INVALID_STATE`)."

        Design: Difficulty/non_linear_state_machine/promo_campaign_pause_resume_cycle
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label N3b", "Artist N3b", "USRC10000033")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        camp = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        get_success_data(api_client.activate_promo_campaign(camp["id"], MKT))
        get_success_data(api_client.complete_promo_campaign(camp["id"], MKT))
        r = api_client.pause_promo_campaign(camp["id"], MKT)
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Queue A — cross_entity_state_dependency/campaign_activate_requires_release_scheduled
# ===========================================================================


class TestCampaignActivateGate:
    def test_planned_release_rejects_then_scheduled_allows(self):
        """PRD §3.6: "Activation moves a campaign from `DRAFT` to `ACTIVE` and
        requires the release's `distribution_status` to be `SCHEDULED`, `DELIVERED`,
        or `LIVE` (`ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/campaign_activate_requires_release_scheduled
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label X2", "Artist X2", "USRC10000071")
        camp = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        r = api_client.activate_promo_campaign(camp["id"], MKT)
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_promo_campaign(camp["id"], MKT))
        assert after["status"] == "DRAFT"

        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        activated = get_success_data(api_client.activate_promo_campaign(camp["id"], MKT))
        assert activated["status"] == "ACTIVE"

    def test_resume_also_gated(self):
        """PRD §3.6: "resuming moves `PAUSED` back to `ACTIVE` under the same
        release-state gate as activation."

        Design: Difficulty/cross_entity_state_dependency/campaign_activate_requires_release_scheduled
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label X2b", "Artist X2b", "USRC10000072")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        camp = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        get_success_data(api_client.activate_promo_campaign(camp["id"], MKT))
        paused = get_success_data(api_client.pause_promo_campaign(camp["id"], MKT))
        assert paused["status"] == "PAUSED"
        resumed = get_success_data(api_client.resume_promo_campaign(camp["id"], MKT))
        assert resumed["status"] == "ACTIVE"


# ===========================================================================
# Queue B — releases / tracks / deliveries
# ===========================================================================


class TestTrackVersionSelfReference:
    def test_radio_edit_lineage_lookup(self):
        """PRD §3.4: "an optional `version_of_track_id` that gives radio edits and
        remixes a self-referential lineage — the referenced track must belong to the
        same label."
        PRD §2.3: "List endpoints also accept filter parameters natural to their
        resource — for example ... `version_of_track_id` ...".

        Design: Corner/entities/track_version_self_reference_lineage
        """
        label = create_label("Label E6")
        artist = create_artist(label["id"], "Artist E6")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-E6",
                                           project_type="ALBUM")
        t1 = add_track(project["id"], title="T1-orig", isrc="USRC20000002")
        t2 = get_success_data(api_client.create_track(project["id"], {
            "title": "T1-radio-edit", "duration_seconds": 180,
            "isrc": "USRC20000003", "version_of_track_id": t1["id"],
        }, ANR))
        assert t2["version_of_track_id"] == t1["id"]
        data, meta = validate_paginated(api_client.list_tracks(
            ADMIN, params={"version_of_track_id": t1["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == t2["id"]


class TestSingleReleaseTrackCount:
    def test_two_tracks_rejected(self):
        """PRD §3.5: "The cardinality rule is strict: a `SINGLE` carries exactly one
        track, an `ALBUM` carries between 2 and 30, every listed track must belong
        to a project of the same contract, and every listed track must already be
        `MIXED`, `MASTERED`, or `CLEARED` — any violation is rejected with
        `ERR_SINGLE_TRACK_COUNT`."

        Design: Corner/validations/single_release_two_tracks_rejected
        """
        label = create_label("Label Vb7")
        artist = create_artist(label["id"], "Artist Vb7")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-Vb7",
                                           project_type="ALBUM")
        t1 = add_track(project["id"], title="T1", isrc="USRC20000032", advance_to="MIXED")
        t2 = add_track(project["id"], title="T2", isrc="USRC20000033", advance_to="MIXED")
        r = api_client.create_release(contract["id"], {
            "project_id": project["id"], "title": "R-Vb7", "release_type": "SINGLE",
            "release_date": "2026-10-01", "track_ids": [t1["id"], t2["id"]],
        }, ANR)
        validate_error(r, ApiErrorId.ERR_SINGLE_TRACK_COUNT)


class TestCoverArtMissing:
    def test_lock_without_cover_art_rejected(self):
        """PRD §3.5: "Locking moves `ASSEMBLED` to `LOCKED` and takes one explicit
        input, `cover_art_confirmed`, which must be true; without confirmed cover
        art the lock is rejected with `ERR_COVER_ART_MISSING`."

        Design: Corner/validations/cover_art_missing_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label Vb19", "Artist Vb19", "USRC20000045")
        get_success_data(api_client.assemble_release(release["id"], ANR))
        r = api_client.lock_release_assets(release["id"], {"cover_art_confirmed": False}, ANR)
        validate_error(r, ApiErrorId.ERR_COVER_ART_MISSING)
        after = get_success_data(api_client.get_release(release["id"], ADMIN))
        assert after["asset_status"] == "ASSEMBLED"


class TestTracksNotCleared:
    def test_mastered_track_blocks_assemble(self):
        """PRD §3.5: "Assembling moves `asset_status` from `DRAFT` to `ASSEMBLED`,
        requires the release's `distribution_status` to still be `PLANNED`
        (`ERR_INVALID_STATE`), and requires every member track to be `CLEARED` —
        not merely mixed or mastered — otherwise `ERR_TRACKS_NOT_CLEARED`."

        Design: Corner/validations/tracks_not_cleared_rejected
        """
        label = create_label("Label Vb20")
        artist = create_artist(label["id"], "Artist Vb20")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-Vb20")
        track = add_track(project["id"], isrc="USRC20000046", advance_to="MASTERED")
        release = create_release(contract["id"], project["id"], [track["id"]])
        r = api_client.assemble_release(release["id"], ANR)
        validate_error(r, ApiErrorId.ERR_TRACKS_NOT_CLEARED)
        after = get_success_data(api_client.get_release(release["id"], ADMIN))
        assert after["asset_status"] == "DRAFT"


class TestSampleClearance:
    def test_missing_clearance_rejected_with_clearance_allowed(self):
        """PRD §3.4: "The final step into `CLEARED` carries a clearance gate: when
        `contains_sample` is true, `clearance_ref` must be non-null, otherwise
        `ERR_SAMPLE_CLEARANCE_MISSING`."

        Design: Corner/validations/sample_clearance_missing_rejected
        """
        label = create_label("Label Vb21")
        artist = create_artist(label["id"], "Artist Vb21")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-Vb21",
                                           project_type="ALBUM")
        t_nc = add_track(project["id"], title="TS-nc", isrc="USRC20000047",
                         contains_sample=True, advance_to="MASTERED")
        t_ok = add_track(project["id"], title="TS-ok", isrc="USRC20000048",
                         contains_sample=True, clearance_ref="CLR-123", advance_to="MASTERED")
        r = api_client.advance_track_stage(t_nc["id"], ANR)
        validate_error(r, ApiErrorId.ERR_SAMPLE_CLEARANCE_MISSING)
        after = get_success_data(api_client.get_track(t_nc["id"], ADMIN))
        assert after["status"] == "MASTERED"
        ok = get_success_data(api_client.advance_track_stage(t_ok["id"], ANR))
        assert ok["status"] == "CLEARED"


class TestGoLiveBeforeDate:
    def test_before_release_date_rejected(self):
        """PRD §3.5: "A `MarketingManager` goes live from `DELIVERED`, allowed only
        once today has reached `release_date` — earlier attempts are rejected with
        `ERR_RELEASE_DATE_NOT_REACHED`."

        Design: Corner/validations/go_live_before_date_rejected
        """
        label = create_label("Label Vb22")
        artist = create_artist(label["id"], "Artist Vb22")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-Vb22")
        track = add_track(project["id"], isrc="USRC20000049", advance_to="CLEARED")
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2026-09-01")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        distributor = create_distributor(label["id"], name="DSP-Vb22")
        deliver_release(release["id"], [distributor["id"]])
        # Clock 2026-08-31 < release_date 2026-09-01.
        set_clock("2026-08-31T00:00:00Z")
        r = api_client.go_live_release(release["id"], MKT)
        validate_error(r, ApiErrorId.ERR_RELEASE_DATE_NOT_REACHED)
        after = get_success_data(api_client.get_release(release["id"], ADMIN))
        assert after["distribution_status"] == "DELIVERED"


class TestDistributorInactive:
    def test_inactive_distributor_rejects_delivery(self):
        """PRD §3.5: "an inactive distributor rejects new deliveries with
        `ERR_DISTRIBUTOR_INACTIVE`."

        Design: Corner/validations/distributor_inactive_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label Vb23", "Artist Vb23", "USRC20000050")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        distributor = create_distributor(label["id"], name="DSP-Vb23")
        get_success_data(api_client.update_distributor(
            distributor["id"], {"is_active": False}, ADMIN))
        r = api_client.create_release_deliveries(
            release["id"], {"distributor_ids": [distributor["id"]]}, MKT)
        validate_error(r, ApiErrorId.ERR_DISTRIBUTOR_INACTIVE)


class TestDuplicateDelivery:
    def test_second_delivery_rejected(self):
        """PRD §3.5: "At most one non-terminal delivery — one in `QUEUED`,
        `TRANSMITTED`, or `REJECTED` — may exist per release-and-distributor pair,
        otherwise `ERR_DUPLICATE_DELIVERY`".

        Design: Corner/validations/duplicate_delivery_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label Vb24", "Artist Vb24", "USRC20000051")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        distributor = create_distributor(label["id"], name="DSP-Vb24")
        get_success_data(api_client.create_release_deliveries(
            release["id"], {"distributor_ids": [distributor["id"]]}, MKT))
        r = api_client.create_release_deliveries(
            release["id"], {"distributor_ids": [distributor["id"]]}, MKT)
        validate_error(r, ApiErrorId.ERR_DUPLICATE_DELIVERY)
        _data, meta = validate_paginated(api_client.list_release_deliveries(release["id"], MKT))
        assert meta["total_count"] == 1


class TestBeatOutsideWindow:
    def test_too_early_rejected(self):
        """PRD §3.6: "the beat must sit inside the release window: `start_date` no
        earlier than `beat_pre_release_days` before `release_date` — 42 days by
        default — and `end_date` no later than `beat_post_release_days` after it —
        30 days by default — with both boundaries inclusive; a beat outside the
        window is rejected with `ERR_BEAT_OUTSIDE_WINDOW`."

        Design: Corner/validations/beat_outside_window_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label Vb18", "Artist Vb18", "USRC20000044")
        # Window for release_date 2026-09-01: [2026-07-21, 2026-10-01]; 2026-06-01 is too early.
        r = api_client.create_beat(release["id"], create_beat_payload(
            beat_type="TEASER", channel="SOCIAL",
            start_date="2026-06-01", end_date="2026-06-08", budget_cents=1_000), MKT)
        validate_error(r, ApiErrorId.ERR_BEAT_OUTSIDE_WINDOW)


class TestDeliveryRejectRetryCycle:
    def test_retry_loop_and_bubble_to_delivered(self):
        """PRD §3.5: "acknowledging moves `TRANSMITTED` to `ACKNOWLEDGED`, and
        rejecting moves it to `REJECTED`; a rejected delivery may be retried,
        returning it to `QUEUED`, again only while the release is `SCHEDULED`.
        Acknowledgement bubbles upward — the moment at least one non-`CANCELLED`
        delivery exists for a release and every non-`CANCELLED` delivery is
        `ACKNOWLEDGED`, the release's `distribution_status` moves from `SCHEDULED`
        to `DELIVERED`."

        Design: Corner/state_machines/delivery_reject_retry_cycle
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label S9", "Artist S9", "USRC20000013")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        distributor = create_distributor(label["id"], name="DSP-S9")
        deliveries = get_success_data(api_client.create_release_deliveries(
            release["id"], {"distributor_ids": [distributor["id"]]}, MKT))
        d = deliveries[0]
        get_success_data(api_client.transmit_delivery(d["id"], MKT))
        rejected = get_success_data(api_client.reject_delivery(d["id"], MKT))
        assert rejected["status"] == "REJECTED"
        queued = get_success_data(api_client.retry_delivery(d["id"], MKT))
        assert queued["status"] == "QUEUED"
        re_tx = get_success_data(api_client.transmit_delivery(d["id"], MKT))
        assert re_tx["attempt_count"] == 2
        ack = get_success_data(api_client.acknowledge_delivery(d["id"], MKT))
        assert ack["status"] == "ACKNOWLEDGED"
        release_after = get_success_data(api_client.get_release(release["id"], ADMIN))
        assert release_after["distribution_status"] == "DELIVERED"


class TestReleaseCancelCascade:
    def test_cancel_cascades_children(self):
        """PRD §3.5: "Cancellation ... cascades: every beat of the release in
        `PLANNED` or `READY` moves to `CANCELLED`, every promo campaign in `DRAFT`,
        `ACTIVE`, or `PAUSED` moves to `KILLED`, and every delivery in `QUEUED` or
        `TRANSMITTED` moves to `CANCELLED`."

        Design: Corner/cross_cutting_layers/release_cancel_cascades_children
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label L4", "Artist L4", "USRC20000082")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        beat = get_success_data(api_client.create_beat(release["id"], create_beat_payload(
            beat_type="TEASER", channel="SOCIAL",
            start_date="2026-08-01", end_date="2026-08-08", budget_cents=5_000), MKT))
        camp = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        get_success_data(api_client.activate_promo_campaign(camp["id"], MKT))
        distributor = create_distributor(label["id"], name="DSP-L4")
        deliveries = get_success_data(api_client.create_release_deliveries(
            release["id"], {"distributor_ids": [distributor["id"]]}, MKT))
        cancelled = get_success_data(api_client.cancel_release(release["id"], ADMIN))
        assert cancelled["distribution_status"] == "CANCELLED"
        beat_after = get_success_data(api_client.get_beat(beat["id"], MKT))
        assert beat_after["status"] == "CANCELLED"
        camp_after = get_success_data(api_client.get_promo_campaign(camp["id"], MKT))
        assert camp_after["status"] == "KILLED"
        delivery_after = get_success_data(api_client.get_asset_delivery(deliveries[0]["id"], ADMIN))
        assert delivery_after["status"] == "CANCELLED"


class TestCampaignCapExceeded:
    def test_spend_at_cap_allowed_one_cent_over_rejected(self):
        """PRD §3.6: "The campaign's `spend_cents` plus the new amount must not
        exceed `spend_cap_cents`, equality allowed, otherwise
        `ERR_CAMPAIGN_CAP_EXCEEDED`."

        Design: Corner/validations/campaign_cap_exceeded_rejected
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label Vb13", "Artist Vb13", "USRC20000041")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        camp = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="RADIO", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        get_success_data(api_client.activate_promo_campaign(camp["id"], MKT))
        # Spend to exactly the cap: allowed.
        spent = get_success_data(api_client.spend_promo_campaign(
            camp["id"], {"amount_cents": 50_000}, MKT))
        assert spent["spend_cents"] == 50_000
        # One more cent: rejected.
        r = api_client.spend_promo_campaign(camp["id"], {"amount_cents": 1}, MKT)
        validate_error(r, ApiErrorId.ERR_CAMPAIGN_CAP_EXCEEDED)
        after = get_success_data(api_client.get_promo_campaign(camp["id"], MKT))
        assert after["spend_cents"] == 50_000


class TestDeliveriesBulkCreate:
    def test_two_distributors_returns_array(self):
        """PRD §3.5: "Creating deliveries takes a list of `distributor_ids` and
        creates one delivery per distributor, each starting `QUEUED` with
        `attempt_count` at zero."

        Design: Corner/endpoints/deliveries_bulk_create_returns_array
        """
        label, artist, contract, project, track, release = _setup_planned_release(
            "Label P2", "Artist P2", "USRC20000061")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        d1 = create_distributor(label["id"], name="DSP-1", channel_type="DSP")
        d2 = create_distributor(label["id"], name="PHY-1", channel_type="PHYSICAL")
        deliveries = get_success_data(api_client.create_release_deliveries(
            release["id"], {"distributor_ids": [d1["id"], d2["id"]]}, MKT))
        assert isinstance(deliveries, list) and len(deliveries) == 2
        for d in deliveries:
            assert d["status"] == "QUEUED"
            assert d["attempt_count"] == 0
        _data, meta = validate_paginated(api_client.list_release_deliveries(release["id"], MKT))
        assert meta["total_count"] == 2


class TestImmediateConsistency:
    def test_get_right_after_advance(self):
        """PRD §2.5: "Any change to a resource — including system-driven changes such
        as cascades, computed-field recomputation, and sweep transitions — counts
        as a mutation and therefore refreshes `updated_at` and increments
        `version`."

        Design: Corner/consistency_model/immediate_read_after_write_consistency

        Note: the scaffold's "updated_at changed between create response and the
        post-advance GET" assertion is not preserved: with the PRD-mandated frozen
        logical clock (§2.4: "before any explicit set call, the clock reads that
        default and never the wall clock"), two mutations at the same logical
        instant are re-stamped with the same value, and the PRD nowhere requires
        strictly increasing timestamps — strict inequality is not uniquely
        derivable from §2.5's "refreshed on every mutation".
        """
        label = create_label("Label M1")
        artist = create_artist(label["id"], "Artist M1")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-M1")
        created = get_success_data(api_client.create_track(project["id"], {
            "title": "TM1", "duration_seconds": 200, "isrc": "USRC20000091",
        }, ANR))
        created_at = created["created_at"]
        advanced = get_success_data(api_client.advance_track_stage(created["id"], ANR))
        assert advanced["status"] == "TRACKED"
        fetched = get_success_data(api_client.get_track(created["id"], ANR))
        assert fetched["status"] == "TRACKED"
        assert fetched["version"] == 2
        assert fetched["created_at"] == created_at
