"""State-machine tests: content revision loop, collab negotiation loop,
cross-entity state gates, invalid transitions, terminal lockdown, idempotency,
guarded transitions, and cross-entity cascades.

Covers difficulty rules non_linear_state_machine, cross_entity_state_dependency
and the corner state_machines section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_active_client, create_content_with_target, create_scheduled_content,
    create_published_content, create_proposed_collab,
    create_client, create_open_conversation,
)
from test_helpers import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CC = TEST_USERS["content_creator_headers"]
AP = TEST_USERS["approver_headers"]
CA = TEST_USERS["community_agent_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# non_linear_state_machine / content_item_revision_cycle_loop
# ===========================================================================
def test_content_item_revision_loop_returns_to_in_review(api):
    """PRD §3.3: "These transitions form the revision loop: an item may cycle
    `IN_REVIEW → CHANGES_REQUESTED → IN_REVIEW` any number of times, each
    resubmission bumping the revision counter."

    Design: Difficulty/non_linear_state_machine/content_item_revision_cycle_loop
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=5, included_channels=1,
        platform="LINKEDIN")
    item = create_content_with_target(client["id"], channel["id"])
    get_success_data(api.submit_content_item(item["id"], CC))
    get_success_data(api.request_changes_content_item(item["id"], AP, {"note": "fix1"}))
    get_success_data(api.resubmit_content_item(item["id"], CC))
    get_success_data(api.request_changes_content_item(item["id"], AP, {"note": "fix2"}))
    final = validate_success(api.resubmit_content_item(item["id"], CC))
    assert final["status"] == "IN_REVIEW", f"expected IN_REVIEW, got {final['status']}"


def test_content_item_revision_round_increments_per_resubmit(api):
    """PRD §3.3: "When a `ContentCreator` resubmits an item from
    `CHANGES_REQUESTED` it returns to `IN_REVIEW` and its `revision_round`
    increments by one."

    Design: Difficulty/non_linear_state_machine/content_item_revision_cycle_loop
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=5, included_channels=1,
        platform="LINKEDIN")
    item = create_content_with_target(client["id"], channel["id"])
    get_success_data(api.submit_content_item(item["id"], CC))
    get_success_data(api.request_changes_content_item(item["id"], AP, {"note": "fix1"}))
    get_success_data(api.resubmit_content_item(item["id"], CC))
    get_success_data(api.request_changes_content_item(item["id"], AP, {"note": "fix2"}))
    final = validate_success(api.resubmit_content_item(item["id"], CC))
    assert final["revision_round"] == 2, (
        f"after two revision loops revision_round must be 2, got {final['revision_round']}")


# ===========================================================================
# non_linear_state_machine / influencer_collab_counter_negotiation_loop
# ===========================================================================
def test_collab_counter_self_loop_stays_countered(api):
    """PRD §3.6: "From `PROPOSED` or `COUNTERED`, an `AccountManager` may issue a
    counter-offer, which keeps or moves the collaboration to `COUNTERED`, sets
    `offer_fee_cents` to the supplied `counter_fee_cents` (which must be greater
    than zero), and increments `negotiation_round` by one."

    Design: Difficulty/non_linear_state_machine/influencer_collab_counter_negotiation_loop
    """
    client, _channel = setup_active_client(monthly_boost_budget_cents=0)
    collab = create_proposed_collab(client["id"], offer_fee_cents=100000, deliverable_count=2)
    get_success_data(api.counter_influencer_collab(collab["id"], {"counter_fee_cents": 90000}, AM))
    final = validate_success(
        api.counter_influencer_collab(collab["id"], {"counter_fee_cents": 85000}, AM))
    assert final["status"] == "COUNTERED", f"expected COUNTERED, got {final['status']}"


def test_collab_counter_loop_bumps_round_and_updates_fee(api):
    """PRD §3.6: "sets `offer_fee_cents` to the supplied `counter_fee_cents`
    (which must be greater than zero), and increments `negotiation_round` by one."

    Design: Difficulty/non_linear_state_machine/influencer_collab_counter_negotiation_loop
    """
    client, _channel = setup_active_client(monthly_boost_budget_cents=0)
    collab = create_proposed_collab(client["id"], offer_fee_cents=100000, deliverable_count=2)
    get_success_data(api.counter_influencer_collab(collab["id"], {"counter_fee_cents": 90000}, AM))
    final = validate_success(
        api.counter_influencer_collab(collab["id"], {"counter_fee_cents": 85000}, AM))
    assert final["negotiation_round"] == 2, (
        f"after two counters negotiation_round must be 2, got {final['negotiation_round']}")
    assert final["offer_fee_cents"] == 85000, (
        f"offer_fee_cents must reflect latest counter 85000, got {final['offer_fee_cents']}")


# ===========================================================================
# cross_entity_state_dependency / boost_launch_requires_content_published
# ===========================================================================
def test_boost_launch_rejected_while_content_scheduled(api):
    """PRD §3.4: "Launching a reserved campaign advances it from `RESERVED` to
    `RUNNING`, permitted only when the boosted content item is `PUBLISHED`; a
    launch against unpublished content is rejected with `ERR_CONTENT_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/boost_launch_requires_content_published
    """
    from test_helpers import setup_reserved_boost_on_scheduled_content
    client, channel, item, boost = setup_reserved_boost_on_scheduled_content()
    validate_error(api.launch_boost_campaign(boost["id"], TEST_USERS["finance_controller_headers"]),
                   ApiErrorId.ERR_CONTENT_NOT_PUBLISHED.value)


def test_boost_launch_succeeds_after_content_published(api):
    """PRD §3.4: "Launching a reserved campaign advances it from `RESERVED` to
    `RUNNING`, permitted only when the boosted content item is `PUBLISHED`; a
    launch against unpublished content is rejected with `ERR_CONTENT_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/boost_launch_requires_content_published
    """
    from test_helpers import setup_reserved_boost_on_scheduled_content
    FC = TEST_USERS["finance_controller_headers"]
    client, channel, item, boost = setup_reserved_boost_on_scheduled_content()
    get_success_data(api.publish_content_item(item["id"], AM))
    launched = validate_success(api.launch_boost_campaign(boost["id"], FC))
    assert launched["status"] == "RUNNING", f"expected RUNNING, got {launched['status']}"


# ===========================================================================
# cross_entity_state_dependency / content_submit_requires_client_active
# ===========================================================================
def test_content_submit_rejected_when_client_suspended(api):
    """PRD §3.3: "A `ContentCreator` submits a draft for review, moving it from
    `DRAFT` to `IN_REVIEW`, but only when the owning client is `ACTIVE` — a
    submission against a non-active client is rejected with `ERR_CLIENT_NOT_ACTIVE`
    — and only when the item has at least one content target."

    Design: Difficulty/cross_entity_state_dependency/content_submit_requires_client_active
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=5, included_channels=1)
    item = create_content_with_target(client["id"], channel["id"])
    get_success_data(api.suspend_client(client["id"], AM))
    validate_error(api.submit_content_item(item["id"], CC),
                   ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value)


def test_content_submit_succeeds_after_reinstate(api):
    """PRD §3.3: "A `ContentCreator` submits a draft for review, moving it from
    `DRAFT` to `IN_REVIEW`, but only when the owning client is `ACTIVE` — a
    submission against a non-active client is rejected with `ERR_CLIENT_NOT_ACTIVE`
    — and only when the item has at least one content target."

    Design: Difficulty/cross_entity_state_dependency/content_submit_requires_client_active
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=5, included_channels=1)
    item = create_content_with_target(client["id"], channel["id"])
    get_success_data(api.suspend_client(client["id"], AM))
    get_success_data(api.reinstate_client(client["id"], AM))
    submitted = validate_success(api.submit_content_item(item["id"], CC))
    assert submitted["status"] == "IN_REVIEW", f"expected IN_REVIEW, got {submitted['status']}"


# ===========================================================================
# corner state_machines section
# ===========================================================================
def test_approve_from_draft_invalid_state(api):
    """PRD §3.8: "Only then is the basic state-machine check applied: if the
    requested transition is not defined from the target's current state the
    request yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_approve_content_from_draft_returns_invalid_state
    """
    client = create_client()
    item = get_success_data(api.create_content_item(
        {"client_id": client["id"], "author_id": "cc-1", "title": "D", "body": "b"}, CC))
    validate_error(api.approve_content_item(item["id"], AP),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_suspend_churned_client_invalid_state(api):
    """PRD §3.8: "Only then is the basic state-machine check applied: if the
    requested transition is not defined from the target's current state the
    request yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_transition_from_terminal_churned_client_rejected
    """
    client = create_client()
    get_success_data(api.churn_client(client["id"], PA))
    validate_error(api.suspend_client(client["id"], PA),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_publish_already_published_invalid_state(api):
    """PRD §3.3: "Publishing is an `AccountManager` action that advances a
    `SCHEDULED` item to `PUBLISHED`."
    PRD §3.8: "if the requested transition is not defined from the target's
    current state the request yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_idempotent_publish_second_attempt_rejected
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=0)
    item = create_published_content(client["id"], channel["id"])
    validate_error(api.publish_content_item(item["id"], AM),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_conversation_assign_requires_channel_live(api):
    """PRD §3.5: "A `CommunityAgent` claims an `OPEN` conversation, advancing it to
    `ASSIGNED` and recording the acting agent's `X-User-ID` onto
    `assigned_agent_id`, but only when the conversation's channel is `LIVE`; a
    claim against a non-live channel is rejected with `ERR_CHANNEL_NOT_LIVE`."

    Design: Corner/state_machines/corner_conversation_assign_requires_channel_live
    """
    client = create_client()
    channel = get_success_data(api.create_channel(
        {"client_id": client["id"], "platform": "FACEBOOK", "handle": "@convco"}, AM))
    get_success_data(api.connect_channel(channel["id"], AM))  # CONNECTED, not LIVE
    conv = get_success_data(api.create_conversation(
        {"channel_id": channel["id"], "kind": "DM", "external_author_handle": "@fan"}, CA))
    validate_error(api.assign_conversation(conv["id"], CA),
                   ApiErrorId.ERR_CHANNEL_NOT_LIVE.value)


def test_message_append_recomputes_conversation_count(api):
    """PRD §3.5: "Appending a message recomputes the parent conversation's
    `message_count` as the number of messages under that conversation."

    Design: Corner/state_machines/corner_message_append_bumps_conversation_count
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=5, included_channels=1,
        platform="X")
    conv = create_open_conversation(channel["id"], kind="COMMENT")
    get_success_data(api.create_message(
        {"conversation_id": conv["id"], "direction": "INBOUND", "body": "hi"}, CA))
    refreshed = validate_success(api.get_conversation(conv["id"], CA))
    assert refreshed["message_count"] == 1, (
        f"message_count must be 1 after one append, got {refreshed['message_count']}")


def test_collab_cancel_rejects_submitted_assets(api):
    """PRD §3.6: "Cancelling a collaboration from `PROPOSED`, `COUNTERED`, or
    `ACCEPTED` drives it to `CANCELLED` and, as a cascade, drives every one of
    that collaboration's assets still in `SUBMITTED` to `REJECTED`."

    Design: Corner/state_machines/corner_ugc_reject_cascade_on_collab_cancel
    """
    client = create_client()
    collab = get_success_data(api.create_influencer_collab(
        {"client_id": client["id"], "influencer_handle": "@u",
         "offer_fee_cents": 50000, "deliverable_count": 1}, AM))
    asset = get_success_data(api.create_ugc_asset(
        {"collab_id": collab["id"], "asset_url": "http://u/1"}, AM))
    get_success_data(api.cancel_influencer_collab(collab["id"], AM))
    refreshed = validate_success(api.get_ugc_asset(asset["id"], AM))
    assert refreshed["status"] == "REJECTED", (
        f"submitted asset must be REJECTED on collab cancel, got {refreshed['status']}")
