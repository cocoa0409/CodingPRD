"""Composite setup helpers for the Salon Spa Booking API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server's database is empty at the start of each test.
All setup calls use get_success_data() (lenient) so failures surface as clear
"Setup failed" errors.

Identity threading: the entity-backed roles (Stylist, Client) must carry the
acting entity's id as X-User-ID for ownership-gated calls. Helpers that need a
Client/Stylist actor accept/return the relevant entity ids so callers can build
ownership-correct headers with make_client_headers / make_stylist_headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_salon_owner_headers,
    make_front_desk_headers,
)
from . import factories as F


OWNER = TEST_USERS["salon_owner_headers"]
FRONT = TEST_USERS["front_desk_headers"]


# --------------------------------------------------------------------------- #
# Low-level single-entity creators (return the created data dict)
# --------------------------------------------------------------------------- #
def create_salon(**overrides) -> dict:
    return get_success_data(api_client.create_salon(F.create_salon_payload(**overrides), OWNER))


def create_stylist(salon_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_stylist(F.create_stylist_payload(salon_id, **overrides), OWNER)
    )


def create_resource(salon_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_resource(F.create_resource_payload(salon_id, **overrides), OWNER)
    )


def create_service(salon_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_service(F.create_service_payload(salon_id, **overrides), OWNER)
    )


def create_client(salon_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_client(F.create_client_payload(salon_id, **overrides), FRONT)
    )


def create_membership_plan(salon_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_membership_plan(
            F.create_membership_plan_payload(salon_id, **overrides), OWNER
        )
    )


def create_membership(client_id, plan_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_membership(
            F.create_membership_payload(client_id, plan_id, **overrides), FRONT
        )
    )


def create_package(salon_id, service_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_package(
            F.create_package_payload(salon_id, service_id, **overrides), OWNER
        )
    )


def create_package_purchase(client_id, package_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_package_purchase(
            F.create_package_purchase_payload(client_id, package_id, **overrides), FRONT
        )
    )


def create_product_sku(salon_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_product_sku(
            F.create_product_sku_payload(salon_id, **overrides), OWNER
        )
    )


# --------------------------------------------------------------------------- #
# Clock control (Tier 1 — temporal state progression)
# --------------------------------------------------------------------------- #
def advance_clock(salon_id, to_iso8601, expected_salon_version) -> dict:
    """Advance the salon's simulated clock; returns the updated salon (new version)."""
    return get_success_data(
        api_client.advance_clock(
            salon_id, F.clock_advance_payload(to_iso8601, expected_salon_version), OWNER
        )
    )


# --------------------------------------------------------------------------- #
# Tier 2: a bookable salon setup (salon + N stylists + N resources + service
# + client) with the clock advanced to a known instant so future bookings pass.
# --------------------------------------------------------------------------- #
def setup_bookable_salon(
    *,
    salon_overrides=None,
    stylist_overrides=None,
    resource_overrides=None,
    service_overrides=None,
    client_overrides=None,
    num_stylists=1,
    num_resources=1,
    clock_to="2026-07-01T12:00:00Z",
):
    """Build an active salon ready to accept a future booking.

    Returns a dict with keys:
      salon, salon_version (current), stylists (list), resources (list),
      service, client.
    stylist/resource overrides may be a single dict (applied to all) or a list
    (one per entity).
    """
    salon = create_salon(**(salon_overrides or {}))
    sid = salon["id"]

    def _ov(ov, i):
        if ov is None:
            return {}
        if isinstance(ov, list):
            return ov[i] if i < len(ov) else {}
        return ov

    stylists = [
        create_stylist(sid, full_name=f"Stylist {i+1}", **_ov(stylist_overrides, i))
        for i in range(num_stylists)
    ]
    resources = [
        create_resource(sid, label=f"Chair {i+1}", **_ov(resource_overrides, i))
        for i in range(num_resources)
    ]
    service = create_service(sid, **(service_overrides or {}))
    client = create_client(sid, **(client_overrides or {}))

    salon_version = salon["version"]
    if clock_to is not None:
        salon = advance_clock(sid, clock_to, salon_version)
        salon_version = salon["version"]

    return {
        "salon": salon,
        "salon_version": salon_version,
        "stylists": stylists,
        "resources": resources,
        "service": service,
        "client": client,
    }


# --------------------------------------------------------------------------- #
# Tier 2/3: book one appointment, returning the appointment and the stylist's
# advanced version (booking bumps Stylist.version by one).
# --------------------------------------------------------------------------- #
def book_appointment(
    salon_id, client_id, stylist, resource_id, service_id, start_utc,
    *, headers=None, package_purchase_id=None, expected_stylist_version=None
):
    """Book an appointment as FrontDesk (default) and return
    (appointment_data, new_stylist_version). `stylist` is the stylist dict so
    its current version can be used for the OCC guard."""
    ev = expected_stylist_version if expected_stylist_version is not None else stylist["version"]
    payload = F.create_appointment_payload(
        salon_id, client_id, stylist["id"], resource_id, service_id, start_utc, ev
    )
    if package_purchase_id is not None:
        payload["package_purchase_id"] = package_purchase_id
    appt = get_success_data(
        api_client.create_appointment(payload, headers or FRONT)
    )
    # A successful booking advances the stylist's version by one.
    stylist["version"] = ev + 1
    return appt, stylist["version"]


# --------------------------------------------------------------------------- #
# Tier 3: complete an appointment via checkout (the COMPLETE trigger). Caller
# must have advanced the clock to/after start_utc.
# --------------------------------------------------------------------------- #
def checkout_appointment(appointment_id, *, tip_cents=0, retail_lines=None, headers=None) -> dict:
    payload = F.create_checkout_payload(appointment_id, tip_cents=tip_cents)
    if retail_lines is not None:
        payload["retail_lines"] = retail_lines
    return get_success_data(api_client.create_checkout(payload, headers or FRONT))


# --------------------------------------------------------------------------- #
# Tier 3: a completed checkout, end-to-end (book -> advance past start ->
# checkout). Returns everything tests for split/tip/retail need.
# --------------------------------------------------------------------------- #
def setup_completed_checkout(
    *,
    salon_overrides=None,
    stylist_overrides=None,
    service_overrides=None,
    start_utc="2026-07-01T13:00:00Z",
    after_start_utc="2026-07-01T14:00:00Z",
    tip_cents=0,
    retail_lines=None,
    skus=None,
):
    """Active salon -> one stylist -> one chair -> service -> client ->
    booking at start_utc -> advance to after_start_utc -> checkout.

    `skus` is an optional list of product-sku override dicts to create before
    checkout (their created dicts are returned under 'skus').
    Returns dict: salon, salon_version, stylist, resource, service, client,
    appointment, checkout, skus.
    """
    base = setup_bookable_salon(
        salon_overrides=salon_overrides,
        stylist_overrides=stylist_overrides,
        service_overrides=service_overrides,
    )
    salon, sid = base["salon"], base["salon"]["id"]
    stylist = base["stylists"][0]
    resource = base["resources"][0]
    service = base["service"]
    client = base["client"]

    created_skus = [create_product_sku(sid, **ov) for ov in (skus or [])]

    appt, _ = book_appointment(
        sid, client["id"], stylist, resource["id"], service["id"], start_utc
    )
    salon = advance_clock(sid, after_start_utc, base["salon_version"])
    checkout = checkout_appointment(
        appt["id"], tip_cents=tip_cents, retail_lines=retail_lines
    )
    return {
        "salon": salon,
        "salon_version": salon["version"],
        "stylist": stylist,
        "resource": resource,
        "service": service,
        "client": client,
        "appointment": appt,
        "checkout": checkout,
        "skus": created_skus,
    }


# --------------------------------------------------------------------------- #
# Tier 4: drive a client to a chosen strike count via repeated no-shows.
# Each no-show needs its own future appointment then the clock advanced past it.
# --------------------------------------------------------------------------- #
def setup_client_with_noshows(
    num_noshows,
    *,
    salon_overrides=None,
    service_overrides=None,
):
    """Create a salon/stylist/chair/service/client, then book `num_noshows`
    appointments (one per hour from 13:00) and no-show each after advancing the
    clock. Returns dict: salon, salon_version, stylist, resource, service,
    client, appointments (list, in no-show order), salon_id.

    Uses buffer 0 + one chair; appointments are spaced hourly so neither the
    stylist nor the resource ever double-books.
    """
    base = setup_bookable_salon(
        salon_overrides=salon_overrides,
        stylist_overrides={"buffer_minutes": 0},
        service_overrides=service_overrides,
    )
    salon, sid = base["salon"], base["salon"]["id"]
    stylist = base["stylists"][0]
    resource = base["resources"][0]
    service = base["service"]
    client = base["client"]

    appts = []
    for i in range(num_noshows):
        start = f"2026-07-01T{13 + i:02d}:00:00Z"
        appt, _ = book_appointment(
            sid, client["id"], stylist, resource["id"], service["id"], start
        )
        appts.append(appt)

    # Advance the clock well past all booked starts, then no-show each.
    far = f"2026-07-01T{13 + num_noshows + 1:02d}:00:00Z"
    salon = advance_clock(sid, far, base["salon_version"])
    for appt in appts:
        get_success_data(api_client.no_show_appointment(appt["id"], FRONT))

    return {
        "salon": salon,
        "salon_version": salon["version"],
        "stylist": stylist,
        "resource": resource,
        "service": service,
        "client": client,
        "appointments": appts,
        "salon_id": sid,
    }


# --------------------------------------------------------------------------- #
# Tier 1/3: a membership in a chosen state.
# --------------------------------------------------------------------------- #
def setup_membership(salon_id, *, plan_overrides=None, client_overrides=None):
    """Create a plan, a client, and an ACTIVE membership in `salon_id`.
    Returns dict: plan, client, membership."""
    plan = create_membership_plan(salon_id, **(plan_overrides or {}))
    client = create_client(salon_id, **(client_overrides or {}))
    membership = create_membership(client["id"], plan["id"])
    return {"plan": plan, "client": client, "membership": membership}
