"""Composite setup helpers.

These encapsulate the multi-step API sequences that most test claims require
before their trigger call. Every helper uses ``get_success_data`` (lenient 2xx
validator) so a setup break surfaces as a clear "Setup failed" rather than a
confusing assertion error. The database is empty at the start of every test,
so each helper builds its preconditions from scratch.

Identity threading: the ``Resident`` and ``Vendor`` roles are entity-backed,
so any ownership-gated call uses ``make_resident_headers(resident_id)`` /
``make_vendor_headers(vendor_id)`` with the real entity id — never a shared
constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_resident_headers,
    make_vendor_headers,
    make_property_manager_headers,
)
from . import factories as f

PM = TEST_USERS["property_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# --- Clock ------------------------------------------------------------------
def set_clock(api, iso: str):
    return get_success_data(api.set_clock(iso, PM))


# --- Base builders ----------------------------------------------------------
def new_property(api, **overrides) -> dict:
    return get_success_data(api.create_property(f.create_property_payload(**overrides), PM))


def new_unit(api, property_id, **overrides) -> dict:
    return get_success_data(api.create_unit(f.create_unit_payload(property_id, **overrides), PM))


def new_resident(api, unit_id, **overrides) -> dict:
    return get_success_data(api.create_resident(f.create_resident_payload(unit_id, **overrides), PM))


def new_amenity(api, property_id, **overrides) -> dict:
    return get_success_data(api.create_amenity(f.create_amenity_payload(property_id, **overrides), PM))


def new_vendor(api, **overrides) -> dict:
    return get_success_data(api.create_vendor(f.create_vendor_payload(**overrides), PM))


def current_amenity_version(api, amenity_id) -> int:
    return get_success_data(api.get_amenity(amenity_id, PM))["version"]


def new_booking(api, amenity_id, resident_id, start_at, end_at,
                expected_version=None, resident_headers=None) -> dict:
    """Create a CONFIRMED booking. Fetches the live amenity version when not
    supplied. Acts as the owning resident by default (ownership-gated)."""
    if expected_version is None:
        expected_version = current_amenity_version(api, amenity_id)
    headers = resident_headers or make_resident_headers(resident_id)
    payload = f.create_booking_payload(amenity_id, resident_id, start_at, end_at, expected_version)
    return get_success_data(api.create_booking(payload, headers))


# --- Money helpers ----------------------------------------------------------
def charge_resident(api, resident_id, amount_cents, description="charge") -> dict:
    return get_success_data(
        api.create_rent_charge(resident_id, f.create_rent_charge_payload(amount_cents, description=description), PM)
    )


def pay_resident(api, resident_id, amount_cents, method="ACH") -> dict:
    return get_success_data(
        api.create_payment(f.create_payment_payload(resident_id, amount_cents, method), PM)
    )


def get_resident(api, resident_id) -> dict:
    return get_success_data(api.get_resident(resident_id, PM))


def get_booking(api, booking_id) -> dict:
    return get_success_data(api.get_booking(booking_id, PM))


# --- Composite scenarios ----------------------------------------------------
def setup_property_unit_resident(api, property_overrides=None, unit_overrides=None,
                                 resident_overrides=None) -> dict:
    """Property + one Unit + one Resident. Returns dict with keys
    property, unit, resident (each the full resource object)."""
    prop = new_property(api, **(property_overrides or {}))
    unit = new_unit(api, prop["id"], **(unit_overrides or {}))
    resident = new_resident(api, unit["id"], **(resident_overrides or {}))
    return {"property": prop, "unit": unit, "resident": resident}


def setup_amenity_booking_base(api, clock="2026-05-20T00:00:00Z",
                               resident_overrides=None, amenity_overrides=None) -> dict:
    """Property + Unit + Resident + open Amenity, clock set. Returns dict with
    property, unit, resident, amenity."""
    base = setup_property_unit_resident(api, resident_overrides=resident_overrides)
    set_clock(api, clock)
    amenity = new_amenity(api, base["property"]["id"], **(amenity_overrides or {}))
    base["amenity"] = amenity
    return base


def make_resident_delinquent(api, resident_id):
    """Push a resident into DELINQUENT via a 60000 charge (> 50000, <= 150000)."""
    return charge_resident(api, resident_id, 60000, "arrears")


def make_resident_suspended(api, resident_id):
    """Push a resident into SUSPENDED via a 200000 charge (> 150000)."""
    return charge_resident(api, resident_id, 200000, "big arrears")


# --- Service-request lifecycle helpers --------------------------------------
def new_service_request(api, unit_id, resident_id, trade="PLUMBING",
                        description="Issue", **overrides) -> dict:
    payload = f.create_service_request_payload(unit_id, resident_id, trade, description, **overrides)
    return get_success_data(api.create_service_request(payload, PM))


def setup_triaged_request(api, trade="PLUMBING", priority=None,
                          triage_user="pm_triage", vendor_trades=None,
                          vendor_overrides=None) -> dict:
    """Property + Unit + Resident + Vendor + a SUBMITTED service request driven
    to TRIAGED by ``triage_user``. Returns dict: property, unit, resident,
    vendor, sr (the triaged request), triage_user."""
    base = setup_property_unit_resident(api)
    v_over = dict(vendor_overrides or {})
    if vendor_trades is not None:
        v_over["trades"] = vendor_trades
    vendor = new_vendor(api, **v_over)
    sr_over = {}
    if priority is not None:
        sr_over["priority"] = priority
    sr = new_service_request(api, base["unit"]["id"], base["resident"]["id"], trade=trade, **sr_over)
    get_success_data(
        api.triage_service_request(sr["id"], {}, make_property_manager_headers(triage_user))
    )
    return {
        "property": base["property"], "unit": base["unit"], "resident": base["resident"],
        "vendor": vendor, "sr": sr, "triage_user": triage_user,
    }


def setup_assigned_request(api, trade="PLUMBING", priority=None,
                           estimated_hours=2, estimated_parts_cents=None,
                           triage_user="pm_triage", assign_user="pm_assign",
                           vendor_overrides=None) -> dict:
    """Triaged request further driven to ASSIGNED. Returns the same dict plus
    the vendor with an incremented active_job_count."""
    ctx = setup_triaged_request(api, trade=trade, priority=priority,
                                triage_user=triage_user, vendor_overrides=vendor_overrides)
    assign_payload = {"vendor_id": ctx["vendor"]["id"], "estimated_hours": estimated_hours}
    if estimated_parts_cents is not None:
        assign_payload["estimated_parts_cents"] = estimated_parts_cents
    ctx["sr"] = get_success_data(
        api.assign_service_request(ctx["sr"]["id"], assign_payload,
                                   make_property_manager_headers(assign_user))
    )
    ctx["assign_user"] = assign_user
    return ctx


def setup_started_request(api, **kwargs) -> dict:
    """Assigned request driven to IN_PROGRESS by the owning vendor."""
    ctx = setup_assigned_request(api, **kwargs)
    ctx["sr"] = get_success_data(
        api.start_service_request(ctx["sr"]["id"], make_vendor_headers(ctx["vendor"]["id"]))
    )
    return ctx


# --- Event helpers ----------------------------------------------------------
def setup_published_event(api, clock="2026-05-20T00:00:00Z", capacity=5, fee_cents=0,
                          event_start="2026-06-15T18:00:00Z", event_end="2026-06-15T20:00:00Z") -> dict:
    """Property + Unit + Resident + a PUBLISHED event. Returns property, unit,
    resident, event."""
    base = setup_property_unit_resident(api)
    set_clock(api, clock)
    event = get_success_data(api.create_event(
        f.create_event_payload(base["property"]["id"], "Event", event_start, event_end,
                               capacity, fee_cents=fee_cents), PM))
    event = get_success_data(api.publish_event(event["id"], PM))
    base["event"] = event
    return base


def register_resident(api, event_id, resident_id) -> dict:
    return get_success_data(
        api.register_event(event_id, {"resident_id": resident_id}, make_resident_headers(resident_id))
    )
