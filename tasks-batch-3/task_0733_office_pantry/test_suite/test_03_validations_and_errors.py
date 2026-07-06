"""Validation errors — refrigeration, capacity, dietary, headcount, empty assortment,
already-active, and priority-pair conflicts."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_client_admin_headers, make_location_manager_headers,
    TEST_USERS,
    set_clock, create_plan, create_client, create_location, create_product,
    create_par_level, create_preference, create_subscription, activate_subscription,
    get_first_rotation_cycle, create_delivery,
    setup_active_subscription, close_and_get_invoice, pay_invoice,
)


# ─────────────────────────────────────────────────────────────
# Difficulty rule 5 — priority_pair_validation_conflict
# ─────────────────────────────────────────────────────────────

def test_state_beats_referential_second_pay_returns_invalid_state(api):
    """PRD §2.11 (priority 12): "The target entity is not in a state from which the requested
    transition is valid, or a rotation cycle referenced by a delivery-generator call is not
    OPEN — ERR_INVALID_STATE (409)."
    PRD §2.11: "Because the ordering is strict, a mid-flight authorization failure always
    surfaces above a state error, a state error above a business-safety check, and a
    business-safety check above the OCC verdict."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_second_subscription
    """
    state = setup_active_subscription(
        plan_overrides={"tier": "S-INV", "billing_type": "FLAT", "flat_fee_cents": 3000,
                        "volume_discount_threshold_headcount": 50},
        client_overrides={"name": "TwoSubs", "headcount": 5},
    )
    state = close_and_get_invoice(state, close_clock="2026-07-05T00:00:00Z")
    inv = state["invoice"]
    # First pay succeeds.
    pay_invoice(inv["id"], state["client"]["id"])
    # Second pay attempt: payment_status is already PAID (state axis violated).
    res = api.pay_invoice(inv["id"], make_client_admin_headers(state["client"]["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_state_beats_referential_priority_ordering_on_pay(api):
    """PRD §2.11: "state error above a business-safety check, and a business-safety check
    above the OCC verdict."
    PRD §2.11 (priority 12): "The target entity is not in a state from which the requested
    transition is valid ... ERR_INVALID_STATE (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_second_subscription
    """
    # Alternative scenario: cancel a subscription then try to cancel again — the state error
    # (already-CANCELLED, priority 12) must fire even though the referential-invariant
    # "one non-terminal sub per client" (priority 20) also is not satisfiable at this state.
    state = setup_active_subscription()
    state_client_id = state["client"]["id"]
    # Cancel first — succeeds.
    api.cancel_subscription(state["subscription"]["id"], make_client_admin_headers(state_client_id))
    # Cancel again from CANCELLED — priority 12 fires.
    res = api.cancel_subscription(state["subscription"]["id"], make_client_admin_headers(state_client_id))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_dietary_safety_beats_capacity_constraint_on_par_level(api):
    """PRD §2.11 (priority 15): "A par-level or a feedback swap-suggestion whose product's
    dietary_flags overlap the client's Preference list — ERR_DIETARY_PREFERENCE_VIOLATION (422)."
    PRD §2.11: "Because the ordering is strict ... a business-safety check above the OCC verdict."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_par_level_dietary_and_capacity
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(name="AllergyCo", headcount=5)
    create_preference(client["id"], "CONTAINS_NUTS")
    loc = create_location(client["id"], name="Full", kind="PANTRY", capacity_units=5)
    filler = create_product(sku="FILL-A", name="Filler", category="SNACK", unit_cost_cents=100)
    # Fill up the location to capacity.
    create_par_level(loc["id"], filler["id"], 5)
    peanut = create_product(
        sku="PEANUTS-A", name="Peanuts", category="SNACK",
        dietary_flags=["CONTAINS_NUTS"], unit_cost_cents=100,
    )
    # Try to add par-level for peanut product — both dietary (safety, priority 15) AND capacity
    # (constraint, priority 17) would fire. Safety must win.
    res = api.create_par_level(
        loc["id"],
        {"product_id": peanut["id"], "par_units": 3},
        make_location_manager_headers(loc["id"]),
    )
    validate_error(res, "ERR_DIETARY_PREFERENCE_VIOLATION", expected_status=422)


def test_dietary_safety_beats_capacity_even_with_smaller_par(api):
    """PRD §2.11: "a business-safety check above the OCC verdict."
    PRD §2.11 (priority 15): "A par-level or a feedback swap-suggestion whose product's
    dietary_flags overlap the client's Preference list — ERR_DIETARY_PREFERENCE_VIOLATION (422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_par_level_dietary_and_capacity
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(name="AllergyCo-2", headcount=5)
    create_preference(client["id"], "CONTAINS_NUTS")
    loc = create_location(client["id"], name="Full-2", kind="PANTRY", capacity_units=5)
    filler = create_product(sku="FILL-B", name="Filler2", category="SNACK", unit_cost_cents=100)
    create_par_level(loc["id"], filler["id"], 4)  # 4 used, 1 remaining.
    # Try to add a peanut par of 2 (would exceed capacity by 1). Priority 15 (dietary safety) must
    # still fire before priority 17 (capacity).
    peanut = create_product(
        sku="PEANUTS-B", name="Peanuts2", category="SNACK",
        dietary_flags=["CONTAINS_NUTS"], unit_cost_cents=100,
    )
    res = api.create_par_level(
        loc["id"],
        {"product_id": peanut["id"], "par_units": 2},
        make_location_manager_headers(loc["id"]),
    )
    validate_error(res, "ERR_DIETARY_PREFERENCE_VIOLATION", expected_status=422)


# ─────────────────────────────────────────────────────────────
# Corner/validations
# ─────────────────────────────────────────────────────────────

def test_par_level_refrigeration_mismatch_at_pantry(api):
    """PRD §2.9: "A Product with requires_refrigeration set to true may be placed only in
    Locations whose kind is FRIDGE or MICRO_MARKET. Attempts to set a ParLevel for a
    refrigerated product at a PANTRY are rejected with ERR_REFRIGERATION_MISMATCH (HTTP 422)."

    Design: Corner/validations/create_par_level_refrigeration_mismatch_at_pantry
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(name="Frig", headcount=5)
    loc = create_location(client["id"], name="PL", kind="PANTRY", capacity_units=10)
    prod = create_product(
        sku="COLD-A", name="Milk", category="BEVERAGE",
        unit_cost_cents=200, requires_refrigeration=True,
    )
    res = api.create_par_level(
        loc["id"],
        {"product_id": prod["id"], "par_units": 1},
        make_location_manager_headers(loc["id"]),
    )
    validate_error(res, "ERR_REFRIGERATION_MISMATCH", expected_status=422)


def test_location_capacity_exceeded_on_par_level(api):
    """PRD §2.10: "Each Location declares its capacity_units, and the sum of par_units over
    all ParLevel rows attached to that location must never exceed the declared capacity.
    A par-level creation that would push the running sum above capacity_units is rejected
    with ERR_LOCATION_CAPACITY_EXCEEDED (HTTP 422)."

    Design: Corner/validations/location_capacity_exceeded_on_par_level
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(name="Cap", headcount=5)
    loc = create_location(client["id"], name="L", kind="PANTRY", capacity_units=5)
    prod = create_product(sku="P-CAP-A", name="P", category="SNACK", unit_cost_cents=100)
    res = api.create_par_level(
        loc["id"],
        {"product_id": prod["id"], "par_units": 6},
        make_location_manager_headers(loc["id"]),
    )
    validate_error(res, "ERR_LOCATION_CAPACITY_EXCEEDED", expected_status=422)


def test_dietary_preference_violation_on_swap_suggestion(api):
    """PRD §3.8: "A suggestion that points at a product the client's preference blocks is
    rejected with ERR_DIETARY_PREFERENCE_VIOLATION."

    Design: Corner/validations/dietary_preference_violation_on_swap_suggestion
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(name="GF", headcount=5)
    create_preference(client["id"], "CONTAINS_GLUTEN")
    ok = create_product(sku="OK-1-A", name="OK", category="SNACK", unit_cost_cents=100)
    glu = create_product(
        sku="GLU-A", name="Gluten", category="SNACK",
        dietary_flags=["CONTAINS_GLUTEN"], unit_cost_cents=100,
    )
    res = api.create_feedback(
        client["id"],
        {"product_id": ok["id"], "rating": 2, "swap_suggestion_product_id": glu["id"]},
        make_client_admin_headers(client["id"]),
    )
    validate_error(res, "ERR_DIETARY_PREFERENCE_VIOLATION", expected_status=422)


def test_invalid_headcount_zero_rejected(api):
    """PRD §3.1: "headcount must be at least 1; any create or later patch that would drop
    it below 1 is rejected with ERR_INVALID_HEADCOUNT."

    Design: Corner/validations/invalid_headcount_zero_rejected
    """
    client = create_client(name="Zero", headcount=10)
    res = api.patch_client_headcount(
        client["id"], {"headcount": 0}, TEST_USERS["platform_admin_headers"]
    )
    validate_error(res, "ERR_INVALID_HEADCOUNT", expected_status=422)


def test_empty_assortment_after_preference_filter(api):
    """PRD §3.4: "If the surviving set is empty after filtering, the request is rejected
    with ERR_EMPTY_ASSORTMENT."

    Design: Corner/validations/empty_assortment_after_preference_filter
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="EA-A", billing_type="FLAT", flat_fee_cents=1000,
                      volume_discount_threshold_headcount=10)
    client = create_client(name="EmptyCo", headcount=5)
    loc = create_location(client["id"], name="L", kind="PANTRY", capacity_units=5)
    # Nutty product goes into par-level BEFORE the preference is set (dietary check on par-level
    # would otherwise block it). After preference set, the delivery generator's filter must catch it.
    prod = create_product(
        sku="NUT-1-A", name="N", category="SNACK",
        dietary_flags=["CONTAINS_NUTS"], unit_cost_cents=100,
    )
    create_par_level(loc["id"], prod["id"], 1)
    create_preference(client["id"], "CONTAINS_NUTS")
    sub = create_subscription(client["id"], plan["id"], client["version"])
    activate_subscription(sub["id"])
    rc = get_first_rotation_cycle(sub["id"])

    res = api.create_delivery(
        rc["id"],
        {"location_id": loc["id"], "scheduled_at": "2026-06-02T00:00:00Z"},
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(res, "ERR_EMPTY_ASSORTMENT", expected_status=422)


def test_subscription_already_active_on_second_create(api):
    """PRD §3.3: "if the client already has a subscription in DRAFT, ACTIVE, or PAUSED,
    the create is rejected with ERR_SUBSCRIPTION_ALREADY_ACTIVE."

    Design: Corner/validations/subscription_already_active_on_second_create
    """
    state = setup_active_subscription(
        plan_overrides={"tier": "SA-1", "billing_type": "FLAT", "flat_fee_cents": 1000,
                        "volume_discount_threshold_headcount": 10},
    )
    # Re-read client to get current version (create+activate advanced it).
    got = validate_success(api.get_client(state["client"]["id"], TEST_USERS["platform_admin_headers"]))
    current_v = got["version"]
    res = api.create_subscription(
        state["client"]["id"],
        {"plan_id": state["plan"]["id"], "expected_client_version": current_v},
        make_client_admin_headers(state["client"]["id"]),
    )
    validate_error(res, "ERR_SUBSCRIPTION_ALREADY_ACTIVE", expected_status=409)
