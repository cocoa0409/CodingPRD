"""Fixed validation-priority ordering and temporal/interval overlap rules.

Translates queue A (Difficulty) priority_pair_validation_conflict and resource_temporal_overlap
instances. Each priority test arranges TWO simultaneously-violated rules and asserts the PRD's
fixed ordering (§2.9) selects the lower-priority-number error.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_plan, create_zone, create_recipe, create_recipes,
    register_member, create_subscription, create_box, add_recipes_to_box,
    add_recipe_payload,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: priority_pair_validation_conflict / cutoff_temporal_beats_allergen_safety ──

def test_cutoff_temporal_beats_allergen_on_add_recipe(api):
    """PRD §2.9: "sixth, the temporal cutoff checks (`ERR_CUTOFF_PASSED` for selection-side writes, `ERR_CUTOFF_NOT_REACHED` for charging); then, the business-rule checks that follow — allergen safety, diet compatibility, box capacity and duplicates, delivery-date overlap, pause-window overlap, referential serviceability and plan activity, and referral integrity"
    PRD §2.7: "attempting any of them at or after the cutoff is rejected with `ERR_CUTOFF_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/cutoff_temporal_beats_allergen_safety
    """
    # Box OPEN, clock advanced past cutoff, adding a PEANUT recipe to a PEANUT-blocked sub.
    # Both ERR_CUTOFF_PASSED (priority 6) and ERR_ALLERGEN_BLOCKED (priority 7) apply; cutoff wins.
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone(zone_code="ZONE_B", cold_pack_surcharge_cents=499, cutoff_weekday=5)
    peanut = create_recipe(title="PeanutDish", contains_allergens=["PEANUT"])
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, blocked_allergens=["PEANUT"])
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")  # cutoff 2026-07-10T23:59:59Z
    set_clock("2026-07-11T00:00:00.000Z")  # now past cutoff
    res = api.add_recipe_to_box(box["id"], add_recipe_payload(peanut["id"]),
                                make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_CUTOFF_PASSED.value, expected_status=409)


def test_cutoff_temporal_beats_allergen_in_zone_c(api):
    """PRD §2.9: "sixth, the temporal cutoff checks (`ERR_CUTOFF_PASSED` for selection-side writes, `ERR_CUTOFF_NOT_REACHED` for charging); then, the business-rule checks that follow — allergen safety, diet compatibility, box capacity and duplicates, delivery-date overlap, pause-window overlap, referential serviceability and plan activity, and referral integrity"
    PRD §2.7: "attempting any of them at or after the cutoff is rejected with `ERR_CUTOFF_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/cutoff_temporal_beats_allergen_safety
    """
    # Same dual violation (past cutoff + blocked allergen) in a different zone/plan config,
    # confirming the temporal cutoff check (priority 6) consistently beats allergen safety
    # (priority 7): the request is rejected with ERR_CUTOFF_PASSED, not ERR_ALLERGEN_BLOCKED.
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=4, meals_per_week=2)
    zone = create_zone(zone_code="ZONE_C", cold_pack_surcharge_cents=999, cutoff_weekday=5)
    dairy = create_recipe(title="DairyDish", contains_allergens=["DAIRY"])
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, blocked_allergens=["DAIRY"])
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")  # cutoff 2026-07-10T23:59:59Z
    set_clock("2026-07-12T00:00:00.000Z")  # past cutoff
    res = api.add_recipe_to_box(box["id"], add_recipe_payload(dairy["id"]),
                                make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_CUTOFF_PASSED.value, expected_status=409)


def test_subscription_state_beats_cutoff_temporal_on_lock(api):
    """PRD §2.9: "fourth, the target resource's state being correct for the operation (the state-conflict family such as `ERR_SELECTION_NOT_OPEN`, `ERR_BOX_NOT_LOCKED`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, and so on)"
    PRD §2.9: "sixth, the temporal cutoff checks (`ERR_CUTOFF_PASSED` for selection-side writes, `ERR_CUTOFF_NOT_REACHED` for charging)"

    Design: Difficulty/priority_pair_validation_conflict/subscription_state_beats_cutoff_temporal_on_lock
    """
    # Box fully selected, delivery outside the pause window so it stays OPEN. Subscription PAUSED
    # AND clock past the box's cutoff at lock time -> both ERR_SUBSCRIPTION_NOT_ACTIVE (state,
    # priority 4) and ERR_CUTOFF_PASSED (temporal, priority 6); the state error wins.
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone(zone_code="ZONE_B", cold_pack_surcharge_cents=499, cutoff_weekday=5)
    recipes = create_recipes(2, prefix="PB")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    hdr = make_member_headers(member["id"])
    box = create_box(member, sub, "2026-09-15T00:00:00.000Z")  # cutoff 2026-09-11T23:59:59Z
    add_recipes_to_box(member, box, recipes)
    # pause to 2026-09-01, before the box delivery -> box not in window, stays OPEN
    validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-09-01T00:00:00.000Z"}, hdr), 200)
    set_clock("2026-09-12T00:00:00.000Z")  # past the box cutoff, still PAUSED
    res = api.lock_selection(box["id"], hdr)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, expected_status=409)


def test_subscription_state_beats_cutoff_temporal_on_lock_zone_c(api):
    """PRD §2.9: "fourth, the target resource's state being correct for the operation (the state-conflict family such as `ERR_SELECTION_NOT_OPEN`, `ERR_BOX_NOT_LOCKED`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, and so on)"
    PRD §3.5: "the owning subscription's `status` is `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`)"

    Design: Difficulty/priority_pair_validation_conflict/subscription_state_beats_cutoff_temporal_on_lock
    """
    # Same dual violation (PAUSED owning subscription AND clock past the box cutoff) in a
    # different zone/plan config, confirming the state check (priority 4) consistently beats the
    # temporal cutoff check (priority 6): the lock is rejected with ERR_SUBSCRIPTION_NOT_ACTIVE,
    # not ERR_CUTOFF_PASSED.
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=4, meals_per_week=2)
    zone = create_zone(zone_code="ZONE_C", cold_pack_surcharge_cents=999, cutoff_weekday=5)
    recipes = create_recipes(2, prefix="ZC")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    hdr = make_member_headers(member["id"])
    box = create_box(member, sub, "2026-09-22T00:00:00.000Z")  # cutoff 2026-09-18T23:59:59Z
    add_recipes_to_box(member, box, recipes)
    # pause to 2026-09-10, before the box delivery -> box stays OPEN (not skipped by cascade)
    validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-09-10T00:00:00.000Z"}, hdr), 200)
    set_clock("2026-09-19T00:00:00.000Z")  # past the box cutoff, still PAUSED
    res = api.lock_selection(box["id"], hdr)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, expected_status=409)


# ─── Difficulty: resource_temporal_overlap / delivery_date_point_collision ──

def test_delivery_date_point_collision_rejected(api):
    """PRD §3.4: "At most one non-`SKIPPED` box may occupy a given `delivery_date` for a subscription — a closed-point collision on the delivery date — and a second non-`SKIPPED` box on the same date is rejected with `ERR_DELIVERY_DATE_TAKEN`."

    Design: Difficulty/resource_temporal_overlap/delivery_date_point_collision_on_subscription
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    hdr = make_member_headers(member["id"])
    create_box(member, sub, "2026-07-15T00:00:00.000Z")
    from test_helpers import create_weekly_box_payload
    res = api.create_weekly_box(
        create_weekly_box_payload(sub["id"], "2026-07-15T00:00:00.000Z"), hdr)
    validate_error(res, ApiErrorId.ERR_DELIVERY_DATE_TAKEN.value, expected_status=409)


def test_first_box_on_delivery_date_succeeds(api):
    """PRD §3.4: "A member creates a **WeeklyBox** against one of their subscriptions by naming the `subscription_id` and a `delivery_date`."
    PRD §3.4: "The `delivery_date` must be strictly after the subscription's current clock date."

    Design: Difficulty/resource_temporal_overlap/delivery_date_point_collision_on_subscription
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    from test_helpers import create_weekly_box_payload
    res = api.create_weekly_box(
        create_weekly_box_payload(sub["id"], "2026-07-15T00:00:00.000Z"),
        make_member_headers(member["id"]))
    box = validate_success(res, 201)
    assert box["delivery_date"] == "2026-07-15T00:00:00.000Z"


# ─── Difficulty: resource_temporal_overlap / pause_window_overlap_half_open_adjacency ──

def test_pause_window_adjacency_at_prior_resume_allowed(api):
    """PRD §3.3: "windows are treated as half-open intervals, so adjacency — where one window's `resume_date` equals the next window's start — is allowed, but a true overlap is rejected with `ERR_PAUSE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pause_window_overlap_half_open_adjacency_allowed
    """
    set_clock("2026-07-05T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    hdr = make_member_headers(member["id"])
    # first pause window [2026-07-05, 2026-07-20)
    validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-07-20T00:00:00.000Z"}, hdr), 200)
    set_clock("2026-07-21T00:00:00.000Z")
    validate_success(api.resume_subscription(sub["id"], hdr), 200)
    # new pause [2026-07-21, 2026-08-01) starts after the prior resume boundary -> allowed
    paused = validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-01T00:00:00.000Z"}, hdr), 200)
    assert paused["status"] == "PAUSED"


def test_pause_window_adjacency_sets_scheduled_resume_date(api):
    """PRD §3.3: "When the pause succeeds, the subscription moves to `PAUSED`; `scheduled_resume_date` is set to the supplied `resume_date"
    PRD §3.3: "windows are treated as half-open intervals, so adjacency — where one window's `resume_date` equals the next window's start — is allowed, but a true overlap is rejected with `ERR_PAUSE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pause_window_overlap_half_open_adjacency_allowed
    """
    set_clock("2026-07-05T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    hdr = make_member_headers(member["id"])
    # first pause window [2026-07-05, 2026-07-20)
    validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-07-20T00:00:00.000Z"}, hdr), 200)
    set_clock("2026-07-21T00:00:00.000Z")
    validate_success(api.resume_subscription(sub["id"], hdr), 200)
    # adjacent second pause [2026-07-21, 2026-08-01) starting after the prior resume boundary
    paused = validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-01T00:00:00.000Z"}, hdr), 200)
    assert paused["status"] == "PAUSED"
    assert paused["scheduled_resume_date"] == "2026-08-01T00:00:00.000Z"
