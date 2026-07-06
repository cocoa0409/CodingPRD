"""Budget, pacing, OCC, and temporal-overlap tests: daily-cap boundary,
deliverables boundary, validation-priority pairs, slot overlap/gap, budget
ceiling and overspend errors, OCC stale-version, derived-budget reconciliation,
and immediate consistency.

Covers difficulty rules boundary_precision_check, priority_pair_validation_conflict,
resource_temporal_overlap and the corner errors / cross_cutting / consistency sections.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_active_client, create_published_content, create_scheduled_content,
    create_draft_boost, reserve_boost, setup_running_boost,
    create_accepted_collab, add_cleared_assets,
    setup_reserved_boost_on_scheduled_content,
)
from test_helpers import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]


# ===========================================================================
# boundary_precision_check / daily_cap_exact_boundary_on_record_spend
# ===========================================================================
def test_record_spend_at_daily_cap_boundary_accepted(api):
    """PRD §3.4: "the bucket total for a given day is the sum of the amounts of all
    prior record-spends carrying the same `spend_day_index` plus this call's
    `amount_cents`, and if that bucket total exceeds `daily_cap_cents` the call is
    rejected with `ERR_DAILY_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/daily_cap_exact_boundary_on_record_spend
    """
    client, channel, item, boost = setup_running_boost(
        requested_budget_cents=200000, daily_cap_cents=50000, duration_days=4)
    spent = validate_success(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 50000, "spend_day_index": 0}, FC))
    # amount == daily_cap is accepted (strict >)
    assert spent["spent_budget_cents"] == 50000, (
        f"spend at exactly the cap must be accepted, got {spent['spent_budget_cents']}")


def test_record_spend_above_daily_cap_rejected(api):
    """PRD §3.4: "if that bucket total exceeds `daily_cap_cents` the call is
    rejected with `ERR_DAILY_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/daily_cap_exact_boundary_on_record_spend
    """
    client, channel, item, boost = setup_running_boost(
        requested_budget_cents=200000, daily_cap_cents=50000, duration_days=4)
    get_success_data(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 50000, "spend_day_index": 0}, FC))
    # fresh day-1 bucket with 50001 > daily_cap 50000
    validate_error(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 50001, "spend_day_index": 1}, FC),
        ApiErrorId.ERR_DAILY_CAP_EXCEEDED.value)


# ===========================================================================
# boundary_precision_check / deliverables_empty_and_exact_boundary_on_mark_delivered
# ===========================================================================
def test_mark_delivered_below_deliverable_count_rejected(api):
    """PRD §3.6: "Marking a collaboration delivered advances it from `ACCEPTED` to
    `DELIVERED`, but only when its `approved_asset_count` is at least its
    `deliverable_count` — that is, enough assets have cleared rights; a shortfall
    is rejected with `ERR_DELIVERABLES_NOT_MET`."

    Design: Difficulty/boundary_precision_check/deliverables_empty_and_exact_boundary_on_mark_delivered
    """
    client, _channel = setup_active_client(monthly_boost_budget_cents=0)
    collab = create_accepted_collab(client["id"], offer_fee_cents=50000, deliverable_count=2)
    add_cleared_assets(collab["id"], 1)  # approved_asset_count == 1 < 2
    validate_error(api.mark_delivered_influencer_collab(collab["id"], AM),
                   ApiErrorId.ERR_DELIVERABLES_NOT_MET.value)


def test_mark_delivered_at_exact_deliverable_count_succeeds(api):
    """PRD §3.6: "Marking a collaboration delivered advances it from `ACCEPTED` to
    `DELIVERED`, but only when its `approved_asset_count` is at least its
    `deliverable_count` — that is, enough assets have cleared rights; a shortfall
    is rejected with `ERR_DELIVERABLES_NOT_MET`."

    Design: Difficulty/boundary_precision_check/deliverables_empty_and_exact_boundary_on_mark_delivered
    """
    client, _channel = setup_active_client(monthly_boost_budget_cents=0)
    collab = create_accepted_collab(client["id"], offer_fee_cents=50000, deliverable_count=2)
    add_cleared_assets(collab["id"], 2)  # approved_asset_count == 2 (exact)
    delivered = validate_success(api.mark_delivered_influencer_collab(collab["id"], AM))
    assert delivered["status"] == "DELIVERED", f"expected DELIVERED, got {delivered['status']}"


# ===========================================================================
# priority_pair_validation_conflict / state_before_fiscal_on_boost_reserve
# ===========================================================================
def test_state_check_precedes_budget_check_on_reserve(api):
    """PRD §3.8: "Only then is the basic state-machine check applied: if the
    requested transition is not defined from the target's current state the
    request yields `ERR_INVALID_STATE`."
    PRD §3.8: "the boost budget ceiling (`ERR_BOOST_BUDGET_EXCEEDED`)" — listed
    among the later business-specific constraints, after the state check.

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_boost_reserve
    """
    # Reserve once (boost goes RESERVED, budget fully consumed); a second reserve
    # is both an invalid state AND over budget — state must win.
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=100000, monthly_post_quota=5, included_channels=1,
        platform="X")
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=100000, daily_cap_cents=50000,
                               duration_days=2)
    boost = reserve_boost(client["id"], boost["id"])
    cver2 = get_success_data(api.get_client(client["id"], FC))["version"]
    err = validate_error(
        api.reserve_boost_campaign(boost["id"], {"expected_client_version": cver2}, FC),
        ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_BOOST_BUDGET_EXCEEDED.value


def test_invalid_state_reserve_leaves_campaign_reserved(api):
    """PRD §3.8: "if the requested transition is not defined from the target's
    current state the request yields `ERR_INVALID_STATE`."
    PRD §3.4: "Reserving budget — a `FinanceController` action advancing the
    campaign from `DRAFT` to `RESERVED`".

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_boost_reserve
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=100000, monthly_post_quota=5, included_channels=1,
        platform="X")
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=100000, daily_cap_cents=50000,
                               duration_days=2)
    boost = reserve_boost(client["id"], boost["id"])
    cver2 = get_success_data(api.get_client(client["id"], FC))["version"]
    validate_error(
        api.reserve_boost_campaign(boost["id"], {"expected_client_version": cver2}, FC),
        ApiErrorId.ERR_INVALID_STATE.value)
    # The rejected re-reserve must not have advanced the campaign past RESERVED.
    refreshed = validate_success(api.get_boost_campaign(boost["id"], FC))
    assert refreshed["status"] == "RESERVED", (
        f"campaign must stay RESERVED after rejected re-reserve, got {refreshed['status']}")


# ===========================================================================
# priority_pair_validation_conflict / state_before_quota_on_publish
# ===========================================================================
def test_state_check_precedes_quota_check_on_publish(api):
    """PRD §3.8: "if the requested transition is not defined from the target's
    current state the request yields `ERR_INVALID_STATE`."
    PRD §3.3: "once the published count has reached the quota a further publish is
    rejected with `ERR_POST_QUOTA_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_quota_on_publish
    """
    # Quota 1, already at quota (1 published); a second item still APPROVED (not
    # SCHEDULED). Publishing the APPROVED item is an invalid state AND quota is
    # exhausted — state must win.
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=1, included_channels=1)
    create_published_content(client["id"], channel["id"], slot_start_utc="2026-03-01T09:00:00Z")
    # second item only approved
    from test_helpers import create_approved_content
    item2 = create_approved_content(client["id"], channel["id"])
    err = validate_error(api.publish_content_item(item2["id"], AM),
                         ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_POST_QUOTA_EXCEEDED.value


def test_invalid_state_publish_leaves_item_approved(api):
    """PRD §3.8: "if the requested transition is not defined from the target's
    current state the request yields `ERR_INVALID_STATE`."
    PRD §3.3: "Publishing is an `AccountManager` action that advances a `SCHEDULED`
    item to `PUBLISHED`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_quota_on_publish
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=1, included_channels=1)
    create_published_content(client["id"], channel["id"], slot_start_utc="2026-03-01T09:00:00Z")
    from test_helpers import create_approved_content
    item2 = create_approved_content(client["id"], channel["id"])
    validate_error(api.publish_content_item(item2["id"], AM),
                   ApiErrorId.ERR_INVALID_STATE.value)
    # The rejected publish must leave the APPROVED item unchanged.
    refreshed = validate_success(api.get_content_item(item2["id"], AM))
    assert refreshed["status"] == "APPROVED", (
        f"item must stay APPROVED after rejected publish, got {refreshed['status']}")


# ===========================================================================
# resource_temporal_overlap / schedule_slot_overlap_with_min_gap_buffer
# ===========================================================================
def test_schedule_within_gap_buffer_rejected(api):
    """PRD §3.2: "When a new slot would be placed on a channel, it must not overlap
    the half-open window of any slot on the same channel that is currently
    `RESERVED` or `FIRED`, and it must additionally be separated from the nearest
    such slot by at least the channel's `min_publish_gap_minutes`; a violation of
    either the overlap rule or the gap rule is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/schedule_slot_overlap_with_min_gap_buffer
    """
    client, channel = setup_active_client(
        monthly_boost_budget_cents=0, included_channels=1,
        platform="FACEBOOK", min_publish_gap_minutes=30)
    create_scheduled_content(client["id"], channel["id"], "2026-03-10T09:00:00Z", duration_minutes=15)
    from test_helpers import create_approved_content
    item2 = create_approved_content(client["id"], channel["id"])
    # 09:30 is only 15 minutes after the [09:00,09:15) window end; gap buffer needs >= 09:45.
    validate_error(api.schedule_content_item(item2["id"], {
        "channel_id": channel["id"],
        "slot_start_utc": "2026-03-10T09:30:00Z",
        "duration_minutes": 15,
    }, AM), ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_schedule_at_exact_gap_boundary_accepted(api):
    """PRD §3.2: "it must additionally be separated from the nearest such slot by
    at least the channel's `min_publish_gap_minutes`; a violation of either the
    overlap rule or the gap rule is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/schedule_slot_overlap_with_min_gap_buffer
    """
    client, channel = setup_active_client(
        monthly_boost_budget_cents=0, included_channels=1,
        platform="FACEBOOK", min_publish_gap_minutes=30)
    create_scheduled_content(client["id"], channel["id"], "2026-03-10T09:00:00Z", duration_minutes=15)
    from test_helpers import create_approved_content
    item2 = create_approved_content(client["id"], channel["id"])
    # 09:45 is exactly 30 minutes after the window end 09:15 -> accepted.
    scheduled = validate_success(api.schedule_content_item(item2["id"], {
        "channel_id": channel["id"],
        "slot_start_utc": "2026-03-10T09:45:00Z",
        "duration_minutes": 15,
    }, AM))
    assert scheduled["status"] == "SCHEDULED", f"expected SCHEDULED, got {scheduled['status']}"


# ===========================================================================
# resource_temporal_overlap / boost_daily_cap_capacity_window_overlap
# ===========================================================================
def test_same_day_aggregate_spend_exceeds_capacity_window(api):
    """PRD §3.4: "The daily cap is an aggregate per-day window, not a per-call
    ceiling: the bucket total for a given day is the sum of the amounts of all
    prior record-spends carrying the same `spend_day_index` plus this call's
    `amount_cents`, and if that bucket total exceeds `daily_cap_cents` the call is
    rejected with `ERR_DAILY_CAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/boost_daily_cap_capacity_window_overlap
    """
    client, channel, item, boost = setup_running_boost(
        requested_budget_cents=200000, daily_cap_cents=50000, duration_days=4)
    get_success_data(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 30000, "spend_day_index": 0}, FC))
    # second 30000 into the SAME day-0 bucket: aggregate 60000 > 50000 cap.
    validate_error(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 30000, "spend_day_index": 0}, FC),
        ApiErrorId.ERR_DAILY_CAP_EXCEEDED.value)


def test_fresh_day_bucket_opens_separate_capacity_window(api):
    """PRD §3.4: "The `spend_day_index` must be greater than or equal to the highest
    `spend_day_index` recorded so far — that is, monotonic non-decreasing — and a
    new, previously unseen index opens a fresh bucket."

    Design: Difficulty/resource_temporal_overlap/boost_daily_cap_capacity_window_overlap
    """
    client, channel, item, boost = setup_running_boost(
        requested_budget_cents=200000, daily_cap_cents=50000, duration_days=4)
    get_success_data(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 30000, "spend_day_index": 0}, FC))
    # The SAME 30000 in a fresh day-1 bucket is its own capacity window and is accepted.
    spent = validate_success(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 30000, "spend_day_index": 1}, FC))
    assert spent["spent_budget_cents"] == 60000, (
        f"two same-amount spends in distinct day buckets accumulate to 60000, got {spent['spent_budget_cents']}")
    assert spent["days_elapsed"] == 2, (
        f"a fresh day index must increment days_elapsed to 2, got {spent['days_elapsed']}")


# ===========================================================================
# corner errors section
# ===========================================================================
def test_reserve_over_available_budget_returns_402(api):
    """PRD §3.4: "the client's `boost_available_cents` must be at least the
    `requested_budget_cents`, and a request that would exceed available budget is
    rejected with `ERR_BOOST_BUDGET_EXCEEDED` and HTTP 402".

    Design: Corner/errors/corner_boost_budget_exceeded_on_reserve
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=100000, monthly_post_quota=5, included_channels=1,
        platform="X")
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=200000, daily_cap_cents=100000,
                               duration_days=2)
    cver = get_success_data(api.get_client(client["id"], FC))["version"]
    validate_error(
        api.reserve_boost_campaign(boost["id"], {"expected_client_version": cver}, FC),
        ApiErrorId.ERR_BOOST_BUDGET_EXCEEDED.value)


def test_record_spend_over_reservation_returns_overspend(api):
    """PRD §3.4: "the campaign's reservation ceiling must hold: the existing
    `spent_budget_cents` plus this call's `amount_cents` must not exceed
    `reserved_budget_cents`, and a breach is rejected with `ERR_BOOST_OVERSPEND`
    and HTTP 402."

    Design: Corner/errors/corner_boost_overspend_returns_402
    """
    client, channel, item, boost = setup_running_boost(
        requested_budget_cents=100000, daily_cap_cents=60000, duration_days=2,
        monthly_boost_budget_cents=1000000)
    get_success_data(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 60000, "spend_day_index": 0}, FC))
    # day-1 bucket 50000 (<= 60000 cap, cap does not bind), but 60000+50000=110000 > reserved 100000
    validate_error(api.record_spend_boost_campaign(
        boost["id"], {"amount_cents": 50000, "spend_day_index": 1}, FC),
        ApiErrorId.ERR_BOOST_OVERSPEND.value)


# ===========================================================================
# corner cross_cutting_complexity_layers section
# ===========================================================================
def test_occ_stale_client_version_on_reserve_rejected(api):
    """PRD §2.7: "If they differ — meaning another writer has advanced the client's
    `version` since the caller last read it, and the caller's view of the
    available budget is therefore stale — the reservation is rejected with
    `ERR_STALE_CLIENT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_client_version_on_reserve
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000, included_channels=1)
    item = create_published_content(client["id"], channel["id"])
    boost1 = create_draft_boost(client["id"], item["id"],
                                requested_budget_cents=100000, daily_cap_cents=50000)
    boost2 = create_draft_boost(client["id"], item["id"],
                                requested_budget_cents=100000, daily_cap_cents=50000)
    cver1 = get_success_data(api.get_client(client["id"], FC))["version"]
    get_success_data(api.reserve_boost_campaign(
        boost1["id"], {"expected_client_version": cver1}, FC))  # bumps version
    # second reserve carries the now-stale pre-bump version
    validate_error(api.reserve_boost_campaign(
        boost2["id"], {"expected_client_version": cver1}, FC),
        ApiErrorId.ERR_STALE_CLIENT_VERSION.value)


def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §2.7: "the reserve operation is the only one that increments a client's
    `version`."
    PRD §3.4: "When a reservation succeeds ... the client's `version` is
    incremented by one."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_correct_version_succeeds_and_bumps
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000, included_channels=1)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=100000, daily_cap_cents=50000)
    cver = get_success_data(api.get_client(client["id"], FC))["version"]
    reserved = validate_success(api.reserve_boost_campaign(
        boost["id"], {"expected_client_version": cver}, FC))
    assert reserved["status"] == "RESERVED", f"expected RESERVED, got {reserved['status']}"
    after = validate_success(api.get_client(client["id"], FC))
    assert after["version"] == cver + 1, (
        f"client version must increment by 1, expected {cver + 1}, got {after['version']}")


def test_derived_budget_reconciliation_after_reserve(api):
    """PRD §2.6: "The client's `boost_reserved_cents` is the sum of
    `reserved_budget_cents` across that client's boost campaigns whose status is
    either `RESERVED` or `RUNNING`."
    PRD §2.6: "The client's `boost_available_cents` is the boost budget limit minus
    reserved minus spent — that is, `boost_budget_limit_cents` less
    `boost_reserved_cents` less `boost_spent_cents`".

    Design: Corner/cross_cutting_complexity_layers/corner_derived_budget_reconciliation_after_reserve
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000, included_channels=1)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=300000, daily_cap_cents=100000,
                               duration_days=3)
    reserve_boost(client["id"], boost["id"])
    refreshed = validate_success(api.get_client(client["id"], FC))
    assert refreshed["boost_reserved_cents"] == 300000, (
        f"reserved must be 300000, got {refreshed['boost_reserved_cents']}")
    # available = 1000000 - 300000 - 0 = 700000
    assert refreshed["boost_available_cents"] == 700000, (
        f"available must be 700000, got {refreshed['boost_available_cents']}")


# ===========================================================================
# corner consistency_model section
# ===========================================================================
def test_reserve_response_shows_immediate_state_and_budget(api):
    """PRD §3.4: "When a reservation succeeds, the campaign's `reserved_budget_cents`
    is set equal to the `requested_budget_cents`".
    PRD §4: "Operations that modify an existing resource ... return a `200 OK`
    status code ... operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/consistency_model/corner_immediate_consistency_reserve_visible_same_request
    """
    client, channel = setup_active_client(monthly_boost_budget_cents=1000000, included_channels=1)
    item = create_published_content(client["id"], channel["id"])
    boost = create_draft_boost(client["id"], item["id"],
                               requested_budget_cents=150000, daily_cap_cents=75000,
                               duration_days=2)
    cver = get_success_data(api.get_client(client["id"], FC))["version"]
    reserved = validate_success(api.reserve_boost_campaign(
        boost["id"], {"expected_client_version": cver}, FC))
    assert reserved["status"] == "RESERVED", (
        f"reserve response itself must show RESERVED, got {reserved['status']}")
    assert reserved["reserved_budget_cents"] == 150000, (
        f"reserve response must show reserved_budget_cents 150000, got {reserved['reserved_budget_cents']}")
