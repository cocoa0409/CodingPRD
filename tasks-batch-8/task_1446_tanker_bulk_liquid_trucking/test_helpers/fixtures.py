"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the server restarts before each test). Uses get_success_data()
internally so setup failures surface as clear "Setup failed" errors.

Identity threading (PRD 2.1): entity-backed roles use make_driver_headers /
make_customer_rep_headers with the real entity id; opaque operator ids come
from constants (OP_METER for the meter closer, OP_SCALE for weight verifier).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import OP_METER, OP_SCALE, SO_1
from .factories import (
    create_agreement_payload,
    create_compatibility_rule_payload,
    create_customer_payload,
    create_driver_payload,
    create_loading_rack_payload,
    create_product_payload,
    create_shipment_payload,
    create_spill_plan_payload,
    create_trailer_payload,
    create_wash_bay_payload,
    create_wash_certificate_payload,
    close_delivery_ticket_payload,
    close_meter_payload,
    confirm_placards_payload,
    plan_shipment_payload,
    record_weights_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_rep_headers,
    make_driver_headers,
    make_safety_officer_headers,
    make_terminal_operator_headers,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
WASH_OP = TEST_USERS["wash_operator_headers"]


def _expect_ok(res, label):
    assert res.status_code < 400, f"Setup failed ({label}): HTTP {res.status_code} {res.text}"
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1: master data primitives
# ---------------------------------------------------------------------------

def create_customer(name="Acme Chem", credit_limit_cents=1_000_000_000, **overrides):
    res = api_client.create_customer(
        create_customer_payload(name=name, credit_limit_cents=credit_limit_cents, **overrides), ADMIN)
    return _expect_ok(res, "create_customer")


def create_product(**overrides):
    res = api_client.create_product(create_product_payload(**overrides), ADMIN)
    return _expect_ok(res, "create_product")


def create_rule(prior_group="PETROLEUM", next_group="PETROLEUM", required_wash_level="NONE", **overrides):
    res = api_client.create_compatibility_rule(
        create_compatibility_rule_payload(
            prior_group=prior_group, next_group=next_group,
            required_wash_level=required_wash_level, **overrides),
        ADMIN)
    return _expect_ok(res, "create_compatibility_rule")


def create_trailer(unit_number="T-101", **overrides):
    res = api_client.create_trailer(create_trailer_payload(unit_number=unit_number, **overrides), ADMIN)
    return _expect_ok(res, "create_trailer")


def create_driver(cdl_number="CDL-1", **overrides):
    res = api_client.create_driver(create_driver_payload(cdl_number=cdl_number, **overrides), ADMIN)
    return _expect_ok(res, "create_driver")


def create_rack(rack_code="R-1", authorized_groups=None, **overrides):
    payload = create_loading_rack_payload(rack_code=rack_code, **overrides)
    if authorized_groups is not None:
        payload["authorized_groups"] = authorized_groups
    res = api_client.create_loading_rack(payload, ADMIN)
    return _expect_ok(res, "create_loading_rack")


def create_wash_bay(bay_code="WB-1", supported_wash_levels=None, cleanup_buffer_minutes=30):
    levels = supported_wash_levels if supported_wash_levels is not None else ["FLUSH", "DETERGENT_WASH"]
    res = api_client.create_wash_bay(
        create_wash_bay_payload(bay_code=bay_code, supported_wash_levels=levels,
                                cleanup_buffer_minutes=cleanup_buffer_minutes),
        ADMIN)
    return _expect_ok(res, "create_wash_bay")


def set_clock(to_iso8601):
    res = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    _expect_ok(res, f"set_clock({to_iso8601})")


# ---------------------------------------------------------------------------
# Tier 2: baseline shipment scenario (master data + DRAFT shipment)
# ---------------------------------------------------------------------------

def setup_draft_shipment(ordered_gallons=1000, route_miles=100, rate_per_gal_cents=100,
                         credit_limit_cents=1_000_000_000, with_rule=True,
                         driver_overrides=None, customer_overrides=None, product_overrides=None,
                         trailer_overrides=None):
    """Master data (customer, PETROLEUM product, optional PETROLEUM->PETROLEUM rule,
    trailer, driver, rack) plus a DRAFT shipment. Returns dict of all pieces."""
    cust = create_customer(credit_limit_cents=credit_limit_cents, **(customer_overrides or {}))
    prod = create_product(**(product_overrides or {}))
    rule = create_rule() if with_rule else None
    trl = create_trailer(**(trailer_overrides or {}))
    drv = create_driver(**(driver_overrides or {}))
    rack = create_rack()
    ship = _expect_ok(
        api_client.create_shipment(
            create_shipment_payload(cust["id"], prod["id"], ordered_gallons=ordered_gallons,
                                    route_miles=route_miles, rate_per_gal_cents=rate_per_gal_cents),
            DISP),
        "create_shipment")
    return {"cust": cust, "prod": prod, "rule": rule, "trl": trl, "drv": drv,
            "rack": rack, "ship": ship}


def plan_shipment(scenario, clock_iso="2026-08-02T10:30:00Z", set_the_clock=True, **plan_overrides):
    """Plan the scenario's DRAFT shipment. Returns the PLANNED shipment."""
    if set_the_clock:
        set_clock(clock_iso)
    payload = plan_shipment_payload(
        scenario["trl"]["id"], scenario["drv"]["id"], scenario["rack"]["id"], **plan_overrides)
    res = api_client.plan_shipment(scenario["ship"]["id"], payload, DISP)
    return _expect_ok(res, "plan_shipment")


def setup_planned_shipment(**kwargs):
    """Baseline scenario with the shipment PLANNED and clock inside the rack window."""
    scenario = setup_draft_shipment(**kwargs)
    scenario["ship"] = plan_shipment(scenario)
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: loading-rack progression (LOADING / LOADED)
# ---------------------------------------------------------------------------

def check_in(scenario, clock_iso="2026-08-02T10:30:00Z"):
    """Clock inside the window, then check in (PLANNED -> LOADING, opens MeterTicket)."""
    set_clock(clock_iso)
    res = api_client.check_in_shipment(scenario["ship"]["id"], make_terminal_operator_headers(OP_METER))
    scenario["ship"] = _expect_ok(res, "check_in")
    return scenario["ship"]


def close_meter(scenario, meter_start_gal=0, meter_end_gal=1000, observed_temp_F=60,
                operator=OP_METER):
    """Close the meter (LOADING -> LOADED). Returns the CLOSED MeterTicket."""
    res = api_client.close_meter(
        scenario["ship"]["id"],
        close_meter_payload(meter_start_gal=meter_start_gal, meter_end_gal=meter_end_gal,
                            observed_temp_F=observed_temp_F),
        make_terminal_operator_headers(operator))
    return _expect_ok(res, "close_meter")


def setup_loading_shipment(**kwargs):
    """Shipment in LOADING with an OPEN meter ticket; clock inside the rack window."""
    scenario = setup_planned_shipment(**kwargs)
    check_in(scenario)
    return scenario


def record_weights(scenario, steer_lb=None, drive_lb=None, trailer_lb=None, operator=OP_SCALE):
    """Record axle weights on a LOADED shipment (weight verifier != meter closer).

    When the axle weights are not given, derive a compliant set from the
    scenario's actual load (PRD 3.4): the measured sum equals the expected
    gross — trailer tare plus round-half-up(net60_gallons x density) — so the
    3% sum-consistency check passes for any metered quantity/temperature, and
    each axle stays within its inclusive rating. Pass explicit values to
    exercise the compliance failures."""
    if steer_lb is None and drive_lb is None and trailer_lb is None:
        steer_lb, drive_lb, trailer_lb = _compliant_weights(scenario)
    res = api_client.record_weights(
        scenario["ship"]["id"],
        record_weights_payload(steer_lb=steer_lb, drive_lb=drive_lb, trailer_lb=trailer_lb),
        make_terminal_operator_headers(operator))
    return _expect_ok(res, "record_weights")


def _compliant_weights(scenario):
    """(steer, drive, trailer) whose sum is exactly the PRD 3.4 expected gross
    for the shipment's closed meter ticket, spread across axles within their
    inclusive ratings."""
    from decimal import Decimal, ROUND_HALF_UP

    ship = _expect_ok(api_client.get_shipment(scenario["ship"]["id"], DISP), "get_shipment")
    trl = _expect_ok(api_client.get_trailer(ship["trailer_id"], DISP), "get_trailer")
    prod = _expect_ok(api_client.get_product(ship["product_id"], DISP), "get_product")
    tickets, _meta = _expect_ok_list(
        api_client.list_meter_tickets(DISP, params={"shipment_id": ship["id"]}),
        "list_meter_tickets")
    closed = [t for t in tickets if t["status"] == "CLOSED"]
    assert len(closed) == 1, f"Setup failed: expected 1 CLOSED meter ticket, got {len(closed)}"
    net60 = Decimal(str(closed[0]["net60_gallons"]))
    density = Decimal(str(prod["density_lb_per_gal"]))
    product_weight = int((net60 * density).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    steer = trl["tare_steer_lb"]
    drive_room = trl["drive_axle_rating_lb"] - trl["tare_drive_lb"]
    drive_extra = min(product_weight // 2, drive_room)
    drive = trl["tare_drive_lb"] + drive_extra
    trailer = trl["tare_trailer_lb"] + (product_weight - drive_extra)
    return steer, drive, trailer


def confirm_placards(scenario, placard_code="UN1993", operator=OP_METER):
    res = api_client.confirm_placards(
        scenario["ship"]["id"], confirm_placards_payload(observed_placard_code=placard_code),
        make_terminal_operator_headers(operator))
    return _expect_ok(res, "confirm_placards")


def setup_loaded_shipment(meter_start_gal=0, meter_end_gal=1000, observed_temp_F=60,
                          weigh=True, placard=True, **kwargs):
    """Shipment LOADED (meter closed); optionally weights verified and placards confirmed."""
    scenario = setup_loading_shipment(**kwargs)
    scenario["meter_ticket"] = close_meter(
        scenario, meter_start_gal=meter_start_gal, meter_end_gal=meter_end_gal,
        observed_temp_F=observed_temp_F)
    if weigh:
        # record_weights derives a compliant axle set from the actual closed
        # meter ticket (PRD 3.4 expected gross) when none is passed.
        scenario["ship"] = record_weights(scenario)
    if placard:
        scenario["ship"] = confirm_placards(scenario)
    scenario["ship"] = _expect_ok(api_client.get_shipment(scenario["ship"]["id"], DISP), "get_shipment")
    return scenario


# ---------------------------------------------------------------------------
# Tier 3b: spill plan lifecycle
# ---------------------------------------------------------------------------

def create_approved_spill_plan(customer_id, product_id, **overrides):
    """DRAFT -> SUBMITTED -> APPROVED spill response plan. Caller identity for the
    CustomerRep steps is the owning customer's id (PRD 2.1 entity-backed identity)."""
    rep = make_customer_rep_headers(customer_id)
    plan = _expect_ok(
        api_client.create_spill_plan(create_spill_plan_payload(customer_id, product_id, **overrides), rep),
        "create_spill_plan")
    _expect_ok(api_client.submit_spill_plan(plan["id"], rep), "submit_spill_plan")
    approved = _expect_ok(
        api_client.approve_spill_plan(plan["id"], make_safety_officer_headers(SO_1)),
        "approve_spill_plan")
    return approved


# ---------------------------------------------------------------------------
# Tier 4: in-transit / delivering / delivered progression
# ---------------------------------------------------------------------------

def setup_in_transit_shipment(**kwargs):
    """Shipment IN_TRANSIT: LOADED + weights + placards + approved spill plan + depart."""
    scenario = setup_loaded_shipment(**kwargs)
    scenario["spill_plan"] = create_approved_spill_plan(scenario["cust"]["id"], scenario["prod"]["id"])
    scenario["ship"] = _expect_ok(api_client.depart_shipment(scenario["ship"]["id"], DISP), "depart")
    return scenario


def start_delivery(scenario):
    """IN_TRANSIT -> DELIVERING; returns the OPEN DeliveryTicket."""
    drv_headers = make_driver_headers(scenario["drv"]["id"])
    scenario["ship"] = _expect_ok(
        api_client.start_delivery(scenario["ship"]["id"], drv_headers), "start_delivery")
    tickets, _meta = _expect_ok_list(api_client.list_delivery_tickets(
        DISP, params={"shipment_id": scenario["ship"]["id"]}), "list_delivery_tickets")
    assert len(tickets) == 1, f"Setup failed: expected 1 delivery ticket, got {len(tickets)}"
    scenario["delivery_ticket"] = tickets[0]
    return scenario["delivery_ticket"]


def setup_delivering_shipment(**kwargs):
    """Shipment DELIVERING with an OPEN delivery ticket."""
    scenario = setup_in_transit_shipment(**kwargs)
    start_delivery(scenario)
    return scenario


def close_delivery(scenario, delivered_observed_gal=1000, delivered_temp_F=60, retain_sample_ml=250):
    """Close the scenario's OPEN delivery ticket as the assigned driver."""
    drv_headers = make_driver_headers(scenario["drv"]["id"])
    res = api_client.close_delivery_ticket(
        scenario["delivery_ticket"]["id"],
        close_delivery_ticket_payload(delivered_observed_gal=delivered_observed_gal,
                                      delivered_temp_F=delivered_temp_F,
                                      retain_sample_ml=retain_sample_ml),
        drv_headers)
    ticket = _expect_ok(res, "close_delivery_ticket")
    scenario["delivery_ticket"] = ticket
    scenario["ship"] = _expect_ok(api_client.get_shipment(scenario["ship"]["id"], DISP), "get_shipment")
    return ticket


def setup_delivered_shipment(delivered_observed_gal=1000, delivered_temp_F=60, **kwargs):
    """Shipment DELIVERED via an in-tolerance (accepted) delivery close."""
    scenario = setup_delivering_shipment(**kwargs)
    close_delivery(scenario, delivered_observed_gal=delivered_observed_gal,
                   delivered_temp_F=delivered_temp_F)
    assert scenario["ship"]["status"] == "DELIVERED", (
        f"Setup failed: expected DELIVERED, got {scenario['ship']['status']}")
    return scenario


def setup_variance_review_shipment(delivered_observed_gal=940, delivered_temp_F=60, **kwargs):
    """Shipment VARIANCE_REVIEW via an out-of-tolerance delivery close."""
    kwargs.setdefault("route_miles", 500)
    scenario = setup_delivering_shipment(**kwargs)
    close_delivery(scenario, delivered_observed_gal=delivered_observed_gal,
                   delivered_temp_F=delivered_temp_F)
    assert scenario["ship"]["status"] == "VARIANCE_REVIEW", (
        f"Setup failed: expected VARIANCE_REVIEW, got {scenario['ship']['status']}")
    return scenario


def setup_reconciled_shipment(**kwargs):
    """Full lifecycle through RECONCILED (accepted delivery, no open incidents)."""
    scenario = setup_delivered_shipment(**kwargs)
    scenario["ship"] = _expect_ok(
        api_client.reconcile_shipment(scenario["ship"]["id"], ADMIN), "reconcile")
    return scenario


def get_retain_sample(scenario):
    samples, _meta = _expect_ok_list(api_client.list_retain_samples(
        DISP, params={"shipment_id": scenario["ship"]["id"]}), "list_retain_samples")
    assert len(samples) == 1, f"Setup failed: expected 1 retain sample, got {len(samples)}"
    scenario["retain_sample"] = samples[0]
    return samples[0]


# ---------------------------------------------------------------------------
# Tier 4b: incidents
# ---------------------------------------------------------------------------

def report_incident(scenario, occurred_at="2026-08-02T11:00:00Z", gallons_spilled=5):
    """Driver reports a spill on an IN_TRANSIT/DELIVERING shipment. Returns incident."""
    drv_headers = make_driver_headers(scenario["drv"]["id"])
    res = api_client.create_spill_incident(
        scenario["ship"]["id"],
        {"occurred_at": occurred_at, "gallons_spilled": gallons_spilled},
        drv_headers)
    return _expect_ok(res, "create_spill_incident")


# ---------------------------------------------------------------------------
# Tier 4c: wash certificates
# ---------------------------------------------------------------------------

def create_certified_cert(trailer_id, wash_level="FLUSH",
                          window_start="2026-08-01T06:00:00Z", window_end="2026-08-01T07:00:00Z",
                          bay_code="WB-1", supported_wash_levels=None, cleanup_buffer_minutes=30):
    """Wash bay + booked + CERTIFIED certificate for the trailer. Returns (cert, bay)."""
    levels = supported_wash_levels if supported_wash_levels is not None else ["FLUSH", "DETERGENT_WASH"]
    bay = create_wash_bay(bay_code=bay_code, supported_wash_levels=levels,
                          cleanup_buffer_minutes=cleanup_buffer_minutes)
    cert = _expect_ok(
        api_client.create_wash_certificate(
            create_wash_certificate_payload(trailer_id, bay["id"], wash_level=wash_level,
                                            window_start=window_start, window_end=window_end),
            WASH_OP),
        "create_wash_certificate")
    cert = _expect_ok(api_client.certify_wash_certificate(cert["id"], WASH_OP), "certify")
    return cert, bay


# ---------------------------------------------------------------------------
# Tier 5: dedicated-trailer program
# ---------------------------------------------------------------------------

def create_active_agreement(committed_loads_per_month=5, cust_name="Dedicated Co", **overrides):
    """Enrolled customer + trailer + PENDING agreement + activate. Returns dict."""
    cust = create_customer(name=cust_name, dedicated_program_enrolled=True)
    trl = create_trailer(**overrides.pop("trailer_overrides", {}))
    agr = _expect_ok(
        api_client.create_agreement(
            create_agreement_payload(cust["id"], trl["id"],
                                     committed_loads_per_month=committed_loads_per_month,
                                     **overrides),
            ADMIN),
        "create_agreement")
    agr = _expect_ok(api_client.activate_agreement(agr["id"], ADMIN), "activate_agreement")
    return {"cust": cust, "trl": trl, "agr": agr}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _expect_ok_list(res, label):
    assert res.status_code < 400, f"Setup failed ({label}): HTTP {res.status_code} {res.text}"
    body = res.json()
    return body["data"], body.get("meta", {})


def list_meter_tickets_for_shipment(shipment_id):
    tickets, meta = _expect_ok_list(
        api_client.list_meter_tickets(DISP, params={"shipment_id": shipment_id}),
        "list_meter_tickets")
    return tickets, meta
