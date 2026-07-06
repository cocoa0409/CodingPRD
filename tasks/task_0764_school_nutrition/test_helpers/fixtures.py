"""Composite setup helpers.

Every test runs against a freshly booted, empty server, so each helper builds all
of its preconditions from scratch using only PRD-declared endpoints. Helpers use
get_success_data() (lenient) internally so setup problems surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_site_payload,
    create_food_item_payload,
    create_reimbursement_rate_payload,
    create_menu_cycle_payload,
    create_inventory_lot_payload,
    create_production_record_payload,
    create_student_payload,
    create_meal_transaction_payload,
    create_reimbursement_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_planner_headers,
    make_director_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["menu_planner_headers"]
DIRECTOR = TEST_USERS["nutrition_director_headers"]
CAFETERIA = TEST_USERS["cafeteria_manager_headers"]
CLERK = TEST_USERS["pos_clerk_headers"]

# Default set of components a compliant lunch cycle offers and a reimbursable
# lunch selects (three distinct components including a fruit).
REIMBURSABLE_LUNCH_COMPONENTS = ["MEAT_MEAT_ALT", "GRAINS", "FRUIT"]


# --------------------------------------------------------------------------
# Config primitives
# --------------------------------------------------------------------------
_site_code_counter = itertools.count(1)


def create_site(api, **overrides) -> dict:
    # site_code must be unique across all sites (PRD §3.1); generate a distinct
    # default per call so tests that create more than one site do not collide.
    overrides.setdefault("site_code", f"TST-{next(_site_code_counter)}")
    return get_success_data(api.create_site(create_site_payload(**overrides), ADMIN))


def create_food_items(api, whole_grain_rich: bool = True) -> dict:
    """Create the four food items that back a compliant lunch cycle.

    entree contributes 2.0 meat oz-eq, grain 1.0 grain oz-eq (whole-grain-rich by
    default), fruit 0.75 cup, and a milk item. Returns their ids keyed by role.
    """
    ent = get_success_data(api.create_food_item(
        create_food_item_payload(name="Chicken Patty", category="ENTREE", meat_alt_oz_eq=2.0), ADMIN))
    grn = get_success_data(api.create_food_item(
        create_food_item_payload(name="WG Roll", category="GRAIN", grain_oz_eq=1.0,
                                 is_whole_grain_rich=whole_grain_rich), ADMIN))
    fru = get_success_data(api.create_food_item(
        create_food_item_payload(name="Apple", category="FRUIT", fruit_cup=0.75), ADMIN))
    milk = get_success_data(api.create_food_item(
        create_food_item_payload(name="Milk", category="MILK"), ADMIN))
    return {"ent": ent["id"], "grn": grn["id"], "fru": fru["id"], "milk": milk["id"]}


def lunch_components(food_ids: dict, planned_servings=1, serving_amount=1) -> list:
    return [
        {"food_item_id": food_ids["ent"], "component": "MEAT_MEAT_ALT",
         "planned_servings": planned_servings, "serving_amount": serving_amount},
        {"food_item_id": food_ids["grn"], "component": "GRAINS",
         "planned_servings": planned_servings, "serving_amount": serving_amount},
        {"food_item_id": food_ids["fru"], "component": "FRUIT",
         "planned_servings": planned_servings, "serving_amount": serving_amount},
        {"food_item_id": food_ids["milk"], "component": "MILK",
         "planned_servings": planned_servings, "serving_amount": serving_amount},
    ]


def create_food_item(api, **overrides) -> dict:
    return get_success_data(api.create_food_item(create_food_item_payload(**overrides), ADMIN))


def seed_nslp_rates(api, free=425, reduced=385, paid=55, addon=8, effective_date="2025-07-01"):
    """Seed the three NSLP category rates used for lunch reimbursement."""
    for category, rate in (("FREE", free), ("REDUCED", reduced), ("PAID", paid)):
        get_success_data(api.create_reimbursement_rate(
            create_reimbursement_rate_payload(program="NSLP", category=category,
                                              rate_cents=rate, performance_addon_cents=addon,
                                              effective_date=effective_date), ADMIN))


def receive_inventory(api, site_id, food_ids: dict, qty=1000, received_date="2026-03-10"):
    """Receive one PURCHASED lot per food item at the given quantity."""
    for key in ("ent", "grn", "fru", "milk"):
        get_success_data(api.create_inventory_lot(
            create_inventory_lot_payload(site_id, food_ids[key], quantity_received=qty,
                                         received_date=received_date), CAFETERIA))


def receive_lot(api, site_id, food_item_id, **overrides) -> dict:
    return get_success_data(api.create_inventory_lot(
        create_inventory_lot_payload(site_id, food_item_id, **overrides), CAFETERIA))


# --------------------------------------------------------------------------
# Tier 1: menu-cycle state progression
# --------------------------------------------------------------------------
def create_draft_lunch_menu(api, site_id, food_ids=None, **overrides) -> dict:
    """Create a DRAFT compliant lunch cycle. Returns the created cycle object."""
    if food_ids is None:
        food_ids = create_food_items(api)
    payload = create_menu_cycle_payload(site_id, lunch_components(food_ids), **overrides)
    return get_success_data(api.create_menu_cycle(payload, PLANNER))


def submit_menu(api, cycle_id, submitter_user_id="planner_1"):
    return get_success_data(
        api.submit_menu_cycle(cycle_id, make_planner_headers(submitter_user_id)))


def approve_menu(api, cycle_id, approver_user_id="dir_1"):
    return get_success_data(
        api.approve_menu_cycle(cycle_id, make_director_headers(approver_user_id)))


def create_approved_lunch_menu(api, site_id, food_ids=None,
                               submitter_user_id="planner_1", approver_user_id="dir_1",
                               **overrides) -> str:
    """Create -> submit -> approve a compliant lunch cycle. Returns its id."""
    cycle = create_draft_lunch_menu(api, site_id, food_ids, **overrides)
    submit_menu(api, cycle["id"], submitter_user_id)
    approve_menu(api, cycle["id"], approver_user_id)
    return cycle["id"]


# --------------------------------------------------------------------------
# Tier 3: production lifecycle
# --------------------------------------------------------------------------
def create_planned_production(api, site_id, menu_cycle_id, **overrides) -> dict:
    payload = create_production_record_payload(site_id, menu_cycle_id, **overrides)
    return get_success_data(api.create_production_record(payload, CAFETERIA))


def create_prepared_production(api, site_id, menu_cycle_id, planned_qty=100,
                               prepared_qty=100, **overrides) -> dict:
    """Create a PLANNED record then prepare it (depleting inventory). Returns the record."""
    record = create_planned_production(api, site_id, menu_cycle_id, planned_qty=planned_qty, **overrides)
    get_success_data(api.prepare_production_record(record["id"], CAFETERIA,
                                                   {"prepared_qty": prepared_qty}))
    return record


# --------------------------------------------------------------------------
# Tier 2: full "prepared lunch site" hierarchy (the most common preamble)
# --------------------------------------------------------------------------
def setup_prepared_lunch_site(api, site_overrides=None, whole_grain_rich=True,
                              service_date="2026-04-15", planned_qty=100,
                              prepared_qty=100, inventory_qty=1000) -> dict:
    """Active district config through to a PREPARED lunch production record.

    Builds: site -> four food items -> full inventory -> APPROVED+COMPLIANT lunch
    cycle -> PREPARED production record. Returns a dict of the key ids/objects.
    """
    site = create_site(api, **(site_overrides or {}))
    food_ids = create_food_items(api, whole_grain_rich=whole_grain_rich)
    receive_inventory(api, site["id"], food_ids, qty=inventory_qty)
    mc_id = create_approved_lunch_menu(api, site["id"], food_ids)
    pr = create_prepared_production(api, site["id"], mc_id, planned_qty=planned_qty,
                                    prepared_qty=prepared_qty, service_date=service_date)
    return {
        "site": site,
        "site_id": site["id"],
        "food_ids": food_ids,
        "mc_id": mc_id,
        "pr": pr,
        "pr_id": pr["id"],
        "service_date": service_date,
    }


# --------------------------------------------------------------------------
# Students & the prepay account
# --------------------------------------------------------------------------
def create_student(api, site_id, **overrides) -> dict:
    return get_success_data(api.create_student(create_student_payload(site_id, **overrides), ADMIN))


def deposit(api, student_id, amount_cents) -> dict:
    return get_success_data(api.deposit_student(student_id, CLERK, {"amount_cents": amount_cents}))


def create_funded_student(api, site_id, eligibility_category="PAID", deposit_cents=5000, **overrides) -> dict:
    """Create a student and (optionally) deposit funds. Returns the latest student object."""
    student = create_student(api, site_id, eligibility_category=eligibility_category, **overrides)
    if deposit_cents:
        return deposit(api, student["id"], deposit_cents)
    return student


# --------------------------------------------------------------------------
# Point-of-service meals
# --------------------------------------------------------------------------
def record_meal(api, site_id, student_id, production_record_id,
                selected_components=None, service_date="2026-04-15",
                a_la_carte_lines=None, **overrides) -> dict:
    if selected_components is None:
        selected_components = list(REIMBURSABLE_LUNCH_COMPONENTS)
    payload = create_meal_transaction_payload(
        site_id, student_id, production_record_id,
        service_date=service_date, selected_components=selected_components, **overrides)
    if a_la_carte_lines is not None:
        payload["a_la_carte_lines"] = a_la_carte_lines
    return get_success_data(api.create_meal_transaction(payload, CLERK))


def record_reimbursable_lunch(api, scenario, student_id, service_date=None) -> dict:
    """Record one reimbursable lunch against a setup_prepared_lunch_site scenario."""
    return record_meal(
        api, scenario["site_id"], student_id, scenario["pr_id"],
        selected_components=list(REIMBURSABLE_LUNCH_COMPONENTS),
        service_date=service_date or scenario["service_date"])


# --------------------------------------------------------------------------
# Reimbursement claims
# --------------------------------------------------------------------------
def create_claim(api, site_id, claim_month="2026-04", creator_user_id="dir_create") -> dict:
    return get_success_data(api.create_reimbursement_claim(
        create_reimbursement_claim_payload(site_id, claim_month=claim_month),
        make_director_headers(creator_user_id)))


def submit_claim(api, claim_id, expected_version, submitter_user_id="dir_submit") -> dict:
    return get_success_data(api.submit_claim(
        claim_id, make_director_headers(submitter_user_id),
        {"expected_claim_version": expected_version}))


def mark_paid(api, claim_id) -> dict:
    return get_success_data(api.mark_paid_claim(claim_id, ADMIN))


def setup_three_category_claim(api, service_date="2026-04-15", claim_month="2026-04",
                               performance_certified=True) -> dict:
    """Performance-certified site + NSLP rates + one FREE, one REDUCED, one PAID
    reimbursable lunch in the month + a DRAFT claim created after all three meals.

    Returns dict with site_id, claim (object), and the three meal-transaction ids.
    """
    seed_nslp_rates(api)  # rates must exist before the site so anything can compute
    scenario = setup_prepared_lunch_site(
        api,
        site_overrides={"performance_based_certified": performance_certified,
                        "negative_balance_allowed": True},
        service_date=service_date)
    site_id, pr_id = scenario["site_id"], scenario["pr_id"]
    meal_ids = {}
    for cat in ("FREE", "REDUCED", "PAID"):
        stu = create_student(api, site_id, eligibility_category=cat)
        mt = record_meal(api, site_id, stu["id"], pr_id,
                         selected_components=list(REIMBURSABLE_LUNCH_COMPONENTS),
                         service_date=service_date)
        meal_ids[cat] = mt["id"]
    claim = create_claim(api, site_id, claim_month=claim_month)
    scenario.update({"claim": claim, "claim_id": claim["id"],
                     "claim_version": claim["version"], "meal_ids": meal_ids})
    return scenario
