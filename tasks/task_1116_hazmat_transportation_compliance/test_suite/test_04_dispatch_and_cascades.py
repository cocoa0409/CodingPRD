"""Dispatch gates and cascades: route window gating, carrier suspension depth-3
cascade, packaging retirement depth-2 cascade, stale security plan pinning."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_approved_carrier_paid, create_standard_catalog, create_material,
    create_packaging_spec, create_documented_shipment, create_tendered_shipment,
    create_qualified_driver, create_vehicle, create_route, create_load,
    add_item, create_shipment, create_classified_shipment,
    create_verified_shipment, create_and_certify_paper,
    create_approved_security_plan, create_sealed_load_with_tendered_shipment,
    setup_dispatchable_scenario, set_clock, pay_outstanding, list_invoices,
)
from test_helpers.fixtures import ADMIN, OFFICER_A, OFFICER_B, REGULATOR, _ok


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / dispatch_requires_route_effective
# ---------------------------------------------------------------------------

def _setup_sealed_load_with_june_route(api):
    """TENDERED shipment on a SEALED load whose route is effective only
    2026-06-01..2026-06-30; clock stays at the 2026-05-01 default."""
    route_overrides = {"effective_from": "2026-06-01T00:00:00Z",
                       "effective_to": "2026-06-30T00:00:00Z"}
    scenario = setup_dispatchable_scenario(route_overrides=route_overrides)
    # the load's planned window must also sit inside June for realism
    return scenario


def test_dispatch_outside_route_window_rejected(api):
    """PRD §3.7: "The route's effective window must cover the clock with closed
    bounds, else `ERR_ROUTE_NOT_EFFECTIVE`".

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_route_effective
    """
    sc = _setup_sealed_load_with_june_route(api)
    resp = api.dispatch_load(sc["load"]["id"], OFFICER_A)
    # clock 2026-05-01 is outside [2026-06-01, 2026-06-30]
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_EFFECTIVE)


def test_dispatch_inside_route_window_fires_full_cascade(api):
    """PRD §3.7: "A successful dispatch fires a three-link cascade: the vehicle
    moves to `DISPATCHED`; in parallel every item shipment moves from
    `TENDERED` to `IN_TRANSIT`; and each now-in-transit shipment's `CERTIFIED`
    shipping paper moves to `LOCKED_IN_TRANSIT`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_route_effective
    """
    sc = _setup_sealed_load_with_june_route(api)
    set_clock("2026-06-15T00:00:00Z")
    dispatched = validate_success(api.dispatch_load(sc["load"]["id"], OFFICER_A))
    assert dispatched["status"] == "DISPATCHED"

    vehicle = validate_success(api.get_vehicle(sc["vehicle"]["id"], REGULATOR))
    assert vehicle["status"] == "DISPATCHED"
    shipment = validate_success(api.get_shipment(sc["shipment"]["id"], REGULATOR))
    assert shipment["status"] == "IN_TRANSIT"
    papers, _ = validate_paginated(api.list_shipping_papers(sc["shipment"]["id"], REGULATOR))
    assert papers[0]["status"] == "LOCKED_IN_TRANSIT"


# ---------------------------------------------------------------------------
# transitive_cascade / carrier_suspend_depth3
# ---------------------------------------------------------------------------

def _setup_suspension_scenario(api):
    """Carrier paid; qualified driver; TENDERED shipment on a SEALED load."""
    return setup_dispatchable_scenario()


def test_suspend_cascades_to_drivers_and_shipments(api):
    """PRD §3.6: "First, every `ACTIVE` driver of the carrier moves to
    `SUSPENDED`". "Second, as a consequence of the carrier leaving
    `APPROVED_ACTIVE`, every shipment of the carrier in `TENDERED` reverts to
    `DOCUMENTED` with `pinned_security_plan_id` and
    `pinned_security_plan_version` cleared — the assigned `driver_id` is kept."

    Design: Difficulty/transitive_cascade/carrier_suspend_depth3
    """
    sc = _setup_suspension_scenario(api)
    suspended = validate_success(api.suspend_carrier(sc["carrier"]["id"], REGULATOR))
    assert suspended["registration_status"] == "SUSPENDED"

    driver = validate_success(api.get_driver(sc["driver"]["id"], REGULATOR))
    assert driver["status"] == "SUSPENDED"
    shipment = validate_success(api.get_shipment(sc["shipment"]["id"], REGULATOR))
    assert shipment["status"] == "DOCUMENTED"
    assert shipment["pinned_security_plan_id"] is None
    assert shipment["driver_id"] == sc["driver"]["id"], "driver assignment is kept"


def test_suspend_pulls_items_and_unseals_load(api):
    """PRD §3.6: "Third, each reverted shipment's load item is removed from any
    `STAGING` or `SEALED` load; every affected load recomputes
    `total_table2_weight_kg`, and an affected `SEALED` load falls back to
    `STAGING` with `required_placards` cleared to the empty list and
    `handling_fee_cents` zeroed."

    Design: Difficulty/transitive_cascade/carrier_suspend_depth3
    """
    sc = _setup_suspension_scenario(api)
    _ok(api.suspend_carrier(sc["carrier"]["id"], REGULATOR), "suspend")

    load = validate_success(api.get_load(sc["load"]["id"], REGULATOR))
    assert load["status"] == "STAGING"
    assert load["total_table2_weight_kg"] == pytest.approx(0.0)
    assert load["required_placards"] == []
    assert load["handling_fee_cents"] == 0
    items, meta = validate_paginated(
        api.list_shipment_load_items(sc["shipment"]["id"], REGULATOR))
    assert meta["total_count"] == 0
    assert items == []


# ---------------------------------------------------------------------------
# transitive_cascade / packaging_retire_depth2
# ---------------------------------------------------------------------------

def _setup_two_shipments_on_one_spec(api):
    """Shipment A PACKAGING_VERIFIED with a CERTIFIED paper; shipment B DRAFT;
    both on the same spec."""
    carrier = create_approved_carrier_paid(hazmat_categories=["FLAMMABLE_LIQUID"])
    material, spec = create_standard_catalog()
    shipment_a = create_classified_shipment(carrier["id"], material["id"], spec["id"],
                                            quantity_kg=200.0)
    paper_a = create_and_certify_paper(shipment_a["id"])
    _ok(api.verify_packaging(shipment_a["id"], OFFICER_A), "verify A")
    shipment_b = create_shipment(carrier["id"], material["id"], spec["id"],
                                 quantity_kg=50.0, declared_value_cents=500)
    return carrier, material, spec, shipment_a, paper_a, shipment_b


def test_retire_cancels_predocumented_shipments(api):
    """PRD §3.3: "retiring an `ACTIVE` spec (any other status yields
    `ERR_SPEC_NOT_ACTIVE`) moves it to `RETIRED` and cascades. Every shipment
    using that spec in `DRAFT`, `CLASSIFIED`, or `PACKAGING_VERIFIED` is
    cancelled".

    Design: Difficulty/transitive_cascade/packaging_retire_depth2
    """
    carrier, material, spec, shipment_a, paper_a, shipment_b = _setup_two_shipments_on_one_spec(api)
    retired = validate_success(api.retire_packaging_spec(spec["id"], REGULATOR))
    assert retired["status"] == "RETIRED"

    sha = validate_success(api.get_shipment(shipment_a["id"], REGULATOR))
    assert sha["status"] == "CANCELLED"
    shb = validate_success(api.get_shipment(shipment_b["id"], REGULATOR))
    assert shb["status"] == "CANCELLED", "DRAFT shipment is swept too"


def test_retire_voids_papers_of_cancelled_shipments(api):
    """PRD §3.3: "and — caused by each such cancellation — that shipment's
    shipping paper, if `DRAFT`, `CERTIFIED`, or `UNDER_AMENDMENT`, is voided."

    Design: Difficulty/transitive_cascade/packaging_retire_depth2
    """
    carrier, material, spec, shipment_a, paper_a, shipment_b = _setup_two_shipments_on_one_spec(api)
    _ok(api.retire_packaging_spec(spec["id"], REGULATOR), "retire")

    papers, _ = validate_paginated(api.list_shipping_papers(shipment_a["id"], REGULATOR))
    assert papers[0]["status"] == "VOIDED"


# ---------------------------------------------------------------------------
# Corner/state_machines/dispatch_rejects_stale_security_plan
# ---------------------------------------------------------------------------

def _setup_pinned_sealed_load(api):
    """EXPLOSIVE carrier; APPROVED plan; TENDERED CLASS_1_1 shipment (pinned)
    on a SEALED load. Returns dict of context."""
    carrier = create_approved_carrier_paid(hazmat_categories=["EXPLOSIVE"])
    plan = create_approved_security_plan(carrier["id"], coverage_categories=["EXPLOSIVE"])
    material = create_material(
        un_na_number="UN0335", proper_shipping_name="FIREWORKS",
        hazard_class="CLASS_1_1", packing_group="PG_NONE", placard_table="TABLE_1",
        transport_category="EXPLOSIVE", reportable_quantity_lbs=1,
        erg_guide_number="112")
    spec = create_packaging_spec(authorized_hazard_classes=["CLASS_1_1"])
    driver = create_qualified_driver(carrier["id"])
    vehicle = create_vehicle(carrier["id"])
    route = create_route(allowed_hazard_classes=["CLASS_1_1"])
    shipment, load = create_sealed_load_with_tendered_shipment(
        carrier, material, spec, driver, vehicle, route,
        declared_shipping_name="FIREWORKS", quantity_kg=10.0)
    return {"carrier": carrier, "plan": plan, "driver": driver,
            "vehicle": vehicle, "route": route, "shipment": shipment, "load": load}


def test_dispatch_rejects_stale_security_plan(api):
    """PRD §3.7: "For every item shipment carrying a `pinned_security_plan_id`,
    the pinned version must still equal the plan's current `version` and the
    plan must still be `APPROVED`, else `ERR_STALE_SECURITY_PLAN`; this is where
    a plan revision stales a pinned shipment, since revising an `APPROVED` plan
    (§3.8) increments its version."

    Design: Corner/state_machines/dispatch_rejects_stale_security_plan
    """
    ctx = _setup_pinned_sealed_load(api)
    pin_v = ctx["shipment"]["pinned_security_plan_version"]
    assert pin_v is not None

    revised = validate_success(api.revise_security_plan(ctx["plan"]["id"], ADMIN))
    assert revised["status"] == "UNDER_REVISION"
    resp = api.dispatch_load(ctx["load"]["id"], OFFICER_A)
    validate_error(resp, ApiErrorId.ERR_STALE_SECURITY_PLAN)

    # Re-approval bumps the version AGAIN, so the pin is still stale
    _ok(api.submit_security_plan(ctx["plan"]["id"], ADMIN), "re-submit")
    _ok(api.approve_security_plan(ctx["plan"]["id"], REGULATOR), "re-approve")
    resp2 = api.dispatch_load(ctx["load"]["id"], OFFICER_A)
    validate_error(resp2, ApiErrorId.ERR_STALE_SECURITY_PLAN)


def test_retender_repins_and_dispatch_succeeds(api):
    """PRD §3.6: "Re-tendering from `TENDERED` re-runs every gate and re-pins
    plan and driver."
    PRD §3.7: "For every item shipment carrying a `pinned_security_plan_id`,
    the pinned version must still equal the plan's current `version` and the
    plan must still be `APPROVED`".

    Design: Corner/state_machines/dispatch_rejects_stale_security_plan
    """
    ctx = _setup_pinned_sealed_load(api)
    pin_v = ctx["shipment"]["pinned_security_plan_version"]
    _ok(api.revise_security_plan(ctx["plan"]["id"], ADMIN), "revise")
    _ok(api.submit_security_plan(ctx["plan"]["id"], ADMIN), "re-submit")
    _ok(api.approve_security_plan(ctx["plan"]["id"], REGULATOR), "re-approve")

    retendered = validate_success(api.tender_shipment(
        ctx["shipment"]["id"], {"driver_id": ctx["driver"]["id"]}, OFFICER_A))
    assert retendered["pinned_security_plan_version"] > pin_v, "re-tender re-pins the current version"

    dispatched = validate_success(api.dispatch_load(ctx["load"]["id"], OFFICER_A))
    assert dispatched["status"] == "DISPATCHED"
