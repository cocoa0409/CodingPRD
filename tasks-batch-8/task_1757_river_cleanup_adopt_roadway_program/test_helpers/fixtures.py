"""Composite setup helpers for the river-cleanup program (PRD §2.5, §3).

Every fixture builds preconditions from scratch via PRD endpoints only; the
harness restarts the server before every test, so nothing is shared between
tests. Setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_depot_payload,
    create_event_payload,
    create_group_payload,
    create_hazard_payload,
    create_segment_payload,
    create_waiver_payload,
    estimated_report_payload,
)
from .test_users import make_coordinator_headers, make_group_leader_headers

COORD = make_coordinator_headers()


# ---------------------------------------------------------------------------
# Tier 1 / 2: basic hierarchy — group, segment, agreement (pending or active)
# ---------------------------------------------------------------------------

def create_group(name="Riverkeepers", org_type="CIVIC",
                 contact_name="Gina Lead", contact_email="gina@riverkeepers.org"):
    """Register an adopter group; returns the group dict. The response id is
    that leader's X-User-ID thereafter."""
    resp = api_client.create_group(
        create_group_payload(
            name=name, org_type=org_type,
            contact_name=contact_name, contact_email=contact_email,
        ),
        make_group_leader_headers("bootstrap-registrar"),
    )
    return get_success_data(resp)


def create_segment(route_name="River Rd", mile_marker_start=4.0,
                   mile_marker_end=6.0, segment_type="RIVERBANK",
                   water_adjacent=True):
    resp = api_client.create_segment(
        create_segment_payload(
            route_name=route_name,
            mile_marker_start=mile_marker_start,
            mile_marker_end=mile_marker_end,
            segment_type=segment_type,
            water_adjacent=water_adjacent,
        ),
        COORD,
    )
    return get_success_data(resp)


def create_agreement(group, segment, contact_email=None):
    """Create a PENDING_REVIEW agreement owned by group.id."""
    headers = make_group_leader_headers(group["id"])
    resp = api_client.create_agreement(
        create_agreement_payload(
            group["id"], segment["id"],
            contact_email=contact_email or group["contact_email"],
        ),
        headers,
    )
    return get_success_data(resp)


def approve_agreement(agreement_id):
    resp = api_client.review_decision(agreement_id, {"decision": "APPROVE"}, COORD)
    return get_success_data(resp)


def setup_active_agreement(group_name="Riverkeepers", org_type="CIVIC",
                           contact_name="Gina Lead",
                           contact_email="gina@riverkeepers.org",
                           route_name="River Rd",
                           mile_marker_start=4.0, mile_marker_end=6.0,
                           segment_type="RIVERBANK", water_adjacent=True):
    """Active agreement on a fresh segment. Returns (group, segment, agreement)."""
    group = create_group(name=group_name, org_type=org_type,
                         contact_name=contact_name,
                         contact_email=contact_email)
    segment = create_segment(
        route_name=route_name,
        mile_marker_start=mile_marker_start,
        mile_marker_end=mile_marker_end,
        segment_type=segment_type,
        water_adjacent=water_adjacent,
    )
    agreement = create_agreement(group, segment, contact_email=contact_email)
    agreement = approve_agreement(agreement["id"])
    return group, segment, agreement


# ---------------------------------------------------------------------------
# Tier 3: event lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_adult_waiver(agreement_id, group_id, name="Ada Adult",
                        dob="1990-05-01"):
    headers = make_group_leader_headers(group_id)
    resp = api_client.create_waiver(
        create_waiver_payload(agreement_id, volunteer_full_name=name, dob=dob),
        headers,
    )
    return get_success_data(resp)


def create_minor_waiver(agreement_id, group_id, supervisor_waiver_id,
                        name="Milo Minor", dob="2009-06-15",
                        guardian_full_name="Pat Parent"):
    headers = make_group_leader_headers(group_id)
    resp = api_client.create_waiver(
        create_waiver_payload(
            agreement_id,
            volunteer_full_name=name,
            dob=dob,
            guardian_full_name=guardian_full_name,
            guardian_consent=True,
            supervisor_waiver_id=supervisor_waiver_id,
        ),
        headers,
    )
    return get_success_data(resp)


def create_event(agreement_id, group_id, scheduled_date="2026-09-10",
                 expected_volunteers=2):
    headers = make_group_leader_headers(group_id)
    resp = api_client.create_event(
        create_event_payload(
            agreement_id,
            scheduled_date=scheduled_date,
            expected_volunteers=expected_volunteers,
        ),
        headers,
    )
    return get_success_data(resp)


def brief_event(event_id, group_id, attendee_waiver_ids):
    headers = make_group_leader_headers(group_id)
    resp = api_client.record_briefing(
        event_id, {"attendee_waiver_ids": attendee_waiver_ids}, headers
    )
    return get_success_data(resp)


def complete_event(event_id, group_id, report_payload=None):
    """File a debris report for a BRIEFING_DONE event (clock must already be
    inside the report window). Returns the created DebrisReport."""
    headers = make_group_leader_headers(group_id)
    resp = api_client.submit_debris_report(
        event_id, report_payload or estimated_report_payload(), headers
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, COORD)
    return get_success_data(resp)


def complete_event_on_date(event_id, group_id, clock_iso, report_payload=None):
    """Advance the clock onto the event's scheduled date and file the report."""
    set_clock(clock_iso)
    return complete_event(event_id, group_id, report_payload)


# ---------------------------------------------------------------------------
# Tier 4: composite scenarios reused across tests
# ---------------------------------------------------------------------------

def setup_agreement_with_waiver(**kwargs):
    """Active agreement + one adult waiver. Returns (group, segment, agreement, waiver)."""
    group, segment, agreement = setup_active_agreement(**kwargs)
    waiver = create_adult_waiver(agreement["id"], group["id"])
    return group, segment, agreement, waiver


def setup_briefed_event(scheduled_date="2026-09-10", expected_volunteers=2,
                        clock_iso=None, **kwargs):
    """Active agreement + adult waiver + briefed event.

    If clock_iso is provided, the clock is advanced AFTER briefing (so the
    briefing is legal at the setup clock). Returns
    (group, segment, agreement, waiver, event).
    """
    group, segment, agreement, waiver = setup_agreement_with_waiver(**kwargs)
    event = create_event(
        agreement["id"], group["id"],
        scheduled_date=scheduled_date, expected_volunteers=expected_volunteers,
    )
    event = brief_event(event["id"], group["id"], [waiver["id"]])
    if clock_iso is not None:
        set_clock(clock_iso)
    return group, segment, agreement, waiver, event


def setup_completed_event(scheduled_date="2026-09-10", clock_iso=None,
                          report_payload=None, expected_volunteers=2, **kwargs):
    """Active agreement + one COMPLETED event (briefed, clock advanced, report filed).

    Returns (group, segment, agreement, waiver, event, report).
    """
    group, segment, agreement, waiver, event = setup_briefed_event(
        scheduled_date=scheduled_date, expected_volunteers=expected_volunteers,
        **kwargs,
    )
    set_clock(clock_iso or f"{scheduled_date}T10:00:00Z")
    report = complete_event(event["id"], group["id"], report_payload)
    event = get_success_data(api_client.get_event(
        event["id"], make_group_leader_headers(group["id"])
    ))
    return group, segment, agreement, waiver, event, report


def create_depot(name="Central Depot", bags=500, vests=100, grabbers=50):
    resp = api_client.create_depot(
        create_depot_payload(
            name=name, bags_on_hand=bags,
            vests_on_hand=vests, grabbers_on_hand=grabbers,
        ),
        COORD,
    )
    return get_success_data(resp)


def setup_depot_and_active_agreement(depot_bags=500, depot_vests=100,
                                     depot_grabbers=50, **kwargs):
    """Depot + active agreement. Returns (depot, group, segment, agreement)."""
    depot = create_depot(bags=depot_bags, vests=depot_vests,
                         grabbers=depot_grabbers)
    group, segment, agreement = setup_active_agreement(**kwargs)
    return depot, group, segment, agreement


def issue_supplies(event_id, group_id, depot_id):
    headers = make_group_leader_headers(group_id)
    resp = api_client.issue_supplies(event_id, {"depot_id": depot_id}, headers)
    return get_success_data(resp)


def get_agreement(agreement_id):
    return get_success_data(api_client.get_agreement(agreement_id, COORD))


def get_event(event_id):
    return get_success_data(api_client.get_event(event_id, COORD))


def get_depot(depot_id):
    return get_success_data(api_client.get_depot(depot_id, COORD))


def get_supply(supply_id):
    return get_success_data(api_client.get_supply(supply_id, COORD))


def get_metrics():
    return get_success_data(api_client.get_metrics(COORD))
