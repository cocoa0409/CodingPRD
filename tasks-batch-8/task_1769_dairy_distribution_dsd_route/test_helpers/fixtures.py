"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database and
the logical clock at the startup default (PRD §2.4). These helpers build the
multi-call preconditions (distributor -> route -> store -> activation ->
product -> driver -> period/announcement -> trip -> order -> confirm ->
pre-cool -> depart -> deliver) so tests can focus on assertions.

All helpers use get_success_data() so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion deep inside a test.

Identity threading (PRD §2.1): DistributorOwner calls are made with
make_distributor_owner_headers(distributor_id), RouteDriver calls with
make_driver_headers(driver_id), StoreReceiver calls with
make_store_receiver_headers(store_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_announcement_payload,
    create_crate_transaction_payload,
    create_distributor_payload,
    create_driver_payload,
    create_listing_payload,
    create_offer_payload,
    create_order_payload,
    create_pricing_period_payload,
    create_product_payload,
    create_return_payload,
    create_route_payload,
    create_standing_par_payload,
    create_store_patch_payload,
    create_store_payload,
    create_temperature_reading_payload,
    create_trip_payload,
    delivered_line,
    order_line,
)
from .test_users import (
    TEST_USERS,
    make_distributor_owner_headers,
    make_driver_headers,
    make_store_receiver_headers,
)

TM = TEST_USERS["territory_manager_headers"]
MA = TEST_USERS["market_admin_headers"]
QI = TEST_USERS["quality_inspector_headers"]


def _setup_fail(action, resp):
    raise AssertionError(
        f"Setup failed during {action}: {resp.status_code} {resp.text}"
        if hasattr(resp, "status_code") else f"Setup failed during {action}"
    )


def _unwrap(resp, action):
    try:
        return get_success_data(resp)
    except AssertionError:
        _setup_fail(action, resp)


# ----------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------
def set_clock(to_iso8601) -> dict:
    return _unwrap(api_client.set_clock(to_iso8601, TM), "set_clock")


# ----------------------------------------------------------------------
# Tier 1: single-entity creators
# ----------------------------------------------------------------------
def create_distributor(name="Dairy Dist", license_number="LIC-1", **over) -> dict:
    return _unwrap(
        api_client.create_distributor(
            create_distributor_payload(name=name, license_number=license_number, **over), TM
        ),
        "create_distributor",
    )


def create_route(distributor_id, route_code="R-1", **over) -> dict:
    return _unwrap(
        api_client.create_route(create_route_payload(distributor_id, route_code, **over), TM),
        "create_route",
    )


def activate_route(route_id) -> dict:
    return _unwrap(api_client.activate_route(route_id, TM), "activate_route")


def suspend_route(route_id) -> dict:
    return _unwrap(api_client.suspend_route(route_id, TM), "suspend_route")


def retire_route(route_id) -> dict:
    return _unwrap(api_client.retire_route(route_id, TM), "retire_route")


def create_store(route_id, distributor_id, store_code="S-1", **over) -> dict:
    # Fixture default: a generous credit limit so confirm-time credit checks do
    # not interfere; tests exercising the credit rule pass an explicit limit.
    over.setdefault("credit_limit_cents", 100000000)
    return _unwrap(
        api_client.create_store(
            create_store_payload(route_id, store_code, **over),
            make_distributor_owner_headers(distributor_id),
        ),
        "create_store",
    )


def get_store(store_id) -> dict:
    return _unwrap(api_client.get_store(store_id, TM), "get_store")


def patch_store(store_id, distributor_id, expected_store_version, **fields) -> dict:
    return _unwrap(
        api_client.patch_store(
            store_id,
            create_store_patch_payload(expected_store_version, **fields),
            make_distributor_owner_headers(distributor_id),
        ),
        "patch_store",
    )


def create_driver(distributor_id, name="Dan Driver", cdl_class="A") -> dict:
    return _unwrap(
        api_client.create_driver(
            create_driver_payload(distributor_id, name=name, cdl_class=cdl_class),
            make_distributor_owner_headers(distributor_id),
        ),
        "create_driver",
    )


def create_product(sku, **over) -> dict:
    return _unwrap(
        api_client.create_product(create_product_payload(sku, **over), TM),
        "create_product",
    )


def upsert_par(store_id, distributor_id, product_id, expected_store_version, **pars) -> dict:
    return _unwrap(
        api_client.upsert_standing_par(
            store_id,
            create_standing_par_payload(product_id, expected_store_version, **pars),
            make_distributor_owner_headers(distributor_id),
        ),
        "upsert_par",
    )


def create_pricing_period(month="2026-08") -> dict:
    return _unwrap(
        api_client.create_pricing_period(create_pricing_period_payload(month), MA),
        "create_pricing_period",
    )


def get_pricing_period(period_id) -> dict:
    return _unwrap(api_client.get_pricing_period(period_id, MA), "get_pricing_period")


def publish_announcement(
    period_id,
    kind="PROVISIONAL",
    class_i_base_cents_per_cwt=None,
    processor_assessment_cents_per_cwt=None,
    hauling_cents_per_cwt=None,
    diesel_index_cents=None,
    base=None,
    assessment=None,
    hauling=None,
    diesel=None,
) -> dict:
    """Publish an announcement, transparently fetching the period's current
    version for the OCC field (PRD §2.6). Accepts the short aliases
    base/assessment/hauling/diesel as well as the full payload field names."""
    if class_i_base_cents_per_cwt is None:
        class_i_base_cents_per_cwt = base if base is not None else 2000
    if processor_assessment_cents_per_cwt is None:
        processor_assessment_cents_per_cwt = assessment if assessment is not None else 35
    if hauling_cents_per_cwt is None:
        hauling_cents_per_cwt = hauling if hauling is not None else 60
    if diesel_index_cents is None:
        diesel_index_cents = diesel if diesel is not None else 299
    period = get_pricing_period(period_id)
    payload = create_announcement_payload(
        kind,
        period["version"],
        class_i_base_cents_per_cwt=class_i_base_cents_per_cwt,
        processor_assessment_cents_per_cwt=processor_assessment_cents_per_cwt,
        hauling_cents_per_cwt=hauling_cents_per_cwt,
        diesel_index_cents=diesel_index_cents,
    )
    return _unwrap(
        api_client.publish_announcement(period_id, payload, MA),
        "publish_announcement",
    )


def create_trip(route_id, driver_id, distributor_id, service_date="2026-08-10", **over) -> dict:
    return _unwrap(
        api_client.create_trip(
            create_trip_payload(route_id, driver_id, service_date, **over),
            make_distributor_owner_headers(distributor_id),
        ),
        "create_trip",
    )


def get_trip(trip_id) -> dict:
    return _unwrap(api_client.get_trip(trip_id, TM), "get_trip")


def create_order(store_id, trip_id, lines, distributor_id, **over) -> dict:
    return _unwrap(
        api_client.create_order(
            create_order_payload(store_id, trip_id, lines, **over),
            make_distributor_owner_headers(distributor_id),
        ),
        "create_order",
    )


def confirm_order(order_id, distributor_id) -> dict:
    return _unwrap(
        api_client.confirm_order(order_id, make_distributor_owner_headers(distributor_id)),
        "confirm_order",
    )


def cancel_order(order_id, distributor_id) -> dict:
    return _unwrap(
        api_client.cancel_order(order_id, make_distributor_owner_headers(distributor_id)),
        "cancel_order",
    )


def add_reading(trip_id, driver_id, recorded_at, temp_tenths_f, zone="BOX") -> dict:
    return _unwrap(
        api_client.add_temperature_reading(
            trip_id,
            create_temperature_reading_payload(recorded_at, temp_tenths_f, zone),
            make_driver_headers(driver_id),
        ),
        "add_reading",
    )


def depart_trip(trip_id, driver_id) -> dict:
    return _unwrap(
        api_client.depart_trip(trip_id, make_driver_headers(driver_id)),
        "depart_trip",
    )


def complete_trip(trip_id, driver_id) -> dict:
    return _unwrap(
        api_client.complete_trip(trip_id, make_driver_headers(driver_id)),
        "complete_trip",
    )


def deliver_order(order_id, driver_id, delivered_lines) -> dict:
    return _unwrap(
        api_client.deliver_order(
            order_id, {"delivered_lines": delivered_lines}, make_driver_headers(driver_id)
        ),
        "deliver_order",
    )


def get_invoice_for_order(order_id) -> dict:
    data = _unwrap(api_client.list_invoices(TM, params={"order_id": order_id}), "list_invoices")
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one invoice for order {order_id}"
    )
    return data[0]


def create_return(order_id, store_id, pickup_trip_id, product_id, quantity_units,
                  reason_code, scanned_code_date, driver_id) -> dict:
    return _unwrap(
        api_client.create_return(
            create_return_payload(
                order_id, store_id, pickup_trip_id, product_id,
                quantity_units, reason_code, scanned_code_date,
            ),
            make_driver_headers(driver_id),
        ),
        "create_return",
    )


def approve_return(return_id, distributor_id) -> dict:
    return _unwrap(
        api_client.approve_return(return_id, make_distributor_owner_headers(distributor_id)),
        "approve_return",
    )


def pay_invoice(invoice_id, store_id, amount_cents) -> dict:
    return _unwrap(
        api_client.pay_invoice(
            invoice_id, {"amount_cents": amount_cents},
            make_store_receiver_headers(store_id),
        ),
        "pay_invoice",
    )


def record_crate_transaction(store_id, kind, crate_count, caller_id, role, note=None) -> dict:
    payload = create_crate_transaction_payload(kind, crate_count)
    if note is not None:
        payload["note"] = note
    headers = (
        make_driver_headers(caller_id)
        if role == "RouteDriver"
        else make_distributor_owner_headers(caller_id)
    )
    return _unwrap(
        api_client.create_crate_transaction(store_id, payload, headers),
        "record_crate_transaction",
    )


# ----------------------------------------------------------------------
# Tier 2: composite scenarios
# ----------------------------------------------------------------------
def setup_route_with_store(
    prefix="T",
    credit_limit_cents=100000000,
    credit_price_basis=None,
    store_overrides=None,
    route_overrides=None,
    activate=True,
) -> dict:
    """Distributor + route + store; route optionally activated (PRD §3.1)."""
    route_kw = dict(route_overrides or {})
    if credit_price_basis is not None:
        route_kw["credit_price_basis"] = credit_price_basis
    distributor = create_distributor(name=f"Dairy Dist {prefix}", license_number=f"LIC-{prefix}-1")
    route = create_route(distributor["id"], route_code=f"R-{prefix}", **route_kw)
    store_kw = {"credit_limit_cents": credit_limit_cents}
    store_kw.update(store_overrides or {})
    store = create_store(route["id"], distributor["id"], store_code=f"S-{prefix}", **store_kw)
    if activate:
        route = activate_route(route["id"])
    return {"distributor": distributor, "route": route, "store": store}


def setup_planned_order(
    prefix="P",
    quantity_units=10,
    service_date="2026-08-10",
    window=("08:00", "08:30"),
    product_overrides=None,
    case_capacity=1000,
    **scenario_kw,
) -> dict:
    """Route ACTIVE + store + product + driver + trip PLANNED + order PLANNED."""
    refs = setup_route_with_store(prefix=prefix, **scenario_kw)
    d_id = refs["distributor"]["id"]
    if product_overrides is None:
        product_overrides = {"list_price_cents": 250, "shelf_life_days": 30}
    product = create_product(f"SKU-{prefix}", **product_overrides)
    driver = create_driver(d_id, name=f"Driver {prefix}")
    trip = create_trip(
        refs["route"]["id"], driver["id"], d_id,
        service_date=service_date, case_capacity=case_capacity,
    )
    order = create_order(
        refs["store"]["id"], trip["id"],
        [order_line(product["id"], quantity_units)],
        d_id,
        delivery_window_start=f"{service_date}T{window[0]}:00Z",
        delivery_window_end=f"{service_date}T{window[1]}:00Z",
    )
    refs.update({"product": product, "driver": driver, "trip": trip, "order": order})
    return refs


def precool_and_depart(trip_id, driver_id, service_date="2026-08-10",
                       reading_time="04:30:00", temp_tenths_f=380) -> dict:
    """Clock to the pre-cool instant, log a compliant BOX reading, depart."""
    at = f"{service_date}T{reading_time}Z"
    set_clock(at)
    add_reading(trip_id, driver_id, at, temp_tenths_f, zone="BOX")
    return depart_trip(trip_id, driver_id)


def setup_delivered_order(
    prefix="D",
    quantity_units=10,
    service_date="2026-08-10",
    code_date="2026-09-01",
    window=("08:00", "08:30"),
    product_overrides=None,
    announcement=None,
    month="2026-08",
    case_capacity=3000,
    precool_time="04:30:00",
    deliver_time="09:00:00",
    **scenario_kw,
) -> dict:
    """Full chain through DELIVERED: order confirmed, trip pre-cooled and
    departed, delivery recorded, invoice fetched (PRD §3.4 side effects).

    announcement: optional dict(kind=..., base=..., assessment=..., hauling=...,
    diesel=...) — when provided, a pricing period for `month` is created and the
    announcement published before the trip runs.
    """
    set_clock(f"{service_date}T00:00:00Z")
    refs = setup_planned_order(
        prefix=prefix,
        quantity_units=quantity_units,
        service_date=service_date,
        window=window,
        product_overrides=product_overrides,
        case_capacity=case_capacity,
        **scenario_kw,
    )
    d_id = refs["distributor"]["id"]
    if announcement is not None:
        ann = dict(announcement)
        kind = ann.pop("kind", "PROVISIONAL")
        period = create_pricing_period(month)
        refs["period"] = period
        refs["announcement"] = publish_announcement(
            period["id"],
            kind=kind,
            class_i_base_cents_per_cwt=ann.get("base", 2000),
            processor_assessment_cents_per_cwt=ann.get("assessment", 35),
            hauling_cents_per_cwt=ann.get("hauling", 60),
            diesel_index_cents=ann.get("diesel", 299),
        )
    refs["order"] = confirm_order(refs["order"]["id"], d_id)
    precool_and_depart(
        refs["trip"]["id"], refs["driver"]["id"], service_date, precool_time
    )
    set_clock(f"{service_date}T{deliver_time}Z")
    refs["order"] = deliver_order(
        refs["order"]["id"], refs["driver"]["id"],
        [delivered_line(refs["product"]["id"], quantity_units, code_date)],
    )
    refs["invoice"] = get_invoice_for_order(refs["order"]["id"])
    return refs


def setup_two_delivery_scenario(
    prefix="S",
    first_units=10,
    second_units=2,
    service_date="2026-08-10",
    code_date="2026-09-01",
    window=("08:00", "08:30"),
    second_window=("08:45", "09:15"),
    product_overrides=None,
    second_product_overrides=None,
    announcement=None,
    month="2026-08",
    case_capacity=3000,
    **scenario_kw,
) -> dict:
    """One trip carrying two DELIVERED orders for the same store at two distinct
    dock windows — produces invoice INV_A for the first product and INV_B for
    the second. Both orders are created while the trip is still PLANNED."""
    set_clock(f"{service_date}T00:00:00Z")
    refs = setup_planned_order(
        prefix=prefix,
        quantity_units=first_units,
        service_date=service_date,
        window=window,
        product_overrides=product_overrides,
        case_capacity=case_capacity,
        **scenario_kw,
    )
    d_id = refs["distributor"]["id"]
    if announcement is not None:
        ann = dict(announcement)
        kind = ann.pop("kind", "PROVISIONAL")
        period = create_pricing_period(month)
        refs["period"] = period
        refs["announcement"] = publish_announcement(
            period["id"],
            kind=kind,
            class_i_base_cents_per_cwt=ann.get("base", 2000),
            processor_assessment_cents_per_cwt=ann.get("assessment", 35),
            hauling_cents_per_cwt=ann.get("hauling", 60),
            diesel_index_cents=ann.get("diesel", 299),
        )
    product_b = create_product(
        f"SKU-{prefix}-B", **(second_product_overrides or {"list_price_cents": 250})
    )
    order_b = create_order(
        refs["store"]["id"], refs["trip"]["id"],
        [order_line(product_b["id"], second_units)],
        d_id,
        delivery_window_start=f"{service_date}T{second_window[0]}:00Z",
        delivery_window_end=f"{service_date}T{second_window[1]}:00Z",
    )
    refs["order"] = confirm_order(refs["order"]["id"], d_id)
    order_b = confirm_order(order_b["id"], d_id)
    precool_and_depart(refs["trip"]["id"], refs["driver"]["id"], service_date)
    set_clock(f"{service_date}T09:00:00Z")
    refs["order"] = deliver_order(
        refs["order"]["id"], refs["driver"]["id"],
        [delivered_line(refs["product"]["id"], first_units, code_date)],
    )
    refs["order_b"] = deliver_order(
        order_b["id"], refs["driver"]["id"],
        [delivered_line(product_b["id"], second_units, code_date)],
    )
    refs["product_b"] = product_b
    refs["invoice"] = get_invoice_for_order(refs["order"]["id"])
    refs["invoice_b"] = get_invoice_for_order(order_b["id"])
    return refs


def run_trip_readings(trip_id, driver_id, readings) -> None:
    """Log a sequence of readings, advancing the clock to each reading's
    recorded_at first (readings must be <= the current clock, PRD §3.4).

    readings: list of (recorded_at_iso8601, temp_tenths_f, zone).
    """
    for recorded_at, temp, zone in readings:
        set_clock(recorded_at)
        add_reading(trip_id, driver_id, recorded_at, temp, zone)


def complete_trip_at(trip_id, driver_id, completed_at) -> dict:
    """Advance the clock and complete the trip (finalizes cold-chain math)."""
    set_clock(completed_at)
    return complete_trip(trip_id, driver_id)
