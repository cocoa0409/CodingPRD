"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Chef calls are entity-backed by Customer (PRD §2.1), so
every order-side helper takes the customer dict and builds per-instance Chef
headers from its real id via make_chef_headers(). Grower and OpsManager are
opaque and use the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CUTOFF_WEDNESDAY, TEST_DEFAULTS, WEEK_START_MONDAY
from .factories import (
    add_delivery_stop_payload,
    add_order_line_payload,
    confirm_standing_order_payload,
    create_crop_plan_payload,
    create_customer_payload,
    create_delivery_route_payload,
    create_food_safety_plan_payload,
    create_germination_test_payload,
    create_sanitation_log_payload,
    create_seed_lot_payload,
    create_standing_order_payload,
    create_variety_payload,
    create_variety_trial_payload,
    sow_crop_plan_payload,
)
from .test_users import TEST_USERS, make_chef_headers

GROWER = TEST_USERS["grower_headers"]
OPS = TEST_USERS["ops_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: variety catalog (create -> trial -> panel -> decide)
# ---------------------------------------------------------------------------

def create_variety(**overrides):
    """Create a variety (born TRIAL, not yet orderable). Returns the variety."""
    return get_success_data(api_client.create_variety(create_variety_payload(**overrides),
                                                      GROWER))


def open_trial(variety_id, yield_score=7.0, sow_date=WEEK_START_MONDAY,
               chef_panel_size=1):
    """Open a variety trial (decision PENDING). Returns the trial."""
    payload = create_variety_trial_payload(
        variety_id, sow_date=sow_date, chef_panel_size=chef_panel_size,
        yield_score=yield_score)
    return get_success_data(api_client.create_variety_trial(payload, GROWER))


def record_panel(trial_id, scores):
    """Record chef panel scores; variety moves TRIAL -> EVALUATION."""
    return get_success_data(api_client.record_panel(trial_id, scores, GROWER))


def decide_trial(trial_id, outcome):
    return get_success_data(api_client.decide_trial(trial_id, outcome, GROWER))


def create_listed_variety(yield_score=7.0, panel_scores=(7.0,), **variety_overrides):
    """Variety walked through trial + panel + ADOPT decision. Returns the
    LISTED variety."""
    variety = create_variety(**variety_overrides)
    trial = open_trial(variety["id"], yield_score=yield_score,
                       chef_panel_size=len(panel_scores))
    record_panel(trial["id"], panel_scores)
    decide_trial(trial["id"], "ADOPT")
    return get_success_data(api_client.get_variety(variety["id"], GROWER))


# ---------------------------------------------------------------------------
# Tier 1: food-safety plan
# ---------------------------------------------------------------------------

def create_food_safety_plan(water_test_current=True, **overrides):
    """Create a food-safety plan (born DRAFT)."""
    payload = create_food_safety_plan_payload(water_test_current=water_test_current,
                                              **overrides)
    return get_success_data(api_client.create_food_safety_plan(payload, OPS))


def approve_food_safety_plan(plan_id):
    return get_success_data(api_client.approve_food_safety_plan(plan_id, OPS))


def suspend_food_safety_plan(plan_id):
    return get_success_data(api_client.suspend_food_safety_plan(plan_id, OPS))


def create_approved_food_safety_plan(**overrides):
    plan = create_food_safety_plan(**overrides)
    return approve_food_safety_plan(plan["id"])


# ---------------------------------------------------------------------------
# Tier 1/2: seed lots and germination clearance
# ---------------------------------------------------------------------------

def create_seed_lot(variety_id, seeds_on_hand_grams=TEST_DEFAULTS["SEEDS_ON_HAND_GRAMS"],
                    **overrides):
    """Receive a seed lot (born QUARANTINE)."""
    payload = create_seed_lot_payload(
        variety_id, seeds_on_hand_grams=seeds_on_hand_grams, **overrides)
    return get_success_data(api_client.create_seed_lot(payload, GROWER))


def start_germination_test(seed_lot_id, seeds_sown_count=100):
    payload = create_germination_test_payload(seed_lot_id,
                                              seeds_sown_count=seeds_sown_count)
    return get_success_data(api_client.create_germination_test(payload, GROWER))


def record_germination(seed_lot_id, seeds_sown_count, germinated_count):
    """Start a test on the lot and record the result. Returns the recorded
    GerminationTest."""
    test = start_germination_test(seed_lot_id, seeds_sown_count=seeds_sown_count)
    return get_success_data(
        api_client.record_germination_result(test["id"], germinated_count, GROWER))


def get_seed_lot(seed_lot_id):
    return get_success_data(api_client.get_seed_lot(seed_lot_id, GROWER))


def create_released_seed_lot(variety_id,
                             seeds_on_hand_grams=TEST_DEFAULTS["SEEDS_ON_HAND_GRAMS"],
                             seeds_sown_count=100, germinated_count=95, **overrides):
    """Seed lot cleared by a passing germination test (QUARANTINE -> RELEASED)."""
    lot = create_seed_lot(variety_id, seeds_on_hand_grams=seeds_on_hand_grams,
                          **overrides)
    record_germination(lot["id"], seeds_sown_count, germinated_count)
    return get_seed_lot(lot["id"])


# ---------------------------------------------------------------------------
# Tier 2/3: crop plans, sowing, tray batches, harvest
# ---------------------------------------------------------------------------

def create_crop_plan(variety_id,
                     planned_tray_count=TEST_DEFAULTS["PLANNED_TRAY_COUNT"],
                     seed_grams_required=TEST_DEFAULTS["SEED_GRAMS_REQUIRED"],
                     planned_sow_date=WEEK_START_MONDAY):
    payload = create_crop_plan_payload(
        variety_id, planned_sow_date=planned_sow_date,
        planned_tray_count=planned_tray_count, seed_grams_required=seed_grams_required)
    return get_success_data(api_client.create_crop_plan(payload, GROWER))


def sow_crop_plan(plan_id, plan_version, seed_lot_id):
    """Sow a PLANNED plan from a RELEASED lot. Returns the updated plan."""
    payload = sow_crop_plan_payload(seed_lot_id, plan_version)
    return get_success_data(api_client.sow_crop_plan(plan_id, payload, GROWER))


def get_crop_plan(plan_id):
    return get_success_data(api_client.get_crop_plan(plan_id, GROWER))


def get_plan_batch(crop_plan_id):
    """The single tray batch created by sowing the plan."""
    batches = get_success_data(
        api_client.list_tray_batches(GROWER, params={"crop_plan_id": crop_plan_id}))
    assert len(batches) >= 1, f"Setup failed: no tray batch for plan {crop_plan_id}"
    return batches[0]


def get_tray_batch(batch_id):
    return get_success_data(api_client.get_tray_batch(batch_id, GROWER))


def advance_batch_to(batch_id, target="READY"):
    """Advance SOWN -> GERMINATING -> GROWING -> READY. Returns the batch."""
    chain = ["GERMINATING", "GROWING", "READY"]
    batch = get_tray_batch(batch_id)
    for state in chain[: chain.index(target) + 1]:
        batch = get_success_data(api_client.advance_tray_batch(batch_id, GROWER))
        assert batch["status"] == state, (
            f"Setup failed: advance expected {state}, got {batch['status']}")
    return batch


def log_sanitation(batch_id, surface_swab_passed=True, wash_water_ppm=100,
                   logged_by="op-1"):
    payload = create_sanitation_log_payload(
        batch_id, surface_swab_passed=surface_swab_passed,
        wash_water_ppm=wash_water_ppm, logged_by=logged_by)
    return get_success_data(api_client.create_sanitation_log(payload, GROWER))


def harvest_batch(batch_id, harvested_kg):
    return get_success_data(api_client.harvest_tray_batch(batch_id, harvested_kg, GROWER))


def setup_sown_batch(variety=None, seeds_on_hand_grams=TEST_DEFAULTS["SEEDS_ON_HAND_GRAMS"],
                     planned_tray_count=TEST_DEFAULTS["PLANNED_TRAY_COUNT"],
                     seed_grams_required=TEST_DEFAULTS["SEED_GRAMS_REQUIRED"],
                     **variety_overrides):
    """APPROVED food-safety plan + LISTED variety + RELEASED lot + sown plan.
    Returns a workspace dict."""
    fsp = create_approved_food_safety_plan()
    if variety is None:
        variety = create_listed_variety(**variety_overrides)
    lot = create_released_seed_lot(variety["id"],
                                   seeds_on_hand_grams=seeds_on_hand_grams)
    plan = create_crop_plan(variety["id"], planned_tray_count=planned_tray_count,
                            seed_grams_required=seed_grams_required)
    plan = sow_crop_plan(plan["id"], plan["version"], lot["id"])
    batch = get_plan_batch(plan["id"])
    return {"food_safety_plan": fsp, "variety": variety, "seed_lot": lot,
            "crop_plan": plan, "tray_batch": batch}


def setup_ready_batch(**kwargs):
    """setup_sown_batch plus advances to READY. Returns the workspace."""
    ws = setup_sown_batch(**kwargs)
    ws["tray_batch"] = advance_batch_to(ws["tray_batch"]["id"], "READY")
    return ws


def setup_harvested_batch(harvested_kg, **kwargs):
    """READY batch + passing sanitation log + harvest. Returns the workspace."""
    ws = setup_ready_batch(**kwargs)
    log_sanitation(ws["tray_batch"]["id"])
    ws["tray_batch"] = harvest_batch(ws["tray_batch"]["id"], harvested_kg)
    ws["crop_plan"] = get_crop_plan(ws["crop_plan"]["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 2: customers and standing orders (Chef is entity-backed by Customer)
# ---------------------------------------------------------------------------

def create_customer(**overrides):
    return get_success_data(api_client.create_customer(
        create_customer_payload(**overrides), OPS))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, OPS))


def create_standing_order(customer, effective_week_start=WEEK_START_MONDAY,
                          change_cutoff_day=CUTOFF_WEDNESDAY):
    payload = create_standing_order_payload(
        customer["id"], effective_week_start=effective_week_start,
        change_cutoff_day=change_cutoff_day)
    return get_success_data(api_client.create_standing_order(
        payload, make_chef_headers(customer["id"])))


def get_standing_order(order_id, customer):
    return get_success_data(api_client.get_standing_order(
        order_id, make_chef_headers(customer["id"])))


def add_order_line(order_id, customer, variety_id, qty_kg,
                   unit_price_cents_per_kg=None):
    """Add a weekly-change line, threading the order's current version (OCC).
    Returns the created OrderItem."""
    order = get_standing_order(order_id, customer)
    payload = add_order_line_payload(
        variety_id, qty_kg, order["version"],
        unit_price_cents_per_kg=unit_price_cents_per_kg)
    return get_success_data(api_client.add_order_line(
        order_id, payload, make_chef_headers(customer["id"])))


def confirm_standing_order(order_id, customer):
    """Confirm a DRAFT order, threading the current version. Returns the order."""
    order = get_standing_order(order_id, customer)
    payload = confirm_standing_order_payload(order["version"])
    return get_success_data(api_client.confirm_standing_order(
        order_id, payload, make_chef_headers(customer["id"])))


def setup_confirmed_order(variety=None, customer=None, qty_kg=1.0,
                          unit_price_cents_per_kg=None,
                          effective_week_start=WEEK_START_MONDAY,
                          change_cutoff_day=CUTOFF_WEDNESDAY,
                          **variety_overrides):
    """LISTED variety + customer + CONFIRMED standing order with one line.
    Returns a workspace dict."""
    if variety is None:
        variety = create_listed_variety(**variety_overrides)
    if customer is None:
        customer = create_customer()
    order = create_standing_order(
        customer, effective_week_start=effective_week_start,
        change_cutoff_day=change_cutoff_day)
    item = add_order_line(order["id"], customer, variety["id"], qty_kg,
                          unit_price_cents_per_kg=unit_price_cents_per_kg)
    order = confirm_standing_order(order["id"], customer)
    return {"variety": variety, "customer": customer, "standing_order": order,
            "order_item": item}


# ---------------------------------------------------------------------------
# Tier 3: delivery routes, stops, dispatch, deliver
# ---------------------------------------------------------------------------

def create_delivery_route(min_stop_subtotal_cents=TEST_DEFAULTS["MIN_STOP_SUBTOTAL_CENTS"],
                          service_date=TEST_DEFAULTS["ROUTE_SERVICE_DATE"],
                          route_code=None):
    payload = create_delivery_route_payload(
        route_code=route_code, service_date=service_date,
        min_stop_subtotal_cents=min_stop_subtotal_cents)
    return get_success_data(api_client.create_delivery_route(payload, OPS))


def add_delivery_stop(route_id, customer_id, standing_order_id):
    payload = add_delivery_stop_payload(customer_id, standing_order_id)
    return get_success_data(api_client.add_delivery_stop(route_id, payload, OPS))


def get_delivery_stop(stop_id):
    return get_success_data(api_client.get_delivery_stop(stop_id, OPS))


def dispatch_route(route_id):
    return get_success_data(api_client.dispatch_route(route_id, OPS))


def deliver_stop(stop_id):
    return get_success_data(api_client.deliver_stop(stop_id, OPS))


def setup_route_with_stop(order_workspace,
                          min_stop_subtotal_cents=TEST_DEFAULTS["MIN_STOP_SUBTOTAL_CENTS"]):
    """PLANNED route with one SCHEDULED stop for the workspace's order."""
    route = create_delivery_route(min_stop_subtotal_cents=min_stop_subtotal_cents)
    stop = add_delivery_stop(route["id"], order_workspace["customer"]["id"],
                             order_workspace["standing_order"]["id"])
    return route, stop


def setup_delivered_stop(qty_kg=2.4, variety=None,
                         min_stop_subtotal_cents=TEST_DEFAULTS["MIN_STOP_SUBTOTAL_CENTS"],
                         **variety_overrides):
    """CONFIRMED order -> route -> stop -> dispatch -> deliver.
    Returns the order workspace plus route and stop."""
    ws = setup_confirmed_order(variety=variety, qty_kg=qty_kg, **variety_overrides)
    route, stop = setup_route_with_stop(
        ws, min_stop_subtotal_cents=min_stop_subtotal_cents)
    ws["route"] = dispatch_route(route["id"])
    ws["stop"] = deliver_stop(stop["id"])
    ws["order_item"] = get_success_data(
        api_client.get_order_item(ws["order_item"]["id"], OPS))
    return ws
