"""Composite setup helpers.

Most interesting claims require the shipment to be at a specific point along the
workflow spine: carrier -> rate -> order -> shipment -> tender -> accept ->
load -> consolidate -> dock appointment -> dispatch -> depart -> deliver ->
invoice. These helpers walk that spine in stages and return every id a test
might need.

Each fixture uses get_success_data() (lenient) internally so setup failures
surface as clear "Setup failed" errors rather than confusing assertion failures.
The harness restarts the server before every test, so each fixture builds its
preconditions from an empty database.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS

CARRIER = TEST_USERS["carrier_ops_headers"]
SHIPPER = TEST_USERS["shipper_ops_headers"]
DOCK = TEST_USERS["dock_ops_headers"]
AUDITOR = TEST_USERS["freight_auditor_headers"]


# --- Single-entity primitives ----------------------------------------------
def create_carrier(name="Acme TL", scac="ACME", mode="TL"):
    resp = api_client.create_carrier(
        {"name": name, "scac": scac, "mode": mode}, CARRIER)
    return get_success_data(resp)


def create_contract_rate(carrier_id, mode="TL", origin_zone="Z1", dest_zone="Z2",
                         base_rate_per_mile_cents=250, min_charge_cents=50000,
                         fuel_surcharge_pct=0.15, effective_start_minute=0,
                         effective_end_minute=1000):
    payload = {
        "carrier_id": carrier_id, "mode": mode,
        "origin_zone": origin_zone, "dest_zone": dest_zone,
        "base_rate_per_mile_cents": base_rate_per_mile_cents,
        "min_charge_cents": min_charge_cents,
        "fuel_surcharge_pct": fuel_surcharge_pct,
        "effective_start_minute": effective_start_minute,
        "effective_end_minute": effective_end_minute,
    }
    return get_success_data(api_client.create_contract_rate(payload, CARRIER))


def create_order(customer_ref="C1", origin_zone="Z1", dest_zone="Z2",
                 weight_lbs=10000, declared_value_cents=200000):
    payload = {
        "customer_ref": customer_ref, "origin_zone": origin_zone,
        "dest_zone": dest_zone, "weight_lbs": weight_lbs,
        "declared_value_cents": declared_value_cents,
    }
    return get_success_data(api_client.create_order(payload, SHIPPER))


def create_shipment(order_id, mode="TL", distance_miles=300, weight_lbs=6000,
                    promised_eta_minute=500):
    payload = {
        "order_id": order_id, "mode": mode, "distance_miles": distance_miles,
        "weight_lbs": weight_lbs, "promised_eta_minute": promised_eta_minute,
    }
    return get_success_data(api_client.create_shipment(payload, SHIPPER))


def create_load(carrier_id, planned_capacity_lbs=10000):
    payload = {"carrier_id": carrier_id, "planned_capacity_lbs": planned_capacity_lbs}
    return get_success_data(api_client.create_load(payload, DOCK))


def create_dock_appointment(load_id, dock_door="D1", start_minute=200, end_minute=260):
    payload = {
        "load_id": load_id, "dock_door": dock_door,
        "start_minute": start_minute, "end_minute": end_minute,
    }
    return get_success_data(api_client.create_dock_appointment(payload, DOCK))


# --- Composite spine builders ----------------------------------------------
def setup_carrier_rate(carrier_name="Acme TL", scac="ACME", mode="TL",
                       base_rate_per_mile_cents=250, min_charge_cents=50000,
                       fuel_surcharge_pct=0.15, origin_zone="Z1", dest_zone="Z2",
                       effective_start_minute=0, effective_end_minute=1000):
    """An ACTIVE carrier plus one ACTIVE contract rate on the given lane."""
    carrier = create_carrier(carrier_name, scac, mode)
    rate = create_contract_rate(
        carrier["id"], mode=mode, origin_zone=origin_zone, dest_zone=dest_zone,
        base_rate_per_mile_cents=base_rate_per_mile_cents,
        min_charge_cents=min_charge_cents, fuel_surcharge_pct=fuel_surcharge_pct,
        effective_start_minute=effective_start_minute,
        effective_end_minute=effective_end_minute)
    return carrier, rate


def setup_tendered_shipment(order_weight=10000, declared_value_cents=200000,
                            distance_miles=300, ship_weight=6000,
                            promised_eta_minute=500, tender_minute=100,
                            origin_zone="Z1", dest_zone="Z2",
                            base_rate_per_mile_cents=250, min_charge_cents=50000,
                            fuel_surcharge_pct=0.15):
    """Carrier + rate + order + shipment + an OFFERED tender (rate-shopped).

    Returns dict with carrier, rate, order, shipment, tender.
    """
    carrier, rate = setup_carrier_rate(
        base_rate_per_mile_cents=base_rate_per_mile_cents,
        min_charge_cents=min_charge_cents, fuel_surcharge_pct=fuel_surcharge_pct,
        origin_zone=origin_zone, dest_zone=dest_zone)
    order = create_order(origin_zone=origin_zone, dest_zone=dest_zone,
                         weight_lbs=order_weight,
                         declared_value_cents=declared_value_cents)
    shipment = create_shipment(order["id"], distance_miles=distance_miles,
                               weight_lbs=ship_weight,
                               promised_eta_minute=promised_eta_minute)
    tender = get_success_data(
        api_client.create_tender(shipment["id"], {"tender_minute": tender_minute}, SHIPPER))
    return {"carrier": carrier, "rate": rate, "order": order,
            "shipment": shipment, "tender": tender}


def setup_booked_shipment(**kwargs):
    """Tendered shipment whose tender has been ACCEPTED -> BOOKED.

    Returns the same dict as setup_tendered_shipment (with the accepted tender).
    """
    ctx = setup_tendered_shipment(**kwargs)
    get_success_data(api_client.accept_tender(ctx["tender"]["id"], CARRIER))
    return ctx


def setup_consolidated_shipment(planned_capacity_lbs=10000, **kwargs):
    """Booked shipment consolidated onto a BUILDING load.

    Returns ctx dict additionally carrying load (post-consolidation) and load_id.
    """
    ctx = setup_booked_shipment(**kwargs)
    load = create_load(ctx["carrier"]["id"], planned_capacity_lbs=planned_capacity_lbs)
    updated_load = get_success_data(api_client.add_shipment_to_load(
        load["id"],
        {"shipment_id": ctx["shipment"]["id"], "expected_load_version": load["version"]},
        DOCK))
    ctx["load"] = updated_load
    ctx["load_id"] = load["id"]
    return ctx


def setup_dispatched_load(dock_door="D1", appt_start=200, appt_end=260,
                          planned_capacity_lbs=10000, **kwargs):
    """Consolidated shipment whose load has a dock appointment and is DISPATCHED."""
    ctx = setup_consolidated_shipment(planned_capacity_lbs=planned_capacity_lbs, **kwargs)
    appt = create_dock_appointment(ctx["load_id"], dock_door=dock_door,
                                   start_minute=appt_start, end_minute=appt_end)
    ctx["appointment"] = appt
    ctx["load"] = get_success_data(api_client.dispatch_load(ctx["load_id"], DOCK))
    return ctx


def setup_in_transit_shipment(**kwargs):
    """Dispatched-load shipment that has departed (execution_status IN_TRANSIT)."""
    ctx = setup_dispatched_load(**kwargs)
    ctx["shipment"] = get_success_data(
        api_client.depart_shipment(ctx["shipment"]["id"], CARRIER))
    return ctx


def setup_delivered_shipment(delivered_minute=400, **kwargs):
    """In-transit shipment delivered at delivered_minute (DELIVERED)."""
    ctx = setup_in_transit_shipment(**kwargs)
    ctx["shipment"] = get_success_data(api_client.deliver_shipment(
        ctx["shipment"]["id"], {"delivered_minute": delivered_minute}, CARRIER))
    return ctx


def setup_received_invoice(invoiced_linehaul_cents=86250,
                           invoiced_accessorial_codes=None,
                           delivered_minute=400, **kwargs):
    """Delivered shipment with a RECEIVED FreightInvoice. ctx carries 'invoice'."""
    ctx = setup_delivered_shipment(delivered_minute=delivered_minute, **kwargs)
    payload = {"shipment_id": ctx["shipment"]["id"],
               "invoiced_linehaul_cents": invoiced_linehaul_cents}
    if invoiced_accessorial_codes is not None:
        payload["invoiced_accessorial_codes"] = invoiced_accessorial_codes
    ctx["invoice"] = get_success_data(api_client.create_freight_invoice(payload, AUDITOR))
    return ctx


def setup_audited_invoice(invoiced_linehaul_cents=86250,
                          invoiced_accessorial_codes=None,
                          delivered_minute=400, **kwargs):
    """Delivered shipment with an AUDITED FreightInvoice."""
    ctx = setup_received_invoice(
        invoiced_linehaul_cents=invoiced_linehaul_cents,
        invoiced_accessorial_codes=invoiced_accessorial_codes,
        delivered_minute=delivered_minute, **kwargs)
    ctx["invoice"] = get_success_data(
        api_client.audit_freight_invoice(ctx["invoice"]["id"], AUDITOR))
    return ctx


def setup_load_with_two_booked_shipments(planned_capacity_lbs=10000,
                                         ship1_weight=6000, ship2_weight=4000):
    """A BUILDING load plus two independent BOOKED shipments not yet consolidated.

    Returns dict with carrier, load, load_id, load_version (current), ship1, ship2.
    Both shipments are BOOKED on the same carrier and ready to add.
    """
    carrier, rate = setup_carrier_rate()
    # Shipment 1
    order1 = create_order(customer_ref="C1", weight_lbs=ship1_weight)
    ship1 = create_shipment(order1["id"], weight_lbs=ship1_weight)
    tender1 = get_success_data(
        api_client.create_tender(ship1["id"], {"tender_minute": 100}, SHIPPER))
    get_success_data(api_client.accept_tender(tender1["id"], CARRIER))
    # Shipment 2
    order2 = create_order(customer_ref="C2", weight_lbs=ship2_weight)
    ship2 = create_shipment(order2["id"], weight_lbs=ship2_weight)
    tender2 = get_success_data(
        api_client.create_tender(ship2["id"], {"tender_minute": 100}, SHIPPER))
    get_success_data(api_client.accept_tender(tender2["id"], CARRIER))
    # Load
    load = create_load(carrier["id"], planned_capacity_lbs=planned_capacity_lbs)
    return {"carrier": carrier, "rate": rate, "load": load, "load_id": load["id"],
            "load_version": load["version"], "ship1": ship1, "ship2": ship2}


def setup_two_loads_one_appointment(dock_door="D1", appt_start=0, appt_end=60):
    """Two BUILDING loads on the same carrier; load1 has one SCHEDULED appointment
    on dock_door over [appt_start, appt_end). Returns carrier, load1, load2, appt1.
    """
    carrier = create_carrier()
    load1 = create_load(carrier["id"])
    load2 = create_load(carrier["id"])
    appt1 = create_dock_appointment(load1["id"], dock_door=dock_door,
                                    start_minute=appt_start, end_minute=appt_end)
    return {"carrier": carrier, "load1": load1, "load2": load2, "appt1": appt1}
