"""Contamination inspections, the strike regime, suspension, and cure."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_contamination_inspection,
    complete_ticket,
    create_household,
    create_inspection_payload,
    create_published_route,
    create_ticket,
    create_zone,
    cure_subscription,
    get_subscription,
    get_ticket,
    inspect_ticket,
    make_inspector_headers,
    make_supervisor_headers,
    reject_tickets,
    set_clock,
    setup_active_household,
    setup_active_household_with_route,
    setup_households_with_active_subscriptions,
    setup_suspended_subscription,
    strike_tickets,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / subscription_suspend_cure_cycle
# ---------------------------------------------------------------------------

def test_suspend_then_cure_returns_active_and_resets_strikes(api, admin_headers):
    """PRD section 3.5: "The subscription moves to `SUSPENDED`, a 2000-cent
    reinstatement surcharge is added to `surcharge_cents`, `suspended_reason` is
    set to `CONTAMINATION_STRIKES`" and "A successful cure resets
    `strikes_this_season` to zero, clears `suspended_reason` to null, adds
    `payment_cents` to `paid_cents`, and returns the subscription to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/subscription_suspend_cure_cycle
    """
    ctx = setup_suspended_subscription(with_cart_size=64)
    sub = ctx["subscription"]
    assert sub["status"] == "SUSPENDED"
    assert sub["surcharge_cents"] == 2000
    assert sub["strikes_this_season"] == 3
    assert sub["suspended_reason"] == "CONTAMINATION_STRIKES"

    # Outstanding: total (12000 + 1500 + 2000 = 15500) - paid (12000) = 3500.
    cured = cure_subscription(sub["id"], ctx["household"]["id"], 3500)
    assert cured["status"] == "ACTIVE"
    assert cured["strikes_this_season"] == 0
    assert cured["suspended_reason"] is None
    assert cured["paid_cents"] == 15500


def test_suspension_cycle_repeats_and_surcharge_accumulates(api, admin_headers):
    """PRD section 3.5: "The cycle from `ACTIVE` to `SUSPENDED` and back is
    repeatable within a season." and "`surcharge_cents` accumulates a 2000-cent
    reinstatement surcharge on each contamination suspension (§3.5)" — a second
    suspension raises the accumulator to 4000.

    Design: Difficulty/non_linear_state_machine/subscription_suspend_cure_cycle
    """
    ctx = setup_suspended_subscription(with_cart_size=64)
    sub = ctx["subscription"]
    cured = cure_subscription(sub["id"], ctx["household"]["id"], 3500)
    assert cured["status"] == "ACTIVE"

    # Second strike set on fresh tickets after the cure.
    tickets = strike_tickets(ctx, ["2026-05-25", "2026-06-01", "2026-06-08"])
    reject_tickets(tickets)

    sub_after = get_subscription(sub["id"])
    assert sub_after["strikes_this_season"] == 3
    assert sub_after["status"] == "SUSPENDED"
    assert sub_after["surcharge_cents"] == 4000
    assert sub_after["paid_cents"] == 15500


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade / contamination_suspension_skips_future_tickets_frees_route
# ---------------------------------------------------------------------------

def _setup_cascade_scenario():
    """Opt-in zone, published route with max_stops 2.

    H1: tickets 05-04, 05-11, 05-18, 05-25. H2: ticket 05-25 (route full on
    05-25 at 2/2). H3: no tickets. H1's 05-04 and 05-11 tickets already
    TAGGED_REJECTED at clock 2026-05-18 (strikes at 2).
    """
    zone = create_zone(service_model="OPT_IN", base_seasonal_fee_cents=12000)
    h1, h2, h3 = setup_households_with_active_subscriptions(zone, 3)
    route = create_published_route(zone["id"], max_stops=2, max_tonnage_lbs=100000)

    t1 = create_ticket(h1["subscription"]["id"], route["id"], "2026-05-04")
    t2 = create_ticket(h1["subscription"]["id"], route["id"], "2026-05-11")
    t3 = create_ticket(h1["subscription"]["id"], route["id"], "2026-05-18")
    t4 = create_ticket(h1["subscription"]["id"], route["id"], "2026-05-25")
    u1 = create_ticket(h2["subscription"]["id"], route["id"], "2026-05-25")

    set_clock("2026-05-18T00:00:00Z")
    inspect_ticket(t1["id"], result="TAGGED_REJECTED", violation_codes=["PLASTIC_BAG"])
    inspect_ticket(t2["id"], result="TAGGED_REJECTED", violation_codes=["FOOD_WASTE"])

    return {"zone": zone, "h1": h1, "h2": h2, "h3": h3, "route": route,
            "t1": t1, "t2": t2, "t3": t3, "t4": t4, "u1": u1}


def test_third_strike_suspends_and_skips_future_tickets(api, admin_headers):
    """PRD section 3.5: "A `TAGGED_REJECTED` inspection is consequential. The
    ticket moves from `SCHEDULED` to `REJECTED_CONTAMINATION`, and the
    subscription's `strikes_this_season` — the count of `TAGGED_REJECTED`
    inspections across that subscription's tickets, where `PASSED` and
    `TAGGED_WARNING` never increment — rises by one." and "every one of that
    subscription's tickets still `SCHEDULED` for a future `service_date` moves
    to `SKIPPED`, freeing the corresponding route capacity."

    Design: Difficulty/transitive_cascade/contamination_suspension_skips_future_tickets_frees_route
    """
    ctx = _setup_cascade_scenario()

    inspect_ticket(ctx["t3"]["id"], result="TAGGED_REJECTED", violation_codes=["DIRT_ROCK"])

    assert get_ticket(ctx["t3"]["id"])["status"] == "REJECTED_CONTAMINATION"
    assert get_subscription(ctx["h1"]["subscription"]["id"])["status"] == "SUSPENDED"
    assert get_ticket(ctx["t4"]["id"])["status"] == "SKIPPED"


def test_suspension_frees_route_capacity_for_another_household(api, admin_headers, supervisor_headers):
    """PRD section 3.5: "every one of that subscription's tickets still
    `SCHEDULED` for a future `service_date` moves to `SKIPPED`, freeing the
    corresponding route capacity." PRD section 3.4: "A ticket whose subscription
    is suspended, cancelled, or expired while the ticket's `service_date` is
    still in the future moves from `SCHEDULED` to `SKIPPED`, and its slot no
    longer counts against the route's stop or tonnage capacity."

    Design: Difficulty/transitive_cascade/contamination_suspension_skips_future_tickets_frees_route
    """
    ctx = _setup_cascade_scenario()
    inspect_ticket(ctx["t3"]["id"], result="TAGGED_REJECTED", violation_codes=["DIRT_ROCK"])

    # The 05-25 date was full (2/2) before the suspension; H1's skipped ticket
    # freed one slot, which H3's new ticket now occupies.
    new_ticket = create_ticket(ctx["h3"]["subscription"]["id"], ctx["route"]["id"], "2026-05-25")
    assert new_ticket["status"] == "SCHEDULED"
    assert get_ticket(ctx["u1"]["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / ticket_complete_requires_active_subscription
# ---------------------------------------------------------------------------

def _setup_suspended_with_today_ticket():
    """Opt-in household suspended by strikes on 05-04/05-11/05-18 tickets; a
    fourth ticket dated 2026-05-25 == the clock date is NOT auto-skipped (only
    future service dates are)."""
    ctx = setup_active_household_with_route(service_model="OPT_IN",
                                            base_seasonal_fee_cents=12000)
    strikes = strike_tickets(ctx, ["2026-05-04", "2026-05-11", "2026-05-18"])
    today = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-25")
    set_clock("2026-05-25T00:00:00Z")
    reject_tickets(strikes)
    ctx["today_ticket"] = today
    ctx["subscription"] = get_subscription(ctx["subscription"]["id"])
    return ctx


def test_complete_rejected_when_subscription_suspended(api, admin_headers, driver_headers):
    """PRD section 3.4: "the ticket must be `SCHEDULED`
    (`ERR_TICKET_NOT_SCHEDULED`) and its subscription must be `ACTIVE`
    (`ERR_SUBSCRIPTION_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/ticket_complete_requires_active_subscription
    """
    ctx = _setup_suspended_with_today_ticket()
    assert ctx["subscription"]["status"] == "SUSPENDED"
    assert get_ticket(ctx["today_ticket"]["id"])["status"] == "SCHEDULED"

    res = api.complete_pickup_ticket(ctx["today_ticket"]["id"], {"weight_lbs": 100}, driver_headers)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)


def test_ticket_remains_scheduled_after_suspended_completion_attempt(api, admin_headers, driver_headers):
    """PRD section 3.4: "the ticket must be `SCHEDULED`
    (`ERR_TICKET_NOT_SCHEDULED`) and its subscription must be `ACTIVE`
    (`ERR_SUBSCRIPTION_NOT_ACTIVE`)." PRD section 3.5: "every one of that
    subscription's tickets still `SCHEDULED` for a future `service_date` moves
    to `SKIPPED`" — a ticket due on the suspension day itself is not future, so
    it stays SCHEDULED, and a failed completion does not move it.

    Design: Difficulty/cross_entity_state_dependency/ticket_complete_requires_active_subscription
    """
    ctx = _setup_suspended_with_today_ticket()

    res = api.complete_pickup_ticket(ctx["today_ticket"]["id"], {"weight_lbs": 100}, driver_headers)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)

    ticket_after = get_ticket(ctx["today_ticket"]["id"])
    assert ticket_after["status"] == "SCHEDULED"
    assert ticket_after["weight_lbs"] is None


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / strike_threshold_exactly_at_max
# ---------------------------------------------------------------------------

def test_one_below_strike_threshold_keeps_active(api, admin_headers):
    """PRD section 3.5: "When the strike count reaches the zone's
    `max_strikes_per_season` while the subscription is `ACTIVE`, the strike
    regime fires: reaching the threshold exactly is sufficient (one strike below
    it is not)."

    Design: Difficulty/boundary_precision_check/strike_threshold_exactly_at_max
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    tickets = strike_tickets(ctx, ["2026-05-04", "2026-05-11"])
    set_clock("2026-05-18T00:00:00Z")
    reject_tickets(tickets)

    sub = get_subscription(ctx["subscription"]["id"])
    assert sub["strikes_this_season"] == 2
    assert sub["status"] == "ACTIVE"


def test_exactly_at_strike_threshold_suspends(api, admin_headers):
    """PRD section 3.5: "The subscription moves to `SUSPENDED`, a 2000-cent
    reinstatement surcharge is added to `surcharge_cents`, `suspended_reason` is
    set to `CONTAMINATION_STRIKES`" — the third TAGGED_REJECTED reaches the
    default threshold of 3 exactly.

    Design: Difficulty/boundary_precision_check/strike_threshold_exactly_at_max
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    tickets = strike_tickets(ctx, ["2026-05-04", "2026-05-11", "2026-05-18"])
    set_clock("2026-05-18T00:00:00Z")
    reject_tickets(tickets[:2])

    sub = get_subscription(ctx["subscription"]["id"])
    assert sub["strikes_this_season"] == 2
    assert sub["status"] == "ACTIVE"

    inspect_ticket(tickets[2]["id"], result="TAGGED_REJECTED", violation_codes=["DIRT_ROCK"])
    sub = get_subscription(ctx["subscription"]["id"])
    assert sub["strikes_this_season"] == 3
    assert sub["status"] == "SUSPENDED"
    assert sub["suspended_reason"] == "CONTAMINATION_STRIKES"


# ---------------------------------------------------------------------------
# Queue B: inspection rules and entitlement input filtering
# ---------------------------------------------------------------------------

def test_warning_inspection_adds_no_strike(api, admin_headers):
    """PRD section 3.5: "A `PASSED` or `TAGGED_WARNING` inspection simply
    records the finding without changing the ticket." and "the subscription's
    `strikes_this_season` — the count of `TAGGED_REJECTED` inspections across
    that subscription's tickets, where `PASSED` and `TAGGED_WARNING` never
    increment".

    Design: Corner/calculations/warning_inspection_adds_no_strike
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-04")

    inspection = inspect_ticket(ticket["id"], result="TAGGED_WARNING",
                                violation_codes=["PLASTIC_BAG"])
    assert_contamination_inspection(inspection)
    assert inspection["result"] == "TAGGED_WARNING"

    sub = get_subscription(ctx["subscription"]["id"])
    assert sub["strikes_this_season"] == 0
    assert sub["status"] == "ACTIVE"
    assert get_ticket(ticket["id"])["status"] == "SCHEDULED"


def test_duplicate_inspection_rejected(api, admin_headers, inspector_headers):
    """PRD section 3.5: "a ticket may be inspected at most once — a second
    inspection attempt fails with `ERR_DUPLICATE_INSPECTION`."

    Design: Corner/state_machines/duplicate_inspection_rejected
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-04")
    first = inspect_ticket(ticket["id"], result="PASSED", violation_codes=[])
    assert first["result"] == "PASSED"

    res = api.create_contamination_inspection(
        create_inspection_payload(ticket["id"], result="TAGGED_REJECTED",
                                  violation_codes=["PLASTIC_BAG"]),
        inspector_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_INSPECTION)
    assert get_ticket(ticket["id"])["status"] == "SCHEDULED"
    assert get_subscription(ctx["subscription"]["id"])["strikes_this_season"] == 0


def test_tagged_inspection_without_codes_returns_invalid_request(api, admin_headers, inspector_headers):
    """PRD section 3.5: "A `PASSED` result requires `violation_codes` to be
    empty; either tagged result requires a non-empty list drawn from
    `PLASTIC_BAG`, `FOOD_WASTE`, `DIRT_ROCK`, `HAZARDOUS`, and
    `NON_YARD_MATERIAL`; violating this pairing is `ERR_INVALID_REQUEST`."

    Design: Corner/validations/tagged_inspection_without_codes_returns_invalid_request
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-04")

    res = api.create_contamination_inspection(
        {"pickup_ticket_id": ticket["id"], "result": "TAGGED_REJECTED", "violation_codes": []},
        inspector_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    assert get_ticket(ticket["id"])["status"] == "SCHEDULED"


def test_entitlement_excludes_rejected_tickets(api, admin_headers):
    """PRD section 3.8: "for each `COMPLETED` ticket across all of the
    household's subscriptions in the current zone season —
    `REJECTED_CONTAMINATION`, `SKIPPED`, and `MISSED` tickets are excluded —
    convert that ticket's `weight_lbs` to gallons at half yield and twenty
    pounds per gallon (0.025 gallons per pound)". A 100-lb COMPLETED ticket plus
    a 300-lb REJECTED_CONTAMINATION ticket yields exactly 2.50 gallons.

    Design: Corner/calculations/entitlement_excludes_rejected_tickets
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    t1 = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-04")
    t2 = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-11")
    complete_ticket(t1["id"], 100)
    inspect_ticket(t2["id"], result="TAGGED_REJECTED", violation_codes=["PLASTIC_BAG"])

    household = api.get_household(ctx["household"]["id"], admin_headers).json()["data"]
    assert household["compost_entitlement_gallons"] == pytest.approx(2.5, abs=1e-9)

    sub = get_subscription(ctx["subscription"]["id"])
    assert sub["strikes_this_season"] == 1
    assert sub["status"] == "ACTIVE"
    assert get_ticket(t2["id"])["status"] == "REJECTED_CONTAMINATION"
