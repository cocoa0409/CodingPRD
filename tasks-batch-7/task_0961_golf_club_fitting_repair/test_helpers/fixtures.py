"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database). Identity threading: any ownership- or
attribution-gated call uses headers built from the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload, create_staff_payload, create_bay_payload,
    create_lesson_package_payload, create_fitting_session_payload,
    create_component_item_payload, create_build_spec_payload,
    create_repair_ticket_payload, create_appraisal_payload,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_fitting_specialist_headers,
    make_repair_technician_headers, make_instructor_headers,
    make_shop_manager_headers,
)

ADMIN = TEST_USERS["shop_admin_headers"]

STAFF_ROLE_TO_HEADER = {
    "FITTING_SPECIALIST": make_fitting_specialist_headers,
    "REPAIR_TECHNICIAN": make_repair_technician_headers,
    "INSTRUCTOR": make_instructor_headers,
    "SHOP_MANAGER": make_shop_manager_headers,
}

DEFAULT_START = "2026-05-10T10:00:00Z"
DEFAULT_END = "2026-05-10T11:00:00Z"
DEFAULT_CLOCK = "2026-05-10T09:00:00Z"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_customer(full_name=None, email=None) -> dict:
    payload = create_customer_payload()
    if full_name is not None:
        payload["full_name"] = full_name
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_customer(payload, ADMIN))


def customer_headers(customer: dict) -> dict:
    return make_customer_headers(customer["id"])


def create_staff(staff_role="FITTING_SPECIALIST", full_name=None) -> dict:
    payload = create_staff_payload(staff_role)
    if full_name is not None:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_staff(payload, ADMIN))


def create_specialist() -> dict:
    return create_staff("FITTING_SPECIALIST", "Fred Fitter")


def create_technician() -> dict:
    return create_staff("REPAIR_TECHNICIAN", "Tina Tech")


def create_manager(full_name="Mary Manager") -> dict:
    return create_staff("SHOP_MANAGER", full_name)


def create_instructor() -> dict:
    return create_staff("INSTRUCTOR", "Ivy Instructor")


def staff_headers(staff: dict) -> dict:
    return STAFF_ROLE_TO_HEADER[staff["staff_role"]](staff["id"])


def create_bay(bay_name=None, cleanup_buffer_minutes=None) -> dict:
    payload = create_bay_payload()
    if bay_name is not None:
        payload["bay_name"] = bay_name
    if cleanup_buffer_minutes is not None:
        payload["cleanup_buffer_minutes"] = cleanup_buffer_minutes
    return get_success_data(api_client.create_bay(payload, ADMIN))


def create_lesson_package(customer, total_credits=5, price_cents=50_000,
                          expires_at="2027-01-01T00:00:00Z") -> dict:
    manager = create_manager()
    payload = create_lesson_package_payload(
        customer["id"], total_credits=total_credits,
        price_cents=price_cents, expires_at=expires_at,
    )
    return get_success_data(
        api_client.create_lesson_package(payload, staff_headers(manager))
    )


def book_session(customer, bay, specialist, starts_at=DEFAULT_START, ends_at=DEFAULT_END,
                 lesson_package_id=None, by=None) -> dict:
    payload = create_fitting_session_payload(
        customer["id"], bay["id"], specialist["id"],
        starts_at=starts_at, ends_at=ends_at,
    )
    if lesson_package_id is not None:
        payload["lesson_package_id"] = lesson_package_id
    headers = by if by is not None else staff_headers(specialist)
    return get_success_data(api_client.create_fitting_session(payload, headers))


def create_component_item(component_type="HEAD", unit_cost_cents=40_000,
                          msrp_cents=55_000, initial_stock=5, sku=None) -> dict:
    payload = create_component_item_payload(
        component_type, unit_cost_cents=unit_cost_cents,
        msrp_cents=msrp_cents, initial_stock=initial_stock,
    )
    if sku is not None:
        payload["sku"] = sku
    return get_success_data(api_client.create_component_item(payload, ADMIN))


def create_component_trio(head_stock=5, shaft_stock=5, grip_stock=5,
                          head_unit=40_000, head_msrp=55_000,
                          shaft_unit=12_000, shaft_msrp=18_000,
                          grip_unit=800, grip_msrp=1_500) -> dict:
    return {
        "head": create_component_item("HEAD", head_unit, head_msrp, head_stock),
        "shaft": create_component_item("SHAFT", shaft_unit, shaft_msrp, shaft_stock),
        "grip": create_component_item("GRIP", grip_unit, grip_msrp, grip_stock),
    }


def get_component_item(item_id, headers=None) -> dict:
    return get_success_data(api_client.get_component_item(item_id, headers or ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: sessions and specs
# ---------------------------------------------------------------------------

def create_completed_session(customer=None, specialist=None, bay=None,
                             starts_at=DEFAULT_START, ends_at=DEFAULT_END) -> dict:
    """Customer + specialist + bay + a session walked BOOKED -> CHECKED_IN -> COMPLETED."""
    customer = customer or create_customer()
    specialist = specialist or create_specialist()
    bay = bay or create_bay()
    session = book_session(customer, bay, specialist, starts_at, ends_at)
    fs_headers = staff_headers(specialist)
    session = get_success_data(api_client.check_in_session(session["id"], fs_headers))
    session = get_success_data(api_client.complete_session(session["id"], fs_headers))
    return {"customer": customer, "specialist": specialist, "bay": bay, "session": session}


def create_draft_spec(customer, session, items, specialist, labor_cents=15_000) -> dict:
    payload = create_build_spec_payload(
        customer["id"], session["id"], items["head"]["id"],
        items["shaft"]["id"], items["grip"]["id"], labor_cents=labor_cents,
    )
    return get_success_data(
        api_client.create_build_spec(payload, staff_headers(specialist))
    )


def quote_spec(spec, specialist) -> dict:
    payload = {"expected_build_spec_version": spec["version"]}
    return get_success_data(
        api_client.quote_build_spec(spec["id"], payload, staff_headers(specialist))
    )


def approve_spec(spec, customer, payment_method="EXTERNAL") -> dict:
    return get_success_data(
        api_client.approve_build_spec(
            spec["id"], {"payment_method": payment_method}, customer_headers(customer)
        )
    )


def mark_ready(spec, technician) -> dict:
    return get_success_data(
        api_client.mark_ready_build_spec(spec["id"], staff_headers(technician))
    )


def deliver_spec(spec, staff) -> dict:
    return get_success_data(api_client.deliver_build_spec(spec["id"], staff_headers(staff)))


def get_spec(spec_id, headers=None) -> dict:
    return get_success_data(api_client.get_build_spec(spec_id, headers or ADMIN))


def get_order_for_spec(spec_id, headers=None) -> dict:
    """Discover the cascade-created component order for a spec via the list endpoint."""
    manager = create_manager()
    h = headers or staff_headers(manager)
    data = get_success_data(
        api_client.list_component_orders(h, params={"build_spec_id": spec_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one component order for spec {spec_id}, got {data}"
    )
    return data[0]


def list_orders_for_spec_raw(spec_id, headers):
    return api_client.list_component_orders(headers, params={"build_spec_id": spec_id})


# ---------------------------------------------------------------------------
# Tier 3: full build lifecycle
# ---------------------------------------------------------------------------

def setup_quoted_spec(complete_session=True, labor_cents=15_000, trio_overrides=None,
                      clock=DEFAULT_CLOCK, customer=None) -> dict:
    """Customer + COMPLETED session + component trio + spec walked to QUOTED."""
    if clock is not None:
        set_clock(clock)
    customer = customer or create_customer()
    specialist = create_specialist()
    technician = create_technician()
    bay = create_bay()
    if complete_session:
        ctx = create_completed_session(customer, specialist, bay)
    else:
        session = book_session(customer, bay, specialist)
        ctx = {"customer": customer, "specialist": specialist, "bay": bay, "session": session}
    items = create_component_trio(**(trio_overrides or {}))
    spec = create_draft_spec(customer, ctx["session"], items, specialist,
                             labor_cents=labor_cents)
    spec = quote_spec(spec, specialist)
    return {
        "customer": customer, "specialist": specialist, "technician": technician,
        "bay": bay, "session": ctx["session"], "items": items, "spec": spec,
    }


def setup_delivered_spec(clock=DEFAULT_CLOCK, deliver_clock="2026-05-10T12:00:00Z") -> dict:
    """Full build lifecycle through DELIVERED.

    Component costs 5000/3000/800 with labor 1000 and a COMPLETED session give
    final_price_cents == 2300 (8800 + 1000 - 7500 rebate).
    """
    ctx = setup_quoted_spec(
        complete_session=True, labor_cents=1_000, clock=clock,
        trio_overrides={
            "head_stock": 1, "shaft_stock": 1, "grip_stock": 1,
            "head_unit": 5_000, "head_msrp": 7_000,
            "shaft_unit": 3_000, "shaft_msrp": 4_000,
            "grip_unit": 800, "grip_msrp": 1_000,
        },
    )
    spec = approve_spec(ctx["spec"], ctx["customer"])
    assert spec["status"] == "IN_BUILD", f"setup: expected IN_BUILD, got {spec['status']}"
    spec = mark_ready(spec, ctx["technician"])
    if deliver_clock is not None:
        set_clock(deliver_clock)
    spec = deliver_spec(spec, ctx["specialist"])
    ctx["spec"] = spec
    return ctx


# ---------------------------------------------------------------------------
# Repair tickets
# ---------------------------------------------------------------------------

def create_repair_ticket(customer, service_type="REGRIP", rush=None,
                         shaft_item=None, club_description="wedge", by=None) -> dict:
    payload = create_repair_ticket_payload(
        customer["id"], club_description=club_description, service_type=service_type,
    )
    if rush is not None:
        payload["rush"] = rush
    if shaft_item is not None:
        payload["shaft_item_id"] = shaft_item["id"]
    headers = by if by is not None else customer_headers(customer)
    return get_success_data(api_client.create_repair_ticket(payload, headers))


def get_ticket(ticket_id, headers) -> dict:
    return get_success_data(api_client.get_repair_ticket(ticket_id, headers))


def pay_ticket(ticket, customer, kind, method="EXTERNAL") -> dict:
    return get_success_data(
        api_client.pay_ticket(ticket["id"], {"kind": kind, "method": method},
                              customer_headers(customer))
    )


def setup_in_progress_ticket(service_type="REGRIP", rush=False, shaft_item=None,
                             shaft_stock=1, clock=DEFAULT_CLOCK) -> dict:
    """Ticket walked to IN_PROGRESS (approve -> deposit -> start-work)."""
    if clock is not None:
        set_clock(clock)
    customer = create_customer()
    technician = create_technician()
    if service_type == "RESHAFT" and shaft_item is None:
        shaft_item = create_component_item("SHAFT", 12_000, 18_000, shaft_stock)
    ticket = create_repair_ticket(customer, service_type, rush, shaft_item,
                                  club_description="driver" if service_type == "RESHAFT" else "wedge")
    ticket = get_success_data(
        api_client.approve_repair_ticket(ticket["id"], customer_headers(customer))
    )
    ticket = pay_ticket(ticket, customer, "DEPOSIT")
    ticket = get_success_data(
        api_client.start_work(ticket["id"], staff_headers(technician))
    )
    return {"customer": customer, "technician": technician,
            "ticket": ticket, "shaft_item": shaft_item}


def setup_picked_up_ticket(clock=DEFAULT_CLOCK) -> dict:
    """Ticket walked all the way to PICKED_UP (deposit, work, QC pass, balance, pickup)."""
    ctx = setup_in_progress_ticket("REGRIP", False, clock=clock)
    customer, technician, ticket = ctx["customer"], ctx["technician"], ctx["ticket"]
    ticket = get_success_data(
        api_client.submit_qc(ticket["id"], {"passed": True}, staff_headers(technician))
    )
    ticket = pay_ticket(ticket, customer, "BALANCE")
    ticket = get_success_data(
        api_client.pickup_ticket(ticket["id"], customer_headers(customer))
    )
    ctx["ticket"] = ticket
    return ctx


# ---------------------------------------------------------------------------
# Trade-ins and listings
# ---------------------------------------------------------------------------

def submit_appraisal(customer, clubs) -> dict:
    payload = create_appraisal_payload(customer["id"], clubs)
    return get_success_data(
        api_client.create_appraisal(payload, customer_headers(customer))
    )


def issue_offer(appraisal, staff, basis="GRADE_MATRIX", market_comps_cents=None) -> dict:
    payload = {"basis": basis, "expected_appraisal_version": appraisal["version"]}
    if market_comps_cents is not None:
        payload["market_comps_cents"] = market_comps_cents
    return get_success_data(
        api_client.create_offer(appraisal["id"], payload, staff_headers(staff))
    )


def accept_appraisal(appraisal, customer) -> dict:
    return get_success_data(
        api_client.accept_appraisal(appraisal["id"], customer_headers(customer))
    )


def get_appraisal(appraisal_id, headers) -> dict:
    return get_success_data(api_client.get_appraisal(appraisal_id, headers))


def get_listing_for_appraisal(appraisal_id, headers=None) -> dict:
    manager = create_manager()
    h = headers or staff_headers(manager)
    data = get_success_data(
        api_client.list_listings(h, params={"appraisal_id": appraisal_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one listing for appraisal {appraisal_id}, got {data}"
    )
    return data[0]


def setup_accepted_appraisal(clubs=None, clock=DEFAULT_CLOCK) -> dict:
    """Customer + specialist + accepted appraisal. Returns ctx with appraisal."""
    if clock is not None:
        set_clock(clock)
    customer = create_customer()
    specialist = create_specialist()
    appraisal = submit_appraisal(customer, clubs or [{"club_type": "DRIVER", "condition_grade": "A"}])
    appraisal = issue_offer(appraisal, specialist)
    appraisal = accept_appraisal(appraisal, customer)
    return {"customer": customer, "specialist": specialist, "appraisal": appraisal}


# ---------------------------------------------------------------------------
# Store credit
# ---------------------------------------------------------------------------

def get_customer(customer_id, headers=None) -> dict:
    return get_success_data(api_client.get_customer(customer_id, headers or ADMIN))


def list_ledger(customer_id, headers=None) -> list:
    manager = create_manager()
    h = headers or staff_headers(manager)
    data = get_success_data(api_client.list_credit_ledger_entries(customer_id, h))
    assert isinstance(data, list), f"expected ledger list, got {data}"
    return data
