"""Launch gate and same-creator / early-bird window exclusivity.

Translates queue-A difficulty rules cross_entity_state_dependency (launch path) and
resource_temporal_overlap, plus queue-B state_machines corners on launch.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_creator_headers,
    create_creator_payload, create_campaign_payload, create_tier_payload,
    register_creator, create_draft_campaign, add_tier, launch_campaign, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / campaign_launch_requires_available_tier (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_launch_with_no_tiers_rejected(api):
    """PRD §3.12: "The campaign must have at least one reward tier whose status is AVAILABLE;
    a launch with no available tier is rejected with ERR_NO_TIERS (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/campaign_launch_requires_available_tier
    """
    creator, campaign = create_draft_campaign(api, funding_model="FLEXIBLE",
                                              funding_goal_cents=1000)
    creator_headers = make_creator_headers(creator["id"])
    resp = api.launch_campaign(campaign["id"], creator_headers)
    validate_error(resp, ApiErrorId.ERR_NO_TIERS.value)
    # status remains DRAFT
    data = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    assert data["status"] == "DRAFT", f"Expected DRAFT after failed launch, got {data['status']}"


def test_launch_with_available_tier_succeeds(api):
    """PRD §3.12: "The campaign must have at least one reward tier whose status is AVAILABLE;
    a launch with no available tier is rejected with ERR_NO_TIERS (HTTP 409)."
    PRD §3.12: "On a successful launch, the campaign's launched_at is set to the current clock,
    its committed_amount_cents is initialized to 0, and its version is incremented."

    Design: Difficulty/cross_entity_state_dependency/campaign_launch_requires_available_tier
    """
    creator, campaign = create_draft_campaign(api, funding_model="FLEXIBLE",
                                              funding_goal_cents=1000)
    add_tier(api, creator, campaign)
    creator_headers = make_creator_headers(creator["id"])
    resp = api.launch_campaign(campaign["id"], creator_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "LIVE", f"Expected LIVE, got {data['status']}"
    assert data["committed_amount_cents"] == 0, (
        f"Expected committed initialized to 0, got {data['committed_amount_cents']}"
    )
    assert data["launched_at"] is not None, "launched_at must be set on launch"


# --------------------------------------------------------------------------- #
# state_machines corners on launch (queue B)
# --------------------------------------------------------------------------- #
def test_launch_already_live_campaign_returns_invalid_state(api):
    """PRD §3.12: "Launching takes a campaign from DRAFT to LIVE".
    PRD §3.5: "the campaign must be in a state that permits the transition, failing with
    ERR_INVALID_STATE (HTTP 409) if not."

    Design: Corner/state_machines/launch_already_live_campaign_returns_invalid_state
    """
    creator, campaign = create_draft_campaign(api)
    add_tier(api, creator, campaign)
    launch_campaign(api, creator, campaign)
    creator_headers = make_creator_headers(creator["id"])
    resp = api.launch_campaign(campaign["id"], creator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_launch_with_past_deadline_returns_deadline_in_past(api):
    """PRD §3.12: "The campaign's deadline_utc must be strictly after the current clock; a
    deadline at or before "now" is rejected with ERR_DEADLINE_IN_PAST (HTTP 422)."

    Design: Corner/state_machines/launch_with_past_deadline_returns_deadline_in_past
    """
    set_clock(api, "2026-06-01T00:00:00.000Z")
    creator, campaign = create_draft_campaign(api, deadline_utc="2026-07-01T00:00:00.000Z",
                                              set_clock_to=None)
    add_tier(api, creator, campaign)
    # Advance the clock past the deadline before launching.
    set_clock(api, "2026-08-01T00:00:00.000Z")
    creator_headers = make_creator_headers(creator["id"])
    resp = api.launch_campaign(campaign["id"], creator_headers)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_IN_PAST.value)


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / creator_live_window_overlap_half_open (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def _make_creator_with_live_k1(api):
    """Helper: creator C1 with a LIVE campaign K1 [2026-06-01, 2026-07-01)."""
    set_clock(api, "2026-06-01T00:00:00.000Z")
    c1 = register_creator(api, display_name="C1")
    c1_headers = make_creator_headers(c1["id"])
    k1 = validate_success(api.create_campaign(
        create_campaign_payload(c1["id"], title="K1", funding_goal_cents=1000,
                                funding_model="FLEXIBLE", deadline_utc="2026-07-01T00:00:00.000Z"),
        c1_headers), 201)
    validate_success(api.create_tier(k1["id"], create_tier_payload(), c1_headers), 201)
    validate_success(api.launch_campaign(k1["id"], c1_headers), 200)
    return c1, c1_headers, k1


def test_overlapping_live_window_launch_rejected(api):
    """PRD §3.12: "The launch is rejected with ERR_CAMPAIGN_WINDOW_OVERLAP (HTTP 409) if the
    same creator already has another campaign whose status is LIVE and whose window overlaps
    — that is, when the current clock is strictly before that other campaign's deadline_utc
    and that other campaign's launched_at is strictly before this campaign's deadline_utc."

    Design: Difficulty/resource_temporal_overlap/creator_live_window_overlap_half_open
    """
    c1, c1_headers, k1 = _make_creator_with_live_k1(api)
    k2 = validate_success(api.create_campaign(
        create_campaign_payload(c1["id"], title="K2", funding_goal_cents=1000,
                                funding_model="FLEXIBLE", deadline_utc="2026-08-01T00:00:00.000Z"),
        c1_headers), 201)
    validate_success(api.create_tier(k2["id"], create_tier_payload(title="T2"), c1_headers), 201)
    # clock 2026-06-15 is strictly before K1.deadline 2026-07-01 -> overlap
    set_clock(api, "2026-06-15T00:00:00.000Z")
    resp = api.launch_campaign(k2["id"], c1_headers)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_OVERLAP.value)
    data = validate_success(api.get_campaign(k2["id"], ADMIN), 200)
    assert data["status"] == "DRAFT", f"Expected K2 still DRAFT, got {data['status']}"


def test_touching_live_window_launch_allowed(api):
    """PRD §3.12: "Because the interval is half-open, two windows that merely touch at an
    endpoint do not overlap: a campaign whose launch instant coincides exactly with another's
    deadline is allowed."

    Design: Difficulty/resource_temporal_overlap/creator_live_window_overlap_half_open
    """
    c1, c1_headers, k1 = _make_creator_with_live_k1(api)
    k2 = validate_success(api.create_campaign(
        create_campaign_payload(c1["id"], title="K2", funding_goal_cents=1000,
                                funding_model="FLEXIBLE", deadline_utc="2026-08-01T00:00:00.000Z"),
        c1_headers), 201)
    validate_success(api.create_tier(k2["id"], create_tier_payload(title="T2"), c1_headers), 201)
    # launch K2 exactly at K1's deadline 2026-07-01: clock == K1.deadline, NOT strictly before
    set_clock(api, "2026-07-01T00:00:00.000Z")
    resp = api.launch_campaign(k2["id"], c1_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "LIVE", (
        f"Expected K2 LIVE (touching endpoint allowed), got {data['status']}"
    )


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / tier_early_bird_window_overlap_with_buffer (queue A, >=2 tests)
# --------------------------------------------------------------------------- #
def test_early_bird_adjacent_window_rejected(api):
    """PRD §3.2: "Mere adjacency is not enough separation: two early-bird windows that merely
    touch end-to-start, with a gap of zero, are still rejected; only a genuine gap of at least
    one hour between them is accepted."

    Design: Difficulty/resource_temporal_overlap/tier_early_bird_window_overlap_with_buffer
    """
    set_clock(api, "2026-06-01T00:00:00.000Z")
    creator, campaign = create_draft_campaign(api, set_clock_to=None)
    creator_headers = make_creator_headers(creator["id"])
    validate_success(api.create_tier(campaign["id"], create_tier_payload(
        title="EarlyA", price_cents=4000, weight_grams=800, is_early_bird=True,
        available_from="2026-06-02T10:00:00.000Z", available_until="2026-06-02T11:00:00.000Z"),
        creator_headers), 201)
    # New early-bird [11:00, 12:00) touches A's end (gap 0s < 3600s) -> rejected
    resp = api.create_tier(campaign["id"], create_tier_payload(
        title="EarlyB", price_cents=4500, weight_grams=800, is_early_bird=True,
        available_from="2026-06-02T11:00:00.000Z", available_until="2026-06-02T12:00:00.000Z"),
        creator_headers)
    validate_error(resp, ApiErrorId.ERR_TIER_WINDOW_OVERLAP.value)


def test_early_bird_window_with_sufficient_gap_allowed(api):
    """PRD §3.2: "a new early-bird window must be separated from every existing early-bird
    tier's window on that campaign by at least one hour (3600 seconds)."
    PRD §3.2: "only a genuine gap of at least one hour between them is accepted."

    Design: Difficulty/resource_temporal_overlap/tier_early_bird_window_overlap_with_buffer
    """
    set_clock(api, "2026-06-01T00:00:00.000Z")
    creator, campaign = create_draft_campaign(api, set_clock_to=None)
    creator_headers = make_creator_headers(creator["id"])
    validate_success(api.create_tier(campaign["id"], create_tier_payload(
        title="EarlyA", price_cents=4000, weight_grams=800, is_early_bird=True,
        available_from="2026-06-02T10:00:00.000Z", available_until="2026-06-02T11:00:00.000Z"),
        creator_headers), 201)
    # New early-bird [12:00, 13:00) starts a full hour after A's end (gap exactly 3600s) -> allowed
    resp = api.create_tier(campaign["id"], create_tier_payload(
        title="EarlyB", price_cents=4500, weight_grams=800, is_early_bird=True,
        available_from="2026-06-02T12:00:00.000Z", available_until="2026-06-02T13:00:00.000Z"),
        creator_headers)
    data = validate_success(resp, 201)
    assert data["is_early_bird"] is True
