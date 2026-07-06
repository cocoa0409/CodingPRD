"""Composite setup helpers.

These encapsulate the multi-step preambles that the difficulty/corner scenarios share:
registering parties, creating and submitting tickets, clearing notifications, dispatching
technicians, completing mark-outs (driving the ticket to MARKED), and refreshing marks.

All setup calls use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" error rather than a confusing downstream assertion. Every fixture builds its
preconditions from scratch — the server is restarted with an empty DB before each test.

Identity threading: after creating an entity-backed actor (Excavator / MemberUtility / LocateTech)
any ownership-gated call uses make_*_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_excavator_payload, create_member_utility_payload, create_locate_tech_payload,
    create_locate_ticket_payload, create_positive_response_payload,
    create_locate_assignment_payload, create_mark_out_payload,
    create_meet_request_payload, create_damage_report_payload,
)
from .test_users import (
    TEST_USERS, make_excavator_headers, make_facility_owner_headers, make_locate_tech_headers,
)

CALL_CENTER = TEST_USERS["call_center_headers"]
ADMIN = TEST_USERS["admin_headers"]

COVERING_POLYGON = {"min_x": 0, "min_y": 0, "max_x": 100, "max_y": 100}
DIG_POLYGON = {"min_x": 10, "min_y": 10, "max_x": 20, "max_y": 20}


# ---------------------------------------------------------------------------
# Tier 0: party registration
# ---------------------------------------------------------------------------

def register_excavator(**overrides) -> dict:
    return get_success_data(api_client.create_excavator(create_excavator_payload(**overrides), CALL_CENTER))


def register_member(**overrides) -> dict:
    """Register an ACTIVE member utility. Defaults to a GAS member covering the standard dig site."""
    payload = create_member_utility_payload(**overrides)
    return get_success_data(api_client.create_member_utility(payload, CALL_CENTER))


def register_tech(member_id: str, certified=("GAS",), **overrides) -> dict:
    payload = create_locate_tech_payload(
        member_utility_id=member_id, certified_facility_types=list(certified), **overrides
    )
    return get_success_data(api_client.create_locate_tech(payload, CALL_CENTER))


def create_ticket(excavator_id: str, **overrides) -> dict:
    payload = create_locate_ticket_payload(excavator_id=excavator_id, **overrides)
    return get_success_data(
        api_client.create_locate_ticket(payload, make_excavator_headers(excavator_id))
    )


def submit_ticket(ticket_id: str, excavator_id: str) -> dict:
    return get_success_data(
        api_client.submit_ticket(ticket_id, make_excavator_headers(excavator_id))
    )


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: notifications & positive responses
# ---------------------------------------------------------------------------

def get_notification_for_member(ticket_id: str, member_id: str) -> dict:
    """Return the (single) UtilityNotification for a ticket routed to member_id."""
    data = get_success_data(
        api_client.list_utility_notifications(
            make_facility_owner_headers(member_id),
            params={"ticket_id": ticket_id, "member_utility_id": member_id},
        )
    )
    rows = data if isinstance(data, list) else data.get("data", data)
    assert rows, f"Setup failed: no notification for ticket {ticket_id} / member {member_id}"
    return rows[0]


def first_notification(ticket_id: str, member_id: str) -> dict:
    """Return the first notification for a ticket (single-member scenarios)."""
    data = get_success_data(
        api_client.list_utility_notifications(
            make_facility_owner_headers(member_id), params={"ticket_id": ticket_id}
        )
    )
    rows = data if isinstance(data, list) else data.get("data", data)
    assert rows, f"Setup failed: no notifications for ticket {ticket_id}"
    return rows[0]


def post_response(notification_id: str, member_id: str, outcome: str = "CLEAR") -> dict:
    payload = create_positive_response_payload(notification_id=notification_id, outcome=outcome)
    return get_success_data(
        api_client.create_positive_response(payload, make_facility_owner_headers(member_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: composite — a submitted, single-member EMERGENCY ticket
# ---------------------------------------------------------------------------

def setup_submitted_ticket(ticket_type="EMERGENCY", member_overrides=None, ticket_overrides=None):
    """Register excavator + one covering member + submit a ticket.

    Returns dict with excavator, member, ticket (post-submit), notification.
    """
    member_overrides = member_overrides or {}
    ticket_overrides = ticket_overrides or {}
    exc = register_excavator()
    mem = register_member(service_polygon=COVERING_POLYGON, **member_overrides)
    ticket = create_ticket(exc["id"], ticket_type=ticket_type, **ticket_overrides)
    submit_ticket(ticket["id"], exc["id"])
    note = first_notification(ticket["id"], mem["id"])
    return {"excavator": exc, "member": mem, "ticket": ticket, "notification": note}


def setup_cleared_ticket(ticket_type="EMERGENCY", member_facility="GAS",
                         emergency_contact_minutes=None, tech_certified=("GAS",)):
    """Submitted EMERGENCY ticket with its single notification answered CLEAR (ALL_CLEAR posture),
    plus a certified AVAILABLE tech ready to dispatch.

    Returns dict: excavator, member, tech, ticket, notification.
    """
    exc = register_excavator()
    mem_overrides = {"facility_type": member_facility, "service_polygon": COVERING_POLYGON}
    if emergency_contact_minutes is not None:
        mem_overrides["emergency_contact_minutes"] = emergency_contact_minutes
    mem = register_member(**mem_overrides)
    tech = register_tech(mem["id"], certified=tech_certified)
    # A NORMAL, non-white-lined ticket requires a prior MeetRequest to submit
    # (PRD §3.2). This fixture only needs a submittable ticket, so white-line
    # NORMAL tickets to satisfy that prerequisite; EMERGENCY tickets are exempt.
    ticket_overrides = {} if ticket_type == "EMERGENCY" else {"is_white_lined": True}
    ticket = create_ticket(exc["id"], ticket_type=ticket_type, **ticket_overrides)
    submit_ticket(ticket["id"], exc["id"])
    note = first_notification(ticket["id"], mem["id"])
    post_response(note["id"], mem["id"], "CLEAR")
    return {"excavator": exc, "member": mem, "tech": tech, "ticket": ticket, "notification": note}


# ---------------------------------------------------------------------------
# Tier 3: dispatch & assignment lifecycle shortcuts
# ---------------------------------------------------------------------------

def dispatch(ticket_id: str, notification_id: str, tech_id: str, owner_member_id: str) -> dict:
    payload = create_locate_assignment_payload(
        ticket_id=ticket_id, notification_id=notification_id, locate_tech_id=tech_id
    )
    return get_success_data(
        api_client.create_locate_assignment(payload, make_facility_owner_headers(owner_member_id))
    )


def go_en_route(assignment_id: str, tech_id: str) -> dict:
    return get_success_data(
        api_client.assignment_en_route(assignment_id, make_locate_tech_headers(tech_id))
    )


def create_markout(assignment_id: str, ticket_id: str, tech_id: str, **overrides) -> dict:
    payload = create_mark_out_payload(assignment_id=assignment_id, ticket_id=ticket_id, **overrides)
    return get_success_data(
        api_client.create_mark_out(payload, make_locate_tech_headers(tech_id))
    )


def complete_markout(markout_id: str, tech_id: str) -> dict:
    return get_success_data(
        api_client.complete_mark_out(markout_id, make_locate_tech_headers(tech_id))
    )


def setup_en_route_with_markout(ticket_type="EMERGENCY", marks_count=2):
    """Cleared ticket -> dispatch -> en-route -> create IN_PROGRESS mark-out (not completed).

    Returns dict: excavator, member, tech, ticket, notification, assignment, markout.
    """
    base = setup_cleared_ticket(ticket_type=ticket_type)
    asg = dispatch(base["ticket"]["id"], base["notification"]["id"],
                   base["tech"]["id"], base["member"]["id"])
    go_en_route(asg["id"], base["tech"]["id"])
    mk = create_markout(asg["id"], base["ticket"]["id"], base["tech"]["id"], marks_count=marks_count)
    base["assignment"] = asg
    base["markout"] = mk
    return base


def setup_marked_ticket(ticket_type="EMERGENCY", marks_count=2):
    """Full lifecycle to a MARKED ticket: cleared -> dispatch -> en-route -> mark-out -> complete.

    Returns dict: excavator, member, tech, ticket, notification, assignment, markout.
    The ticket is MARKED; the mark-out is COMPLETE.
    """
    base = setup_en_route_with_markout(ticket_type=ticket_type, marks_count=marks_count)
    complete_markout(base["markout"]["id"], base["tech"]["id"])
    return base


def current_ticket_version(ticket_id: str, tech_id: str) -> int:
    data = get_success_data(
        api_client.get_locate_ticket(ticket_id, make_locate_tech_headers(tech_id))
    )
    return data["version"]


def create_refresh_markout(assignment_id: str, ticket_id: str, tech_id: str,
                           supersedes_markout_id: str, expected_ticket_version, **overrides) -> dict:
    payload = create_mark_out_payload(
        assignment_id=assignment_id, ticket_id=ticket_id,
        supersedes_markout_id=supersedes_markout_id,
        expected_ticket_version=expected_ticket_version, **overrides,
    )
    return get_success_data(
        api_client.create_mark_out(payload, make_locate_tech_headers(tech_id))
    )


# ---------------------------------------------------------------------------
# Tier 4: damage reports
# ---------------------------------------------------------------------------

def file_damage_report(ticket_id: str, member_id: str, repair_cost_cents: int,
                       dug_within_marks: bool, markout_id: str = None) -> dict:
    payload = create_damage_report_payload(
        ticket_id=ticket_id, member_utility_id=member_id,
        repair_cost_cents=repair_cost_cents, dug_within_marks=dug_within_marks,
    )
    if markout_id is not None:
        payload["markout_id"] = markout_id
    return get_success_data(
        api_client.create_damage_report(payload, make_facility_owner_headers(member_id))
    )


def review_damage_report(damage_report_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.review_damage_report(damage_report_id, make_facility_owner_headers(member_id))
    )


# ---------------------------------------------------------------------------
# Tier 5: meet requests
# ---------------------------------------------------------------------------

def create_meet(ticket_id: str, member_id: str, excavator_id: str, start_min: int, end_min: int) -> dict:
    payload = create_meet_request_payload(
        ticket_id=ticket_id, member_utility_id=member_id,
        proposed_start_min=start_min, proposed_end_min=end_min,
    )
    return get_success_data(
        api_client.create_meet_request(payload, make_excavator_headers(excavator_id))
    )


def schedule_meet(meet_id: str, member_id: str) -> dict:
    return get_success_data(
        api_client.schedule_meet_request(meet_id, make_facility_owner_headers(member_id))
    )
