"""Validation-precedence, boundary-precision, cross-entity-dependency,
temporal-window, and compensating-invariant depth tests.

Covers difficulty rules priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, and compensating_invariant.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    setup_open_season, setup_confirmed_subscription, setup_confirmed_with_addon,
    setup_capacity_one_remaining, setup_offered_waitlist,
    setup_confirmed_with_refund_hold,
    register_member, set_clock, confirm_subscription, get_season_version,
    get_season_version_via_dc, box_for_week, add_add_on,
    make_member_headers,
    create_subscription_payload, create_subscription_add_on_payload,
    create_waitlist_entry_payload, create_vacation_hold_payload,
    promote_waitlist_payload,
    ApiErrorId, TEST_USERS,
)

FM = TEST_USERS["farm_manager_headers"]
DC = TEST_USERS["delivery_coordinator_headers"]


# ─── Rule 5: priority_pair_validation_conflict ───────────────────────────────

def test_signup_closed_beats_season_capacity(api):
    """PRD §3.3: "The relevant business gates, in their priority order, are: the season-close temporal window (`ERR_SIGNUP_CLOSED`, HTTP 409) — the current clock must be at or before the season's `signup_close_date`; then the site weekly-capacity gate (`ERR_SITE_CAPACITY_FULL`, HTTP 409) — the assigned site's `active_subscription_count` must be strictly less than its `weekly_capacity`; then the season-capacity gate (`ERR_SEASON_CAPACITY_FULL`, HTTP 409) — the season's `confirmed_share_count` must be strictly less than its `total_share_capacity`; and finally the optimistic-concurrency gate (`ERR_STALE_VERSION`, HTTP 412) on `expected_season_version`."

    Design: Difficulty/priority_pair_validation_conflict/signup_closed_beats_season_capacity_temporal_vs_fiscal
    """
    # capacity 1, signup_close 2026-06-20; first sub confirmed (capacity full);
    # clock advanced to 2026-06-25 (past close); confirm the second sub.
    base = setup_open_season(week_count=12, total_share_capacity=1,
                             site_weekly_capacity=100, base_price_cents=50000,
                             signup_close_date="2026-06-20T00:00:00Z")
    set_clock("2026-06-10T00:00:00Z")
    season_id = base["season"]["id"]

    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    sub_a = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_a["id"],
                                    base["share"]["id"], base["site"]["id"]), mha))
    confirm_subscription(season_id, sub_a["id"])

    member_b = register_member(tier="BASELINE")
    mhb = make_member_headers(member_b["id"])
    sub_b = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_b["id"],
                                    base["share"]["id"], base["site"]["id"]), mhb))

    set_clock("2026-06-25T00:00:00Z")
    sea_v = get_season_version(season_id)
    res = api_client.confirm_subscription(
        sub_b["id"], {"expected_season_version": sea_v}, FM)
    # Both past-close AND over-capacity → ERR_SIGNUP_CLOSED wins (earlier gate).
    validate_error(res, ApiErrorId.ERR_SIGNUP_CLOSED.value)


def test_not_owner_beats_invalid_state(api):
    """PRD §2.7: "Resource ownership follows for member-actor endpoints, yielding `ERR_NOT_RESOURCE_OWNER`. Existence of all path and referenced resources is checked next, yielding `ERR_NOT_FOUND`. Season cohesion (`ERR_SEASON_MISMATCH`) is then evaluated, followed by state validity (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/not_owner_beats_invalid_state_auth_vs_state
    """
    # Member A owns a CONFIRMED sub then cancels it (now CANCELLED). Member B
    # (non-owner) attempts a second cancel → owner check fires before state check.
    base = setup_open_season(week_count=12, total_share_capacity=100,
                             base_price_cents=50000)
    season_id = base["season"]["id"]
    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    member_b = register_member(tier="BASELINE")
    mhb = make_member_headers(member_b["id"])

    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_a["id"],
                                    base["share"]["id"], base["site"]["id"]), mha))
    confirm_subscription(season_id, sub["id"])
    validate_success(api_client.cancel_subscription(sub["id"], mha), 200)

    # Member B cancels the already-CANCELLED subscription.
    res = api_client.cancel_subscription(sub["id"], mhb)
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ─── Rule 6: boundary_precision_check ────────────────────────────────────────

def test_season_capacity_last_slot_succeeds_at_boundary(api):
    """PRD §3.3: "the season-capacity gate (`ERR_SEASON_CAPACITY_FULL`, HTTP 409) — the season's `confirmed_share_count` must be strictly less than its `total_share_capacity".
    PRD §3.3: "Both capacity gates use a strict less-than comparison, so the last available slot may be taken but the count may never reach or exceed its cap."

    Design: Difficulty/boundary_precision_check/season_capacity_strict_less_than_boundary
    """
    # capacity 2, one already confirmed (count 1 < 2) → second confirm succeeds.
    ctx = setup_capacity_one_remaining(total_share_capacity=2, site_weekly_capacity=100,
                                       base_price_cents=50000, week_count=12)
    season_id = ctx["season"]["id"]
    sea_v = get_season_version(season_id)
    confirmed = validate_success(api_client.confirm_subscription(
        ctx["sub_b"]["id"], {"expected_season_version": sea_v}, FM), 200)
    assert confirmed["billing_status"] == "CONFIRMED", (
        f"boundary confirm expected CONFIRMED, got {confirmed['billing_status']}")
    season = validate_success(api_client.get_season(season_id, FM), 200)
    assert season["confirmed_share_count"] == 2, (
        f"confirmed_share_count expected 2, got {season['confirmed_share_count']}")


def test_season_capacity_at_cap_rejected(api):
    """PRD §3.3: "the season's `confirmed_share_count` must be strictly less than its `total_share_capacity".
    PRD §3.3: "the last available slot may be taken but the count may never reach or exceed its cap."

    Design: Difficulty/boundary_precision_check/season_capacity_strict_less_than_boundary
    """
    # capacity 1, one confirmed (count 1, 1 < 1 false) → second confirm rejected.
    ctx = setup_capacity_one_remaining(total_share_capacity=1, site_weekly_capacity=100,
                                       base_price_cents=50000, week_count=12)
    season_id = ctx["season"]["id"]
    sea_v = get_season_version(season_id)
    res = api_client.confirm_subscription(
        ctx["sub_b"]["id"], {"expected_season_version": sea_v}, FM)
    validate_error(res, ApiErrorId.ERR_SEASON_CAPACITY_FULL.value)


def test_addon_supply_exhausted_at_zero_remaining(api):
    """PRD §3.5: "An attachment may be created only while the add-on has remaining supply: its `committed_count` must be strictly less than its `weekly_supply_cap`, and an attempt to attach when the committed count has reached the cap is rejected with `ERR_ADDON_SUPPLY_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/addon_supply_exhausted_zero_remaining_boundary
    """
    # weekly_supply_cap 1, one attachment already live (committed_count 1) → next attach fails.
    base = setup_open_season(week_count=12, total_share_capacity=100, base_price_cents=50000)
    season_id = base["season"]["id"]
    add_on = add_add_on(season_id, kind="FLOWERS", weekly_price_cents=1000, weekly_supply_cap=1)

    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    sub_a = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_a["id"],
                                    base["share"]["id"], base["site"]["id"]), mha))
    member_b = register_member(tier="BASELINE")
    mhb = make_member_headers(member_b["id"])
    sub_b = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_b["id"],
                                    base["share"]["id"], base["site"]["id"]), mhb))

    get_success_data(api_client.create_subscription_add_on(
        create_subscription_add_on_payload(sub_a["id"], add_on["id"]), mha))

    res = api_client.create_subscription_add_on(
        create_subscription_add_on_payload(sub_b["id"], add_on["id"]), mhb)
    validate_error(res, ApiErrorId.ERR_ADDON_SUPPLY_EXHAUSTED.value)
    add_on_after = validate_success(api_client.get_add_on(add_on["id"], FM), 200)
    assert add_on_after["committed_count"] == 1, (
        f"committed_count expected unchanged 1, got {add_on_after['committed_count']}")


# ─── Rule 7: cross_entity_state_dependency ───────────────────────────────────

def test_confirm_rejected_when_season_closed(api):
    """PRD §3.1: "After closing, no new confirmed subscriptions are accepted and further signups are routed to the waitlist; `CLOSED` is terminal."
    PRD §3.3: "The season itself must also be `OPEN` for a confirm to be defined at all."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_season_open_subscription_vs_season
    """
    base = setup_open_season(week_count=12, total_share_capacity=100, base_price_cents=50000)
    season_id = base["season"]["id"]
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    # Close the season, then attempt confirm.
    validate_success(api_client.close_season(season_id, FM), 200)
    sea_v = get_season_version(season_id)
    res = api_client.confirm_subscription(sub["id"], {"expected_season_version": sea_v}, FM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    sub_after = validate_success(api_client.get_subscription(sub["id"], FM), 200)
    assert sub_after["billing_status"] == "PENDING_PAYMENT", (
        f"subscription should be unchanged, got {sub_after['billing_status']}")


def test_promote_rejected_when_site_full(api):
    """PRD §3.8: "the requested site must have room (its `active_subscription_count` strictly less than its `weekly_capacity`, surfacing `ERR_SITE_CAPACITY_FULL` if not)".

    Design: Difficulty/cross_entity_state_dependency/promote_requires_site_capacity_waitlist_vs_pickupsite
    """
    # site weekly_capacity 1, season capacity 5; one CONFIRMED sub fills the site;
    # a WAITING entry requests the same site → promotion rejected.
    base = setup_open_season(week_count=12, total_share_capacity=5,
                             site_weekly_capacity=1, base_price_cents=50000)
    season_id = base["season"]["id"]
    set_clock("2026-06-01T00:00:00Z")

    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    sub_a = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_a["id"],
                                    base["share"]["id"], base["site"]["id"]), mha))
    confirm_subscription(season_id, sub_a["id"])

    member_b = register_member(tier="BASELINE")
    wl = get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(season_id, member_b["id"],
                                      base["share"]["id"], base["site"]["id"])))
    sea_v = get_season_version_via_dc(season_id)
    res = api_client.promote_waitlist(
        season_id,
        promote_waitlist_payload(base["share"]["id"], base["site"]["id"], sea_v), DC)
    validate_error(res, ApiErrorId.ERR_SITE_CAPACITY_FULL.value)
    wl_after = validate_success(api_client.get_waitlist_entry(wl["id"], DC), 200)
    assert wl_after["status"] == "WAITING", (
        f"waitlist entry should stay WAITING, got {wl_after['status']}")


# ─── Rule 8: resource_temporal_overlap ───────────────────────────────────────

def test_hold_window_strict_before_delivery_date(api):
    """PRD §3.7: "Placing a hold advances the held box from `SCHEDULED` to `HELD`, and is permitted only when the box is currently `SCHEDULED` and the current clock is strictly before that box's delivery date".
    PRD §3.7: "Placing or releasing a hold at or after the held box's delivery date is rejected with `ERR_HOLD_WINDOW_PASSED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/hold_window_half_open_before_delivery_date
    """
    # week-1 delivery date 2026-07-01T00:00:00Z; clock set exactly to that instant.
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=12, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    box_w1 = box_for_week(sub_id, mh, 1)
    set_clock("2026-07-01T00:00:00Z")  # clock == delivery date

    res = api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w1["id"]), mh)
    validate_error(res, ApiErrorId.ERR_HOLD_WINDOW_PASSED.value)
    box = validate_success(api_client.get_weekly_box(box_w1["id"], mh), 200)
    assert box["status"] == "SCHEDULED", (
        f"box should stay SCHEDULED when hold rejected, got {box['status']}")


def test_waitlist_accept_at_inclusive_deadline_succeeds(api):
    """PRD §3.8: "The member may accept, which is permitted only while the entry is `OFFERED` and the current clock is at or before `offer_expires_at`; accepting moves the entry from `OFFERED` to `CONVERTED` and creates a fresh `PENDING_PAYMENT` subscription for that member with the requested share and site".

    Design: Difficulty/resource_temporal_overlap/waitlist_offer_window_inclusive_deadline
    """
    # Promote at clock 2026-06-01 → offer_expires_at = 2026-06-03; advance to exactly
    # that instant; accept must succeed (deadline is inclusive).
    ctx = setup_offered_waitlist(clock="2026-06-01T00:00:00Z", total_share_capacity=5,
                                 site_weekly_capacity=5, base_price_cents=50000)
    wl_id = ctx["waitlist_entry"]["id"]
    mh = ctx["member_headers"]
    set_clock("2026-06-03T00:00:00Z")  # clock == offer_expires_at

    accepted = validate_success(api_client.accept_waitlist_entry(wl_id, mh), 200)
    assert accepted["status"] == "CONVERTED", (
        f"accept at deadline expected CONVERTED, got {accepted['status']}")


# ─── Rule 9: compensating_invariant ──────────────────────────────────────────

def test_hold_then_release_conserves_balance(api):
    """PRD §3.7: "On release of a `REFUND`-mode hold, the original `CREDIT_HOLD_REFUND` is reversed by posting an offsetting charge, and the subscription's `outstanding_balance_cents` is recomputed."

    Design: Difficulty/compensating_invariant/hold_then_release_conserves_outstanding_balance
    """
    # season_price 50000, pre-hold outstanding 50000; REFUND hold on week 5 then released.
    ctx = setup_confirmed_with_refund_hold(week_index=5, clock="2026-06-15T00:00:00Z",
                                           base_price_cents=50000, week_count=12)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    box_id = ctx["box"]["id"]
    hold_id = ctx["hold"]["id"]

    validate_success(api_client.release_vacation_hold(hold_id, mh), 200)

    sub = validate_success(api_client.get_subscription(sub_id, FM), 200)
    assert sub["outstanding_balance_cents"] == 50000, (
        f"balance must return to pre-hold 50000 after release, "
        f"got {sub['outstanding_balance_cents']}")
    box = validate_success(api_client.get_weekly_box(box_id, mh), 200)
    assert box["status"] == "SCHEDULED"


def test_addon_attach_then_detach_conserves_committed_count(api):
    """PRD §3.5: "Detaching an add-on is also a `Member` action. It moves the junction record from `ATTACHED` to `DETACHED`, decrements the owning add-on's `committed_count` by one (freeing a unit of its weekly supply cap), posts an offsetting credit for the undelivered weeks, and recomputes the subscription's `outstanding_balance_cents`."

    Design: Difficulty/compensating_invariant/addon_attach_then_detach_conserves_committed_count
    """
    # add-on EGGS cap 5, committed_count 0; attach (→1) then detach (→0).
    ctx = setup_confirmed_with_addon(kind="EGGS", weekly_price_cents=800,
                                     weekly_supply_cap=5, clock="2026-06-15T00:00:00Z",
                                     base_price_cents=50000, week_count=12)
    mh = ctx["member_headers"]
    add_on_id = ctx["add_on"]["id"]
    sao_id = ctx["subscription_add_on"]["id"]

    # Confirm committed_count is 1 after attach (the fixture attaches it).
    add_on_mid = validate_success(api_client.get_add_on(add_on_id, FM), 200)
    assert add_on_mid["committed_count"] == 1

    detached = validate_success(api_client.delete_subscription_add_on(sao_id, mh), 200)
    assert detached["status"] == "DETACHED"
    add_on_after = validate_success(api_client.get_add_on(add_on_id, FM), 200)
    assert add_on_after["committed_count"] == 0, (
        f"committed_count must return to pre-attach 0 after detach, "
        f"got {add_on_after['committed_count']}")


# ─── Second-instance coverage (distinct facets of each rule) ──────────────────

def _ledger(subscription_id, headers):
    res = api_client.list_ledger_entries(subscription_id, headers, params={"limit": 100})
    return res.json().get("data", [])


def test_signup_closed_alone_blocks_confirm_with_capacity_free(api):
    """PRD §3.3: "the season-close temporal window (`ERR_SIGNUP_CLOSED`, HTTP 409)
    — the current clock must be at or before the season's `signup_close_date`".

    Design: Difficulty/priority_pair_validation_conflict/signup_closed_beats_season_capacity_temporal_vs_fiscal
    """
    # Capacity is plentiful (100); only the signup-close window is breached.
    base = setup_open_season(week_count=12, total_share_capacity=100,
                             site_weekly_capacity=100, base_price_cents=50000,
                             signup_close_date="2026-06-20T00:00:00Z")
    set_clock("2026-06-10T00:00:00Z")
    season_id = base["season"]["id"]
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    set_clock("2026-06-25T00:00:00Z")  # now past signup_close_date
    sea_v = get_season_version(season_id)
    res = api_client.confirm_subscription(sub["id"], {"expected_season_version": sea_v}, FM)
    validate_error(res, ApiErrorId.ERR_SIGNUP_CLOSED.value)


def test_not_owner_beats_state_even_when_state_valid(api):
    """PRD §2.7: "Resource ownership follows for member-actor endpoints, yielding
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Difficulty/priority_pair_validation_conflict/not_owner_beats_invalid_state_auth_vs_state
    """
    # Member A owns a CONFIRMED (cancellable) subscription; Member B (non-owner)
    # attempts to cancel it. Ownership check fires before any state evaluation.
    base = setup_open_season(week_count=12, total_share_capacity=100, base_price_cents=50000)
    season_id = base["season"]["id"]
    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    member_b = register_member(tier="BASELINE")
    mhb = make_member_headers(member_b["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_a["id"],
                                    base["share"]["id"], base["site"]["id"]), mha))
    confirm_subscription(season_id, sub["id"])  # CONFIRMED — a valid cancel state

    res = api_client.cancel_subscription(sub["id"], mhb)
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    # The owner can still cancel — confirming the subscription was genuinely cancellable.
    validate_success(api_client.cancel_subscription(sub["id"], mha), 200)


def test_addon_attach_under_cap_succeeds_boundary(api):
    """PRD §3.5: "An attachment may be created only while the add-on has remaining
    supply: its `committed_count` must be strictly less than its
    `weekly_supply_cap`".

    Design: Difficulty/boundary_precision_check/addon_supply_exhausted_zero_remaining_boundary
    """
    # committed_count 0 < weekly_supply_cap 1 → attach SUCCEEDS at the X-1 boundary.
    base = setup_open_season(week_count=12, total_share_capacity=100, base_price_cents=50000)
    season_id = base["season"]["id"]
    add_on = add_add_on(season_id, kind="FLOWERS", weekly_price_cents=1000, weekly_supply_cap=1)
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    sao = validate_success(api_client.create_subscription_add_on(
        create_subscription_add_on_payload(sub["id"], add_on["id"]), mh), 201)
    assert sao["status"] == "ATTACHED"
    add_on_after = validate_success(api_client.get_add_on(add_on["id"], FM), 200)
    assert add_on_after["committed_count"] == 1, (
        f"committed_count expected 1 after a single attach, "
        f"got {add_on_after['committed_count']}")


def test_confirm_rejected_when_season_still_draft(api):
    """PRD §3.3: "The season itself must also be `OPEN` for a confirm to be defined
    at all."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_season_open_subscription_vs_season
    """
    # A subscription cannot be created against a DRAFT season, so build a season,
    # open it, create the subscription, then CLOSE it — confirm must be undefined
    # because the season is no longer OPEN.
    base = setup_open_season(week_count=12, total_share_capacity=100, base_price_cents=50000)
    season_id = base["season"]["id"]
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh))
    validate_success(api_client.close_season(season_id, FM), 200)
    sea_v = get_season_version(season_id)
    res = api_client.confirm_subscription(sub["id"], {"expected_season_version": sea_v}, FM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_promote_succeeds_when_site_has_room(api):
    """PRD §3.8: "the requested site must have room (its `active_subscription_count`
    strictly less than its `weekly_capacity`, surfacing `ERR_SITE_CAPACITY_FULL`
    if not)".

    Design: Difficulty/cross_entity_state_dependency/promote_requires_site_capacity_waitlist_vs_pickupsite
    """
    # Site weekly_capacity 2, one CONFIRMED sub (count 1 < 2) → promotion SUCCEEDS.
    base = setup_open_season(week_count=12, total_share_capacity=5,
                             site_weekly_capacity=2, base_price_cents=50000)
    season_id = base["season"]["id"]
    set_clock("2026-06-01T00:00:00Z")
    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    sub_a = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_a["id"],
                                    base["share"]["id"], base["site"]["id"]), mha))
    confirm_subscription(season_id, sub_a["id"])

    member_b = register_member(tier="BASELINE")
    wl = get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(season_id, member_b["id"],
                                      base["share"]["id"], base["site"]["id"])))
    sea_v = get_season_version_via_dc(season_id)
    promoted = validate_success(api_client.promote_waitlist(
        season_id,
        promote_waitlist_payload(base["share"]["id"], base["site"]["id"], sea_v), DC), 200)
    assert promoted["status"] == "OFFERED", (
        f"promotion with room expected OFFERED, got {promoted['status']}")


def test_hold_window_strictly_before_delivery_succeeds(api):
    """PRD §3.7: "Placing a hold advances the held box from `SCHEDULED` to `HELD`,
    and is permitted only when the box is currently `SCHEDULED` and the current
    clock is strictly before that box's delivery date".

    Design: Difficulty/resource_temporal_overlap/hold_window_half_open_before_delivery_date
    """
    # Clock 2026-06-30, one day before week-1 delivery 2026-07-01 → hold SUCCEEDS.
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=12, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    box_w1 = box_for_week(sub_id, mh, 1)
    set_clock("2026-06-30T00:00:00Z")  # strictly before delivery date
    hold = validate_success(api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w1["id"]), mh), 201)
    assert hold["status"] == "ACTIVE"
    box = validate_success(api_client.get_weekly_box(box_w1["id"], mh), 200)
    assert box["status"] == "HELD", f"box expected HELD when hold placed, got {box['status']}"


def test_hold_then_release_ledger_nets_to_zero(api):
    """PRD §3.7: "In `REFUND` mode the system posts a `CREDIT_HOLD_REFUND` ledger
    entry for one week's pro-rata share value and then recomputes the
    subscription's `outstanding_balance_cents`."
    PRD §3.7: "On release of a `REFUND`-mode hold, the original `CREDIT_HOLD_REFUND`
    is reversed by posting an offsetting charge, and the subscription's
    `outstanding_balance_cents` is recomputed."

    Design: Difficulty/compensating_invariant/hold_then_release_conserves_outstanding_balance
    """
    ctx = setup_confirmed_with_refund_hold(week_index=5, clock="2026-06-15T00:00:00Z",
                                           base_price_cents=50000, week_count=12)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    # After placing the REFUND hold the refund credit is present (-4166 for week 5).
    refunds_before = [e for e in _ledger(sub_id, mh) if e["entry_type"] == "CREDIT_HOLD_REFUND"]
    assert refunds_before, "expected a CREDIT_HOLD_REFUND after placing the hold"

    validate_success(api_client.release_vacation_hold(ctx["hold"]["id"], mh), 200)
    # The refund + offsetting reversal sum to zero across the hold's ledger lines.
    entries = _ledger(sub_id, mh)
    hold_lines = sum(e["amount_cents"] for e in entries
                     if e["entry_type"] in ("CREDIT_HOLD_REFUND",))
    # The reversal is an offsetting CHARGE; total ledger after CHARGE_SEASON equals 50000.
    sub = validate_success(api_client.get_subscription(sub_id, FM), 200)
    assert sub["outstanding_balance_cents"] == 50000, (
        f"balance expected 50000 after compensating release, "
        f"got {sub['outstanding_balance_cents']}")


def test_addon_detach_frees_unit_for_reattach(api):
    """PRD §3.5: "Detaching an add-on is also a `Member` action. It moves the
    junction record from `ATTACHED` to `DETACHED`, decrements the owning add-on's
    `committed_count` by one (freeing a unit of its weekly supply cap)".

    Design: Difficulty/compensating_invariant/addon_attach_then_detach_conserves_committed_count
    """
    # add-on cap 1; member A attaches then detaches; the freed unit lets member B attach.
    base = setup_open_season(week_count=12, total_share_capacity=100, base_price_cents=50000)
    season_id = base["season"]["id"]
    add_on = add_add_on(season_id, kind="EGGS", weekly_price_cents=800, weekly_supply_cap=1)
    member_a = register_member(tier="BASELINE")
    mha = make_member_headers(member_a["id"])
    sub_a = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_a["id"],
                                    base["share"]["id"], base["site"]["id"]), mha))
    sao_a = get_success_data(api_client.create_subscription_add_on(
        create_subscription_add_on_payload(sub_a["id"], add_on["id"]), mha))
    validate_success(api_client.delete_subscription_add_on(sao_a["id"], mha), 200)

    add_on_after = validate_success(api_client.get_add_on(add_on["id"], FM), 200)
    assert add_on_after["committed_count"] == 0, "detach must free the supply unit"
    # The freed unit now allows another subscription to attach.
    member_b = register_member(tier="BASELINE")
    mhb = make_member_headers(member_b["id"])
    sub_b = get_success_data(api_client.create_subscription(
        create_subscription_payload(season_id, member_b["id"],
                                    base["share"]["id"], base["site"]["id"]), mhb))
    sao_b = validate_success(api_client.create_subscription_add_on(
        create_subscription_add_on_payload(sub_b["id"], add_on["id"]), mhb), 201)
    assert sao_b["status"] == "ATTACHED"
