"""Composite setup helpers (PRD Section 3 workflows).

The test harness restarts the API server and empties the database before every
individual test, so each helper builds its preconditions from scratch using only
PRD-declared endpoints. Setup calls use the lenient get_success_data() validator
so a broken precondition surfaces as a clear "Setup failed" rather than a
confusing assertion later.

Identity threading: whenever a Couple/Officiant acts on a resource they own, the
call uses make_couple_headers(couple_id) / make_officiant_headers(officiant_id)
with the real entity id (PRD Section 2.1 ownership).
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .constants import CLOCK_DEFAULT_UTC
from .factories import (
    create_officiant_payload,
    create_couple_payload,
    create_package_payload,
    create_venue_payload,
    create_booking_payload,
    create_date_hold_payload,
    create_ceremony_script_payload,
    create_rehearsal_payload,
    create_marriage_license_payload,
    create_review_payload,
)
from .test_users import (
    make_coordinator_headers,
    make_couple_headers,
    make_officiant_headers,
)

COORDINATOR = make_coordinator_headers()


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Set the logical clock (PRD Section 2.5). Coordinator-only."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, COORDINATOR))


def run_expiry(api):
    """Run the scheduled expiry sweep (PRD Section 2.5). Coordinator-only."""
    return get_success_data(api.run_expiry(COORDINATOR))


# ---------------------------------------------------------------------------
# Roster & reference data (PRD Section 3.1)
# ---------------------------------------------------------------------------
def create_officiant(api, **overrides) -> dict:
    return get_success_data(api.create_officiant(create_officiant_payload(**overrides), COORDINATOR))


def transition_officiant(api, officiant_id, to_state) -> dict:
    return get_success_data(
        api.transition_officiant(officiant_id, {"to_state": to_state}, COORDINATOR)
    )


def create_active_officiant(api, **overrides) -> dict:
    """Create an officiant and approve it PENDING_REVIEW -> ACTIVE."""
    off = create_officiant(api, **overrides)
    return transition_officiant(api, off["id"], "ACTIVE")


def suspend_officiant(api, officiant_id) -> dict:
    return transition_officiant(api, officiant_id, "SUSPENDED")


def get_officiant(api, officiant_id) -> dict:
    return get_success_data(api.get_officiant(officiant_id, COORDINATOR))


def current_officiant_version(api, officiant_id) -> int:
    return get_officiant(api, officiant_id)["version"]


def create_couple(api, **overrides) -> dict:
    return get_success_data(api.create_couple(create_couple_payload(**overrides), COORDINATOR))


def create_package(api, **overrides) -> dict:
    return get_success_data(api.create_package(create_package_payload(**overrides), COORDINATOR))


def create_venue(api, jurisdiction=None, **overrides) -> dict:
    if jurisdiction is not None:
        overrides["jurisdiction"] = jurisdiction
    return get_success_data(api.create_venue(create_venue_payload(**overrides), COORDINATOR))


def setup_reference(api, *, officiant_overrides=None, package_overrides=None,
                    venue_jurisdiction="CA", clock=CLOCK_DEFAULT_UTC) -> SimpleNamespace:
    """Active officiant + couple + package + venue, with the clock initialized.

    Returns a namespace: .officiant .couple .package .venue
    (the officiant's current version is officiant["version"]).
    """
    set_clock(api, clock)
    officiant = create_active_officiant(api, **(officiant_overrides or {}))
    couple = create_couple(api)
    package = create_package(api, **(package_overrides or {}))
    venue = create_venue(api, jurisdiction=venue_jurisdiction)
    return SimpleNamespace(officiant=officiant, couple=couple, package=package, venue=venue)


# ---------------------------------------------------------------------------
# Bookings, holds, confirmation (PRD Sections 3.2, 3.3, 3.8)
# ---------------------------------------------------------------------------
def create_booking(api, officiant, couple, package, venue, *, as_coordinator=False, **overrides) -> dict:
    headers = COORDINATOR if as_coordinator else make_couple_headers(couple["id"])
    payload = create_booking_payload(officiant["id"], couple["id"], package["id"], venue["id"], **overrides)
    return get_success_data(api.create_booking(payload, headers))


def place_hold(api, booking, couple, officiant_version, **overrides) -> dict:
    payload = create_date_hold_payload(booking["id"], officiant_version, **overrides)
    return get_success_data(api.create_date_hold(payload, make_couple_headers(couple["id"])))


def confirm_booking(api, booking, couple, deposit_amount_cents=None) -> dict:
    amount = deposit_amount_cents if deposit_amount_cents is not None else booking["deposit_due_cents"]
    return get_success_data(
        api.confirm_booking(booking["id"], {"deposit_amount_cents": amount}, make_couple_headers(couple["id"]))
    )


def cancel_booking(api, booking, couple=None, *, as_coordinator=False, cancel_reason="COUPLE_REQUEST") -> dict:
    headers = COORDINATOR if as_coordinator else make_couple_headers(couple["id"])
    return get_success_data(
        api.cancel_booking(booking["id"], {"cancel_reason": cancel_reason}, headers)
    )


def complete_booking(api, booking, officiant, *, clock_to=None) -> dict:
    if clock_to is not None:
        set_clock(api, clock_to)
    return get_success_data(
        api.complete_booking(booking["id"], make_officiant_headers(officiant["id"]))
    )


def setup_held_booking(api, *, booking_overrides=None, officiant_overrides=None,
                       package_overrides=None, venue_jurisdiction="CA",
                       clock=CLOCK_DEFAULT_UTC) -> SimpleNamespace:
    """Active officiant + couple + package + venue + a booking advanced to HOLD.

    Returns namespace: .officiant .couple .package .venue .booking .hold
    """
    ref = setup_reference(
        api, officiant_overrides=officiant_overrides, package_overrides=package_overrides,
        venue_jurisdiction=venue_jurisdiction, clock=clock,
    )
    booking = create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue,
                             **(booking_overrides or {}))
    hold = place_hold(api, booking, ref.couple, ref.officiant["version"])
    return SimpleNamespace(**vars(ref), booking=booking, hold=hold)


def setup_confirmed_booking(api, *, deposit_amount_cents=None, booking_overrides=None,
                            officiant_overrides=None, package_overrides=None,
                            venue_jurisdiction="CA", clock=CLOCK_DEFAULT_UTC) -> SimpleNamespace:
    """A booking driven all the way to CONFIRMED (deposit captured)."""
    ctx = setup_held_booking(
        api, booking_overrides=booking_overrides, officiant_overrides=officiant_overrides,
        package_overrides=package_overrides, venue_jurisdiction=venue_jurisdiction, clock=clock,
    )
    confirmed = confirm_booking(api, ctx.booking, ctx.couple, deposit_amount_cents)
    ctx.booking = confirmed
    return ctx


def setup_completed_booking(api, *, complete_clock="2026-09-02T00:00:00Z",
                            booking_overrides=None, **kwargs) -> SimpleNamespace:
    """A booking driven to COMPLETED (clock advanced past ceremony_start)."""
    ctx = setup_confirmed_booking(api, booking_overrides=booking_overrides, **kwargs)
    completed = complete_booking(api, ctx.booking, ctx.officiant, clock_to=complete_clock)
    ctx.booking = completed
    return ctx


def setup_backup_pending_booking(api, **kwargs) -> SimpleNamespace:
    """A CONFIRMED booking whose officiant is then suspended, so the suspension
    cascade moves the booking to BACKUP_PENDING (PRD Section 2.8)."""
    ctx = setup_confirmed_booking(api, **kwargs)
    suspend_officiant(api, ctx.officiant["id"])
    ctx.booking = get_success_data(api.get_booking(ctx.booking["id"], COORDINATOR))
    return ctx


# ---------------------------------------------------------------------------
# Ceremony scripts (PRD Section 3.4)
# ---------------------------------------------------------------------------
def create_script(api, booking, couple, **overrides) -> dict:
    payload = create_ceremony_script_payload(booking["id"], **overrides)
    return get_success_data(api.create_ceremony_script(payload, make_couple_headers(couple["id"])))


def submit_script(api, script, couple) -> dict:
    return get_success_data(api.submit_ceremony_script(script["id"], make_couple_headers(couple["id"])))


def patch_script(api, script, couple, **fields) -> dict:
    return get_success_data(api.patch_ceremony_script(script["id"], fields, make_couple_headers(couple["id"])))


def decide_script(api, script, officiant, decision, notes=None) -> dict:
    payload = {"decision": decision}
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api.decide_ceremony_script(script["id"], payload, make_officiant_headers(officiant["id"])))


def create_approved_script(api, booking, couple, officiant, **overrides) -> dict:
    """Create a script and drive it DRAFT -> SUBMITTED -> APPROVED."""
    script = create_script(api, booking, couple, **overrides)
    submit_script(api, script, couple)
    return decide_script(api, script, officiant, "APPROVE")


# ---------------------------------------------------------------------------
# Rehearsals (PRD Section 3.5)
# ---------------------------------------------------------------------------
def create_rehearsal(api, booking, couple, venue, **overrides) -> dict:
    payload = create_rehearsal_payload(booking["id"], venue["id"], **overrides)
    return get_success_data(api.create_rehearsal(payload, make_couple_headers(couple["id"])))


def transition_rehearsal(api, rehearsal, actor_headers, to_state) -> dict:
    return get_success_data(api.transition_rehearsal(rehearsal["id"], {"to_state": to_state}, actor_headers))


def confirm_rehearsal(api, rehearsal, officiant) -> dict:
    return transition_rehearsal(api, rehearsal, make_officiant_headers(officiant["id"]), "CONFIRMED")


# ---------------------------------------------------------------------------
# Marriage licenses (PRD Section 3.6)
# ---------------------------------------------------------------------------
def create_license(api, booking, couple, **overrides) -> dict:
    payload = create_marriage_license_payload(booking["id"], **overrides)
    return get_success_data(api.create_marriage_license(payload, make_couple_headers(couple["id"])))


def file_license(api, lic, couple) -> dict:
    return get_success_data(
        api.transition_marriage_license(lic["id"], {"to_state": "FILED"}, make_couple_headers(couple["id"]))
    )


def sign_license(api, lic, officiant) -> dict:
    return get_success_data(
        api.transition_marriage_license(lic["id"], {"to_state": "SIGNED"}, make_officiant_headers(officiant["id"]))
    )


# ---------------------------------------------------------------------------
# Reviews (PRD Section 3.9)
# ---------------------------------------------------------------------------
def create_review(api, booking, couple, **overrides) -> dict:
    payload = create_review_payload(booking["id"], **overrides)
    return get_success_data(api.create_review(payload, make_couple_headers(couple["id"])))


def moderate_review(api, review, decision) -> dict:
    return get_success_data(api.moderate_review(review["id"], {"decision": decision}, COORDINATOR))
