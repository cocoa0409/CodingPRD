"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts against
an empty database and the logical clock at 2026-08-01T00:00:00Z). Setup calls
use get_success_data() so failures surface as clear "Setup step failed" errors.

Ownership threading (PRD §2.1): ListingAgent calls on a listing use headers
built from the owning Agent.id via make_listing_agent_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agent_payload,
    create_listing_payload,
    create_media_asset_payload,
    create_portal_account_payload,
    create_feed_subscription_payload,
    create_decision_payload,
    create_showing_window_payload,
    create_feedback_payload,
)
from .test_users import TEST_USERS, make_listing_agent_headers

MC = TEST_USERS["marketing_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]
MD = TEST_USERS["marketing_director_headers"]
PW = TEST_USERS["portal_webhook_headers"]


# ─── Tier 1: single-resource creation ─────────────────

def create_agent(**overrides) -> dict:
    """Create an agent (MarketingDirector-only, PRD §3.1). Returns the Agent."""
    res = api_client.create_agent(create_agent_payload(**overrides), MD)
    return get_success_data(res, 201)


def owner_headers(agent: dict) -> dict:
    """ListingAgent headers bound to this agent's id (ownership-gated calls)."""
    return make_listing_agent_headers(agent["id"])


def create_draft_listing(agent: dict, complete=True, **overrides) -> dict:
    """Create a DRAFT listing owned by `agent`. Returns the Listing."""
    res = api_client.create_listing(
        create_listing_payload(agent["id"], complete=complete, **overrides),
        owner_headers(agent),
    )
    return get_success_data(res, 201)


def create_portal(**overrides) -> dict:
    """Create a portal account (starts ACTIVE, PRD §3.5). Returns the PortalAccount."""
    res = api_client.create_portal_account(create_portal_account_payload(**overrides), MD)
    return get_success_data(res, 201)


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, MD), 200)


def run_sweep() -> dict:
    """Run the operations sweep (PRD §2.4). Returns expired/dispatched/deferred ids."""
    return get_success_data(api_client.run_sweep(MD), 200)


def get_listing(listing_id: str) -> dict:
    return get_success_data(api_client.get_listing(listing_id, MC), 200)


def get_summary(listing_id: str) -> dict:
    return get_success_data(api_client.get_listing_summary(listing_id, MC), 200)


# ─── Tier 2: listing preparation (media + review) ─────

def upload_photo(listing: dict, agent: dict, **overrides) -> dict:
    """Upload a PHOTO asset (starts UPLOADED). Returns the MediaAsset."""
    res = api_client.create_media_asset(
        listing["id"], create_media_asset_payload(kind="PHOTO", **overrides),
        owner_headers(agent),
    )
    return get_success_data(res, 201)


def upload_and_ready_photo(listing: dict, agent: dict, **overrides) -> dict:
    """Upload a PHOTO and mark it READY (auto-primary if first, PRD §3.2)."""
    photo = upload_photo(listing, agent, **overrides)
    res = api_client.mark_media_ready(photo["id"], owner_headers(agent))
    return get_success_data(res, 200)


def create_submittable_listing(agent=None, **listing_overrides):
    """Complete DRAFT listing with one READY PHOTO. Returns (agent, listing, photo)."""
    if agent is None:
        agent = create_agent()
    listing = create_draft_listing(agent, complete=True, **listing_overrides)
    photo = upload_and_ready_photo(listing, agent)
    return agent, listing, photo


def submit_listing(listing: dict, agent: dict) -> dict:
    """Submit for review; returns the PENDING ComplianceReview (PRD §3.3)."""
    res = api_client.submit_review(listing["id"], owner_headers(agent))
    return get_success_data(res, 201)


def approve_review(review: dict) -> dict:
    res = api_client.decide_compliance_review(
        review["id"], create_decision_payload("APPROVED"), CO)
    return get_success_data(res, 200)


def reject_review(review: dict, flagged_terms=("adults only",), notes="revise remarks") -> dict:
    res = api_client.decide_compliance_review(
        review["id"],
        create_decision_payload("REJECTED", flagged_terms=list(flagged_terms), notes=notes),
        CO,
    )
    return get_success_data(res, 200)


# ─── Tier 3: lifecycle shortcuts ──────────────────────

def create_active_listing(agent=None, **listing_overrides):
    """Full intake path: agent -> complete DRAFT -> READY PHOTO -> submit ->
    approve -> activate (PRD §3.1-§3.4). Returns (agent, active_listing)."""
    agent, listing, _photo = create_submittable_listing(agent, **listing_overrides)
    review = submit_listing(listing, agent)
    approve_review(review)
    res = api_client.activate_listing(listing["id"], owner_headers(agent))
    active = get_success_data(res, 200)
    return agent, active


def create_withdrawn_listing(agent=None, **listing_overrides):
    """ACTIVE listing withdrawn at the current clock. Returns (agent, listing)."""
    agent, active = create_active_listing(agent, **listing_overrides)
    res = api_client.withdraw_listing(active["id"], owner_headers(agent))
    return agent, get_success_data(res, 200)


def subscribe_listing(listing: dict, portal: dict) -> dict:
    """Subscribe listing to portal; queues a FULL_SYNC job (PRD §3.5)."""
    res = api_client.create_feed_subscription(
        listing["id"], create_feed_subscription_payload(portal["id"]), MC)
    return get_success_data(res, 201)


def create_syndicated_listing(agent=None, portal_overrides=None, **listing_overrides):
    """ACTIVE listing subscribed to one portal. Returns (agent, listing, portal, sub)."""
    agent, active = create_active_listing(agent, **listing_overrides)
    portal = create_portal(**(portal_overrides or {}))
    sub = subscribe_listing(active, portal)
    return agent, active, portal, sub


# ─── Tier 4: syndication job helpers ──────────────────

def list_jobs_of_subscription(subscription_id: str, params=None) -> list:
    data = get_success_data(
        api_client.list_subscription_jobs(subscription_id, MC, params=params), 200)
    return data


def list_jobs_of_listing(listing_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_listing_feed_events(listing_id, MC, params=params), 200)


def find_job(jobs: list, job_type=None, status=None) -> dict:
    """Pick the single job of a subscription/listing matching type/status."""
    matches = [
        j for j in jobs
        if (job_type is None or j["job_type"] == job_type)
        and (status is None or j["status"] == status)
    ]
    assert matches, f"No job with type={job_type} status={status} in {jobs}"
    return matches[0]


def dispatch_due_jobs() -> dict:
    """Run the sweep; returns its data (dispatched/deferred/expired ids)."""
    return run_sweep()


def dispatch_full_sync(subscription_id: str) -> dict:
    """Sweep, then return the subscription's DISPATCHED FULL_SYNC job."""
    run_sweep()
    return find_job(list_jobs_of_subscription(subscription_id),
                    job_type="FULL_SYNC", status="DISPATCHED")


# ─── Tier 5: showing windows & feedback ───────────────

def create_window(listing: dict, agent: dict, starts_at: str, ends_at: str) -> dict:
    res = api_client.create_showing_window(
        listing["id"], create_showing_window_payload(starts_at, ends_at),
        owner_headers(agent),
    )
    return get_success_data(res, 201)


def submit_feedback(window: dict, agent: dict, rating: int, comment=None) -> dict:
    res = api_client.create_feedback(
        window["id"], create_feedback_payload(rating, comment=comment),
        owner_headers(agent),
    )
    return get_success_data(res, 201)


def create_ended_window(listing: dict, agent: dict,
                        starts_at="2026-08-01T10:00:00Z",
                        ends_at="2026-08-01T11:00:00Z",
                        advance_clock_to="2026-08-01T12:00:00Z") -> dict:
    """Create a showing window, then move the clock at/past its ends_at so
    feedback becomes admissible (PRD §3.8)."""
    window = create_window(listing, agent, starts_at, ends_at)
    if advance_clock_to is not None:
        set_clock(advance_clock_to)
    return window
