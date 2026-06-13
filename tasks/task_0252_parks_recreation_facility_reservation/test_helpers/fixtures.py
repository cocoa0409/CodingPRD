"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup step failed" errors rather than confusing downstream assertions.

Identity threading: a Patron is entity_backed, so every ownership-gated call uses
make_patron_headers(patron["id"]) — never the shared TEST_USERS["patron_headers"]
constant — so the server's X-User-ID == Permit.patron_id ownership check passes.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_facility_payload,
    create_patron_payload,
    create_insurance_certificate_payload,
    create_permit_payload,
    create_payment_payload,
    create_league_payload,
    create_lottery_round_payload,
    create_lottery_entry_payload,
)
from .test_users import TEST_USERS, make_patron_headers

COORD = TEST_USERS["rec_coordinator_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


# ─── Primitives ───────────────────────────────────────────────────────────────

def set_clock(iso: str):
    """Set the server logical clock. Returns the response data."""
    return get_success_data(api_client.set_clock(iso, COORD))


def create_facility(**overrides):
    """Create a facility. Returns the facility dict (includes version)."""
    return get_success_data(api_client.create_facility(create_facility_payload(**overrides), COORD))


def create_patron(verified=False, **overrides):
    """Create a patron. If verified=True, also accept residency proof.
    Returns the (possibly re-fetched, verified) patron dict."""
    patron = get_success_data(api_client.create_patron(create_patron_payload(**overrides), COORD))
    if verified:
        patron = get_success_data(api_client.verify_residency(patron["id"], COORD))
    return patron


def create_coi(patron_id, **overrides):
    """Upload a COI for a patron (acting as that patron). Returns the COI dict."""
    return get_success_data(api_client.create_insurance_certificate(
        create_insurance_certificate_payload(patron_id, **overrides),
        make_patron_headers(patron_id),
    ))


def apply_permit(facility_id, patron_id, start_at, end_at, **overrides):
    """Apply for a permit on behalf of the patron (ownership-threaded).
    Returns the APPLIED permit dict."""
    return get_success_data(api_client.apply_permit(
        facility_id,
        create_permit_payload(patron_id, start_at, end_at, **overrides),
        make_patron_headers(patron_id),
    ))


def capture_payment(permit_id, fee_component_cents, deposit_component_cents):
    """Capture a payment (FinanceClerk). Returns the CAPTURED payment dict."""
    return get_success_data(api_client.create_payment(
        permit_id,
        create_payment_payload(fee_component_cents, deposit_component_cents),
        FINANCE,
    ))


def facility_version(facility_id):
    """Read the facility's current version (for OCC threading)."""
    return get_success_data(api_client.get_facility(facility_id, COORD))["version"]


def grant_permit(facility_id, permit_id, expected_facility_version, on_conflict=None):
    """Grant a permit with the supplied expected_facility_version.
    Returns the grant response data (the permit)."""
    payload = {"expected_facility_version": expected_facility_version}
    if on_conflict is not None:
        payload["on_conflict"] = on_conflict
    return get_success_data(api_client.grant_permit(facility_id, permit_id, payload, COORD))


# ─── Tier 3: Full lifecycle shortcuts ─────────────────────────────────────────

def setup_granted_permit(
    *,
    clock="2026-07-01T00:00:00Z",
    facility_overrides=None,
    patron_verified=False,
    patron_overrides=None,
    start_at="2026-08-01T17:00:00Z",
    end_at="2026-08-01T20:00:00Z",
    fee_component_cents=24000,
    deposit_component_cents=0,
    coi_overrides=None,
):
    """Drive a single permit all the way to GRANTED.

    Sequence: set clock -> create facility -> create patron (optionally verified)
    -> [optional COI] -> apply permit -> capture payment -> grant.

    Returns dict with keys: facility, patron, permit (granted), coi (or None),
    facility_version_after (post-grant version).
    """
    set_clock(clock)
    facility = create_facility(**(facility_overrides or {}))
    patron = create_patron(verified=patron_verified, **(patron_overrides or {}))

    coi = None
    apply_kwargs = {}
    if coi_overrides is not None:
        coi = create_coi(patron["id"], **coi_overrides)
        apply_kwargs["coi_id"] = coi["id"]

    permit = apply_permit(facility["id"], patron["id"], start_at, end_at, **apply_kwargs)
    capture_payment(permit["id"], fee_component_cents, deposit_component_cents)
    v = facility_version(facility["id"])
    granted = grant_permit(facility["id"], permit["id"], v)
    v_after = facility_version(facility["id"])

    return {
        "facility": facility,
        "patron": patron,
        "permit": granted,
        "coi": coi,
        "facility_version_after": v_after,
    }


def setup_applied_permit(
    *,
    clock="2026-07-01T00:00:00Z",
    facility_overrides=None,
    patron_verified=False,
    patron_overrides=None,
    start_at="2026-08-01T17:00:00Z",
    end_at="2026-08-01T20:00:00Z",
    capture=True,
    fee_component_cents=20000,
    deposit_component_cents=0,
    coi_overrides=None,
):
    """Drive a single permit to APPLIED, optionally capturing a payment but NOT
    granting. Used by grant-failure tests.

    Returns dict: facility, patron, permit (APPLIED), coi (or None),
    facility_version (current).
    """
    set_clock(clock)
    facility = create_facility(**(facility_overrides or {}))
    patron = create_patron(verified=patron_verified, **(patron_overrides or {}))

    coi = None
    apply_kwargs = {}
    if coi_overrides is not None:
        coi = create_coi(patron["id"], **coi_overrides)
        apply_kwargs["coi_id"] = coi["id"]

    permit = apply_permit(facility["id"], patron["id"], start_at, end_at, **apply_kwargs)
    if capture:
        capture_payment(permit["id"], fee_component_cents, deposit_component_cents)
    return {
        "facility": facility,
        "patron": patron,
        "permit": permit,
        "coi": coi,
        "facility_version": facility_version(facility["id"]),
    }


def cancel_permit(facility_id, permit_id, patron_headers, refund_destination="ORIGINAL"):
    """Cancel a permit. Returns the cancel response data (the permit)."""
    payload = {"refund_destination": refund_destination}
    return get_success_data(api_client.cancel_permit(facility_id, permit_id, payload, patron_headers))


def get_first_refund(permit_id):
    """Read the (single) refund created for a permit. Returns the refund dict or None."""
    data = get_success_data(api_client.list_permit_refunds(permit_id, FINANCE))
    return data[0] if data else None


# ─── Tier 2/5: League setup ───────────────────────────────────────────────────

def setup_league_with_children(
    *,
    clock="2026-07-01T00:00:00Z",
    facility_overrides=None,
    patron_overrides=None,
    occurrences=2,
    weekday=1,
    start_hour=10,
    duration_minutes=120,
    first_date="2026-08-04T00:00:00Z",
):
    """Create a league series and read back its child permits.

    Returns dict: facility, patron, league, children (list of permit dicts in
    creation order).
    """
    set_clock(clock)
    facility = create_facility(**(facility_overrides or {}))
    patron = create_patron(**(patron_overrides or {}))
    league = get_success_data(api_client.create_league(
        create_league_payload(
            facility["id"], patron["id"],
            occurrences=occurrences, weekday=weekday, start_hour=start_hour,
            duration_minutes=duration_minutes, first_date=first_date,
        ),
        make_patron_headers(patron["id"]),
    ))
    children = get_success_data(api_client.list_league_permits(league["id"], COORD))
    return {
        "facility": facility,
        "patron": patron,
        "league": league,
        "children": children,
    }


# ─── Lottery setup ────────────────────────────────────────────────────────────

def create_lottery_round(facility_id, **overrides):
    """Open a lottery round. Returns the round dict."""
    return get_success_data(api_client.create_lottery_round(
        create_lottery_round_payload(facility_id, **overrides), COORD))


def enter_lottery(round_id, patron_id):
    """Enter a patron into a lottery round (ownership-threaded). Returns entry dict."""
    return get_success_data(api_client.create_lottery_entry(
        round_id, create_lottery_entry_payload(patron_id), make_patron_headers(patron_id)))


def setup_lottery_round_with_entries(
    *,
    clock="2026-07-02T00:00:00Z",
    closes_at="2026-07-15T00:00:00Z",
    facility_overrides=None,
    slot_start_at="2026-08-03T18:00:00Z",
    slot_end_at="2026-08-03T20:00:00Z",
    entrants=None,
):
    """Open a round and enter the supplied patrons in order.

    `entrants` is a list of dicts: {"verified": bool, "residency": str}.
    Returns dict: facility, round, entries (list, in entry order), patrons (list),
    facility_version (current).
    """
    set_clock(clock)
    facility = create_facility(**(facility_overrides or {}))
    rnd = create_lottery_round(
        facility["id"], closes_at=closes_at,
        slot_start_at=slot_start_at, slot_end_at=slot_end_at,
    )
    patrons = []
    entries = []
    for spec in (entrants or []):
        p = create_patron(
            verified=spec.get("verified", False),
            residency=spec.get("residency", "NON_RESIDENT"),
        )
        patrons.append(p)
        entries.append(enter_lottery(rnd["id"], p["id"]))
    return {
        "facility": facility,
        "round": rnd,
        "entries": entries,
        "patrons": patrons,
        "facility_version": facility_version(facility["id"]),
    }
