"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
Fixtures use get_success_data() (lenient) internally so setup failures surface
as clear "Setup failed" errors.
"""
import itertools
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CC = TEST_USERS["content_creator_headers"]
AP = TEST_USERS["approver_headers"]
CA = TEST_USERS["community_agent_headers"]
FC = TEST_USERS["finance_controller_headers"]
PA = TEST_USERS["platform_admin_headers"]

# Unique handle/title generator so repeated fixture calls in one test never
# collide on the (client_id, platform) handle uniqueness rule.
_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}{next(_counter)}"


# ---------------------------------------------------------------------------
# Tier 1: state progression — client / package / channel
# ---------------------------------------------------------------------------
def create_client(name="Test Client", account_manager_id="am-1"):
    """Create a fresh ONBOARDING client. Returns the client dict."""
    resp = api_client.create_client(
        {"name": name, "account_manager_id": account_manager_id}, AM
    )
    return get_success_data(resp)


def create_draft_package(client_id, tier="GROWTH", monthly_retainer_fee_cents=300000,
                         monthly_boost_budget_cents=1000000, monthly_post_quota=10,
                         included_channels=3):
    resp = api_client.create_retainer_package({
        "client_id": client_id,
        "tier": tier,
        "monthly_retainer_fee_cents": monthly_retainer_fee_cents,
        "monthly_boost_budget_cents": monthly_boost_budget_cents,
        "monthly_post_quota": monthly_post_quota,
        "included_channels": included_channels,
    }, AM)
    return get_success_data(resp)


def create_live_channel(client_id, platform="INSTAGRAM", handle=None,
                        min_publish_gap_minutes=None):
    """Create a channel and walk it PENDING -> CONNECTED -> LIVE.

    Requires the owning client to be in ONBOARDING or ACTIVE and to have an
    ACTIVE package whose included_channels allowance has room.
    Returns the live channel dict.
    """
    payload = {
        "client_id": client_id,
        "platform": platform,
        "handle": handle or _uniq("@ch"),
    }
    if min_publish_gap_minutes is not None:
        payload["min_publish_gap_minutes"] = min_publish_gap_minutes
    ch = get_success_data(api_client.create_channel(payload, AM))
    get_success_data(api_client.connect_channel(ch["id"], AM))
    ch = get_success_data(api_client.go_live_channel(ch["id"], AM))
    return ch


def setup_active_client(monthly_retainer_fee_cents=300000,
                        monthly_boost_budget_cents=1000000,
                        monthly_post_quota=10, included_channels=3,
                        tier="GROWTH", platform="INSTAGRAM",
                        min_publish_gap_minutes=None):
    """Full path to an ACTIVE client owning one LIVE channel.

    Sequence: create client -> create+activate package -> create+connect+go-live
    one channel -> activate client. Returns (client, channel).
    The returned client dict reflects the post-activation read.
    """
    client = create_client()
    create_and_activate_package(
        client["id"], tier=tier,
        monthly_retainer_fee_cents=monthly_retainer_fee_cents,
        monthly_boost_budget_cents=monthly_boost_budget_cents,
        monthly_post_quota=monthly_post_quota,
        included_channels=included_channels,
    )
    channel = create_live_channel(
        client["id"], platform=platform,
        min_publish_gap_minutes=min_publish_gap_minutes,
    )
    get_success_data(api_client.activate_client(client["id"], AM))
    client = get_success_data(api_client.get_client(client["id"], AM))
    return client, channel


def create_and_activate_package(client_id, **overrides):
    """Create a draft package and activate it. Returns the active package."""
    pkg = create_draft_package(client_id, **overrides)
    pkg = get_success_data(api_client.activate_retainer_package(pkg["id"], AM))
    return pkg


# ---------------------------------------------------------------------------
# Tier 2/3: content lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_content_with_target(client_id, channel_id, title=None):
    """Create a DRAFT content item attached to one channel. Returns the item."""
    item = get_success_data(api_client.create_content_item({
        "client_id": client_id,
        "author_id": "cc-1",
        "title": title or _uniq("Item"),
        "body": "b",
    }, CC))
    get_success_data(api_client.create_content_target(
        {"content_item_id": item["id"], "channel_id": channel_id}, CC))
    return item


def create_approved_content(client_id, channel_id, title=None):
    """Create -> submit -> approve a content item. Returns the APPROVED item.

    Requires the owning client to be ACTIVE.
    """
    item = create_content_with_target(client_id, channel_id, title=title)
    get_success_data(api_client.submit_content_item(item["id"], CC))
    item = get_success_data(api_client.approve_content_item(item["id"], AP))
    return item


def create_scheduled_content(client_id, channel_id, slot_start_utc,
                             duration_minutes=15, title=None):
    """Create -> submit -> approve -> schedule. Returns (item, slot_id)."""
    item = create_approved_content(client_id, channel_id, title=title)
    item = get_success_data(api_client.schedule_content_item(item["id"], {
        "channel_id": channel_id,
        "slot_start_utc": slot_start_utc,
        "duration_minutes": duration_minutes,
    }, AM))
    return item, item["scheduled_slot_id"]


def create_published_content(client_id, channel_id,
                             slot_start_utc="2026-03-01T09:00:00Z",
                             duration_minutes=15, title=None):
    """Create -> submit -> approve -> schedule -> publish. Returns the PUBLISHED item.

    Requires the owning client ACTIVE and quota headroom.
    """
    item, _slot = create_scheduled_content(
        client_id, channel_id, slot_start_utc,
        duration_minutes=duration_minutes, title=title)
    item = get_success_data(api_client.publish_content_item(item["id"], AM))
    return item


# ---------------------------------------------------------------------------
# Tier 4: boost lifecycle / threshold targeting
# ---------------------------------------------------------------------------
def create_draft_boost(client_id, content_item_id, requested_budget_cents=100000,
                       daily_cap_cents=50000, duration_days=2):
    resp = api_client.create_boost_campaign({
        "client_id": client_id,
        "content_item_id": content_item_id,
        "requested_budget_cents": requested_budget_cents,
        "daily_cap_cents": daily_cap_cents,
        "duration_days": duration_days,
    }, FC)
    return get_success_data(resp)


def reserve_boost(client_id, boost_id):
    """Reserve a DRAFT boost using the client's current version. Returns the campaign."""
    cver = get_success_data(api_client.get_client(client_id, FC))["version"]
    resp = api_client.reserve_boost_campaign(
        boost_id, {"expected_client_version": cver}, FC)
    return get_success_data(resp)


def setup_running_boost(requested_budget_cents=300000, daily_cap_cents=200000,
                        duration_days=3, monthly_boost_budget_cents=1000000):
    """ACTIVE client with a PUBLISHED content item and a RUNNING boost campaign.

    Sequence: active client + live channel -> publish content -> create boost ->
    reserve (OCC) -> launch. Returns (client, channel, content_item, boost).
    """
    client, channel = setup_active_client(
        monthly_boost_budget_cents=monthly_boost_budget_cents)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(
        client["id"], item["id"],
        requested_budget_cents=requested_budget_cents,
        daily_cap_cents=daily_cap_cents,
        duration_days=duration_days,
    )
    boost = reserve_boost(client["id"], boost["id"])
    boost = get_success_data(api_client.launch_boost_campaign(boost["id"], FC))
    client = get_success_data(api_client.get_client(client["id"], FC))
    return client, channel, item, boost


def setup_reserved_boost_on_scheduled_content(requested_budget_cents=100000,
                                              daily_cap_cents=50000):
    """ACTIVE client with a SCHEDULED (not published) content item and a RESERVED boost.

    Reserving is allowed while content is SCHEDULED. Returns
    (client, channel, content_item, boost).
    """
    client, channel = setup_active_client()
    item, _slot = create_scheduled_content(
        client["id"], channel["id"], "2026-03-01T09:00:00Z")
    boost = create_draft_boost(
        client["id"], item["id"],
        requested_budget_cents=requested_budget_cents,
        daily_cap_cents=daily_cap_cents,
    )
    boost = reserve_boost(client["id"], boost["id"])
    return client, channel, item, boost


# ---------------------------------------------------------------------------
# Tier 3/4: influencer collab lifecycle
# ---------------------------------------------------------------------------
def create_proposed_collab(client_id, offer_fee_cents=100000, deliverable_count=2,
                           influencer_handle=None):
    resp = api_client.create_influencer_collab({
        "client_id": client_id,
        "influencer_handle": influencer_handle or _uniq("@infl"),
        "offer_fee_cents": offer_fee_cents,
        "deliverable_count": deliverable_count,
    }, AM)
    return get_success_data(resp)


def create_accepted_collab(client_id, offer_fee_cents=100000, deliverable_count=2):
    """Propose then accept a collab. Returns the ACCEPTED collab."""
    collab = create_proposed_collab(
        client_id, offer_fee_cents=offer_fee_cents, deliverable_count=deliverable_count)
    collab = get_success_data(api_client.accept_influencer_collab(collab["id"], AM))
    return collab


def add_cleared_assets(collab_id, count):
    """Submit `count` UGC assets under the collab and clear rights on each.

    Requires the parent collab to be ACCEPTED or DELIVERED. Returns list of asset ids.
    """
    ids = []
    for _ in range(count):
        asset = get_success_data(api_client.create_ugc_asset(
            {"collab_id": collab_id, "asset_url": _uniq("http://u/")}, AM))
        get_success_data(api_client.clear_rights_ugc_asset(asset["id"], AM))
        ids.append(asset["id"])
    return ids


def setup_collab_with_cleared_assets(offer_fee_cents=100000, deliverable_count=4,
                                     cleared_count=6):
    """ACTIVE client + an ACCEPTED collab with `cleared_count` RIGHTS_CLEARED assets.

    Returns (client, collab, asset_ids).
    """
    client, _channel = setup_active_client(monthly_boost_budget_cents=0)
    collab = create_accepted_collab(
        client["id"], offer_fee_cents=offer_fee_cents,
        deliverable_count=deliverable_count)
    asset_ids = add_cleared_assets(collab["id"], cleared_count)
    return client, collab, asset_ids


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
def create_open_conversation(channel_id, kind="DM", external_author_handle="@fan"):
    resp = api_client.create_conversation({
        "channel_id": channel_id,
        "kind": kind,
        "external_author_handle": external_author_handle,
    }, CA)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Ledger helper
# ---------------------------------------------------------------------------
def list_ledger_for_boost(boost_id, headers=FC):
    """Return all ledger entries for a given boost campaign (paging through)."""
    entries = []
    offset = 0
    while True:
        resp = api_client.list_ledger_entries(
            headers, params={"boost_campaign_id": boost_id, "limit": 100, "offset": offset})
        body = resp.json()
        page = body.get("data", [])
        entries.extend(page)
        meta = body.get("meta", {})
        if not meta.get("has_more"):
            break
        offset += 100
    return entries
