"""Composite setup helpers for the cold-chain reefer API.

Every test runs against a freshly restarted, empty server, so each fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion mismatch.

Carrier is the one entity_backed role (PRD §2.1): after a carrier is created, every
ownership-gated carrier call threads make_carrier_headers(carrier["id"]). Shipper /
Driver / ComplianceOfficer / PlatformAdmin are opaque; cancel/withdraw ownership is
threaded with the owning operator's explicit X-User-ID via make_shipper_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_carrier_headers,
    make_shipper_headers,
)
from . import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
DRIVER = TEST_USERS["driver_headers"]

# Default operator ids used across fixtures (opaque for shipper; carrier threads id).
SHIPPER_OP = "shipper-op"
CO_OP = "co-op"
DRIVER_OP = "driver-op"

DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
# IN_TRANSIT start anchors offset_min = 0 at the dispatch instant. With the clock at
# 2026-03-01T00:00:00Z when dispatch occurs, a clock of 2026-03-01T02:20:00Z is 140
# minutes later — the provisional read horizon used by the dual-variant test.


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(F.clock_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Atomic config helpers
# ---------------------------------------------------------------------------
def create_carrier(legal_name="Test Carrier", fsma_registered=True,
                   sanitary_training_current=True, liability_cap_cents=None,
                   op_id="carrier-op"):
    """Create a carrier acting under op_id, then return (carrier, carrier_headers)
    where carrier_headers is threaded with the real Carrier.id (entity_backed)."""
    payload = {
        "legal_name": legal_name,
        "fsma_registered": fsma_registered,
        "sanitary_training_current": sanitary_training_current,
    }
    if liability_cap_cents is not None:
        payload["liability_cap_cents"] = liability_cap_cents
    carrier = get_success_data(
        api_client.create_carrier(payload, make_carrier_headers(op_id))
    )
    return carrier, make_carrier_headers(carrier["id"])


def create_lane(code="FROZEN", setpoint_min_c=-25, setpoint_max_c=-15,
                regulated=True, tolerance_degree_minutes=30):
    payload = {
        "code": code,
        "setpoint_min_c": setpoint_min_c,
        "setpoint_max_c": setpoint_max_c,
        "regulated": regulated,
        "tolerance_degree_minutes": tolerance_degree_minutes,
    }
    return get_success_data(api_client.create_temp_lane(payload, ADMIN))


def create_chilled_lane():
    return create_lane(code="CHILLED", setpoint_min_c=0, setpoint_max_c=4,
                       regulated=True, tolerance_degree_minutes=30)


def create_unit(carrier_headers, carrier_id, asset_tag="RU-1", compartment_count=1,
                last_sanitation_at="2026-02-28T00:00:00Z"):
    payload = {
        "carrier_id": carrier_id,
        "asset_tag": asset_tag,
        "compartment_count": compartment_count,
    }
    if last_sanitation_at is not None:
        payload["last_sanitation_at"] = last_sanitation_at
    return get_success_data(api_client.create_reefer_unit(payload, carrier_headers))


def shipper_headers(op_id=SHIPPER_OP):
    return make_shipper_headers(op_id)


# ---------------------------------------------------------------------------
# Tendered shipment + structure
# ---------------------------------------------------------------------------
def tender_shipment(carrier_id, cargo_class="FOOD", shipper_op=SHIPPER_OP):
    return get_success_data(
        api_client.create_shipment(
            F.create_shipment_payload(carrier_id, cargo_class), make_shipper_headers(shipper_op)
        )
    )


def add_compartment(shipment_id, lane_id, ordinal=1, shipper_op=SHIPPER_OP):
    return get_success_data(
        api_client.create_compartment(
            shipment_id, F.create_compartment_payload(lane_id, ordinal),
            make_shipper_headers(shipper_op),
        )
    )


def add_lot(compartment_id, sku="SKU-1", pallet_count=1, declared_value_cents=100000,
            shipper_op=SHIPPER_OP):
    return get_success_data(
        api_client.create_lot(
            compartment_id,
            F.create_lot_payload(sku=sku, pallet_count=pallet_count,
                                 declared_value_cents=declared_value_cents),
            make_shipper_headers(shipper_op),
        )
    )


def add_stop(shipment_id, kind, appointment_min, pallets_handled=0,
             compartments_touched=1, actor_headers=None, shipper_op=SHIPPER_OP):
    headers = actor_headers if actor_headers is not None else make_shipper_headers(shipper_op)
    return get_success_data(
        api_client.create_stop(
            shipment_id,
            F.create_stop_payload(kind, appointment_min, pallets_handled, compartments_touched),
            headers,
        )
    )


def current_version(shipment_id, carrier_headers):
    return get_success_data(api_client.get_shipment(shipment_id, carrier_headers))["version"]


def accept(shipment_id, unit_id, carrier_headers, expected_version=None):
    if expected_version is None:
        expected_version = current_version(shipment_id, carrier_headers)
    return get_success_data(
        api_client.accept_shipment(
            shipment_id, F.accept_payload(unit_id, expected_version), carrier_headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 1/2: scenario builders
# ---------------------------------------------------------------------------
def setup_tendered_with_compartments(num_compartments=1, cargo_class="FOOD",
                                     compartment_count=None, lane_kind="FROZEN",
                                     liability_cap_cents=None, carrier_op="carrier-op",
                                     shipper_op=SHIPPER_OP, asset_tag="RU-1",
                                     last_sanitation_at="2026-02-28T00:00:00Z"):
    """Carrier + lane + unit + TENDERED shipment with `num_compartments` compartments.

    Returns a dict with carrier, carrier_headers, lane, unit, shipment, compartments.
    The unit's compartment_count defaults to num_compartments so accept passes the
    sizing gate unless overridden.
    """
    if compartment_count is None:
        compartment_count = max(num_compartments, 1)
    carrier, ch = create_carrier(liability_cap_cents=liability_cap_cents, op_id=carrier_op)
    lane = create_chilled_lane() if lane_kind == "CHILLED" else create_lane()
    unit = create_unit(ch, carrier["id"], asset_tag=asset_tag,
                       compartment_count=compartment_count,
                       last_sanitation_at=last_sanitation_at)
    shipment = tender_shipment(carrier["id"], cargo_class=cargo_class, shipper_op=shipper_op)
    compartments = [
        add_compartment(shipment["id"], lane["id"], ordinal=i + 1, shipper_op=shipper_op)
        for i in range(num_compartments)
    ]
    return {
        "carrier": carrier,
        "carrier_headers": ch,
        "lane": lane,
        "unit": unit,
        "shipment": shipment,
        "compartments": compartments,
    }


def setup_accepted(num_compartments=1, cargo_class="FOOD", lane_kind="FROZEN",
                   liability_cap_cents=None, carrier_op="carrier-op",
                   shipper_op=SHIPPER_OP, last_sanitation_at="2026-02-28T00:00:00Z"):
    """Tendered scenario, then accepted onto the unit (TENDERED -> ACCEPTED)."""
    ctx = setup_tendered_with_compartments(
        num_compartments=num_compartments, cargo_class=cargo_class, lane_kind=lane_kind,
        liability_cap_cents=liability_cap_cents, carrier_op=carrier_op,
        shipper_op=shipper_op, last_sanitation_at=last_sanitation_at,
    )
    accept(ctx["shipment"]["id"], ctx["unit"]["id"], ctx["carrier_headers"])
    return ctx


def _precool_temp(lane_kind):
    return 2 if lane_kind == "CHILLED" else -20


def setup_precooled(num_compartments=1, cargo_class="FOOD", lane_kind="FROZEN",
                    liability_cap_cents=None, carrier_op="carrier-op",
                    shipper_op=SHIPPER_OP, last_sanitation_at="2026-02-28T00:00:00Z"):
    """ACCEPTED scenario, then an in-band PRECOOL reading per compartment and
    precool-verify (ACCEPTED -> PRECOOLED)."""
    ctx = setup_accepted(
        num_compartments=num_compartments, cargo_class=cargo_class, lane_kind=lane_kind,
        liability_cap_cents=liability_cap_cents, carrier_op=carrier_op,
        shipper_op=shipper_op, last_sanitation_at=last_sanitation_at,
    )
    temp = _precool_temp(lane_kind)
    for comp in ctx["compartments"]:
        get_success_data(api_client.create_reading(
            comp["id"], F.create_reading_payload("PRECOOL", 0, temp_c=temp), ctx["carrier_headers"]
        ))
    get_success_data(
        api_client.precool_verify_shipment(ctx["shipment"]["id"], ctx["carrier_headers"])
    )
    return ctx


def setup_in_transit(num_compartments=1, cargo_class="FOOD", lane_kind="FROZEN",
                     liability_cap_cents=None, carrier_op="carrier-op",
                     shipper_op=SHIPPER_OP, last_sanitation_at="2026-02-28T00:00:00Z",
                     clock=DEFAULT_CLOCK):
    """PRECOOLED scenario, then dispatched (PRECOOLED -> IN_TRANSIT). Sets the clock
    so the telemetry timeline is deterministic."""
    set_clock(clock)
    ctx = setup_precooled(
        num_compartments=num_compartments, cargo_class=cargo_class, lane_kind=lane_kind,
        liability_cap_cents=liability_cap_cents, carrier_op=carrier_op,
        shipper_op=shipper_op, last_sanitation_at=last_sanitation_at,
    )
    get_success_data(api_client.dispatch_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    return ctx


def add_temp_readings(compartment_id, readings, actor_headers=None):
    """Append a sequence of TEMP readings. `readings` is a list of (offset_min, temp_c)."""
    headers = actor_headers if actor_headers is not None else DRIVER
    for offset_min, temp_c in readings:
        get_success_data(api_client.create_reading(
            compartment_id, F.create_reading_payload("TEMP", offset_min, temp_c=temp_c), headers
        ))


def deliver(shipment_id, driver_headers=None):
    headers = driver_headers if driver_headers is not None else DRIVER
    return get_success_data(api_client.deliver_shipment(shipment_id, headers))


# ---------------------------------------------------------------------------
# Tier 3/4: delivered shipment with a controlled impairment, ready for a claim
# ---------------------------------------------------------------------------
def setup_delivered_with_temp_series(temp_readings, num_compartments=1, lots=None,
                                     cargo_class="FOOD", lane_kind="FROZEN",
                                     liability_cap_cents=None, carrier_op="carrier-op",
                                     shipper_op=SHIPPER_OP, clock=DEFAULT_CLOCK):
    """Full lifecycle to DELIVERED with a controlled TEMP series on compartment 0.

    `temp_readings` is a list of (offset_min, temp_c) applied to the first compartment.
    `lots` is an optional list of (sku, pallet_count, declared_value_cents) added to
    the first compartment before accept (lots must be added while TENDERED).
    Returns the IN_TRANSIT/DELIVERED context dict (shipment reflected post-deliver via
    a fresh GET would be needed by callers).
    """
    set_clock(clock)
    ctx = setup_tendered_with_compartments(
        num_compartments=num_compartments, cargo_class=cargo_class, lane_kind=lane_kind,
        liability_cap_cents=liability_cap_cents, carrier_op=carrier_op, shipper_op=shipper_op,
    )
    comp0 = ctx["compartments"][0]
    if lots:
        for sku, pallets, value in lots:
            add_lot(comp0["id"], sku=sku, pallet_count=pallets,
                    declared_value_cents=value, shipper_op=shipper_op)
    accept(ctx["shipment"]["id"], ctx["unit"]["id"], ctx["carrier_headers"])
    temp = _precool_temp(lane_kind)
    for comp in ctx["compartments"]:
        get_success_data(api_client.create_reading(
            comp["id"], F.create_reading_payload("PRECOOL", 0, temp_c=temp), ctx["carrier_headers"]
        ))
    get_success_data(api_client.precool_verify_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    get_success_data(api_client.dispatch_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    add_temp_readings(comp0["id"], temp_readings)
    delivered = deliver(ctx["shipment"]["id"])
    ctx["delivered"] = delivered
    return ctx


def file_claim(shipment_id, shipper_op=SHIPPER_OP):
    return get_success_data(
        api_client.create_claim(F.claim_payload(shipment_id), make_shipper_headers(shipper_op))
    )


def review_claim(claim_id, co_op=CO_OP):
    from .test_users import make_compliance_officer_headers
    return get_success_data(
        api_client.review_claim(claim_id, make_compliance_officer_headers(co_op))
    )


# ---------------------------------------------------------------------------
# Stop lifecycle to a state ready for close (detention/lumper boundary tests)
# ---------------------------------------------------------------------------
def setup_arrived_stop(arrived_min=0, appointment_min=0, kind="DELIVERY",
                       pallets_handled=0, compartments_touched=1, lane_kind="CHILLED",
                       carrier_op="carrier-op", shipper_op=SHIPPER_OP, clock=DEFAULT_CLOCK):
    """Build an IN_TRANSIT shipment with one DELIVERY stop arrived at arrived_min.

    The stop is scheduled (while TENDERED) then the shipment is accept/precool/dispatch'd,
    then the stop is arrived. Returns (ctx, stop) with the stop in ARRIVED.
    """
    set_clock(clock)
    ctx = setup_tendered_with_compartments(
        num_compartments=1, cargo_class="FOOD", lane_kind=lane_kind,
        carrier_op=carrier_op, shipper_op=shipper_op,
    )
    stop = add_stop(ctx["shipment"]["id"], kind, appointment_min,
                    pallets_handled=pallets_handled, compartments_touched=compartments_touched,
                    shipper_op=shipper_op)
    accept(ctx["shipment"]["id"], ctx["unit"]["id"], ctx["carrier_headers"])
    comp = ctx["compartments"][0]
    get_success_data(api_client.create_reading(
        comp["id"], F.create_reading_payload("PRECOOL", 0, temp_c=_precool_temp(lane_kind)),
        ctx["carrier_headers"]
    ))
    get_success_data(api_client.precool_verify_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    get_success_data(api_client.dispatch_shipment(ctx["shipment"]["id"], ctx["carrier_headers"]))
    get_success_data(api_client.arrive_stop(
        ctx["shipment"]["id"], stop["id"], F.arrive_payload(arrived_min), DRIVER
    ))
    ctx["stop"] = stop
    return ctx, stop
