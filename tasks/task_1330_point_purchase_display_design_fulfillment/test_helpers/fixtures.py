"""Composite setup helpers for multi-step test prerequisites.

All helpers build state from scratch against a freshly restarted server using
only PRD-declared endpoints, threading each entity's current `version` through
the OCC-guarded writes (PRD §2.7). Setup calls use the lenient get_success_data
validator so a failed precondition surfaces as a clear "Setup step failed".
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import api_client
from .constants import (
    APPOINTMENT_INSIDE_WINDOW,
    SHIP_WINDOW_END,
    SHIP_WINDOW_START,
    TIME_INSIDE_WINDOW,
)
from .factories import (
    create_client_payload,
    create_compliance_rule_payload,
    create_damage_claim_payload,
    create_design_payload,
    create_field_service_request_payload,
    create_kit_payload,
    create_production_run_payload,
    create_program_payload,
    create_shipment_payload,
    create_store_payload,
)
from .test_users import (
    CLAIMS_ADJUSTER,
    COMPLIANCE_OFFICER,
    DESIGNER,
    FIELD_SERVICE_MANAGER,
    LOGISTICS_COORDINATOR,
    PLATFORM_ADMIN,
    PRODUCTION_PLANNER,
    PROGRAM_MANAGER,
    WAREHOUSE_OPERATOR,
)

# ─── Tier 1: single-entity creation and transitions ───


def set_clock(to_iso8601: str):
    """Advance the server-side logical clock (PlatformAdmin only)."""
    return get_success_data(api_client.set_logical_clock(
        {"to_iso8601": to_iso8601}, PLATFORM_ADMIN))


def create_client(name: str = "Acme Corp", contact_email: str = "ops@acme.example"):
    return get_success_data(api_client.create_client(
        create_client_payload(name=name, contact_email=contact_email),
        PLATFORM_ADMIN))


def create_program(client_id: str, store_count: int = 200,
                   program_revenue_cents: int = 12000000,
                   program_name: str = "Summer", retailer_name: str = "BigBox"):
    return get_success_data(api_client.create_program(
        create_program_payload(
            client_id,
            retailer_name=retailer_name,
            program_name=program_name,
            store_count=store_count,
            program_revenue_cents=program_revenue_cents),
        PROGRAM_MANAGER))


def add_compliance_rule(program_id: str, dimension: str = "MAX_WIDTH_IN",
                        limit_value: str = "48", active: bool = True):
    return get_success_data(api_client.create_compliance_rule(
        program_id,
        create_compliance_rule_payload(
            program_id, dimension=dimension, limit_value=limit_value,
            active=active),
        COMPLIANCE_OFFICER))


def start_design(program_id: str):
    return get_success_data(api_client.start_design(program_id, PROGRAM_MANAGER))


def authorize_production(program_id: str):
    return get_success_data(
        api_client.authorize_production(program_id, PROGRAM_MANAGER))


def start_fulfillment(program_id: str):
    return get_success_data(api_client.start_fulfillment(program_id, PROGRAM_MANAGER))


def close_program(program_id: str):
    return get_success_data(api_client.close_program(program_id, PROGRAM_MANAGER))


def create_design_entity(program_id: str, design_code: str = "D1",
                         width_in=40, height_in=60, depth_in=24,
                         weight_lb=30, material: str = "CORRUGATE"):
    return get_success_data(api_client.create_design(
        create_design_payload(
            program_id, design_code=design_code, width_in=width_in,
            height_in=height_in, depth_in=depth_in, weight_lb=weight_lb,
            material=material),
        DESIGNER))


def submit_design(design_id: str):
    return get_success_data(api_client.submit_design(design_id, DESIGNER))


def begin_review(design_id: str):
    return get_success_data(api_client.begin_review(design_id, COMPLIANCE_OFFICER))


def approve_design(design_id: str, expected_design_version: int):
    return get_success_data(api_client.approve_design(
        design_id, {"expected_design_version": expected_design_version},
        COMPLIANCE_OFFICER))


def reject_design(design_id: str):
    return get_success_data(api_client.reject_design(design_id, COMPLIANCE_OFFICER))


def revise_design(design_id: str):
    return get_success_data(api_client.revise_design(design_id, DESIGNER))


def lock_design(design_id: str):
    return get_success_data(api_client.lock_design(design_id, PROGRAM_MANAGER))


def create_store(program_id: str, store_number: str = "S1",
                 address: str | None = None):
    payload = create_store_payload(program_id, store_number)
    if address is not None:
        payload["address"] = address
    return get_success_data(api_client.create_store(payload, PROGRAM_MANAGER))


def create_production_run_entity(program: dict, design_id: str,
                                 overage_pct=0,
                                 expected_program_version: int | None = None):
    """Create a PLANNED run, threading the parent program's current version
    into the OCC-guarded create (PRD §2.7)."""
    if expected_program_version is None:
        expected_program_version = program["version"]
    return get_success_data(api_client.create_production_run(
        create_production_run_payload(
            program["id"], design_id, expected_program_version,
            overage_pct=overage_pct),
        PRODUCTION_PLANNER))


def authorize_run(run_id: str):
    return get_success_data(api_client.authorize_run(run_id, PRODUCTION_PLANNER))


def mark_produced(run_id: str):
    return get_success_data(api_client.mark_produced(run_id, PRODUCTION_PLANNER))


def create_manual_kit(production_run_id: str, store_id: str):
    return get_success_data(api_client.create_kit(
        create_kit_payload(production_run_id, store_id), WAREHOUSE_OPERATOR))


def mark_kitted(kit_id: str):
    return get_success_data(api_client.mark_kitted(kit_id, WAREHOUSE_OPERATOR))


def list_kits_for_run(run_id: str):
    data, _meta = validate_paginated(
        api_client.list_run_kits(run_id, WAREHOUSE_OPERATOR))
    return data


def create_shipment_for_kit(kit_id: str,
                            ship_window_start: str = SHIP_WINDOW_START,
                            ship_window_end: str = SHIP_WINDOW_END):
    return get_success_data(api_client.create_shipment(
        create_shipment_payload(
            kit_id, ship_window_start=ship_window_start,
            ship_window_end=ship_window_end),
        LOGISTICS_COORDINATOR))


def set_appointment(shipment_id: str, appointment_at: str = APPOINTMENT_INSIDE_WINDOW):
    return get_success_data(api_client.set_appointment(
        shipment_id, {"appointment_at": appointment_at}, LOGISTICS_COORDINATOR))


def ship_shipment(shipment_id: str):
    return get_success_data(api_client.ship_shipment(shipment_id, LOGISTICS_COORDINATOR))


def deliver_shipment(shipment_id: str):
    return get_success_data(
        api_client.deliver_shipment(shipment_id, LOGISTICS_COORDINATOR))


def get_kit(kit_id: str):
    return get_success_data(api_client.get_kit(kit_id, WAREHOUSE_OPERATOR))


def get_shipment(shipment_id: str):
    return get_success_data(api_client.get_shipment(shipment_id, LOGISTICS_COORDINATOR))


def get_design(design_id: str):
    return get_success_data(api_client.get_design(design_id, DESIGNER))


def get_program(program_id: str):
    return get_success_data(api_client.get_program(program_id, PROGRAM_MANAGER))


def get_production_run(run_id: str):
    return get_success_data(api_client.get_production_run(run_id, PRODUCTION_PLANNER))


def create_damage_claim_entity(kit_id: str, reported_by: str = "Store Manager",
                               replacement_quantity: int = 2):
    return get_success_data(api_client.create_damage_claim(
        create_damage_claim_payload(
            kit_id, reported_by=reported_by,
            replacement_quantity=replacement_quantity),
        CLAIMS_ADJUSTER))


def approve_claim(claim_id: str):
    return get_success_data(api_client.approve_claim(claim_id, CLAIMS_ADJUSTER))


def fulfill_claim(claim_id: str):
    return get_success_data(api_client.fulfill_claim(claim_id, WAREHOUSE_OPERATOR))


def get_recap(program_id: str):
    """Read the program's recap. The recap listing returns one recap per
    program; tolerate either an array or object envelope shape."""
    res = api_client.get_program_recap(program_id, PROGRAM_MANAGER)
    data = validate_success(res, 200)
    if isinstance(data, list):
        assert len(data) == 1, \
            f"expected exactly one recap per program, got {len(data)}"
        return data[0]
    return data


# ─── Tier 2/3: composite lifecycle fixtures ───────────


def setup_program_in_design(store_count: int = 200,
                            program_revenue_cents: int = 12000000,
                            program_name: str = "Summer"):
    """Client + program walked DRAFT -> DESIGN with one active MAX_WIDTH_IN=48
    compliance rule. Returns (client, program) with the program's fresh version."""
    client = create_client()
    program = create_program(
        client["id"], store_count=store_count,
        program_revenue_cents=program_revenue_cents, program_name=program_name)
    add_compliance_rule(program["id"])
    program = start_design(program["id"])
    return client, program


def walk_design_to_approved(program_id: str, **design_overrides):
    """Create a design and walk DRAFT -> SUBMITTED -> COMPLIANCE_REVIEW ->
    APPROVED, threading the design's version into the guarded approve."""
    design = create_design_entity(program_id, **design_overrides)
    design = submit_design(design["id"])
    design = begin_review(design["id"])
    design = approve_design(design["id"], design["version"])
    return design


def setup_program_in_production(store_count: int = 200,
                                program_revenue_cents: int = 12000000,
                                design_overrides: dict | None = None):
    """Program in PRODUCTION with one APPROVED design.
    Returns (client, program, design); program carries its fresh version."""
    client, program = setup_program_in_design(
        store_count=store_count, program_revenue_cents=program_revenue_cents)
    design = walk_design_to_approved(program["id"], **(design_overrides or {}))
    program = authorize_production(program["id"])
    return client, program, design


def setup_authorized_run(store_count: int = 200, overage_pct=8,
                         program_revenue_cents: int = 12000000):
    """Program in PRODUCTION + APPROVED design + run authorized (costing
    computed). Returns (program, design, run)."""
    _client, program, design = setup_program_in_production(
        store_count=store_count, program_revenue_cents=program_revenue_cents)
    run = create_production_run_entity(program, design["id"],
                                       overage_pct=overage_pct)
    run = authorize_run(run["id"])
    return program, design, run


def setup_produced_run(store_count: int = 3, overage_pct=0, num_stores: int = 1,
                       program_revenue_cents: int = 1000000):
    """Program in PRODUCTION with `num_stores` stores and a PRODUCED run;
    kits were cascaded into existence at completion (PRD §3.3).
    Returns a context dict: client, program, design, stores, run, kits."""
    client, program, design = setup_program_in_production(
        store_count=store_count, program_revenue_cents=program_revenue_cents)
    stores = [create_store(program["id"], store_number=f"S{i + 1}")
              for i in range(num_stores)]
    run = create_production_run_entity(program, design["id"],
                                       overage_pct=overage_pct)
    run = authorize_run(run["id"])
    run = mark_produced(run["id"])
    kits = list_kits_for_run(run["id"])
    return {
        "client": client,
        "program": program,
        "design": design,
        "stores": stores,
        "run": run,
        "kits": kits,
    }


def setup_kitted_kit(**kwargs):
    """Produced run whose first kit has been kitted. Adds ctx["kit"]."""
    ctx = setup_produced_run(**kwargs)
    ctx["kit"] = mark_kitted(ctx["kits"][0]["id"])
    return ctx


def setup_shipment_scheduled(**kwargs):
    """Kitted kit + SCHEDULED shipment with the canonical ship window.
    Adds ctx["kit"], ctx["shipment"]."""
    ctx = setup_kitted_kit(**kwargs)
    ctx["shipment"] = create_shipment_for_kit(ctx["kit"]["id"])
    return ctx


def setup_shipment_appointment_set(**kwargs):
    """Shipment in APPOINTMENT_SET with an appointment inside the window."""
    ctx = setup_shipment_scheduled(**kwargs)
    ctx["shipment"] = set_appointment(ctx["shipment"]["id"])
    return ctx


def setup_shipped(**kwargs):
    """Shipment SHIPPED (logical clock inside the window); parent kit cascaded
    to SHIPPED. Adds ctx["shipment"], ctx["kit"] (refreshed post-ship)."""
    ctx = setup_shipment_appointment_set(**kwargs)
    set_clock(TIME_INSIDE_WINDOW)
    ctx["shipment"] = ship_shipment(ctx["shipment"]["id"])
    ctx["kit"] = get_kit(ctx["kit"]["id"])
    return ctx


def setup_delivered(**kwargs):
    """Shipment DELIVERED; parent kit cascaded to DELIVERED."""
    ctx = setup_shipped(**kwargs)
    ctx["shipment"] = deliver_shipment(ctx["shipment"]["id"])
    ctx["kit"] = get_kit(ctx["kit"]["id"])
    return ctx


def setup_closed_program(store_count: int = 3, num_stores: int = 1,
                         overage_pct=0, program_revenue_cents: int = 1000000):
    """Full lifecycle through program close: produced run, every store's kit
    kitted, shipped and delivered, then program FULFILLMENT -> CLOSED.
    Returns the produced-run context with ctx["program"] refreshed to CLOSED."""
    ctx = setup_produced_run(
        store_count=store_count, overage_pct=overage_pct,
        num_stores=num_stores, program_revenue_cents=program_revenue_cents)
    ctx["program"] = start_fulfillment(ctx["program"]["id"])
    shipments = []
    for kit in ctx["kits"]:
        kit = mark_kitted(kit["id"])
        shipment = create_shipment_for_kit(kit["id"])
        shipment = set_appointment(shipment["id"])
        shipments.append(shipment)
    set_clock(TIME_INSIDE_WINDOW)
    for shipment in shipments:
        ship_shipment(shipment["id"])
        deliver_shipment(shipment["id"])
    ctx["shipments"] = shipments
    ctx["program"] = close_program(ctx["program"]["id"])
    return ctx


def create_field_service_request_entity(store_id: str, program_id: str,
                                        issue_type: str = "ASSEMBLY_HELP"):
    return get_success_data(api_client.create_field_service_request(
        create_field_service_request_payload(
            store_id, program_id, issue_type=issue_type),
        FIELD_SERVICE_MANAGER))
