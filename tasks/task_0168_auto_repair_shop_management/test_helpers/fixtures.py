"""Composite setup helpers.

Each helper builds a multi-step precondition state from scratch using only
PRD-declared endpoints, so every test starts against an empty database. All
setup calls use get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup step failed" error.

Identity threading: Customer and Technician are entity-backed roles. Helpers
always thread the real Customer.id / Technician.id into the ownership-gated
calls (authorize, decision, clock-in/out, complete) via make_*_headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
)
from . import factories as f


SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["service_advisor_headers"]
PM = TEST_USERS["parts_manager_headers"]


# ---------------------------------------------------------------------------
# Atomic creators
# ---------------------------------------------------------------------------
def create_customer(api, **overrides) -> dict:
    return get_success_data(api.create_customer(f.create_customer_payload(**overrides), SM))


def create_vehicle(api, customer_id, **overrides) -> dict:
    return get_success_data(
        api.create_vehicle(f.create_vehicle_payload(customer_id, **overrides), SM)
    )


def create_technician(api, **overrides) -> dict:
    return get_success_data(api.create_technician(f.create_technician_payload(**overrides), SM))


def create_service_bay(api, **overrides) -> dict:
    return get_success_data(api.create_service_bay(f.create_service_bay_payload(**overrides), SM))


def create_labor_operation(api, **overrides) -> dict:
    return get_success_data(
        api.create_labor_operation(f.create_labor_operation_payload(**overrides), SM)
    )


def create_repair_order(api, customer_id, vehicle_id, **overrides) -> dict:
    return get_success_data(
        api.create_repair_order(
            f.create_repair_order_payload(customer_id, vehicle_id, **overrides), SM
        )
    )


def create_customer_and_vehicle(api, vehicle_overrides=None, **cust_overrides):
    """Returns (customer, vehicle)."""
    customer = create_customer(api, **cust_overrides)
    vehicle = create_vehicle(api, customer["id"], **(vehicle_overrides or {}))
    return customer, vehicle


def setup_markup_matrix(api, tiers):
    """Create a markup matrix from a list of (tier_index, lower, upper, pct) tuples.
    upper may be None for the unbounded top tier."""
    created = []
    for tier_index, lower, upper, pct in tiers:
        extra = {} if upper is None else {"upper_bound_cents": upper}
        created.append(
            get_success_data(
                api.create_markup_tier(
                    f.create_markup_tier_payload(tier_index, lower, pct, **extra), PM
                )
            )
        )
    return created


def setup_three_tier_matrix(api):
    """The canonical matrix used across pricing instances:
    [0,5000)@0.50, [5000,20000)@0.40, [20000,inf)@0.25."""
    return setup_markup_matrix(api, [
        (0, 0, 5000, 0.50),
        (1, 5000, 20000, 0.40),
        (2, 20000, None, 0.25),
    ])


# ---------------------------------------------------------------------------
# RepairOrder lifecycle progression
# ---------------------------------------------------------------------------
def authorize_ro(api, ro_id, customer_id):
    """Authorize an RO at its current version (re-reads version first)."""
    ro = get_success_data(api.get_repair_order(ro_id, SM))
    return get_success_data(
        api.authorize_repair_order(
            ro_id,
            {"expected_repair_order_version": ro["version"]},
            make_customer_headers(customer_id),
        )
    )


def schedule_ro(api, ro_id, bay_id, start, end):
    return get_success_data(
        api.schedule_repair_order(ro_id, f.schedule_payload(bay_id, start, end), SM)
    )


def transition_ro(api, ro_id, action, headers=None):
    return get_success_data(
        api.transition_repair_order(ro_id, {"action": action}, headers or SA)
    )


def setup_ro_in_progress(
    api,
    op_overrides=None,
    line_overrides=None,
    bay_start="2026-06-01T09:00:00Z",
    bay_end="2026-06-01T17:00:00Z",
    create_line=True,
    **ro_overrides,
):
    """Create a customer + vehicle + bay (+ optional op + labor line), authorize,
    schedule, and START -> IN_PROGRESS.

    Returns a dict with keys: customer, vehicle, bay, operation, ro, labor_line.

    When create_line is False, operation/labor_line are None in the result, but an
    anchor labor line is still added so the order has a billable line to authorize
    against (authorization requires at least one billable line); the test then adds
    its own line(s) onto the started order.
    """
    customer, vehicle = create_customer_and_vehicle(api)
    bay = create_service_bay(api)
    operation = None
    labor_line = None
    ro = create_repair_order(api, customer["id"], vehicle["id"], **ro_overrides)
    if create_line:
        operation = create_labor_operation(api, **(op_overrides or {}))
        labor_line = get_success_data(
            api.create_labor_line(
                ro["id"],
                f.create_labor_line_payload(operation["id"], **(line_overrides or {})),
                SM,
            )
        )
    else:
        # Anchor line so authorization has something billable; not returned.
        anchor_op = create_labor_operation(api)
        get_success_data(
            api.create_labor_line(ro["id"], f.create_labor_line_payload(anchor_op["id"]), SM)
        )
    authorize_ro(api, ro["id"], customer["id"])
    schedule_ro(api, ro["id"], bay["id"], bay_start, bay_end)
    transition_ro(api, ro["id"], "START")
    return {
        "customer": customer,
        "vehicle": vehicle,
        "bay": bay,
        "operation": operation,
        "ro": ro,
        "labor_line": labor_line,
    }


# ---------------------------------------------------------------------------
# LaborLine clock helpers
# ---------------------------------------------------------------------------
def clock_in(api, ll_id, technician_id, clock_in_ts):
    return get_success_data(
        api.clock_in_labor_line(
            ll_id,
            {"technician_id": technician_id, "clock_in": clock_in_ts},
            make_technician_headers(technician_id),
        )
    )


def clock_out(api, ll_id, technician_id, clock_out_ts):
    return get_success_data(
        api.clock_out_labor_line(
            ll_id, {"clock_out": clock_out_ts}, make_technician_headers(technician_id)
        )
    )


def complete_labor_line(api, ll_id, technician_id):
    return get_success_data(
        api.complete_labor_line(ll_id, make_technician_headers(technician_id))
    )


def clock_session_and_complete(api, ll_id, technician_id, clock_in_ts, clock_out_ts):
    """Clock in, clock out, and complete a labor line. Returns the completed line."""
    clock_in(api, ll_id, technician_id, clock_in_ts)
    clock_out(api, ll_id, technician_id, clock_out_ts)
    return complete_labor_line(api, ll_id, technician_id)


# ---------------------------------------------------------------------------
# Inspection + RecommendedJob helpers
# ---------------------------------------------------------------------------
def create_inspection(api, ro_id, technician_id):
    return get_success_data(
        api.create_inspection(
            ro_id, f.create_inspection_payload(technician_id), make_technician_headers(technician_id)
        )
    )


def add_item(api, insp_id, technician_id, point_name, severity=None):
    extra = {} if severity is None else {"severity": severity}
    return get_success_data(
        api.add_inspection_item(
            insp_id,
            f.add_inspection_item_payload(point_name, **extra),
            make_technician_headers(technician_id),
        )
    )


def submit_inspection(api, insp_id, technician_id):
    return get_success_data(
        api.submit_inspection(insp_id, make_technician_headers(technician_id))
    )


def create_recommended_job(api, insp_id, technician_id, ro_id, op_id, **overrides):
    return get_success_data(
        api.create_recommended_job(
            insp_id,
            f.create_recommended_job_payload(ro_id, op_id, **overrides),
            make_technician_headers(technician_id),
        )
    )


def setup_inspection_with_pending_job(api, item_severity="YELLOW", job_overrides=None, submit=False):
    """Customer + vehicle + RO + DRAFT inspection with one item + one PENDING
    recommended job. Optionally submit the inspection.

    Returns dict: customer, vehicle, ro, technician, operation, inspection,
    recommended_job.
    """
    customer, vehicle = create_customer_and_vehicle(api)
    technician = create_technician(api)
    operation = create_labor_operation(api)
    ro = create_repair_order(api, customer["id"], vehicle["id"])
    inspection = create_inspection(api, ro["id"], technician["id"])
    add_item(api, inspection["id"], technician["id"], "Inspection point", item_severity)
    job = create_recommended_job(
        api,
        inspection["id"],
        technician["id"],
        ro["id"],
        operation["id"],
        **(job_overrides or {}),
    )
    if submit:
        submit_inspection(api, inspection["id"], technician["id"])
    return {
        "customer": customer,
        "vehicle": vehicle,
        "ro": ro,
        "technician": technician,
        "operation": operation,
        "inspection": inspection,
        "recommended_job": job,
    }


# ---------------------------------------------------------------------------
# PartLine / CoreCharge helpers
# ---------------------------------------------------------------------------
def add_part_line(api, ro_id, part_number, quantity, unit_cost_cents, **overrides):
    return get_success_data(
        api.create_part_line(
            ro_id,
            f.create_part_line_payload(part_number, quantity, unit_cost_cents, **overrides),
            PM,
        )
    )


def get_core_charge_for_ro(api, ro_id):
    """Return the first core charge owned by the RO (the cascade creates one)."""
    data, _meta = _list(api.list_repair_order_core_charges(ro_id, PM))
    assert data, f"Setup step failed: no core charge found on RO {ro_id}"
    return data[0]


def _list(response):
    """Lenient list unwrap returning (data, meta)."""
    body = get_success_data(response)
    # get_success_data returns the data payload (a list for array responses).
    if isinstance(body, list):
        return body, {}
    return body, {}


def setup_ro_with_charged_core(api, deposit_cents=4000, quantity=1, unit_cost_cents=8000):
    """Markup matrix + customer/vehicle + RO ESTIMATE + one cored part line ->
    a CHARGED CoreCharge.

    Returns dict: customer, vehicle, ro, part_line, core_charge.
    """
    setup_markup_matrix(api, [(0, 0, 20000, 0.40)])
    customer, vehicle = create_customer_and_vehicle(api)
    ro = create_repair_order(api, customer["id"], vehicle["id"])
    part_line = add_part_line(
        api,
        ro["id"],
        "CORE-PART",
        quantity,
        unit_cost_cents,
        markup_mode="FLAT_BRACKET",
        has_core=True,
        core_deposit_cents=deposit_cents,
    )
    core_charge = get_core_charge_for_ro(api, ro["id"])
    return {
        "customer": customer,
        "vehicle": vehicle,
        "ro": ro,
        "part_line": part_line,
        "core_charge": core_charge,
    }


# ---------------------------------------------------------------------------
# Warranty: fully closed original RO (for comeback tests)
# ---------------------------------------------------------------------------
def set_clock(api, iso_ts):
    return get_success_data(api.set_clock({"to_iso8601": iso_ts}, SM))


def setup_closed_original_ro(
    api,
    closed_clock="2026-01-01T08:00:00Z",
    odometer_miles=40000,
    book_hours=2.0,
    rate_cents=12000,
    clock_in_ts="2026-01-01T09:00:00Z",
    clock_out_ts="2026-01-01T10:30:00Z",
    bay_start="2026-01-01T09:00:00Z",
    bay_end="2026-01-01T13:00:00Z",
):
    """Drive an RO all the way to CLOSED at `closed_clock`, with one completed
    flat-rate labor line crediting a technician. Anchors the warranty window.

    Returns dict: customer, vehicle, technician, operation, bay, ro, labor_line.
    """
    set_clock(api, closed_clock)
    operation = create_labor_operation(api, book_hours=book_hours, default_rate_cents=rate_cents)
    technician = create_technician(api)
    customer = create_customer(api)
    vehicle = create_vehicle(api, customer["id"], odometer_miles=odometer_miles)
    bay = create_service_bay(api)
    ro = create_repair_order(api, customer["id"], vehicle["id"])
    labor_line = get_success_data(
        api.create_labor_line(
            ro["id"],
            f.create_labor_line_payload(
                operation["id"], technician_id=technician["id"], billing_method="FLAT_RATE"
            ),
            SM,
        )
    )
    authorize_ro(api, ro["id"], customer["id"])
    schedule_ro(api, ro["id"], bay["id"], bay_start, bay_end)
    transition_ro(api, ro["id"], "START")
    clock_session_and_complete(api, labor_line["id"], technician["id"], clock_in_ts, clock_out_ts)
    get_success_data(api.complete_repair_order(ro["id"], make_technician_headers(technician["id"])))
    transition_ro(api, ro["id"], "INVOICE")
    transition_ro(api, ro["id"], "CLOSE")
    return {
        "customer": customer,
        "vehicle": vehicle,
        "technician": technician,
        "operation": operation,
        "bay": bay,
        "ro": ro,
        "labor_line": labor_line,
    }
