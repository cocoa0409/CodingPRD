"""Validation-ordering precedence conflicts, the wave-OPEN cross-entity
precondition, aggregate wave-capacity and box-period point-exclusivity overlaps,
and optimistic concurrency control on wave and subscription versions.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId, TEST_USERS, make_subscriber_headers,
    cancel_payload, prepay_payload, pause_payload, create_allocation_payload,
    create_gift_grant_payload, redeem_gift_payload,
    set_clock, get_wave, get_product, get_subscription, get_box_selection,
    create_plan, create_product, create_subscriber, create_subscription,
    create_wave, curate_box, reserve_box_into_wave,
    setup_reserved_allocation,
)

ADMIN = TEST_USERS["curation_admin_headers"]


# ─── priority_pair: cutoff(9) beats inventory(10) (queue A, >=2 tests) ──────

def _setup_short_box_past_cutoff():
    """Box [A,A] needs A x2 but A.on_hand=1 (short), and clock is at the cutoff."""
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="PP1", period_price_cents=6000, box_item_count=2)
    pa = create_product(sku="PP1A", name="PP1 A", on_hand_qty=1)
    subscriber = create_subscriber(email="pp1@x.com", full_name="PP1 S")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [pa["id"], pa["id"]])
    wave = create_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    set_clock("2026-06-10T00:00:00Z")  # at cutoff (cutoff passed) AND product short
    return {"sub": sub, "box": box, "wave": wave, "pa": pa}


def test_allocation_cutoff_passed_beats_insufficient_inventory(api):
    """PRD §2.8: "9. **Temporal constraints** — win-back window, cutoff timing,
    resume-date sanity, each yielding HTTP 422. 10. **Safety constraints** —
    empty-wave shipping and insufficient inventory, each yielding HTTP 422."
    PRD §2.8: "Within a single request, an earlier check that fails masks every
    later one."

    Cutoff (priority 9) is reported ahead of insufficient inventory (priority 10).

    Design: Difficulty/priority_pair_validation_conflict/allocation_temporal_cutoff_beats_safety_inventory
    """
    ctx = _setup_short_box_past_cutoff()
    res = api.create_allocation(
        create_allocation_payload(ctx["sub"]["id"], ctx["wave"]["id"], ctx["box"]["id"],
                                  ctx["wave"]["version"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_CUTOFF_PASSED.value, expected_status=422)


def test_allocation_cutoff_conflict_does_not_reserve_inventory(api):
    """PRD §2.8: "Within a single request, an earlier check that fails masks every
    later one."
    PRD §3.8: "if any single product is short, the entire box is rejected with
    `ERR_INSUFFICIENT_INVENTORY` and nothing is reserved."

    The cutoff failure pre-empts everything, so no inventory is reserved.

    Design: Difficulty/priority_pair_validation_conflict/allocation_temporal_cutoff_beats_safety_inventory
    """
    ctx = _setup_short_box_past_cutoff()
    api.create_allocation(
        create_allocation_payload(ctx["sub"]["id"], ctx["wave"]["id"], ctx["box"]["id"],
                                  ctx["wave"]["version"]), ADMIN)
    assert get_product(ctx["pa"]["id"])["allocated_qty"] == 0
    assert get_wave(ctx["wave"]["id"])["reserved_count"] == 0


# ─── priority_pair: gift constraint(8) beats window(9) (queue A, >=2 tests) ─

def _setup_cancelled_gift_past_window():
    """A gift subscription, cancelled, with the clock > 60 days past cancellation."""
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="GP", period_price_cents=6000, box_item_count=1)
    gifter = create_subscriber(email="gifter@x.com", full_name="Gifter")
    gres = api_client.create_gift_grant(
        create_gift_grant_payload(plan["id"], gifter["id"], 1, "rec@x.com"),
        make_subscriber_headers(gifter["id"]))
    gift = validate_success(gres, 201)
    recipient = create_subscriber(email="rec@x.com", full_name="Recipient")
    rec_headers = make_subscriber_headers(recipient["id"])
    rres = api_client.redeem_gift_grant(
        redeem_gift_payload(gift["redemption_code"], recipient["id"]), rec_headers)
    gsub = validate_success(rres, 201)
    validate_success(api_client.cancel_subscription(gsub["id"], cancel_payload("IMMEDIATE"), rec_headers), 200)
    set_clock("2026-09-01T00:00:00Z")  # > 60 days past cancellation
    return {"gsub": gsub, "rec_headers": rec_headers}


def test_winback_gift_not_reactivatable_beats_window_closed(api):
    """PRD §3.3: "when `is_gift` is false, because a gift subscription can never be
    win-back reactivated and such a request is rejected with
    `ERR_GIFT_NOT_REACTIVATABLE`".
    PRD §2.8: "**Business constraints** — the eligibility rules enumerated in §3
    (prepaid term offered, plan not retired, gift not reactivatable, pause limit,
    box item count, gift redeemable, box not already finalized), each yielding HTTP 422."
    PRD §2.8: "**Temporal constraints** — win-back window, cutoff timing,
    resume-date sanity, each yielding HTTP 422."
    PRD §2.8: "Within a single request, an earlier check that fails masks every
    later one."

    The gift constraint (priority 8) is reported ahead of the closed window
    (priority 9).

    Design: Difficulty/priority_pair_validation_conflict/winback_constraint_gift_beats_temporal_window
    """
    ctx = _setup_cancelled_gift_past_window()
    res = api.winback_subscription(ctx["gsub"]["id"], ctx["rec_headers"])
    validate_error(res, ApiErrorId.ERR_GIFT_NOT_REACTIVATABLE.value, expected_status=422)


def test_winback_gift_conflict_leaves_subscription_cancelled(api):
    """PRD §3.3: "a gift subscription can never be win-back reactivated and such a
    request is rejected with `ERR_GIFT_NOT_REACTIVATABLE`".

    The rejected win-back does not transition the gift subscription.

    Design: Difficulty/priority_pair_validation_conflict/winback_constraint_gift_beats_temporal_window
    """
    ctx = _setup_cancelled_gift_past_window()
    api.winback_subscription(ctx["gsub"]["id"], ctx["rec_headers"])
    assert get_subscription(ctx["gsub"]["id"])["lifecycle_status"] == "CANCELLED"


# ─── cross_entity_state_dependency: allocation needs wave OPEN (queue A, >=2) ─

def test_allocation_rejected_when_wave_locked(api):
    """PRD §3.8: "The referenced wave must be `OPEN` (otherwise the state check
    fails with `ERR_INVALID_STATE`)".
    PRD §3.9: "Locking moves the wave `OPEN` → `LOCKED`, after which no new
    allocations may attach (reservation requires an `OPEN` wave)."

    Design: Difficulty/cross_entity_state_dependency/allocation_requires_wave_open_not_locked
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="CE1", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="CE1P", name="CE1 P", on_hand_qty=5)
    subscriber = create_subscriber(email="ce1@x.com", full_name="CE1 S")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [product["id"]])
    wave = create_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    set_clock("2026-06-10T00:00:00Z")
    locked = validate_success(api.lock_wave(wave["id"], ADMIN), 200)
    assert locked["status"] == "LOCKED"
    res = api.create_allocation(
        create_allocation_payload(sub["id"], wave["id"], box["id"], locked["version"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_allocation_succeeds_while_wave_open(api):
    """PRD §3.8: "The referenced wave must be `OPEN` (otherwise the state check
    fails with `ERR_INVALID_STATE`)".
    PRD §3.8: "When both checks pass, the allocation is created `RESERVED`".

    The positive companion: an OPEN wave admits the allocation (201, RESERVED).

    Design: Difficulty/cross_entity_state_dependency/allocation_requires_wave_open_not_locked
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="CE1b", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="CE1Pb", name="CE1 Pb", on_hand_qty=5)
    subscriber = create_subscriber(email="ce1b@x.com", full_name="CE1 Sb")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [product["id"]])
    wave = create_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    res = api.create_allocation(
        create_allocation_payload(sub["id"], wave["id"], box["id"], wave["version"]), ADMIN)
    alloc = validate_success(res, 201)
    assert alloc["status"] == "RESERVED"


# ─── resource_temporal_overlap: wave capacity full (queue A, >=2 tests) ─────

def _setup_capacity_one_wave_with_one_reservation():
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="TO1", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="TO1P", name="TO1 P", on_hand_qty=9)
    s1 = create_subscriber(email="to1a@x.com", full_name="TO1 A")
    sub1 = create_subscription(s1, plan)
    box1 = curate_box(sub1, s1, [product["id"]])
    s2 = create_subscriber(email="to1b@x.com", full_name="TO1 B")
    sub2 = create_subscription(s2, plan)
    box2 = curate_box(sub2, s2, [product["id"]])
    wave = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=1)
    reserve_box_into_wave(sub1, box1, wave, wave["version"])
    w1 = get_wave(wave["id"])
    return {"sub2": sub2, "box2": box2, "wave": wave, "product": product,
            "wave_ver1": w1["version"]}


def test_wave_capacity_full_rejects_extra_allocation(api):
    """PRD §3.8: "Separately, the wave must have room: if `reserved_count` has
    already reached `capacity`, the reservation is rejected with
    `ERR_WAVE_CAPACITY_FULL`."

    Capacity 1, one reservation held; a second collides on capacity.

    Design: Difficulty/resource_temporal_overlap/wave_aggregate_capacity_full_rejects_extra_allocation
    """
    ctx = _setup_capacity_one_wave_with_one_reservation()
    res = api.create_allocation(
        create_allocation_payload(ctx["sub2"]["id"], ctx["wave"]["id"], ctx["box2"]["id"],
                                  ctx["wave_ver1"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_WAVE_CAPACITY_FULL.value, expected_status=422)


def test_wave_capacity_full_does_not_change_reserved_count(api):
    """PRD §3.8: "if `reserved_count` has already reached `capacity`, the
    reservation is rejected with `ERR_WAVE_CAPACITY_FULL`."
    PRD §2.5: "`allocated_qty` is the reserved pool, the number of units currently
    held by `RESERVED` allocations."

    The rejected reservation leaves reserved_count at 1 and the second box's product
    unreserved.

    Design: Difficulty/resource_temporal_overlap/wave_aggregate_capacity_full_rejects_extra_allocation
    """
    ctx = _setup_capacity_one_wave_with_one_reservation()
    api.create_allocation(
        create_allocation_payload(ctx["sub2"]["id"], ctx["wave"]["id"], ctx["box2"]["id"],
                                  ctx["wave_ver1"]), ADMIN)
    assert get_wave(ctx["wave"]["id"])["reserved_count"] == 1
    assert get_product(ctx["product"]["id"])["allocated_qty"] == 1


# ─── resource_temporal_overlap: box point-exclusivity (queue A, >=2 tests) ──

def _setup_box_finalized_into_first_wave():
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="TO2", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="TO2P", name="TO2 P", on_hand_qty=9)
    subscriber = create_subscriber(email="to2@x.com", full_name="TO2 S")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [product["id"]])
    wave1 = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    alloc1 = reserve_box_into_wave(sub, box, wave1, wave1["version"])
    wave2 = create_wave("2026-06-18T00:00:00Z", "2026-06-20T00:00:00Z", capacity=10)
    return {"sub": sub, "box": box, "wave2": wave2, "alloc1": alloc1}


def test_box_already_finalized_rejects_second_allocation(api):
    """PRD §3.8: "the referenced box must not already be finalized into a
    non-released allocation — a box period slot may hold at most one non-released
    allocation, so a double reservation of the same box period is rejected with
    `ERR_BOX_ALREADY_FINALIZED`."

    Design: Difficulty/resource_temporal_overlap/box_period_point_exclusivity_rejects_double_allocation
    """
    ctx = _setup_box_finalized_into_first_wave()
    res = api.create_allocation(
        create_allocation_payload(ctx["sub"]["id"], ctx["wave2"]["id"], ctx["box"]["id"],
                                  ctx["wave2"]["version"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_BOX_ALREADY_FINALIZED.value, expected_status=422)


def test_box_already_finalized_keeps_first_allocation_binding(api):
    """PRD §3.8: "the box selection's `decision` becomes `FINALIZED` with its
    `allocation_id` set".
    PRD §3.8: "a box period slot may hold at most one non-released allocation".

    The second reservation is rejected; the box stays bound to the first wave's
    allocation and the second wave reserves nothing.

    Design: Difficulty/resource_temporal_overlap/box_period_point_exclusivity_rejects_double_allocation
    """
    ctx = _setup_box_finalized_into_first_wave()
    api.create_allocation(
        create_allocation_payload(ctx["sub"]["id"], ctx["wave2"]["id"], ctx["box"]["id"],
                                  ctx["wave2"]["version"]), ADMIN)
    box = get_box_selection(ctx["box"]["id"])
    assert box["allocation_id"] == ctx["alloc1"]["id"], "box still bound to first allocation"
    assert get_wave(ctx["wave2"]["id"])["reserved_count"] == 0


# ─── OCC corner (cross_cutting_complexity_layers) ───────────────────────────

def test_occ_allocation_happy_path_bumps_wave_version(api):
    """PRD §2.7: "reserving a curated box into a wave requires the request to carry
    `expected_wave_version`, holding the client's last-observed `version` of the
    target `ShippingWave`."
    PRD §3.8: "the wave's `reserved_count` is increased by 1, the box's
    `line_items` are snapshotted as a list of `{ product_id, qty }` (one entry per
    distinct product), the box selection's `decision` becomes `FINALIZED` with its
    `allocation_id` set, and the wave's `version` is incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_allocation_happy_path_correct_wave_version_succeeds
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="OK", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="OKP", name="OK P", on_hand_qty=5)
    subscriber = create_subscriber(email="ok@x.com", full_name="OK S")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [product["id"]])
    wave = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=5)
    res = api.create_allocation(
        create_allocation_payload(sub["id"], wave["id"], box["id"], wave["version"]), ADMIN)
    alloc = validate_success(res, 201)
    assert alloc["status"] == "RESERVED"
    after = get_wave(wave["id"])
    assert after["reserved_count"] == 1
    assert after["version"] == wave["version"] + 1


def test_occ_allocation_stale_wave_version_rejected(api):
    """PRD §2.7: "If a prior writer has attached an allocation to that wave since
    the client last read it — legitimately consuming a capacity slot and advancing
    the wave's `version` — then the client's view of remaining capacity is stale,
    and the reservation is rejected with `ERR_STALE_WAVE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_allocation_stale_wave_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="ST", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="STP", name="ST P", on_hand_qty=9)
    s1 = create_subscriber(email="st1@x.com", full_name="ST One")
    sub1 = create_subscription(s1, plan)
    box1 = curate_box(sub1, s1, [product["id"]])
    s2 = create_subscriber(email="st2@x.com", full_name="ST Two")
    sub2 = create_subscription(s2, plan)
    box2 = curate_box(sub2, s2, [product["id"]])
    wave = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=5)
    stale_version = wave["version"]
    reserve_box_into_wave(sub1, box1, wave, stale_version)  # advances wave.version
    res = api.create_allocation(
        create_allocation_payload(sub2["id"], wave["id"], box2["id"], stale_version), ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_WAVE_VERSION.value, expected_status=412)
    assert get_wave(wave["id"])["reserved_count"] == 1, "second allocation not applied"


def test_occ_prepay_stale_subscription_version_rejected(api):
    """PRD §2.7: "purchasing a prepaid term requires the request to carry
    `expected_subscription_version`, holding the client's last-observed `version` of
    the target `Subscription`."
    PRD §2.7: "If another writer has advanced the subscription's `version` since the
    client last read it — for instance by moving it into `PREPAID` or `PAST_DUE` —
    the prepay is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_prepay_stale_subscription_version_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="SP", period_price_cents=6000,
                       prepaid_terms_offered=[6], prepaid_discount_pct=0.10)
    subscriber = create_subscriber(email="sp@x.com", full_name="SP S")
    sub = create_subscription(subscriber, plan)
    headers = make_subscriber_headers(subscriber["id"])
    stale_version = sub["version"]
    # A pause/resume cycle advances the subscription's version beyond stale_version.
    validate_success(api.pause_subscription(sub["id"], pause_payload("2026-08-01T00:00:00Z"), headers), 200)
    validate_success(api.resume_subscription(sub["id"], headers), 200)
    res = api.prepay_subscription(sub["id"], prepay_payload(6, stale_version), headers)
    validate_error(res, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value, expected_status=412)
    assert get_subscription(sub["id"])["billing_status"] == "CURRENT", "prepay not applied"
