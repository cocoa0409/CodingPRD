"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database, so these helpers build the full
catalog -> customer -> truck -> order -> load -> batch -> pour -> complete ->
invoice chains that the pricing, QC, and billing rules need. Setup calls use
the lenient get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_cement_price_index_payload,
    create_customer_payload,
    create_mix_design_payload,
    create_order_payload,
    create_plant_payload,
    create_price_list_payload,
    create_truck_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_driver_headers, make_qc_headers

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BATCH_OP = TEST_USERS["batch_operator_headers"]
DRV1 = TEST_USERS["driver_headers"]
DRV2 = TEST_USERS["driver2_headers"]
QC_A = TEST_USERS["qc_a_headers"]
QC_B = TEST_USERS["qc_b_headers"]
QC_C = TEST_USERS["qc_c_headers"]


def set_clock(to_iso8601: str):
    """Move the server logical clock to the supplied instant."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PM)
    )


def create_plant(**overrides):
    """Create a plant; returns (plant_dict, initial_version)."""
    data = get_success_data(api_client.create_plant(create_plant_payload(**overrides), PM))
    return data, data["version"]


def create_active_mix(plant_id, **overrides):
    """Create a mix design and activate it (DRAFT -> ACTIVE)."""
    mix = get_success_data(
        api_client.create_mix_design(create_mix_design_payload(plant_id, **overrides), PM)
    )
    return get_success_data(api_client.activate_mix_design(mix["id"], PM))


def create_draft_mix(plant_id, **overrides):
    """Create a mix design left in DRAFT."""
    return get_success_data(
        api_client.create_mix_design(create_mix_design_payload(plant_id, **overrides), PM)
    )


def create_active_price_list(plant_id, mix_design_id, plant_version, **overrides):
    """Create-and-activate a price list (supersedes any prior ACTIVE list)."""
    return get_success_data(
        api_client.create_price_list(
            create_price_list_payload(plant_id, mix_design_id, plant_version, **overrides),
            PM,
        )
    )


def publish_index(plant_id, effective_month, index_points):
    """Publish a monthly cement price index row."""
    return get_success_data(
        api_client.create_cement_price_index(
            create_cement_price_index_payload(plant_id, effective_month, index_points), PM
        )
    )


def create_customer(**overrides):
    """Create a customer; returns the customer dict."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), PM))


def create_truck(plant_id, **overrides):
    """Register a truck (AVAILABLE, last_available_at stamped from the clock)."""
    return get_success_data(
        api_client.create_truck(create_truck_payload(plant_id, **overrides), DISP)
    )


def place_order(plant_id, mix_design_id, customer_id, **overrides):
    """Place an order as the owning customer (customer_id from X-User-ID)."""
    return get_success_data(
        api_client.create_order(
            create_order_payload(plant_id, mix_design_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def confirm_order(order_id):
    """Confirm a PLACED order; returns the CONFIRMED order (with its version)."""
    return get_success_data(api_client.confirm_order(order_id, DISP))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, DISP))


def get_load(load_id):
    return get_success_data(api_client.get_load(load_id, DISP))


def get_truck(truck_id):
    return get_success_data(api_client.get_truck(truck_id, DISP))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, PM))


def get_cylinder_set(cylinder_set_id):
    return get_success_data(api_client.get_cylinder_set(cylinder_set_id, QC_A))


def schedule_load(order_id, order_version, qty_yd3=8.0, truck_id=None):
    """Schedule a load on an order; returns the SCHEDULED load dict."""
    payload = {"qty_yd3": qty_yd3, "expected_order_version": order_version}
    if truck_id is not None:
        payload["truck_id"] = truck_id
    return get_success_data(api_client.schedule_load(order_id, payload, DISP))


def schedule_load_fresh(order_id, qty_yd3=8.0, truck_id=None):
    """Re-read the order and schedule a load with the current version."""
    current = get_order(order_id)
    return schedule_load(order_id, current["version"], qty_yd3=qty_yd3, truck_id=truck_id)


def batch_load(load_id, batch_time, extra_batch_water_gal=None):
    """Batch a SCHEDULED load at an explicit batch_time."""
    payload = {"batch_time": batch_time}
    if extra_batch_water_gal is not None:
        payload["extra_batch_water_gal"] = extra_batch_water_gal
    return get_success_data(api_client.batch_load(load_id, payload, BATCH_OP))


# ---------------------------------------------------------------------------
# Tier 2: standard catalog composites
# ---------------------------------------------------------------------------

def setup_standard_catalog(indices=None, customer_overrides=None, admixtures=None,
                           mix_overrides=None):
    """Plant + ACTIVE mix + ACTIVE price list + indices + one customer.

    indices: list of (effective_month, index_points); None publishes nothing.
    Returns dict with plant, mix, price_list, customer, plus their versions.
    """
    plant, plant_version = create_plant()
    mix_kwargs = dict(mix_overrides or {})
    if admixtures is not None:
        mix_kwargs["admixtures"] = admixtures
    mix = create_active_mix(plant["id"], **mix_kwargs)
    price_list = create_active_price_list(plant["id"], mix["id"], plant_version)
    for month, points in (indices or []):
        publish_index(plant["id"], month, points)
    customer = create_customer(**(customer_overrides or {}))
    return {
        "plant": plant,
        "plant_version": plant_version,
        "mix": mix,
        "price_list": price_list,
        "customer": customer,
    }


def setup_confirmed_order(indices=None, customer_overrides=None, order_overrides=None,
                          truck_fleet_numbers=("T1",), admixtures=None):
    """Standard catalog + trucks + one CONFIRMED order.

    Returns dict with the catalog entries, trucks {fleet: dict}, the order,
    and the order's post-confirm version.
    """
    catalog = setup_standard_catalog(
        indices=indices, customer_overrides=customer_overrides, admixtures=admixtures
    )
    trucks = {fleet: create_truck(catalog["plant"]["id"], fleet_number=fleet)
              for fleet in truck_fleet_numbers}
    order = place_order(
        catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"],
        **(order_overrides or {}),
    )
    confirmed = confirm_order(order["id"])
    catalog.update({
        "trucks": trucks,
        "order": confirmed,
        "order_version": confirmed["version"],
    })
    return catalog


def setup_scheduled_load(indices=None, order_overrides=None, load_qty=8.0,
                         customer_overrides=None, admixtures=None):
    """Confirmed order + one SCHEDULED load on truck T1.

    Returns (context, load). context carries plant/mix/price_list/customer/order/T1.
    """
    ctx = setup_confirmed_order(
        indices=indices,
        customer_overrides=customer_overrides,
        order_overrides=order_overrides,
        truck_fleet_numbers=("T1",),
        admixtures=admixtures,
    )
    load = schedule_load(ctx["order"]["id"], ctx["order_version"],
                         qty_yd3=load_qty, truck_id=ctx["trucks"]["T1"]["id"])
    ctx["load"] = load
    return ctx, load


def setup_batched_load(indices=None, order_overrides=None, load_qty=8.0,
                       batch_time="2026-08-15T10:00:00Z", batch_extra_water=None,
                       customer_overrides=None, admixtures=None):
    """One load driven SCHEDULED -> BATCHED. Returns (context, load)."""
    ctx, load = setup_scheduled_load(
        indices=indices, order_overrides=order_overrides, load_qty=load_qty,
        customer_overrides=customer_overrides, admixtures=admixtures,
    )
    load = batch_load(load["id"], batch_time, batch_extra_water)
    ctx["load"] = load
    return ctx, load


def setup_pouring_load(indices=None, order_overrides=None, load_qty=8.0,
                       batch_time="2026-08-15T10:00:00Z", arrive_at="2026-08-15T10:30:00Z",
                       customer_overrides=None, admixtures=None, driver=DRV1):
    """One load driven through to POURING (batch -> depart -> arrive -> start-pour).

    Returns (context, load).
    """
    ctx, load = setup_batched_load(
        indices=indices, order_overrides=order_overrides, load_qty=load_qty,
        batch_time=batch_time, customer_overrides=customer_overrides, admixtures=admixtures,
    )
    get_success_data(api_client.depart_load(load["id"], driver))
    set_clock(arrive_at)
    get_success_data(api_client.arrive_load(load["id"], driver))
    load = get_success_data(api_client.start_pour_load(load["id"], driver))
    ctx["load"] = load
    return ctx, load


def setup_completed_load(indices=None, order_overrides=None, load_qty=8.0,
                         batch_time="2026-08-15T10:00:00Z", arrive_at="2026-08-15T10:30:00Z",
                         complete_at="2026-08-15T12:00:00Z", start_pour=True,
                         customer_overrides=None, admixtures=None, driver=DRV1):
    """One load driven to COMPLETED (full discharge). Returns (context, load).

    With the defaults (qty 8.0 order / 8.0 load) the completion crosses the
    fulfillment boundary, so the order flips to DELIVERED and a DRAFT invoice
    is auto-created.
    """
    if start_pour:
        ctx, load = setup_pouring_load(
            indices=indices, order_overrides=order_overrides, load_qty=load_qty,
            batch_time=batch_time, arrive_at=arrive_at,
            customer_overrides=customer_overrides, admixtures=admixtures, driver=driver,
        )
    else:
        ctx, load = setup_batched_load(
            indices=indices, order_overrides=order_overrides, load_qty=load_qty,
            batch_time=batch_time, customer_overrides=customer_overrides,
            admixtures=admixtures,
        )
        get_success_data(api_client.depart_load(load["id"], driver))
        set_clock(arrive_at)
        get_success_data(api_client.arrive_load(load["id"], driver))
    set_clock(complete_at)
    load = get_success_data(
        api_client.complete_load(load["id"], {"discharged_qty_yd3": load_qty}, driver)
    )
    ctx["load"] = load
    return ctx, load


def get_invoice_for_order(order_id):
    """Fetch the single auto-created invoice for a delivered order."""
    invoices, meta = _list_invoices({"order_id": order_id})
    assert len(invoices) >= 1, "expected an auto-created invoice for the order"
    return invoices[0]


def _list_invoices(params):
    res = api_client.list_invoices(DISP, params=params)
    body = res.json()
    assert 200 <= res.status_code < 300, f"list invoices failed: {body}"
    return body["data"], body.get("meta", {})


def setup_issued_invoice(indices=None, **kwargs):
    """Delivered order + its auto-created invoice issued (ISSUED).

    Returns (context, load, invoice).
    """
    ctx, load = setup_completed_load(indices=indices, **kwargs)
    invoice = get_invoice_for_order(ctx["order"]["id"])
    invoice = get_success_data(api_client.issue_invoice(invoice["id"], PM))
    return ctx, load, invoice


def setup_cylinder_set_on_pouring_load(cast_clock="2026-08-15T10:35:00Z", num_cylinders=3,
                                       caster=QC_A, **kwargs):
    """Pouring load with a cylinder set cast on it. Returns (context, load, cset)."""
    ctx, load = setup_pouring_load(**kwargs)
    set_clock(cast_clock)
    cset = get_success_data(
        api_client.create_cylinder_set(load["id"], {"num_cylinders": num_cylinders}, caster)
    )
    return ctx, load, cset


def record_seven_day_break(cset_id, strength_psi, at_iso, recorder=QC_B):
    """Advance the clock and record the SEVEN_DAY break."""
    set_clock(at_iso)
    return get_success_data(
        api_client.record_break(
            cset_id, {"break_type": "SEVEN_DAY", "strength_psi": strength_psi}, recorder
        )
    )


def record_twenty_eight_day_break(cset_id, strength_psi, at_iso, recorder=QC_B):
    """Advance the clock and record the TWENTY_EIGHT_DAY break."""
    set_clock(at_iso)
    return get_success_data(
        api_client.record_break(
            cset_id, {"break_type": "TWENTY_EIGHT_DAY", "strength_psi": strength_psi},
            recorder,
        )
    )


def setup_final_recorded_cylinder_set(seven_day_psi=3100, final_psi=3800,
                                      complete_before_breaks=False, **kwargs):
    """Cylinder set with both breaks recorded (FINAL_RECORDED).

    The set is cast at 2026-08-15T10:35; breaks are recorded at cast+7d and
    cast+28d. When complete_before_breaks is true the load is completed first
    (required before certification).
    Returns (context, load, cset).
    """
    ctx, load, cset = setup_cylinder_set_on_pouring_load(**kwargs)
    if complete_before_breaks:
        set_clock("2026-08-15T12:00:00Z")
        load = get_success_data(
            api_client.complete_load(
                load["id"], {"discharged_qty_yd3": load["qty_yd3"]}, DRV1
            )
        )
        ctx["load"] = load
    record_seven_day_break(cset["id"], seven_day_psi, "2026-08-22T12:00:00Z")
    cset = record_twenty_eight_day_break(cset["id"], final_psi, "2026-09-12T12:00:00Z")
    return ctx, load, cset
