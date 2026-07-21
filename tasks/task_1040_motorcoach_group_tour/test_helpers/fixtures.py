"""Composite setup helpers.

Every helper builds its preconditions from scratch (the harness restarts the
server and resets the DB + logical clock before every test) using only
PRD-declared endpoints. Setup calls use the lenient get_success_data() validator
so a setup failure surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import TEST_USERS
from . import factories as f

OPS = TEST_USERS["ops_headers"]
SALES = TEST_USERS["sales_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ---------------------------------------------------------------------------
# Primitives — one API call each, returning the created/updated data payload.
# ---------------------------------------------------------------------------

def create_tour_product(**overrides) -> dict:
    return get_success_data(api.create_tour_product(f.create_tour_product_payload(**overrides), OPS))


def create_coach(**overrides) -> dict:
    return get_success_data(api.create_coach(f.create_coach_payload(**overrides), OPS))


def create_driver(**overrides) -> dict:
    return get_success_data(api.create_driver(f.create_driver_payload(**overrides), OPS))


def create_guide(**overrides) -> dict:
    return get_success_data(api.create_guide(f.create_guide_payload(**overrides), OPS))


def create_departure(tour_product_id, **overrides) -> dict:
    return get_success_data(
        api.create_departure(f.create_departure_payload(tour_product_id, **overrides), OPS)
    )


def publish_departure(departure_id) -> dict:
    return get_success_data(api.publish_departure(departure_id, OPS))


def create_hotel_block(departure_id, **overrides) -> dict:
    return get_success_data(
        api.create_hotel_block(f.create_hotel_block_payload(departure_id, **overrides), OPS)
    )


def create_booking(departure_id, **overrides) -> dict:
    return get_success_data(
        api.create_booking(f.create_booking_payload(departure_id, **overrides), SALES)
    )


def add_passenger(booking_id, **overrides) -> dict:
    return get_success_data(
        api.create_passenger(f.create_passenger_payload(booking_id, **overrides), SALES)
    )


def pay(booking_id, kind, amount_cents, **overrides) -> dict:
    return get_success_data(
        api.create_payment(f.create_payment_payload(booking_id, kind, amount_cents, **overrides), SALES)
    )


def confirm_booking(booking_id) -> dict:
    return get_success_data(api.confirm_booking(booking_id, SALES))


def get_departure(departure_id) -> dict:
    return get_success_data(api.get_departure(departure_id, OPS))


def current_version(departure_id) -> int:
    return get_departure(departure_id)["version"]


def assign_resource(departure_id, resource_kind, resource_id) -> dict:
    """Assign a coach/driver/guide, reading the departure's current version for OCC.

    resource_kind is one of "COACH", "DRIVER", "GUIDE".
    """
    version = current_version(departure_id)
    payload = {"resource_kind": resource_kind, "expected_departure_version": version}
    if resource_kind == "COACH":
        payload["coach_id"] = resource_id
    elif resource_kind == "DRIVER":
        payload["driver_id"] = resource_id
    elif resource_kind == "GUIDE":
        payload["guide_id"] = resource_id
    return get_success_data(api.assign_departure(departure_id, payload, OPS))


def first_voucher_id(booking_id) -> str:
    data, _ = _list(api.list_vouchers(SALES, params={"booking_id": booking_id}))
    return data[0]["id"]


def voucher_ids(booking_id) -> list:
    data, _ = _list(api.list_vouchers(SALES, params={"booking_id": booking_id}))
    return [v["id"] for v in data]


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Composite: an OPEN departure staffed with the requested crew.
# ---------------------------------------------------------------------------

def setup_open_departure(coach=True, driver=False, guide=False,
                         seat_capacity=10, guaranteed_min_pax=5,
                         start_date="2026-08-01", end_date="2026-08-03",
                         base_price=100000, deposit=20000, duration_days=3,
                         drive_hours=6):
    """Create tour product + departure, publish (-> OPEN), and assign requested crew.

    Returns a dict with keys: tp, coach, driver, guide (ids where created), dep
    (the departure data after the last mutation).
    """
    tp = create_tour_product(base_price_per_person_cents=base_price,
                             deposit_per_person_cents=deposit,
                             duration_days=duration_days)
    dep = create_departure(tp["id"], start_date=start_date, end_date=end_date,
                           guaranteed_min_pax=guaranteed_min_pax,
                           itinerary_days=f.itinerary(drive_hours, service_date=start_date))
    dep = publish_departure(dep["id"])
    result = {"tp": tp, "dep": dep, "coach": None, "driver": None, "guide": None}
    if coach:
        c = create_coach(seat_capacity=seat_capacity)
        result["coach"] = c
        result["dep"] = assign_resource(dep["id"], "COACH", c["id"])
    if driver:
        d = create_driver()
        result["driver"] = d
        result["dep"] = assign_resource(dep["id"], "DRIVER", d["id"])
    if guide:
        g = create_guide()
        result["guide"] = g
        result["dep"] = assign_resource(dep["id"], "GUIDE", g["id"])
    return result


def add_confirmed_booking(departure_id, pax_count=2, rooms_requested=0,
                          insurance_opt_in=False, pay_full=False,
                          deposit_amount=None):
    """Create a booking, attach pax_count passengers, pay, and confirm it.

    Returns the confirmed booking data (re-fetched after confirm).
    """
    bk = create_booking(departure_id, pax_count=pax_count, rooms_requested=rooms_requested,
                        insurance_opt_in=insurance_opt_in)
    for i in range(pax_count):
        add_passenger(bk["id"], full_name=f"Pax {i + 1}", is_lead=(i == 0))
    if pay_full:
        pay(bk["id"], "DEPOSIT", bk["deposit_due_cents"])
        remainder = bk["booking_total_cents"] - bk["deposit_due_cents"]
        if remainder > 0:
            pay(bk["id"], "BALANCE", remainder)
    else:
        amount = deposit_amount if deposit_amount is not None else bk["deposit_due_cents"]
        pay(bk["id"], "DEPOSIT", amount)
    return confirm_booking(bk["id"])
