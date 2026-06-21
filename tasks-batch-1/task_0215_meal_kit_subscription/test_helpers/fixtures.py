"""Composite setup helpers for multi-step Meal Kit Subscription test prerequisites.

Each helper uses get_success_data() (lenient validator) internally, so a broken setup
produces a clear "setup failed" error rather than a confusing downstream assertion failure.

IDENTITY THREADING: members are entity_backed. After a fixture registers a Member, every
ownership-gated call (subscription create, box create, recipe add, lock, skip, etc.) is made
with make_member_headers(member["id"]) — never the shared TEST_USERS["member_headers"].

DATA ISOLATION: the harness restarts the server (empty DB) before every test, so each fixture
builds its full precondition chain from scratch via PRD-declared endpoints only.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_shipping_zone_payload,
    create_recipe_payload,
    create_member_payload,
    create_subscription_payload,
    create_weekly_box_payload,
    add_recipe_payload,
    create_referral_payload,
    pause_payload,
    clock_payload,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]
ANON = TEST_USERS["anonymous_headers"]

# A clock instant used by most setups whose delivery dates fall in mid-July 2026.
DEFAULT_CLOCK = "2026-07-01T00:00:00.000Z"


# ─── Clock ────────────────────────────────────────────────────────────────

def set_clock(now_iso8601: str):
    """Set the logical clock to a specific instant (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(clock_payload(now_iso8601), ADMIN))


# ─── Tier 1: Catalog primitives ─────────────────────────────────────────────

def create_plan(servings_per_meal=2, meals_per_week=3, code=None, is_active=None):
    """Create a catalog Plan. Returns the plan dict."""
    payload = create_plan_payload(servings_per_meal=servings_per_meal,
                                  meals_per_week=meals_per_week)
    if code is not None:
        payload["code"] = code
    else:
        payload["code"] = f"PLAN_{servings_per_meal}x{meals_per_week}_{id(payload) & 0xffff}"
    if is_active is not None:
        payload["is_active"] = is_active
    return get_success_data(api_client.create_plan(payload, ADMIN))


def create_zone(zone_code="ZONE_A", cold_pack_surcharge_cents=0, cutoff_weekday=5,
                serviceable=None):
    """Create a ShippingZone. Returns the zone dict."""
    payload = create_shipping_zone_payload(zone_code=zone_code,
                                           cold_pack_surcharge_cents=cold_pack_surcharge_cents,
                                           cutoff_weekday=cutoff_weekday)
    if serviceable is not None:
        payload["serviceable"] = serviceable
    return get_success_data(api_client.create_shipping_zone(payload, ADMIN))


def create_recipe(title="Recipe", is_premium=None, contains_allergens=None,
                  diet_tags=None, is_available=None):
    """Create a Recipe. Returns the recipe dict."""
    payload = create_recipe_payload(title=title)
    if is_premium is not None:
        payload["is_premium"] = is_premium
    if contains_allergens is not None:
        payload["contains_allergens"] = contains_allergens
    if diet_tags is not None:
        payload["diet_tags"] = diet_tags
    if is_available is not None:
        payload["is_available"] = is_available
    return get_success_data(api_client.create_recipe(payload, ADMIN))


def create_recipes(n, prefix="R", **recipe_kwargs):
    """Create n recipes, returning the list of recipe dicts."""
    return [create_recipe(title=f"{prefix}{i}", **recipe_kwargs) for i in range(n)]


def register_member(zone_id, email=None, full_name="Member", referred_by_member_id=None):
    """Register a Member into a zone. Returns the member dict."""
    payload = create_member_payload(zone_id, full_name=full_name)
    if email is not None:
        payload["email"] = email
    if referred_by_member_id is not None:
        payload["referred_by_member_id"] = referred_by_member_id
    return get_success_data(api_client.create_member(payload, ANON))


def create_subscription(member, plan, billing_cycle_day=1, diet_preference=None,
                        blocked_allergens=None, monthly_addon_fee_cents=None):
    """Create a Subscription owned by member, bound to plan. Returns the subscription dict.

    Uses the member's own identity headers (entity_backed ownership)."""
    payload = create_subscription_payload(member["id"], plan["id"],
                                          billing_cycle_day=billing_cycle_day)
    if diet_preference is not None:
        payload["diet_preference"] = diet_preference
    if blocked_allergens is not None:
        payload["blocked_allergens"] = blocked_allergens
    if monthly_addon_fee_cents is not None:
        payload["monthly_addon_fee_cents"] = monthly_addon_fee_cents
    return get_success_data(
        api_client.create_subscription(payload, make_member_headers(member["id"])))


# ─── Tier 2: Box construction ───────────────────────────────────────────────

def create_box(member, subscription, delivery_date):
    """Create an OPEN/PENDING WeeklyBox on a subscription. Returns the box dict."""
    payload = create_weekly_box_payload(subscription["id"], delivery_date)
    return get_success_data(
        api_client.create_weekly_box(payload, make_member_headers(member["id"])))


def add_recipes_to_box(member, box, recipes):
    """Add each recipe (list of recipe dicts) as a BoxRecipe slot on box.
    Returns the list of created BoxRecipe dicts."""
    headers = make_member_headers(member["id"])
    slots = []
    for r in recipes:
        slots.append(get_success_data(
            api_client.add_recipe_to_box(box["id"], add_recipe_payload(r["id"]), headers)))
    return slots


def lock_box(member, box):
    """Lock a fully-selected OPEN box. Returns the locked box dict."""
    return get_success_data(
        api_client.lock_selection(box["id"], make_member_headers(member["id"])))


def fill_and_lock_box(member, subscription, plan, recipes, delivery_date):
    """Create a box, add exactly meals_per_week recipes, and lock it.
    Returns (box_after_lock, box_recipe_slots)."""
    box = create_box(member, subscription, delivery_date)
    needed = plan["meals_per_week"]
    slots = add_recipes_to_box(member, box, recipes[:needed])
    locked = lock_box(member, box)
    return locked, slots


# ─── Tier 3: Fulfillment lifecycle (Ops) ────────────────────────────────────

def charge_box(box):
    """Charge a LOCKED box at/after cutoff (PlatformOps). Returns the charged box dict."""
    return get_success_data(api_client.charge_box(box["id"], OPS))


def ship_box(box):
    """Ship a CHARGED box (PlatformOps). Returns the shipped box dict."""
    return get_success_data(api_client.ship_box(box["id"], OPS))


def refund_box(box):
    """Refund a CHARGED box (PlatformOps). Returns the refunded box dict."""
    return get_success_data(api_client.refund_box(box["id"], OPS))


# ─── Tier 4: Composite scenarios ────────────────────────────────────────────

def setup_lockable_box(servings_per_meal=4, meals_per_week=2, zone_code="ZONE_A",
                       cold_pack_surcharge_cents=0, cutoff_weekday=5,
                       diet_preference=None, delivery_date="2026-07-15T00:00:00.000Z",
                       clock=DEFAULT_CLOCK):
    """Build a fully-selected OPEN box ready to lock.

    Creates: clock -> plan -> zone -> meals_per_week recipes -> member -> subscription ->
    box -> add all recipe slots. Returns a dict with plan, zone, member, subscription, box,
    recipes, slots. The box is OPEN with meals_per_week slots (not yet locked)."""
    set_clock(clock)
    plan = create_plan(servings_per_meal=servings_per_meal, meals_per_week=meals_per_week)
    zone = create_zone(zone_code=zone_code,
                       cold_pack_surcharge_cents=cold_pack_surcharge_cents,
                       cutoff_weekday=cutoff_weekday)
    recipes = create_recipes(meals_per_week, prefix="LR")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, diet_preference=diet_preference)
    box = create_box(member, sub, delivery_date)
    slots = add_recipes_to_box(member, box, recipes)
    return {
        "plan": plan, "zone": zone, "member": member, "subscription": sub,
        "box": box, "recipes": recipes, "slots": slots,
    }


def setup_locked_box(**kwargs):
    """Same as setup_lockable_box, then lock. Returns the dict with box replaced by the
    locked box (provisional_charge_cents populated)."""
    ctx = setup_lockable_box(**kwargs)
    ctx["box"] = lock_box(ctx["member"], ctx["box"])
    return ctx


def setup_charged_box(advance_clock="2026-07-11T00:00:00.000Z", **kwargs):
    """Build a locked box, advance the clock past cutoff, and charge it.
    Returns the context dict with box replaced by the charged box."""
    ctx = setup_locked_box(**kwargs)
    set_clock(advance_clock)
    ctx["box"] = charge_box(ctx["box"])
    return ctx


def setup_referrer_referee_with_pending_referral(zone_code="ZONE_A",
                                                 cold_pack_surcharge_cents=0,
                                                 cutoff_weekday=5,
                                                 clock=DEFAULT_CLOCK):
    """Register a referrer R and a referee E recruited by R, plus a PENDING Referral.

    Returns dict: plan, zone, referrer, referee, referral, recipes (2). The referee is
    registered as an organic signup (no referred_by), then a single explicit referral is created
    directly by naming both members, so the returned referral id is known and unique."""
    set_clock(clock)
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone(zone_code=zone_code,
                       cold_pack_surcharge_cents=cold_pack_surcharge_cents,
                       cutoff_weekday=cutoff_weekday)
    recipes = create_recipes(2, prefix="RF")
    referrer = register_member(zone["id"], full_name="Referrer")
    referee = register_member(zone["id"], full_name="Referee")
    referral = get_success_data(api_client.create_referral(
        create_referral_payload(referrer["id"], referee["id"]), ADMIN))
    return {
        "plan": plan, "zone": zone, "referrer": referrer, "referee": referee,
        "referral": referral, "recipes": recipes,
    }


def ship_referee_first_box(ctx, delivery_date="2026-07-15T00:00:00.000Z",
                           charge_clock="2026-07-11T00:00:00.000Z"):
    """Given a referrer/referee context, build the referee's first box and ship it
    (lock -> advance clock -> charge -> ship), which settles the referral and credits R.

    Returns the shipped box dict."""
    referee = ctx["referee"]
    plan = ctx["plan"]
    sub = create_subscription(referee, plan)
    box = create_box(referee, sub, delivery_date)
    add_recipes_to_box(referee, box, ctx["recipes"][:plan["meals_per_week"]])
    lock_box(referee, box)
    set_clock(charge_clock)
    charge_box(box)
    return ship_box(box)


def setup_paused_subscription(monthly_addon_fee_cents=0, billing_cycle_day=1,
                              resume_date="2026-08-01T00:00:00.000Z",
                              clock=DEFAULT_CLOCK, diet_preference=None):
    """Create an ACTIVE subscription and pause it. Returns dict: plan, zone, member,
    subscription (the pause response), resume_date."""
    set_clock(clock)
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, billing_cycle_day=billing_cycle_day,
                              monthly_addon_fee_cents=monthly_addon_fee_cents,
                              diet_preference=diet_preference)
    paused = get_success_data(api_client.pause_subscription(
        sub["id"], pause_payload(resume_date), make_member_headers(member["id"])))
    return {"plan": plan, "zone": zone, "member": member,
            "subscription": paused, "resume_date": resume_date}


def setup_active_subscription(monthly_addon_fee_cents=0, billing_cycle_day=1,
                              clock=DEFAULT_CLOCK):
    """Create a plain ACTIVE subscription with member + plan + zone.
    Returns dict: plan, zone, member, subscription."""
    set_clock(clock)
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, billing_cycle_day=billing_cycle_day,
                              monthly_addon_fee_cents=monthly_addon_fee_cents)
    return {"plan": plan, "zone": zone, "member": member, "subscription": sub}
