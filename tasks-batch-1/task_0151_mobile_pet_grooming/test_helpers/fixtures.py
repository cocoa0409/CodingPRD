"""Composite setup helpers for the Mobile Pet Grooming API.

Every test runs against a freshly restarted, empty server, so each fixture
builds its full precondition chain from scratch using only PRD-declared
endpoints. Helpers use get_success_data() (lenient) so a broken setup surfaces
a clear "Setup step failed" message rather than an opaque assertion.

Identity threading: Customer and Groomer are entity-backed. After creating a
Customer/Groomer, ownership-gated calls use make_customer_headers(customer_id)
/ make_groomer_headers(groomer_id) with the real entity id — never the shared
TEST_USERS fallback.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_admin_headers,
    make_dispatcher_headers,
    make_customer_headers,
    make_groomer_headers,
)

# Module-level uniqueness counter so repeated fixture calls within one test do
# not collide on unique fields (email / label / breed name).
_seq = itertools.count(1)


def _u() -> int:
    return next(_seq)


ADMIN = make_admin_headers()
DISPATCH = make_dispatcher_headers()


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
from datetime import datetime, timezone  # noqa: E402

# Mirror of the logical clock the test most recently set, so helpers can tell
# whether the server clock is still behind a reserved slot_start without needing
# a (PRD-undefined) GET-clock endpoint on the implementation.
_last_set_clock = None


def _parse_iso(s):
    """Parse an ISO-8601 UTC instant (trailing 'Z' or offset) to an aware UTC dt."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _server_clock_before(iso: str) -> bool:
    """True when the last clock the test set is strictly before `iso` (so the
    no-show precondition is not yet satisfied). If no clock was set, assume the
    server is on real wall-clock and treat any past-dated test slot as reached."""
    if _last_set_clock is None:
        return False
    return _parse_iso(_last_set_clock) < _parse_iso(iso)


def set_clock(iso: str):
    """Set the server's logical UTC clock (PlatformAdmin only)."""
    global _last_set_clock
    _last_set_clock = iso
    return get_success_data(api_client.set_clock(iso, ADMIN))


# --------------------------------------------------------------------------
# Tier 1: catalog primitives
# --------------------------------------------------------------------------
def create_breed(name=None, coat_type="SMOOTH", size_class="MEDIUM", base_service_minutes=60):
    name = name or f"Breed-{_u()}"
    return get_success_data(api_client.create_breed({
        "name": name, "coat_type": coat_type, "size_class": size_class,
        "base_service_minutes": base_service_minutes,
    }, ADMIN))


def create_service_tier(code="FULL_GROOM", base_price_cents=6000, duration_multiplier=1.00):
    return get_success_data(api_client.create_service_tier({
        "code": code, "base_price_cents": base_price_cents,
        "duration_multiplier": duration_multiplier,
    }, ADMIN))


def create_add_on(code="DESHED", price_cents=2000, duration_minutes=30, requires_calm=None):
    payload = {"code": code, "price_cents": price_cents, "duration_minutes": duration_minutes}
    if requires_calm is not None:
        payload["requires_calm"] = requires_calm
    return get_success_data(api_client.create_add_on(payload, ADMIN))


def create_van(label=None, max_stops=5, has_show_equipment=None):
    label = label or f"Van-{_u()}"
    payload = {"label": label, "max_stops": max_stops}
    if has_show_equipment is not None:
        payload["has_show_equipment"] = has_show_equipment
    return get_success_data(api_client.create_van(payload, ADMIN))


def create_groomer(email=None, skill_level="SENIOR", handles_aggressive=True,
                   status="AVAILABLE", full_name="Groomer"):
    email = email or f"groomer{_u()}@example.com"
    return get_success_data(api_client.create_groomer({
        "email": email, "full_name": full_name, "skill_level": skill_level,
        "handles_aggressive": handles_aggressive, "status": status,
    }, ADMIN))


def create_customer(service_zip="90001", email=None, full_name="Owner"):
    email = email or f"owner{_u()}@example.com"
    return get_success_data(api_client.create_customer({
        "email": email, "full_name": full_name, "service_zip": service_zip,
    }, ADMIN))


def create_pet(customer_id, breed_id, name="Pet", weight_lbs=30,
               coat_condition=None, behavioral_flag=None):
    payload = {"customer_id": customer_id, "breed_id": breed_id,
               "name": name, "weight_lbs": weight_lbs}
    if coat_condition is not None:
        payload["coat_condition"] = coat_condition
    if behavioral_flag is not None:
        payload["behavioral_flag"] = behavioral_flag
    return get_success_data(api_client.create_pet(payload, make_customer_headers(customer_id)))


def upload_rabies(pet_id, customer_id, issued_on="2026-01-01T00:00:00Z",
                  expires_on="2027-01-01T00:00:00Z"):
    return get_success_data(api_client.create_vaccination(pet_id, {
        "vaccine_type": "RABIES", "issued_on": issued_on, "expires_on": expires_on,
    }, make_customer_headers(customer_id)))


def create_route_day(van_id, coverage_zip="90001",
                     service_date="2026-06-10T00:00:00Z",
                     window_start="2026-06-10T09:00:00Z",
                     window_end="2026-06-10T17:00:00Z"):
    return get_success_data(api_client.create_route_day({
        "van_id": van_id, "service_date": service_date,
        "window_start": window_start, "window_end": window_end,
        "coverage_zip": coverage_zip,
    }, DISPATCH))


# --------------------------------------------------------------------------
# Tier 2: a fully provisioned single-customer world
# --------------------------------------------------------------------------
def setup_world(zip_code="90001", tier_code="FULL_GROOM", base_price_cents=6000,
                duration_multiplier=1.00, base_service_minutes=60,
                weight_lbs=30, coat_condition=None, behavioral_flag=None,
                van_max_stops=5, has_show_equipment=None,
                window_start="2026-06-10T09:00:00Z",
                window_end="2026-06-10T17:00:00Z",
                service_date="2026-06-10T00:00:00Z",
                with_groomer=True, with_vaccination=True,
                handles_aggressive=True, skill_level="SENIOR"):
    """Build a complete bookable world: tier, breed, (groomer,) van, route day,
    customer, pet, (RABIES vaccination). Returns a dict of all entities and the
    route day's initial version under key 'rd_version'.
    """
    tier = create_service_tier(code=tier_code, base_price_cents=base_price_cents,
                               duration_multiplier=duration_multiplier)
    breed = create_breed(base_service_minutes=base_service_minutes)
    groomer = create_groomer(handles_aggressive=handles_aggressive,
                             skill_level=skill_level) if with_groomer else None
    van = create_van(max_stops=van_max_stops, has_show_equipment=has_show_equipment)
    route_day = create_route_day(van["id"], coverage_zip=zip_code,
                                 service_date=service_date,
                                 window_start=window_start, window_end=window_end)
    customer = create_customer(service_zip=zip_code)
    pet = create_pet(customer["id"], breed["id"], weight_lbs=weight_lbs,
                     coat_condition=coat_condition, behavioral_flag=behavioral_flag)
    if with_vaccination:
        upload_rabies(pet["id"], customer["id"])
    return {
        "tier": tier, "breed": breed, "groomer": groomer, "van": van,
        "route_day": route_day, "rd_version": route_day["version"],
        "customer": customer, "pet": pet,
    }


# --------------------------------------------------------------------------
# Tier 3: appointment lifecycle shortcuts
# --------------------------------------------------------------------------
def create_appointment(pet_id, tier_id, customer_id, recurring_plan_id=None):
    payload = {"pet_id": pet_id, "service_tier_id": tier_id}
    if recurring_plan_id is not None:
        payload["recurring_plan_id"] = recurring_plan_id
    return get_success_data(api_client.create_appointment(payload, make_customer_headers(customer_id)))


def attach_add_on(appointment_id, add_on_id, customer_id):
    return get_success_data(api_client.attach_add_on(
        appointment_id, {"add_on_id": add_on_id}, make_customer_headers(customer_id)))


def quote(appointment_id):
    return get_success_data(api_client.quote_appointment(appointment_id, DISPATCH))


def current_route_version(route_day_id):
    rd = get_success_data(api_client.get_route_day(route_day_id, DISPATCH))
    return rd["version"]


def schedule(appointment_id, route_day_id, slot_start, expected_version=None):
    """Schedule an appointment. If expected_version is None, the current
    RouteDay.version is fetched first so the OCC check passes."""
    if expected_version is None:
        expected_version = current_route_version(route_day_id)
    return get_success_data(api_client.schedule_appointment(appointment_id, {
        "route_day_id": route_day_id, "slot_start": slot_start,
        "expected_route_day_version": expected_version,
    }, DISPATCH))


def create_quoted_appointment(world, add_on_ids=None):
    """Create -> (attach add-ons) -> quote. Returns the QUOTED appointment dict."""
    appt = create_appointment(world["pet"]["id"], world["tier"]["id"], world["customer"]["id"])
    for aid in (add_on_ids or []):
        attach_add_on(appt["id"], aid, world["customer"]["id"])
    return quote(appt["id"])


def create_scheduled_appointment(world, slot_start, add_on_ids=None):
    """Create -> (attach) -> quote -> schedule. Returns the SCHEDULED appointment dict."""
    appt = create_quoted_appointment(world, add_on_ids=add_on_ids)
    return schedule(appt["id"], world["route_day"]["id"], slot_start)


def complete(appointment_id, groomer_id, skipped_add_on_ids=None):
    payload = {}
    if skipped_add_on_ids is not None:
        payload["skipped_add_on_ids"] = skipped_add_on_ids
    return get_success_data(api_client.complete_appointment(
        appointment_id, payload, make_groomer_headers(groomer_id)))


def no_show(appointment_id):
    """Record a no-show on a SCHEDULED appointment.

    PRD §3.5: a no-show "may only be recorded once the current clock has reached
    the reserved stop's slot_start (the clock is at or after slot_start)". Tests
    place reserved slots at chronological points across the service window; this
    helper advances the server's logical clock to the reserved slot_start when the
    clock is still behind it, so the precondition holds. Advancing within the same
    service day never ages a strike out of the trailing-90-day window, so strike
    and fee assertions are unaffected. The clock is only moved forward, never back.
    """
    appt = get_success_data(api_client.get_appointment(appointment_id, DISPATCH))
    stop_id = appt.get("route_stop_id")
    if stop_id is not None:
        stop = get_success_data(api_client.get_route_stop(stop_id, DISPATCH))
        slot_start = stop["slot_start"]
        # Advance the logical clock to slot_start only when it is still behind, so
        # the clock moves forward only (never back), preserving every test's own
        # explicitly set clock when that clock is already at/after the slot.
        if _server_clock_before(slot_start):
            set_clock(slot_start)
    return get_success_data(api_client.no_show_appointment(appointment_id, DISPATCH))


def cancel(appointment_id, customer_id):
    return get_success_data(api_client.cancel_appointment(
        appointment_id, make_customer_headers(customer_id)))


# --------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting (strikes)
# --------------------------------------------------------------------------
def accrue_no_show_strikes(world, count, first_slot="2026-06-10T09:00:00Z"):
    """Drive `count` SCHEDULED->NO_SHOW cycles on the same customer/pet so the
    customer accumulates `count` no_show_strikes. Slots are spaced 2h apart and
    all start at or before the current clock so the no-show precondition holds.
    Returns the list of no-showed appointment dicts.

    Requires the world clock to already be at or after `first_slot` + spacing,
    and the route window to span all the slots.
    """
    appts = []
    base_hour = int(first_slot[11:13])
    for i in range(count):
        slot = f"{first_slot[:11]}{base_hour + i * 2:02d}{first_slot[13:]}"
        appt = create_scheduled_appointment(world, slot)
        no_show(appt["id"])
        appts.append(get_success_data(api_client.get_appointment(appt["id"], DISPATCH)))
    return appts


# --------------------------------------------------------------------------
# Tier 5: recurring plans
# --------------------------------------------------------------------------
def create_recurring_plan(pet_id, tier_id, customer_id, cadence_days=28, discount_pct=0.05):
    return get_success_data(api_client.create_recurring_plan({
        "pet_id": pet_id, "service_tier_id": tier_id,
        "cadence_days": cadence_days, "discount_pct": discount_pct,
    }, make_customer_headers(customer_id)))


def generate_plan_appointment(plan_id):
    return get_success_data(api_client.generate_appointment(plan_id, DISPATCH))


# --------------------------------------------------------------------------
# Tier 5: fee charges
# --------------------------------------------------------------------------
def get_customer(customer_id, headers=None):
    return get_success_data(api_client.get_customer(customer_id, headers or DISPATCH))


def list_customer_fee_charges(customer_id, customer_headers=None):
    resp = api_client.list_customer_fee_charges(
        customer_id, customer_headers or make_customer_headers(customer_id))
    return get_success_data(resp)


def first_fee_for_customer(customer_id):
    fees = list_customer_fee_charges(customer_id)
    assert fees, f"expected at least one fee charge for customer {customer_id}"
    return fees[0]


def fees_for_appointment(appointment_id):
    resp = api_client.list_fee_charges(DISPATCH, params={"appointment_id": appointment_id})
    return get_success_data(resp)
