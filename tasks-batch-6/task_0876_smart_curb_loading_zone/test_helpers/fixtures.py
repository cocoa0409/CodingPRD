"""Composite setup helpers.

Each helper drives the PRD-declared endpoints to reach a target state so tests
can focus on assertions. All setup calls go through get_success_data() (lenient
2xx validator) so a broken precondition surfaces as a clear "Setup failed".

Identity threading: the Permittee role is entity_backed, so every ownership-gated
call uses make_permittee_headers(permittee_id) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_permittee_payload,
    create_pricing_policy_payload,
    create_zone_payload,
    create_permit_payload,
    create_reservation_payload,
    create_citation_payload,
    create_event_payload,
    create_schedule_window_payload,
)
from .test_users import (
    make_permittee_headers,
    make_curb_planner_headers,
    make_permit_approver_headers,
    make_enforcement_officer_headers,
    make_platform_admin_headers,
)

# Canonical reservation window used across pricing fixtures.
PEAK_START = "2026-06-01T08:00:00Z"   # start hour 08 -> peak window [7,10)
PEAK_END = "2026-06-01T08:45:00Z"     # 45 booked minutes -> 3 slots
OFFPEAK_START = "2026-06-01T12:00:00Z"
OFFPEAK_END = "2026-06-01T12:15:00Z"


# --- Primitive builders --------------------------------------------------------

def advance_clock(api, iso, admin_user="admin1"):
    """Set the server logical clock to an ISO-8601 instant."""
    return get_success_data(api.set_clock(iso, make_platform_admin_headers(admin_user)))


def make_policy(api, **overrides):
    return get_success_data(api.create_pricing_policy(
        create_pricing_policy_payload(**overrides), make_curb_planner_headers()))


def make_zone(api, policy_id, **overrides):
    return get_success_data(api.create_zone(
        create_zone_payload(policy_id, **overrides), make_curb_planner_headers()))


def make_permittee(api, **overrides):
    return get_success_data(api.create_permittee(
        create_permittee_payload(**overrides), make_platform_admin_headers()))


def make_permit(api, permittee_id, zone_ids, **overrides):
    """Create a DRAFT permit owned by permittee_id."""
    return get_success_data(api.create_permit(
        create_permit_payload(permittee_id, zone_ids, **overrides),
        make_permittee_headers(permittee_id)))


def submit_permit(api, permit_id, permittee_id):
    return get_success_data(api.submit_permit(permit_id, make_permittee_headers(permittee_id)))


def review_permit(api, permit_id, reviewer="planner1"):
    return get_success_data(api.review_permit(permit_id, make_curb_planner_headers(reviewer)))


def approve_permit(api, permit_id, approver="approver1"):
    return get_success_data(api.approve_permit(permit_id, make_permit_approver_headers(approver)))


def activate_permit(api, permit_id, permittee_id, reviewer="planner1", approver="approver1"):
    """Walk a DRAFT permit through submit -> review -> approve to ACTIVE."""
    submit_permit(api, permit_id, permittee_id)
    review_permit(api, permit_id, reviewer)
    return approve_permit(api, permit_id, approver)


# --- Composite scenarios -------------------------------------------------------

def setup_active_permit(api, clock="2026-05-20T00:00:00Z", zone_overrides=None,
                        policy_overrides=None, reviewer="planner1", approver="approver1"):
    """Policy + ACTIVE zone + permittee + ACTIVE permit authorizing that zone.

    Returns a dict: policy, zone, permittee, permit, plus id shortcuts
    (policy_id, zone_id, permittee_id, permit_id).
    """
    advance_clock(api, clock)
    policy = make_policy(api, **(policy_overrides or {}))
    zone = make_zone(api, policy["id"], **(zone_overrides or {}))
    permittee = make_permittee(api)
    permit = make_permit(api, permittee["id"], [zone["id"]])
    permit = activate_permit(api, permit["id"], permittee["id"], reviewer, approver)
    return {
        "policy": policy, "zone": zone, "permittee": permittee, "permit": permit,
        "policy_id": policy["id"], "zone_id": zone["id"],
        "permittee_id": permittee["id"], "permit_id": permit["id"],
    }


def make_reservation(api, permit_id, permittee_id, zone_id, start_utc, end_utc):
    """Create a PENDING reservation."""
    return get_success_data(api.create_reservation(
        create_reservation_payload(permit_id, zone_id, start_utc, end_utc),
        make_permittee_headers(permittee_id)))


def confirm_reservation(api, reservation_id, permittee_id):
    return get_success_data(api.confirm_reservation(
        reservation_id, make_permittee_headers(permittee_id)))


def make_confirmed_reservation(api, permit_id, permittee_id, zone_id, start_utc, end_utc):
    """Create + confirm a reservation. Returns the CONFIRMED reservation dict."""
    res = make_reservation(api, permit_id, permittee_id, zone_id, start_utc, end_utc)
    return confirm_reservation(api, res["id"], permittee_id)


def setup_confirmed_reservation(api, start_utc=PEAK_START, end_utc=PEAK_END,
                                clock="2026-05-20T00:00:00Z", zone_overrides=None):
    """setup_active_permit + one CONFIRMED reservation on the peak window.

    Returns the setup_active_permit dict augmented with reservation / reservation_id.
    """
    ctx = setup_active_permit(api, clock=clock, zone_overrides=zone_overrides)
    res = make_confirmed_reservation(
        api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"], start_utc, end_utc)
    ctx["reservation"] = res
    ctx["reservation_id"] = res["id"]
    return ctx


# --- Sensor helpers ------------------------------------------------------------

def open_session(api, zone_id, reservation_id=None, admin_user="admin1"):
    payload = {"zone_id": zone_id}
    if reservation_id is not None:
        payload["reservation_id"] = reservation_id
    return get_success_data(api.occupancy_enter(payload, make_platform_admin_headers(admin_user)))


def close_session(api, session_id, admin_user="admin1"):
    return get_success_data(api.occupancy_exit(session_id, make_platform_admin_headers(admin_user)))


def record_occupancy(api, zone_id, reservation_id, entered_iso, exited_iso):
    """Advance clock to entered_iso, open a session, advance to exited_iso, close it.
    Returns the CLOSED OccupancySession dict."""
    advance_clock(api, entered_iso)
    sess = open_session(api, zone_id, reservation_id)
    advance_clock(api, exited_iso)
    return close_session(api, sess["id"])


# --- Citation helpers ----------------------------------------------------------

def make_citation(api, zone_id, permittee_id, violation_type="OVERSTAY",
                  officer="officer1", **overrides):
    return get_success_data(api.create_citation(
        create_citation_payload(zone_id, permittee_id, violation_type, **overrides),
        make_enforcement_officer_headers(officer)))


def dispute_citation(api, citation_id, permittee_id, reason="not us"):
    return get_success_data(api.dispute_citation(
        citation_id, reason, make_permittee_headers(permittee_id)))


def setup_disputed_citation(api, violation_type="OVERSTAY", clock="2026-05-20T00:00:00Z"):
    """Policy + zone + permittee + an ISSUED-then-DISPUTED citation.

    Returns dict with policy, zone, permittee ids plus citation / citation_id and
    the base fine captured at issue.
    """
    advance_clock(api, clock)
    policy = make_policy(api)
    zone = make_zone(api, policy["id"])
    permittee = make_permittee(api)
    citation = make_citation(api, zone["id"], permittee["id"], violation_type)
    disputed = dispute_citation(api, citation["id"], permittee["id"])
    return {
        "policy": policy, "zone": zone, "permittee": permittee,
        "permittee_id": permittee["id"], "zone_id": zone["id"],
        "citation": citation, "citation_id": citation["id"],
        "base_fine_cents": citation["fine_due_cents"],
        "disputed": disputed,
    }


# --- Event helpers -------------------------------------------------------------

def make_event(api, zone_ids, start_utc, end_utc, name="Street Fair", planner="planner1"):
    return get_success_data(api.create_event(
        create_event_payload(name, start_utc, end_utc, zone_ids),
        make_curb_planner_headers(planner)))


# --- Schedule-window helpers ---------------------------------------------------

def make_schedule_window(api, permit_id, permittee_id, zone_id, day_of_week,
                         start_minute, end_minute, exclusive=None):
    overrides = {}
    if exclusive is not None:
        overrides["exclusive"] = exclusive
    return get_success_data(api.create_schedule_window(
        create_schedule_window_payload(
            permit_id, zone_id, day_of_week, start_minute, end_minute, **overrides),
        make_permittee_headers(permittee_id)))


def setup_permit_with_zone_no_approval(api, clock="2026-05-20T00:00:00Z", zone_overrides=None):
    """Policy + ACTIVE zone + permittee + DRAFT permit (never submitted/approved).

    Used by schedule-window fixtures — attaching a window does not require an
    ACTIVE permit, only ownership.
    """
    advance_clock(api, clock)
    policy = make_policy(api, **{})
    zone = make_zone(api, policy["id"], **(zone_overrides or {}))
    permittee = make_permittee(api)
    permit = make_permit(api, permittee["id"], [zone["id"]])
    return {
        "policy": policy, "zone": zone, "permittee": permittee, "permit": permit,
        "policy_id": policy["id"], "zone_id": zone["id"],
        "permittee_id": permittee["id"], "permit_id": permit["id"],
    }


# --- Ledger inspection ---------------------------------------------------------

def fetch_ledger_entries(api, params=None, planner="planner1"):
    """List ledger entries as CurbPlanner. Returns the raw data list."""
    from prd_bench_local_runner.testing import validate_paginated
    resp = api.list_ledger_entries(make_curb_planner_headers(planner), params=params or {})
    data, _meta = validate_paginated(resp)
    return data
