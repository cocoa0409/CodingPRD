"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database and the default logical clock
2026-08-01T00:00:00Z). Setup calls go through get_success_data so failures
surface as clear "Setup step failed" errors.
"""
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_EVENT_ENDS_AT,
    DEFAULT_EVENT_STARTS_AT,
    DEFAULT_MEMBER_IDS,
    STANDARD_TERM_ENDS_AT,
    TENURE_SAFE_CLOCK,
)
from .factories import (
    assign_sponsor_payload,
    create_climate_survey_payload,
    create_event_payload,
    create_funding_request_payload,
    create_group_payload,
    create_leadership_term_payload,
    create_membership_payload,
    create_mentoring_engagement_payload,
    create_program_payload,
    create_rsvp_payload,
    create_sponsor_payload,
    create_survey_response_payload,
    create_venue_payload,
)
from .test_users import (
    make_dei_admin_headers,
    make_employee_headers,
    make_group_leader_headers,
    make_sponsor_headers,
)

DEI_HEADERS = make_dei_admin_headers()


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and simple state progression
# ---------------------------------------------------------------------------

def create_program(pool_total_cents: int = 100000, fiscal_year: int = 2027,
                   goals: Optional[list] = None) -> dict:
    """Create an InclusionProgram (starts SETUP / NORMAL)."""
    payload = create_program_payload(fiscal_year, pool_total_cents, goals)
    return get_success_data(api_client.create_program(payload, DEI_HEADERS))


def open_program(program_id: str) -> dict:
    """Move a program SETUP -> OPEN. Returns the updated program."""
    return get_success_data(api_client.open_program(program_id, DEI_HEADERS))


def create_open_program(pool_total_cents: int = 100000, fiscal_year: int = 2027,
                        goals: Optional[list] = None) -> dict:
    """Create a program and open it. Returns the OPEN program."""
    program = create_program(pool_total_cents, fiscal_year, goals)
    return open_program(program["id"])


def lock_allocation(program_id: str) -> dict:
    """Move a program OPEN -> ALLOCATION_LOCKED (runs the allocation waterfall)."""
    return get_success_data(api_client.lock_allocation(program_id, DEI_HEADERS))


def create_sponsor(employee_id: str = "emp_sp1", max_groups: int = 3,
                   max_mentees: int = 2) -> dict:
    """Appoint an executive sponsor (starts ACTIVE)."""
    payload = create_sponsor_payload(employee_id, max_groups, max_mentees)
    return get_success_data(api_client.create_sponsor(payload, DEI_HEADERS))


def set_sponsor_status(sponsor_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.set_sponsor_status(sponsor_id, {"to_status": to_status}, DEI_HEADERS)
    )


def advance_clock(to_iso8601: str) -> None:
    """Advance the logical clock (runs the term-expiry sweep)."""
    get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, DEI_HEADERS))


def create_venue(name: str = "Main Hall", capacity: int = 100) -> dict:
    return get_success_data(api_client.create_venue(create_venue_payload(name, capacity), DEI_HEADERS))


# ---------------------------------------------------------------------------
# Tier 2: group charter chain (draft -> members -> sponsor -> submit -> endorse)
# ---------------------------------------------------------------------------

def create_group_draft(program_id: str, name: str, category: str = "AFFINITY",
                       creator_employee_id: str = "emp_l1",
                       mission_statement: str = "A test mission statement") -> dict:
    """Create an ErgGroup in CHARTER_DRAFT owned by creator_employee_id."""
    payload = create_group_payload(program_id, name, mission_statement, category)
    return get_success_data(
        api_client.create_group(payload, make_group_leader_headers(creator_employee_id))
    )


def add_members(group_id: str, employee_ids: List[str]) -> List[dict]:
    """Enroll each employee via DeiAdmin. Returns the membership rows."""
    rows = []
    for employee_id in employee_ids:
        payload = create_membership_payload(group_id, employee_id=employee_id)
        rows.append(get_success_data(api_client.create_membership(payload, DEI_HEADERS)))
    return rows


def assign_sponsor_to_group(group: dict, sponsor_id: str) -> dict:
    """Assign a sponsor using the group's current version (OCC)."""
    payload = assign_sponsor_payload(sponsor_id, group["version"])
    return get_success_data(api_client.assign_sponsor(group["id"], payload, DEI_HEADERS))


def submit_charter(group_id: str, creator_employee_id: str) -> dict:
    return get_success_data(
        api_client.submit_charter(group_id, make_group_leader_headers(creator_employee_id))
    )


def sponsor_endorse_charter(group_id: str, sponsor_id: str) -> dict:
    return get_success_data(
        api_client.group_sponsor_decision(
            group_id, {"decision": "ENDORSE"}, make_sponsor_headers(sponsor_id)
        )
    )


def dei_approve_charter(group_id: str) -> dict:
    return get_success_data(
        api_client.group_dei_decision(group_id, {"decision": "APPROVE"}, DEI_HEADERS)
    )


def create_active_group(program_id: str, sponsor_id: str, name: str,
                        category: str = "AFFINITY", creator_employee_id: str = "emp_l1",
                        member_ids: Optional[List[str]] = None) -> dict:
    """Full charter chain: draft -> 10 members -> assign sponsor -> submit ->
    sponsor ENDORSE -> DEI APPROVE. Returns the ACTIVE group."""
    member_ids = list(member_ids) if member_ids is not None else list(DEFAULT_MEMBER_IDS)
    group = create_group_draft(program_id, name, category, creator_employee_id)
    add_members(group["id"], member_ids)
    group = assign_sponsor_to_group(group, sponsor_id)
    submit_charter(group["id"], creator_employee_id)
    sponsor_endorse_charter(group["id"], sponsor_id)
    return dei_approve_charter(group["id"])


# ---------------------------------------------------------------------------
# Tier 3: leadership terms (tenure requires the 2026-11-01 clock advance)
# ---------------------------------------------------------------------------

def create_leader_term(group_id: str, leader_employee_id: str,
                       ends_at: str = STANDARD_TERM_ENDS_AT,
                       predecessor_term_id: Optional[str] = None) -> dict:
    payload = create_leadership_term_payload(group_id, leader_employee_id, ends_at,
                                             predecessor_term_id)
    return get_success_data(api_client.create_leadership_term(payload, DEI_HEADERS))


def setup_active_group_with_leader(program_id: str, sponsor_id: str,
                                   name: str = "Group", category: str = "AFFINITY",
                                   creator_employee_id: str = "emp_l1",
                                   term_leader: str = "emp_f01",
                                   ends_at: str = STANDARD_TERM_ENDS_AT,
                                   advance_to: str = TENURE_SAFE_CLOCK) -> tuple:
    """ACTIVE group (10 founding members) + ACTIVE leadership term for
    term_leader. The clock is advanced past the 90-day tenure gate first.
    Returns (group, term)."""
    group = create_active_group(program_id, sponsor_id, name, category, creator_employee_id)
    advance_clock(advance_to)
    term = create_leader_term(group["id"], term_leader, ends_at)
    return group, term


def setup_locked_group_with_leader(program_id: str, sponsor_id: str,
                                   name: str = "Group", category: str = "AFFINITY",
                                   creator_employee_id: str = "emp_l1",
                                   term_leader: str = "emp_f01") -> tuple:
    """ACTIVE group + ACTIVE term + program ALLOCATION_LOCKED.
    Returns (group, term)."""
    group, term = setup_active_group_with_leader(
        program_id, sponsor_id, name, category, creator_employee_id, term_leader
    )
    lock_allocation(program_id)
    return group, term


# ---------------------------------------------------------------------------
# Tier 3: funding request lifecycle
# ---------------------------------------------------------------------------

def create_funding_request(group_id: str, leader_employee_id: str,
                           category: str = "EVENT", purpose: str = "Test purpose",
                           requested_cents: int = 100000,
                           external_matching_cents: int = 0) -> dict:
    """Submit a funding request as the group's ACTIVE-term leader."""
    payload = create_funding_request_payload(group_id, category, purpose,
                                             requested_cents, external_matching_cents)
    return get_success_data(
        api_client.create_funding_request(payload, make_group_leader_headers(leader_employee_id))
    )


def sponsor_decide_funding(request_id: str, sponsor_id: str, decision: str,
                           counter_amount_cents: Optional[int] = None) -> dict:
    payload = {"decision": decision}
    if counter_amount_cents is not None:
        payload["counter_amount_cents"] = counter_amount_cents
    return get_success_data(
        api_client.funding_sponsor_decision(request_id, payload, make_sponsor_headers(sponsor_id))
    )


def setup_endorsed_request(group_id: str, sponsor_id: str, leader_employee_id: str,
                           **request_kwargs) -> dict:
    """Funding request walked SUBMITTED -> ENDORSED."""
    request = create_funding_request(group_id, leader_employee_id, **request_kwargs)
    return sponsor_decide_funding(request["id"], sponsor_id, "ENDORSE")


def setup_approved_request(group_id: str, sponsor_id: str, leader_employee_id: str,
                           **request_kwargs) -> dict:
    """Funding request walked SUBMITTED -> ENDORSED -> APPROVED (program must
    be ALLOCATION_LOCKED)."""
    request = setup_endorsed_request(group_id, sponsor_id, leader_employee_id, **request_kwargs)
    return get_success_data(
        api_client.funding_dei_decision(request["id"], {"decision": "APPROVE"}, DEI_HEADERS)
    )


# ---------------------------------------------------------------------------
# Tier 3: events and RSVPs
# ---------------------------------------------------------------------------

def create_event(group_id: str, venue_id: str, title: str = "Test Event",
                 category: str = "SOCIAL",
                 starts_at: str = DEFAULT_EVENT_STARTS_AT,
                 ends_at: str = DEFAULT_EVENT_ENDS_AT,
                 capacity: int = 10,
                 funding_request_id: Optional[str] = None) -> dict:
    payload = create_event_payload(group_id, venue_id, title, category, starts_at,
                                   ends_at, capacity, funding_request_id)
    return get_success_data(api_client.create_event(payload, DEI_HEADERS))


def publish_event(event_id: str) -> dict:
    return get_success_data(api_client.publish_event(event_id, DEI_HEADERS))


def setup_published_event(group_id: str, venue_id: str, **event_kwargs) -> dict:
    """PLANNED -> PUBLISHED event. Returns the published event."""
    event = create_event(group_id, venue_id, **event_kwargs)
    return publish_event(event["id"])


def rsvp(event_id: str, employee_id: str) -> dict:
    """RSVP as an Employee (REGISTERED if a seat is free, else WAITLISTED)."""
    return get_success_data(
        api_client.create_rsvp(create_rsvp_payload(event_id), make_employee_headers(employee_id))
    )


def rsvp_many(event_id: str, employee_ids: List[str]) -> List[dict]:
    return [rsvp(event_id, employee_id) for employee_id in employee_ids]


def check_in(rsvp_id: str) -> dict:
    return get_success_data(api_client.check_in_rsvp(rsvp_id, DEI_HEADERS))


# ---------------------------------------------------------------------------
# Tier 3: climate surveys
# ---------------------------------------------------------------------------

def create_survey(program_id: str, title: str = "Pulse",
                  opens_at: str = "2026-08-01T00:00:00Z",
                  closes_at: str = "2026-09-01T00:00:00Z",
                  min_responses: int = 1) -> dict:
    payload = create_climate_survey_payload(program_id, title, opens_at, closes_at,
                                            min_responses)
    return get_success_data(api_client.create_climate_survey(payload, DEI_HEADERS))


def open_survey(survey_id: str) -> dict:
    return get_success_data(api_client.open_climate_survey(survey_id, DEI_HEADERS))


def submit_response(survey_id: str, employee_id: str, belonging_score: int = 4,
                    growth_score: int = 4, fairness_score: int = 4,
                    safety_score: int = 4) -> dict:
    payload = create_survey_response_payload(survey_id, belonging_score, growth_score,
                                             fairness_score, safety_score)
    return get_success_data(
        api_client.create_survey_response(payload, make_employee_headers(employee_id))
    )


def setup_open_survey(program_id: str, **survey_kwargs) -> dict:
    """DRAFT -> OPEN survey. Returns the open survey."""
    survey = create_survey(program_id, **survey_kwargs)
    return open_survey(survey["id"])


# ---------------------------------------------------------------------------
# Tier 3: mentoring engagements
# ---------------------------------------------------------------------------

def create_engagement(program_id: str, sponsor_id: str, mentee_employee_id: str,
                      starts_at: str = "2026-09-01T00:00:00Z",
                      ends_at: str = "2026-09-15T00:00:00Z",
                      via_admin: bool = False) -> dict:
    """Propose a mentoring engagement (PROPOSED). An Employee proposes for
    themselves; a DeiAdmin supplies mentee_employee_id explicitly."""
    if via_admin:
        payload = create_mentoring_engagement_payload(
            program_id, sponsor_id, starts_at, ends_at, mentee_employee_id
        )
        headers = DEI_HEADERS
    else:
        payload = create_mentoring_engagement_payload(
            program_id, sponsor_id, starts_at, ends_at
        )
        headers = make_employee_headers(mentee_employee_id)
    return get_success_data(api_client.create_mentoring_engagement(payload, headers))
