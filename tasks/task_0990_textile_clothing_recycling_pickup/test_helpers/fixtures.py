"""Composite setup helpers.

Multi-step arrange chains built only from PRD-declared endpoints. Each test
starts against a fresh server, so every helper builds its preconditions from
scratch. Setup calls use the lenient get_success_data() validator so failures
surface as clear setup errors. Entity-backed role calls thread the real entity
id through the make_*_headers builders.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_zone_payload, create_resident_payload, create_bag_kit_payload,
    create_pickup_payload, route_pickup_payload, mark_collected_payload,
    create_partner_payload, create_dropbox_payload, create_fill_reading_payload,
    certify_ticket_payload, create_contamination_report_payload,
    create_sponsor_fund_payload, create_charity_payload,
    create_reporting_period_payload, charity_split_payload, clock_payload,
)
from .test_users import (
    TEST_USERS, make_resident_headers, make_driver_headers,
    make_partner_manager_headers, make_inspector_headers,
)

OP = TEST_USERS["zone_operator_headers"]
DRIVER = TEST_USERS["driver_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
SENSOR = TEST_USERS["sensor_gateway_headers"]

DEFAULT_WINDOW_START = "2026-05-10T10:00:00Z"
DEFAULT_WINDOW_END = "2026-05-10T12:00:00Z"
DEFAULT_SERVICE_DATE = "2026-05-10"
DEFAULT_DRIVER_ID = "drv-1"


# --- Single-entity creators -------------------------------------------------

def new_zone(name="Zone"):
    return get_success_data(api_client.create_zone(create_zone_payload(name=name), OP))


def new_charity(name="ClothesAid"):
    return get_success_data(api_client.create_charity(create_charity_payload(name=name), OP))


def set_zone_splits(zone, charity_pcts):
    """Replace charity_splits via the OCC-guarded endpoint.

    charity_pcts: list of (charity_dict, pct). Returns the updated zone.
    """
    lines = [{"charity_id": c["id"], "pct": pct} for c, pct in charity_pcts]
    resp = api_client.replace_charity_split(
        zone["id"], charity_split_payload(lines, zone["version"]), OP
    )
    return get_success_data(resp)


def new_fund(zone_id, initial_cents=100000, sponsor_name="EcoCorp"):
    payload = create_sponsor_fund_payload(
        zone_id, sponsor_name=sponsor_name, initial_cents=initial_cents
    )
    return get_success_data(api_client.create_sponsor_fund(payload, OP))


def new_resident(zone_id, full_name="Resident Ray", email="resident@x.com", address="1 Main St"):
    payload = create_resident_payload(
        zone_id, full_name=full_name, email=email, address=address
    )
    return get_success_data(api_client.create_resident(payload, OP))


def new_partner(name="ThriftCo", partner_type="THRIFT", accepted_grades=("RESALE", "RECYCLE"),
                capacity_kg=1000):
    payload = create_partner_payload(
        name=name, partner_type=partner_type,
        accepted_grades=list(accepted_grades), capacity_kg=capacity_kg,
    )
    return get_success_data(api_client.create_partner(payload, OP))


def new_dropbox(zone_id, label="Box-1", location="Depot"):
    payload = create_dropbox_payload(zone_id, label=label, location=location)
    return get_success_data(api_client.create_dropbox(payload, OP))


# --- Kit chain ---------------------------------------------------------------

def order_kit(resident_id, kit_type="BAG"):
    resp = api_client.order_bag_kit(
        resident_id, create_bag_kit_payload(kit_type=kit_type),
        make_resident_headers(resident_id),
    )
    return get_success_data(resp)


def dispatch_kit(kit_id):
    return get_success_data(api_client.dispatch_bag_kit(kit_id, OP))


def deliver_kit(kit_id, driver_id=DEFAULT_DRIVER_ID):
    return get_success_data(api_client.deliver_bag_kit(kit_id, make_driver_headers(driver_id)))


def new_delivered_kit(resident_id, kit_type="BAG"):
    """Order -> dispatch -> deliver. Returns the DELIVERED kit."""
    kit = order_kit(resident_id, kit_type)
    dispatch_kit(kit["id"])
    return deliver_kit(kit["id"])


# --- Pickup chain --------------------------------------------------------------

def new_pickup(resident_id, window_start=DEFAULT_WINDOW_START,
               window_end=DEFAULT_WINDOW_END, bags_claimed=10):
    payload = create_pickup_payload(
        resident_id, window_start=window_start, window_end=window_end,
        bags_claimed=bags_claimed,
    )
    return get_success_data(api_client.create_pickup_request(payload, make_resident_headers(resident_id)))


def route_pickup(pickup_id, driver_id=DEFAULT_DRIVER_ID, service_date=DEFAULT_SERVICE_DATE):
    payload = route_pickup_payload(driver_id=driver_id, service_date=service_date)
    return get_success_data(api_client.route_pickup(pickup_id, payload, OP))


def collect_pickup(pickup_id, driver_id=DEFAULT_DRIVER_ID, provisional_weight_kg=40.0):
    """mark-collected (201): returns the created PROVISIONAL WeightTicket."""
    resp = api_client.mark_collected(
        pickup_id, mark_collected_payload(provisional_weight_kg=provisional_weight_kg),
        make_driver_headers(driver_id),
    )
    return get_success_data(resp)


def no_show_pickup(pickup_id, driver_id=DEFAULT_DRIVER_ID):
    return get_success_data(api_client.mark_no_show(pickup_id, make_driver_headers(driver_id)))


def rebook_pickup(pickup_id, resident_id, window_start, window_end):
    payload = {"window_start": window_start, "window_end": window_end}
    return get_success_data(api_client.rebook_pickup(pickup_id, payload, make_resident_headers(resident_id)))


# --- Ticket / credit chain ------------------------------------------------------

def certify_ticket(ticket_id, certified_weight_kg=12.5, grade="RESALE"):
    payload = certify_ticket_payload(certified_weight_kg=certified_weight_kg, grade=grade)
    return get_success_data(api_client.certify_ticket(ticket_id, payload, OP))


def new_credit(ticket_id):
    return get_success_data(api_client.create_diversion_credit(ticket_id, OP))


def finalize_credit(credit_id):
    return get_success_data(api_client.finalize_credit(credit_id, OP))


def dispute_credit(credit_id, resident_id, reason="resident contests certified weight"):
    return get_success_data(api_client.dispute_credit(
        credit_id, {"reason": reason}, make_resident_headers(resident_id)
    ))


def settle_credit(credit_id):
    return get_success_data(api_client.settle_credit(credit_id, OP))


def void_credit(credit_id):
    return get_success_data(api_client.void_credit(credit_id, OP))


# --- Routing selector chain -------------------------------------------------------

def run_selector(ticket_id):
    """POST /weight-tickets/{id}/routing-assignments (201): returns PENDING assignment."""
    return get_success_data(api_client.create_routing_assignment(ticket_id, OP))


def accept_assignment(assignment_id, partner_id):
    return get_success_data(api_client.accept_routing_assignment(
        assignment_id, make_partner_manager_headers(partner_id)
    ))


def decline_assignment(assignment_id, partner_id, reason=None):
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(api_client.decline_routing_assignment(
        assignment_id, payload, make_partner_manager_headers(partner_id)
    ))


def complete_assignment(assignment_id, partner_id):
    return get_success_data(api_client.complete_routing_assignment(
        assignment_id, make_partner_manager_headers(partner_id)
    ))


# --- Drop-box chain ------------------------------------------------------------

def post_reading(dropbox_id, fill_pct, recorded_at="2026-05-01T06:00:00Z"):
    payload = create_fill_reading_payload(fill_pct=fill_pct, recorded_at=recorded_at)
    return get_success_data(api_client.create_fill_reading(dropbox_id, payload, SENSOR))


def collect_box(dropbox_id, provisional_weight_kg=55.0, driver_id=DEFAULT_DRIVER_ID):
    """POST collections (201): returns the created PROVISIONAL WeightTicket."""
    resp = api_client.create_dropbox_collection(
        dropbox_id, mark_collected_payload(provisional_weight_kg=provisional_weight_kg),
        make_driver_headers(driver_id),
    )
    return get_success_data(resp)


# --- Contamination chain ---------------------------------------------------------

def file_report(ticket_id, severity="MAJOR", notes=None, inspector_id="insp-1"):
    payload = create_contamination_report_payload(severity=severity)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_contamination_report(
        ticket_id, payload, make_inspector_headers(inspector_id)
    ))


def adjudicate_report(report_id, outcome="UPHELD"):
    return get_success_data(api_client.adjudicate_report(report_id, {"outcome": outcome}, OP))


# --- Reporting period / clock -------------------------------------------------

def new_reporting_period(zone_id, period_start="2026-05-01T00:00:00Z",
                         period_end="2026-06-01T00:00:00Z"):
    payload = create_reporting_period_payload(period_start=period_start, period_end=period_end)
    return get_success_data(api_client.create_reporting_period(zone_id, payload, OP))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), OP))


# --- Read helpers (lenient) ------------------------------------------------------

def read_zone(zone_id):
    return get_success_data(api_client.get_zone(zone_id, OP))


def read_resident(resident_id):
    return get_success_data(api_client.get_resident(resident_id, OP))


def read_pickup(pickup_id):
    return get_success_data(api_client.get_pickup_request(pickup_id, OP))


def read_ticket(ticket_id):
    return get_success_data(api_client.get_weight_ticket(ticket_id, OP))


def read_credit(credit_id):
    return get_success_data(api_client.get_diversion_credit(credit_id, OP))


def read_fund(fund_id):
    return get_success_data(api_client.get_sponsor_fund(fund_id, OP))


def read_partner(partner_id):
    return get_success_data(api_client.get_partner(partner_id, OP))


def read_dropbox(dropbox_id):
    return get_success_data(api_client.get_dropbox(dropbox_id, OP))


def read_charity(charity_id):
    return get_success_data(api_client.get_charity(charity_id, OP))


def read_period(period_id):
    return get_success_data(api_client.get_reporting_period(period_id, OP))


# --- Composite pipelines ---------------------------------------------------------

def ctx_collected(*, zone_name="Zone", fund_cents=None, splits=None, partner=None,
                  resident_name="Rita Ray", resident_email="rita@x.com",
                  kit_type="BAG", bags_claimed=10,
                  window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END,
                  driver_id=DEFAULT_DRIVER_ID, service_date=DEFAULT_SERVICE_DATE,
                  provisional_weight_kg=40.0):
    """Zone (+optional splits/fund/partner) + resident + DELIVERED kit +
    ROUTED pickup + collected PROVISIONAL ticket."""
    zone = new_zone(zone_name)
    charities = []
    if splits:
        charities = [new_charity(name) for name, _ in splits]
        zone = set_zone_splits(zone, list(zip(charities, [p for _, p in splits])))
    fund = new_fund(zone["id"], fund_cents) if fund_cents is not None else None
    partner_obj = new_partner(**partner) if partner else None
    resident = new_resident(zone["id"], resident_name, resident_email)
    kit = new_delivered_kit(resident["id"], kit_type)
    pickup = new_pickup(resident["id"], window_start, window_end, bags_claimed)
    pickup = route_pickup(pickup["id"], driver_id, service_date)
    ticket = collect_pickup(pickup["id"], driver_id, provisional_weight_kg)
    return {
        "zone": zone, "charities": charities, "fund": fund, "partner": partner_obj,
        "resident": resident, "kit": kit, "pickup": pickup, "ticket": ticket,
    }


def ctx_certified(*, certified_weight_kg=12.5, grade="RESALE", **kw):
    """ctx_collected + facility certification (ticket CERTIFIED)."""
    ctx = ctx_collected(**kw)
    ctx["ticket"] = certify_ticket(ctx["ticket"]["id"], certified_weight_kg, grade)
    return ctx


def ctx_credit(**kw):
    """ctx_certified + credit creation (credit PROVISIONAL)."""
    ctx = ctx_certified(**kw)
    ctx["credit"] = new_credit(ctx["ticket"]["id"])
    return ctx


def ctx_finalized(**kw):
    """ctx_credit + finalize (credit FINALIZED, hold placed)."""
    ctx = ctx_credit(**kw)
    ctx["credit"] = finalize_credit(ctx["credit"]["id"])
    return ctx


def ctx_settled(**kw):
    """ctx_finalized + settle (credit SETTLED, splits frozen)."""
    ctx = ctx_finalized(**kw)
    ctx["credit"] = settle_credit(ctx["credit"]["id"])
    return ctx


def ctx_box(*, zone_name="Zone", label="Box-1", location="Depot"):
    zone = new_zone(zone_name)
    box = new_dropbox(zone["id"], label, location)
    return {"zone": zone, "box": box}


def ctx_box_full(*, fill_pct=90.0, recorded_at="2026-05-01T06:00:00Z", **kw):
    """Zone + box driven to FULL_PENDING_COLLECTION by a sensor reading."""
    ctx = ctx_box(**kw)
    ctx["reading"] = post_reading(ctx["box"]["id"], fill_pct, recorded_at)
    ctx["box"] = read_dropbox(ctx["box"]["id"])
    return ctx


def ctx_box_collected(*, provisional_weight_kg=55.0, driver_id=DEFAULT_DRIVER_ID, **kw):
    """ctx_box_full + driver collection: box back to OK, PROVISIONAL ticket created."""
    ctx = ctx_box_full(**kw)
    ctx["ticket"] = collect_box(ctx["box"]["id"], provisional_weight_kg, driver_id)
    return ctx
