"""Composite setup helpers for the remanufacturing lifecycle.

Each helper builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints, so tests can focus on assertions. All
helpers return plain dicts of the entities/ids a test needs. Setup calls
use get_success_data() so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assembly_record_payload,
    create_customer_payload,
    create_decision_payload,
    create_finding_payload,
    create_loaner_assignment_payload,
    create_loaner_unit_payload,
    create_order_payload,
    create_run_in_test_payload,
    create_shipment_payload,
    create_unit_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)

IC = TEST_USERS["intake_coordinator_headers"]
RE = TEST_USERS["reman_engineer_headers"]
QI = TEST_USERS["quality_inspector_headers"]
SM = TEST_USERS["service_manager_headers"]


def _ok(resp, what):
    assert resp.status_code < 300, (
        f"Setup failed ({what}): {resp.status_code} {resp.text}")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: basic creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the shop logical clock (PRD §2.8)."""
    return _ok(api_client.set_clock(to_iso8601, SM), "set clock")


def make_customer(legal_name="Test Customer", credit_limit_cents=90_000_000) -> dict:
    return _ok(api_client.create_customer(
        create_customer_payload(legal_name=legal_name,
                                credit_limit_cents=credit_limit_cents), IC),
        "create customer")


def get_customer(customer_id) -> dict:
    return _ok(api_client.get_customer(customer_id, SM), "get customer")


def make_unit(customer_id, serial_number="GBX-0001", model="HZ-450",
              rated_torque_nm=12_000, hours=None, check_in=True) -> dict:
    """Register a unit; optionally advance its odometer and check it in."""
    unit = _ok(api_client.create_unit(
        customer_id,
        create_unit_payload(serial_number=serial_number, model=model,
                            rated_torque_nm=rated_torque_nm),
        IC), "create unit")
    if hours is not None:
        unit = _ok(api_client.record_service_hours(unit["id"], hours, IC),
                   "record service hours")
    if check_in:
        unit = _ok(api_client.check_in_unit(unit["id"], IC), "check in unit")
    return unit


def get_unit(unit_id) -> dict:
    return _ok(api_client.get_unit(unit_id, SM), "get unit")


def make_order(unit_id, intake_hours=0, quoted_estimate_cents=100_000,
               rush=False) -> dict:
    payload = create_order_payload(intake_hours=intake_hours,
                                   quoted_estimate_cents=quoted_estimate_cents,
                                   rush=rush)
    return _ok(api_client.create_order(unit_id, payload, IC), "create order")


def get_order(order_id) -> dict:
    return _ok(api_client.get_order(order_id, SM), "get order")


def setup_unit_with_order(serial_number="GBX-0001", hours=None,
                          quoted_estimate_cents=100_000, rush=False,
                          credit_limit_cents=90_000_000,
                          legal_name="Test Customer") -> dict:
    """Customer + checked-in unit + INTAKE order. The order's intake_hours
    equals the unit odometer (0 when hours is None)."""
    customer = make_customer(legal_name=legal_name,
                             credit_limit_cents=credit_limit_cents)
    unit = make_unit(customer["id"], serial_number=serial_number, hours=hours)
    order = make_order(unit["id"],
                       intake_hours=unit["cumulative_service_hours"],
                       quoted_estimate_cents=quoted_estimate_cents, rush=rush)
    return {"customer": customer, "unit": unit, "order": order}


# ---------------------------------------------------------------------------
# Tier 2: teardown stage
# ---------------------------------------------------------------------------

def start_teardown(order_id) -> dict:
    return _ok(api_client.start_teardown(order_id, RE), "start teardown")


def add_finding(order_id, component_code="PINION_1", condition="REGRINDABLE",
                severity=2, notes="wear") -> dict:
    return _ok(api_client.create_finding(
        order_id,
        create_finding_payload(component_code=component_code,
                               condition=condition, severity=severity,
                               notes=notes),
        RE), "create finding")


def add_decision(order_id, component_code="PINION_1", action="REGRIND",
                 labor_hours=2.0, material_cents=5_000) -> dict:
    return _ok(api_client.create_decision(
        order_id,
        create_decision_payload(component_code=component_code, action=action,
                                labor_hours=labor_hours,
                                material_cents=material_cents),
        RE), "create decision")


def setup_order_in_teardown(components=None, **order_kwargs) -> dict:
    """INTAKE order walked into TEARDOWN. `components` is a list of
    (component_code, condition, severity, action, labor_hours, material_cents)
    tuples; when given, findings and decisions are posted for each."""
    ctx = setup_unit_with_order(**order_kwargs)
    ctx["order"] = start_teardown(ctx["order"]["id"])
    ctx["findings"] = []
    ctx["decisions"] = []
    for comp in (components or []):
        code, condition, severity, action, labor_hours, material_cents = comp
        ctx["findings"].append(
            add_finding(ctx["order"]["id"], component_code=code,
                        condition=condition, severity=severity))
        ctx["decisions"].append(
            add_decision(ctx["order"]["id"], component_code=code,
                         action=action, labor_hours=labor_hours,
                         material_cents=material_cents))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: scope submission / approval
# ---------------------------------------------------------------------------

def submit_scope(order_id) -> dict:
    return _ok(api_client.submit_scope(order_id, RE), "submit scope")


def setup_order_in_scope_approval(components=None, **kwargs) -> dict:
    """Order in SCOPE_APPROVAL: by default one REGRIND 4.0h/12000 decision
    (scope 46000) priced above the quoted estimate (10000) so the customer
    must approve. Pass `components` to control the priced scope."""
    kwargs.setdefault("quoted_estimate_cents", 10_000)
    ctx = setup_order_in_teardown(
        components=components or
        [("PINION_1", "REGRINDABLE", 2, "REGRIND", 4.0, 12_000)],
        **kwargs)
    ctx["order"] = submit_scope(ctx["order"]["id"])
    return ctx


def approve_scope(order_id, customer_id) -> dict:
    return _ok(api_client.approve_scope(
        order_id, make_customer_headers(customer_id)), "approve scope")


def setup_approved_order(auto=False, components=None, **kwargs) -> dict:
    """Order in APPROVED. With auto=True the quoted estimate covers the scope
    so submit-scope auto-approves; otherwise the owning customer approves."""
    if auto:
        kwargs.setdefault("quoted_estimate_cents", 50_000)
        ctx = setup_order_in_teardown(
            components=components or
            [("PINION_1", "REGRINDABLE", 2, "REGRIND", 2.0, 5_000)],
            **kwargs)
        ctx["order"] = submit_scope(ctx["order"]["id"])
    else:
        ctx = setup_order_in_scope_approval(components=components, **kwargs)
        ctx["order"] = approve_scope(ctx["order"]["id"], ctx["customer"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: build / assembly / run-in
# ---------------------------------------------------------------------------

def setup_order_in_assembly(**kwargs) -> dict:
    """Order walked APPROVED → IN_BUILD → ASSEMBLY."""
    ctx = setup_approved_order(**kwargs)
    ctx["order"] = _ok(api_client.start_build(ctx["order"]["id"], RE),
                       "start build")
    ctx["order"] = _ok(api_client.start_assembly(ctx["order"]["id"], RE),
                       "start assembly")
    return ctx


def record_assembly(order_id, backlash_mm=0.10, radial_clearance_mm=0.02,
                    axial_clearance_mm=0.02) -> dict:
    return _ok(api_client.create_assembly_record(
        order_id,
        create_assembly_record_payload(
            backlash_mm=backlash_mm, radial_clearance_mm=radial_clearance_mm,
            axial_clearance_mm=axial_clearance_mm),
        QI), "create assembly record")


def setup_order_in_run_in(**kwargs) -> dict:
    """Order in RUN_IN with one in-tolerance ACTIVE assembly record."""
    ctx = setup_order_in_assembly(**kwargs)
    ctx["assembly_record"] = record_assembly(ctx["order"]["id"])
    ctx["order"] = _ok(api_client.submit_assembly(ctx["order"]["id"], QI),
                       "submit assembly")
    return ctx


def record_run_in(order_id, duration_minutes=120, max_temp_c=80.0,
                  vibration_mm_s=2.0, oil_particle_count=1_500) -> dict:
    return _ok(api_client.create_run_in_test(
        order_id,
        create_run_in_test_payload(
            duration_minutes=duration_minutes, max_temp_c=max_temp_c,
            vibration_mm_s=vibration_mm_s, oil_particle_count=oil_particle_count),
        QI), "create run-in test")


def setup_ready_to_ship_order(**kwargs) -> dict:
    """Order in RUN_IN, then a passing run-in test → READY_TO_SHIP."""
    ctx = setup_order_in_run_in(**kwargs)
    ctx["run_in_test"] = record_run_in(ctx["order"]["id"])
    ctx["order"] = get_order(ctx["order"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: freight, shipping, completion
# ---------------------------------------------------------------------------

def add_shipment(order_id, direction="OUTBOUND", weight_kg=400,
                 rigging_bay_date="2026-08-10", rigging_bay_hours=2) -> dict:
    return _ok(api_client.create_shipment(
        order_id,
        create_shipment_payload(direction=direction, weight_kg=weight_kg,
                                rigging_bay_date=rigging_bay_date,
                                rigging_bay_hours=rigging_bay_hours),
        IC), "create shipment")


def setup_shipped_order(rigging_bay_date="2026-08-10", weight_kg=400,
                        rigging_bay_hours=2, **kwargs) -> dict:
    """READY_TO_SHIP order + BOOKED outbound shipment, then ship → SHIPPED
    (outbound shipment moves to IN_TRANSIT)."""
    ctx = setup_ready_to_ship_order(**kwargs)
    ctx["shipment"] = add_shipment(
        ctx["order"]["id"],
        direction="OUTBOUND", weight_kg=weight_kg,
        rigging_bay_date=rigging_bay_date, rigging_bay_hours=rigging_bay_hours)
    ctx["order"] = _ok(api_client.ship_order(ctx["order"]["id"], SM),
                       "ship order")
    return ctx


def setup_completed_order(rigging_bay_date="2026-08-10", weight_kg=400,
                          rigging_bay_hours=2, **kwargs) -> dict:
    """Full pipeline through COMPLETED: ship, deliver outbound, complete."""
    ctx = setup_shipped_order(rigging_bay_date=rigging_bay_date,
                              weight_kg=weight_kg,
                              rigging_bay_hours=rigging_bay_hours, **kwargs)
    ctx["shipment"] = _ok(
        api_client.deliver_shipment(ctx["shipment"]["id"], IC),
        "deliver shipment")
    ctx["order"] = _ok(api_client.complete_order(ctx["order"]["id"], SM),
                       "complete order")
    ctx["unit"] = get_unit(ctx["unit"]["id"])
    ctx["customer"] = get_customer(ctx["customer"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Loaner fleet
# ---------------------------------------------------------------------------

def make_loaner(serial_number="LN-0001", model="HZ-450") -> dict:
    return _ok(api_client.create_loaner_unit(
        create_loaner_unit_payload(serial_number=serial_number, model=model),
        SM), "create loaner unit")


def get_loaner(loaner_id) -> dict:
    return _ok(api_client.get_loaner_unit(loaner_id, SM), "get loaner unit")


def make_assignment(loaner_id, order_id, start_date="2026-08-10",
                    end_date="2026-08-20") -> dict:
    return _ok(api_client.create_loaner_assignment(
        loaner_id,
        create_loaner_assignment_payload(order_id, start_date=start_date,
                                         end_date=end_date),
        IC), "create loaner assignment")


def get_assignment(assignment_id) -> dict:
    return _ok(api_client.get_loaner_assignment(assignment_id, IC),
               "get loaner assignment")


def setup_checked_out_assignment(start_date="2026-08-01",
                                 end_date="2026-08-10",
                                 clock="2026-08-02T00:00:00Z",
                                 serial_number="GBX-LN1",
                                 loaner_serial="LN-0001") -> dict:
    """Loaner + RESERVED assignment for an order, checked out inside its
    window (the logical clock is placed within [start_date, end_date))."""
    set_clock(clock)
    ctx = setup_unit_with_order(serial_number=serial_number)
    loaner = make_loaner(serial_number=loaner_serial)
    assignment = make_assignment(loaner["id"], ctx["order"]["id"],
                                 start_date=start_date, end_date=end_date)
    assignment = _ok(api_client.checkout_loaner(assignment["id"], IC),
                     "checkout loaner")
    ctx["loaner"] = loaner
    ctx["assignment"] = assignment
    return ctx


# ---------------------------------------------------------------------------
# Warranty claims
# ---------------------------------------------------------------------------

def make_claim(order_id, customer_id, reported_hours=100,
               claim_reason="noise") -> dict:
    return _ok(api_client.create_warranty_claim(
        order_id,
        create_warranty_claim_payload(reported_hours=reported_hours,
                                      claim_reason=claim_reason),
        make_customer_headers(customer_id)), "create warranty claim")


def get_claim(claim_id) -> dict:
    return _ok(api_client.get_warranty_claim(claim_id, SM), "get warranty claim")


def setup_claim_under_review(reported_hours=100, advance_unit_hours=None,
                             **kwargs) -> dict:
    """Completed order + warranty claim moved OPEN → UNDER_REVIEW.

    reported_hours is the claim's odometer reading; advance_unit_hours (when
    given) first advances the unit odometer so the reading is legal.
    """
    ctx = setup_completed_order(**kwargs)
    if advance_unit_hours is not None:
        ctx["unit"] = _ok(
            api_client.record_service_hours(ctx["unit"]["id"],
                                            advance_unit_hours, IC),
            "advance unit hours")
    ctx["claim"] = make_claim(ctx["order"]["id"], ctx["customer"]["id"],
                              reported_hours=reported_hours)
    ctx["claim"] = _ok(
        api_client.review_warranty_claim(ctx["claim"]["id"], QI),
        "review warranty claim")
    return ctx
