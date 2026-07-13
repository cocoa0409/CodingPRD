"""Composite setup helpers.

Every test runs against a freshly restarted, empty server, so each fixture builds
all of its preconditions from scratch using only PRD-declared endpoints. Setup
calls use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion failure downstream.

Each fixture takes the ApiClient as its first argument and returns a dict of the
ids it created so tests can drive the trigger and assert against fresh GETs.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_terminal_payload, create_chassis_payload, create_driver_payload,
    create_booking_payload, create_appointment_payload, create_leg_payload,
    create_invoice_payload, create_accessorial_payload,
)
from .test_users import TEST_USERS

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLER = TEST_USERS["biller_headers"]


# --- Primitive creators ---------------------------------------------------

def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, DISPATCHER))


def mk_terminal(api, **overrides):
    return get_success_data(api.create_terminal(create_terminal_payload(**overrides), DISPATCHER))


def mk_chassis(api, **overrides):
    return get_success_data(api.create_chassis(create_chassis_payload(**overrides), DISPATCHER))


def mk_driver(api, **overrides):
    return get_success_data(api.create_driver(create_driver_payload(**overrides), DISPATCHER))


def mk_booking(api, terminal_id, **overrides):
    return get_success_data(api.create_booking(create_booking_payload(terminal_id, **overrides), DISPATCHER))


def mk_confirmed_booking(api, terminal_id, **overrides):
    """Create a booking then confirm it. Returns (booking_dict, confirmed_dict)."""
    booking = mk_booking(api, terminal_id, **overrides)
    confirmed = get_success_data(api.confirm_booking(booking["id"], DISPATCHER))
    return booking, confirmed


def mk_chassis_assigned_booking(api, terminal_id, chassis_id, **overrides):
    """Booking driven to CHASSIS_ASSIGNED with the given chassis. Returns booking dict after assign."""
    _, confirmed = mk_confirmed_booking(api, terminal_id, **overrides)
    assigned = get_success_data(
        api.assign_chassis(
            confirmed["id"],
            {"chassis_id": chassis_id, "expected_booking_version": confirmed["version"]},
            DISPATCHER,
        )
    )
    return assigned


# --- State-progression composites ----------------------------------------

def setup_pickup_ready(
    api,
    *,
    clock="2026-05-06T00:00:00Z",
    demurrage_daily_rate_cents=12500,
    per_diem_rate_cents=8500,
    free_days=4,
    last_free_day="2026-06-30T00:00:00Z",
    linehaul_base_cents=45000,
    container_number="MSCU100",
    driver_status="ACTIVE",
    appt_start="2026-05-06T06:00:00Z",
    appt_end="2026-05-20T23:59:59Z",
    leg_start="2026-05-06T08:00:00Z",
    leg_end="2026-05-06T12:00:00Z",
    slot_capacity_per_window=None,
):
    """Terminal + chassis + driver + booking driven to APPOINTED, with a PLANNED
    PICKUP leg linked to the pickup appointment. This is the state immediately
    before dispatch. Returns ctx dict."""
    if clock is not None:
        set_clock(api, clock)
    term_over = {"demurrage_daily_rate_cents": demurrage_daily_rate_cents}
    if slot_capacity_per_window is not None:
        term_over["slot_capacity_per_window"] = slot_capacity_per_window
    terminal = mk_terminal(api, **term_over)
    chassis = mk_chassis(api, per_diem_rate_cents=per_diem_rate_cents, free_days=free_days)
    driver = mk_driver(api, status=driver_status)
    assigned = mk_chassis_assigned_booking(
        api, terminal["id"], chassis["id"],
        container_number=container_number, last_free_day=last_free_day,
        linehaul_base_cents=linehaul_base_cents,
    )
    appt = get_success_data(api.create_appointment(
        create_appointment_payload(assigned["id"], terminal["id"], "PICKUP", appt_start, appt_end),
        DISPATCHER,
    ))
    leg = get_success_data(api.create_leg(
        create_leg_payload(assigned["id"], driver["id"], "PICKUP", leg_start, leg_end,
                           appointment_id=appt["id"]),
        DISPATCHER,
    ))
    return {
        "terminal_id": terminal["id"],
        "chassis_id": chassis["id"],
        "driver_id": driver["id"],
        "booking_id": assigned["id"],
        "appointment_id": appt["id"],
        "leg_id": leg["id"],
    }


def setup_dispatched_pickup(api, *, dispatch_clock=None, **kwargs):
    """setup_pickup_ready + dispatch the pickup leg (booking -> DISPATCHED, chassis OUT).
    If dispatch_clock is given, the clock is set to it just before dispatch (drives
    actual_pickup_at / demurrage_actual and assigned_out_at)."""
    ctx = setup_pickup_ready(api, **kwargs)
    if dispatch_clock is not None:
        set_clock(api, dispatch_clock)
    get_success_data(api.dispatch_leg(ctx["leg_id"], DISPATCHER))
    return ctx


def setup_delivered_booking(api, *, dispatch_clock=None, **kwargs):
    """Drive a booking all the way to DELIVERED (pickup dispatched then completed)."""
    ctx = setup_dispatched_pickup(api, dispatch_clock=dispatch_clock, **kwargs)
    get_success_data(api.complete_leg(ctx["leg_id"], DISPATCHER))
    return ctx


def setup_empty_returned(api, *, dispatch_clock=None, return_clock=None,
                         return_start="2026-05-24T08:00:00Z",
                         return_end="2026-05-24T12:00:00Z", **kwargs):
    """Drive a booking to EMPTY_RETURNED via a RETURN leg (dispatched then completed).
    return_clock sets the clock before creating/dispatching/completing the return leg
    (drives returned_at / final per-diem). Returns ctx with return_leg_id added."""
    ctx = setup_delivered_booking(api, dispatch_clock=dispatch_clock, **kwargs)
    if return_clock is not None:
        set_clock(api, return_clock)
    ret_leg = get_success_data(api.create_leg(
        create_leg_payload(ctx["booking_id"], ctx["driver_id"], "RETURN", return_start, return_end),
        DISPATCHER,
    ))
    get_success_data(api.dispatch_leg(ret_leg["id"], DISPATCHER))
    get_success_data(api.complete_leg(ret_leg["id"], DISPATCHER))
    ctx["return_leg_id"] = ret_leg["id"]
    return ctx


def setup_invoiced_booking(api, *, accessorials=None, dispatch_clock=None, **kwargs):
    """DELIVERED booking with a generated DRAFT invoice. `accessorials` is a list of
    (kind, amount_cents) added in order. Returns ctx with invoice_id + accessorial_ids."""
    ctx = setup_delivered_booking(api, dispatch_clock=dispatch_clock, **kwargs)
    invoice = get_success_data(api.create_invoice(create_invoice_payload(ctx["booking_id"]), BILLER))
    ctx["invoice_id"] = invoice["id"]
    ctx["accessorial_ids"] = []
    for kind, amount in (accessorials or []):
        acc = get_success_data(api.add_accessorial(
            invoice["id"], create_accessorial_payload(kind=kind, amount_cents=amount), BILLER,
        ))
        ctx["accessorial_ids"].append(acc["id"])
    return ctx
