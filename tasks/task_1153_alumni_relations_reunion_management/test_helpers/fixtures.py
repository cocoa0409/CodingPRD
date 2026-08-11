"""Composite setup helpers.

Every test starts against a freshly restarted server (empty database, logical
clock at the startup default), so each helper builds its preconditions from
scratch using only PRD-declared endpoints. Setup calls use the lenient
`get_success_data` validator so failures surface as clear setup errors.

Identity threading: entity-backed roles (CommitteeVolunteer, Alumni,
AffinityGroupLeader, ReunionChair) always act through `make_*_headers` with
the actual record id — never through the shared fallback constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_record_payload,
    create_research_case_payload,
    create_log_lead_payload,
    create_event_payload,
    create_committee_payload,
    create_membership_payload,
    create_ticket_tier_payload,
    create_registration_payload,
    create_group_payload,
    create_program_payload,
    create_campaign_payload,
    create_pledge_payload,
    create_publication_payload,
    create_preference_payload,
)
from .test_users import (
    TEST_USERS,
    make_committee_volunteer_headers,
    make_alumni_headers,
    make_affinity_group_leader_headers,
)

STAFF = TEST_USERS["staff_headers"]
DIRECTOR = TEST_USERS["director_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creators
# ---------------------------------------------------------------------------

def create_record(**overrides) -> dict:
    """Create an AlumniRecord as staff. Returns the created record."""
    resp = api_client.create_record(create_record_payload(**overrides), STAFF)
    return get_success_data(resp)


def create_event(**overrides) -> dict:
    """Create a ReunionEvent as staff. Returns the created event."""
    resp = api_client.create_event(create_event_payload(**overrides), STAFF)
    return get_success_data(resp)


def create_committee(event_id: str, **overrides) -> dict:
    resp = api_client.create_committee(event_id, create_committee_payload(**overrides), STAFF)
    return get_success_data(resp)


def invite_member(committee_id: str, alumni_id: str, role: str = "MEMBER") -> dict:
    """Invite an alumnus to a committee (staff). Returns INVITED membership."""
    resp = api_client.create_membership(
        committee_id, create_membership_payload(alumni_id, role), STAFF
    )
    return get_success_data(resp)


def accept_membership(membership_id: str, alumni_id: str) -> dict:
    """Accept an invitation as the invited volunteer themself (ownership)."""
    resp = api_client.accept_membership(
        membership_id, make_committee_volunteer_headers(alumni_id)
    )
    return get_success_data(resp)


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, STAFF)
    return get_success_data(resp)


def current_event(event_id: str) -> dict:
    return get_success_data(api_client.get_event(event_id, STAFF))


def create_tier(event_id: str, **overrides) -> dict:
    """Create a TicketTier, reading the event's current version first so the
    optimistic-concurrency guard is satisfied however many intermediate
    mutations the event has seen."""
    event = current_event(event_id)
    payload = create_ticket_tier_payload(event["version"], **overrides)
    resp = api_client.create_ticket_tier(event_id, payload, STAFF)
    return get_success_data(resp)


def register(event_id: str, tier_id: str, alumni_id: str) -> dict:
    """Create a registration as the registrant themself (Alumni role)."""
    resp = api_client.create_registration(
        event_id,
        create_registration_payload(tier_id, alumni_id),
        make_alumni_headers(alumni_id),
    )
    return get_success_data(resp)


def confirm(registration_id: str, alumni_id: str) -> dict:
    resp = api_client.confirm_payment(registration_id, make_alumni_headers(alumni_id))
    return get_success_data(resp)


def register_and_confirm(event_id: str, tier_id: str, alumni_id: str) -> dict:
    """Create a registration and confirm payment. Returns CONFIRMED row."""
    registration = register(event_id, tier_id, alumni_id)
    return confirm(registration["id"], alumni_id)


# ---------------------------------------------------------------------------
# Tier 2 — event + committee hierarchies
# ---------------------------------------------------------------------------

def setup_event_with_chair(event_overrides=None, chair_overrides=None) -> dict:
    """Event (PLANNING) + committee + one ACTIVE CHAIR membership.

    Returns dict(event, committee, chair, membership).
    """
    chair = create_record(**(chair_overrides or {}))
    event = create_event(**(event_overrides or {}))
    committee = create_committee(event["id"])
    membership = invite_member(committee["id"], chair["id"], role="CHAIR")
    membership = accept_membership(membership["id"], chair["id"])
    return {
        "event": current_event(event["id"]),
        "committee": committee,
        "chair": chair,
        "membership": membership,
    }


def setup_committee_formed_event(event_overrides=None, chair_overrides=None) -> dict:
    """Event walked to COMMITTEE_FORMED with one ACTIVE CHAIR."""
    ctx = setup_event_with_chair(event_overrides, chair_overrides)
    get_success_data(api_client.form_committee(ctx["event"]["id"], STAFF))
    ctx["event"] = current_event(ctx["event"]["id"])
    return ctx


def setup_open_event(
    event_overrides=None,
    tier_overrides=None,
    clock_iso: str = None,
) -> dict:
    """Full chain to OPEN_FOR_REGISTRATION with one ticket tier.

    The clock is moved to `clock_iso` (if given) BEFORE open-registration so
    the tier's sales window covers the current logical clock. The tier's
    window must contain both `clock_iso` and any later registration time the
    test uses.

    Returns dict(event, committee, chair, membership, tier).
    """
    ctx = setup_committee_formed_event(event_overrides)
    tier = create_tier(ctx["event"]["id"], **(tier_overrides or {}))
    if clock_iso is not None:
        set_clock(clock_iso)
    get_success_data(api_client.open_registration(ctx["event"]["id"], STAFF))
    ctx["event"] = current_event(ctx["event"]["id"])
    ctx["tier"] = tier
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — gift campaign lifecycles
# ---------------------------------------------------------------------------

def setup_active_campaign(
    event_overrides=None,
    campaign_overrides=None,
    chair_overrides=None,
) -> dict:
    """Milestone event with an ACTIVE gift campaign.

    Follows the PRD campaign setup path: event (created while the logical
    clock reads 2026, so class_year 2001 yields milestone_year 25) +
    committee with an ACTIVE CHAIR, then campaign create + activate.

    Returns dict(event, committee, chair, membership, campaign).
    """
    ctx = setup_event_with_chair(event_overrides, chair_overrides)
    resp = api_client.create_campaign(
        ctx["event"]["id"], create_campaign_payload(**(campaign_overrides or {})), STAFF
    )
    campaign = get_success_data(resp)
    campaign = get_success_data(api_client.activate_campaign(campaign["id"], STAFF))
    ctx["campaign"] = campaign
    return ctx


def create_pledge_as_alumni(campaign_id: str, alumni_id: str, amount_cents: int) -> dict:
    """Create a pledge as the pledging alumnus themself."""
    resp = api_client.create_pledge(
        campaign_id,
        create_pledge_payload(alumni_id, amount_cents),
        make_alumni_headers(alumni_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4 — lost-alumni research lifecycles
# ---------------------------------------------------------------------------

def setup_lost_record(record_overrides=None) -> dict:
    """Create a record and mark it LOST. Returns the LOST record."""
    record = create_record(**(record_overrides or {}))
    return get_success_data(api_client.mark_lost(record["id"], STAFF))


def setup_research_case(case_overrides=None, record_overrides=None) -> dict:
    """LOST record + OPEN research case. Returns dict(record, case)."""
    record = setup_lost_record(record_overrides)
    resp = api_client.create_research_case(
        create_research_case_payload(record["id"], **(case_overrides or {})), STAFF
    )
    return {"record": record, "case": get_success_data(resp)}


def setup_case_in_state(target_state: str, case_overrides=None, record_overrides=None) -> dict:
    """Walk a research case to LEAD_LOGGED or VERIFIED.

    Returns dict(record, case) with the case in `target_state`.
    """
    ctx = setup_research_case(case_overrides, record_overrides)
    case = ctx["case"]
    if target_state in ("LEAD_LOGGED", "VERIFIED"):
        case = get_success_data(
            api_client.log_lead(case["id"], create_log_lead_payload(
                **{k: v for k, v in (case_overrides or {}).items()
                   if k in ("lead_source", "lead_detail", "lead_confidence")}
            ), STAFF)
        )
    if target_state == "VERIFIED":
        case = get_success_data(api_client.verify_case(case["id"], STAFF))
    ctx["case"] = case
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — affinity groups and programs
# ---------------------------------------------------------------------------

def setup_group_with_leader(group_overrides=None, leader_overrides=None) -> dict:
    """ACTIVE AffinityGroup + an ACTIVE alumnus to lead programs.

    Returns dict(group, leader).
    """
    leader = create_record(**(leader_overrides or {}))
    resp = api_client.create_group(create_group_payload(**(group_overrides or {})), STAFF)
    return {"group": get_success_data(resp), "leader": leader}


def create_program_as_leader(group_id: str, leader_id: str, **overrides) -> dict:
    resp = api_client.create_program(
        group_id,
        create_program_payload(leader_id, **overrides),
        make_affinity_group_leader_headers(leader_id),
    )
    return get_success_data(resp)


def propose_program_as_leader(program_id: str, leader_id: str) -> dict:
    return get_success_data(
        api_client.propose_program(program_id, make_affinity_group_leader_headers(leader_id))
    )


def setup_proposed_program(group_overrides=None, program_overrides=None) -> dict:
    """Group + leader + one program walked DRAFT -> PROPOSED.

    Returns dict(group, leader, program).
    """
    ctx = setup_group_with_leader(group_overrides)
    program = create_program_as_leader(
        ctx["group"]["id"], ctx["leader"]["id"], **(program_overrides or {})
    )
    program = propose_program_as_leader(program["id"], ctx["leader"]["id"])
    ctx["program"] = program
    return ctx


def setup_approved_program(group_overrides=None, program_overrides=None) -> dict:
    """Group + leader + one program walked to APPROVED (budget committed)."""
    ctx = setup_proposed_program(group_overrides, program_overrides)
    program = get_success_data(api_client.approve_program(ctx["program"]["id"], STAFF))
    ctx["program"] = program
    return ctx


# ---------------------------------------------------------------------------
# Publications
# ---------------------------------------------------------------------------

def create_publication_for_event(event_id: str, **overrides) -> dict:
    resp = api_client.create_publication(
        event_id, create_publication_payload(**overrides), STAFF
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Communication preferences
# ---------------------------------------------------------------------------

def create_preference_for_record(record_id: str, channel: str = "EMAIL", opt_in: bool = True) -> dict:
    resp = api_client.create_preference(
        record_id, create_preference_payload(channel, opt_in=opt_in), STAFF
    )
    return get_success_data(resp)


def get_preference(record_id: str, preference_id: str) -> dict:
    """Read one preference row back via the record's preference list."""
    data, _meta = _list_preferences(record_id)
    for row in data:
        if row["id"] == preference_id:
            return row
    raise AssertionError(
        f"Setup failed: preference {preference_id} not present on record {record_id}"
    )


def _list_preferences(record_id: str):
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_preferences(record_id, STAFF)
    return validate_paginated(resp)
