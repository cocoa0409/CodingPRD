"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only: the harness restarts the API server before each test, so no
helper may assume a pre-existing row.

`get_success_data()` (the lenient validator) is used throughout so a broken
setup step reports "Setup step failed" rather than an opaque assertion.

Identity threading: `CustomerBuyer` is the one role whose `X-User-ID` is a real
`Customer.id` (PRD §2.1), so every ownership-gated call below is issued with
`make_customer_buyer_headers(customer["id"])`.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import _suffix as _fixture_suffix
from .constants import TEST_DEFAULTS
from .factories import (
    abort_route_payload,
    attach_engagement_payload,
    cancel_order_payload,
    clock_payload,
    counter_contract_payload,
    create_contract_line_payload,
    create_customer_payload,
    create_forward_contract_payload,
    create_index_quote_payload,
    create_lot_payload,
    create_order_line_payload,
    create_order_payload,
    create_product_payload,
    create_route_payload,
    create_route_stop_payload,
    create_silo_payload,
    create_substitution_request_payload,
    create_tech_engagement_payload,
    create_warehouse_zone_payload,
    log_hours_payload,
    quarantine_lot_payload,
    residual_reading_payload,
    short_drop_payload,
    zone_lockout_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_manager_headers,
    make_customer_buyer_headers,
    make_logistics_planner_headers,
    make_pricing_controller_headers,
    make_quality_manager_headers,
    make_technical_specialist_headers,
    make_warehouse_operator_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
PC = TEST_USERS["pricing_controller_headers"]
WO = TEST_USERS["warehouse_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]
TS = TEST_USERS["technical_specialist_headers"]
LP = TEST_USERS["logistics_planner_headers"]

# ---------------------------------------------------------------------------
# Catalogue specs reused across scenarios (PRD §3.1 SKU inputs).
# ---------------------------------------------------------------------------

FLOUR_HRW_INDEXED = {
    "sku": "FLR-HRW-50",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "bulk_capable": True,
    "shelf_life_days": 180,
    "index_code": "HRW_WHEAT",
    "list_price_cents_per_lb": 42,
    "min_rotation_days": 30,
}

FLOUR_HRW_LIST_ONLY = dict(FLOUR_HRW_INDEXED, index_code="NONE")

YEAST_INSTANT = {
    "sku": "YST-INST-01",
    "category": "LEAVENING",
    "allergen_class": "NONE",
    "bulk_capable": False,
    "shelf_life_days": 240,
    "index_code": "NONE",
    "list_price_cents_per_lb": 310,
    "min_rotation_days": 30,
}

RICE_FLOUR = {
    "sku": "RCE-FLR-50",
    "category": "FLOUR",
    "allergen_class": "NONE",
    "bulk_capable": True,
    "shelf_life_days": 200,
    "index_code": "NONE",
    "list_price_cents_per_lb": 88,
    "min_rotation_days": 20,
}

ALMOND_FLOUR = {
    "sku": "ALM-FLR-25",
    "category": "INCLUSION",
    "allergen_class": "TREE_NUT",
    "bulk_capable": False,
    "shelf_life_days": 120,
    "index_code": "NONE",
    "list_price_cents_per_lb": 890,
    "min_rotation_days": 15,
}

PEANUT_PASTE = {
    "sku": "PNT-PST-20",
    "category": "INCLUSION",
    "allergen_class": "PEANUT",
    "bulk_capable": False,
    "shelf_life_days": 150,
    "index_code": "NONE",
    "list_price_cents_per_lb": 640,
    "min_rotation_days": 10,
}

EMULSIFIER = {
    "sku": "SPC-EMU-10",
    "category": "FAT",
    "allergen_class": "NONE",
    "bulk_capable": False,
    "shelf_life_days": 90,
    "index_code": "NONE",
    "list_price_cents_per_lb": 490,
    "min_rotation_days": 0,
}


# ---------------------------------------------------------------------------
# Tier 1 primitives — one API call each.
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """PRD §2.4 — a PlatformAdmin moves the logical clock."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), AM))


def buyer_headers(customer: dict) -> dict:
    return make_customer_buyer_headers(customer["id"])


def create_product(spec: dict = None, **overrides) -> dict:
    payload = create_product_payload(**dict(spec or {}, **overrides))
    return get_success_data(api_client.create_product(payload, PC))


def publish_index_quote(**overrides) -> dict:
    return get_success_data(
        api_client.create_index_quote(create_index_quote_payload(**overrides), PC)
    )


def create_zone(**overrides) -> dict:
    return get_success_data(
        api_client.create_warehouse_zone(create_warehouse_zone_payload(**overrides), WO)
    )


def schedule_zone_lockout(zone_id: str, lockout_start_at: str, lockout_end_at: str) -> dict:
    return get_success_data(
        api_client.set_zone_lockout(
            zone_id, zone_lockout_payload(lockout_start_at, lockout_end_at), QM
        )
    )


def receive_lot(product_id: str, zone_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lot(create_lot_payload(product_id, zone_id, **overrides), WO)
    )


def quarantine_lot(lot_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.quarantine_lot(lot_id, quarantine_lot_payload(**overrides), QM)
    )


def register_silo(customer_id: str, product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_silo(create_silo_payload(customer_id, product_id, **overrides), WO)
    )


def record_residual_reading(silo_id: str, measured_residual_lb) -> dict:
    return get_success_data(
        api_client.create_residual_reading(
            silo_id, residual_reading_payload(measured_residual_lb), WO
        )
    )


def open_order(customer: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(
            create_order_payload(customer["id"], **overrides), buyer_headers(customer)
        )
    )


def add_order_line(customer: dict, order_id: str, product_id: str, quantity_lb, **overrides) -> dict:
    return get_success_data(
        api_client.create_order_line(
            order_id,
            create_order_line_payload(product_id, quantity_lb, **overrides),
            buyer_headers(customer),
        )
    )


def submit_order(customer: dict, order_id: str) -> dict:
    return get_success_data(api_client.submit_order(order_id, {}, buyer_headers(customer)))


def allocate_order(order_id: str) -> dict:
    return get_success_data(api_client.allocate_order(order_id, {}, WO))


def deallocate_order(order_id: str) -> dict:
    return get_success_data(api_client.deallocate_order(order_id, {}, WO))


def cancel_order(customer: dict, order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_order(order_id, cancel_order_payload(**overrides), buyer_headers(customer))
    )


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, PC))


def read_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, AM))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, WO))


def read_zone(zone_id: str) -> dict:
    return get_success_data(api_client.get_warehouse_zone(zone_id, WO))


def read_order_line(order_line_id: str) -> dict:
    return get_success_data(api_client.get_order_line(order_line_id, PC))


def read_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, LP))


def read_route_stop(stop_id: str) -> dict:
    return get_success_data(api_client.get_route_stop(stop_id, LP))


def read_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_forward_contract(contract_id, PC))


def read_contract_line(contract_line_id: str) -> dict:
    return get_success_data(api_client.get_contract_line(contract_line_id, PC))


def read_silo(silo_id: str) -> dict:
    return get_success_data(api_client.get_silo(silo_id, WO))


def read_engagement(engagement_id: str) -> dict:
    return get_success_data(api_client.get_tech_engagement(engagement_id, TS))


def read_substitution_request(request_id: str) -> dict:
    return get_success_data(api_client.get_substitution_request(request_id, QM))


# ---------------------------------------------------------------------------
# Tier 2 — routes, stops and the contract negotiation chain.
# ---------------------------------------------------------------------------


def create_route(**overrides) -> dict:
    return get_success_data(api_client.create_route(create_route_payload(**overrides), LP))


def append_stop(route_id: str, order_id: str, window_start_at: str, window_end_at: str,
                expected_route_version: int = None) -> dict:
    """Appends a drop. PRD §2.6 requires `expected_route_version`; when the
    caller does not pin one we read the route's current `version` first."""
    if expected_route_version is None:
        expected_route_version = read_route(route_id)["version"]
    payload = create_route_stop_payload(
        order_id,
        expected_route_version,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
    )
    return get_success_data(api_client.create_route_stop(route_id, payload, LP))


def seal_route(route_id: str) -> dict:
    return get_success_data(api_client.seal_route(route_id, {}, LP))


def unseal_route(route_id: str) -> dict:
    return get_success_data(api_client.unseal_route(route_id, {}, LP))


def dispatch_route(route_id: str) -> dict:
    return get_success_data(api_client.dispatch_route(route_id, {}, LP))


def abort_route(route_id: str, **overrides) -> dict:
    return get_success_data(api_client.abort_route(route_id, abort_route_payload(**overrides), LP))


def deliver_stop(stop_id: str) -> dict:
    return get_success_data(api_client.deliver_route_stop(stop_id, {}, WO))


def short_stop(stop_id: str, delivered_lb_total, **overrides) -> dict:
    return get_success_data(
        api_client.short_route_stop(stop_id, short_drop_payload(delivered_lb_total, **overrides), WO)
    )


def draft_contract(customer: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_forward_contract(
            create_forward_contract_payload(customer["id"], **overrides), AM
        )
    )


def add_contract_line(contract_id: str, product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract_line(
            contract_id, create_contract_line_payload(product_id, **overrides), AM
        )
    )


def offer_contract(contract_id: str, author_user_id: str = "am-1") -> dict:
    return get_success_data(
        api_client.offer_forward_contract(contract_id, {}, make_account_manager_headers(author_user_id))
    )


def counter_contract(customer: dict, contract_id: str, counter_basis_cents_per_lb: int) -> dict:
    return get_success_data(
        api_client.counter_forward_contract(
            contract_id,
            counter_contract_payload(counter_basis_cents_per_lb),
            buyer_headers(customer),
        )
    )


def activate_contract(contract_id: str, controller_user_id: str = "pc-1") -> dict:
    return get_success_data(
        api_client.activate_forward_contract(
            contract_id, {}, make_pricing_controller_headers(controller_user_id)
        )
    )


def setup_active_contract(customer: dict, product_id: str, volume_committed_lb=20000,
                          basis_cents_per_lb=6, cap_cents_per_lb=None,
                          pricing_mode="ORDER_DATE_INDEX",
                          term_start_on=TEST_DEFAULTS["TERM_START_ON"],
                          term_end_on=TEST_DEFAULTS["TERM_END_ON"]) -> dict:
    """Draft -> line -> offer (am-1) -> activate (pc-1).

    PRD §3.2 requires the activating controller's `X-User-ID` to differ from
    `authored_by_user_id`, so the offer and the activation use different
    operator identifiers.
    """
    contract = draft_contract(
        customer,
        term_start_on=term_start_on,
        term_end_on=term_end_on,
        pricing_mode=pricing_mode,
    )
    line_overrides = {
        "volume_committed_lb": volume_committed_lb,
        "basis_cents_per_lb": basis_cents_per_lb,
    }
    if cap_cents_per_lb is not None:
        line_overrides["cap_cents_per_lb"] = cap_cents_per_lb
    contract_line = add_contract_line(contract["id"], product_id, **line_overrides)
    offer_contract(contract["id"])
    activated = activate_contract(contract["id"])
    return {"contract": activated, "contract_line": contract_line}


def open_engagement(customer: dict, product_id: str, specialist_user_id: str = "ts-1") -> dict:
    return get_success_data(
        api_client.create_tech_engagement(
            create_tech_engagement_payload(customer["id"], product_id),
            make_technical_specialist_headers(specialist_user_id),
        )
    )


def log_hours(engagement_id: str, hours, specialist_user_id: str = "ts-1", **overrides) -> dict:
    return get_success_data(
        api_client.log_tech_hours(
            engagement_id,
            log_hours_payload(hours, **overrides),
            make_technical_specialist_headers(specialist_user_id),
        )
    )


def attach_engagement(engagement_id: str, order_id: str, specialist_user_id: str = "ts-1") -> dict:
    return get_success_data(
        api_client.attach_tech_engagement(
            engagement_id,
            attach_engagement_payload(order_id),
            make_technical_specialist_headers(specialist_user_id),
        )
    )


def raise_substitution_request(order_line_id: str, proposed_product_id: str,
                               expected_order_version: int,
                               specialist_user_id: str = "ts-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_substitution_request(
            create_substitution_request_payload(
                order_line_id, proposed_product_id, expected_order_version, **overrides
            ),
            make_technical_specialist_headers(specialist_user_id),
        )
    )


def claim_substitution_request(request_id: str, manager_user_id: str = "qm-1") -> dict:
    return get_success_data(
        api_client.claim_substitution_request(
            request_id, {}, make_quality_manager_headers(manager_user_id)
        )
    )


def approve_substitution_request(request_id: str, manager_user_id: str = "qm-1") -> dict:
    return get_success_data(
        api_client.approve_substitution_request(
            request_id, {}, make_quality_manager_headers(manager_user_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 3 — a bakery, a catalogue SKU, an allergen-matched zone and stock.
# ---------------------------------------------------------------------------


def setup_bakery_with_stock(product_spec: dict = None, quantity_received_lb=50000,
                            customer_overrides: dict = None,
                            product_overrides: dict = None,
                            zone_overrides: dict = None,
                            lot_overrides: dict = None) -> dict:
    """Customer + SKU + a zone dedicated to that SKU's allergen class + one lot.

    PRD §2.8: "At receipt, a lot may only enter a zone whose `allergen_class` is
    exactly equal to the `allergen_class` of the lot's product", so the zone is
    always created with the product's own class.
    """
    spec = dict(product_spec or {})
    spec.update(product_overrides or {})
    customer = create_customer(**(customer_overrides or {}))
    product = create_product(spec)
    zone = create_zone(
        **dict({"allergen_class": product["allergen_class"]}, **(zone_overrides or {}))
    )
    lot = receive_lot(
        product["id"],
        zone["id"],
        **dict({"quantity_received_lb": quantity_received_lb}, **(lot_overrides or {})),
    )
    return {"customer": customer, "product": product, "zone": zone, "lot": lot}


# ---------------------------------------------------------------------------
# Tier 4 — orders along the two status dimensions of PRD §3.3.
# ---------------------------------------------------------------------------


def setup_new_order(quantity_lb=1000, product_spec: dict = None, **setup_kwargs) -> dict:
    """A `NEW`/`UNPRICED` order carrying exactly one line."""
    base = setup_bakery_with_stock(product_spec=product_spec, **setup_kwargs)
    order = open_order(base["customer"])
    line = add_order_line(base["customer"], order["id"], base["product"]["id"], quantity_lb)
    base["order"] = read_order(order["id"])
    base["order_line"] = line
    return base


def setup_submitted_order(quantity_lb=1000, product_spec: dict = None, **setup_kwargs) -> dict:
    """A `NEW`/`PROVISIONAL` order: submission is what moves `pricing_status`
    from `UNPRICED` to `PROVISIONAL` (PRD §3.3)."""
    scenario = setup_new_order(quantity_lb=quantity_lb, product_spec=product_spec, **setup_kwargs)
    scenario["order"] = submit_order(scenario["customer"], scenario["order"]["id"])
    scenario["order_line"] = read_order_line(scenario["order_line"]["id"])
    return scenario


def setup_allocated_order(quantity_lb=1000, product_spec: dict = None, **setup_kwargs) -> dict:
    """An `ALLOCATED`/`PROVISIONAL` order with its line reserved against a lot."""
    scenario = setup_submitted_order(
        quantity_lb=quantity_lb, product_spec=product_spec, **setup_kwargs
    )
    scenario["order"] = allocate_order(scenario["order"]["id"])
    scenario["order_line"] = read_order_line(scenario["order_line"]["id"])
    scenario["lot"] = read_lot(scenario["lot"]["id"])
    return scenario


def setup_routed_order(quantity_lb=1000, product_spec: dict = None,
                       service_on=TEST_DEFAULTS["SERVICE_DATE"],
                       window_start_at=TEST_DEFAULTS["WINDOW_START_AT"],
                       window_end_at=TEST_DEFAULTS["WINDOW_END_AT"],
                       route_overrides: dict = None, **setup_kwargs) -> dict:
    """A `ROUTED` order sitting on a `PLANNED` stop of a `PLANNING` route.

    PRD §3.9: "The order must be sitting at `ALLOCATED`, and appending the stop
    advances it `ALLOCATED → ROUTED`".
    """
    scenario = setup_allocated_order(
        quantity_lb=quantity_lb, product_spec=product_spec, **setup_kwargs
    )
    route = create_route(**dict({"service_on": service_on}, **(route_overrides or {})))
    stop = append_stop(route["id"], scenario["order"]["id"], window_start_at, window_end_at)
    scenario["route"] = read_route(route["id"])
    scenario["route_stop"] = stop
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


def setup_sealed_route(**kwargs) -> dict:
    scenario = setup_routed_order(**kwargs)
    scenario["route"] = seal_route(scenario["route"]["id"])
    scenario["route_stop"] = read_route_stop(scenario["route_stop"]["id"])
    return scenario


def setup_loaded_order(**kwargs) -> dict:
    """A `LOADED` order on a `DISPATCHED` route.

    PRD §3.10: "A `LogisticsPlanner` moves a route `SEALED → DISPATCHED` only
    when the logical clock date equals the route's `service_on`", so the clock
    is advanced onto the service date first.
    """
    scenario = setup_sealed_route(**kwargs)
    set_clock(scenario["route"]["service_on"])
    scenario["route"] = dispatch_route(scenario["route"]["id"])
    scenario["order"] = read_order(scenario["order"]["id"])
    scenario["route_stop"] = read_route_stop(scenario["route_stop"]["id"])
    return scenario


def setup_delivered_order(**kwargs) -> dict:
    """A `DELIVERED`/`PROVISIONAL` order — the state final settlement needs."""
    scenario = setup_loaded_order(**kwargs)
    scenario["route_stop"] = deliver_stop(scenario["route_stop"]["id"])
    scenario["order"] = read_order(scenario["order"]["id"])
    scenario["order_line"] = read_order_line(scenario["order_line"]["id"])
    scenario["lot"] = read_lot(scenario["lot"]["id"])
    scenario["route"] = read_route(scenario["route"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 5 — bulk silo fills, support engagements and substitution proposals.
# ---------------------------------------------------------------------------


def setup_bulk_order(quantity_lb=5000, capacity_lb=60000, min_fill_lb=2000,
                     residual_lb=None, product_spec: dict = None,
                     silo_overrides: dict = None, **setup_kwargs) -> dict:
    """A `BULK` order whose SKU is `bulk_capable` and whose bakery owns a silo.

    PRD §3.3: "If the order's `delivery_mode` is `BULK`, every line's product
    must have `bulk_capable` set to true and the bakery must have a silo
    registered for that SKU".
    """
    spec = dict(product_spec or RICE_FLOUR)
    spec["bulk_capable"] = True
    base = setup_bakery_with_stock(product_spec=spec, **setup_kwargs)
    silo = register_silo(
        base["customer"]["id"],
        base["product"]["id"],
        **dict({"capacity_lb": capacity_lb, "min_fill_lb": min_fill_lb},
               **(silo_overrides or {})),
    )
    if residual_lb is not None:
        silo = record_residual_reading(silo["id"], residual_lb)
    order = open_order(base["customer"], delivery_mode="BULK")
    line = add_order_line(base["customer"], order["id"], base["product"]["id"], quantity_lb)
    base["silo"] = silo
    base["order"] = read_order(order["id"])
    base["order_line"] = line
    return base


def setup_billable_engagement(hours=4.0, product_spec: dict = None,
                              specialist_user_id: str = "ts-1", **setup_kwargs) -> dict:
    """An engagement that has crossed the qualifying threshold.

    PRD §3.11: "the moment `hours_logged` reaches 4.0, the boundary being
    inclusive, an `OPEN` engagement moves itself to `BILLABLE` and the attach
    fee is computed."
    """
    scenario = setup_submitted_order(product_spec=product_spec, **setup_kwargs)
    engagement = open_engagement(
        scenario["customer"], scenario["product"]["id"], specialist_user_id=specialist_user_id
    )
    engagement = log_hours(engagement["id"], hours, specialist_user_id=specialist_user_id)
    scenario["engagement"] = engagement
    return scenario


def setup_substitution_request(proposed_spec: dict = None, quantity_lb=1000,
                               product_spec: dict = None,
                               specialist_user_id: str = "ts-1", **setup_kwargs) -> dict:
    """A `REQUESTED` proposal on the single line of an `ALLOCATED` order, with a
    second SKU (and a matching zone plus lot) already in stock to swap to."""
    scenario = setup_allocated_order(
        quantity_lb=quantity_lb, product_spec=product_spec, **setup_kwargs
    )
    proposed = create_product(dict(proposed_spec or YEAST_INSTANT))
    proposed_zone = create_zone(allergen_class=proposed["allergen_class"])
    proposed_lot = receive_lot(proposed["id"], proposed_zone["id"], quantity_received_lb=50000)
    request = raise_substitution_request(
        scenario["order_line"]["id"],
        proposed["id"],
        scenario["order"]["version"],
        specialist_user_id=specialist_user_id,
    )
    scenario["proposed_product"] = proposed
    scenario["proposed_zone"] = proposed_zone
    scenario["proposed_lot"] = proposed_lot
    scenario["substitution_request"] = request
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


def setup_claimed_substitution(manager_user_id: str = "qm-1", **kwargs) -> dict:
    """An `UNDER_REVIEW` proposal — the only state approval and rejection accept.

    PRD §3.8: "Claiming a request moves it `REQUESTED → UNDER_REVIEW` and
    records the claiming manager in `decided_by_user_id`".
    """
    scenario = setup_substitution_request(**kwargs)
    scenario["substitution_request"] = claim_substitution_request(
        scenario["substitution_request"]["id"], manager_user_id=manager_user_id
    )
    return scenario


def setup_contracted_order(volume_committed_lb=20000, basis_cents_per_lb=6,
                           cap_cents_per_lb=None, pricing_mode="ORDER_DATE_INDEX",
                           quantity_lb=1000, product_spec: dict = None,
                           index_price_cents_per_lb=38, quote_effective_on="2026-08-01T00:00:00Z",
                           **setup_kwargs) -> dict:
    """An `UNPRICED` order nominating an `ACTIVE` contract, with the index board
    already carrying a prevailing quote for the SKU's index."""
    spec = dict(product_spec or FLOUR_HRW_INDEXED)
    base = setup_bakery_with_stock(product_spec=spec, **setup_kwargs)
    quote = None
    if spec.get("index_code", "NONE") != "NONE":
        quote = publish_index_quote(
            index_code=spec["index_code"],
            effective_on=quote_effective_on,
            price_cents_per_lb=index_price_cents_per_lb,
        )
    contract_bundle = setup_active_contract(
        base["customer"],
        base["product"]["id"],
        volume_committed_lb=volume_committed_lb,
        basis_cents_per_lb=basis_cents_per_lb,
        cap_cents_per_lb=cap_cents_per_lb,
        pricing_mode=pricing_mode,
    )
    order = open_order(base["customer"], contract_id=contract_bundle["contract"]["id"])
    line = add_order_line(base["customer"], order["id"], base["product"]["id"], quantity_lb)
    base.update(contract_bundle)
    base["index_quote"] = quote
    base["order"] = read_order(order["id"])
    base["order_line"] = line
    return base


def setup_indexed_contract_delivered_order(
    pricing_mode="DELIVERY_DATE_INDEX",
    quotes=((("2026-07-01T00:00:00Z"), 38), (("2026-09-10T00:00:00Z"), 47)),
    quantity_lb=20000,
    basis_cents_per_lb=6,
    volume_committed_lb=100000,
    open_clock="2026-08-05T00:00:00Z",
    service_on="2026-09-15T00:00:00Z",
    window_start_at="2026-09-15T08:00:00Z",
    window_end_at="2026-09-15T10:00:00Z",
    vehicle_capacity_lb=24000,
    deliver=True,
) -> dict:
    """Drives one indexed flour order all the way to `DELIVERED`/`PROVISIONAL`.

    The clock opens at `open_clock` so `order_placed_on` is stamped there, and is
    advanced onto the route's `service_on` before dispatch, so `delivered_on`
    lands on a later date than `order_placed_on`. That separation is what makes
    the two observation-date variants of PRD §3.4 distinguishable.
    """
    set_clock(open_clock)
    customer = create_customer(legal_name=f"Indexed Bakehouse {_fixture_suffix()}")
    product = create_product(FLOUR_HRW_INDEXED)
    for effective_on, price_cents_per_lb in quotes:
        publish_index_quote(
            index_code=FLOUR_HRW_INDEXED["index_code"],
            effective_on=effective_on,
            price_cents_per_lb=price_cents_per_lb,
        )
    zone = create_zone(allergen_class=product["allergen_class"])
    lot = receive_lot(product["id"], zone["id"], quantity_received_lb=50000)
    bundle = setup_active_contract(
        customer,
        product["id"],
        volume_committed_lb=volume_committed_lb,
        basis_cents_per_lb=basis_cents_per_lb,
        pricing_mode=pricing_mode,
        term_start_on="2026-08-01T00:00:00Z",
        term_end_on="2026-12-31T00:00:00Z",
    )
    order = open_order(customer, contract_id=bundle["contract"]["id"])
    line = add_order_line(customer, order["id"], product["id"], quantity_lb)
    provisional = submit_order(customer, order["id"])
    allocate_order(order["id"])
    route = create_route(service_on=service_on, vehicle_capacity_lb=vehicle_capacity_lb)
    stop = append_stop(route["id"], order["id"], window_start_at, window_end_at)
    seal_route(route["id"])
    set_clock(service_on)
    dispatch_route(route["id"])
    if deliver:
        deliver_stop(stop["id"])
    return {
        "customer": customer,
        "product": product,
        "zone": zone,
        "lot": lot,
        "contract": bundle["contract"],
        "contract_line": bundle["contract_line"],
        "order": read_order(order["id"]),
        "order_line": read_order_line(line["id"]),
        "provisional_order": provisional,
        "route": read_route(route["id"]),
        "route_stop": read_route_stop(stop["id"]),
    }
