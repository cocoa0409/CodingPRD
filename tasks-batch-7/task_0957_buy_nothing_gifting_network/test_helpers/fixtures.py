"""Composite setup helpers for multi-step test prerequisites (PRD §2.5, §3.1–§3.8).

Every fixture builds preconditions from scratch using only PRD-declared
endpoints. Internally fixtures use get_success_data() (lenient validator) so
setup failures surface as clear "Setup failed" assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    create_curb_alert_payload,
    create_gift_post_payload,
    create_group_payload,
    create_member_payload,
    create_membership_payload,
    create_pickup_plan_payload,
    create_report_payload,
    create_wishlist_payload,
    resolve_report_action_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_anonymous_headers,
    make_member_headers,
    make_moderator_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: clock + member basics
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock and run the epoch sweep (PlatformAdmin)."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, make_admin_headers())
    assert res.status_code == 200, f"Setup failed: set_clock -> {res.status_code}: {res.text}"
    return get_success_data(res)


def register_member(email: str, display_name: str = "Member") -> dict:
    """Register a member as Anonymous. Returns the Member dict."""
    res = api_client.create_member(
        create_member_payload(email=email, display_name=display_name),
        make_anonymous_headers(),
    )
    assert res.status_code == 201, f"Setup failed: register {email} -> {res.status_code}: {res.text}"
    return get_success_data(res)


def create_group(name: str, zip_code: str, join_policy: str = "OPEN", capacity: int = 150) -> dict:
    """Create a group as PlatformAdmin. Returns the NeighborhoodGroup dict."""
    res = api_client.create_group(
        create_group_payload(name=name, zip_code=zip_code, join_policy=join_policy,
                             capacity=capacity),
        make_admin_headers(),
    )
    assert res.status_code == 201, f"Setup failed: create group -> {res.status_code}: {res.text}"
    return get_success_data(res)


def join_group(member: dict, group: dict) -> dict:
    """POST /v1/memberships as the member. Returns the GroupMembership dict
    (APPROVED inline for OPEN groups, REQUESTED for APPROVAL_REQUIRED)."""
    res = api_client.create_membership(
        create_membership_payload(group["id"]), make_member_headers(member["id"])
    )
    assert res.status_code == 201, f"Setup failed: join group -> {res.status_code}: {res.text}"
    return get_success_data(res)


def approve_membership_as_admin(membership_id: str, role: str = None) -> dict:
    """Approve a REQUESTED membership as PlatformAdmin, optionally assigning a role."""
    payload = {"role": role} if role else None
    res = api_client.approve_membership(membership_id, make_admin_headers(), payload=payload)
    assert res.status_code == 200, (
        f"Setup failed: approve membership -> {res.status_code}: {res.text}"
    )
    return get_success_data(res)


def setup_group_with_members(
    member_specs,
    name="Group",
    zip_code="98101",
    join_policy="OPEN",
    capacity=150,
    clock="2026-05-10T09:00:00Z",
):
    """Set clock, register members, create group, join all members.

    member_specs: list of (email, display_name) tuples.
    Returns (group, {email: member_dict}).
    """
    if clock is not None:
        set_clock(clock)
    group = create_group(name, zip_code, join_policy=join_policy, capacity=capacity)
    members = {}
    for email, display_name in member_specs:
        m = register_member(email, display_name)
        join_group(m, group)
        members[email] = m
    return group, members


# ---------------------------------------------------------------------------
# Tier 1: gift-post state progression
# ---------------------------------------------------------------------------

def create_post(giver: dict, group: dict, title="Test Item", category="OTHER",
                claim_mode="FIRST_COME", expires_at="2026-06-10T00:00:00Z",
                description=None) -> dict:
    """Create a DRAFT gift post as the giver. Returns the GiftPost dict."""
    overrides = {}
    if description is not None:
        overrides["description"] = description
    res = api_client.create_gift_post(
        create_gift_post_payload(
            group["id"], title=title, category=category, claim_mode=claim_mode,
            expires_at=expires_at, **overrides,
        ),
        make_member_headers(giver["id"]),
    )
    assert res.status_code == 201, f"Setup failed: create post -> {res.status_code}: {res.text}"
    return get_success_data(res)


def publish_post(giver: dict, post: dict) -> dict:
    """Publish a DRAFT post. Returns the OPEN GiftPost dict."""
    res = api_client.publish_gift_post(post["id"], make_member_headers(giver["id"]))
    assert res.status_code == 200, f"Setup failed: publish post -> {res.status_code}: {res.text}"
    return get_success_data(res)


def create_and_publish_post(giver: dict, group: dict, **kwargs) -> dict:
    """Create + publish. Returns the OPEN GiftPost dict."""
    post = create_post(giver, group, **kwargs)
    return publish_post(giver, post)


# ---------------------------------------------------------------------------
# Tier 2: claims
# ---------------------------------------------------------------------------

def create_claim(claimer: dict, post: dict) -> dict:
    """Claim an OPEN post. Returns the Claim dict (OFFERED when head slot vacant
    and mode != GIVER_PICK, else QUEUED)."""
    res = api_client.create_claim(
        {"post_id": post["id"]}, make_member_headers(claimer["id"])
    )
    assert res.status_code == 201, f"Setup failed: claim -> {res.status_code}: {res.text}"
    return get_success_data(res)


def create_accepted_claim(giver: dict, claimer: dict, group: dict, **post_kwargs):
    """Published post + claim + accept. Returns (post, claim)."""
    post = create_and_publish_post(giver, group, **post_kwargs)
    claim = create_claim(claimer, post)
    assert claim["status"] == "OFFERED", (
        f"Setup failed: expected auto-promoted OFFERED claim, got {claim['status']}"
    )
    res = api_client.accept_claim(claim["id"], make_member_headers(claimer["id"]))
    assert res.status_code == 200, f"Setup failed: accept -> {res.status_code}: {res.text}"
    return post, get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 3: pickup plans / full lifecycle
# ---------------------------------------------------------------------------

def create_proposed_plan(proposer: dict, claim: dict,
                         window_start="2026-05-11T10:00:00Z",
                         window_end="2026-05-11T11:00:00Z") -> dict:
    """Propose a pickup plan on an ACCEPTED claim. Returns the PROPOSED plan."""
    res = api_client.create_pickup_plan(
        create_pickup_plan_payload(claim["id"], window_start, window_end),
        make_member_headers(proposer["id"]),
    )
    assert res.status_code == 201, f"Setup failed: create plan -> {res.status_code}: {res.text}"
    return get_success_data(res)


def create_confirmed_plan(giver: dict, claimer: dict, claim: dict,
                          window_start="2026-05-11T10:00:00Z",
                          window_end="2026-05-11T11:00:00Z") -> dict:
    """Giver proposes, claimer confirms. Returns the CONFIRMED plan."""
    plan = create_proposed_plan(giver, claim, window_start, window_end)
    res = api_client.confirm_pickup_plan(plan["id"], make_member_headers(claimer["id"]))
    assert res.status_code == 200, f"Setup failed: confirm plan -> {res.status_code}: {res.text}"
    return get_success_data(res)


def complete_gift_cycle(giver: dict, claimer: dict, group: dict,
                        window_start="2026-05-10T12:00:00Z",
                        window_end="2026-05-10T13:00:00Z",
                        **post_kwargs):
    """Full gift lifecycle: post -> publish -> claim -> accept -> plan -> confirm
    -> complete. Returns (post, claim, plan) with post/claim FULFILLED and plan
    COMPLETED."""
    post, claim = create_accepted_claim(giver, claimer, group, **post_kwargs)
    plan = create_confirmed_plan(giver, claimer, claim, window_start, window_end)
    res = api_client.complete_pickup_plan(plan["id"], make_member_headers(giver["id"]))
    assert res.status_code == 200, f"Setup failed: complete plan -> {res.status_code}: {res.text}"
    plan = get_success_data(res)
    claim = get_success_data(api_client.get_claim(claim["id"], make_member_headers(claimer["id"])))
    post = get_success_data(api_client.get_gift_post(post["id"], make_member_headers(giver["id"])))
    return post, claim, plan


# ---------------------------------------------------------------------------
# Tier 4: moderation / strikes / thresholds
# ---------------------------------------------------------------------------

def file_report(reporter: dict, group: dict, target_id: str, target_type="MEMBER",
                category="SPAM") -> dict:
    """File a report as the reporter. Returns the OPEN Report dict."""
    res = api_client.create_report(
        create_report_payload(group["id"], target_id, target_type=target_type,
                              category=category),
        make_member_headers(reporter["id"]),
    )
    assert res.status_code == 201, f"Setup failed: report -> {res.status_code}: {res.text}"
    return get_success_data(res)


def resolve_with_strike(report: dict, severity_points: int = 1) -> dict:
    """start-review + resolve ACTION/STRIKE as PlatformAdmin. Returns resolved Report."""
    res = api_client.start_review_report(report["id"], make_admin_headers())
    assert res.status_code == 200, (
        f"Setup failed: start-review -> {res.status_code}: {res.text}"
    )
    res = api_client.resolve_report(
        report["id"],
        resolve_report_action_payload(severity_points=severity_points),
        make_admin_headers(),
    )
    assert res.status_code == 200, f"Setup failed: resolve -> {res.status_code}: {res.text}"
    return get_success_data(res)


def apply_strike(reporter: dict, group: dict, target_member: dict, severity_points: int = 1,
                 category="SPAM") -> dict:
    """File a MEMBER report against target_member and resolve it with a STRIKE.
    Returns the resolved Report dict."""
    report = file_report(reporter, group, target_member["id"], target_type="MEMBER",
                         category=category)
    return resolve_with_strike(report, severity_points=severity_points)


def get_member(member_id: str, headers=None) -> dict:
    res = api_client.get_member(member_id, headers or make_member_headers(member_id))
    return get_success_data(res)


def get_post(post_id: str, headers) -> dict:
    return get_success_data(api_client.get_gift_post(post_id, headers))


def get_claim(claim_id: str, headers) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers))


def get_plan(plan_id: str, headers) -> dict:
    return get_success_data(api_client.get_pickup_plan(plan_id, headers))


def find_active_strike_action(member: dict) -> dict:
    """Return the first ACTIVE moderation action for the member (admin listing)."""
    res = api_client.list_moderation_actions(
        make_admin_headers(), params={"member_id": member["id"], "status": "ACTIVE"}
    )
    data = get_success_data(res)
    assert isinstance(data, list) and len(data) >= 1, (
        "Setup failed: no ACTIVE moderation action found for member"
    )
    return data[0]


# ---------------------------------------------------------------------------
# Tier 5: curb alerts
# ---------------------------------------------------------------------------

def create_curb_alert(creator: dict, group: dict, zone="MAPLE",
                      starts_at="2026-05-12T09:00:00Z", ends_at="2026-05-12T10:00:00Z") -> dict:
    res = api_client.create_curb_alert(
        create_curb_alert_payload(group["id"], zone=zone, starts_at=starts_at,
                                  ends_at=ends_at),
        make_member_headers(creator["id"]),
    )
    assert res.status_code == 201, (
        f"Setup failed: curb alert -> {res.status_code}: {res.text}"
    )
    return get_success_data(res)


def create_wishlist(member: dict, group: dict, keyword="chair", category=None) -> dict:
    overrides = {}
    if category is not None:
        overrides["category"] = category
    res = api_client.create_wishlist(
        create_wishlist_payload(group["id"], keyword=keyword, **overrides),
        make_member_headers(member["id"]),
    )
    assert res.status_code == 201, f"Setup failed: wishlist -> {res.status_code}: {res.text}"
    return get_success_data(res)


def make_moderator(member: dict, group: dict) -> dict:
    """Join an APPROVAL_REQUIRED group and get approved with role MODERATOR
    by PlatformAdmin. Returns the APPROVED GroupMembership dict."""
    membership = join_group(member, group)
    assert membership["status"] == "REQUESTED", (
        "Setup failed: moderator bootstrap requires an APPROVAL_REQUIRED group"
    )
    return approve_membership_as_admin(membership["id"], role="MODERATOR")


__all__ = [name for name in dir() if not name.startswith("_")]
