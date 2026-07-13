"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Identity threading: every entity_backed write (Donor-owned writes, PartnerAdmin
voids) uses the per-instance header builder with the real entity id so that
ownership checks pass.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_partner_payload,
    create_vehicle_payload,
    create_route_payload,
    create_donor_payload,
    create_pickup_request_payload,
    create_item_payload,
    create_recurring_plan_payload,
    schedule_payload,
)
from .test_users import TEST_USERS, make_donor_headers, make_partner_admin_headers
from .constants import (
    DEFAULT_SERVICE_DATE,
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
)

_DISPATCHER = TEST_USERS["dispatcher_headers"]
_DRIVER = TEST_USERS["driver_headers"]
_PLATFORM = TEST_USERS["platform_admin_headers"]
_ANON = TEST_USERS["anonymous_headers"]


# ─── Primitive builders (one API call each) ───────────────────────────

def create_partner(**overrides) -> dict:
    """PlatformAdmin creates a charity partner. Returns the partner."""
    res = api_client.create_partner(create_partner_payload(**overrides), _PLATFORM)
    return get_success_data(res)


def create_vehicle(**overrides) -> dict:
    """PlatformAdmin creates a vehicle. Returns the vehicle."""
    res = api_client.create_vehicle(create_vehicle_payload(**overrides), _PLATFORM)
    return get_success_data(res)


def create_donor(**overrides) -> dict:
    """Anonymous self-registers a donor. Returns the donor."""
    res = api_client.create_donor(create_donor_payload(**overrides), _ANON)
    return get_success_data(res)


def create_route(vehicle_id: str, partner_id: str, **overrides) -> dict:
    """Dispatcher creates a PLANNED route. Returns the route."""
    res = api_client.create_route(create_route_payload(vehicle_id, partner_id, **overrides), _DISPATCHER)
    return get_success_data(res)


def open_route(route_id: str) -> dict:
    """Dispatcher opens a route (PLANNED -> OPEN). Returns the opened route."""
    return get_success_data(api_client.open_route(route_id, _DISPATCHER))


def route_version(route_id: str) -> int:
    """Read the route's current version (freshly, as a dispatcher would)."""
    route = get_success_data(api_client.get_route(route_id, _DISPATCHER))
    return route["version"]


def create_request(donor_id: str, partner_id: str, **overrides) -> dict:
    """Donor creates a pickup request (ownership-threaded). Returns the request."""
    headers = make_donor_headers(donor_id)
    res = api_client.create_pickup_request(
        create_pickup_request_payload(donor_id, partner_id, **overrides), headers)
    return get_success_data(res)


def add_item(request_id: str, donor_id: str, **overrides) -> dict:
    """Donor adds an item to their REQUESTED pickup. Returns the item."""
    headers = make_donor_headers(donor_id)
    res = api_client.add_item(request_id, create_item_payload(**overrides), headers)
    return get_success_data(res)


def schedule_request(request_id: str, route_id: str, slot_start: str, slot_end: str,
                     expected_route_version=None) -> dict:
    """Dispatcher schedules a request onto a route. If expected_route_version is
    omitted, the route's current version is read first. Returns the RouteStop."""
    if expected_route_version is None:
        expected_route_version = route_version(route_id)
    res = api_client.schedule_pickup(
        request_id,
        schedule_payload(route_id, expected_route_version, slot_start, slot_end),
        _DISPATCHER,
    )
    return get_success_data(res)


def complete_request(request_id: str, measured_volume_cf: int) -> dict:
    """Driver completes a scheduled pickup. Returns the request."""
    res = api_client.complete_pickup(request_id, {"measured_volume_cf": measured_volume_cf}, _DRIVER)
    return get_success_data(res)


def appraise_item(item_id: str, **fields) -> dict:
    """Driver appraises an item (value/condition/weight/stream). Returns the item."""
    res = api_client.appraise_item(item_id, dict(fields), _DRIVER)
    return get_success_data(res)


def create_recurring_plan(donor_id: str, partner_id: str, **overrides) -> dict:
    """Donor creates a recurring plan (ownership-threaded). Returns the plan."""
    headers = make_donor_headers(donor_id)
    res = api_client.create_recurring_plan(
        create_recurring_plan_payload(donor_id, partner_id, **overrides), headers)
    return get_success_data(res)


# ─── Lookups for cross-aggregate children ─────────────────────────────

def get_receipt_for_request(request_id: str, partner_id: str) -> dict:
    """List donation receipts for a request and return the single receipt."""
    headers = make_partner_admin_headers(partner_id)
    data = get_success_data(api_client.list_receipts(headers, params={"request_id": request_id}))
    assert len(data) >= 1, f"expected a receipt for request {request_id}"
    return data[0]


def get_invoice_for_request(request_id: str, donor_id: str) -> dict:
    """List haul invoices for a request and return the single invoice."""
    headers = make_donor_headers(donor_id)
    data = get_success_data(api_client.list_request_haul_invoices(request_id, headers))
    assert len(data) >= 1, f"expected an invoice for request {request_id}"
    return data[0]


# ─── Composite: provision an OPEN route for a partner ─────────────────

def setup_open_route(partner_categories=None, capacity_cf=200,
                     service_date=DEFAULT_SERVICE_DATE,
                     window_start=DEFAULT_WINDOW_START,
                     window_end=DEFAULT_WINDOW_END,
                     partner_status=None) -> dict:
    """Partner + vehicle + OPEN route. Returns dict with partner, vehicle,
    route (post-open), and route_version (captured at open)."""
    partner_kwargs = {"accepted_categories": partner_categories or ["FURNITURE"]}
    if partner_status is not None:
        partner_kwargs["status"] = partner_status
    partner = create_partner(**partner_kwargs)
    vehicle = create_vehicle(capacity_cf=capacity_cf)
    route = create_route(vehicle["id"], partner["id"], service_date=service_date,
                         window_start=window_start, window_end=window_end)
    opened = open_route(route["id"])
    return {
        "partner": partner,
        "vehicle": vehicle,
        "route": opened,
        "route_version": opened["version"],
    }


# ─── Composite: a REQUESTED request ready to schedule ─────────────────

def setup_schedulable_request(partner_categories=None, capacity_cf=200,
                              disposition="DONATION", pickup_mode="ATTENDED",
                              porch_photo_url=None, safety_attestation=None,
                              items=None, open_route_flag=True,
                              service_date=DEFAULT_SERVICE_DATE,
                              window_start=DEFAULT_WINDOW_START,
                              window_end=DEFAULT_WINDOW_END) -> dict:
    """Provision partner + vehicle + route (optionally OPEN) + donor + a
    REQUESTED pickup request with items. Does NOT schedule.

    `items` is a list of item-payload override dicts; when None a single
    FURNITURE item of volume 20 is added; pass [] to add no items.

    Returns dict: partner, vehicle, route, route_version, donor, request, items.
    """
    partner = create_partner(accepted_categories=partner_categories or ["FURNITURE"])
    vehicle = create_vehicle(capacity_cf=capacity_cf)
    route = create_route(vehicle["id"], partner["id"], service_date=service_date,
                         window_start=window_start, window_end=window_end)
    if open_route_flag:
        route = open_route(route["id"])

    donor = create_donor()
    req_overrides = {"disposition": disposition, "pickup_mode": pickup_mode}
    if porch_photo_url is not None:
        req_overrides["porch_photo_url"] = porch_photo_url
    if safety_attestation is not None:
        req_overrides["safety_attestation"] = safety_attestation
    request = create_request(donor["id"], partner["id"], **req_overrides)

    if items is None:
        items = [{}]
    created_items = [add_item(request["id"], donor["id"], **item) for item in items]

    return {
        "partner": partner,
        "vehicle": vehicle,
        "route": route,
        "route_version": route["version"],
        "donor": donor,
        "request": request,
        "items": created_items,
    }


# ─── Composite: a SCHEDULED request ───────────────────────────────────

def setup_scheduled_request(slot_start="2026-03-15T10:00:00Z",
                            slot_end="2026-03-15T10:30:00Z",
                            **scenario_kwargs) -> dict:
    """setup_schedulable_request(...) then schedule it. Adds `stop` to the
    returned dict and refreshes `route_version` to the post-schedule value."""
    ctx = setup_schedulable_request(**scenario_kwargs)
    stop = schedule_request(ctx["request"]["id"], ctx["route"]["id"], slot_start, slot_end,
                            expected_route_version=ctx["route_version"])
    ctx["stop"] = stop
    ctx["route_version"] = route_version(ctx["route"]["id"])
    return ctx


# ─── Composite: a COMPLETED donation with an ISSUED receipt ───────────

def setup_completed_donation(items=None, appraisals=None, measured_volume_cf=None,
                             partner_categories=None, capacity_cf=200) -> dict:
    """Provision through a COMPLETED DONATION pickup with an ISSUED receipt.

    `items`      — item override dicts (default: two HOUSEHOLD items 1005/GOOD/vol 25).
    `appraisals` — optional list aligned with items; each entry a dict of appraisal
                   fields applied to the corresponding item before completion.
    Returns dict adding `receipt` (the issued DonationReceipt).
    """
    if items is None:
        items = [
            {"category": "HOUSEHOLD", "volume_cf": 25, "weight_lbs": 10,
             "declared_value_cents": 1005, "declared_condition": "GOOD"},
            {"category": "HOUSEHOLD", "volume_cf": 25, "weight_lbs": 10,
             "declared_value_cents": 1005, "declared_condition": "GOOD"},
        ]
    ctx = setup_scheduled_request(
        partner_categories=partner_categories or ["HOUSEHOLD"],
        capacity_cf=capacity_cf, disposition="DONATION", pickup_mode="ATTENDED",
        items=items,
    )
    if appraisals:
        for item, appraisal in zip(ctx["items"], appraisals):
            if appraisal:
                appraise_item(item["id"], **appraisal)
    if measured_volume_cf is None:
        measured_volume_cf = sum(i["volume_cf"] for i in ctx["items"])
    complete_request(ctx["request"]["id"], measured_volume_cf)
    ctx["receipt"] = get_receipt_for_request(ctx["request"]["id"], ctx["partner"]["id"])
    return ctx


# ─── Composite: a COMPLETED haul with an INVOICED HaulInvoice ─────────

def setup_completed_haul(items=None, appraisals=None, measured_volume_cf=20,
                         pickup_mode="ATTENDED", porch_photo_url=None,
                         safety_attestation=None, capacity_cf=200) -> dict:
    """Provision through a COMPLETED HAUL pickup with an INVOICED invoice.
    Returns dict adding `invoice` (the HaulInvoice)."""
    if items is None:
        items = [{"category": "FURNITURE", "volume_cf": 20, "weight_lbs": 5,
                  "declared_value_cents": 100, "declared_condition": "GOOD"}]
    ctx = setup_scheduled_request(
        partner_categories=["FURNITURE"], capacity_cf=capacity_cf,
        disposition="HAUL", pickup_mode=pickup_mode,
        porch_photo_url=porch_photo_url, safety_attestation=safety_attestation,
        items=items,
    )
    if appraisals:
        for item, appraisal in zip(ctx["items"], appraisals):
            if appraisal:
                appraise_item(item["id"], **appraisal)
    complete_request(ctx["request"]["id"], measured_volume_cf)
    ctx["invoice"] = get_invoice_for_request(ctx["request"]["id"], ctx["donor"]["id"])
    return ctx


# ─── Composite: a PAUSED recurring plan ───────────────────────────────

def setup_paused_plan(frequency="WEEKLY", default_disposition="DONATION") -> dict:
    """Partner + donor + plan created ACTIVE then paused (PAUSED).
    Returns dict: partner, donor, plan (post-pause)."""
    partner = create_partner()
    donor = create_donor()
    plan = create_recurring_plan(donor["id"], partner["id"],
                                 frequency=frequency, default_disposition=default_disposition)
    paused = get_success_data(api_client.pause_plan(plan["id"], make_donor_headers(donor["id"])))
    return {"partner": partner, "donor": donor, "plan": paused}
