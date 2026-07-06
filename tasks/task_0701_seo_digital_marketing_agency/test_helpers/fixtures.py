"""Composite setup helpers.

Each helper drives the API through the multi-step preambles that the difficulty
and corner test scenarios share, returning the created resources so tests can
focus on the assertion under examination.

The test harness resets the database before every test, so every fixture builds
its entire precondition state from scratch using only PRD-declared endpoints.

Setup calls use get_success_data() (lenient 2xx validator) so a broken precondition
surfaces as a clear "Setup failed" rather than a confusing assertion failure.

Identity threading: Client is entity_backed, so Client-role calls that are
ownership-gated (sign / approve / request_revision / withdraw) use
make_client_headers(client_id) with the real client id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers
from . import factories


ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]

DEFAULT_CLOCK = "2026-04-10T00:00:00Z"
DEFAULT_SPRINT_START = "2026-04-01T00:00:00Z"
DEFAULT_SPRINT_END = "2026-05-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Advance the logical clock to a known instant (AgencyAdmin)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: onboarding state progression
# ---------------------------------------------------------------------------
def create_prospect_client(**overrides) -> dict:
    """Create a PROSPECT client (no reseller). Returns the client."""
    payload = factories.create_client_payload(**overrides)
    return get_success_data(api_client.create_client(payload, ADMIN))


def create_audited_client(audit_scores=None, **client_overrides) -> dict:
    """Create a client and record one audit -> AUDITED. Returns the client (re-read)."""
    client = create_prospect_client(**client_overrides)
    scores = audit_scores or {}
    audit_payload = factories.create_audit_payload(**scores)
    get_success_data(api_client.create_audit(client["id"], audit_payload, ADMIN))
    return get_success_data(api_client.get_client(client["id"], ADMIN))


def create_reseller(**overrides) -> dict:
    """Create a reseller (AgencyAdmin). Returns the reseller."""
    payload = factories.create_reseller_payload(**overrides)
    return get_success_data(api_client.create_reseller(payload, ADMIN))


def create_audited_client_with_draft_retainer(
    client_overrides=None, retainer_overrides=None, audit_scores=None
):
    """AUDITED client + a DRAFT retainer. Returns (client, retainer)."""
    client = create_audited_client(audit_scores=audit_scores, **(client_overrides or {}))
    ret_payload = factories.create_retainer_payload(
        client_id=client["id"], **(retainer_overrides or {})
    )
    retainer = get_success_data(api_client.create_retainer(ret_payload, ADMIN))
    return client, retainer


def create_active_client_with_active_retainer(
    client_overrides=None, retainer_overrides=None, audit_scores=None
):
    """ACTIVE client (bubbled up) + ACTIVE retainer.

    Returns (client, retainer) both re-read after activation.
    """
    client, retainer = create_audited_client_with_draft_retainer(
        client_overrides, retainer_overrides, audit_scores
    )
    retainer = get_success_data(api_client.activate_retainer(retainer["id"], ADMIN))
    client = get_success_data(api_client.get_client(client["id"], ADMIN))
    return client, retainer


# ---------------------------------------------------------------------------
# Tier 2: sprint + deliverable scaffolding
# ---------------------------------------------------------------------------
def create_active_sprint(client_id, retainer_id, **sprint_overrides) -> dict:
    """Create a sprint and start it (PLANNING -> ACTIVE). Returns the sprint."""
    payload = factories.create_sprint_payload(
        client_id=client_id, retainer_id=retainer_id, **sprint_overrides
    )
    sprint = get_success_data(api_client.create_sprint(payload, AM))
    sprint = get_success_data(api_client.start_sprint(sprint["id"], AM))
    return sprint


def setup_client_retainer_active_sprint(
    clock=DEFAULT_CLOCK,
    retainer_overrides=None,
    sprint_overrides=None,
    client_overrides=None,
):
    """Most common composite: clock set, ACTIVE client + ACTIVE retainer + ACTIVE sprint.

    Returns (client, retainer, sprint). Re-reads the retainer after sprint start so
    the caller has the current retainer version (sprint start does not bump it).
    """
    if clock is not None:
        set_clock(clock)
    client, retainer = create_active_client_with_active_retainer(
        client_overrides=client_overrides, retainer_overrides=retainer_overrides
    )
    sprint = create_active_sprint(
        client["id"], retainer["id"], **(sprint_overrides or {})
    )
    retainer = get_success_data(api_client.get_retainer(retainer["id"], ADMIN))
    return client, retainer, sprint


def create_draft_deliverable(client_id, retainer_id, sprint_id, **overrides) -> dict:
    """Create a DRAFT deliverable. Returns the deliverable."""
    payload = factories.create_deliverable_payload(
        client_id=client_id, retainer_id=retainer_id, sprint_id=sprint_id, **overrides
    )
    return get_success_data(api_client.create_deliverable(payload, AM))


def create_assigned_deliverable(
    client_id, retainer_id, sprint_id, deliverable_overrides=None
):
    """Create a DRAFT deliverable and assign it (reserves credits).

    Reads the retainer for the current version, passes it as expected_retainer_version.
    Returns (deliverable, retainer) both re-read after assign.
    """
    deliverable = create_draft_deliverable(
        client_id, retainer_id, sprint_id, **(deliverable_overrides or {})
    )
    retainer = get_success_data(api_client.get_retainer(retainer_id, ADMIN))
    deliverable = get_success_data(
        api_client.assign_deliverable(
            deliverable["id"],
            {"expected_retainer_version": retainer["version"]},
            AM,
        )
    )
    retainer = get_success_data(api_client.get_retainer(retainer_id, ADMIN))
    return deliverable, retainer


def create_in_review_deliverable(
    client_id, retainer_id, sprint_id, deliverable_overrides=None
):
    """Drive a deliverable DRAFT -> ASSIGNED -> IN_PROGRESS -> IN_REVIEW.

    Returns (deliverable, retainer) re-read after the deliverable reaches IN_REVIEW.
    """
    deliverable, _ = create_assigned_deliverable(
        client_id, retainer_id, sprint_id, deliverable_overrides
    )
    get_success_data(api_client.start_deliverable(deliverable["id"], AM))
    deliverable = get_success_data(api_client.submit_deliverable(deliverable["id"], AM))
    retainer = get_success_data(api_client.get_retainer(retainer_id, ADMIN))
    return deliverable, retainer


# ---------------------------------------------------------------------------
# Tier 3: ad campaign scaffolding
# ---------------------------------------------------------------------------
def create_live_campaign(client_id, retainer_id, **campaign_overrides) -> dict:
    """Create an ad campaign and launch it (DRAFT -> LIVE). Returns the campaign."""
    payload = factories.create_ad_campaign_payload(
        client_id=client_id, retainer_id=retainer_id, **campaign_overrides
    )
    campaign = get_success_data(api_client.create_ad_campaign(payload, AM))
    campaign = get_success_data(api_client.launch_ad_campaign(campaign["id"], AM))
    return campaign


def setup_live_campaign_with_spend(
    spend_cents, campaign_overrides=None, client_overrides=None, retainer_overrides=None
):
    """Direct ACTIVE client + ACTIVE retainer + LIVE campaign with recorded spend.

    Returns (client, retainer, campaign) with the campaign re-read after the spend.
    """
    client, retainer = create_active_client_with_active_retainer(
        client_overrides=client_overrides, retainer_overrides=retainer_overrides
    )
    campaign = create_live_campaign(
        client["id"], retainer["id"], **(campaign_overrides or {})
    )
    campaign = get_success_data(
        api_client.record_spend(campaign["id"], {"amount_cents": spend_cents}, AM)
    )
    return client, retainer, campaign


def setup_dispute_under_review(
    disputed_cents, spend_cents, campaign_overrides=None
):
    """Direct ACTIVE client + LIVE campaign with spend + a dispute moved to UNDER_REVIEW.

    Returns (client, retainer, campaign, dispute) with the dispute re-read after review.
    """
    client, retainer, campaign = setup_live_campaign_with_spend(
        spend_cents, campaign_overrides=campaign_overrides
    )
    dispute = get_success_data(
        api_client.create_dispute(
            factories.create_dispute_payload(
                ad_campaign_id=campaign["id"],
                client_id=client["id"],
                disputed_cents=disputed_cents,
            ),
            AM,
        )
    )
    dispute = get_success_data(api_client.review_dispute(dispute["id"], AM))
    return client, retainer, campaign, dispute


# ---------------------------------------------------------------------------
# Tier 4: keyword + snapshot scaffolding
# ---------------------------------------------------------------------------
def create_tracking_keyword(client_id, **kw_overrides) -> dict:
    """Create a keyword target and activate tracking (PLANNED -> TRACKING).

    Returns the keyword target (re-read after tracking).
    """
    payload = factories.create_keyword_target_payload(
        client_id=client_id, **kw_overrides
    )
    kw = get_success_data(api_client.create_keyword_target(payload, AM))
    kw = get_success_data(api_client.activate_tracking(kw["id"], AM))
    return kw


def add_snapshot(keyword_id, position, organic_traffic, observed_at=None) -> dict:
    """Append a rank snapshot. Returns the snapshot."""
    payload = factories.create_snapshot_payload(
        position=position, organic_traffic=organic_traffic
    )
    if observed_at is not None:
        payload["observed_at"] = observed_at
    return get_success_data(api_client.create_snapshot(keyword_id, payload, AM))


# ---------------------------------------------------------------------------
# Tier 5: contracts
# ---------------------------------------------------------------------------
def create_active_contract(client_id, retainer_id, **contract_overrides) -> dict:
    """Create a contract, sign it (as the owning Client) and activate it.

    Requires the linked retainer to already be ACTIVE.
    Returns the contract (re-read after activation).
    """
    payload = factories.create_contract_payload(
        client_id=client_id, retainer_id=retainer_id, **contract_overrides
    )
    contract = get_success_data(api_client.create_contract(payload, AM))
    get_success_data(
        api_client.sign_contract(contract["id"], make_client_headers(client_id))
    )
    contract = get_success_data(api_client.activate_contract(contract["id"], AM))
    return contract


# ---------------------------------------------------------------------------
# Tier 6: GBP listings
# ---------------------------------------------------------------------------
def create_verified_gbp_listing(client_id, **listing_overrides) -> dict:
    """Create a GBP listing and verify it (UNVERIFIED -> VERIFIED).

    Returns the listing (re-read after verify).
    """
    payload = factories.create_gbp_listing_payload(
        client_id=client_id, **listing_overrides
    )
    listing = get_success_data(api_client.create_gbp_listing(payload, AM))
    listing = get_success_data(api_client.verify_gbp_listing(listing["id"], AM))
    return listing
