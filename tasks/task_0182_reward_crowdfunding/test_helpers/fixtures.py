"""Composite setup helpers for the Reward Crowdfunding domain.

Every fixture builds its preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the server (empty database) before every test.

Fixtures use get_success_data() (lenient) so setup failures surface as clear "Setup failed"
errors. Ownership-gated calls thread the real entity id through make_creator_headers /
make_backer_headers per PRD §2.1.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_creator_headers, make_backer_headers
from .factories import (
    create_creator_payload,
    create_backer_payload,
    create_campaign_payload,
    create_tier_payload,
    create_stretch_goal_payload,
    create_addon_product_payload,
    create_pledge_payload,
    attach_addon_payload,
    authorization_payload,
    clock_payload,
)

ADMIN = TEST_USERS["admin_headers"]

# Default clock instants (ISO 8601 UTC, 3 fractional digits).
DEFAULT_LAUNCH_CLOCK = "2026-06-01T00:00:00.000Z"
DEFAULT_DEADLINE = "2026-07-01T00:00:00.000Z"


# --------------------------------------------------------------------------- #
# Tier 0: primitive registration / clock helpers
# --------------------------------------------------------------------------- #
def register_creator(api, payout_currency="USD", display_name="C"):
    """Register a Creator. Returns the creator dict."""
    return get_success_data(
        api.create_creator(create_creator_payload(display_name=display_name, payout_currency=payout_currency), ADMIN)
    )


def register_backer(api, email="b@x.com", display_name="B"):
    """Register a Backer. Returns the backer dict."""
    return get_success_data(api.create_backer(create_backer_payload(email=email, display_name=display_name), ADMIN))


def set_clock(api, now_utc):
    """Set the server clock (no auto-close)."""
    return api.set_clock(clock_payload(now_utc), ADMIN)


def advance_clock(api, now_utc):
    """Advance the clock, auto-closing any due LIVE campaign."""
    return api.advance_clock(clock_payload(now_utc), ADMIN)


# --------------------------------------------------------------------------- #
# Tier 1: campaign skeleton + state progression
# --------------------------------------------------------------------------- #
def create_draft_campaign(
    api,
    creator=None,
    funding_model="FLEXIBLE",
    funding_goal_cents=1000,
    deadline_utc=DEFAULT_DEADLINE,
    title="Camp",
    set_clock_to=DEFAULT_LAUNCH_CLOCK,
):
    """Register a creator (if not supplied), set the clock, create a DRAFT campaign.

    Returns (creator, campaign).
    """
    if set_clock_to is not None:
        set_clock(api, set_clock_to)
    if creator is None:
        creator = register_creator(api)
    creator_headers = make_creator_headers(creator["id"])
    campaign = get_success_data(
        api.create_campaign(
            create_campaign_payload(
                creator["id"],
                title=title,
                funding_model=funding_model,
                funding_goal_cents=funding_goal_cents,
                deadline_utc=deadline_utc,
            ),
            creator_headers,
        )
    )
    return creator, campaign


def add_tier(api, creator, campaign, **tier_overrides):
    """Create a reward tier on a DRAFT campaign (owner-scoped). Returns the tier dict."""
    creator_headers = make_creator_headers(creator["id"])
    return get_success_data(
        api.create_tier(campaign["id"], create_tier_payload(**tier_overrides), creator_headers)
    )


def add_stretch_goal(api, creator, campaign, threshold_cents, **overrides):
    """Create a stretch goal on a DRAFT campaign. Returns the stretch-goal dict."""
    creator_headers = make_creator_headers(creator["id"])
    return get_success_data(
        api.create_stretch_goal(
            campaign["id"], create_stretch_goal_payload(threshold_cents, **overrides), creator_headers
        )
    )


def add_addon_product(api, creator, campaign, **overrides):
    """Create an add-on product (DRAFT or LIVE). Returns the add-on dict."""
    creator_headers = make_creator_headers(creator["id"])
    return get_success_data(
        api.create_addon_product(campaign["id"], create_addon_product_payload(**overrides), creator_headers)
    )


def launch_campaign(api, creator, campaign):
    """Launch a DRAFT campaign to LIVE (owner-scoped). Returns the launched campaign dict."""
    creator_headers = make_creator_headers(creator["id"])
    return get_success_data(api.launch_campaign(campaign["id"], creator_headers))


def create_live_campaign_with_tier(
    api,
    funding_model="FLEXIBLE",
    funding_goal_cents=1000,
    deadline_utc=DEFAULT_DEADLINE,
    tier_overrides=None,
    set_clock_to=DEFAULT_LAUNCH_CLOCK,
):
    """Active (LIVE) campaign with exactly one reward tier.

    Returns (creator, campaign, tier) where campaign reflects post-launch state (version bumped).
    """
    creator, campaign = create_draft_campaign(
        api,
        funding_model=funding_model,
        funding_goal_cents=funding_goal_cents,
        deadline_utc=deadline_utc,
        set_clock_to=set_clock_to,
    )
    tier = add_tier(api, creator, campaign, **(tier_overrides or {}))
    launched = launch_campaign(api, creator, campaign)
    return creator, launched, tier


# --------------------------------------------------------------------------- #
# Tier 2: pledges
# --------------------------------------------------------------------------- #
def create_pledge(
    api,
    campaign,
    backer,
    tier,
    expected_campaign_version,
    pledge_amount_cents=5000,
    destination_zone="DOMESTIC",
):
    """Create a single pledge against a LIVE campaign. Returns the pledge dict."""
    backer_headers = make_backer_headers(backer["id"])
    return get_success_data(
        api.create_pledge(
            campaign["id"],
            create_pledge_payload(
                backer["id"],
                tier["id"],
                expected_campaign_version,
                pledge_amount_cents=pledge_amount_cents,
                destination_zone=destination_zone,
            ),
            backer_headers,
        )
    )


def queue_authorization(api, pledge, outcome):
    """Queue a simulated processor outcome (SUCCEEDED|DECLINED) for a pledge."""
    return get_success_data(api.queue_authorization(pledge["id"], authorization_payload(outcome), ADMIN))


def attach_addon_line(api, backer, pledge, addon, quantity):
    """Attach an add-on line to a pledge (backer-owned). Returns the pledge add-on line dict."""
    backer_headers = make_backer_headers(backer["id"])
    return get_success_data(
        api.attach_addon(pledge["id"], attach_addon_payload(addon["id"], quantity), backer_headers)
    )


# --------------------------------------------------------------------------- #
# Tier 3 / 4: full lifecycle through close (settlement)
# --------------------------------------------------------------------------- #
def setup_live_campaign_with_authorized_pledges(
    api,
    funding_model="FLEXIBLE",
    funding_goal_cents=1000,
    deadline_utc=DEFAULT_DEADLINE,
    tier_overrides=None,
    pledge_specs=None,
    set_clock_to=DEFAULT_LAUNCH_CLOCK,
):
    """Build a LIVE campaign with a set of pledges, each carrying a queued authorization.

    pledge_specs: list of dicts, each like
        {"amount": 5000, "zone": "DOMESTIC", "outcome": "SUCCEEDED"}
    A fresh backer is registered per pledge. The campaign is NOT yet closed.

    Returns (creator, campaign, tier, backers, pledges).
    """
    if pledge_specs is None:
        pledge_specs = [{"amount": 5000, "zone": "DOMESTIC", "outcome": "SUCCEEDED"}]
    creator, campaign, tier = create_live_campaign_with_tier(
        api,
        funding_model=funding_model,
        funding_goal_cents=funding_goal_cents,
        deadline_utc=deadline_utc,
        tier_overrides=tier_overrides,
        set_clock_to=set_clock_to,
    )
    current_version = campaign["version"]
    backers = []
    pledges = []
    for i, spec in enumerate(pledge_specs):
        backer = register_backer(api, email=f"b{i}@x.com", display_name=f"B{i}")
        pledge = create_pledge(
            api,
            campaign,
            backer,
            tier,
            current_version,
            pledge_amount_cents=spec.get("amount", 5000),
            destination_zone=spec.get("zone", "DOMESTIC"),
        )
        # The campaign version advances by one on each successful pledge create.
        current_version = pledge["version"] if "version" in pledge else current_version
        # Re-read the campaign version to thread the next OCC token deterministically.
        camp_now = get_success_data(api.get_campaign(campaign["id"], ADMIN))
        current_version = camp_now["version"]
        backers.append(backer)
        pledges.append(pledge)
        if spec.get("outcome") is not None:
            queue_authorization(api, pledge, spec["outcome"])
    return creator, campaign, tier, backers, pledges


def close_campaign_via_advance(api, campaign, deadline_utc=DEFAULT_DEADLINE):
    """Advance the clock to/past the deadline, triggering the settlement cascade.

    Returns the post-close campaign dict.
    """
    advance_clock(api, deadline_utc)
    return get_success_data(api.get_campaign(campaign["id"], ADMIN))


def setup_successful_campaign(
    api,
    funding_model="FLEXIBLE",
    funding_goal_cents=1000,
    pledge_specs=None,
    deadline_utc=DEFAULT_DEADLINE,
):
    """Full lifecycle to a SUCCESSFUL campaign with captured pledges.

    Returns (creator, campaign_after_close, tier, backers, pledges).
    """
    if pledge_specs is None:
        pledge_specs = [{"amount": 5000, "zone": "DOMESTIC", "outcome": "SUCCEEDED"}]
    creator, campaign, tier, backers, pledges = setup_live_campaign_with_authorized_pledges(
        api,
        funding_model=funding_model,
        funding_goal_cents=funding_goal_cents,
        deadline_utc=deadline_utc,
        pledge_specs=pledge_specs,
    )
    closed = close_campaign_via_advance(api, campaign, deadline_utc=deadline_utc)
    return creator, closed, tier, backers, pledges
