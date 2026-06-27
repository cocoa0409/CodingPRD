"""Temporal rules: concurrent campaign-window overlap, investor-update quiet period, supersede
cascade, and the update-publish cross-entity state guard.

Queue-A: resource_temporal_overlap (campaign window + quiet period),
cross_entity_state_dependency (update publish requires LIVE/FUNDED offering).
Queue-B: state_machines (supersede cascade) corner.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_issuer_headers, make_compliance_officer_headers,
    create_offering_payload, create_investor_update_payload,
    create_verified_issuer, create_draft_offering, create_qualified_offering,
    create_live_offering, set_clock,
    create_draft_update,
    api_client,
)

CO = make_compliance_officer_headers()


# ============================================================================
# Campaign-window closed-interval overlap (queue A: resource_temporal_overlap)
# ============================================================================

def test_campaign_window_overlap_rejected_on_golive(api):
    """PRD §3.3: "Two such windows overlap when the existing offering's `live_at` is strictly
    before this offering's `deadline_at` and the current logical-clock instant is strictly before
    the existing offering's `deadline_at` ... A genuine overlap is rejected with
    `ERR_CAMPAIGN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_overlap_on_offering
    """
    set_clock("2026-02-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Ov Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    # Offering A LIVE: live_at 2026-02-01, deadline 2026-04-01.
    create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000,
                         deadline_at="2026-04-01T00:00:00Z")
    # Offering B QUALIFIED, deadline 2026-05-01.
    off_b = create_qualified_offering(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000,
                                      deadline_at="2026-05-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")  # B's window [2026-03-01, 2026-05-01] overlaps A's [.., 2026-04-01]
    resp = api.go_live(off_b["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_OVERLAP, expected_status=409)
    after = validate_success(api.get_offering(off_b["id"], headers=issuer_headers))
    assert after["status"] == "DRAFT"


def test_touching_campaign_windows_are_permitted(api):
    """PRD §3.3: "because both comparisons are strict, two windows that merely touch at a single
    instant — one window's `deadline_at` equal to the other's `live_at` — do not overlap and are
    permitted."

    Design: Difficulty/resource_temporal_overlap/campaign_window_closed_interval_overlap_on_offering
    """
    set_clock("2026-02-01T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Touch Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    # Offering A LIVE: live_at 2026-02-01, deadline 2026-04-01.
    create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000,
                         deadline_at="2026-04-01T00:00:00Z")
    # Offering B QUALIFIED, deadline 2026-06-01; B goes live at exactly A's deadline (2026-04-01).
    off_b = create_qualified_offering(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000,
                                      deadline_at="2026-06-01T00:00:00Z")
    set_clock("2026-04-01T00:00:00Z")  # now == A.deadline_at -> touching, allowed (strict <).
    live_b = validate_success(api.go_live(off_b["id"], headers=issuer_headers))
    assert live_b["status"] == "LIVE"


# ============================================================================
# Investor-update quiet period point-buffer (queue A: resource_temporal_overlap)
# ============================================================================

def test_quiet_period_publish_exactly_24h_later_rejected(api):
    """PRD §3.8: "publication is admissible only if there is no prior `PUBLISHED` update on the
    same offering, or the current logical-clock instant is strictly more than twenty-four hours
    after the most recent prior `PUBLISHED` update's `published_at` on that offering. This is a
    point-event-with-mandatory-gap rule, not an interval overlap: a publish exactly twenty-four
    hours after the prior one is still too soon and is rejected with `ERR_UPDATE_QUIET_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/update_quiet_period_point_buffer_on_investor_update
    """
    set_clock("2026-02-15T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Qp Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000,
                                    deadline_at="2026-12-01T00:00:00Z")
    u1 = create_draft_update(offering["id"], issuer["id"], title="U1", body="First")
    set_clock("2026-03-01T00:00:00Z")
    validate_success(api.publish_investor_update(u1["id"], headers=issuer_headers))
    u2 = create_draft_update(offering["id"], issuer["id"], title="U2", body="Second")
    set_clock("2026-03-02T00:00:00Z")  # exactly 24h after u1 -> not strictly > 24h.
    resp = api.publish_investor_update(u2["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_UPDATE_QUIET_PERIOD, expected_status=409)
    after = validate_success(api.get_investor_update(u2["id"], headers=issuer_headers))
    assert after["status"] == "DRAFT"


def test_quiet_period_publish_beyond_24h_admitted(api):
    """PRD §3.8: "the current logical-clock instant is strictly more than twenty-four hours after
    the most recent prior `PUBLISHED` update's `published_at` on that offering."

    Design: Difficulty/resource_temporal_overlap/update_quiet_period_point_buffer_on_investor_update
    """
    set_clock("2026-02-15T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Qp2 Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000,
                                    deadline_at="2026-12-01T00:00:00Z")
    u1 = create_draft_update(offering["id"], issuer["id"], title="U1", body="First")
    set_clock("2026-03-01T00:00:00Z")
    validate_success(api.publish_investor_update(u1["id"], headers=issuer_headers))
    u2 = create_draft_update(offering["id"], issuer["id"], title="U2", body="Second")
    set_clock("2026-03-02T00:00:01Z")  # strictly more than 24h after u1 -> admitted.
    published = validate_success(api.publish_investor_update(u2["id"], headers=issuer_headers))
    assert published["status"] == "PUBLISHED"


# ============================================================================
# Cross-entity: update publish requires LIVE/FUNDED offering (queue A)
# ============================================================================

def test_publish_update_requires_offering_live_or_funded(api):
    """PRD §3.8: "Publishing advances `DRAFT → PUBLISHED` and is permitted only when the update is
    in `DRAFT` and the parent offering is in `LIVE` or `FUNDED` — updates cannot be published on a
    `DRAFT`, `CANCELLED`, or `FAILED` offering."

    Design: Difficulty/cross_entity_state_dependency/update_publish_requires_offering_live_or_funded
    """
    issuer = create_verified_issuer(legal_name="Up Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_draft_offering(issuer["id"])  # never gone live
    update = create_draft_update(offering["id"], issuer["id"], title="Hello", body="First update")
    resp = api.publish_investor_update(update["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_investor_update(update["id"], headers=issuer_headers))
    assert after["status"] == "DRAFT"


def test_publish_update_on_draft_offering_stays_draft(api):
    """PRD §3.8: "updates cannot be published on a `DRAFT`, `CANCELLED`, or `FAILED` offering."
    PRD §2.8: "then whether the target is in a legal state for the requested transition
    (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/update_publish_requires_offering_live_or_funded
    """
    issuer = create_verified_issuer(legal_name="Up2 Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_draft_offering(issuer["id"])
    update = create_draft_update(offering["id"], issuer["id"], title="Draft-era", body="Body")
    resp = api.publish_investor_update(update["id"], headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after_off = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after_off["status"] == "DRAFT"


# ============================================================================
# Supersede cascade (queue B state_machines)
# ============================================================================

def test_publish_superseding_update_supersedes_prior(api):
    """PRD §3.8: "When a superseding update is published, the prior update it references (which
    must itself be `PUBLISHED`) cascades `PUBLISHED → SUPERSEDED`, with its own `version`
    incremented by one."
    PRD §3.8: "A superseding update — one whose `supersedes_update_id` is non-null — is exempt
    from the gap entirely."

    Design: Corner/state_machines/publish_superseding_update_supersedes_prior_cascade
    """
    set_clock("2026-02-15T00:00:00Z")
    issuer = create_verified_issuer(legal_name="Su Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = create_live_offering(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000,
                                    deadline_at="2026-12-01T00:00:00Z")
    u1 = create_draft_update(offering["id"], issuer["id"], title="U1", body="First")
    set_clock("2026-03-01T00:00:00Z")
    validate_success(api.publish_investor_update(u1["id"], headers=issuer_headers))
    # Superseding update is exempt from the quiet-period gap (no clock advance needed).
    u2 = create_draft_update(offering["id"], issuer["id"], title="U2 correction",
                             body="Corrected", supersedes_update_id=u1["id"])
    published = validate_success(api.publish_investor_update(u2["id"], headers=issuer_headers))
    assert published["status"] == "PUBLISHED"
    after_u1 = validate_success(api.get_investor_update(u1["id"], headers=issuer_headers))
    assert after_u1["status"] == "SUPERSEDED"
