"""Composite setup helpers for the baggage claims domain.

Every fixture builds its preconditions from scratch via PRD-declared endpoints;
the harness restarts the server before each test, so no state carries over.
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH, CLOCK_PLUS_504H,
)
from .factories import (
    create_station_payload, create_carrier_payload, create_courier_service_payload,
    create_repair_vendor_payload, create_passenger_payload, create_bag_tag_payload,
    create_report_payload, create_tracing_event_payload, create_dispatch_payload,
    create_repair_order_payload, make_receipt, create_expense_claim_payload,
    unique_station_code, unique_carrier_code,
)
from .test_users import TEST_USERS, make_passenger_headers

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


# ---------------------------------------------------------------------------
# Tier 1: reference data and simple entities
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_EPOCH):
    """Set the logical clock (SystemAdmin). Returns the clock response data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_station(station_code=None, name="New York JFK", bags_handled_total=1000000):
    # PRD §3.1: station_code is "treated as a unique business identifier" — default
    # to a unique code so tests needing several stations never self-collide.
    if station_code is None:
        station_code = unique_station_code()
    return get_success_data(api_client.create_station(
        create_station_payload(station_code=station_code, name=name,
                               bags_handled_total=bags_handled_total), ADMIN))


def create_carrier(carrier_code=None, name="Air Alpha", is_interline_partner=False):
    # PRD §3.1: carrier_code is "also unique" — default to a unique code.
    if carrier_code is None:
        carrier_code = unique_carrier_code()
    return get_success_data(api_client.create_carrier(
        create_carrier_payload(carrier_code=carrier_code, name=name,
                               is_interline_partner=is_interline_partner), ADMIN))


def create_courier_service(serves_station_ids, name="Speedy", turnaround_buffer_minutes=60):
    return get_success_data(api_client.create_courier_service(
        create_courier_service_payload(serves_station_ids, name=name,
                                       turnaround_buffer_minutes=turnaround_buffer_minutes),
        ADMIN))


def create_repair_vendor(name="FixIt", bench_capacity=2):
    return get_success_data(api_client.create_repair_vendor(
        create_repair_vendor_payload(name=name, bench_capacity=bench_capacity), ADMIN))


def create_passenger(full_name="Pat Flyer", email=None, tier="STANDARD"):
    payload = create_passenger_payload(full_name=full_name, tier=tier)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_passenger(payload, AGENT))


def create_bag_tag(passenger_id, routing_carrier_ids, is_international=False,
                   weight_kg=20, declared_value_cents=0):
    return get_success_data(api_client.create_bag_tag(
        create_bag_tag_payload(passenger_id, routing_carrier_ids,
                               is_international=is_international, weight_kg=weight_kg,
                               declared_value_cents=declared_value_cents), AGENT))


def create_report(passenger_id, bag_tag_id, station_id, report_type="DELAYED",
                  report_reference=None):
    payload = create_report_payload(passenger_id, bag_tag_id, station_id,
                                    type=report_type)
    if report_reference is not None:
        payload["report_reference"] = report_reference
    return get_success_data(api_client.create_report(payload, AGENT))


# ---------------------------------------------------------------------------
# Tier 2: common composite scenarios
# ---------------------------------------------------------------------------

def setup_station_carrier_passenger(bags_handled_total=1000000, tier="STANDARD"):
    """Clock at epoch + station + one carrier + one passenger.

    Returns (station, carrier, passenger).
    """
    set_clock(CLOCK_EPOCH)
    station = create_station(bags_handled_total=bags_handled_total)
    carrier = create_carrier()
    passenger = create_passenger(tier=tier)
    return station, carrier, passenger


def setup_bag_and_report(is_international=False, weight_kg=20, declared_value_cents=0,
                         report_type="DELAYED", tier="STANDARD",
                         bags_handled_total=1000000, routing_extra_carrier=False):
    """Station + carrier(s) + passenger + bag tag + report.

    Returns dict with keys: station, carrier, passenger, bag, report.
    When routing_extra_carrier is True, a second (interline) carrier is appended
    to the routing, making it the liable carrier.
    """
    station, carrier, passenger = setup_station_carrier_passenger(
        bags_handled_total=bags_handled_total, tier=tier)
    routing = [carrier["id"]]
    extra = None
    if routing_extra_carrier:
        extra = create_carrier(carrier_code="BA", name="Air Beta", is_interline_partner=True)
        routing.append(extra["id"])
    bag = create_bag_tag(passenger["id"], routing, is_international=is_international,
                         weight_kg=weight_kg, declared_value_cents=declared_value_cents)
    report = create_report(passenger["id"], bag["id"], station["id"],
                           report_type=report_type)
    # Report creation flips the bag status (PRD §3.3); re-fetch so callers see the
    # post-cascade bag rather than the stale CHECKED snapshot from tag creation.
    bag = get_success_data(api_client.get_bag_tag(bag["id"], AGENT))
    return {"station": station, "carrier": carrier, "carrier_extra": extra,
            "passenger": passenger, "bag": bag, "report": report}


def setup_found_pending_delivery(is_international=False, weight_kg=20,
                                 declared_value_cents=0, tier="STANDARD",
                                 courier_buffer=60, with_courier=True):
    """DELAYED report walked to FOUND_PENDING_DELIVERY via a LOCATED event.

    Returns dict with keys: station, carrier, courier, passenger, bag, report.
    """
    ctx = setup_bag_and_report(is_international=is_international, weight_kg=weight_kg,
                               declared_value_cents=declared_value_cents,
                               report_type="DELAYED", tier=tier)
    courier = None
    if with_courier:
        courier = create_courier_service([ctx["station"]["id"]],
                                         turnaround_buffer_minutes=courier_buffer)
    get_success_data(api_client.record_tracing_event(
        ctx["report"]["id"],
        create_tracing_event_payload(ctx["carrier"]["id"], ctx["station"]["id"], "LOCATED"),
        AGENT))
    ctx["courier"] = courier
    return ctx


def setup_declared_lost_report(is_international=False, weight_kg=20,
                               declared_value_cents=0, tier="STANDARD",
                               bags_handled_total=1000000):
    """DELAYED report swept to DECLARED_LOST at created_at + 504h.

    Returns dict with keys: station, carrier, passenger, bag, report.
    """
    ctx = setup_bag_and_report(is_international=is_international, weight_kg=weight_kg,
                               declared_value_cents=declared_value_cents,
                               report_type="DELAYED", tier=tier,
                               bags_handled_total=bags_handled_total)
    set_clock(CLOCK_PLUS_504H)
    return ctx


def setup_settlement_accepted(contents_loss_cents=100000, is_international=True,
                              weight_kg=20, declared_value_cents=0,
                              root_cause="MISCONNECT", bags_handled_total=1000000):
    """Report walked to SETTLEMENT_ACCEPTED via the lost-bag path.

    Returns dict with keys: station, carrier, passenger, bag, report, report_version
    (the report's version after acceptance — the fresh OCC value for payment creation).
    """
    ctx = setup_declared_lost_report(is_international=is_international,
                                     weight_kg=weight_kg,
                                     declared_value_cents=declared_value_cents,
                                     bags_handled_total=bags_handled_total)
    rpt_id = ctx["report"]["id"]
    get_success_data(api_client.assess_loss(
        rpt_id, {"contents_loss_cents": contents_loss_cents}, ADJUSTER))
    get_success_data(api_client.offer_settlement(
        rpt_id, {"root_cause": root_cause,
                 "root_cause_station_id": ctx["station"]["id"]}, ADJUSTER))
    accepted = get_success_data(api_client.accept_settlement(
        rpt_id, make_passenger_headers(ctx["passenger"]["id"])))
    ctx["report"] = accepted
    ctx["report_version"] = accepted["version"]
    return ctx


def setup_closed_report(contents_loss_cents=100000, is_international=True,
                        root_cause="MISCONNECT", bags_handled_total=1000000):
    """Full lifecycle through CLOSED.

    Returns dict with keys: station, carrier, passenger, bag, report, payment.
    """
    ctx = setup_settlement_accepted(contents_loss_cents=contents_loss_cents,
                                    is_international=is_international,
                                    root_cause=root_cause,
                                    bags_handled_total=bags_handled_total)
    rpt_id = ctx["report"]["id"]
    payment = get_success_data(api_client.create_settlement_payment(
        rpt_id, {"expected_report_version": ctx["report_version"]}, ADJUSTER))
    paid = get_success_data(api_client.mark_payment_paid(payment["id"], ADJUSTER))
    ctx["payment"] = paid
    ctx["report"] = get_success_data(api_client.get_report(rpt_id, ADJUSTER))
    return ctx


def setup_damage_report_repairable(contents_damage_cents=5000):
    """DAMAGED report assessed repairable, still in DAMAGE_REVIEW.

    Returns dict with keys: station, carrier, passenger, bag, report.
    """
    ctx = setup_bag_and_report(report_type="DAMAGED")
    get_success_data(api_client.assess_damage(
        ctx["report"]["id"],
        {"repairable": True, "contents_damage_cents": contents_damage_cents}, ADJUSTER))
    return ctx


def setup_damage_report_claim_review(contents_damage_cents=5000):
    """DAMAGED report assessed NOT repairable -> CLAIM_REVIEW.

    Returns dict with keys: station, carrier, passenger, bag, report.
    """
    ctx = setup_bag_and_report(report_type="DAMAGED")
    report = get_success_data(api_client.assess_damage(
        ctx["report"]["id"],
        {"repairable": False, "contents_damage_cents": contents_damage_cents}, ADJUSTER))
    ctx["report"] = report
    return ctx


def create_dispatch_for_report(report_id, courier_id, pickup_at="2026-08-02T10:00:00Z",
                               travel_minutes=120, delivery_address="1 Main St"):
    return get_success_data(api_client.create_dispatch(
        create_dispatch_payload(report_id, courier_id, pickup_at=pickup_at,
                                travel_minutes=travel_minutes,
                                delivery_address=delivery_address), AGENT))


def create_expense_claim(report_id, passenger_id, receipts):
    """Passenger-scoped creation: threads the owning passenger's identity."""
    return get_success_data(api_client.create_expense_claim(
        create_expense_claim_payload(report_id, receipts),
        make_passenger_headers(passenger_id)))
