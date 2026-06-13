"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for all setup calls so a setup
failure surfaces as a clear "setup failed" error rather than a confusing
assertion failure deep inside a test.

Identity threading: MemberOperator is entity-backed, so every member-scoped
write here uses make_member_operator_headers(member_id) with the real member id.

Each test runs against a freshly-restarted, empty database, so every fixture
builds its full precondition chain from scratch using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_member_payload,
    top_up_payload,
    create_station_payload,
    create_storage_unit_payload,
    create_storage_assignment_payload,
    create_ingredient_payload,
    create_ingredient_order_payload,
    create_recipe_payload,
    create_recipe_component_payload,
    create_batch_payload,
    complete_batch_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_operator_headers,
)

FM = TEST_USERS["facility_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Tier 1: Members ────────────────────────────────────────────────────────

def register_member(business_name="Acme Foods", email=None, plan_tier=None):
    """Register a member and return the created Member dict (status ACTIVE)."""
    payload = create_member_payload(business_name=business_name)
    if email is not None:
        payload["email"] = email
    if plan_tier is not None:
        payload["plan_tier"] = plan_tier
    return get_success_data(api_client.register_member(payload, ANON))


def register_funded_member(amount_cents=100000, plan_tier=None, business_name="Funded Co"):
    """Register a member and top up its wallet.

    Returns (member, current_version). The version reflects the wallet top-up,
    which advances Member.version by one (PRD 2.7), so it is suitable as the
    expected_member_version for the next guarded write.
    """
    member = register_member(business_name=business_name, plan_tier=plan_tier)
    mo = make_member_operator_headers(member["id"])
    if amount_cents > 0:
        topped = get_success_data(
            api_client.top_up_wallet(member["id"], top_up_payload(amount_cents), mo)
        )
        return member, topped["version"]
    return member, member["version"]


def current_member_version(member_id):
    """GET the member and return its current version (for chaining guarded writes)."""
    mo = make_member_operator_headers(member_id)
    m = get_success_data(api_client.get_member(member_id, mo))
    return m["version"]


# ─── Tier 2: Stations & bookings ────────────────────────────────────────────

def create_station(name="Prep Table 1", station_class="PREP_TABLE", **overrides):
    payload = create_station_payload(name=name, station_class=station_class, **overrides)
    return get_success_data(api_client.create_station(payload, FM))


def create_booking(member_id, station_id, start_utc, end_utc, expected_version):
    mo = make_member_operator_headers(member_id)
    payload = {
        "station_id": station_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_member_version": expected_version,
    }
    return get_success_data(api_client.create_booking(member_id, payload, mo))


def create_completed_booking(member_id, station_id, start_utc, end_utc, expected_version):
    """Create a booking then complete it. Returns the completed Booking dict."""
    mo = make_member_operator_headers(member_id)
    bk = create_booking(member_id, station_id, start_utc, end_utc, expected_version)
    return get_success_data(api_client.complete_booking(member_id, bk["id"], mo))


# ─── Tier 3: Ingredients & stock ────────────────────────────────────────────

def create_ingredient(name="Almond Flour", unit_cost_cents=100, allergen_tags=None):
    payload = create_ingredient_payload(name=name, unit_cost_cents=unit_cost_cents)
    if allergen_tags is not None:
        payload["allergen_tags"] = allergen_tags
    return get_success_data(api_client.create_ingredient(payload, FM))


def stock_ingredient(member_id, ingredient_id, order_qty, unit_cost_cents):
    """Place and receive an ingredient order. Returns the refreshed Ingredient dict."""
    mo = make_member_operator_headers(member_id)
    order = get_success_data(
        api_client.create_ingredient_order(
            member_id,
            create_ingredient_order_payload(ingredient_id, order_qty, unit_cost_cents),
            mo,
        )
    )
    get_success_data(api_client.receive_ingredient_order(member_id, order["id"], mo))
    return get_success_data(api_client.get_ingredient(ingredient_id, FM))


# ─── Tier 4: Recipes ────────────────────────────────────────────────────────

def create_published_recipe(member_id, batch_yield_units=10, components=None, name="Test Recipe"):
    """Create a DRAFT recipe with the given components and publish it.

    `components` is a list of (ingredient_id, planned_qty) tuples. Defaults to
    a single dummy component if omitted by the caller, which the caller must
    supply via create_ingredient first.
    Returns the published Recipe dict.
    """
    mo = make_member_operator_headers(member_id)
    recipe = get_success_data(
        api_client.create_recipe(member_id, create_recipe_payload(name=name, batch_yield_units=batch_yield_units), mo)
    )
    for ingredient_id, planned_qty in (components or []):
        get_success_data(
            api_client.add_recipe_component(
                member_id, recipe["id"],
                create_recipe_component_payload(ingredient_id, planned_qty), mo,
            )
        )
    return get_success_data(api_client.publish_recipe(member_id, recipe["id"], mo))


def create_draft_recipe_with_component(member_id, ingredient_id, planned_qty=1.0,
                                       batch_yield_units=10, name="Draft Recipe"):
    """Create a DRAFT recipe with one component; do NOT publish. Returns Recipe dict."""
    mo = make_member_operator_headers(member_id)
    recipe = get_success_data(
        api_client.create_recipe(member_id, create_recipe_payload(name=name, batch_yield_units=batch_yield_units), mo)
    )
    get_success_data(
        api_client.add_recipe_component(
            member_id, recipe["id"],
            create_recipe_component_payload(ingredient_id, planned_qty), mo,
        )
    )
    return recipe


# ─── Tier 5: Batches ────────────────────────────────────────────────────────

def create_planned_batch(member_id, recipe_id, planned_yield_units=10):
    mo = make_member_operator_headers(member_id)
    return get_success_data(
        api_client.create_batch(member_id, create_batch_payload(recipe_id, planned_yield_units), mo)
    )


def create_started_batch(member_id, recipe_id, planned_yield_units=10):
    """Plan then start a batch (requires stock already present). Returns IN_PRODUCTION batch."""
    mo = make_member_operator_headers(member_id)
    batch = create_planned_batch(member_id, recipe_id, planned_yield_units)
    return get_success_data(api_client.start_batch(member_id, batch["id"], mo))


def create_completed_batch(member_id, recipe_id, planned_yield_units=10,
                           actual_yield_units=None, actual_components=None):
    """Plan -> start -> complete a batch. Returns the COMPLETED batch dict.

    Requires the member to be funded and the recipe ingredients stocked.
    """
    mo = make_member_operator_headers(member_id)
    batch = create_started_batch(member_id, recipe_id, planned_yield_units)
    ay = actual_yield_units if actual_yield_units is not None else planned_yield_units
    return get_success_data(
        api_client.complete_batch(member_id, batch["id"], complete_batch_payload(ay, actual_components), mo)
    )


def setup_member_with_completed_batch(allergen_tags=None, planned_yield_units=10,
                                      planned_qty=1.0, ingredient_cost=100, order_qty=100):
    """Full chain to a COMPLETED batch owned by a funded member.

    Returns (member, ingredient, recipe, completed_batch).
    Used by packout tests (seal / allergen gate / packed_unit_count).
    """
    member, _ = register_funded_member(amount_cents=100000)
    ingredient = create_ingredient(name="PackIng", unit_cost_cents=ingredient_cost,
                                   allergen_tags=allergen_tags)
    stock_ingredient(member["id"], ingredient["id"], order_qty, ingredient_cost)
    recipe = create_published_recipe(member["id"], batch_yield_units=planned_yield_units,
                                     components=[(ingredient["id"], planned_qty)])
    batch = create_completed_batch(member["id"], recipe["id"], planned_yield_units,
                                   actual_yield_units=planned_yield_units,
                                   actual_components=[{"ingredient_id": ingredient["id"], "actual_qty": float(planned_yield_units * planned_qty)}])
    return member, ingredient, recipe, batch


# ─── Tier 6: Storage units & assignments ────────────────────────────────────

def create_storage_unit(name="Cooler", temp_class="DRY", total_slots=20,
                        temp_min_c=10.0, temp_max_c=25.0):
    payload = create_storage_unit_payload(
        name=name, temp_class=temp_class, total_slots=total_slots,
        temp_min_c=temp_min_c, temp_max_c=temp_max_c,
    )
    return get_success_data(api_client.create_storage_unit(payload, FM))


def create_storage_assignment(member_id, temp_class, requested_slots, expected_version):
    mo = make_member_operator_headers(member_id)
    payload = create_storage_assignment_payload(temp_class, requested_slots, expected_version)
    return get_success_data(api_client.create_storage_assignment(member_id, payload, mo))


def quarantine_unit_via_breach(unit_id, out_of_range_c, base_iso, first_min=0, second_min_offset=121):
    """Drive a storage unit to QUARANTINED by posting two out-of-range readings
    more than 120 minutes apart.

    base_iso is an ISO-8601 string for the first reading at HH:00; the second
    reading is posted second_min_offset minutes later so cumulative excursion
    strictly exceeds 120. Returns the refreshed StorageUnit dict.
    """
    # First out-of-range reading -> EXCURSION (run starts at 0).
    api_client.create_temp_log(unit_id, {"reading_c": out_of_range_c, "reading_utc": base_iso[0]}, CO)
    # Second out-of-range reading > 120 min later -> excursion_minutes > 120 -> QUARANTINED.
    api_client.create_temp_log(unit_id, {"reading_c": out_of_range_c, "reading_utc": base_iso[1]}, CO)
    return get_success_data(api_client.get_storage_unit(unit_id, FM))


# ─── Tier 7: Invoicing ──────────────────────────────────────────────────────

def create_invoice(member_id, period_start_utc, period_end_utc):
    return get_success_data(
        api_client.create_invoice(member_id, {
            "period_start_utc": period_start_utc,
            "period_end_utc": period_end_utc,
        }, FM)
    )
