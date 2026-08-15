"""Composite setup helpers.

Each fixture builds its preconditions from scratch against a freshly restarted
server, using only PRD-declared endpoints. Resident calls are always made with
make_resident_headers(household_id) so ownership checks pass.

All fixtures use get_success_data() so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    cancel_payload,
    create_dumping_report_payload,
    create_household_payload,
    create_item_payload,
    create_pickup_request_payload,
    create_route_day_payload,
    determine_payload,
    schedule_payload,
)
from .test_users import (
    TEST_USERS,
    make_resident_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
DRIVER = TEST_USERS["driver_headers"]

BASE_CLOCK = "2026-08-05T00:00:00Z"
SERVICE_MORNING = "2026-08-10T07:00:00Z"
DEFAULT_ROUTE_DATE = "2026-08-10"


# ---------------------------------------------------------------------------
# Tier 1: atomic steps
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, DISPATCHER)
    return get_success_data(resp)


def create_household(street_address="1 Test Way", service_zone="ZONE_NORTH",
                     annual_allowance_items=None):
    payload = create_household_payload(
        street_address=street_address, service_zone=service_zone
    )
    if annual_allowance_items is not None:
        payload["annual_allowance_items"] = annual_allowance_items
    resp = api_client.create_household(payload, DISPATCHER)
    return get_success_data(resp)


def resident(household_id):
    return make_resident_headers(household_id)


def create_route_day(service_zone="ZONE_NORTH", route_date=DEFAULT_ROUTE_DATE,
                     max_load_units=40, max_stops=25):
    resp = api_client.create_route_day(
        create_route_day_payload(
            service_zone=service_zone, route_date=route_date,
            max_load_units=max_load_units, max_stops=max_stops,
        ),
        DISPATCHER,
    )
    return get_success_data(resp)


def create_draft_request(household_id):
    resp = api_client.create_pickup_request(
        create_pickup_request_payload(household_id), resident(household_id)
    )
    return get_success_data(resp)


def add_item(household_id, request_id, sequence_no=1,
             category="STANDARD_FURNITURE", is_oversize=False,
             preparation_ack=True):
    resp = api_client.add_item(
        request_id,
        create_item_payload(
            sequence_no=sequence_no, category=category,
            is_oversize=is_oversize, preparation_ack=preparation_ack,
        ),
        resident(household_id),
    )
    return get_success_data(resp)


def submit_request(household_id, request_id):
    resp = api_client.submit_pickup_request(request_id, resident(household_id))
    return get_success_data(resp)


def get_route_day(route_day_id):
    return get_success_data(api_client.get_route_day(route_day_id, DISPATCHER))


def schedule_request(household_id, request_id, route_day):
    """Schedule using the route's CURRENT version (fresh GET inside)."""
    current = get_route_day(route_day["id"] if isinstance(route_day, dict) else route_day)
    rd_id = current["id"]
    resp = api_client.schedule_pickup_request(
        request_id,
        schedule_payload(rd_id, current["version"]),
        resident(household_id),
    )
    return get_success_data(resp)


def get_request(household_id, request_id):
    return get_success_data(
        api_client.get_pickup_request(request_id, resident(household_id))
    )


def get_request_items(request_id, headers=None):
    return get_success_data(
        api_client.list_items(request_id, headers or INSPECTOR)
    )


def get_request_assessments(request_id):
    return get_success_data(
        api_client.list_request_fee_assessments(request_id, INSPECTOR)
    )


def get_request_notifications(request_id, headers=None):
    return get_success_data(
        api_client.list_request_notifications(request_id, headers or INSPECTOR)
    )


def get_household_allowances(household_id):
    return get_success_data(
        api_client.list_household_allowances(household_id, INSPECTOR)
    )


def get_household_assessments(household_id):
    return get_success_data(
        api_client.list_household_fee_assessments(household_id, INSPECTOR)
    )


def get_ledger_row(household_id, calendar_year=2026):
    """The (household, year) allowance ledger row; fails if none exists."""
    rows = get_household_allowances(household_id)
    for row in rows:
        if row["calendar_year"] == calendar_year:
            return row
    raise AssertionError(
        f"Setup failed: no allowance ledger row for household {household_id} "
        f"in {calendar_year}"
    )


def find_assessment(assessments, kind):
    for a in assessments:
        if a["kind"] == kind:
            return a
    raise AssertionError(f"Setup failed: no assessment of kind {kind}")


def dispatch_route(route_day_id):
    return get_success_data(api_client.dispatch_route_day(route_day_id, DISPATCHER))


# ---------------------------------------------------------------------------
# Tier 2/3: entity hierarchy + lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_household_with_draft(street_address="1 Test Way",
                               service_zone="ZONE_NORTH",
                               annual_allowance_items=4,
                               items=((1, "STANDARD_FURNITURE", False, True),)):
    """Household + DRAFT request preloaded with the given items.

    items: iterable of (sequence_no, category, is_oversize, preparation_ack).
    Returns (household, request, items_list).
    """
    hh = create_household(street_address, service_zone, annual_allowance_items)
    req = create_draft_request(hh["id"])
    added = [
        add_item(hh["id"], req["id"], seq, cat, oversize, ack)
        for (seq, cat, oversize, ack) in items
    ]
    return hh, req, added


def setup_submitted_request(street_address="1 Test Way",
                            service_zone="ZONE_NORTH",
                            annual_allowance_items=4,
                            items=((1, "STANDARD_FURNITURE", False, True),)):
    """Household + request with items, SUBMITTED. Returns (household, request, items)."""
    hh, req, added = setup_household_with_draft(
        street_address, service_zone, annual_allowance_items, items
    )
    req = submit_request(hh["id"], req["id"])
    return hh, req, added


def setup_scheduled_request(street_address="1 Test Way",
                            service_zone="ZONE_NORTH",
                            annual_allowance_items=4,
                            route_date=DEFAULT_ROUTE_DATE,
                            max_load_units=40, max_stops=25,
                            items=((1, "STANDARD_FURNITURE", False, True),),
                            route_day=None):
    """Household + SUBMITTED request scheduled onto an OPEN route.

    Returns (household, request, items, route_day).
    """
    hh, req, added = setup_submitted_request(
        street_address, service_zone, annual_allowance_items, items
    )
    rd = route_day or create_route_day(
        service_zone=service_zone, route_date=route_date,
        max_load_units=max_load_units, max_stops=max_stops,
    )
    req = schedule_request(hh["id"], req["id"], rd)
    return hh, req, added, get_route_day(rd["id"])


def setup_completed_request(street_address="1 Test Way",
                            service_zone="ZONE_NORTH",
                            annual_allowance_items=4,
                            route_date=DEFAULT_ROUTE_DATE,
                            items=((1, "STANDARD_FURNITURE", False, True),),
                            service_clock=SERVICE_MORNING,
                            improper_preparation_item_ids=None):
    """Full happy path: scheduled -> clock to day-of -> dispatch -> complete.

    Returns (household, request, items, route_day).
    """
    hh, req, added, rd = setup_scheduled_request(
        street_address=street_address, service_zone=service_zone,
        annual_allowance_items=annual_allowance_items,
        route_date=route_date, items=items,
    )
    set_clock(service_clock)
    dispatch_route(rd["id"])
    payload = {}
    if improper_preparation_item_ids is not None:
        payload["improper_preparation_item_ids"] = improper_preparation_item_ids
    req = get_success_data(
        api_client.complete_pickup_request(req["id"], payload, DRIVER)
    )
    return hh, req, added, get_route_day(rd["id"])


def setup_refused_request(street_address="1 Test Way",
                          service_zone="ZONE_NORTH",
                          annual_allowance_items=4,
                          route_date=DEFAULT_ROUTE_DATE,
                          refusal_reason_code="BLOCKED_ACCESS",
                          items=((1, "STANDARD_FURNITURE", False, True),),
                          service_clock=SERVICE_MORNING):
    """Scheduled request on a dispatched route, refused by the driver.

    Returns (household, request, items, route_day).
    """
    hh, req, added, rd = setup_scheduled_request(
        street_address=street_address, service_zone=service_zone,
        annual_allowance_items=annual_allowance_items,
        route_date=route_date, items=items,
    )
    set_clock(service_clock)
    dispatch_route(rd["id"])
    req = get_success_data(
        api_client.refuse_pickup_request(
            req["id"], {"refusal_reason_code": refusal_reason_code}, DRIVER
        )
    )
    return hh, req, added, get_route_day(rd["id"])


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def consume_allowance(household_id, count, service_zone="ZONE_NORTH",
                      calendar_anchor_clock="2026-01-05T00:00:00Z",
                      route_date="2026-01-12"):
    """Consume `count` allowance slots for the household in calendar year 2026
    via a single scheduled request holding `count` STANDARD_FURNITURE items.

    Leaves the clock at calendar_anchor_clock. Returns the consuming request.
    """
    items = tuple((i + 1, "STANDARD_FURNITURE", False, True) for i in range(count))
    req = create_draft_request(household_id)
    for (seq, cat, oversize, ack) in items:
        add_item(household_id, req["id"], seq, cat, oversize, ack)
    submit_request(household_id, req["id"])
    rd = create_route_day(service_zone=service_zone, route_date=route_date)
    schedule_request(household_id, req["id"], rd)
    return get_request(household_id, req["id"])


# ---------------------------------------------------------------------------
# Tier 5: enforcement / terminal states
# ---------------------------------------------------------------------------

def suspend_household_via_illegal_dumping(household_id, notes="confirmed dumping"):
    """File an unlinked dumping report and determine ILLEGAL_DUMPING.

    Returns (report, fine_assessment); household is left SUSPENDED.
    """
    report = get_success_data(
        api_client.create_dumping_report(
            create_dumping_report_payload(household_id), INSPECTOR
        )
    )
    report = get_success_data(
        api_client.determine_dumping_report(
            report["id"], determine_payload("ILLEGAL_DUMPING",
                                            determination_notes=notes),
            INSPECTOR,
        )
    )
    fine = find_assessment(
        get_household_assessments(household_id), "ILLEGAL_DUMPING_FINE"
    )
    return report, fine


def standard_base_clock():
    """Most scenarios start at 2026-08-05 (before the default route date)."""
    set_clock(BASE_CLOCK)
