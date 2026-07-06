"""Composite setup helpers — build tests' preconditions from scratch."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    member_payload, admin_adjust_payload,
    skill_offer_payload, skill_request_payload, exchange_payload,
    credential_payload, group_project_payload, project_shift_payload,
    dispute_payload, dispute_resolve_payload,
)
from .test_users import (
    TEST_USERS, make_member_headers, make_organizer_headers, make_admin_headers,
)


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> None:
    """Set the platform's logical clock via PlatformAdmin."""
    resp = api_client.set_clock(to_iso8601, headers=TEST_USERS["admin_headers"])
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 — Basic entity creation
# ---------------------------------------------------------------------------

def create_member(email_prefix: str = "m", home_neighborhood: str = "NW-01") -> dict:
    """Create a Member via POST /members as Anonymous. Returns the member dict."""
    payload = member_payload(email_prefix=None)
    # Give the caller a stable email prefix if desired.
    if email_prefix:
        # Merge in a caller-specified prefix but keep a random suffix to stay unique.
        import uuid as _uuid
        payload["email"] = f"{email_prefix}-{_uuid.uuid4().hex[:6]}@example.com"
    payload["home_neighborhood"] = home_neighborhood
    resp = api_client.create_member(payload, headers=TEST_USERS["anonymous_headers"])
    return get_success_data(resp)


def seed_balance(member_id: str, delta_minutes: int, memo: str = "seed balance") -> dict:
    """Post a PlatformAdmin admin-adjustment to seed a member's balance."""
    resp = api_client.admin_adjust_ledger(
        admin_adjust_payload(member_id, delta_minutes, memo),
        headers=TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def create_offer(provider: dict, **overrides) -> dict:
    """Create a SkillOffer owned by the given provider Member."""
    resp = api_client.create_skill_offer(
        skill_offer_payload(provider["id"], **overrides),
        headers=make_member_headers(provider["id"]),
    )
    return get_success_data(resp)


def create_request(requester: dict, **overrides) -> dict:
    """Create a SkillRequest owned by the given requester Member."""
    resp = api_client.create_skill_request(
        skill_request_payload(requester["id"], **overrides),
        headers=make_member_headers(requester["id"]),
    )
    return get_success_data(resp)


def create_exchange(requester: dict, offer: dict, request: dict, **overrides) -> dict:
    """Create an Exchange as the requester Member. Requester owns the request row."""
    resp = api_client.create_exchange(
        exchange_payload(offer["id"], request["id"], **overrides),
        headers=make_member_headers(requester["id"]),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2 — Common preambles
# ---------------------------------------------------------------------------

def setup_two_members_and_offer(requester_seed: int = 240, offer_minutes: int = 60,
                                clock: str = "2026-03-01T09:00:00Z",
                                required_trust_tier: str = None) -> dict:
    """Boot clock, create requester + provider, seed requester, create one offer.

    Returns {'requester', 'provider', 'offer'} — no request yet, no exchange yet.
    """
    set_clock(clock)
    requester = create_member(email_prefix="req")
    provider = create_member(email_prefix="prov")
    if requester_seed:
        seed_balance(requester["id"], requester_seed, memo="fixture seed")
    offer_overrides = {"minutes_per_session": offer_minutes}
    if required_trust_tier is not None:
        offer_overrides["required_trust_tier"] = required_trust_tier
    offer = create_offer(provider, **offer_overrides)
    return {"requester": requester, "provider": provider, "offer": offer}


def setup_scheduled_exchange(committed_minutes: int = 60,
                             scheduled_start: str = "2026-03-05T10:00:00Z",
                             earliest: str = "2026-03-05T10:00:00Z",
                             latest: str = "2026-03-05T18:00:00Z",
                             requester_seed: int = 240,
                             clock: str = "2026-03-01T09:00:00Z") -> dict:
    """Full preamble to a SCHEDULED exchange. Returns
    {'requester', 'provider', 'offer', 'request', 'exchange'}."""
    ctx = setup_two_members_and_offer(
        requester_seed=requester_seed,
        offer_minutes=committed_minutes,
        clock=clock,
    )
    request = create_request(
        ctx["requester"],
        skill_code="GARDENING",
        needed_minutes=committed_minutes,
        earliest_start_utc=earliest,
        latest_start_utc=latest,
    )
    exchange = create_exchange(
        ctx["requester"], ctx["offer"], request,
        scheduled_start_utc=scheduled_start,
        committed_minutes=committed_minutes,
    )
    return {**ctx, "request": request, "exchange": exchange}


def setup_delivered_exchange(committed_minutes: int = 60,
                             scheduled_start: str = "2026-03-05T10:00:00Z",
                             deliver_at: str = "2026-03-05T11:30:00Z",
                             earliest: str = "2026-03-05T10:00:00Z",
                             latest: str = "2026-03-05T18:00:00Z",
                             requester_seed: int = 240,
                             clock: str = "2026-03-01T09:00:00Z") -> dict:
    """Take an exchange to DELIVERED. Same return shape as setup_scheduled_exchange."""
    ctx = setup_scheduled_exchange(
        committed_minutes=committed_minutes,
        scheduled_start=scheduled_start,
        earliest=earliest, latest=latest,
        requester_seed=requester_seed, clock=clock,
    )
    set_clock(deliver_at)
    resp = api_client.mark_exchange_delivered(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["provider"]["id"]),
    )
    ctx["exchange"] = get_success_data(resp)
    return ctx


def setup_settled_exchange(committed_minutes: int = 60,
                           scheduled_start: str = "2026-03-05T10:00:00Z",
                           settle_at: str = "2026-03-05T11:30:00Z",
                           earliest: str = "2026-03-05T10:00:00Z",
                           latest: str = "2026-03-05T18:00:00Z",
                           requester_seed: int = 240,
                           clock: str = "2026-03-01T09:00:00Z") -> dict:
    """Drive an exchange to SETTLED. Same return shape as setup_scheduled_exchange."""
    ctx = setup_delivered_exchange(
        committed_minutes=committed_minutes,
        scheduled_start=scheduled_start,
        deliver_at=settle_at,
        earliest=earliest, latest=latest,
        requester_seed=requester_seed, clock=clock,
    )
    resp = api_client.settle_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    ctx["exchange"] = get_success_data(resp)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — Project scaffolding
# ---------------------------------------------------------------------------

def create_project(organizer: dict, **overrides) -> dict:
    """Create a GroupProject as the organizer Member."""
    resp = api_client.create_group_project(
        group_project_payload(organizer["id"], **overrides),
        headers=make_organizer_headers(organizer["id"]),
    )
    return get_success_data(resp)


def create_shift(organizer: dict, project: dict, **overrides) -> dict:
    resp = api_client.create_project_shift(
        project["id"],
        project_shift_payload(**overrides),
        headers=make_organizer_headers(organizer["id"]),
    )
    return get_success_data(resp)


def publish_project(organizer: dict, project: dict) -> dict:
    resp = api_client.publish_group_project(
        project["id"], headers=make_organizer_headers(organizer["id"]),
    )
    return get_success_data(resp)


def assign_member_to_shift(member: dict, shift: dict) -> dict:
    resp = api_client.create_shift_assignment(
        shift["id"], {"member_id": member["id"]},
        headers=make_member_headers(member["id"]),
    )
    return get_success_data(resp)


def setup_published_project_with_shift(shift_start: str = "2026-03-05T09:00:00Z",
                                       duration_minutes: int = 60,
                                       capacity: int = 1,
                                       window_start: str = "2026-03-05T09:00:00Z",
                                       window_end: str = "2026-03-05T17:00:00Z",
                                       clock: str = "2026-03-01T09:00:00Z") -> dict:
    """Return {'organizer', 'volunteer', 'project', 'shift'}. Project is OPEN."""
    set_clock(clock)
    organizer = create_member(email_prefix="org")
    volunteer = create_member(email_prefix="vol")
    project = create_project(
        organizer,
        title="Fixture Project",
        window_start_utc=window_start,
        window_end_utc=window_end,
    )
    shift = create_shift(
        organizer, project,
        role_label="PACKER",
        shift_start_utc=shift_start,
        duration_minutes=duration_minutes,
        capacity=capacity,
    )
    project = publish_project(organizer, project)
    return {"organizer": organizer, "volunteer": volunteer,
            "project": project, "shift": shift}


def setup_member_with_two_prior_noshows() -> dict:
    """Build a member with exactly 2 NO_SHOW strikes in the last 90 days.

    Returns {'organizer', 'member', 'project', 'strike_shifts', 'reserve_shift'}.
    The member has 2 NO_SHOWs and no_show_strikes==2 and is_suspended==false;
    reserve_shift is a pre-created third shift at 2026-03-05T09:00 that
    consumers can use to drive to the third strike, or leave assigned/cancelled.
    Additional shifts (sh_extra1, sh_extra2) are pre-created for consumers
    that need future-dated shifts.
    """
    set_clock("2026-03-01T09:00:00Z")
    organizer = create_member(email_prefix="org")
    member = create_member(email_prefix="vol")

    project = create_project(
        organizer, title="Strike scaffold",
        window_start_utc="2026-03-02T09:00:00Z",
        window_end_utc="2026-03-31T17:00:00Z",
    )
    sh1 = create_shift(organizer, project,
                       role_label="P",
                       shift_start_utc="2026-03-02T09:00:00Z",
                       duration_minutes=60, capacity=1)
    sh2 = create_shift(organizer, project,
                       role_label="P",
                       shift_start_utc="2026-03-03T09:00:00Z",
                       duration_minutes=60, capacity=1)
    # Pre-create the shifts consumers might want to reach the 3rd strike
    # from PLANNING → OPEN — this avoids relying on an implementer allowing
    # POST /group-projects/{id}/shifts on an OPEN project.
    reserve_shift = create_shift(organizer, project,
                                 role_label="P",
                                 shift_start_utc="2026-03-05T09:00:00Z",
                                 duration_minutes=60, capacity=1)
    sh_extra1 = create_shift(organizer, project,
                             role_label="P",
                             shift_start_utc="2026-03-06T09:00:00Z",
                             duration_minutes=60, capacity=1)
    sh_extra2 = create_shift(organizer, project,
                             role_label="P",
                             shift_start_utc="2026-03-10T09:00:00Z",
                             duration_minutes=60, capacity=1)
    publish_project(organizer, project)
    assign_member_to_shift(member, sh1)
    assign_member_to_shift(member, sh2)
    set_clock("2026-03-02T10:30:00Z")
    set_clock("2026-03-03T10:30:00Z")
    return {"organizer": organizer, "member": member, "project": project,
            "strike_shifts": [sh1, sh2],
            "reserve_shift": reserve_shift,
            "sh_extra1": sh_extra1,
            "sh_extra2": sh_extra2}


def setup_suspended_member() -> dict:
    """Build a member with 3 NO_SHOW strikes → is_suspended==true.

    Returns {'organizer', 'member', 'project', 'sh_extra1', 'sh_extra2'}.
    """
    ctx = setup_member_with_two_prior_noshows()
    # Third strike — reserve_shift starts 2026-03-05T09:00, duration 60 min.
    assign_member_to_shift(ctx["member"], ctx["reserve_shift"])
    set_clock("2026-03-05T10:30:00Z")
    return {"organizer": ctx["organizer"],
            "member": ctx["member"],
            "project": ctx["project"],
            "sh_extra1": ctx["sh_extra1"],
            "sh_extra2": ctx["sh_extra2"]}


# ---------------------------------------------------------------------------
# Tier 4 — Disputes
# ---------------------------------------------------------------------------

def setup_disputed_exchange(claimed_delta_minutes: int = 15,
                            reason_code: str = "INCOMPLETE_SERVICE",
                            committed_minutes: int = 60) -> dict:
    """Drive to DELIVERED, then file a dispute (Exchange -> DISPUTED, Dispute OPEN).
    Returns {..., 'dispute'} on top of the setup_delivered_exchange shape."""
    ctx = setup_delivered_exchange(committed_minutes=committed_minutes)
    resp = api_client.create_dispute(
        dispute_payload(
            ctx["exchange"]["id"],
            ctx["requester"]["id"],
            reason_code=reason_code,
            claimed_delta_minutes=claimed_delta_minutes,
        ),
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    dispute = get_success_data(resp)
    # Refresh exchange status
    resp2 = api_client.get_exchange(
        ctx["exchange"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    ctx["exchange"] = get_success_data(resp2)
    ctx["dispute"] = dispute
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — Redemption
# ---------------------------------------------------------------------------

def read_member(member_id: str, headers: dict = None) -> dict:
    if headers is None:
        headers = make_admin_headers()
    resp = api_client.get_member(member_id, headers=headers)
    return get_success_data(resp)
