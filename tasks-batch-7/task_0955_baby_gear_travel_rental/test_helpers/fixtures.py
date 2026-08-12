"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls use
the lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors.

Identity threading: ownership-gated calls always use
make_customer_headers(customer["id"]) / make_hotel_partner_headers(...) with
the actual entity id, never the shared opaque constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_catalog_item_payload,
    create_cleaning_ticket_payload,
    create_customer_payload,
    create_damage_claim_payload,
    create_hotel_partner_payload,
    create_insurance_plan_payload,
    create_recall_payload,
    create_reservation_payload,
    create_route_payload,
    create_stop_payload,
    create_unit_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_inspector_headers,
    make_ops_headers,
)

DEFAULT_START = TEST_DEFAULTS["START_DATE"]          # "2026-06-10"
DEFAULT_END = TEST_DEFAULTS["END_DATE"]              # "2026-06-13"
DEFAULT_ZONE = TEST_DEFAULTS["ZONE"]                 # "Z1"
DEFAULT_ADDRESS = "1 Main St"


def _ops():
    return TEST_USERS["ops_admin_headers"]


# ----------------------------------------------------------------- builders
def create_customer(**overrides) -> dict:
    """Register a customer (Anonymous). Returns the Customer."""
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(**overrides), TEST_USERS["anonymous_headers"]
        )
    )


def create_catalog_item(**overrides) -> dict:
    """Create a catalog item (OperationsAdmin). Returns the CatalogItem."""
    return get_success_data(
        api_client.create_catalog_item(create_catalog_item_payload(**overrides), _ops())
    )


def create_unit(catalog_item_id: str, **overrides) -> dict:
    """Register a physical unit (OperationsAdmin). Returns the InventoryUnit."""
    return get_success_data(
        api_client.create_inventory_unit(
            create_unit_payload(catalog_item_id, **overrides), _ops()
        )
    )


def create_route(**overrides) -> dict:
    """Create a PLANNED delivery route (OperationsAdmin)."""
    return get_success_data(
        api_client.create_route(create_route_payload(**overrides), _ops())
    )


def create_hotel_partner(**overrides) -> dict:
    """Onboard a hotel partner (OperationsAdmin). Returns the HotelPartner."""
    return get_success_data(
        api_client.create_hotel_partner(
            create_hotel_partner_payload(**overrides), _ops()
        )
    )


def create_insurance_plan(**overrides) -> dict:
    """Create an insurance plan (OperationsAdmin). Returns the InsurancePlan."""
    return get_success_data(
        api_client.create_insurance_plan(
            create_insurance_plan_payload(**overrides), _ops()
        )
    )


def create_quoted_reservation(customer_id: str, lines, **overrides) -> dict:
    """Create a QUOTED reservation owned by the given customer."""
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(lines=lines, **overrides),
            make_customer_headers(customer_id),
        )
    )


def confirm_reservation(reservation_id: str, customer_id: str) -> dict:
    """Confirm a QUOTED reservation as its owning customer. Returns CONFIRMED."""
    return get_success_data(
        api_client.confirm_reservation(
            reservation_id, make_customer_headers(customer_id)
        )
    )


def get_reservation(reservation_id: str) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, _ops()))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_inventory_unit(unit_id, _ops()))


def get_customer_by_id(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, _ops()))


def get_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, _ops()))


def get_route_stop(stop_id: str) -> dict:
    return get_success_data(api_client.get_route_stop(stop_id, _ops()))


def get_line(line_id: str) -> dict:
    return get_success_data(api_client.get_reservation_line(line_id, _ops()))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_damage_claim(claim_id, _ops()))


def get_extension(extension_id: str) -> dict:
    return get_success_data(api_client.get_extension(extension_id, _ops()))


def list_lines(reservation_id: str) -> list:
    """All lines of a reservation, created_at ascending."""
    return get_success_data(
        api_client.list_reservation_lines(
            _ops(), params={"reservation_id": reservation_id}
        )
    )


def list_unit_tickets(unit_id: str) -> list:
    """All cleaning tickets of a unit, created_at ascending."""
    return get_success_data(api_client.list_unit_cleaning_tickets(unit_id, _ops()))


def list_deposit_transactions(reservation_id: str) -> list:
    """Ledger entries for a reservation, created_at ascending."""
    return get_success_data(
        api_client.list_deposit_transactions(reservation_id, _ops())
    )


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (OperationsAdmin)."""
    return get_success_data(api_client.set_current_utc(to_iso8601, _ops()))


def get_availability(catalog_item_id: str, start_date: str, end_date: str) -> int:
    """Forward-looking available_count over [start_date, end_date)."""
    data = get_success_data(
        api_client.get_catalog_availability(
            catalog_item_id, start_date, end_date, _ops()
        )
    )
    return data["available_count"]


def get_reservation_version(reservation_id: str) -> int:
    return get_reservation(reservation_id)["version"]


# ------------------------------------------- Tier 1/2: composite entity setup
def setup_confirmed_reservation(
    num_lines: int = 1,
    rate_cents: int = TEST_DEFAULTS["DAILY_RATE_CENTS"],
    deposit_cents: int = TEST_DEFAULTS["DEPOSIT_AMOUNT_CENTS"],
    weight_kg: float = TEST_DEFAULTS["WEIGHT_KG"],
    turnaround_hours: int = TEST_DEFAULTS["CLEANING_TURNAROUND_HOURS"],
    deep_every: int = TEST_DEFAULTS["DEEP_CLEAN_EVERY_CYCLES"],
    grade: str = "A",
    start_date: str = DEFAULT_START,
    end_date: str = DEFAULT_END,
    zone_code: str = DEFAULT_ZONE,
    address: str = DEFAULT_ADDRESS,
    insurance_plan_id=None,
    hotel_partner_id=None,
    customer_overrides=None,
    catalog_overrides=None,
) -> dict:
    """Customer + catalog item + N units + reservation, confirmed.

    Returns a context dict: {"customer", "catalog", "units", "reservation"}
    where reservation is the CONFIRMED representation.
    """
    customer = create_customer(**(customer_overrides or {}))
    catalog_kwargs = {
        "daily_rate_cents": rate_cents,
        "deposit_amount_cents": deposit_cents,
        "weight_kg": weight_kg,
        "cleaning_turnaround_hours": turnaround_hours,
        "deep_clean_every_cycles": deep_every,
    }
    catalog_kwargs.update(catalog_overrides or {})
    catalog = create_catalog_item(**catalog_kwargs)
    units = [
        create_unit(catalog["id"], condition_grade=grade) for _ in range(num_lines)
    ]
    reservation = create_quoted_reservation(
        customer["id"],
        lines=[{"catalog_item_id": catalog["id"]} for _ in range(num_lines)],
        delivery_address=address,
        zone_code=zone_code,
        start_date=start_date,
        end_date=end_date,
        insurance_plan_id=insurance_plan_id,
        hotel_partner_id=hotel_partner_id,
    )
    confirmed = confirm_reservation(reservation["id"], customer["id"])
    return {
        "customer": customer,
        "catalog": catalog,
        "units": units,
        "reservation": confirmed,
    }


# ------------------------------- Tier 3: delivery / pickup lifecycle shortcuts
def run_route_stop(
    reservation: dict,
    stop_type: str,
    route_date: str,
    window_start: str,
    window_end: str,
    clock: str,
    vehicle_capacity_kg: float = TEST_DEFAULTS["VEHICLE_CAPACITY_KG"],
) -> dict:
    """Create route + stop, dispatch, set the clock, complete the stop.

    Returns {"route": ..., "stop": <completed stop>}.
    """
    route = get_success_data(
        api_client.create_route(
            create_route_payload(
                route_date=route_date,
                zone_code=reservation["zone_code"],
                vehicle_capacity_kg=vehicle_capacity_kg,
            ),
            _ops(),
        )
    )
    stop = get_success_data(
        api_client.add_route_stop(
            route["id"],
            create_stop_payload(
                reservation["id"],
                stop_type,
                address=reservation["delivery_address"],
                time_window_start=window_start,
                time_window_end=window_end,
            ),
            _ops(),
        )
    )
    get_success_data(api_client.dispatch_route(route["id"], _ops()))
    set_clock(clock)
    completed = get_success_data(api_client.complete_route_stop(stop["id"], _ops()))
    return {"route": route, "stop": completed}


def deliver_reservation(
    reservation: dict,
    clock: str = "2026-06-10T09:00:00Z",
    route_date: str = None,
    window: tuple = None,
    vehicle_capacity_kg: float = TEST_DEFAULTS["VEHICLE_CAPACITY_KG"],
) -> dict:
    """Complete a DELIVERY_SETUP stop: reservation CONFIRMED -> DELIVERED."""
    route_date = route_date or reservation["start_date"]
    window = window or (f"{route_date}T08:00:00Z", f"{route_date}T10:00:00Z")
    result = run_route_stop(
        reservation,
        "DELIVERY_SETUP",
        route_date,
        window[0],
        window[1],
        clock,
        vehicle_capacity_kg=vehicle_capacity_kg,
    )
    result["reservation"] = get_reservation(reservation["id"])
    return result


def pickup_reservation(
    reservation: dict,
    clock: str,
    route_date: str = None,
    window: tuple = None,
    vehicle_capacity_kg: float = TEST_DEFAULTS["VEHICLE_CAPACITY_KG"],
) -> dict:
    """Complete a PICKUP stop: reservation DELIVERED -> RETURNED.

    The reservation must already be DELIVERED. clock is the pickup instant
    (stamped as returned_at).
    """
    route_date = route_date or reservation["end_date"]
    window = window or (f"{route_date}T00:00:00Z", f"{route_date}T06:00:00Z")
    result = run_route_stop(
        reservation,
        "PICKUP",
        route_date,
        window[0],
        window[1],
        clock,
        vehicle_capacity_kg=vehicle_capacity_kg,
    )
    result["reservation"] = get_reservation(reservation["id"])
    return result


def setup_delivered_reservation(
    delivery_clock: str = "2026-06-10T09:00:00Z", **kwargs
) -> dict:
    """Confirmed reservation walked through DELIVERY_SETUP completion.

    Returns setup_confirmed_reservation's ctx plus "delivery" and a refreshed
    "reservation" (DELIVERED) and "lines".
    """
    ctx = setup_confirmed_reservation(**kwargs)
    delivery = deliver_reservation(ctx["reservation"], clock=delivery_clock)
    ctx["delivery"] = delivery
    ctx["reservation"] = delivery["reservation"]
    ctx["lines"] = list_lines(ctx["reservation"]["id"])
    return ctx


def setup_returned_reservation(
    pickup_clock: str = "2026-06-13T04:00:00Z",
    pickup_route_date: str = None,
    pickup_window: tuple = None,
    **kwargs,
) -> dict:
    """Delivered reservation walked through PICKUP completion.

    Returns setup_delivered_reservation's ctx plus "pickup" and a refreshed
    "reservation" (RETURNED) and "lines" (RETURNED).
    """
    ctx = setup_delivered_reservation(**kwargs)
    pickup = pickup_reservation(
        ctx["reservation"],
        clock=pickup_clock,
        route_date=pickup_route_date,
        window=pickup_window,
    )
    ctx["pickup"] = pickup
    ctx["reservation"] = pickup["reservation"]
    ctx["lines"] = list_lines(ctx["reservation"]["id"])
    return ctx


def setup_settled_reservation(**kwargs) -> dict:
    """Returned reservation settled by an OperationsAdmin."""
    ctx = setup_returned_reservation(**kwargs)
    settled = get_success_data(
        api_client.settle_reservation(ctx["reservation"]["id"], _ops())
    )
    ctx["reservation"] = settled
    return ctx


# ------------------------------------------------------ damage claim helpers
def file_damage_claim(
    line_id: str,
    severity: str = "MINOR",
    repair_cost_cents: int = 5000,
    description: str = "damage found on inspection",
    filer_headers=None,
) -> dict:
    """File a claim against a RETURNED line. Defaults to Inspector insp-1."""
    return get_success_data(
        api_client.create_damage_claim(
            create_damage_claim_payload(
                line_id,
                severity=severity,
                repair_cost_cents=repair_cost_cents,
                description=description,
            ),
            filer_headers or TEST_USERS["inspector_1_headers"],
        )
    )


def approve_claim(claim_id: str, reviewer_user_id: str = "ops-1") -> dict:
    """Approve a claim as an OperationsAdmin distinct from the filer."""
    return get_success_data(
        api_client.approve_damage_claim(
            claim_id, make_ops_headers(reviewer_user_id)
        )
    )


# --------------------------------------------------------- extension helpers
def create_extension(
    reservation_id: str, customer_id: str, requested_end_date: str
) -> dict:
    """Create an extension request with the reservation's current version."""
    version = get_reservation_version(reservation_id)
    return get_success_data(
        api_client.create_extension_request(
            reservation_id,
            {
                "requested_end_date": requested_end_date,
                "expected_reservation_version": version,
            },
            make_customer_headers(customer_id),
        )
    )


def approve_extension(extension_id: str) -> dict:
    return get_success_data(api_client.approve_extension(extension_id, _ops()))


# ------------------------------------------------------------- recall helper
def create_and_activate_recall(catalog_item_id: str, severity: str = "MANDATORY") -> dict:
    """Create a recall notice and activate it. Returns the ACTIVE recall."""
    recall = get_success_data(
        api_client.create_recall(
            create_recall_payload(catalog_item_id, severity=severity), _ops()
        )
    )
    return get_success_data(api_client.activate_recall(recall["id"], _ops()))


# ------------------------------------------------------ cleaning ticket helper
def open_manual_ticket(unit_id: str, ticket_type: str = "STANDARD", headers=None):
    """Manually open a cleaning ticket (raw response — may be an error)."""
    return api_client.create_cleaning_ticket(
        create_cleaning_ticket_payload(unit_id, ticket_type=ticket_type),
        headers or TEST_USERS["inspector_1_headers"],
    )
