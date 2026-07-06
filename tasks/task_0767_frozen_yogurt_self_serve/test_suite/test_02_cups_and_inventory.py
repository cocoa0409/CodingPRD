"""Adding cups: toppings, flavors, allergen guard, weight, mix, and void conservation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_topping_payload, add_line_payload,
    make_machine, make_flavor, make_topping, make_ticket, add_line, do_checkout,
    setup_machine_flavor,
)

MANAGER = TEST_USERS["manager_headers"]
SHIFTLEAD = TEST_USERS["shiftlead_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def test_create_topping_defaults_available_with_stock(api):
    """PRD §3.2: "A new topping's `status` is `AVAILABLE`; a `ShiftLead` may
    rotate it to the terminal `ROTATED_OUT`, which requires the topping to
    currently be `AVAILABLE` and otherwise fails with `ERR_TOPPING_INVALID_STATE`."
    PRD §3.2: "an `initial_units` count that seeds the read-only `on_hand_units`"

    Design: Corner/entities/create_topping_defaults_available
    """
    resp = api.create_topping(create_topping_payload(name="Mochi", surcharge_cents=30, initial_units=50), SHIFTLEAD)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "AVAILABLE"
    assert data["on_hand_units"] == 50, f"on_hand_units must seed from initial_units 50, got {data['on_hand_units']}"


def test_rotate_out_already_rotated_flavor_rejected(api):
    """PRD §3.2: "A `ShiftLead` may permanently rotate a flavor off the menu,
    moving it from `LOADED` to the terminal `ROTATED_OUT`; this requires the
    flavor to currently be `LOADED`, and otherwise fails with
    `ERR_FLAVOR_INVALID_STATE`."

    Design: Corner/state_machines/rotate_out_already_rotated_flavor_rejected
    """
    machine = make_machine(api, mix_par_oz=1000)
    flavor = make_flavor(api, machine["id"])
    validate_success(api.rotate_out_flavor(flavor["id"], SHIFTLEAD))
    resp = api.rotate_out_flavor(flavor["id"], SHIFTLEAD)
    validate_error(resp, ApiErrorId.ERR_FLAVOR_INVALID_STATE.value)


def test_allergen_conflict_wins_over_rotated_out_topping(api):
    """PRD §2.7: "the business checks fire in this exact sequence: (1) the
    **allergen guard**, rejecting with `ERR_ALLERGEN_CONFLICT`; (2) the
    **sanitation gate**, requiring the flavor's machine to be `READY`, rejecting
    with `ERR_MACHINE_NOT_READY`; (3) **inventory availability** of the flavor and
    every requested topping, rejecting with `ERR_TOPPING_UNAVAILABLE`; (4)
    **net-weight validity**, rejecting with `ERR_INVALID_WEIGHT`; and (5) **mix
    sufficiency**, rejecting with `ERR_INSUFFICIENT_MIX`."

    Design: Difficulty/priority_pair_validation_conflict/addline_allergen_safety_beats_topping_constraint
    """
    machine, flavor = setup_machine_flavor(api)
    topping = make_topping(api, name="Peanuts", surcharge_cents=40, initial_units=50, allergen_tags=["NUTS"])
    validate_success(api.rotate_out_topping(topping["id"], SHIFTLEAD))
    ticket = make_ticket(api, excluded_allergens=["NUTS"])
    resp = api.add_line(ticket["id"], add_line_payload(flavor["id"], 5.0, topping_ids=[topping["id"]]), CASHIER)
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


def test_allergen_conflict_fires_on_available_topping(api):
    """PRD §3.4: "First, the **allergen guard**: if any applied topping carries
    an allergen tag that appears in the ticket's `excluded_allergens`, the cup is
    rejected with `ERR_ALLERGEN_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/addline_allergen_safety_beats_topping_constraint
    """
    machine, flavor = setup_machine_flavor(api)
    topping = make_topping(api, name="Peanuts", surcharge_cents=40, initial_units=50, allergen_tags=["NUTS"])
    ticket = make_ticket(api, excluded_allergens=["NUTS"])
    resp = api.add_line(ticket["id"], add_line_payload(flavor["id"], 5.0, topping_ids=[topping["id"]]), CASHIER)
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


def test_net_weight_zero_rejected(api):
    """PRD §3.4: "Fourth, **weight**: the computed `net_weight_oz` must be
    strictly greater than zero, otherwise `ERR_INVALID_WEIGHT`."

    Design: Difficulty/boundary_precision_check/sale_line_net_weight_strictly_positive
    """
    machine, flavor = setup_machine_flavor(api)
    ticket = make_ticket(api)
    resp = api.add_line(ticket["id"], add_line_payload(flavor["id"], 2.0, container_tare_oz=2.0), CASHIER)
    validate_error(resp, ApiErrorId.ERR_INVALID_WEIGHT.value)


def test_net_weight_strictly_positive_accepted(api):
    """PRD §3.4: "The read-only `net_weight_oz` is the gross weight minus the
    tare and must be strictly greater than zero."

    Design: Difficulty/boundary_precision_check/sale_line_net_weight_strictly_positive
    """
    machine, flavor = setup_machine_flavor(api)
    ticket = make_ticket(api)
    resp = api.add_line(ticket["id"], add_line_payload(flavor["id"], 2.5, container_tare_oz=2.0), CASHIER)
    data = validate_success(resp, expected_status=201)
    assert data["net_weight_oz"] == 0.5, \
        f"net_weight_oz must be gross 2.5 minus tare 2.0 = 0.5, got {data['net_weight_oz']}"


def test_void_restores_topping_units(api):
    """PRD §3.6: "A void unwinds the ticket's entire footprint: every topping
    consumed by the ticket's cups has its `on_hand_units` restored by the number
    of units it consumed"

    Design: Difficulty/compensating_invariant/void_conserves_topping_units
    """
    machine, flavor = setup_machine_flavor(api)
    topping = make_topping(api, surcharge_cents=30, initial_units=50)
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 7.3, topping_ids=[topping["id"]])
    do_checkout(api, ticket["id"])
    voided = validate_success(api.void_ticket(ticket["id"], SHIFTLEAD))
    assert voided["payment_status"] == "VOIDED"
    got = validate_success(api.get_topping(topping["id"], CASHIER))
    assert got["on_hand_units"] == 50, \
        f"void must restore consumed topping units back to 50, got {got['on_hand_units']}"


def test_topping_units_consumed_then_restored_no_drift(api):
    """PRD §3.2: "Each cup that includes a topping consumes one unit of its
    `on_hand_units`; voiding a ticket restores consumed units, and a `ShiftLead`
    may increase stock by supplying `added_units` on a restock, which adds to
    `on_hand_units`."

    Design: Difficulty/compensating_invariant/void_conserves_topping_units
    """
    machine, flavor = setup_machine_flavor(api)
    topping = make_topping(api, surcharge_cents=30, initial_units=50)
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 7.3, topping_ids=[topping["id"]])
    after_add = validate_success(api.get_topping(topping["id"], CASHIER))
    assert after_add["on_hand_units"] == 49, f"one cup must consume one unit (50->49), got {after_add['on_hand_units']}"
    do_checkout(api, ticket["id"])
    validate_success(api.void_ticket(ticket["id"], SHIFTLEAD))
    after_void = validate_success(api.get_topping(topping["id"], CASHIER))
    assert after_void["on_hand_units"] == 50, f"void must return units to 50, got {after_void['on_hand_units']}"


def test_addline_insufficient_mix_rejected(api):
    """PRD §3.4: "Fifth, **mix sufficiency**: the requested `net_weight_oz` must
    not exceed the flavor's machine `current_mix_level_oz`, otherwise
    `ERR_INSUFFICIENT_MIX`."

    Design: Corner/validations/addline_insufficient_mix_rejected
    """
    machine = make_machine(api, mix_par_oz=1000, initial_mix_oz=5)
    flavor = make_flavor(api, machine["id"])
    ticket = make_ticket(api)
    resp = api.add_line(ticket["id"], add_line_payload(flavor["id"], 10.0), CASHIER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MIX.value)


def test_void_restores_machine_mix_level(api):
    """PRD §3.6: "each source machine's `current_mix_level_oz` is restored by the
    total `net_weight_oz` its flavor dispensed on this ticket, capped so it never
    exceeds that machine's `mix_par_oz`"

    Design: Corner/cross_cutting_complexity_layers/void_restores_machine_mix_derived_field
    """
    machine = make_machine(api, mix_par_oz=1000, initial_mix_oz=1000)
    flavor = make_flavor(api, machine["id"])
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 7.3)
    do_checkout(api, ticket["id"])
    validate_success(api.void_ticket(ticket["id"], SHIFTLEAD))
    got = validate_success(api.get_machine(machine["id"], CASHIER))
    assert got["current_mix_level_oz"] == 1000, \
        f"void must restore machine mix back to 1000, got {got['current_mix_level_oz']}"
