"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors instead of confusing assertion failures.

Identity threading: CustomerRep is bound to a persisted Customer, so every
ownership-gated call uses make_customer_rep_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import WEEK_1
from .factories import (
    claim_offer_payload,
    create_allocation_payload,
    create_claim_payload,
    create_fabrication_batch_payload,
    create_forward_contract_payload,
    create_certificate_payload,
    create_price_sheet_payload,
    create_product_payload,
    create_purchase_order_payload,
    create_sheet_line_payload,
    create_shipment_payload,
    create_supplier_payload,
    create_customer_payload,
    create_warehouse_payload,
    create_yield_spec_payload,
    inspect_lot_payload,
    receive_po_payload,
    set_clock_payload,
    temperature_reading_payload,
)
from .test_users import TEST_USERS, make_customer_rep_headers

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]
GRADER = TEST_USERS["quality_grader_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


def _ok(step, resp):
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 0 — single-resource reference data
# ---------------------------------------------------------------------------

def create_product(product_code=None, kind="PRIMAL", species="BEEF",
                   max_fat_pct=12.0, shelf_life_days=21,
                   required_temp_max_f=40, **overrides):
    payload = create_product_payload(
        kind=kind, species=species, shelf_life_days=shelf_life_days,
        required_temp_max_f=required_temp_max_f, **overrides,
    )
    if product_code is not None:
        payload["product_code"] = product_code
    if max_fat_pct is None:
        payload.pop("max_fat_pct", None)
    else:
        payload["max_fat_pct"] = max_fat_pct
    resp = api_client.create_product(payload, ADMIN)
    return _ok("create_product", resp)


def create_carcass_product(product_code=None, shelf_life_days=30, **overrides):
    """Carcass-kind products carry a null max_fat_pct (PRD §3.1)."""
    return create_product(product_code=product_code, kind="CARCASS",
                          max_fat_pct=None, shelf_life_days=shelf_life_days,
                          **overrides)


def create_supplier(**overrides):
    resp = api_client.create_supplier(create_supplier_payload(**overrides), ADMIN)
    return _ok("create_supplier", resp)


def create_customer(**overrides):
    resp = api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    return _ok("create_customer", resp)


def create_warehouse(**overrides):
    resp = api_client.create_warehouse(create_warehouse_payload(**overrides), ADMIN)
    return _ok("create_warehouse", resp)


def create_yield_spec(carcass_product_id, output_product_id,
                      expected_yield_pct=50.0, min_yield_pct=45.0,
                      max_yield_pct=55.0, **overrides):
    resp = api_client.create_yield_spec(
        create_yield_spec_payload(
            carcass_product_id, output_product_id, expected_yield_pct,
            min_yield_pct, max_yield_pct, **overrides,
        ),
        ADMIN,
    )
    return _ok("create_yield_spec", resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return _ok("set_clock", resp)


# ---------------------------------------------------------------------------
# Tier 1 — price sheet cycle
# ---------------------------------------------------------------------------

def create_sheet(week_start_date=WEEK_1, supersedes_sheet_id=None):
    payload = create_price_sheet_payload(week_start_date)
    if supersedes_sheet_id is not None:
        payload["supersedes_sheet_id"] = supersedes_sheet_id
    resp = api_client.create_price_sheet(payload, TRADER)
    return _ok("create_price_sheet", resp)


def add_sheet_line(sheet_id, product_id, price_per_lb_cents=700,
                   weekly_supply_lbs=100_000):
    resp = api_client.add_sheet_line(
        sheet_id,
        create_sheet_line_payload(product_id, price_per_lb_cents,
                                  weekly_supply_lbs),
        TRADER,
    )
    return _ok("add_sheet_line", resp)


def publish_sheet(sheet_id):
    resp = api_client.publish_price_sheet(sheet_id, ADMIN)
    return _ok("publish_price_sheet", resp)


def setup_published_sheet_with_line(product_id=None, week_start_date=WEEK_1,
                                    price_per_lb_cents=700,
                                    weekly_supply_lbs=100_000):
    """A PUBLISHED sheet carrying one line. Returns (product, sheet, line)."""
    product = product_id and api_client.get_product(product_id, ADMIN)
    if product_id is None:
        product = create_product()
    else:
        product = get_success_data(product)
    sheet = create_sheet(week_start_date)
    line = add_sheet_line(sheet["id"], product["id"], price_per_lb_cents,
                          weekly_supply_lbs)
    publish_sheet(sheet["id"])
    return product, sheet, line


# ---------------------------------------------------------------------------
# Tier 2 — procurement: purchase orders and receiving
# ---------------------------------------------------------------------------

def book_po(supplier_id, product_id, ordered_weight_lbs=1000,
            contract_price_per_cwt_cents=20_000,
            required_delivery_date="2026-08-04", **overrides):
    resp = api_client.create_purchase_order(
        create_purchase_order_payload(
            supplier_id, product_id, ordered_weight_lbs,
            contract_price_per_cwt_cents, required_delivery_date, **overrides,
        ),
        TRADER,
    )
    return _ok("create_purchase_order", resp)


def receive_po(po_id, warehouse_id, received_weight_lbs=1000, lot_code=None,
               production_date="2026-08-01"):
    """Receive and return (po_data, lot_data) — the lot is IN_INSPECTION."""
    resp = api_client.receive_purchase_order(
        po_id,
        receive_po_payload(warehouse_id, received_weight_lbs, lot_code,
                           production_date),
        OPERATOR,
    )
    po_data = _ok("receive_purchase_order", resp)
    lots = _ok("list_inventory_lots",
               api_client.list_inventory_lots(ADMIN, params={"po_id": po_id}))
    assert isinstance(lots, list) and len(lots) == 1, \
        f"Setup failed: expected exactly one lot for po {po_id}, got {lots}"
    return po_data, lots[0]


def get_po_lot(po_id):
    lots = _ok("list_inventory_lots",
               api_client.list_inventory_lots(ADMIN, params={"po_id": po_id}))
    assert isinstance(lots, list) and len(lots) == 1, \
        f"Setup failed: expected exactly one lot for po {po_id}, got {lots}"
    return lots[0]


# ---------------------------------------------------------------------------
# Tier 3 — lot pipeline: receive + inspect to AVAILABLE
# ---------------------------------------------------------------------------

def setup_available_lot(kind="PRIMAL", max_fat_pct=12.0, shelf_life_days=21,
                        weight=1000, measured_fat_pct=10.0,
                        production_date="2026-08-01",
                        clock="2026-08-03T00:00:00Z", capacity_lbs=100_000,
                        product_code=None):
    """Full procurement chain ending in one AVAILABLE lot.

    Returns dict(product, supplier, warehouse, po, lot).
    """
    if kind == "CARCASS":
        product = create_carcass_product(product_code=product_code,
                                         shelf_life_days=shelf_life_days)
    else:
        product = create_product(product_code=product_code, kind=kind,
                                 max_fat_pct=max_fat_pct,
                                 shelf_life_days=shelf_life_days)
    supplier = create_supplier()
    warehouse = create_warehouse(capacity_lbs=capacity_lbs)
    if clock is not None:
        set_clock(clock)
    po = book_po(supplier["id"], product["id"], ordered_weight_lbs=weight)
    _, lot = receive_po(po["id"], warehouse["id"], received_weight_lbs=weight,
                        production_date=production_date)
    resp = api_client.inspect_lot(lot["id"],
                                  inspect_lot_payload(measured_fat_pct), GRADER)
    lot = _ok("inspect_lot", resp)
    return {
        "product": product, "supplier": supplier, "warehouse": warehouse,
        "po": po, "lot": lot,
    }


# ---------------------------------------------------------------------------
# Tier 4 — allocation pipeline: PUBLISHED sheet + CONFIRMED allocation
# ---------------------------------------------------------------------------

def setup_confirmed_allocation(requested_lbs=500, price_per_lb_cents=700,
                               weekly_supply_lbs=100_000,
                               credit_limit_cents=100_000_000,
                               allocation_tier="TIER_1", lot_weight=1000,
                               forward_contract=None, shelf_life_days=21,
                               production_date="2026-08-01",
                               clock="2026-08-03T00:00:00Z",
                               week_start_date=WEEK_1):
    """Available stock + PUBLISHED sheet + one CONFIRMED allocation.

    Returns dict(product, supplier, warehouse, customer, sheet, line, po, lot,
    allocation).
    """
    ctx = setup_available_lot(max_fat_pct=12.0, shelf_life_days=shelf_life_days,
                              weight=lot_weight, production_date=production_date,
                              clock=clock)
    customer = create_customer(credit_limit_cents=credit_limit_cents,
                               allocation_tier=allocation_tier)
    sheet = create_sheet(week_start_date)
    line = add_sheet_line(sheet["id"], ctx["product"]["id"],
                          price_per_lb_cents, weekly_supply_lbs)
    publish_sheet(sheet["id"])
    payload = create_allocation_payload(customer["id"], line["id"],
                                        requested_lbs)
    if forward_contract is not None:
        payload["forward_contract_id"] = forward_contract["id"]
    resp = api_client.create_allocation(
        payload, make_customer_rep_headers(customer["id"]))
    allocation = _ok("create_allocation", resp)
    _ok("run_allocation", api_client.run_allocation(sheet["id"], RISK))
    allocation = _ok("get_allocation",
                     api_client.get_allocation(allocation["id"], ADMIN))
    ctx.update({
        "customer": customer, "sheet": sheet, "line": line,
        "allocation": allocation,
    })
    return ctx


def request_allocation(customer, line_id, requested_lbs,
                       forward_contract_id=None):
    """Create a REQUESTED allocation as the owning CustomerRep."""
    payload = create_allocation_payload(customer["id"], line_id, requested_lbs)
    if forward_contract_id is not None:
        payload["forward_contract_id"] = forward_contract_id
    resp = api_client.create_allocation(
        payload, make_customer_rep_headers(customer["id"]))
    return _ok("create_allocation", resp)


def run_sheet(sheet_id):
    """Run the allocation waterfall and return the run summary."""
    resp = api_client.run_allocation(sheet_id, RISK)
    return _ok("run_allocation", resp)


def get_allocation(allocation_id):
    return _ok("get_allocation",
               api_client.get_allocation(allocation_id, ADMIN))


def get_customer(customer_id):
    return _ok("get_customer", api_client.get_customer(customer_id, ADMIN))


def get_line(line_id):
    return _ok("get_price_sheet_line",
               api_client.get_price_sheet_line(line_id, ADMIN))


def get_lot(lot_id):
    return _ok("get_inventory_lot",
               api_client.get_inventory_lot(lot_id, ADMIN))


def get_warehouse(warehouse_id):
    return _ok("get_warehouse", api_client.get_warehouse(warehouse_id, ADMIN))


def get_sheet(sheet_id):
    return _ok("get_price_sheet", api_client.get_price_sheet(sheet_id, ADMIN))


def get_po(po_id):
    return _ok("get_purchase_order",
               api_client.get_purchase_order(po_id, ADMIN))


def get_contract(contract_id):
    return _ok("get_forward_contract",
               api_client.get_forward_contract(contract_id, ADMIN))


def get_claim(claim_id):
    return _ok("get_claim", api_client.get_claim(claim_id, ADMIN))


def get_shipment(shipment_id):
    return _ok("get_shipment", api_client.get_shipment(shipment_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 5 — shipment and claim pipelines
# ---------------------------------------------------------------------------

def create_forward_contract(customer, product_id, committed_lbs=100,
                            fixed_price_per_lb_cents=650,
                            delivery_week_start=WEEK_1):
    resp = api_client.create_forward_contract(
        create_forward_contract_payload(
            customer["id"], product_id, committed_lbs,
            fixed_price_per_lb_cents, delivery_week_start,
        ),
        TRADER,
    )
    return _ok("create_forward_contract", resp)


def load_out_shipment(allocation_id, shipped_lbs, lot_ids=None,
                      carrier_name="CAR-1", trailer_temp_setpoint_f=36.0):
    payload = create_shipment_payload(
        allocation_id, shipped_lbs, carrier_name, trailer_temp_setpoint_f,
    )
    if lot_ids is not None:
        payload["lot_ids"] = lot_ids
    resp = api_client.create_shipment(payload, OPERATOR)
    return _ok("create_shipment", resp)


def add_reading(shipment_id, reading_f, recorded_at="2026-08-03T08:00:00Z"):
    resp = api_client.add_temperature_reading(
        shipment_id, temperature_reading_payload(reading_f, recorded_at),
        OPERATOR,
    )
    return _ok("add_temperature_reading", resp)


def depart(shipment_id):
    return _ok("depart_shipment", api_client.depart_shipment(shipment_id, OPERATOR))


def deliver(shipment_id, customer):
    return _ok(
        "deliver_shipment",
        api_client.deliver_shipment(
            shipment_id, make_customer_rep_headers(customer["id"])),
    )


def setup_staging_shipment(shipped_lbs=500, **kwargs):
    """CONFIRMED allocation + STAGING shipment (no readings yet)."""
    ctx = setup_confirmed_allocation(requested_lbs=shipped_lbs, **kwargs)
    shipment = load_out_shipment(ctx["allocation"]["id"], shipped_lbs)
    ctx["shipment"] = shipment
    return ctx


def setup_delivered_shipment(shipped_lbs=500, breach=False,
                             compliant_reading_f=38.0,
                             breach_reading_f=41.5, **kwargs):
    """Full pipeline through DELIVERED.

    One compliant reading is recorded before departure; when breach=True a
    second reading above the product's ceiling is appended while IN_TRANSIT,
    leaving temp_compliance BREACHED.
    """
    ctx = setup_staging_shipment(shipped_lbs=shipped_lbs, **kwargs)
    ship_id = ctx["shipment"]["id"]
    add_reading(ship_id, compliant_reading_f)
    depart(ship_id)
    if breach:
        add_reading(ship_id, breach_reading_f, "2026-08-04T08:00:00Z")
    ctx["shipment"] = deliver(ship_id, ctx["customer"])
    return ctx


def setup_filed_claim(claim_type="QUALITY_DEFECT", claimed_amount_cents=200_000,
                      **kwargs):
    """DELIVERED shipment + one FILED claim. Returns the pipeline context."""
    ctx = setup_delivered_shipment(**kwargs)
    resp = api_client.create_claim(
        create_claim_payload(ctx["shipment"]["id"], claim_type,
                             claimed_amount_cents),
        make_customer_rep_headers(ctx["customer"]["id"]),
    )
    ctx["claim"] = _ok("create_claim", resp)
    return ctx


def post_offer(claim_id, offer_cents, expected_claim_version):
    resp = api_client.post_claim_offer(
        claim_id, claim_offer_payload(offer_cents, expected_claim_version),
        ADJUSTER,
    )
    return _ok("post_claim_offer", resp)


def counter_claim(claim_id, customer, counter_amount_cents):
    resp = api_client.counter_claim(
        claim_id, {"counter_amount_cents": counter_amount_cents},
        make_customer_rep_headers(customer["id"]),
    )
    return _ok("counter_claim", resp)


def accept_claim(claim_id, customer):
    return _ok(
        "accept_claim",
        api_client.accept_claim(
            claim_id, make_customer_rep_headers(customer["id"])),
    )


# ---------------------------------------------------------------------------
# Tier 6 — grading / fabrication helpers
# ---------------------------------------------------------------------------

def issue_grade_certificate(lot_id, grade_result="CHOICE",
                            issue_date="2026-08-03", certificate_number=None):
    resp = api_client.create_inspection_certificate(
        create_certificate_payload(
            lot_id, "USDA_GRADE", grade_result, certificate_number,
            issue_date=issue_date,
        ),
        GRADER,
    )
    return _ok("create_inspection_certificate", resp)


def inspect_lot(lot_id, measured_fat_pct=10.0):
    resp = api_client.inspect_lot(
        lot_id, inspect_lot_payload(measured_fat_pct), GRADER)
    return _ok("inspect_lot", resp)
