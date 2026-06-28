"""Composite setup helpers for the Creator Membership API.

Because the runner restarts the server (empty DB) before every test, every
fixture builds its preconditions from scratch using only PRD-declared
endpoints. Helpers use get_success_data() (lenient) internally so setup
failures surface as clear "Setup step failed" errors.

Identity threading: Creator and Patron are entity-backed roles. After a fixture
creates a Creator/Patron, every ownership-gated call uses make_creator_headers
/make_patron_headers with that entity's real id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_creator_payload,
    create_tier_payload,
    create_per_creation_tier_payload,
    create_patron_payload,
    create_pledge_payload,
    create_charge_payload,
    create_post_payload,
    create_conversation_payload,
    create_win_back_offer_payload,
    create_payout_payload,
)
from .test_users import (
    make_creator_headers,
    make_patron_headers,
    make_platform_admin_headers,
)

ADMIN = make_platform_admin_headers()


# ---------------------------------------------------------------------------
# Clock control (Tier 1 helper used everywhere time matters)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the logical clock to the given UTC instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Primitive creators / patrons / tiers
# ---------------------------------------------------------------------------
def create_creator(**overrides) -> dict:
    """Register a creator. Returns the Creator resource."""
    return get_success_data(
        api_client.create_creator(create_creator_payload(**overrides), make_creator_headers("bootstrap"))
    )


def create_patron(**overrides) -> dict:
    """Register a patron. Returns the Patron resource."""
    return get_success_data(
        api_client.create_patron(create_patron_payload(**overrides), make_patron_headers("bootstrap"))
    )


def create_published_tier(creator_id: str, **overrides) -> dict:
    """Create a MONTHLY tier owned by creator_id and publish it. Returns the
    PUBLISHED Tier."""
    headers = make_creator_headers(creator_id)
    tier = get_success_data(api_client.create_tier(create_tier_payload(creator_id, **overrides), headers))
    return get_success_data(api_client.publish_tier(tier["id"], headers))


def create_published_per_creation_tier(creator_id: str, **overrides) -> dict:
    """Create a PER_CREATION tier owned by creator_id and publish it."""
    headers = make_creator_headers(creator_id)
    tier = get_success_data(
        api_client.create_tier(create_per_creation_tier_payload(creator_id, **overrides), headers)
    )
    return get_success_data(api_client.publish_tier(tier["id"], headers))


# ---------------------------------------------------------------------------
# Charge helpers
# ---------------------------------------------------------------------------
def get_pledge_charges(pledge_id: str) -> list:
    """All charges for a pledge (admin view), newest filtering left to caller."""
    data, _ = _list(api_client.list_charges(ADMIN, params={"pledge_id": pledge_id}))
    return data


def settle_charge(charge_id: str, outcome: str = "SUCCEEDED") -> dict:
    """Settle a PENDING charge with the given outcome (admin)."""
    return get_success_data(api_client.settle_charge(charge_id, {"outcome": outcome}, ADMIN))


def first_pledge_charge(pledge_id: str) -> dict:
    """The earliest charge for a pledge (its INITIAL_PRORATION under UP_FRONT)."""
    charges = get_pledge_charges(pledge_id)
    assert charges, f"Setup step failed: no charges found for pledge {pledge_id}"
    return charges[0]


def _list(response):
    """Internal: return (data, meta) from a list response, lenient on status."""
    get_success_data(response)
    body = response.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 2/3: pledge lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_draft_pledge(patron_id, creator_id, tier_id) -> dict:
    """Create a pledge (stays DRAFT until its first charge settles). Returns the
    Pledge resource (lifecycle_status DRAFT under an UP_FRONT MONTHLY creator)."""
    return get_success_data(
        api_client.create_pledge(
            create_pledge_payload(patron_id, creator_id, tier_id), make_patron_headers(patron_id)
        )
    )


def create_active_pledge(patron_id, creator_id, tier_id) -> dict:
    """Create a pledge under an UP_FRONT MONTHLY creator and settle its first
    INITIAL_PRORATION charge SUCCEEDED so it bubbles DRAFT→ACTIVE. Returns the
    refreshed (ACTIVE) Pledge resource."""
    pledge = create_draft_pledge(patron_id, creator_id, tier_id)
    charge = first_pledge_charge(pledge["id"])
    settle_charge(charge["id"], "SUCCEEDED")
    return get_pledge(pledge["id"])


def get_pledge(pledge_id: str) -> dict:
    return get_success_data(api_client.get_pledge(pledge_id, ADMIN))


def get_pledge_version(pledge_id: str) -> int:
    return get_pledge(pledge_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: full "active membership" scenario (the most common preamble)
# ---------------------------------------------------------------------------
def setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500,
                            platform_plan=None, charge_timing=None):
    """Clock + creator (UP_FRONT MONTHLY) + published tier + patron + ACTIVE
    pledge (first charge settled). Returns dict with creator, tier, patron,
    pledge, and the settled first charge.
    """
    set_clock(clock)
    creator_overrides = {}
    if platform_plan is not None:
        creator_overrides["platform_plan"] = platform_plan
    if charge_timing is not None:
        creator_overrides["charge_timing"] = charge_timing
    creator = create_creator(**creator_overrides)
    tier = create_published_tier(creator["id"], monthly_fee_cents=monthly_fee_cents)
    patron = create_patron()
    draft = create_draft_pledge(patron["id"], creator["id"], tier["id"])
    init_charge = first_pledge_charge(draft["id"])
    settle_charge(init_charge["id"], "SUCCEEDED")
    pledge = get_pledge(draft["id"])
    return {
        "creator": creator,
        "tier": tier,
        "patron": patron,
        "pledge": pledge,
        "init_charge": get_success_data(api_client.get_charge(init_charge["id"], ADMIN)),
    }


# ---------------------------------------------------------------------------
# Tier 4: accumulated SUCCEEDED charges for payout-settlement tests
# ---------------------------------------------------------------------------
def setup_creator_with_succeeded_charges(net_amounts, clock="2026-06-01T00:00:00Z",
                                         platform_plan="STARTER", monthly_fee_cents=1500):
    """Create a STARTER END_OF_MONTH creator with one ACTIVE pledge, then settle
    a series of SUCCEEDED charges whose gross amounts == net amounts (no wallet
    credit). EVERY requested amount is delivered via an admin-created
    CYCLE_RENEWAL charge. Returns dict(creator, tier, patron, pledge,
    charge_ids).

    The creator uses END_OF_MONTH charge timing so pledge creation mints NO
    automatic INITIAL_PRORATION charge; the pledge is then activated by settling
    an admin-created gross-0 INITIAL_PRORATION enrollment charge. A gross-0
    activation charge contributes 0 to net_amount_cents, 0 to the creator's
    pending_payout_cents, and 0 to the payout gross — so the swept totals reflect
    exactly the requested net_amounts and nothing else. (Under an UP_FRONT
    creator the auto INITIAL_PRORATION would settle SUCCEEDED at the same cycle
    anchor and silently inflate every swept total.)
    """
    set_clock(clock)
    creator = create_creator(platform_plan=platform_plan, charge_timing="END_OF_MONTH")
    tier = create_published_tier(creator["id"], monthly_fee_cents=monthly_fee_cents)
    patron = create_patron()
    pledge = create_draft_pledge(patron["id"], creator["id"], tier["id"])
    # Activate via a gross-0 enrollment charge (first-charge settle SETS
    # current_cycle_charged_cents to the settled amount, i.e. 0, and bubbles the
    # pledge DRAFT -> ACTIVE, PRD §3.2).
    enroll = get_success_data(
        api_client.create_charge(
            create_charge_payload(pledge["id"], charge_kind="INITIAL_PRORATION", gross_amount_cents=0),
            ADMIN,
        )
    )
    settle_charge(enroll["id"], "SUCCEEDED")
    pledge = get_pledge(pledge["id"])
    charge_ids = []
    for amt in net_amounts:
        ch = get_success_data(
            api_client.create_charge(
                create_charge_payload(pledge["id"], charge_kind="CYCLE_RENEWAL", gross_amount_cents=amt),
                ADMIN,
            )
        )
        settle_charge(ch["id"], "SUCCEEDED")
        charge_ids.append(ch["id"])
    return {
        "creator": creator,
        "tier": tier,
        "patron": patron,
        "pledge": pledge,
        "charge_ids": charge_ids,
        "cycle_anchor_date": clock,
    }


# ---------------------------------------------------------------------------
# Tier 4: PER_CREATION pledge ready for paid-post publishing
# ---------------------------------------------------------------------------
def setup_per_creation_membership(clock="2026-06-10T00:00:00Z",
                                  per_creation_fee_cents=500,
                                  per_creation_monthly_cap_cents=1200):
    """Clock + PER_CREATION UP_FRONT creator + published PER_CREATION tier
    (rank 1) + patron + ACTIVE PER_CREATION pledge. The pledge is activated by
    settling its admin-created INITIAL_PRORATION enrollment charge.

    Returns dict(creator, tier, patron, pledge).
    """
    set_clock(clock)
    creator = create_creator(billing_mode="PER_CREATION", charge_timing="UP_FRONT")
    tier = create_published_per_creation_tier(
        creator["id"],
        per_creation_fee_cents=per_creation_fee_cents,
        per_creation_monthly_cap_cents=per_creation_monthly_cap_cents,
    )
    patron = create_patron()
    pledge = create_draft_pledge(patron["id"], creator["id"], tier["id"])
    # A PER_CREATION pledge has no auto proration charge (proration is a MONTHLY
    # rule). Activate it by settling its first charge SUCCEEDED — using an
    # admin-created enrollment charge if the create flow did not mint one.
    # The enrollment charge is gross 0 so the pledge enters its first cycle with
    # current_cycle_charged_cents == 0 (a first-charge settle SETS that field to
    # the settled amount, PRD §3.2): the harness must not pre-consume any of the
    # per-creation monthly cap, so later paid-post publishes see the full cap.
    existing = get_pledge_charges(pledge["id"])
    if existing:
        settle_charge(existing[0]["id"], "SUCCEEDED")
    else:
        ch = get_success_data(
            api_client.create_charge(
                create_charge_payload(pledge["id"], charge_kind="INITIAL_PRORATION", gross_amount_cents=0),
                ADMIN,
            )
        )
        settle_charge(ch["id"], "SUCCEEDED")
    return {
        "creator": creator,
        "tier": tier,
        "patron": patron,
        "pledge": get_pledge(pledge["id"]),
    }


def create_paid_post(creator_id, min_tier_rank=1):
    """Create a DRAFT paid-creation post owned by creator_id (not yet published)."""
    headers = make_creator_headers(creator_id)
    return get_success_data(
        api_client.create_post(
            create_post_payload(creator_id, min_tier_rank=min_tier_rank, is_paid_creation=True),
            headers,
        )
    )


def publish_post(post_id, creator_id):
    """Publish a DRAFT post owned by creator_id."""
    return get_success_data(api_client.publish_post(post_id, make_creator_headers(creator_id)))


# ---------------------------------------------------------------------------
# Tier 5: lapsed pledge + win-back offer (reactivation / win-back tests)
# ---------------------------------------------------------------------------
def setup_cancelled_lapsed_pledge(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500):
    """Active membership then cancelled → CANCELLED + LAPSED. Returns dict with
    creator, tier, patron, pledge (post-cancel)."""
    s = setup_active_membership(clock=clock, monthly_fee_cents=monthly_fee_cents)
    api_client.cancel_pledge(s["pledge"]["id"], make_patron_headers(s["patron"]["id"]))
    s["pledge"] = get_pledge(s["pledge"]["id"])
    return s


def setup_lapsed_pledge_with_offer(lapse_clock="2026-04-01T00:00:00Z",
                                   monthly_fee_cents=1500, discount_pct=None):
    """Active membership at lapse_clock, cancel it (→ LAPSED, lapsed_at set),
    then create a win-back offer for it. Returns dict with creator, tier,
    patron, pledge, offer.
    """
    s = setup_cancelled_lapsed_pledge(clock=lapse_clock, monthly_fee_cents=monthly_fee_cents)
    payload = create_win_back_offer_payload(s["pledge"]["id"])
    if discount_pct is not None:
        payload["discount_pct"] = discount_pct
    offer = get_success_data(
        api_client.create_win_back_offer(payload, make_creator_headers(s["creator"]["id"]))
    )
    s["offer"] = offer
    return s


# ---------------------------------------------------------------------------
# Tier 4: pledge driven into GRACE via two failed renewal charges
# ---------------------------------------------------------------------------
def setup_pledge_in_grace(clock="2026-06-01T00:00:00Z", monthly_fee_cents=1500):
    """Active membership, then a CYCLE_RENEWAL charge FAILS (→ PAST_DUE) and a
    retry CYCLE_RENEWAL charge also FAILS (→ GRACE, grace_deadline set).
    Returns dict with creator, tier, patron, pledge (in GRACE).
    """
    s = setup_active_membership(clock=clock, monthly_fee_cents=monthly_fee_cents)
    pledge_id = s["pledge"]["id"]
    ren = get_success_data(
        api_client.create_charge(
            create_charge_payload(pledge_id, charge_kind="CYCLE_RENEWAL", gross_amount_cents=monthly_fee_cents),
            ADMIN,
        )
    )
    settle_charge(ren["id"], "FAILED")
    retry = get_success_data(
        api_client.create_charge(
            create_charge_payload(pledge_id, charge_kind="CYCLE_RENEWAL", gross_amount_cents=monthly_fee_cents),
            ADMIN,
        )
    )
    settle_charge(retry["id"], "FAILED")
    s["pledge"] = get_pledge(pledge_id)
    return s


# ---------------------------------------------------------------------------
# Payout helper
# ---------------------------------------------------------------------------
def sweep_payout(creator_id, cycle_anchor_date):
    """Sweep a creator's SUCCEEDED unswept charges into a PENDING payout."""
    return get_success_data(
        api_client.create_payout(create_payout_payload(creator_id, cycle_anchor_date), ADMIN)
    )


# ---------------------------------------------------------------------------
# Conversation helper
# ---------------------------------------------------------------------------
def open_conversation(creator_id, patron_id):
    """Open a conversation as the patron (patron must already hold an
    ACTIVE/PAUSED pledge to the creator)."""
    return get_success_data(
        api_client.create_conversation(
            create_conversation_payload(creator_id, patron_id), make_patron_headers(patron_id)
        )
    )
