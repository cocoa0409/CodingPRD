"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database).
Lenient get_success_data() is used so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_ENROLLMENT, SEASON_YEAR
from .factories import (
    create_cart_payload,
    create_compost_claim_payload,
    create_facility_delivery_payload,
    create_facility_payload,
    create_giveback_event_payload,
    create_household_payload,
    create_inspection_payload,
    create_outreach_campaign_payload,
    create_pickup_ticket_payload,
    create_receive_payload,
    create_route_payload,
    create_service_zone_payload,
    create_subscription_payload,
    create_surge_booking_payload,
    create_surge_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_clerk_headers,
    make_coordinator_headers,
    make_driver_headers,
    make_inspector_headers,
    make_resident_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# --- Clock -----------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Drive the logical clock (admin-only test hook)."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    assert res.status_code == 200, f"setup failed: set_clock -> {res.status_code} {res.text}"


# --- Tier 1: single-resource creators ---------------------------------------

def create_zone(clock=CLOCK_ENROLLMENT, set_clock_first=True, **overrides) -> dict:
    if set_clock_first:
        set_clock(clock)
    res = api_client.create_service_zone(create_service_zone_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_household(zone_id: str, address_line: str = "1 Oak St") -> dict:
    res = api_client.create_household(
        create_household_payload(zone_id, address_line=address_line),
        TEST_USERS["anonymous_headers"],
    )
    return get_success_data(res)


def create_subscription(household: dict, season_year: int = SEASON_YEAR) -> dict:
    """Create a subscription with a fresh OCC version read of the household."""
    current = get_success_data(api_client.get_household(household["id"], ADMIN))
    res = api_client.create_subscription(
        create_subscription_payload(household["id"], current["version"], season_year=season_year),
        make_resident_headers(household["id"]),
    )
    return get_success_data(res)


def pay_subscription(subscription_id: str, household_id: str, use_credit_balance: bool = False) -> dict:
    res = api_client.pay_subscription(
        subscription_id,
        {"use_credit_balance": use_credit_balance},
        make_resident_headers(household_id),
    )
    return get_success_data(res)


def create_active_subscription(household: dict, season_year: int = SEASON_YEAR) -> dict:
    """Create a subscription and activate it (universal auto-activates; opt-in is paid)."""
    sub = create_subscription(household, season_year=season_year)
    if sub["status"] != "ACTIVE":
        sub = pay_subscription(sub["id"], household["id"])
    assert sub["status"] == "ACTIVE", f"setup failed: subscription not ACTIVE: {sub}"
    return sub


def create_cart(household: dict, subscription_id: str, size_gallons=64) -> dict:
    res = api_client.create_cart(
        create_cart_payload(household["id"], subscription_id, size_gallons),
        make_resident_headers(household["id"]),
    )
    return get_success_data(res)


def deliver_cart(cart_id: str, supervisor_id: str = "sup_1") -> dict:
    return get_success_data(api_client.deliver_cart(cart_id, make_supervisor_headers(supervisor_id)))


def create_route(zone_id: str, **overrides) -> dict:
    res = api_client.create_route(create_route_payload(zone_id, **overrides), ADMIN)
    return get_success_data(res)


def create_published_route(zone_id: str, **overrides) -> dict:
    route = create_route(zone_id, **overrides)
    return get_success_data(api_client.publish_route(route["id"], ADMIN))


def create_ticket(subscription_id: str, route_id: str, service_date: str, supervisor_id: str = "sup_1") -> dict:
    res = api_client.create_pickup_ticket(
        create_pickup_ticket_payload(subscription_id, route_id, service_date),
        make_supervisor_headers(supervisor_id),
    )
    return get_success_data(res)


def complete_ticket(ticket_id: str, weight_lbs: int, driver_id: str = "drv_1") -> dict:
    return get_success_data(
        api_client.complete_pickup_ticket(ticket_id, {"weight_lbs": weight_lbs}, make_driver_headers(driver_id))
    )


def inspect_ticket(ticket_id: str, result: str = "TAGGED_REJECTED", violation_codes=None, inspector_id: str = "insp_1") -> dict:
    return get_success_data(
        api_client.create_contamination_inspection(
            create_inspection_payload(ticket_id, result=result, violation_codes=violation_codes),
            make_inspector_headers(inspector_id),
        )
    )


def report_missed(ticket_id: str, household: dict) -> dict:
    return get_success_data(
        api_client.report_missed_pickup_ticket(ticket_id, make_resident_headers(household["id"]))
    )


def validate_missed(ticket_id: str, validated: bool, supervisor_id: str = "sup_1") -> dict:
    return get_success_data(
        api_client.validate_missed_pickup_ticket(
            ticket_id, {"validated": validated}, make_supervisor_headers(supervisor_id)
        )
    )


def get_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def get_household(household_id: str) -> dict:
    return get_success_data(api_client.get_household(household_id, ADMIN))


def get_ticket(ticket_id: str) -> dict:
    return get_success_data(api_client.get_pickup_ticket(ticket_id, ADMIN))


def get_surge_event(event_id: str) -> dict:
    return get_success_data(api_client.get_surge_event(event_id, ADMIN))


def get_giveback_event(event_id: str) -> dict:
    return get_success_data(api_client.get_giveback_event(event_id, ADMIN))


# --- Tier 2: zone + household + subscription + route hierarchies ------------

def setup_active_household(service_model: str = "OPT_IN", clock: str = CLOCK_ENROLLMENT,
                           address_line: str = "1 Oak St", **zone_overrides) -> dict:
    """Zone + household + ACTIVE subscription (paid when opt-in)."""
    zone_kwargs = {"service_model": service_model}
    zone_kwargs.update(zone_overrides)
    if service_model == "UNIVERSAL":
        zone_kwargs.setdefault("base_seasonal_fee_cents", 9000)
    zone = create_zone(clock=clock, **zone_kwargs)
    household = create_household(zone["id"], address_line=address_line)
    subscription = create_active_subscription(household)
    return {"zone": zone, "household": household, "subscription": subscription}


def setup_active_household_with_route(service_model: str = "OPT_IN", clock: str = CLOCK_ENROLLMENT,
                                      address_line: str = "1 Oak St", route_overrides=None,
                                      **zone_overrides) -> dict:
    """Zone + household + ACTIVE subscription + published MONDAY route."""
    ctx = setup_active_household(service_model=service_model, clock=clock,
                                 address_line=address_line, **zone_overrides)
    ctx["route"] = create_published_route(ctx["zone"]["id"], **(route_overrides or {}))
    return ctx


def setup_households_with_active_subscriptions(zone: dict, count: int) -> list:
    """N households in one zone, each with an ACTIVE 2026 subscription."""
    out = []
    for i in range(count):
        household = create_household(zone["id"], address_line=f"{i + 1} Oak St")
        subscription = create_active_subscription(household)
        out.append({"household": household, "subscription": subscription})
    return out


# --- Tier 3: contamination / suspension lifecycles ---------------------------

def strike_tickets(ctx: dict, dates: list, supervisor_id: str = "sup_1") -> list:
    """Schedule one ticket per date for the context's subscription."""
    return [
        create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], d, supervisor_id=supervisor_id)
        for d in dates
    ]


def reject_tickets(tickets: list, inspector_id: str = "insp_1"):
    """Record a TAGGED_REJECTED inspection against each ticket."""
    codes = ["PLASTIC_BAG", "FOOD_WASTE", "DIRT_ROCK", "HAZARDOUS", "NON_YARD_MATERIAL"]
    for i, ticket in enumerate(tickets):
        inspect_ticket(ticket["id"], result="TAGGED_REJECTED",
                       violation_codes=[codes[i % len(codes)]], inspector_id=inspector_id)


def setup_suspended_subscription(clock: str = "2026-05-18T00:00:00Z",
                                 strike_dates=("2026-05-04", "2026-05-11", "2026-05-18"),
                                 service_model: str = "OPT_IN",
                                 with_cart_size: str = None,
                                 extra_ticket_dates=()) -> dict:
    """ACTIVE subscription driven to SUSPENDED via TAGGED_REJECTED strikes.

    For opt-in subscriptions the base fee is paid before any cart is added
    (cart requests require an ACTIVE subscription). Returns a context dict
    with zone/household/subscription/route and the strike tickets plus any
    extra future tickets (which the suspension flips to SKIPPED).
    """
    ctx = setup_active_household_with_route(service_model=service_model)
    if with_cart_size is not None:
        create_cart(ctx["household"], ctx["subscription"]["id"], with_cart_size)
    tickets = strike_tickets(ctx, list(strike_dates))
    extra = strike_tickets(ctx, list(extra_ticket_dates))
    set_clock(clock)
    reject_tickets(tickets)
    ctx["strike_tickets"] = tickets
    ctx["extra_tickets"] = extra
    ctx["subscription"] = get_subscription(ctx["subscription"]["id"])
    return ctx


def cure_subscription(subscription_id: str, household_id: str, payment_cents: int) -> dict:
    return get_success_data(
        api_client.cure_subscription(
            subscription_id, {"payment_cents": payment_cents}, make_resident_headers(household_id)
        )
    )


# --- Tier 3: missed-pickup -> service credit chain ---------------------------

def setup_pending_credit(service_model: str = "OPT_IN", ticket_date: str = "2026-05-04",
                         report_clock: str = "2026-05-05T00:00:00Z",
                         validator_id: str = "sup_1") -> dict:
    """Drive one ticket through report-missed + validate-missed(true).

    Returns a context dict including the PENDING_APPROVAL credit id.
    """
    ctx = setup_active_household_with_route(service_model=service_model)
    ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], ticket_date)
    set_clock(report_clock)
    report_missed(ticket["id"], ctx["household"])
    validate_missed(ticket["id"], True, supervisor_id=validator_id)
    credits, _meta = _list_credits(ctx["subscription"]["id"])
    assert len(credits) == 1, f"setup failed: expected 1 pending credit, got {len(credits)}"
    ctx["ticket"] = get_ticket(ticket["id"])
    ctx["credit"] = credits[0]
    return ctx


def _list_credits(subscription_id: str, status: str = None):
    params = {"subscription_id": subscription_id}
    if status:
        params["status"] = status
    res = api_client.list_service_credits(ADMIN, params=params)
    body = res.json()
    assert res.status_code == 200, f"setup failed: list credits -> {res.status_code} {res.text}"
    return body["data"], body["meta"]


def approve_credit(credit_id: str, clerk_id: str = "clerk_1") -> dict:
    return get_success_data(api_client.approve_service_credit(credit_id, make_clerk_headers(clerk_id)))


def void_credit(credit_id: str, clerk_id: str = "clerk_1") -> dict:
    return get_success_data(api_client.void_service_credit(credit_id, make_clerk_headers(clerk_id)))


# --- Tier 3: surge events and bookings ---------------------------------------

def setup_open_surge_event(capacity_slots: int = 5, num_households: int = 1,
                           event_type: str = "LEAF_SURGE", service_date: str = "2026-11-07",
                           booking_window_start: str = "2026-10-01T00:00:00Z",
                           booking_window_end: str = "2026-11-01T00:00:00Z",
                           clock: str = "2026-10-15T00:00:00Z",
                           service_model: str = "UNIVERSAL", **zone_overrides) -> dict:
    """Universal zone, N households with ACTIVE subscriptions, one surge event
    whose booking window is open at the given clock."""
    zone_kwargs = {"service_model": service_model, "base_seasonal_fee_cents": 9000}
    zone_kwargs.update(zone_overrides)
    zone = create_zone(**zone_kwargs)
    households = setup_households_with_active_subscriptions(zone, num_households)
    event = get_success_data(api_client.create_surge_event(
        create_surge_event_payload(
            zone["id"], event_type=event_type, service_date=service_date,
            capacity_slots=capacity_slots, booking_window_start=booking_window_start,
            booking_window_end=booking_window_end),
        ADMIN,
    ))
    set_clock(clock)
    return {"zone": zone, "households": households, "event": get_surge_event(event["id"])}


def book_surge(event_id: str, household: dict, quantity_bundles: int = 2):
    """Book with a fresh OCC read of the event. Returns the raw response."""
    event = get_surge_event(event_id)
    return api_client.create_surge_booking(
        create_surge_booking_payload(event_id, household["id"], event["version"],
                                     quantity_bundles=quantity_bundles),
        make_resident_headers(household["id"]),
    )


def book_surge_ok(event_id: str, household: dict, quantity_bundles: int = 2) -> dict:
    return get_success_data(book_surge(event_id, household, quantity_bundles))


def cancel_booking(booking_id: str, household: dict) -> dict:
    return get_success_data(
        api_client.cancel_surge_booking(booking_id, make_resident_headers(household["id"]))
    )


# --- Tier 3: facilities and deliveries ---------------------------------------

def create_facility(**overrides) -> dict:
    return get_success_data(api_client.create_facility(create_facility_payload(**overrides), ADMIN))


def create_delivery(facility_id: str, route_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_facility_delivery(
            create_facility_delivery_payload(facility_id, route_id, **overrides),
            make_supervisor_headers("sup_1"),
        )
    )


def receive_delivery(delivery_id: str, outcome: str = "ACCEPT", gross_weight_lbs: int = 1000,
                     contaminated_item_count: int = 0, supervisor_id: str = "sup_1") -> dict:
    return get_success_data(
        api_client.receive_facility_delivery(
            delivery_id,
            create_receive_payload(outcome, gross_weight_lbs, contaminated_item_count),
            make_supervisor_headers(supervisor_id),
        )
    )


def setup_facility_with_route(clock: str = "2026-06-01T00:00:00Z",
                              route_overrides=None, **facility_overrides) -> dict:
    """Zone + published route + OPEN facility, clock inside the season."""
    zone = create_zone(clock=clock)
    route = create_published_route(zone["id"], **(route_overrides or {}))
    facility = create_facility(**facility_overrides)
    return {"zone": zone, "route": route, "facility": facility}


# --- Tier 4: giveback scenario (tickets -> entitlement, deliveries -> inventory)

def setup_giveback_scenario(completed_weights=(100, 100), accepted_lbs=(4000, 6000),
                            per_household_cap_gallons: int = 10,
                            event_date: str = "2026-11-15",
                            claim_clock: str = "2026-11-15T08:00:00Z") -> dict:
    """Universal household with completed tickets (entitlement), a facility with
    ACCEPTED deliveries (inventory), and a giveback event open at claim_clock.

    Returns a context dict with zone/household/subscription/route/facility/
    deliveries/event. 10000 accepted lbs -> floor(10000 x 0.025) = 250 gallons.
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    ticket_dates = ["2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25"]
    tickets = []
    for i, weight in enumerate(completed_weights):
        ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"],
                               ticket_dates[i % len(ticket_dates)])
        tickets.append(complete_ticket(ticket["id"], weight))
    ctx["tickets"] = tickets

    facility = create_facility()
    delivery_dates = ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"]
    deliveries = []
    for i, lbs in enumerate(accepted_lbs):
        date = delivery_dates[i % len(delivery_dates)]
        delivery = create_delivery(
            facility["id"], ctx["route"]["id"], delivery_date=date,
            window_start=f"{date}T09:00:00Z", window_end=f"{date}T10:00:00Z")
        deliveries.append(receive_delivery(delivery["id"], "ACCEPT", lbs, 0))
    ctx["facility"] = facility
    ctx["deliveries"] = deliveries

    event = get_success_data(api_client.create_giveback_event(
        create_giveback_event_payload(ctx["zone"]["id"], event_date=event_date,
                                      per_household_cap_gallons=per_household_cap_gallons),
        ADMIN,
    ))
    ctx["event"] = event
    if claim_clock is not None:
        set_clock(claim_clock)
    return ctx


def claim_compost(event_id: str, household: dict, gallons: int):
    """Raw claim response (caller validates success or error)."""
    return api_client.create_compost_claim(
        create_compost_claim_payload(event_id, household["id"], gallons),
        make_resident_headers(household["id"]),
    )


def claim_compost_ok(event_id: str, household: dict, gallons: int) -> dict:
    return get_success_data(claim_compost(event_id, household, gallons))


# --- Tier 3: outreach campaigns ----------------------------------------------

def create_campaign(coordinator_id: str = "out_1", **overrides) -> dict:
    return get_success_data(
        api_client.create_outreach_campaign(
            create_outreach_campaign_payload(**overrides),
            make_coordinator_headers(coordinator_id),
        )
    )
