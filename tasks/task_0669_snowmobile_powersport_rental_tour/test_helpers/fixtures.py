"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for setup steps so that a broken
precondition surfaces as a clear "Setup failed" error rather than a confusing
downstream assertion failure.

The server is restarted (empty DB, clock reset to 2026-04-01T00:00:00Z) before
every test, so every helper builds all of its own state from scratch.

Identity threading: a Member/Guide is entity_backed, so ownership-gated calls
(confirm/cancel a reservation, depart/complete a departure) MUST use
make_member_headers(member["id"]) / make_guide_headers(guide["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    member_payload, guide_payload, trail_payload, unit_payload,
    gear_payload, departure_payload, reservation_payload, unique_email, unique_vin,
)
from .test_users import TEST_USERS, make_member_headers, make_guide_headers

DISPATCH = TEST_USERS["dispatch_headers"]
ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Primitive creators ────────────────────────────────────────────────

def create_trail(**overrides) -> dict:
    return get_success_data(api_client.create_trail(trail_payload(**overrides), DISPATCH))


def create_unit(**overrides) -> dict:
    if "vin_tag" not in overrides:
        overrides["vin_tag"] = unique_vin()
    return get_success_data(api_client.create_unit(unit_payload(**overrides), DISPATCH))


def create_guide(**overrides) -> dict:
    return get_success_data(api_client.create_guide(guide_payload(**overrides), DISPATCH))


def create_gear(**overrides) -> dict:
    return get_success_data(api_client.create_gear_item(gear_payload(**overrides), DISPATCH))


def create_departure(trail_id, **overrides) -> dict:
    return get_success_data(api_client.create_departure(departure_payload(trail_id, **overrides), DISPATCH))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def register_member(**overrides) -> dict:
    if "email" not in overrides:
        overrides["email"] = unique_email()
    return get_success_data(api_client.register_member(member_payload(**overrides), ANON))


def register_signed_member(**overrides) -> dict:
    """Register a member and sign their waiver (adult by default).
    Pass guardian_ack=True to sign for an under-18 member."""
    guardian_ack = overrides.pop("guardian_ack", None)
    mem = register_member(**overrides)
    sign_body = {"guardian_ack": True} if guardian_ack else {}
    get_success_data(api_client.sign_waiver(mem["id"], sign_body, make_member_headers(mem["id"])))
    return get_success_data(api_client.get_member(mem["id"], make_member_headers(mem["id"])))


def train_member(member_id, level):
    return get_success_data(api_client.complete_training(member_id, {"level": level}, DISPATCH))


# ─── Reservation builders ──────────────────────────────────────────────

def create_reservation(member, departure_id, unit_id, helmet_id=None, suit_id=None) -> dict:
    extra = {}
    if helmet_id is not None:
        extra["helmet_gear_id"] = helmet_id
    if suit_id is not None:
        extra["suit_gear_id"] = suit_id
    return get_success_data(api_client.create_reservation(
        reservation_payload(member["id"], departure_id, unit_id, **extra),
        make_member_headers(member["id"])))


def confirm_reservation(reservation_id, member_id, expected_version) -> dict:
    return get_success_data(api_client.confirm_reservation(
        reservation_id, {"expected_tour_departure_version": expected_version},
        make_member_headers(member_id)))


def current_departure_version(departure_id) -> int:
    dep = get_success_data(api_client.get_departure(departure_id, DISPATCH))
    return dep["version"]


def create_and_confirm_reservation(member, departure_id, unit_id, helmet_id=None, suit_id=None,
                                   expected_version=None) -> dict:
    """Create a PENDING reservation then confirm it. If expected_version is None,
    reads the departure's live version first (handles multi-rider departures where
    earlier confirms have already advanced the version)."""
    res = create_reservation(member, departure_id, unit_id, helmet_id, suit_id)
    if expected_version is None:
        expected_version = current_departure_version(departure_id)
    return confirm_reservation(res["id"], member["id"], expected_version)


# ─── Lifecycle shortcuts ───────────────────────────────────────────────

def assign_guide(departure_id, guide_id):
    return get_success_data(api_client.assign_guide(departure_id, {"guide_id": guide_id}, DISPATCH))


def lock_departure(departure_id):
    return get_success_data(api_client.lock_departure(departure_id, DISPATCH))


def depart_departure(departure_id, guide_id):
    return get_success_data(api_client.depart_departure(departure_id, make_guide_headers(guide_id)))


def setup_confirmed_reservation(trail_overrides=None, unit_overrides=None,
                                departure_overrides=None, member_overrides=None,
                                with_helmet=False, with_suit=False):
    """
    Build a fully CONFIRMED reservation (deposit HELD) on a SCHEDULED departure.

    Returns a dict bundle: trail, unit, guide-less, departure, member, helmet, suit,
    reservation. The reservation has been confirmed against the departure's fresh
    version. Caller can read entities back for assertions.
    """
    trail = create_trail(**(trail_overrides or {}))
    unit = create_unit(**(unit_overrides or {}))
    dep = create_departure(trail["id"], **(departure_overrides or {}))
    member = register_signed_member(**(member_overrides or {}))

    helmet = create_gear(kind="HELMET", size_code="M", replacement_cost_cents=12000) if with_helmet else None
    suit = create_gear(kind="SUIT", size_code="L", replacement_cost_cents=20000) if with_suit else None

    res = create_and_confirm_reservation(
        member, dep["id"], unit["id"],
        helmet_id=helmet["id"] if helmet else None,
        suit_id=suit["id"] if suit else None,
        expected_version=dep["version"])
    return {
        "trail": trail, "unit": unit, "departure": dep, "member": member,
        "helmet": helmet, "suit": suit, "reservation": res,
    }


def setup_checked_out_reservation(trail_overrides=None, unit_overrides=None,
                                  departure_overrides=None, member_overrides=None,
                                  guide_overrides=None, with_helmet=False, with_suit=False,
                                  depart_clock=None):
    """
    Build a reservation walked all the way to CHECKED_OUT:
    confirm -> assign guide -> lock -> set clock to start -> depart (cascade check-out).

    departure_overrides should set starts_at/ends_at; depart_clock should be at or
    after starts_at. Returns the same bundle as setup_confirmed_reservation plus 'guide'.
    """
    departure_overrides = dict(departure_overrides or {})
    guide_overrides = dict(guide_overrides or {})
    # Guide class must satisfy departure's required_guide_class.
    if "max_class" not in guide_overrides:
        guide_overrides["max_class"] = departure_overrides.get("required_guide_class", "TRAIL")

    bundle = setup_confirmed_reservation(
        trail_overrides=trail_overrides, unit_overrides=unit_overrides,
        departure_overrides=departure_overrides, member_overrides=member_overrides,
        with_helmet=with_helmet, with_suit=with_suit)

    guide = create_guide(**guide_overrides)
    assign_guide(bundle["departure"]["id"], guide["id"])
    lock_departure(bundle["departure"]["id"])
    if depart_clock:
        set_clock(depart_clock)
    depart_departure(bundle["departure"]["id"], guide["id"])

    bundle["guide"] = guide
    return bundle


def return_reservation(reservation_id, fuel_return_fraction, damage_assessed_cents=None,
                       lost_gear_ids=None) -> dict:
    body = {"fuel_return_fraction": fuel_return_fraction}
    if damage_assessed_cents is not None:
        body["damage_assessed_cents"] = damage_assessed_cents
    if lost_gear_ids is not None:
        body["lost_gear_ids"] = lost_gear_ids
    return get_success_data(api_client.return_reservation(reservation_id, body, DISPATCH))


# ─── Read-back helpers (use real role headers for ownership) ────────────

def read_member(member_id) -> dict:
    return get_success_data(api_client.get_member(member_id, DISPATCH))


def read_unit(unit_id) -> dict:
    return get_success_data(api_client.get_unit(unit_id, DISPATCH))


def read_gear(gear_id) -> dict:
    return get_success_data(api_client.get_gear_item(gear_id, DISPATCH))


def read_departure(departure_id) -> dict:
    return get_success_data(api_client.get_departure(departure_id, DISPATCH))


def read_reservation(reservation_id) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, DISPATCH))


def read_guide(guide_id) -> dict:
    return get_success_data(api_client.get_guide(guide_id, DISPATCH))
