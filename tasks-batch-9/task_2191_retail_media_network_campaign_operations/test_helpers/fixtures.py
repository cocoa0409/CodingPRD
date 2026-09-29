"""Composite setup helpers for the retail media network API.

Every test starts against an empty database, so any test that is about a rule deeper
than resource creation has to walk the whole approval ladder first. The builders here
are that ladder, cut into reusable rungs:

    active advertiser
      -> trade fund pool                     (co-op money)
      -> active budget plan                  (media commitment)
        -> placement slot + catalog product  (inventory and merchandising)
          -> draft campaign
            -> line item, pending eligibility
            -> line item, eligible           (slot occupancy granted)
              -> scheduled campaign          (plan reservation taken)
                -> delivering campaign + serving line item
                  -> settled auction         (spend recognised)
                    -> completed campaign
                      -> issued invoice
                        -> measurement dispute

Each builder takes a mutable `world` dictionary, adds its own keys to it and returns
it, so a caller composes exactly as far up the ladder as its rule needs and can then
reach back for any earlier resource. `build_world()` seeds an empty one.

Every builder reads its result through `get_success_data()`, the lenient validator, so
a broken precondition surfaces as a setup failure rather than as a confusing assertion
inside the test body.

Setup steps use distinct operator identifiers on the two sides of every approval chain,
because one operator may not stand on both sides of a submit-then-decide pair.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .assertions import shift_days, shift_hours
from .constants import CLOCK_STARTUP_DEFAULT
from .test_users import (
    ACCOUNT_MANAGER,
    AUCTION_SERVICE,
    BILLING_OPS,
    CATALOG_OPS,
    CREDIT_ANALYST,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    SECOND_MEASUREMENT_ANALYST,
    make_advertiser_user_headers,
)


# ---------------------------------------------------------------------------
# The world dictionary
# ---------------------------------------------------------------------------


def build_world(**seed) -> dict:
    """Start an empty world. Every builder extends the dictionary it is handed."""
    world = {
        "clock": CLOCK_STARTUP_DEFAULT,
        "advertisers": [],
        "plans": [],
        "pools": [],
        "slots": [],
        "products": [],
        "campaigns": [],
        "line_items": [],
        "assignments": [],
        "auctions": [],
        "engagements": [],
        "sales": [],
        "studies": [],
        "invoices": [],
        "disputes": [],
    }
    world.update(seed)
    return world


def advertiser_headers(world: dict) -> dict:
    """AdvertiserUser headers for the seat that owns this world's advertiser."""
    return make_advertiser_user_headers(world["advertiser"]["id"])


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------


def set_clock(world: dict, moment: str) -> dict:
    """Move the logical clock and remember where it now stands."""
    get_success_data(api_client.set_clock({"current_utc": moment}, NETWORK_ADMIN))
    world["clock"] = moment
    return world


def advance_clock_days(world: dict, days: int) -> dict:
    """Move the logical clock forward by whole days from where it stands."""
    return set_clock(world, shift_days(world["clock"], days))


def advance_clock_hours(world: dict, hours: int) -> dict:
    """Move the logical clock forward by whole hours from where it stands."""
    return set_clock(world, shift_hours(world["clock"], hours))


def run_daily_checkpoint(world: dict, **payload) -> dict:
    """Run the deterministic daily sweep at the current logical time."""
    return get_success_data(
        api_client.run_daily_checkpoint(payload or None, NETWORK_ADMIN)
    )


# ---------------------------------------------------------------------------
# Re-reads, for the version an optimistic-concurrency call must carry
# ---------------------------------------------------------------------------


def reread_advertiser(world: dict) -> dict:
    """Re-read the advertiser and refresh its copy in the world."""
    data = get_success_data(
        api_client.get_advertiser(world["advertiser"]["id"], NETWORK_ADMIN)
    )
    world["advertiser"] = data
    return data


def reread_plan(world: dict, key: str = "plan") -> dict:
    """Re-read a budget plan and refresh its copy in the world."""
    data = get_success_data(api_client.get_budget_plan(world[key]["id"], NETWORK_ADMIN))
    world[key] = data
    return data


def reread_pool(world: dict, key: str = "pool") -> dict:
    """Re-read a trade fund pool and refresh its copy in the world."""
    data = get_success_data(
        api_client.get_trade_fund_account(world[key]["id"], BILLING_OPS)
    )
    world[key] = data
    return data


def reread_campaign(world: dict, key: str = "campaign") -> dict:
    """Re-read a campaign and refresh its copy in the world.

    Creating a line item or a study increments the parent campaign's version, so a
    second child must be created against a freshly read version.
    """
    data = get_success_data(api_client.get_campaign(world[key]["id"], NETWORK_ADMIN))
    world[key] = data
    return data


def reread_line_item(world: dict, key: str = "line_item") -> dict:
    """Re-read a line item and refresh its copy in the world."""
    data = get_success_data(api_client.get_line_item(world[key]["id"], NETWORK_ADMIN))
    world[key] = data
    return data


def reread_slot(world: dict, key: str = "slot") -> dict:
    """Re-read a placement slot and refresh its copy in the world."""
    data = get_success_data(
        api_client.get_placement_slot(world[key]["id"], NETWORK_ADMIN)
    )
    world[key] = data
    return data


def reread_product(world: dict, key: str = "product") -> dict:
    """Re-read a catalog product and refresh its copy in the world."""
    data = get_success_data(
        api_client.get_catalog_product(world[key]["id"], CATALOG_OPS)
    )
    world[key] = data
    return data


def reread_invoice(world: dict, key: str = "invoice") -> dict:
    """Re-read an invoice and refresh its copy in the world."""
    data = get_success_data(api_client.get_invoice(world[key]["id"], BILLING_OPS))
    world[key] = data
    return data


def reread_study(world: dict, key: str = "study") -> dict:
    """Re-read an incrementality study and refresh its copy in the world."""
    data = get_success_data(
        api_client.get_incrementality_study(world[key]["id"], MEASUREMENT_ANALYST)
    )
    world[key] = data
    return data


def reread_dispute(world: dict, key: str = "dispute") -> dict:
    """Re-read a measurement dispute and refresh its copy in the world."""
    data = get_success_data(
        api_client.get_measurement_dispute(world[key]["id"], MEASUREMENT_ANALYST)
    )
    world[key] = data
    return data


# ---------------------------------------------------------------------------
# Tier 1: advertisers, pools and plans
# ---------------------------------------------------------------------------


def build_active_advertiser(world: dict = None, key: str = "advertiser", **overrides):
    """Register a self-serve advertiser and take it through KYC to ACTIVE.

    Onboarding submission and the KYC decision are made by different operators, as
    the two sides of an approval chain must be.
    """
    world = build_world() if world is None else world
    created = get_success_data(
        api_client.create_advertiser(f.advertiser_payload(**overrides), NETWORK_ADMIN)
    )
    api_client.submit_advertiser_onboarding(
        created["id"], f.submit_onboarding_payload(), ACCOUNT_MANAGER
    )
    decided = get_success_data(
        api_client.decide_advertiser_kyc(
            created["id"], f.kyc_decision_payload("APPROVE"), CREDIT_ANALYST
        )
    )
    world[key] = decided
    world["advertisers"].append(decided)
    world.setdefault("advertiser", decided)
    return world


def build_active_managed_advertiser(
    world: dict = None, key: str = "advertiser", **overrides
):
    """Register a managed advertiser and take it through KYC to ACTIVE.

    A managed advertiser has no self-serve daily spend cap, so auction headroom for
    its line items is decided by the line-item and campaign caps alone.
    """
    world = build_world() if world is None else world
    created = get_success_data(
        api_client.create_advertiser(
            f.managed_advertiser_payload(**overrides), NETWORK_ADMIN
        )
    )
    api_client.submit_advertiser_onboarding(
        created["id"], f.submit_onboarding_payload(), ACCOUNT_MANAGER
    )
    decided = get_success_data(
        api_client.decide_advertiser_kyc(
            created["id"], f.kyc_decision_payload("APPROVE"), CREDIT_ANALYST
        )
    )
    world[key] = decided
    world["advertisers"].append(decided)
    world.setdefault("advertiser", decided)
    return world


def build_second_active_advertiser(world: dict, **overrides):
    """Add a second, unrelated active advertiser under the key `other_advertiser`.

    Used wherever a rule has to be shown to be scoped to one advertiser: an
    advertiser seat reading across the boundary, or a campaign pointed at another
    advertiser's plan.
    """
    return build_active_advertiser(world, key="other_advertiser", **overrides)


def build_child_advertiser(world: dict, **overrides):
    """Add an active child advertiser under the key `child_advertiser`.

    A child evaluates its own limit against the parent's credit limit but does not
    roll its exposure up into the parent.
    """
    overrides.setdefault("parent_advertiser_id", world["advertiser"]["id"])
    return build_active_advertiser(world, key="child_advertiser", **overrides)


def build_trade_fund_pool(
    world: dict, accrual_cents: int = 3000000, key: str = "pool", **overrides
):
    """Open a trade fund pool for the advertiser and optionally seed an accrual.

    Pass `accrual_cents=0` to leave the pool open with nothing accrued.
    """
    pool = get_success_data(
        api_client.create_trade_fund_account(
            f.trade_fund_account_payload(world["advertiser"]["id"], **overrides),
            BILLING_OPS,
        )
    )
    if accrual_cents:
        pool = get_success_data(
            api_client.post_trade_fund_accrual(
                pool["id"], f.accrual_payload(accrual_cents), BILLING_OPS
            )
        )
    world[key] = pool
    world["pools"].append(pool)
    return world


def build_frozen_trade_fund_pool(
    world: dict, accrual_cents: int = 3000000, frozen_reason: str = "AUDIT", **overrides
):
    """Open a trade fund pool, seed it and then freeze it.

    A frozen pool refuses accruals, manual deductions and invoice draws, which is
    what a state-before-money precedence test needs.
    """
    build_trade_fund_pool(world, accrual_cents=accrual_cents, **overrides)
    world["pool"] = get_success_data(
        api_client.freeze_trade_fund_account(
            world["pool"]["id"], {"frozen_reason": frozen_reason}, BILLING_OPS
        )
    )
    return world


def build_draft_budget_plan(world: dict, key: str = "plan", **overrides):
    """Create a budget plan and leave it in DRAFT.

    Creation carries the advertiser version, so the advertiser is re-read first: any
    earlier plan on the same advertiser has already moved it on.
    """
    advertiser = reread_advertiser(world)
    plan = get_success_data(
        api_client.create_budget_plan(
            f.budget_plan_payload(advertiser["id"], advertiser["version"], **overrides),
            ACCOUNT_MANAGER,
        )
    )
    world[key] = plan
    world["plans"].append(plan)
    return world


def build_active_budget_plan(world: dict, key: str = "plan", **overrides):
    """Create a budget plan and take it through submission and approval.

    Approval promotes the plan straight to ACTIVE when the logical clock already sits
    inside its window, which is the case for the default window.
    """
    build_draft_budget_plan(world, key=key, **overrides)
    api_client.submit_budget_plan(
        world[key]["id"], {"submission_note": "quarterly commitment"}, ACCOUNT_MANAGER
    )
    world[key] = get_success_data(
        api_client.approve_budget_plan(
            world[key]["id"], {"approval_note": "inside credit limit"}, CREDIT_ANALYST
        )
    )
    return world


# ---------------------------------------------------------------------------
# Tier 2: inventory, catalog and campaigns
# ---------------------------------------------------------------------------


def build_placement_slot(world: dict, key: str = "slot", **overrides):
    """Create an on-site placement slot. Only a network administrator may."""
    slot = get_success_data(
        api_client.create_placement_slot(
            f.placement_slot_payload(**overrides), NETWORK_ADMIN
        )
    )
    world[key] = slot
    world["slots"].append(slot)
    return world


def build_offsite_placement_slot(world: dict, key: str = "slot", **overrides):
    """Create an off-site placement slot carrying an adjacency buffer."""
    slot = get_success_data(
        api_client.create_placement_slot(
            f.offsite_placement_slot_payload(**overrides), NETWORK_ADMIN
        )
    )
    world[key] = slot
    world["slots"].append(slot)
    return world


def build_catalog_product(world: dict, key: str = "product", **overrides):
    """Register an in-stock catalog product."""
    product = get_success_data(
        api_client.create_catalog_product(
            f.catalog_product_payload(**overrides), CATALOG_OPS
        )
    )
    world[key] = product
    world["products"].append(product)
    return world


def build_draft_campaign(
    world: dict, key: str = "campaign", plan_key: str = "plan", **overrides
):
    """Create a campaign against the plan and leave it in DRAFT."""
    campaign = get_success_data(
        api_client.create_campaign(
            f.campaign_payload(
                world["advertiser"]["id"], world[plan_key]["id"], **overrides
            ),
            ACCOUNT_MANAGER,
        )
    )
    world[key] = campaign
    world["campaigns"].append(campaign)
    return world


def build_line_item(
    world: dict,
    key: str = "line_item",
    campaign_key: str = "campaign",
    slot_key: str = "slot",
    product_key: str = "product",
    assign_product: bool = True,
    **overrides,
):
    """Create a line item on the campaign and give it one hero product assignment.

    The campaign is re-read first because every line item creation advances the
    parent campaign's version, and the assignment carries the line item's own
    version.
    """
    campaign = reread_campaign(world, campaign_key)
    line_item = get_success_data(
        api_client.create_line_item(
            f.line_item_payload(
                campaign["id"],
                world[slot_key]["id"],
                campaign["version"],
                **overrides,
            ),
            ACCOUNT_MANAGER,
        )
    )
    world[key] = line_item
    world["line_items"].append(line_item)
    if assign_product:
        assignment = get_success_data(
            api_client.create_product_assignment(
                f.product_assignment_payload(
                    line_item["id"], world[product_key]["id"], line_item["version"]
                ),
                CATALOG_OPS,
            )
        )
        world["assignments"].append(assignment)
        world["assignment"] = assignment
    return world


def build_pending_eligibility_line_item(world: dict, key: str = "line_item", **kwargs):
    """Create a line item with its hero assignment and submit it for eligibility.

    The line item holds no slot occupancy yet: occupancy is granted only by the
    approval.
    """
    build_line_item(world, key=key, **kwargs)
    world[key] = get_success_data(
        api_client.submit_line_item_eligibility(world[key]["id"], None, ACCOUNT_MANAGER)
    )
    return world


def build_eligible_line_item(world: dict, key: str = "line_item", **kwargs):
    """Create a line item and take it through the catalog eligibility fork to ELIGIBLE.

    Approval raises the slot's occupancy by one and computes the line item's
    reservation from its daily budget and flight length.
    """
    build_pending_eligibility_line_item(world, key=key, **kwargs)
    world[key] = get_success_data(
        api_client.decide_line_item_eligibility(
            world[key]["id"], f.decision_payload("APPROVE"), CATALOG_OPS
        )
    )
    return world


def build_pending_review_campaign(
    world: dict, key: str = "campaign", with_line_item: bool = True, **kwargs
):
    """Take a campaign with one eligible line item to PENDING_REVIEW.

    Nothing is reserved against the plan while the campaign waits in review.
    """
    if with_line_item:
        build_eligible_line_item(world, campaign_key=key, **kwargs)
    world[key] = get_success_data(
        api_client.submit_campaign_for_review(
            world[key]["id"], {"submission_note": "ready for flight"}, ACCOUNT_MANAGER
        )
    )
    return world


def build_scheduled_campaign(world: dict, key: str = "campaign", **kwargs):
    """Take a campaign through review approval to SCHEDULED.

    Approval reserves the campaign's allocation against the plan, so the plan's
    available headroom falls by exactly that allocation. The reviewer differs from the
    submitter, as the approval chain requires.
    """
    build_pending_review_campaign(world, key=key, **kwargs)
    world[key] = get_success_data(
        api_client.decide_campaign_review(
            world[key]["id"], f.decision_payload("APPROVE"), NETWORK_ADMIN
        )
    )
    return world


def build_delivering_campaign(
    world: dict,
    key: str = "campaign",
    activate_at: str = None,
    refresh_line_items: bool = True,
    **kwargs,
):
    """Take a campaign to DELIVERING and its eligible line items to SERVING.

    Activation needs the logical clock inside the flight, so the clock is moved to
    `activate_at` first; by default that is the campaign's own flight start. Reaching
    `DELIVERING` carries every eligible line item to `SERVING` on its own, so the line
    items are re-read rather than activated a second time.
    """
    build_scheduled_campaign(world, key=key, **kwargs)
    set_clock(world, activate_at or world[key]["flight_start_at"])
    world[key] = get_success_data(
        api_client.activate_campaign(world[key]["id"], None, ACCOUNT_MANAGER)
    )
    if refresh_line_items:
        for index, line_item in enumerate(list(world["line_items"])):
            current = get_success_data(
                api_client.get_line_item(line_item["id"], ACCOUNT_MANAGER)
            )
            world["line_items"][index] = current
            for name, held in list(world.items()):
                if isinstance(held, dict) and held.get("id") == current["id"]:
                    world[name] = current
    return world


def build_second_line_item_on_same_slot(
    world: dict, key: str = "second_line_item", activate: bool = False, **overrides
):
    """Add another line item to the same campaign and slot.

    Every occupancy rule — aggregate capacity, category exclusivity and the off-site
    adjacency buffer — needs at least two line items competing for one slot, and the
    second must be created against a freshly read campaign version.
    """
    build_eligible_line_item(world, key=key, **overrides)
    if activate:
        world[key] = get_success_data(
            api_client.activate_line_item(world[key]["id"], None, ACCOUNT_MANAGER)
        )
    return world


def build_second_campaign_on_same_plan(
    world: dict, key: str = "second_campaign", **overrides
):
    """Add a second draft campaign drawing on the same budget plan.

    Two campaigns on one plan is the shape every plan-level headroom rule needs: the
    first campaign's reservation is what leaves the second one short.
    """
    return build_draft_campaign(world, key=key, **overrides)


# ---------------------------------------------------------------------------
# Ready-made ladders, for tests whose rule sits far up the chain
# ---------------------------------------------------------------------------


def build_funded_advertiser(
    world: dict = None,
    accrual_cents: int = 3000000,
    advertiser: dict = None,
    pool: dict = None,
    plan: dict = None,
):
    """Advertiser active, trade fund pool open and accrued, budget plan active.

    This is the floor every campaign test stands on.
    """
    world = build_active_advertiser(world, **(advertiser or {}))
    build_trade_fund_pool(world, accrual_cents=accrual_cents, **(pool or {}))
    build_active_budget_plan(world, **(plan or {}))
    return world


def build_inventory(
    world: dict, offsite: bool = False, slot: dict = None, product: dict = None
):
    """Add one placement slot and one in-stock catalog product."""
    if offsite:
        build_offsite_placement_slot(world, **(slot or {}))
    else:
        build_placement_slot(world, **(slot or {}))
    build_catalog_product(world, **(product or {}))
    return world


def build_campaign_ready_world(
    world: dict = None,
    accrual_cents: int = 3000000,
    offsite: bool = False,
    plan: dict = None,
    pool: dict = None,
    advertiser: dict = None,
    slot: dict = None,
    product: dict = None,
    campaign: dict = None,
    managed: bool = False,
):
    """Everything a campaign needs, with the campaign itself left in DRAFT.

    Advertiser active, pool accrued, plan active, one slot, one product, one draft
    campaign. Each layer takes its own override dictionary so a test can vary one
    figure — a slot's capacity, a campaign's daily cap — without restating the rest.
    """
    world = build_world() if world is None else world
    if managed:
        build_active_managed_advertiser(world, **(advertiser or {}))
    else:
        build_active_advertiser(world, **(advertiser or {}))
    build_trade_fund_pool(world, accrual_cents=accrual_cents, **(pool or {}))
    build_active_budget_plan(world, **(plan or {}))
    if offsite:
        build_offsite_placement_slot(world, **(slot or {}))
    else:
        build_placement_slot(world, **(slot or {}))
    build_catalog_product(world, **(product or {}))
    build_draft_campaign(world, **(campaign or {}))
    return world


# ---------------------------------------------------------------------------
# Tier 3: auctions, engagements and sales
# ---------------------------------------------------------------------------


def build_open_auction(
    world: dict, key: str = "auction", slot_key: str = "slot", **overrides
):
    """Open an auction on the slot at the current logical time.

    The request instant defaults to where the clock stands, so a candidate line item
    is inside its flight if the clock is.
    """
    overrides.setdefault("requested_at", world["clock"])
    auction = get_success_data(
        api_client.create_auction_event(
            f.auction_event_payload(world[slot_key]["id"], **overrides), AUCTION_SERVICE
        )
    )
    world[key] = auction
    world["auctions"].append(auction)
    return world


def build_ranked_auction(world: dict, key: str = "auction", **overrides):
    """Open an auction and rank its candidates.

    Ranking writes one bid row per candidate line item and stamps the quality-adjusted
    score each was ordered by; a candidate below the slot floor is filtered out here.
    """
    build_open_auction(world, key=key, **overrides)
    world[key] = get_success_data(
        api_client.rank_auction_event(world[key]["id"], None, AUCTION_SERVICE)
    )
    world["bids"] = get_success_data(
        api_client.list_auction_bids(AUCTION_SERVICE, auction_event_id=world[key]["id"])
    )
    return world


def build_awarded_auction(world: dict, key: str = "auction", **overrides):
    """Open an auction, rank it and award the winner at the second-price clearing figure."""
    build_ranked_auction(world, key=key, **overrides)
    world[key] = get_success_data(
        api_client.award_auction_event(world[key]["id"], None, AUCTION_SERVICE)
    )
    return world


def build_engagement_event(
    world: dict,
    event_type: str = "CLICK",
    auction_key: str = "auction",
    line_item_key: str = "line_item",
    product_key: str = "product",
    **overrides,
):
    """Record one engagement against the awarded auction at the current logical time."""
    overrides.setdefault("occurred_at", world["clock"])
    event = get_success_data(
        api_client.create_engagement_event(
            f.engagement_event_payload(
                world[line_item_key]["id"],
                world[auction_key]["id"],
                world[product_key]["id"],
                event_type=event_type,
                **overrides,
            ),
            AUCTION_SERVICE,
        )
    )
    world["engagements"].append(event)
    world["engagement"] = event
    return world


def build_engagements(world: dict, impressions: int = 1, clicks: int = 1, **overrides):
    """Record a fixed mix of impressions and clicks against the awarded auction.

    Settlement charges per click on a cost-per-click line item and per thousand
    impressions on a cost-per-mille one, so a test states whichever counter its
    charge is built from.
    """
    for _ in range(impressions):
        build_engagement_event(world, event_type="IMPRESSION", **overrides)
    for _ in range(clicks):
        build_engagement_event(world, event_type="CLICK", **overrides)
    return world


def build_settled_auction(
    world: dict, key: str = "auction", impressions: int = 1, clicks: int = 1, **overrides
):
    """Take an auction all the way to SETTLED with a stated engagement mix.

    Settlement is where money moves: the charge is recognised against the line item,
    the campaign and the plan, and a plan left with nothing available is exhausted by
    this call.
    """
    build_awarded_auction(world, key=key, **overrides)
    build_engagements(world, impressions=impressions, clicks=clicks, auction_key=key)
    world[key] = get_success_data(
        api_client.settle_auction_event(world[key]["id"], None, AUCTION_SERVICE)
    )
    return world


def build_attributed_sale(world: dict, sale_cents: int = 5000, **overrides):
    """Attribute one retail sale to the most recent engagement."""
    overrides.setdefault("occurred_at", world["clock"])
    sale = get_success_data(
        api_client.create_attributed_sale(
            f.attributed_sale_payload(
                world["engagement"]["id"],
                world["product"]["id"],
                sale_cents=sale_cents,
                **overrides,
            ),
            MEASUREMENT_ANALYST,
        )
    )
    world["sales"].append(sale)
    world["sale"] = sale
    return world


# ---------------------------------------------------------------------------
# Tier 4: campaign finalisation and billing
# ---------------------------------------------------------------------------


def build_completed_campaign(
    world: dict, key: str = "campaign", at_flight_end: bool = True
):
    """Complete a delivering campaign once its flight has run out.

    Completion needs the clock at or past the flight end. It ends the campaign's
    serving line items and moves the billing dimension on in the same request, so the
    two status dimensions are read together afterwards.
    """
    if at_flight_end:
        set_clock(world, world[key]["flight_end_at"])
    world[key] = get_success_data(
        api_client.complete_campaign(world[key]["id"], None, ACCOUNT_MANAGER)
    )
    return world


def build_draft_invoice(
    world: dict,
    key: str = "invoice",
    billing_period_code: str = "2026-08",
    plan_key: str = "plan",
    pool_key: str = "pool",
    **overrides,
):
    """Open a draft invoice for one billing month."""
    invoice = get_success_data(
        api_client.create_invoice(
            f.invoice_payload(
                world["advertiser"]["id"],
                world[plan_key]["id"],
                world[pool_key]["id"],
                billing_period_code=billing_period_code,
                **overrides,
            ),
            BILLING_OPS,
        )
    )
    world[key] = invoice
    world["invoices"].append(invoice)
    return world


def build_issued_invoice(world: dict, key: str = "invoice", **overrides):
    """Open a draft invoice and issue it.

    Issuance runs the whole charge waterfall and fixes the due date, the dispute
    deadline and the write-off date from the moment of issue. It is refused unless
    every campaign in the period has finished delivering, so the campaign must be
    completed first.
    """
    build_draft_invoice(world, key=key, **overrides)
    world[key] = get_success_data(
        api_client.issue_invoice(
            world[key]["id"], {"issue_note": "period closed"}, BILLING_OPS
        )
    )
    return world


def build_settled_invoice(
    world: dict,
    key: str = "invoice",
    paid_amount_cents: int = None,
    **overrides,
):
    """Issue an invoice and pay it in full."""
    build_issued_invoice(world, key=key, **overrides)
    amount = (
        paid_amount_cents
        if paid_amount_cents is not None
        else world[key]["net_cash_due_cents"]
    )
    world[key] = get_success_data(
        api_client.settle_invoice(
            world[key]["id"],
            {"paid_amount_cents": amount, "payment_reference": "WIRE-2026-08-001"},
            BILLING_OPS,
        )
    )
    return world


# ---------------------------------------------------------------------------
# Tier 5: disputes
# ---------------------------------------------------------------------------


def build_filed_dispute(
    world: dict,
    key: str = "dispute",
    invoice_key: str = "invoice",
    dispute_category: str = "IMPRESSION_DISCREPANCY",
    claimed_amount_cents: int = 10000,
    **overrides,
):
    """File a dispute against an issued invoice.

    Filing starts the service-level clock, whose length follows from the dispute's
    category, and carries the invoice version so a concurrent invoice change is caught.
    The filing operator is the account manager, because filing is reserved to the network
    administrator, the account manager and the owning advertiser user.
    """
    invoice = reread_invoice(world, invoice_key)
    dispute = get_success_data(
        api_client.create_measurement_dispute(
            f.measurement_dispute_payload(
                invoice["id"],
                invoice["version"],
                dispute_category=dispute_category,
                claimed_amount_cents=claimed_amount_cents,
                **overrides,
            ),
            ACCOUNT_MANAGER,
        )
    )
    world[key] = dispute
    world["disputes"].append(dispute)
    return world


def build_dispute_under_review(world: dict, key: str = "dispute", **kwargs):
    """File a dispute and take it under review with an analyst assigned.

    The assigned analyst is a different operator from the one who files, because the
    same operator may not both raise and adjudicate a dispute.
    """
    build_filed_dispute(world, key=key, **kwargs)
    world[key] = get_success_data(
        api_client.start_measurement_dispute_review(
            world[key]["id"],
            {"assigned_analyst_user_id": SECOND_MEASUREMENT_ANALYST["X-User-ID"]},
            SECOND_MEASUREMENT_ANALYST,
        )
    )
    return world


def build_dispute_awaiting_info(world: dict, key: str = "dispute", **kwargs):
    """Take a dispute under review and then request further information.

    Each information request extends the deadline, and only a bounded number may be
    made before the review has to conclude on what it has.
    """
    build_dispute_under_review(world, key=key, **kwargs)
    world[key] = get_success_data(
        api_client.request_measurement_dispute_info(
            world[key]["id"],
            {"information_request_note": "partner impression logs required"},
            SECOND_MEASUREMENT_ANALYST,
        )
    )
    return world


def provide_dispute_info(world: dict, key: str = "dispute"):
    """Answer an outstanding information request, returning the dispute to review."""
    world[key] = get_success_data(
        api_client.provide_measurement_dispute_info(
            world[key]["id"],
            {"evidence_note": "logs supplied"},
            advertiser_headers(world),
        )
    )
    return world


def request_dispute_info(world: dict, key: str = "dispute", note: str = "further logs"):
    """Make another information request on a dispute already under review."""
    world[key] = get_success_data(
        api_client.request_measurement_dispute_info(
            world[key]["id"],
            {"information_request_note": note},
            SECOND_MEASUREMENT_ANALYST,
        )
    )
    return world


# ---------------------------------------------------------------------------
# Tier 5: incrementality studies
# ---------------------------------------------------------------------------


def build_designed_study(
    world: dict, key: str = "study", campaign_key: str = "campaign", **overrides
):
    """Design a study on the campaign.

    Design carries the campaign version and is refused unless the campaign is already
    scheduled or delivering, so the campaign must have cleared review first.
    """
    campaign = reread_campaign(world, campaign_key)
    study = get_success_data(
        api_client.create_incrementality_study(
            f.incrementality_study_payload(
                campaign["id"], campaign["version"], **overrides
            ),
            MEASUREMENT_ANALYST,
        )
    )
    world[key] = study
    world["studies"].append(study)
    return world


def build_running_study(
    world: dict,
    key: str = "study",
    exposed_group_size: int = 50000,
    control_group_size: int = 12500,
    **overrides,
):
    """Design a study and start it with both cohorts sized.

    Starting requires the logical clock to have reached the study window's opening
    instant, so the clock is moved there first.
    """
    build_designed_study(world, key=key, **overrides)
    set_clock(world, world[key]["window_start_at"])
    world[key] = get_success_data(
        api_client.start_incrementality_study(
            world[key]["id"],
            f.study_start_payload(exposed_group_size, control_group_size),
            MEASUREMENT_ANALYST,
        )
    )
    return world


def build_measured_study(
    world: dict,
    key: str = "study",
    exposed_conversions: int = 3000,
    control_conversions: int = 600,
    exposed_sales_cents: int = 15000000,
    control_sales_cents: int = 3000000,
    **overrides,
):
    """Take a study to MEASURED, moving the clock past the window's close first.

    Measurement is refused before the window has run out, and it is where lift,
    significance and incremental return on ad spend are computed.
    """
    build_running_study(world, key=key, **overrides)
    set_clock(world, world[key]["window_end_at"])
    world[key] = get_success_data(
        api_client.measure_incrementality_study(
            world[key]["id"],
            f.study_measure_payload(
                exposed_conversions,
                control_conversions,
                exposed_sales_cents,
                control_sales_cents,
            ),
            MEASUREMENT_ANALYST,
        )
    )
    return world


def build_published_study(world: dict, key: str = "study", **kwargs):
    """Take a study to PUBLISHED. Publication is refused below the significance floor."""
    build_measured_study(world, key=key, **kwargs)
    world[key] = get_success_data(
        api_client.publish_incrementality_study(
            world[key]["id"], {"publication_note": "released"}, MEASUREMENT_ANALYST
        )
    )
    return world


# ---------------------------------------------------------------------------
# Whole-lifecycle shortcuts
# ---------------------------------------------------------------------------


def build_delivering_world(
    world: dict = None,
    accrual_cents: int = 3000000,
    offsite: bool = False,
    managed: bool = False,
    plan: dict = None,
    pool: dict = None,
    advertiser: dict = None,
    slot: dict = None,
    product: dict = None,
    campaign: dict = None,
    line_item: dict = None,
    activate_at: str = None,
):
    """One campaign DELIVERING with one line item SERVING, from an empty database.

    This is the state most auction, pacing and cascade rules are stated against.
    """
    world = build_campaign_ready_world(
        world,
        accrual_cents=accrual_cents,
        offsite=offsite,
        managed=managed,
        plan=plan,
        pool=pool,
        advertiser=advertiser,
        slot=slot,
        product=product,
        campaign=campaign,
    )
    build_delivering_campaign(world, activate_at=activate_at, **(line_item or {}))
    return world


def build_billable_world(
    world: dict = None,
    impressions: int = 1,
    clicks: int = 1,
    **kwargs,
):
    """A campaign delivered, settled once and completed, ready to be invoiced.

    The chain is: deliver, open and rank and award an auction, record the engagement
    mix, settle it so spend is recognised, then complete the campaign at its flight
    end so the billing dimension moves on.
    """
    world = build_delivering_world(world, **kwargs)
    build_settled_auction(world, impressions=impressions, clicks=clicks)
    build_completed_campaign(world)
    return world



# ---------------------------------------------------------------------------
# Movements applied to an already-built world
# ---------------------------------------------------------------------------


def adjust_product_stock(
    world: dict,
    delta_units: int,
    key: str = "product",
    headers: dict = None,
    **overrides,
):
    """Post a signed stock movement and refresh the product in the world.

    A negative movement that carries `in_stock_units` below the serving threshold is
    what fires the out-of-stock pausing chain, so callers use this to trigger the
    cascade rather than to set stock up front.
    """
    get_success_data(
        api_client.post_catalog_product_stock_adjustment(
            world[key]["id"],
            f.stock_adjustment_payload(delta_units, **overrides),
            headers or CATALOG_OPS,
        )
    )
    reread_product(world, key=key)
    return world


def suspend_advertiser(
    world: dict,
    suspension_reason: str = "MANUAL",
    headers: dict = None,
    **overrides,
):
    """Suspend the advertiser, which runs the three-level suspension cascade.

    Every scheduled or delivering campaign of the advertiser is paused and each of
    their eligible or serving line items is manually paused, so this is the shortest
    route to a world whose campaigns were stopped by something outside themselves.
    """
    payload = {"suspension_reason": suspension_reason}
    payload.update(overrides)
    world["advertiser"] = get_success_data(
        api_client.suspend_advertiser(
            world["advertiser"]["id"], payload, headers or CREDIT_ANALYST
        )
    )
    return world


def pause_campaign(
    world: dict,
    key: str = "campaign",
    pause_reason: str = "MANUAL",
    headers: dict = None,
    **overrides,
):
    """Pause a delivering campaign and refresh it in the world."""
    world[key] = get_success_data(
        api_client.pause_campaign(
            world[key]["id"],
            f.pause_payload(pause_reason, **overrides),
            headers or ACCOUNT_MANAGER,
        )
    )
    return world


def pause_line_item(
    world: dict,
    key: str = "line_item",
    pause_reason: str = "MANUAL",
    headers: dict = None,
    **overrides,
):
    """Pause a serving line item and refresh it in the world."""
    world[key] = get_success_data(
        api_client.pause_line_item(
            world[key]["id"],
            f.pause_payload(pause_reason, **overrides),
            headers or ACCOUNT_MANAGER,
        )
    )
    return world


def post_pool_deduction(
    world: dict,
    amount_cents: int,
    key: str = "pool",
    headers: dict = None,
    **overrides,
):
    """Post a manual deduction against a trade fund pool and refresh it.

    Manual deductions move drawable money into the deducted column without an invoice,
    which is how a pool is walked to a chosen `available_cents` before the rule under
    test is exercised.
    """
    get_success_data(
        api_client.post_trade_fund_deduction(
            world[key]["id"],
            f.deduction_payload(amount_cents, world[key]["version"], **overrides),
            headers or BILLING_OPS,
        )
    )
    reread_pool(world, key=key)
    return world
