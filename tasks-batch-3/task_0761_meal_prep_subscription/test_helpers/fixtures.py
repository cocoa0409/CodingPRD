"""Composite setup helpers for the meal-prep subscription API.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the server (empty DB) before every test. Setup calls use
get_success_data() (lenient) so a broken precondition surfaces as a clear "Setup failed".

Identity threading: the Customer role is entity_backed:Customer, so every ownership-gated call
uses make_customer_headers(<customer id>) with the real Customer.id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import make_customer_headers, make_admin_headers, make_anonymous_headers
from . import factories as f
from .constants import CLOCK_START_UTC, CUTOFF_AT, DELIVERY_DATE

ADMIN = make_admin_headers()
ANON = make_anonymous_headers()


def _d(resp):
    return get_success_data(resp)


# ----------------------------------------------------------------------------
# Primitives
# ----------------------------------------------------------------------------
def set_clock(api, to_iso8601=CLOCK_START_UTC):
    return _d(api.set_clock(f.set_clock_payload(to_iso8601), ADMIN))


def seed_zone(api, **overrides):
    return _d(api.create_shipping_zone(f.create_shipping_zone_payload(**overrides), ADMIN))


def seed_plan(api, **overrides):
    return _d(api.create_plan(f.create_plan_payload(**overrides), ADMIN))


def seed_starter_plan(api, **overrides):
    base = {"plan_code": "STARTER", "name": "Starter", "meals_per_week": 6, "price_per_meal_cents": 1299}
    base.update(overrides)
    return _d(api.create_plan(f.create_plan_payload(**base), ADMIN))


def seed_meal(api, **overrides):
    return _d(api.create_meal(f.create_meal_payload(**overrides), ADMIN))


def seed_customer(api, zone_id, **overrides):
    return _d(api.create_customer(f.create_customer_payload(zone_id, **overrides), ANON))


def seed_subscription(api, customer_id, plan_id):
    return _d(api.create_subscription(
        f.create_subscription_payload(customer_id, plan_id), make_customer_headers(customer_id)))


def seed_run(api, meal_id, open_run=False, **overrides):
    run = _d(api.create_production_run(f.create_production_run_payload(meal_id, **overrides), ADMIN))
    if open_run:
        run = _d(api.open_production_run(run["id"], ADMIN))
    return run


def seed_box(api, subscription_id, customer_id, delivery_date=DELIVERY_DATE):
    return _d(api.create_box(
        subscription_id, f.create_box_payload(delivery_date), make_customer_headers(customer_id)))


def seed_item(api, box_id, customer_id, meal_id, quantity=1):
    return _d(api.create_box_item(
        box_id, f.create_box_item_payload(meal_id, quantity), make_customer_headers(customer_id)))


def seed_credit(api, customer_id, amount_cents):
    return _d(api.create_credit(customer_id, f.create_credit_payload(amount_cents, "SWAP_CREDIT"), ADMIN))


# ----------------------------------------------------------------------------
# Base scenario: WEST zone + PRO plan + one meal + ACTIVE customer/subscription
# ----------------------------------------------------------------------------
def setup_base(api, allergen_exclusions=None, meal_allergens=None):
    """Clock at startup default; WEST zone, PRO plan, meal M1, ACTIVE customer + subscription.
    Returns a context dict of ids."""
    set_clock(api)
    zone = seed_zone(api)
    plan = seed_plan(api)
    meal_kwargs = {}
    if meal_allergens is not None:
        meal_kwargs["allergens"] = meal_allergens
    meal = seed_meal(api, **meal_kwargs)
    cust_kwargs = {}
    if allergen_exclusions is not None:
        cust_kwargs["allergen_exclusions"] = allergen_exclusions
    cust = seed_customer(api, zone["id"], **cust_kwargs)
    sub = seed_subscription(api, cust["id"], plan["id"])
    return {
        "zone_id": zone["id"], "plan_id": plan["id"], "m1_id": meal["id"],
        "cust_id": cust["id"], "sub_id": sub["id"], "sub_version": sub["version"],
    }


# ----------------------------------------------------------------------------
# Box lifecycle composites
# ----------------------------------------------------------------------------
def setup_pro_box_ready_to_lock(api, quantity=12, wallet_cents=0, par_total=100):
    """PRO customer with an OPEN box holding one SELECTED line of `quantity`, clock advanced to
    exactly the box cutoff (2026-03-12T18:00:00Z) so the box is lockable. Optionally seeds wallet.
    Returns {cust_id, sub_id, box_id, run_id, m1_id}."""
    ctx = setup_base(api)
    if wallet_cents:
        seed_credit(api, ctx["cust_id"], wallet_cents)
    run = seed_run(api, ctx["m1_id"], open_run=True, par_total=par_total)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    seed_item(api, box["id"], ctx["cust_id"], ctx["m1_id"], quantity)
    set_clock(api, CUTOFF_AT)
    ctx.update({"box_id": box["id"], "run_id": run["id"]})
    return ctx


def setup_pro_box_locked(api, quantity=12, wallet_cents=0, charge=None):
    """As setup_pro_box_ready_to_lock, then lock the box (billing PENDING). If `charge` is
    "SUCCEEDED" or "DECLINED", also simulate that payment outcome.
    Returns {cust_id, sub_id, box_id, run_id, m1_id}."""
    ctx = setup_pro_box_ready_to_lock(api, quantity=quantity, wallet_cents=wallet_cents)
    _d(api.lock_box(ctx["box_id"], ADMIN))
    if charge is not None:
        _d(api.simulate_payment(f.simulate_payment_payload(ctx["box_id"], charge), ADMIN))
    return ctx


def setup_two_boxes_for_refund(api):
    """One PRO customer, two 12-meal boxes both charged to total 13688c. box_a stays LOCKED
    (pre-ship); box_b is additionally SHIPPED (post-ship). Returns
    {cust_id, sub_id, box_a_id, box_b_id}."""
    ctx = setup_base(api)
    run_a = seed_run(api, ctx["m1_id"], open_run=True, delivery_date="2026-03-16", line_code="L1")
    run_b = seed_run(api, ctx["m1_id"], open_run=True, delivery_date="2026-03-23", line_code="L2",
                     window_start="2026-03-21T06:00:00Z", window_end="2026-03-21T10:00:00Z")
    box_a = seed_box(api, ctx["sub_id"], ctx["cust_id"], "2026-03-16")
    seed_item(api, box_a["id"], ctx["cust_id"], ctx["m1_id"], 12)
    box_b = seed_box(api, ctx["sub_id"], ctx["cust_id"], "2026-03-23")
    seed_item(api, box_b["id"], ctx["cust_id"], ctx["m1_id"], 12)
    # Advance to box_b's cutoff (2026-03-19T18:00Z); both boxes are then at/after their cutoff.
    set_clock(api, "2026-03-19T18:00:00Z")
    _d(api.lock_box(box_a["id"], ADMIN))
    _d(api.simulate_payment(f.simulate_payment_payload(box_a["id"], "SUCCEEDED"), ADMIN))
    _d(api.lock_box(box_b["id"], ADMIN))
    _d(api.simulate_payment(f.simulate_payment_payload(box_b["id"], "SUCCEEDED"), ADMIN))
    _d(api.ship_box(box_b["id"], ADMIN))
    ctx.update({"box_a_id": box_a["id"], "box_b_id": box_b["id"]})
    return ctx


def setup_referee_box_ready_two_lines(api):
    """Referee (referred_by set) on PRO with a first box holding two SELECTED lines of qty 3
    (meals M1, M2). Clock at cutoff so the box is lockable. Returns {cust_id, box_id}."""
    set_clock(api)
    zone = seed_zone(api)
    plan = seed_plan(api)
    m1 = seed_meal(api, meal_code="M1", name="Meal 1")
    m2 = seed_meal(api, meal_code="M2", name="Meal 2", protein_g=35, carb_g=40, fat_g=12, calories=450)
    referrer = seed_customer(api, zone["id"], email="r@x.com", full_name="Ref R")
    referee = seed_customer(api, zone["id"], email="e@x.com", full_name="Referee E",
                            referred_by_code=referrer["referral_code"])
    sub = seed_subscription(api, referee["id"], plan["id"])
    seed_run(api, m1["id"], open_run=True, line_code="L1")
    seed_run(api, m2["id"], open_run=True, line_code="L2")
    box = seed_box(api, sub["id"], referee["id"])
    seed_item(api, box["id"], referee["id"], m1["id"], 3)
    seed_item(api, box["id"], referee["id"], m2["id"], 3)
    set_clock(api, CUTOFF_AT)
    return {"cust_id": referee["id"], "box_id": box["id"], "referrer_id": referrer["id"]}


# ----------------------------------------------------------------------------
# Referral composites
# ----------------------------------------------------------------------------
def setup_two_referees_charged(api):
    """Referrer R; two referees signed up with R's code: P on PRO (12 meals/wk), S on STARTER
    (6 meals/wk). Each has a first box locked and charged (not yet shipped).
    Returns {r_id, p_id, s_id, box_p_id, box_s_id}."""
    set_clock(api)
    zone = seed_zone(api)
    pro = seed_plan(api)
    starter = seed_starter_plan(api)
    m1 = seed_meal(api, meal_code="M1", name="Meal 1")
    referrer = seed_customer(api, zone["id"], email="r@x.com", full_name="Ref R")
    p = seed_customer(api, zone["id"], email="p@x.com", full_name="Referee P",
                      referred_by_code=referrer["referral_code"])
    s = seed_customer(api, zone["id"], email="s@x.com", full_name="Referee S",
                      referred_by_code=referrer["referral_code"])
    sub_p = seed_subscription(api, p["id"], pro["id"])
    sub_s = seed_subscription(api, s["id"], starter["id"])
    seed_run(api, m1["id"], open_run=True, par_total=100)
    box_p = seed_box(api, sub_p["id"], p["id"])
    seed_item(api, box_p["id"], p["id"], m1["id"], 12)
    box_s = seed_box(api, sub_s["id"], s["id"])
    seed_item(api, box_s["id"], s["id"], m1["id"], 6)
    set_clock(api, CUTOFF_AT)
    _d(api.lock_box(box_p["id"], ADMIN))
    _d(api.simulate_payment(f.simulate_payment_payload(box_p["id"], "SUCCEEDED"), ADMIN))
    _d(api.lock_box(box_s["id"], ADMIN))
    _d(api.simulate_payment(f.simulate_payment_payload(box_s["id"], "SUCCEEDED"), ADMIN))
    return {"r_id": referrer["id"], "p_id": p["id"], "s_id": s["id"],
            "box_p_id": box_p["id"], "box_s_id": box_s["id"]}


def setup_referee_box_charged(api):
    """Referrer R; referee E (PRO) signed up with R's code; E's first box locked and charged
    (not shipped). Returns {r_id, e_id, box_id}."""
    set_clock(api)
    zone = seed_zone(api)
    pro = seed_plan(api)
    m1 = seed_meal(api, meal_code="M1", name="Meal 1")
    referrer = seed_customer(api, zone["id"], email="r@x.com", full_name="Ref R")
    e = seed_customer(api, zone["id"], email="e@x.com", full_name="Referee E",
                      referred_by_code=referrer["referral_code"])
    sub = seed_subscription(api, e["id"], pro["id"])
    seed_run(api, m1["id"], open_run=True, par_total=100)
    box = seed_box(api, sub["id"], e["id"])
    seed_item(api, box["id"], e["id"], m1["id"], 12)
    set_clock(api, CUTOFF_AT)
    _d(api.lock_box(box["id"], ADMIN))
    _d(api.simulate_payment(f.simulate_payment_payload(box["id"], "SUCCEEDED"), ADMIN))
    return {"r_id": referrer["id"], "e_id": e["id"], "box_id": box["id"]}


# ----------------------------------------------------------------------------
# Production-run / par composites
# ----------------------------------------------------------------------------
def setup_run5_box_selected5(api):
    """Run par_total 5 opened for 2026-03-16; one OPEN box that selected quantity 5 (run now
    SOLD_OUT, par_remaining 0). Returns {cust_id, sub_id, box_id, run_id, item_id, m1_id}."""
    ctx = setup_base(api)
    run = seed_run(api, ctx["m1_id"], open_run=True, par_total=5)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    item = seed_item(api, box["id"], ctx["cust_id"], ctx["m1_id"], 5)
    ctx.update({"box_id": box["id"], "run_id": run["id"], "item_id": item["id"]})
    return ctx


def setup_run5_box_open(api):
    """Run par_total 5 opened for 2026-03-16; one OPEN box with NO items yet.
    Returns {cust_id, sub_id, box_id, run_id, m1_id}."""
    ctx = setup_base(api)
    run = seed_run(api, ctx["m1_id"], open_run=True, par_total=5)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    ctx.update({"box_id": box["id"], "run_id": run["id"]})
    return ctx


def setup_scheduled_run_box(api):
    """A run for (M1, 2026-03-16) created but NOT opened (status SCHEDULED); one OPEN box before
    cutoff. Returns {cust_id, sub_id, box_id, run_id, m1_id}."""
    ctx = setup_base(api)
    run = seed_run(api, ctx["m1_id"], open_run=False, par_total=100)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    ctx.update({"box_id": box["id"], "run_id": run["id"]})
    return ctx


def setup_two_runs_box_item3(api):
    """Two opened runs for 2026-03-16: run1 (M1, par 10) and run2 (M2, par 10); one OPEN box
    that selected M1 quantity 3 (run1 reserved 3). Returns
    {cust_id, box_id, run1_id, run2_id, m1_id, m2_id, item_id}."""
    set_clock(api)
    zone = seed_zone(api)
    plan = seed_plan(api)
    m1 = seed_meal(api, meal_code="M1", name="Meal 1")
    m2 = seed_meal(api, meal_code="M2", name="Meal 2", protein_g=35, carb_g=40, fat_g=12, calories=450)
    cust = seed_customer(api, zone["id"])
    sub = seed_subscription(api, cust["id"], plan["id"])
    run1 = seed_run(api, m1["id"], open_run=True, line_code="L1", par_total=10)
    run2 = seed_run(api, m2["id"], open_run=True, line_code="L2", par_total=10)
    box = seed_box(api, sub["id"], cust["id"])
    item = seed_item(api, box["id"], cust["id"], m1["id"], 3)
    return {"cust_id": cust["id"], "box_id": box["id"], "run1_id": run1["id"],
            "run2_id": run2["id"], "m1_id": m1["id"], "m2_id": m2["id"], "item_id": item["id"]}


def setup_run_on_line_l1(api):
    """One run on line L1, window [2026-03-14T06:00:00Z, 2026-03-14T10:00:00Z]. Returns
    {m1_id, run_a_id}."""
    set_clock(api)
    m1 = seed_meal(api, meal_code="M1", name="Meal 1")
    run_a = seed_run(api, m1["id"], line_code="L1",
                     window_start="2026-03-14T06:00:00Z", window_end="2026-03-14T10:00:00Z")
    return {"m1_id": m1["id"], "run_a_id": run_a["id"]}


# ----------------------------------------------------------------------------
# Validation / state composites
# ----------------------------------------------------------------------------
def setup_open_box_no_run(api, clock_iso=None):
    """PRO customer with one OPEN box for 2026-03-16 (no items, no run). If clock_iso is given,
    advance the clock to it. Returns {cust_id, sub_id, box_id}."""
    ctx = setup_base(api)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    if clock_iso is not None:
        set_clock(api, clock_iso)
    ctx["box_id"] = box["id"]
    return ctx


def setup_skipped_box(api, advance_past_cutoff=True):
    """PRO customer with one box for 2026-03-16 skipped (fulfillment SKIPPED) while the clock was
    before cutoff. If advance_past_cutoff, the clock is then advanced to 2026-03-13T00:00:00Z
    (strictly after cutoff). Returns {cust_id, sub_id, box_id}."""
    ctx = setup_base(api)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    _d(api.skip_box(box["id"], make_customer_headers(ctx["cust_id"])))
    if advance_past_cutoff:
        set_clock(api, "2026-03-13T00:00:00Z")
    ctx["box_id"] = box["id"]
    return ctx


def setup_allergen_box(api, par_total=0):
    """Customer excludes PEANUT; meal MP contains PEANUT with its only run for 2026-03-16 opened
    (AVAILABLE) with `par_total` servings; one OPEN box. With the default par_total=0 the run is
    also sold out (both the allergen and the sold-out constraint would fire on a select). With
    par_total>0 only the allergen check can fail. Returns {cust_id, box_id, mp_id}."""
    set_clock(api)
    zone = seed_zone(api)
    plan = seed_plan(api)
    mp = seed_meal(api, meal_code="MP", name="Peanut Noodles", protein_g=20, carb_g=60,
                   fat_g=25, calories=700, allergens=["PEANUT"])
    cust = seed_customer(api, zone["id"], allergen_exclusions=["PEANUT"])
    sub = seed_subscription(api, cust["id"], plan["id"])
    seed_run(api, mp["id"], open_run=True, par_total=par_total)
    box = seed_box(api, sub["id"], cust["id"])
    return {"cust_id": cust["id"], "box_id": box["id"], "mp_id": mp["id"]}


def setup_cancelled_subscription(api):
    """A subscription that has been cancelled (status CANCELLED). Returns {cust_id, sub_id}."""
    ctx = setup_base(api)
    _d(api.cancel_subscription(ctx["sub_id"], make_customer_headers(ctx["cust_id"])))
    return {"cust_id": ctx["cust_id"], "sub_id": ctx["sub_id"]}


def setup_subscription_with_pause(api):
    """A subscription with one SCHEDULED pause window [2026-03-16, 2026-03-30).
    Returns {cust_id, sub_id}."""
    ctx = setup_base(api)
    _d(api.create_pause_window(
        ctx["sub_id"], f.create_pause_window_payload("2026-03-16", "2026-03-30"),
        make_customer_headers(ctx["cust_id"])))
    return {"cust_id": ctx["cust_id"], "sub_id": ctx["sub_id"]}


def setup_subscription_two_plans(api):
    """A subscription on PRO (version 1) plus a STARTER plan. Returns
    {cust_id, sub_id, sub_version, pro_plan_id, starter_plan_id}."""
    set_clock(api)
    zone = seed_zone(api)
    pro = seed_plan(api)
    starter = seed_starter_plan(api)
    cust = seed_customer(api, zone["id"])
    sub = seed_subscription(api, cust["id"], pro["id"])
    return {"cust_id": cust["id"], "sub_id": sub["id"], "sub_version": sub["version"],
            "pro_plan_id": pro["id"], "starter_plan_id": starter["id"]}


def setup_open_run_box_selected3(api):
    """PRO customer with an OPEN box selecting M1 quantity 3 on an opened run (par 100).
    Returns {cust_id, sub_id, box_id, run_id, item_id, m1_id}."""
    ctx = setup_base(api)
    run = seed_run(api, ctx["m1_id"], open_run=True, par_total=100)
    box = seed_box(api, ctx["sub_id"], ctx["cust_id"])
    item = seed_item(api, box["id"], ctx["cust_id"], ctx["m1_id"], 3)
    ctx.update({"box_id": box["id"], "run_id": run["id"], "item_id": item["id"]})
    return ctx
