"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty database) before
every individual test. Setup calls use get_success_data() (lenient) so a setup
failure surfaces as a clear "Setup failed" error rather than a confusing
assertion mismatch downstream.

Host is entity-backed (PRD 2.1); ownership-gated Host calls thread the real
Host.id via make_host_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_host_headers,
    make_security_officer_headers,
)
from . import factories as f

SO = TEST_USERS["security_officer_headers"]
LA = TEST_USERS["lobby_attendant_headers"]


# --- Clock control -------------------------------------------------------

def set_clock(now_utc: str):
    """Pin the server clock (PRD 3.10). SecurityOfficer-only."""
    return get_success_data(api_client.set_clock({"now_utc": now_utc}, SO))


# --- Tier: base topology -------------------------------------------------

def create_site(badge_total=5, **overrides):
    payload = f.create_site_payload(badge_total=badge_total, **overrides)
    return get_success_data(api_client.create_site(payload, SO))


def create_floor(site_id, capacity=5, **overrides):
    payload = f.create_floor_payload(site_id, capacity=capacity, **overrides)
    return get_success_data(api_client.create_floor(payload, SO))


def create_host(site_id, **overrides):
    payload = f.create_host_payload(site_id, **overrides)
    return get_success_data(api_client.create_host(payload, SO))


def create_watchlist_entry(site_id, match_type, match_value_normalized, **overrides):
    payload = f.create_watchlist_entry_payload(
        site_id, match_type, match_value_normalized, **overrides
    )
    return get_success_data(api_client.create_watchlist_entry(payload, SO))


def create_meeting_room(floor_id, **overrides):
    payload = f.create_meeting_room_payload(floor_id, **overrides)
    return get_success_data(api_client.create_meeting_room(payload, SO))


def create_parking_space(site_id, **overrides):
    payload = f.create_parking_space_payload(site_id, **overrides)
    return get_success_data(api_client.create_parking_space(payload, SO))


def create_contractor_pass(host_id, **overrides):
    payload = f.create_contractor_pass_payload(host_id, **overrides)
    return get_success_data(api_client.create_contractor_pass(payload, SO))


def setup_site_floor_host(badge_total=5, capacity=5):
    """Active base topology: one Site, one Floor, one Host.
    Returns (site, floor, host)."""
    site = create_site(badge_total=badge_total)
    floor = create_floor(site["id"], capacity=capacity)
    host = create_host(site["id"])
    return site, floor, host


def setup_site_host(badge_total=5):
    """Site + Host only (delivery / contractor flows). Returns (site, host)."""
    site = create_site(badge_total=badge_total)
    host = create_host(site["id"])
    return site, host


# --- Tier: Visit state progression --------------------------------------

def create_visit(site_id, host_id, floor_id, **overrides):
    """Pre-register a visit (LobbyAttendant). Returns the PREREGISTERED visit."""
    payload = f.create_visit_payload(site_id, host_id, floor_id, **overrides)
    return get_success_data(api_client.create_visit(payload, LA))


def screen_visit(visit_id):
    """Run screening (LobbyAttendant); auto-advances per decision. Returns visit."""
    return get_success_data(api_client.screen_visit(visit_id, LA))


def create_cleared_visit(site_id, host_id, floor_id, **visit_overrides):
    """Pre-register a visit with no matching watchlist entries and screen it so it
    auto-advances to CLEARED. Returns the CLEARED visit. id_scanned defaults true."""
    visit = create_visit(site_id, host_id, floor_id, **visit_overrides)
    screened = screen_visit(visit["id"])
    return screened


def create_flagged_visit(site_id, host_id, floor_id, company="Acme Corp"):
    """Create a COMPANY REVIEW watchlist entry and a visit whose company matches,
    then screen so it auto-advances to FLAGGED. Returns the FLAGGED visit."""
    create_watchlist_entry(
        site_id, "COMPANY", company.lower().strip(), severity="REVIEW", active=True
    )
    visit = create_visit(
        site_id, host_id, floor_id,
        visitor_full_name="Rev Visitor", visitor_company=company, id_scanned=True,
    )
    return screen_visit(visit["id"])


def get_floor_version(floor_id):
    """Read a floor's current version (LobbyAttendant)."""
    return get_success_data(api_client.get_floor(floor_id, LA))["version"]


def sign_in_visit(visit_id, floor_id):
    """Sign a CLEARED visit in, threading the floor's current version into
    expected_floor_version. Returns the SIGNED_IN visit."""
    fv = get_floor_version(floor_id)
    return get_success_data(
        api_client.sign_in_visit(visit_id, {"expected_floor_version": fv}, LA)
    )


def setup_signed_in_visit(badge_total=5, capacity=5, now_utc="2026-06-16T09:00:00Z",
                          visit_overrides=None):
    """Full setup through SIGNED_IN: site, floor, host, one CLEARED visit signed in
    at now_utc. Returns (site, floor, host, visit)."""
    set_clock(now_utc)
    site, floor, host = setup_site_floor_host(badge_total=badge_total, capacity=capacity)
    visit = create_cleared_visit(site["id"], host["id"], floor["id"],
                                 **(visit_overrides or {}))
    signed_in = sign_in_visit(visit["id"], floor["id"])
    return site, floor, host, signed_in


# --- Tier: contractor-covered visit -------------------------------------

def setup_contractor_covered_cleared_visit(
    badge_total=5, capacity=5, now_utc="2026-06-16T09:00:00Z",
    pass_overrides=None, visit_overrides=None,
):
    """Site, Floor, Host, ACTIVE ContractorPass, and a contractor-covered CLEARED
    visit (id_scanned true, within pass window by default). Clock pinned.
    Returns (site, floor, host, pass_, visit)."""
    set_clock(now_utc)
    site, floor, host = setup_site_floor_host(badge_total=badge_total, capacity=capacity)
    pass_ = create_contractor_pass(host["id"], **(pass_overrides or {}))
    vo = {
        "contractor_pass_id": pass_["id"],
        "visitor_full_name": "Pat Builder",
        "visitor_company": "BuildCo",
    }
    vo.update(visit_overrides or {})
    visit = create_cleared_visit(site["id"], host["id"], floor["id"], **vo)
    return site, floor, host, pass_, visit


# --- Tier: agreement attachment -----------------------------------------

def create_agreement(visit_id, **overrides):
    """Attach a PENDING agreement to a visit (LobbyAttendant)."""
    payload = f.create_agreement_payload(visit_id, **overrides)
    return get_success_data(api_client.create_agreement(payload, LA))


# --- Tier: floor at capacity --------------------------------------------

def setup_floor_at_capacity_with_pending_second_visit(
    now_utc="2026-06-16T09:00:00Z", second_id_scanned=True, badge_total=5,
):
    """Capacity-1 floor fully occupied by one SIGNED_IN visit, plus a second CLEARED
    visit on that full floor (id_scanned configurable). Returns
    (site, floor, host, first_visit, second_visit, floor_version_after_first).
    floor_version_after_first is the floor version observed after the first sign-in,
    suitable for the second sign-in's expected_floor_version."""
    set_clock(now_utc)
    site = create_site(badge_total=badge_total)
    floor = create_floor(site["id"], capacity=1)
    host = create_host(site["id"])
    v1 = create_cleared_visit(site["id"], host["id"], floor["id"],
                              visitor_full_name="First In", visitor_company="FirstCo",
                              id_scanned=True)
    v1_signed = sign_in_visit(v1["id"], floor["id"])
    floor_v_after = get_floor_version(floor["id"])
    v2 = create_cleared_visit(site["id"], host["id"], floor["id"],
                              visitor_full_name="Second In", visitor_company="SecondCo",
                              id_scanned=second_id_scanned)
    return site, floor, host, v1_signed, v2, floor_v_after


# --- Tier: delivery ------------------------------------------------------

def create_delivery(host_id, **overrides):
    """Log a delivery (LobbyAttendant). Returns the RECEIVED delivery."""
    payload = f.create_delivery_payload(host_id, **overrides)
    return get_success_data(api_client.create_delivery(payload, LA))


# --- Helpers for officer headers tied to a host -------------------------

def officer_headers_as_host(host_id):
    """SecurityOfficer headers whose X-User-ID equals a Host.id — for the
    segregation-of-duties violation case (PRD 3.4)."""
    return make_security_officer_headers(host_id)


def host_headers(host_id):
    return make_host_headers(host_id)
