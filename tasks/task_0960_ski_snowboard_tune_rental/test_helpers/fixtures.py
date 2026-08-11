"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data() so failures surface
as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_damage_assessment_payload,
    create_demo_credit_payload,
    create_equipment_item_payload,
    create_pickup_booking_payload,
    create_pickup_window_payload,
    create_reservation_item_payload,
    create_reservation_payload,
    create_season_lease_payload,
    create_shop_day_capacity_payload,
    create_tune_ticket_payload,
)
from .test_users import TEST_USERS, make_customer_headers

FD = TEST_USERS["front_desk_headers"]
TECH = TEST_USERS["technician_headers"]
MGR = TEST_USERS["manager_headers"]


def _ok(resp, what: str):
    data = get_success_data(resp)
    if not isinstance(data, dict) or "id" not in data:
        raise AssertionError(f"Setup failed ({what}): {resp.status_code} {resp.text}")
    return data


# ---------------------------------------------------------------- primitives
def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, MGR)
    if resp.status_code // 100 != 2:
        raise AssertionError(f"Setup failed (set clock {to_iso8601}): {resp.status_code} {resp.text}")


def make_customer(**overrides) -> dict:
    return _ok(api_client.create_customer(create_customer_payload(**overrides), FD), "create customer")


def make_junior_customer(**overrides) -> dict:
    """Junior eligible for the season-lease program at the default season start."""
    defaults = {
        "date_of_birth": "2014-06-01",
        "height_cm": 140,
        "weight_kg": 40,
        "boot_sole_mm": 260,
        "skier_type": "TYPE_1",
    }
    defaults.update(overrides)
    return make_customer(**defaults)


def make_guardian_customer(**overrides) -> dict:
    defaults = {
        "date_of_birth": "1980-03-10",
        "height_cm": 182,
        "weight_kg": 84,
        "boot_sole_mm": 305,
        "skier_type": "TYPE_2",
    }
    defaults.update(overrides)
    return make_customer(**defaults)


def make_equipment_item(**overrides) -> dict:
    return _ok(api_client.create_equipment_item(create_equipment_item_payload(**overrides), MGR), "create equipment item")


def make_junior_equipment_item(**overrides) -> dict:
    defaults = {
        "gear_type": "SKI",
        "tier": "JUNIOR",
        "din_min": 1,
        "din_max": 6,
        "purchase_price_cents": 30000,
        "base_daily_rate_cents": 2500,
    }
    defaults.update(overrides)
    return make_equipment_item(**defaults)


def make_demo_equipment_item(**overrides) -> dict:
    defaults = {
        "gear_type": "SNOWBOARD",
        "tier": "DEMO",
        "purchase_price_cents": 50000,
        "base_daily_rate_cents": 5000,
    }
    defaults.update(overrides)
    return make_equipment_item(**defaults)


def declare_capacity(service_date: str, base_labor_minutes: int = 480, rush_reserved_minutes: int = 120) -> dict:
    return _ok(
        api_client.create_shop_day_capacity(
            create_shop_day_capacity_payload(
                service_date=service_date,
                base_labor_minutes=base_labor_minutes,
                rush_reserved_minutes=rush_reserved_minutes,
            ),
            MGR,
        ),
        "declare shop-day capacity",
    )


# ---------------------------------------------------------------- rentals
def make_reservation(customer: dict, start_date="2026-12-10", end_date="2026-12-12",
                     pickup_method="SHOP", actor_headers=None) -> dict:
    """Create a DRAFT/UNPAID reservation. Defaults to the owning customer as actor."""
    headers = actor_headers or make_customer_headers(customer["id"])
    return _ok(
        api_client.create_reservation(
            create_reservation_payload(customer["id"], start_date=start_date,
                                       end_date=end_date, pickup_method=pickup_method),
            headers,
        ),
        "create reservation",
    )


def add_item(reservation: dict, gear_type="SKI", tier="STANDARD", actor_headers=None) -> dict:
    headers = actor_headers or make_customer_headers(reservation["customer_id"])
    return _ok(
        api_client.add_reservation_item(
            reservation["id"],
            create_reservation_item_payload(gear_type_requested=gear_type, tier_requested=tier),
            headers,
        ),
        "add reservation item",
    )


def assign_item(item: dict, preferred_equipment_item_id: str = None) -> dict:
    payload = {}
    if preferred_equipment_item_id is not None:
        payload["preferred_equipment_item_id"] = preferred_equipment_item_id
    return _ok(api_client.assign_reservation_item(item["id"], payload, FD), "assign reservation item")


def setup_assigned_reservation(start_date="2026-12-10", end_date="2026-12-12",
                               rate=4000, price=60000, num_units=1,
                               customer_overrides=None, equipment_overrides=None,
                               pickup_method="SHOP") -> dict:
    """Customer + num_units units + reservation with num_units items, each ASSIGNED
    to its own unit. Returns a context dict."""
    customer = make_customer(**(customer_overrides or {}))
    units = [
        make_equipment_item(base_daily_rate_cents=rate, purchase_price_cents=price,
                            **(equipment_overrides or {}))
        for _ in range(num_units)
    ]
    reservation = make_reservation(customer, start_date=start_date, end_date=end_date,
                                   pickup_method=pickup_method)
    items = []
    for unit in units:
        item = add_item(reservation)
        items.append(assign_item(item, preferred_equipment_item_id=unit["id"]))
    return {"customer": customer, "units": units, "reservation": reservation, "items": items}


def confirm(reservation: dict, deposit_authorized_cents: int, actor_headers=None) -> dict:
    headers = actor_headers or make_customer_headers(reservation["customer_id"])
    return _ok(
        api_client.confirm_reservation(reservation["id"],
                                       {"deposit_authorized_cents": deposit_authorized_cents},
                                       headers),
        "confirm reservation",
    )


def setup_confirmed_reservation(deposit_authorized_cents=2400, **kwargs) -> dict:
    ctx = setup_assigned_reservation(**kwargs)
    ctx["reservation"] = confirm(ctx["reservation"], deposit_authorized_cents)
    return ctx


def setup_picked_up_reservation(pickup_instant="2026-12-10T09:00:00Z", **kwargs) -> dict:
    ctx = setup_confirmed_reservation(**kwargs)
    set_clock(pickup_instant)
    ctx["reservation"] = _ok(api_client.pickup_reservation(ctx["reservation"]["id"], FD),
                             "pickup reservation")
    return ctx


def setup_returned_reservation(return_instant="2026-12-12T17:00:00Z",
                               pickup_instant="2026-12-10T09:00:00Z", **kwargs) -> dict:
    """Full rental cycle through RETURNED/CAPTURED; units land in AWAITING_INSPECTION."""
    ctx = setup_picked_up_reservation(pickup_instant=pickup_instant, **kwargs)
    set_clock(return_instant)
    ctx["reservation"] = _ok(api_client.return_reservation(ctx["reservation"]["id"], FD),
                             "return reservation")
    return ctx


# ---------------------------------------------------------------- tune tickets
def make_tune_ticket(customer: dict, services=("WAX",), rush=False, actor_headers=None,
                     **overrides) -> dict:
    headers = actor_headers or make_customer_headers(customer["id"])
    return _ok(
        api_client.create_tune_ticket(
            create_tune_ticket_payload(customer["id"], services=list(services), rush=rush, **overrides),
            headers,
        ),
        "create tune ticket",
    )


def quote_ticket(ticket: dict, parts_surcharge_cents=0) -> dict:
    return _ok(
        api_client.quote_tune_ticket(ticket["id"], {"parts_surcharge_cents": parts_surcharge_cents}, TECH),
        "quote tune ticket",
    )


def approve_ticket(ticket: dict, customer: dict, expected_version: int = None) -> dict:
    version = expected_version if expected_version is not None else ticket["version"]
    return _ok(
        api_client.approve_tune_ticket(
            ticket["id"], {"expected_tune_ticket_version": version},
            make_customer_headers(customer["id"]),
        ),
        "approve tune ticket",
    )


def setup_approved_ticket(services=("WAX",), rush=False, service_date="2026-12-01",
                          base_labor_minutes=480, rush_reserved_minutes=120,
                          clock_instant="2026-12-01T09:00:00Z",
                          parts_surcharge_cents=0, customer=None) -> dict:
    """Capacity row + customer + ticket driven INTAKE -> QUOTED -> APPROVED."""
    set_clock(clock_instant)
    capacity = declare_capacity(service_date, base_labor_minutes, rush_reserved_minutes)
    customer = customer or make_customer()
    ticket = make_tune_ticket(customer, services=services, rush=rush)
    ticket = quote_ticket(ticket, parts_surcharge_cents=parts_surcharge_cents)
    ticket = approve_ticket(ticket, customer)
    return {"customer": customer, "ticket": ticket, "capacity": capacity}


def setup_ticket_in_quality_check(**kwargs) -> dict:
    ctx = setup_approved_ticket(**kwargs)
    ticket = _ok(api_client.start_tune_ticket(ctx["ticket"]["id"], TECH), "start tune ticket")
    ticket = _ok(api_client.complete_tune_ticket(ticket["id"], TECH), "complete tune ticket")
    ctx["ticket"] = ticket
    return ctx


# ---------------------------------------------------------------- season leases
def make_season_lease(junior: dict, guardian: dict, **overrides) -> dict:
    return _ok(
        api_client.create_season_lease(
            create_season_lease_payload(junior["id"], guardian["id"], **overrides), FD),
        "create season lease",
    )


def setup_active_lease(season_start_date="2026-11-01", season_end_date="2027-03-31",
                       activation_instant="2026-11-01T08:00:00Z",
                       junior_overrides=None, package_tier="JUNIOR_SKI",
                       unit_overrides=None) -> dict:
    """Junior + guardian + JUNIOR unit + lease activated (unit OUT)."""
    set_clock(activation_instant)
    junior = make_junior_customer(**(junior_overrides or {}))
    guardian = make_guardian_customer()
    unit = make_junior_equipment_item(**(unit_overrides or {}))
    lease = make_season_lease(junior, guardian, season_start_date=season_start_date,
                              season_end_date=season_end_date, package_tier=package_tier)
    lease = _ok(
        api_client.activate_season_lease(lease["id"], {"equipment_item_id": unit["id"]}, FD),
        "activate season lease",
    )
    return {"junior": junior, "guardian": guardian, "unit": unit, "lease": lease}


# ---------------------------------------------------------------- damage chain
def make_damage_assessment(reservation: dict, equipment_item: dict, severity="COSMETIC",
                           **overrides) -> dict:
    return _ok(
        api_client.create_damage_assessment(
            create_damage_assessment_payload(reservation["id"], equipment_item["id"],
                                             severity=severity, **overrides),
            TECH,
        ),
        "create damage assessment",
    )


def setup_suspended_lease_via_total_loss() -> dict:
    """Active junior lease; the junior's separate on-time rental comes back with a
    TOTAL_LOSS invoice, which captures the deposit, bars the customer, and suspends
    the lease in one cascade."""
    ctx = setup_active_lease()
    rental_unit = make_equipment_item()
    junior = ctx["junior"]
    reservation = make_reservation(junior, start_date="2026-12-10", end_date="2026-12-12",
                                   actor_headers=FD)
    item = add_item(reservation, actor_headers=FD)
    assign_item(item)
    confirm(reservation, 2400, actor_headers=FD)
    set_clock("2026-12-10T09:00:00Z")
    _ok(api_client.pickup_reservation(reservation["id"], FD), "pickup rental")
    set_clock("2026-12-12T17:00:00Z")
    reservation = _ok(api_client.return_reservation(reservation["id"], FD), "return rental")
    assessment = make_damage_assessment(reservation, rental_unit, severity="TOTAL_LOSS")
    assessment = _ok(api_client.invoice_damage_assessment(assessment["id"], FD), "invoice assessment")
    ctx.update({"rental_unit": rental_unit, "reservation": reservation,
                "assessment": assessment})
    return ctx


# ---------------------------------------------------------------- demo & purchase
def make_demo_credit(customer: dict, unit: dict, **overrides) -> dict:
    return _ok(
        api_client.create_demo_credit(
            create_demo_credit_payload(customer["id"], unit["id"], **overrides), FD),
        "create demo credit",
    )


# ---------------------------------------------------------------- slope-side pickup
def make_pickup_window(**overrides) -> dict:
    return _ok(api_client.create_pickup_window(create_pickup_window_payload(**overrides), MGR),
               "create pickup window")


def make_pickup_booking(window: dict, reservation: dict, actor_headers=None) -> dict:
    headers = actor_headers or make_customer_headers(reservation["customer_id"])
    return _ok(
        api_client.create_pickup_booking(
            create_pickup_booking_payload(window["id"], reservation["id"]), headers),
        "create pickup booking",
    )


def setup_confirmed_slope_side_reservation(start_date="2026-12-20", end_date="2026-12-21",
                                           deposit_authorized_cents=1600) -> dict:
    ctx = setup_assigned_reservation(start_date=start_date, end_date=end_date,
                                     pickup_method="SLOPE_SIDE")
    ctx["reservation"] = confirm(ctx["reservation"], deposit_authorized_cents)
    return ctx
