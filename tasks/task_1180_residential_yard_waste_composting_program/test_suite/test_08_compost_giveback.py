"""Compost entitlement rounding and the giveback program: inventory
derivation, claim quota ladder, and claim voiding."""
import pytest

from test_helpers import (
    ApiErrorId,
    claim_compost,
    claim_compost_ok,
    complete_ticket,
    create_published_route,
    create_ticket,
    get_giveback_event,
    get_household,
    make_clerk_headers,
    make_resident_headers,
    set_clock,
    setup_active_household_with_route,
    setup_giveback_scenario,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / entitlement_per_pickup_rounding_pinned
# ---------------------------------------------------------------------------

def _setup_two_ticket_household():
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    t1 = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-04")
    t2 = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-11")
    ctx.update({"t1": t1, "t2": t2})
    return ctx


def test_entitlement_rounds_each_pickup_half_up(api, admin_headers):
    """PRD section 3.8: "The rounding order is pinned: each pickup is rounded
    first and the rounded values are summed." round-half-up(133 x 0.025, 2) =
    3.33 for the first pickup alone.

    Design: Difficulty/combinatorial_formula/entitlement_per_pickup_rounding_pinned
    """
    ctx = _setup_two_ticket_household()
    complete_ticket(ctx["t1"]["id"], 133)

    household = get_household(ctx["household"]["id"])
    assert household["compost_entitlement_gallons"] == pytest.approx(3.33, abs=1e-9)


def test_entitlement_per_pickup_rounding_pinned(api, admin_headers):
    """PRD section 3.8: "The alternative order — summing all pounds first and
    converting once — is explicitly forbidden because it diverges: 133 pounds
    plus 67 pounds yields 5.01 gallons under the pinned order (3.33 plus 1.68)
    but 5.00 under the forbidden one."

    Design: Difficulty/combinatorial_formula/entitlement_per_pickup_rounding_pinned
    """
    ctx = _setup_two_ticket_household()
    complete_ticket(ctx["t1"]["id"], 133)
    complete_ticket(ctx["t2"]["id"], 67)

    household = get_household(ctx["household"]["id"])
    assert household["compost_entitlement_gallons"] == pytest.approx(5.01, abs=1e-9)


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / claim_equal_to_entitlement_allowed
# ---------------------------------------------------------------------------

def test_claim_equal_to_entitlement_allowed(api, admin_headers):
    """PRD section 3.8: "first entitlement, rejecting with
    `ERR_ENTITLEMENT_EXCEEDED` when the requested gallons exceed the
    household's remaining `compost_entitlement_gallons`" and "A successful
    claim is created already `FULFILLED`, deducts its `gallons` from
    `remaining_gallons`, and records the household's entitlement at claim time
    in `entitlement_snapshot_gallons` at two decimal places." A 5-gallon claim
    equals the 5.00 entitlement and is allowed; inventory 250 falls to 245.

    Design: Difficulty/boundary_precision_check/claim_equal_to_entitlement_allowed
    """
    ctx = setup_giveback_scenario(completed_weights=(100, 100),
                                  accepted_lbs=(4000, 6000),
                                  per_household_cap_gallons=10)
    event = ctx["event"]
    assert event["initial_inventory_gallons"] == 250

    claim = claim_compost_ok(event["id"], ctx["household"], 5)
    assert claim["status"] == "FULFILLED"
    assert claim["entitlement_snapshot_gallons"] == pytest.approx(5.0, abs=1e-9)

    event_after = get_giveback_event(event["id"])
    assert event_after["remaining_gallons"] == 245


def test_claim_beyond_remaining_entitlement_rejected(api, admin_headers):
    """PRD section 3.8: "first entitlement, rejecting with
    `ERR_ENTITLEMENT_EXCEEDED` when the requested gallons exceed the
    household's remaining `compost_entitlement_gallons`". After claiming all
    5.00 gallons, a further 1-gallon claim exceeds the remaining 0.00.

    Design: Difficulty/boundary_precision_check/claim_equal_to_entitlement_allowed
    """
    ctx = setup_giveback_scenario(completed_weights=(100, 100),
                                  accepted_lbs=(4000, 6000),
                                  per_household_cap_gallons=10)
    event = ctx["event"]
    claim_compost_ok(event["id"], ctx["household"], 5)

    res = claim_compost(event["id"], ctx["household"], 1)
    validate_error(res, ApiErrorId.ERR_ENTITLEMENT_EXCEEDED)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / claim_requires_open_giveback_event
# ---------------------------------------------------------------------------

def test_claim_rejected_while_event_scheduled(api, admin_headers):
    """PRD section 3.8: "The event must be `OPEN` — claims are only possible
    on the event date — otherwise `ERR_GIVEBACK_EVENT_NOT_OPEN`." PRD section
    2.4: "A compost giveback event reads `SCHEDULED` before its `event_date`".

    Design: Difficulty/cross_entity_state_dependency/claim_requires_open_giveback_event
    """
    ctx = setup_giveback_scenario(completed_weights=(100,), accepted_lbs=(4000, 6000),
                                  per_household_cap_gallons=10,
                                  claim_clock="2026-11-10T08:00:00Z")
    event = get_giveback_event(ctx["event"]["id"])
    assert event["status"] == "SCHEDULED"

    res = claim_compost(ctx["event"]["id"], ctx["household"], 2)
    validate_error(res, ApiErrorId.ERR_GIVEBACK_EVENT_NOT_OPEN)


def test_claim_succeeds_once_event_opens(api, admin_headers):
    """PRD section 2.4: "A compost giveback event reads `SCHEDULED` before its
    `event_date`, `OPEN` exactly on `event_date`, and `CLOSED` after it." PRD
    section 3.8: "A successful claim is created already `FULFILLED`, deducts
    its `gallons` from `remaining_gallons`". The identical 2-gallon claim that
    failed while SCHEDULED succeeds on the event date; inventory 250 -> 248.

    Design: Difficulty/cross_entity_state_dependency/claim_requires_open_giveback_event
    """
    ctx = setup_giveback_scenario(completed_weights=(100,), accepted_lbs=(4000, 6000),
                                  per_household_cap_gallons=10,
                                  claim_clock="2026-11-10T08:00:00Z")
    res = claim_compost(ctx["event"]["id"], ctx["household"], 2)
    validate_error(res, ApiErrorId.ERR_GIVEBACK_EVENT_NOT_OPEN)

    set_clock("2026-11-15T08:00:00Z")
    claim = claim_compost_ok(ctx["event"]["id"], ctx["household"], 2)
    assert claim["status"] == "FULFILLED"
    assert get_giveback_event(ctx["event"]["id"])["remaining_gallons"] == 248


# ---------------------------------------------------------------------------
# Queue B: quota ladder and void lifecycle
# ---------------------------------------------------------------------------

def test_claim_over_household_cap(api, admin_headers):
    """PRD section 3.8: "second the per-household cap, rejecting with
    `ERR_PER_HOUSEHOLD_CAP_EXCEEDED` when the request would push the
    household's cumulative claimed gallons at this event above
    `per_household_cap_gallons`". With entitlement 5.00 and cap 3, a 4-gallon
    claim passes entitlement but fails the cap; a 3-gallon claim (== cap)
    succeeds and inventory falls 250 -> 247.

    Design: Corner/validations/claim_over_household_cap
    """
    ctx = setup_giveback_scenario(completed_weights=(100, 100),
                                  accepted_lbs=(4000, 6000),
                                  per_household_cap_gallons=3)
    event = ctx["event"]

    res = claim_compost(event["id"], ctx["household"], 4)
    validate_error(res, ApiErrorId.ERR_PER_HOUSEHOLD_CAP_EXCEEDED)

    claim = claim_compost_ok(event["id"], ctx["household"], 3)
    assert claim["status"] == "FULFILLED"
    assert get_giveback_event(event["id"])["remaining_gallons"] == 247


def test_claim_insufficient_inventory(api, admin_headers):
    """PRD section 3.8: "third inventory, rejecting with
    `ERR_INSUFFICIENT_INVENTORY` when the request exceeds the event's
    `remaining_gallons`." With entitlement 400.00 and cap 400 but inventory
    250, a 300-gallon claim passes the first two quota gates and fails
    inventory.

    Design: Corner/validations/claim_insufficient_inventory
    """
    ctx = setup_giveback_scenario(completed_weights=(8000, 8000),
                                  accepted_lbs=(4000, 6000),
                                  per_household_cap_gallons=400)
    event = ctx["event"]
    assert event["initial_inventory_gallons"] == 250

    res = claim_compost(event["id"], ctx["household"], 300)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


def test_claim_void_twice_rejected(api, admin_headers):
    """PRD section 3.8: "A `BillingClerk` may void a `FULFILLED` claim
    (otherwise `ERR_INVALID_STATE`): the claim becomes `VOIDED`, its gallons
    are added back to the event's `remaining_gallons`, and the household's
    entitlement consumption is released."

    Design: Corner/state_machines/claim_void_twice_rejected
    """
    ctx = setup_giveback_scenario(completed_weights=(100,), accepted_lbs=(4000, 6000),
                                  per_household_cap_gallons=10)
    event = ctx["event"]
    claim = claim_compost_ok(event["id"], ctx["household"], 2)
    assert get_giveback_event(event["id"])["remaining_gallons"] == 248

    voided = validate_success(
        api.void_compost_claim(claim["id"], make_clerk_headers("clerk_1")), 200)
    assert voided["status"] == "VOIDED"
    assert get_giveback_event(event["id"])["remaining_gallons"] == 250

    res = api.void_compost_claim(claim["id"], make_clerk_headers("clerk_1"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    # Inventory is restored exactly once.
    assert get_giveback_event(event["id"])["remaining_gallons"] == 250
