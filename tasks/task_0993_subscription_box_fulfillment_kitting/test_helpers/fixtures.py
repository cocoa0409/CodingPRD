"""Composite setup helpers (PRD §3 workflows).

Every helper builds preconditions from scratch using only PRD-declared
endpoints; the harness restarts the server before each test, so nothing is
carried over. Setup calls use get_success_data() so failures surface as
clear "Setup failed" messages. Ownership-gated ClientOps calls always use
make_client_ops_headers(client_id) with the real Client.id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_START_ISO,
    DEFAULT_PERIOD,
    PERIOD_END_ISO,
    TEST_DEFAULTS,
    WAVE_END_ISO,
    WAVE_START_ISO,
)
from .factories import (
    assign_shipments_payload,
    bom_line,
    bom_lines_payload,
    churn_payload,
    clock_payload,
    complete_kitting_payload,
    create_assembly_run_payload,
    create_box_plan_payload,
    create_client_payload,
    create_component_payload,
    create_kit_revision_payload,
    create_return_case_payload,
    create_shipping_wave_payload,
    credit_adjustment_payload,
    import_batch_payload,
    receipt_payload,
    rework_payload,
    scan_payload,
    subscriber_row,
)
from .test_users import TEST_USERS, make_client_ops_headers

ADMIN = TEST_USERS["platform_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
SUPPORT = TEST_USERS["customer_service_headers"]


def _setup_failed(step: str, resp) -> AssertionError:
    try:
        body = resp.text
    except Exception:
        body = "<no body>"
    return AssertionError(f"Setup failed at {step}: HTTP {resp.status_code} {body}")


def _ok(resp, step: str, expect_array: bool = False):
    if resp.status_code >= 300:
        raise _setup_failed(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START_ISO) -> dict:
    """Advance the logical clock (PlatformAdmin-only capability, PRD §2.5)."""
    return _ok(api_client.set_clock(clock_payload(to_iso8601), ADMIN), "set_clock")


def create_client(wallet_cents: int = 0, name: str = None,
                  billing_email: str = None) -> dict:
    """Register a client; optionally top up the prepaid wallet. Returns the
    client as of the latest mutation."""
    overrides = {}
    if name is not None:
        overrides["name"] = name
    if billing_email is not None:
        overrides["billing_email"] = billing_email
    client = _ok(api_client.create_client(create_client_payload(**overrides), ADMIN),
                 "create_client")
    if wallet_cents:
        client = _ok(
            api_client.create_credit_adjustment(
                client["id"], credit_adjustment_payload(wallet_cents), BILLING),
            "credit_adjustment",
        )
    return client


def get_client(client_id: str) -> dict:
    return _ok(api_client.get_client(client_id, BILLING), "get_client")


def create_component(sku: str, unit_cost_cents: int = TEST_DEFAULTS["UNIT_COST_CENTS"],
                     reorder_point_units: int = 0, name: str = None) -> dict:
    overrides = {}
    if name is not None:
        overrides["name"] = name
    return _ok(
        api_client.create_component(
            create_component_payload(sku=sku, unit_cost_cents=unit_cost_cents,
                                     reorder_point_units=reorder_point_units, **overrides),
            WAREHOUSE),
        "create_component",
    )


def receive_stock(component_id: str, quantity: int, note: str = None) -> dict:
    """Receipt carrying the component's current version (OCC, PRD §2.8)."""
    current = get_component(component_id)
    return _ok(
        api_client.create_receipt(
            component_id,
            receipt_payload(quantity, current["version"], note=note),
            WAREHOUSE),
        "create_receipt",
    )


def create_stocked_component(sku: str, quantity: int,
                             reorder_point_units: int = 0,
                             unit_cost_cents: int = TEST_DEFAULTS["UNIT_COST_CENTS"]) -> dict:
    """Register a component and record an initial receipt. Returns latest state."""
    component = create_component(sku, unit_cost_cents=unit_cost_cents,
                                 reorder_point_units=reorder_point_units)
    if quantity:
        component = receive_stock(component["id"], quantity)
    return component


def get_component(component_id: str) -> dict:
    return _ok(api_client.get_component(component_id, WAREHOUSE), "get_component")


def create_plan(client_id: str, sku: str,
                price_per_box_cents: int = TEST_DEFAULTS["PRICE_PER_BOX_CENTS"],
                shipping_weight_grams: int = TEST_DEFAULTS["SHIPPING_WEIGHT_GRAMS"],
                name: str = None) -> dict:
    overrides = {}
    if name is not None:
        overrides["name"] = name
    return _ok(
        api_client.create_box_plan(
            create_box_plan_payload(
                client_id,
                sku=sku,
                price_per_box_cents=price_per_box_cents,
                shipping_weight_grams=shipping_weight_grams,
                **overrides),
            make_client_ops_headers(client_id)),
        "create_box_plan",
    )


def get_plan(plan_id: str, client_id: str = None) -> dict:
    headers = make_client_ops_headers(client_id) if client_id else WAREHOUSE
    return _ok(api_client.get_box_plan(plan_id, headers), "get_box_plan")


# ---------------------------------------------------------------------------
# Tier 2: kit revision pipeline
# ---------------------------------------------------------------------------

def create_revision(plan_id: str, client_id: str) -> dict:
    """Create a DRAFT revision, OCC-guarded on the plan's current version."""
    plan = get_plan(plan_id, client_id)
    return _ok(
        api_client.create_kit_revision(
            plan_id,
            create_kit_revision_payload(plan["version"]),
            make_client_ops_headers(client_id)),
        "create_kit_revision",
    )


def put_bom(revision_id: str, client_id: str, lines: list) -> list:
    return _ok(
        api_client.put_bom_lines(revision_id, bom_lines_payload(lines),
                                 make_client_ops_headers(client_id)),
        "put_bom_lines",
    )


def approve_revision(revision_id: str, client_id: str) -> dict:
    return _ok(api_client.approve_kit_revision(revision_id,
                                               make_client_ops_headers(client_id)),
               "approve_kit_revision")


def activate_plan(plan_id: str, client_id: str) -> dict:
    return _ok(api_client.activate_box_plan(plan_id, make_client_ops_headers(client_id)),
               "activate_box_plan")


def create_active_plan_with_bom(client_id: str, sku: str, bom: list,
                                price_per_box_cents: int = TEST_DEFAULTS["PRICE_PER_BOX_CENTS"],
                                shipping_weight_grams: int = TEST_DEFAULTS["SHIPPING_WEIGHT_GRAMS"],
                                name: str = None) -> tuple:
    """Plan + DRAFT revision + BOM lines + approve + activate.

    bom: list of (component_id, qty_per_box) tuples.
    Returns (plan, revision) as of their latest states.
    """
    plan = create_plan(client_id, sku, price_per_box_cents=price_per_box_cents,
                       shipping_weight_grams=shipping_weight_grams, name=name)
    revision = create_revision(plan["id"], client_id)
    put_bom(revision["id"], client_id,
            [bom_line(cid, qty) for cid, qty in bom])
    revision = approve_revision(revision["id"], client_id)
    plan = activate_plan(plan["id"], client_id)
    return plan, revision


# ---------------------------------------------------------------------------
# Tier 2: subscriber imports
# ---------------------------------------------------------------------------

def import_subscribers(plan_id: str, client_id: str, rows: list) -> tuple:
    """Upload + commit a batch. Returns (committed_batch, [subscribers])."""
    batch = _ok(
        api_client.create_import_batch(plan_id, import_batch_payload(rows),
                                       make_client_ops_headers(client_id)),
        "create_import_batch",
    )
    batch = _ok(api_client.commit_import_batch(batch["id"],
                                               make_client_ops_headers(client_id)),
                "commit_import_batch")
    resp = api_client.list_subscribers(make_client_ops_headers(client_id),
                                       params={"import_batch_id": batch["id"]})
    if resp.status_code >= 300:
        raise _setup_failed("list_subscribers", resp)
    subscribers, _meta = validate_paginated(resp)
    return batch, subscribers


def import_named_subscribers(plan_id: str, client_id: str, emails_zones: list) -> list:
    """emails_zones: [(email, zone), ...]. Returns subscriber dicts."""
    rows = [subscriber_row(email, zone) for email, zone in emails_zones]
    _batch, subscribers = import_subscribers(plan_id, client_id, rows)
    return subscribers


# ---------------------------------------------------------------------------
# Tier 3: assembly run lifecycle
# ---------------------------------------------------------------------------

def create_run(plan_id: str, period: str = DEFAULT_PERIOD) -> dict:
    return _ok(
        api_client.create_assembly_run(create_assembly_run_payload(plan_id, period),
                                       WAREHOUSE),
        "create_assembly_run",
    )


def get_run(run_id: str) -> dict:
    return _ok(api_client.get_assembly_run(run_id, WAREHOUSE), "get_assembly_run")


def lock_run(run_id: str) -> dict:
    return _ok(api_client.lock_assembly_run(run_id, WAREHOUSE), "lock_assembly_run")


def run_to_kitting(run_id: str) -> dict:
    lock_run(run_id)
    return _ok(api_client.start_kitting(run_id, WAREHOUSE), "start_kitting")


def run_to_kitted(run_id: str, actual_kitted_count: int) -> dict:
    run_to_kitting(run_id)
    return _ok(
        api_client.complete_kitting(run_id, complete_kitting_payload(actual_kitted_count),
                                    WAREHOUSE),
        "complete_kitting",
    )


def list_run_shipments(run_id: str, fulfill_status: str = None,
                       label_status: str = None) -> list:
    params = {}
    if fulfill_status:
        params["fulfill_status"] = fulfill_status
    if label_status:
        params["label_status"] = label_status
    resp = api_client.list_run_shipments(run_id, WAREHOUSE, params=params or None)
    if resp.status_code >= 300:
        raise _setup_failed("list_run_shipments", resp)
    shipments, _meta = validate_paginated(resp)
    return shipments


def list_run_events(run_id: str, event_type: str = None) -> list:
    params = {"event_type": event_type} if event_type else None
    resp = api_client.list_run_inventory_events(run_id, WAREHOUSE, params=params)
    if resp.status_code >= 300:
        raise _setup_failed("list_run_inventory_events", resp)
    events, _meta = validate_paginated(resp)
    return events


def list_component_events(component_id: str, event_type: str = None) -> list:
    params = {"event_type": event_type} if event_type else None
    resp = api_client.list_component_inventory_events(component_id, WAREHOUSE,
                                                      params=params)
    if resp.status_code >= 300:
        raise _setup_failed("list_component_inventory_events", resp)
    events, _meta = validate_paginated(resp)
    return events


# ---------------------------------------------------------------------------
# Tier 4: full pipeline composite
# ---------------------------------------------------------------------------

def setup_kitted_scenario(sku_prefix: str, num_subscribers: int = 1,
                          actual_kitted_count: int = None,
                          qty_per_box: int = 1, stock: int = 100,
                          price_per_box_cents: int = TEST_DEFAULTS["PRICE_PER_BOX_CENTS"],
                          shipping_weight_grams: int = TEST_DEFAULTS["SHIPPING_WEIGHT_GRAMS"],
                          wallet_cents: int = TEST_DEFAULTS["WALLET_SEED_CENTS"],
                          zone: int = TEST_DEFAULTS["ZONE"],
                          reorder_point_units: int = 0,
                          period: str = DEFAULT_PERIOD,
                          run_state: str = "KITTED") -> dict:
    """Full pipeline: client+wallet -> stocked component -> ACTIVE plan with
    one-line BOM -> imported ACTIVE subscribers -> run walked to run_state.

    run_state: "DRAFT" | "LOCKED" | "KITTING" | "KITTED".
    Returns dict: client, component, plan, revision, subscribers, run, shipments.
    """
    set_clock()
    client = create_client(wallet_cents=wallet_cents, name=f"{sku_prefix} Client",
                           billing_email=f"{sku_prefix.lower()}@acme.test")
    component = create_stocked_component(f"CMP-{sku_prefix}", stock,
                                         reorder_point_units=reorder_point_units)
    plan, revision = create_active_plan_with_bom(
        client["id"], f"PL-{sku_prefix}",
        [(component["id"], qty_per_box)],
        price_per_box_cents=price_per_box_cents,
        shipping_weight_grams=shipping_weight_grams)
    subscribers = import_named_subscribers(
        plan["id"], client["id"],
        [(f"{sku_prefix.lower()}s{i}@x.test", zone) for i in range(1, num_subscribers + 1)])
    run = create_run(plan["id"], period)
    if run_state in ("LOCKED", "KITTING", "KITTED"):
        run = lock_run(run["id"])
    if run_state in ("KITTING", "KITTED"):
        run = _ok(api_client.start_kitting(run["id"], WAREHOUSE), "start_kitting")
    if run_state == "KITTED":
        actual = actual_kitted_count if actual_kitted_count is not None else num_subscribers
        run = _ok(
            api_client.complete_kitting(run["id"], complete_kitting_payload(actual),
                                        WAREHOUSE),
            "complete_kitting",
        )
    shipments = list_run_shipments(run["id"]) if run_state in ("LOCKED", "KITTING", "KITTED") else []
    return {
        "client": client,
        "component": get_component(component["id"]),
        "plan": plan,
        "revision": revision,
        "subscribers": subscribers,
        "run": run,
        "shipments": shipments,
    }


# ---------------------------------------------------------------------------
# Tier 4: shipping waves and labels
# ---------------------------------------------------------------------------

def create_wave(carrier: str = "USPS", service_level: str = "GROUND",
                pickup_start: str = WAVE_START_ISO,
                pickup_end: str = WAVE_END_ISO) -> dict:
    return _ok(
        api_client.create_shipping_wave(
            create_shipping_wave_payload(carrier=carrier, service_level=service_level,
                                         pickup_start=pickup_start, pickup_end=pickup_end),
            WAREHOUSE),
        "create_shipping_wave",
    )


def get_wave(wave_id: str) -> dict:
    return _ok(api_client.get_shipping_wave(wave_id, WAREHOUSE), "get_shipping_wave")


def assign_to_wave(wave_id: str, shipment_ids: list) -> dict:
    return _ok(
        api_client.assign_shipments(wave_id, assign_shipments_payload(shipment_ids),
                                    WAREHOUSE),
        "assign_shipments",
    )


def manifest_wave(wave_id: str) -> dict:
    return _ok(api_client.manifest_wave(wave_id, WAREHOUSE), "manifest_wave")


def assign_and_manifest(wave_id: str, shipment_ids: list) -> dict:
    assign_to_wave(wave_id, shipment_ids)
    return manifest_wave(wave_id)


def ship_via_wave(shipment_ids: list, carrier: str = "USPS",
                  service_level: str = "GROUND",
                  pickup_start: str = WAVE_START_ISO,
                  pickup_end: str = WAVE_END_ISO,
                  tender: bool = False, scan_type: str = None) -> tuple:
    """Create a wave, assign the shipments, manifest; optionally tender and
    scan each shipment. Returns (wave, [latest shipment dicts])."""
    wave = create_wave(carrier, service_level, pickup_start, pickup_end)
    wave = assign_and_manifest(wave["id"], shipment_ids)
    if tender:
        wave = _ok(api_client.tender_wave(wave["id"], WAREHOUSE), "tender_wave")
    if scan_type:
        for shipment_id in shipment_ids:
            _ok(api_client.scan_shipment(shipment_id, scan_payload(scan_type), WAREHOUSE),
                "scan_shipment")
    shipments = [
        _ok(api_client.get_shipment(sid, WAREHOUSE), "get_shipment")
        for sid in shipment_ids
    ]
    return wave, shipments


def get_shipment(shipment_id: str) -> dict:
    return _ok(api_client.get_shipment(shipment_id, WAREHOUSE), "get_shipment")


# ---------------------------------------------------------------------------
# Tier 4: return cases
# ---------------------------------------------------------------------------

def open_return_case(shipment_id: str, reason: str = "DAMAGED",
                     requested_resolution: str = "REFUND") -> dict:
    return _ok(
        api_client.create_return_case(
            create_return_case_payload(shipment_id, reason, requested_resolution),
            SUPPORT),
        "create_return_case",
    )


def return_case_to_received(case_id: str) -> dict:
    """REQUESTED -> APPROVED -> RECEIVED."""
    _ok(api_client.approve_return_case(case_id, SUPPORT), "approve_return_case")
    return _ok(api_client.receive_return_case(case_id, WAREHOUSE), "receive_return_case")


# ---------------------------------------------------------------------------
# Tier 5: billing statements
# ---------------------------------------------------------------------------

def get_statement_for_client(client_id: str, period: str = None) -> dict:
    """Return the client's single statement (asserts exactly one exists)."""
    params = {"period": period} if period else None
    resp = api_client.list_client_billing_statements(client_id, BILLING, params=params)
    if resp.status_code >= 300:
        raise _setup_failed("list_client_billing_statements", resp)
    statements, meta = validate_paginated(resp)
    assert len(statements) == 1, (
        f"Setup failed: expected exactly 1 statement for client {client_id}, "
        f"found {len(statements)}"
    )
    return statements[0]


def get_statement(statement_id: str) -> dict:
    return _ok(api_client.get_billing_statement(statement_id, BILLING),
               "get_billing_statement")


def finalize_statement(statement_id: str, clock: str = PERIOD_END_ISO) -> dict:
    """Advance the clock past period end, then finalize."""
    set_clock(clock)
    return _ok(api_client.finalize_statement(statement_id, BILLING), "finalize_statement")
