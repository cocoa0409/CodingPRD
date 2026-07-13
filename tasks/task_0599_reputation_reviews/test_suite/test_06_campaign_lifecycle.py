"""Campaign lifecycle: create (OCC), schedule (window collision), activate, pause, complete."""

from test_helpers import (
    ApiErrorId,
    assert_campaign,
    assert_credit_ledger,
    assert_score,
    create_campaign,
    create_campaign_payload,
    create_listing,
    create_running_campaign,
    enqueue_request,
    read_campaign,
    read_location,
    read_review_request,
    schedule_campaign,
    setup_bare_location,
    setup_campaign_with_queued_requests,
    setup_location_with_google_only,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Activation demands posture OPEN
# ---------------------------------------------------------------------------
def _setup_scheduled_campaign_on_a_restricted_location():
    """A single never-synced GOOGLE listing scores 15.00, below the 40.00 health floor."""
    env = setup_bare_location()
    location_id = env["location"]["id"]
    create_listing(location_id, "GOOGLE")

    campaign = create_campaign(location_id, name="Blocked")
    schedule_campaign(campaign["id"])
    env["campaign"] = read_campaign(campaign["id"])
    return env


def test_activating_a_campaign_on_a_restricted_location_is_rejected(api, admin_headers):
    """PRD §3.6: "**Activation** takes the campaign `SCHEDULED → RUNNING` or, after a
    pause, `PAUSED → RUNNING`. It is one of the two operations that demand a posture of
    exactly `OPEN`: a `RESTRICTED` location rejects it with `ERR_LOCATION_RESTRICTED` and
    a `FROZEN` one with `ERR_LOCATION_FROZEN`."
    PRD §2.5: "**The listing-health predicate.** Always armed. It fires when
    `listing_health_score` is strictly below 40.00."

    Design: Difficulty/cross_entity_state_dependency/campaign_activate_requires_location_posture_open
    """
    env = _setup_scheduled_campaign_on_a_restricted_location()
    location = read_location(env["location"]["id"])
    assert_score(location["listing_health_score"], 15.00, "listing_health_score")
    assert location["posture"] == "RESTRICTED"

    resp = api.activate_campaign(env["campaign"]["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_LOCATION_RESTRICTED.value)


def test_a_rejected_activation_leaves_the_campaign_scheduled_and_unanchored(api, admin_headers):
    """PRD §3.6: "The first activation of a campaign's life stamps `activated_at` with the
    current logical instant, and this is the anchor of the BROAD attribution window
    described below; **a later re-activation never moves it.**"
    PRD §3.6: "A new campaign is born in `DRAFT` with all three credit ledger fields —
    `credits_reserved`, `credits_consumed` and `credits_released` — at 0, `sent_count` at
    0, `billing_cost` at 0.00, and `activated_at` null."

    Design: Difficulty/cross_entity_state_dependency/campaign_activate_requires_location_posture_open
    """
    env = _setup_scheduled_campaign_on_a_restricted_location()

    resp = api.activate_campaign(env["campaign"]["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_LOCATION_RESTRICTED.value)

    campaign = read_campaign(env["campaign"]["id"])
    assert_campaign(campaign)
    assert campaign["status"] == "SCHEDULED", "the refused activation must not move the campaign"
    assert campaign["activated_at"] is None, "the BROAD window anchor stays unset"


# ---------------------------------------------------------------------------
# The buffered send-window collision
# ---------------------------------------------------------------------------
def _setup_location_with_scheduled_window_09_to_11():
    env = setup_location_with_google_only()
    campaign_a = create_campaign(
        env["location"]["id"],
        name="Campaign A",
        channel="EMAIL",
        send_window_start="09:00",
        send_window_end="11:00",
        daily_send_cap=5,
        credits_allocated=5,
    )
    schedule_campaign(campaign_a["id"])
    env["campaign_a"] = read_campaign(campaign_a["id"])
    return env


def test_scheduling_a_window_touching_the_buffer_edge_is_a_collision(api, admin_headers):
    """PRD §3.6: "Convert both windows to minutes since midnight and expand the
    candidate's window symmetrically by a channel buffer of a quarter of an hour — 15
    minutes — on each side. The candidate collides with that other campaign when the
    candidate's buffered open is at or before the other's close **and** the candidate's
    buffered close is at or after the other's open. These are closed intervals: touching
    exactly at the buffer edge *is* a collision. Any collision rejects the schedule with
    `ERR_SEND_WINDOW_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/campaign_send_window_buffered_edge_rejects_touching_allows_one_minute_gap
    """
    env = _setup_location_with_scheduled_window_09_to_11()
    # 11:15 buffered open = 675 - 15 = 660 minutes, exactly Campaign A's 11:00 close.
    campaign_b = create_campaign(
        env["location"]["id"],
        name="Campaign B",
        channel="EMAIL",
        send_window_start="11:15",
        send_window_end="12:00",
        daily_send_cap=5,
        credits_allocated=5,
    )

    resp = api.schedule_campaign(campaign_b["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_SEND_WINDOW_CONFLICT.value)

    assert read_campaign(campaign_b["id"])["status"] == "DRAFT"
    assert read_campaign(env["campaign_a"]["id"])["status"] == "SCHEDULED"


def test_scheduling_a_window_one_minute_beyond_the_buffer_edge_succeeds(api, admin_headers):
    """PRD §3.6: "**Scheduling** takes the campaign `DRAFT → SCHEDULED`, and it is the
    moment the send-window collision check runs. Consider any *other* campaign at the
    same location, on the same `channel`, whose `status` is `SCHEDULED`, `RUNNING` or
    `PAUSED`."
    PRD §3.6: "The candidate collides with that other campaign when the candidate's
    buffered open is at or before the other's close **and** the candidate's buffered close
    is at or after the other's open."

    Design: Difficulty/resource_temporal_overlap/campaign_send_window_buffered_edge_rejects_touching_allows_one_minute_gap
    """
    env = _setup_location_with_scheduled_window_09_to_11()
    # 11:16 buffered open = 676 - 15 = 661 minutes, one minute past Campaign A's 11:00 close.
    campaign_c = create_campaign(
        env["location"]["id"],
        name="Campaign C",
        channel="EMAIL",
        send_window_start="11:16",
        send_window_end="12:00",
        daily_send_cap=5,
        credits_allocated=5,
    )

    scheduled = validate_success(api.schedule_campaign(campaign_c["id"], admin_headers))
    assert scheduled["status"] == "SCHEDULED"
    assert read_campaign(env["campaign_a"]["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Pause / complete / OCC on create
# ---------------------------------------------------------------------------
def test_a_manual_pause_keeps_queued_requests_and_their_reserved_credits(api, admin_headers):
    """PRD §3.6: "A *manual* pause by a `LocationManager` takes the campaign `RUNNING →
    PAUSED` and leaves the queue intact: every `QUEUED` request stays queued and its
    reserved credit stays reserved."

    Design: Corner/state_machines/manual_campaign_pause_keeps_queued_requests_and_reserved_credits
    """
    env = setup_campaign_with_queued_requests(
        num_requests=1, sites=("GOOGLE",), daily_send_cap=5, credits_allocated=5
    )

    paused = validate_success(api.pause_campaign(env["campaign"]["id"], admin_headers))
    assert paused["status"] == "PAUSED"

    request = read_review_request(env["requests"][0]["id"])
    assert request["status"] == "QUEUED", "a manual pause does not empty the queue"

    campaign = read_campaign(env["campaign"]["id"])
    assert_credit_ledger(campaign, reserved=1, consumed=0, released=0)


def test_completing_a_campaign_suppresses_its_queue_and_releases_the_credits(api, admin_headers):
    """PRD §3.6: "**Completion** takes the campaign `RUNNING → COMPLETED` or `PAUSED →
    COMPLETED`, and, like the system pause, it suppresses every remaining `QUEUED` request
    with the same credit release per request. `COMPLETED` is terminal."
    PRD §3.6: "every `QUEUED` request of that campaign is moved to `SUPPRESSED`, and for
    each one, `credits_reserved` drops by one while `credits_released` rises by one."

    Design: Corner/state_machines/campaign_complete_suppresses_queued_requests_and_releases_credits
    """
    env = setup_campaign_with_queued_requests(
        num_requests=2, sites=("GOOGLE",), daily_send_cap=5, credits_allocated=5
    )

    completed = validate_success(api.complete_campaign(env["campaign"]["id"], admin_headers))
    assert completed["status"] == "COMPLETED"

    for request in env["requests"]:
        assert read_review_request(request["id"])["status"] == "SUPPRESSED"

    campaign = read_campaign(env["campaign"]["id"])
    assert_credit_ledger(campaign, reserved=0, consumed=0, released=2)


def test_campaign_create_carrying_a_stale_location_version_is_rejected(api, admin_headers):
    """PRD §2.8: "Creating a campaign under a location requires `expected_location_version`,
    carrying the client's last observed `version` of that `Location`. If it does not equal
    the location's current `version`, the create is rejected with `ERR_STALE_VERSION`
    (412)."
    PRD §2.8: "A successful create increments the location's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_location_version_on_campaign_create_returns_412
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    observed_version = read_location(location_id)["version"]

    first = validate_success(
        api.create_campaign(
            location_id,
            create_campaign_payload(
                observed_version,
                name="Campaign A",
                channel="EMAIL",
                daily_send_cap=5,
                credits_allocated=5,
            ),
            admin_headers,
        ),
        201,
    )

    resp = api.create_campaign(
        location_id,
        create_campaign_payload(
            observed_version,
            name="Campaign B",
            channel="SMS",
            send_window_start="14:00",
            send_window_end="16:00",
            daily_send_cap=5,
            credits_allocated=5,
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    rows = validate_success(api.list_campaigns(location_id, admin_headers))
    assert len(rows) == 1, "the stale create must not add a second Campaign"
    assert read_campaign(first["id"])["status"] == "DRAFT"
