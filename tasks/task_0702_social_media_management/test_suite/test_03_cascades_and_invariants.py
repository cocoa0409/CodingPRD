"""Cascade and conservation-invariant tests: client churn depth-3 cascade,
boost-complete release ledger cascade, reserve+cancel budget conservation,
schedule+unschedule slot-occupancy conservation.

Covers difficulty rules transitive_cascade and compensating_invariant.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_active_client, create_scheduled_content, create_published_content,
    create_draft_boost, reserve_boost, list_ledger_for_boost,
)
from test_helpers import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# transitive_cascade / client_churn_cascade_depth3
# ===========================================================================
def test_churn_disconnects_channel(api):
    """PRD §3.1: "When a client churns, every one of its channels that is not
    already `DISCONNECTED` is driven to `DISCONNECTED`, and every conversation on
    those channels that is `OPEN`, `ASSIGNED`, or `ESCALATED` is driven to
    `RESOLVED`."

    Design: Difficulty/transitive_cascade/client_churn_cascade_depth3
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=500000, included_channels=2)
    create_scheduled_content(client["id"], channel["id"], "2026-03-05T09:00:00Z")
    get_success_data(api.churn_client(client["id"], PA))
    ch = validate_success(api.get_channel(channel["id"], AM))
    assert ch["status"] == "DISCONNECTED", f"channel must be DISCONNECTED, got {ch['status']}"


def test_churn_cascade_releases_slot_and_reverts_content(api):
    """PRD §3.2: "Disconnection has two cascades: every schedule slot of that
    channel still in `RESERVED` is released to `RELEASED`, and each such released
    slot's content item, if it was `SCHEDULED`, is reverted to `APPROVED` with its
    `scheduled_slot_id` cleared."

    Design: Difficulty/transitive_cascade/client_churn_cascade_depth3
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=500000, included_channels=2)
    item, slot_id = create_scheduled_content(client["id"], channel["id"], "2026-03-05T09:00:00Z")
    get_success_data(api.churn_client(client["id"], PA))

    slot = validate_success(api.get_schedule_slot(slot_id, AM))
    assert slot["status"] == "RELEASED", f"slot must be RELEASED, got {slot['status']}"

    refreshed = validate_success(api.get_content_item(item["id"], AM))
    assert refreshed["status"] == "APPROVED", (
        f"scheduled content must revert to APPROVED, got {refreshed['status']}")
    assert refreshed["scheduled_slot_id"] is None, (
        f"scheduled_slot_id must be cleared, got {refreshed['scheduled_slot_id']}")


# ===========================================================================
# transitive_cascade / boost_complete_release_ledger_cascade_depth2
# ===========================================================================
def test_boost_complete_writes_release_ledger_entry(api):
    """PRD §3.4: "the unspent remainder is the `reserved_budget_cents` minus the
    `spent_budget_cents`, and when that remainder is greater than zero a ledger
    entry of type `BOOST_RELEASE` is appended whose `amount_cents` is the negative
    of that unspent remainder (a release returns budget, so the signed amount is
    negative), carrying the `boost_campaign_id` and `cycle_index`".

    Design: Difficulty/transitive_cascade/boost_complete_release_ledger_cascade_depth2
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000, included_channels=2)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=300000, daily_cap_cents=200000,
                               duration_days=3)
    boost = reserve_boost(client["id"], boost["id"])
    boost = get_success_data(api.launch_boost_campaign(boost["id"], FC))
    get_success_data(api.record_spend_boost_campaign(boost["id"], {"amount_cents": 120000}, FC))
    get_success_data(api.complete_boost_campaign(boost["id"], FC))

    entries = list_ledger_for_boost(boost["id"])
    releases = [e for e in entries
                if e["entry_type"] == "BOOST_RELEASE" and e["amount_cents"] == -180000]
    assert releases, (
        f"expected a BOOST_RELEASE of -180000 for boost {boost['id']}, got {entries}")


def test_boost_complete_recomputes_client_budget(api):
    """PRD §3.4: "the campaign's `reserved_budget_cents` is then set to zero and
    the client's `boost_reserved_cents`, `boost_spent_cents`, and
    `boost_available_cents` are recomputed."

    Design: Difficulty/transitive_cascade/boost_complete_release_ledger_cascade_depth2
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000, included_channels=2)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=300000, daily_cap_cents=200000,
                               duration_days=3)
    boost = reserve_boost(client["id"], boost["id"])
    boost = get_success_data(api.launch_boost_campaign(boost["id"], FC))
    get_success_data(api.record_spend_boost_campaign(boost["id"], {"amount_cents": 120000}, FC))
    get_success_data(api.complete_boost_campaign(boost["id"], FC))

    refreshed = validate_success(api.get_client(client["id"], FC))
    assert refreshed["boost_reserved_cents"] == 0, (
        f"reserved must be 0, got {refreshed['boost_reserved_cents']}")
    assert refreshed["boost_spent_cents"] == 120000, (
        f"spent must be 120000, got {refreshed['boost_spent_cents']}")
    # available = 1000000 - 0 - 120000 = 880000
    assert refreshed["boost_available_cents"] == 880000, (
        f"available must be 880000, got {refreshed['boost_available_cents']}")


# ===========================================================================
# compensating_invariant / boost_reserve_then_cancel_conserves_client_budget
# ===========================================================================
def test_reserve_then_cancel_restores_available_budget(api):
    """PRD §2.6: "A client's ad-boost budget obeys a conservation invariant that is
    recomputed from the underlying boost campaigns on every reservation, spend
    record, completion, cancellation, and on client activation."
    PRD §3.4: "Cancelling a campaign from `DRAFT` or `RESERVED` drives it to
    `CANCELLED`: the released amount is the `reserved_budget_cents` when cancelling
    from `RESERVED` ... the `reserved_budget_cents` is then zeroed and the
    client's `boost_reserved_cents` and `boost_available_cents` are recomputed."

    Design: Difficulty/compensating_invariant/boost_reserve_then_cancel_conserves_client_budget
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000, included_channels=2)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=100000, daily_cap_cents=50000,
                               duration_days=2)
    boost = reserve_boost(client["id"], boost["id"])
    get_success_data(api.cancel_boost_campaign(boost["id"], FC))

    refreshed = validate_success(api.get_client(client["id"], FC))
    assert refreshed["boost_available_cents"] == 1000000, (
        f"available must return to 1000000, got {refreshed['boost_available_cents']}")
    assert refreshed["boost_reserved_cents"] == 0, (
        f"reserved must be 0, got {refreshed['boost_reserved_cents']}")


def test_reserve_then_cancel_ledger_sums_to_zero(api):
    """PRD §3.4: "When a reservation succeeds ... a ledger entry of type
    `BOOST_RESERVE` is appended with a positive `amount_cents` equal to the
    reserved amount".
    PRD §3.4: "when that released amount is greater than zero a `BOOST_RELEASE`
    ledger entry with a negative `amount_cents` of that magnitude is appended".

    Design: Difficulty/compensating_invariant/boost_reserve_then_cancel_conserves_client_budget
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000, included_channels=2)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=100000, daily_cap_cents=50000,
                               duration_days=2)
    boost = reserve_boost(client["id"], boost["id"])
    get_success_data(api.cancel_boost_campaign(boost["id"], FC))

    entries = list_ledger_for_boost(boost["id"])
    total = sum(e["amount_cents"] for e in entries)
    assert total == 0, (
        f"BOOST_RESERVE (+100000) and BOOST_RELEASE (-100000) must sum to 0, got {total} ({entries})")


# ===========================================================================
# compensating_invariant / schedule_then_unschedule_conserves_channel_slot_occupancy
# ===========================================================================
def test_unschedule_releases_slot_and_clears_pointer(api):
    """PRD §3.3: "Unscheduling reverses this: an `AccountManager` moves the item
    from `SCHEDULED` back to `APPROVED`, releasing the reserved slot (it leaves
    `RESERVED` for `RELEASED`) and clearing `scheduled_slot_id`."

    Design: Difficulty/compensating_invariant/schedule_then_unschedule_conserves_channel_slot_occupancy
    """
    client, channel = setup_active_client(
        monthly_boost_budget_cents=0, included_channels=1,
        platform="LINKEDIN", min_publish_gap_minutes=30)
    item, slot_id = create_scheduled_content(
        client["id"], channel["id"], "2026-03-12T09:00:00Z")
    reverted = validate_success(api.unschedule_content_item(item["id"], AM))
    assert reverted["scheduled_slot_id"] is None, (
        f"scheduled_slot_id must be cleared, got {reverted['scheduled_slot_id']}")

    slot = validate_success(api.get_schedule_slot(slot_id, AM))
    assert slot["status"] == "RELEASED", f"slot must be RELEASED, got {slot['status']}"


def test_reschedule_same_slot_time_after_unschedule(api):
    """PRD §3.2: "When a new slot would be placed on a channel, it must not overlap
    the half-open window of any slot on the same channel that is currently
    `RESERVED` or `FIRED`, and it must additionally be separated from the nearest
    such slot by at least the channel's `min_publish_gap_minutes`".
    PRD §3.3: "releasing the reserved slot (it leaves `RESERVED` for `RELEASED`)
    and clearing `scheduled_slot_id`."

    Design: Difficulty/compensating_invariant/schedule_then_unschedule_conserves_channel_slot_occupancy
    """
    client, channel = setup_active_client(
        monthly_boost_budget_cents=0, included_channels=1,
        platform="LINKEDIN", min_publish_gap_minutes=30)
    item, _slot_id = create_scheduled_content(
        client["id"], channel["id"], "2026-03-12T09:00:00Z")
    get_success_data(api.unschedule_content_item(item["id"], AM))
    # The released slot freed the timeline; same start time must be accepted again.
    rescheduled = validate_success(api.schedule_content_item(item["id"], {
        "channel_id": channel["id"],
        "slot_start_utc": "2026-03-12T09:00:00Z",
        "duration_minutes": 15,
    }, AM))
    assert rescheduled["status"] == "SCHEDULED", (
        f"re-scheduling at the same time must succeed, got {rescheduled['status']}")
