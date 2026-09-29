"""Writes that quote a parent version another write has already moved.

Five creation endpoints carry a mandatory version expectation naming their parent, and
each of the tests below holds a version that was genuinely current when it was read and
has since been superseded by a mutation the PRD names explicitly — a KYC decision, a
first product assignment, a first manual deduction, a first dispute filing, a first
study design. The refusal is never about the child's own fields, which are valid
throughout, and never about a shortage: the pool has room, the fiscal periods do not
collide, and the assignment has an eligible product to attach.

The last test is the other side of the same coin: a single accepted write whose
consequences run three levels down, from a plan's headroom reaching exactly zero to a
line item paused for a reason nobody in the request named.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    BILLING_OPS,
    CREDIT_ANALYST,
    ERR_STALE_ADVERTISER_VERSION,
    ERR_STALE_CAMPAIGN_VERSION,
    ERR_STALE_INVOICE_VERSION,
    ERR_STALE_LINE_ITEM_VERSION,
    ERR_STALE_TRADE_FUND_VERSION,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    api_client,
    assert_budget_plan_identity,
    assert_line_item_paused,
    assert_occupancy_count,
    assert_trade_fund_identity,
    factories as f,
    get_success_data,
    parse_utc,
    reread_campaign,
    reread_invoice,
    reread_line_item,
    reread_plan,
    reread_pool,
    reread_slot,
    reread_study,
    validate_error,
    validate_success,
)
from test_helpers.fixtures_corner_rbac import (
    BASELINE_ADVERTISER,
    BASELINE_LINE_ITEM_A,
    BASELINE_PLAN,
    BASELINE_PRODUCT_B,
    build_baseline_advertiser,
    build_baseline_billing_world,
    build_baseline_campaign_world,
    build_baseline_delivering_world,
    build_baseline_draft_invoice,
    build_baseline_plan,
)
from test_helpers.fixtures import (
    build_catalog_product,
    build_line_item,
    build_trade_fund_pool,
)

# --- The second budget plan on a superseded advertiser read ----------------

SECOND_PLAN = {
    "fiscal_period_code": "2026-Q4",
    "committed_total_cents": 500000,
    "trade_fund_share_cents": 0,
    "window_start_at": "2026-10-01T00:00:00Z",
    "window_end_at": "2026-12-01T00:00:00Z",
}


def test_a_budget_plan_create_quoting_a_superseded_advertiser_version_is_refused():
    """A plan create quoting the advertiser version the KYC decision moved is refused.

    PRD 3.1: "All three branches stamp `kyc_decided_by_user_id` and increment the
    advertiser's `version` by 1".

    PRD 2.7: "Opening a budget plan requires `expected_advertiser_version` to equal the
    target advertiser's current `version`."

    The two fiscal periods never collide, so nothing but the version expectation can
    refuse the second create.

    Design: Corner/cross_cutting_complexity_layers/a_second_budget_plan_create_on_the_advertiser_version_read_before_the_first_returns_412
    """
    advertiser = get_success_data(
        api_client.create_advertiser(
            f.advertiser_payload(**BASELINE_ADVERTISER), NETWORK_ADMIN
        )
    )
    submitted = get_success_data(
        api_client.submit_advertiser_onboarding(
            advertiser["id"], f.submit_onboarding_payload(), ACCOUNT_MANAGER
        )
    )
    version_read_before_the_decision = submitted["version"]
    approved = get_success_data(
        api_client.decide_advertiser_kyc(
            advertiser["id"], f.kyc_decision_payload("APPROVE"), CREDIT_ANALYST
        )
    )
    first_plan = get_success_data(
        api_client.create_budget_plan(
            f.budget_plan_payload(advertiser["id"], approved["version"], **BASELINE_PLAN),
            ACCOUNT_MANAGER,
        )
    )

    response = api_client.create_budget_plan(
        f.budget_plan_payload(
            advertiser["id"], version_read_before_the_decision, **SECOND_PLAN
        ),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ERR_STALE_ADVERTISER_VERSION)

    current = get_success_data(api_client.get_advertiser(advertiser["id"], NETWORK_ADMIN))
    assert current["onboarding_status"] == "ACTIVE"
    assert current["credit_exposure_cents"] == 0
    held = get_success_data(api_client.get_budget_plan(first_plan["id"], NETWORK_ADMIN))
    assert held["plan_status"] == "DRAFT"
    assert held["available_cents"] == 2000000


# --- The second product assignment on a superseded line item read ----------


def test_a_product_assignment_quoting_a_superseded_line_item_version_is_refused():
    """A second assignment quoting the line item's creation version is refused.

    PRD 3.4: "The assignment is born `ACTIVE` with a null `removed_at`, and its creation
    recomputes the line item's `eligible_product_count`, `relevance_score` and
    `quality_adjusted_score` and increments the line item's `version` by 1."

    PRD 2.7: "Creating a product assignment requires `expected_line_item_version` to
    equal the parent line item's current `version`. A new assignment marked as the hero
    product supersedes the previous hero on the same line item, so a stale writer would
    demote a hero product chosen after its read."

    Design: Corner/cross_cutting_complexity_layers/a_second_product_assignment_on_the_line_item_version_read_before_the_first_returns_412
    """
    world = build_baseline_campaign_world()
    build_line_item(world, **BASELINE_LINE_ITEM_A)
    version_read_at_creation = world["line_item"]["version"]
    build_catalog_product(world, key="product_b", **BASELINE_PRODUCT_B)

    response = api_client.create_product_assignment(
        f.product_assignment_payload(
            world["line_item"]["id"],
            world["product_b"]["id"],
            version_read_at_creation,
            is_hero=True,
        ),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ERR_STALE_LINE_ITEM_VERSION)

    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "DRAFT"
    assert line_item["eligible_product_count"] == 1


# --- The second manual deduction on a superseded pool read -----------------

POOL_ACCRUAL_CENTS = 500000
PLAN_TRADE_FUND_SHARE_CENTS = 200000
MANUAL_DEDUCTION_CENTS = 10000


def test_a_manual_deduction_quoting_a_superseded_pool_version_is_refused():
    """A second draw quoting the pool version the first draw moved is refused.

    PRD 3.4: "A manual deduction, posted with `deduction_amount_cents`, a mandatory
    `deduction_reference` and the mandatory `expected_trade_fund_account_version`, moves
    the amount from `available_cents` to `deducted_cents` and requires `available_cents`
    to be at least the requested amount".

    PRD 2.2: "`version`, an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row — including mutations the row
    suffers as a bystander in somebody else's cascade."

    PRD 2.7: "Posting a manual trade fund deduction requires
    `expected_trade_fund_account_version` to equal the target pool's current `version`."

    The pool still holds 290,000 drawable cents against a 10,000-cent request, so the
    funding rule cannot be what refuses the second draw.

    Design: Corner/cross_cutting_complexity_layers/a_second_manual_deduction_on_the_pool_version_read_before_the_first_returns_412
    """
    world = build_baseline_advertiser()
    build_trade_fund_pool(world, accrual_cents=POOL_ACCRUAL_CENTS, deduction_cap_pct=0.6)
    build_baseline_plan(world, trade_fund_share_cents=PLAN_TRADE_FUND_SHARE_CENTS)
    version_read_before_the_first_draw = reread_pool(world)["version"]

    validate_success(
        api_client.post_trade_fund_deduction(
            world["pool"]["id"],
            f.deduction_payload(
                MANUAL_DEDUCTION_CENTS,
                version_read_before_the_first_draw,
                deduction_reference="MAN-DED-A",
            ),
            BILLING_OPS,
        )
    )

    response = api_client.post_trade_fund_deduction(
        world["pool"]["id"],
        f.deduction_payload(
            MANUAL_DEDUCTION_CENTS,
            version_read_before_the_first_draw,
            deduction_reference="MAN-DED-B",
        ),
        BILLING_OPS,
    )
    validate_error(response, ERR_STALE_TRADE_FUND_VERSION)

    pool = reread_pool(world)
    assert pool["accrued_cents"] == 500000
    assert pool["reserved_cents"] == 200000
    assert pool["deducted_cents"] == 10000
    assert pool["available_cents"] == 290000
    assert pool["account_status"] == "OPEN"
    assert_trade_fund_identity(pool)


# --- The second dispute on a superseded invoice read -----------------------

FIRST_DISPUTE_CLAIM_CENTS = 50
SECOND_DISPUTE_CLAIM_CENTS = 40


def test_a_dispute_quoting_a_superseded_invoice_version_is_refused():
    """A second filing quoting the pre-dispute invoice version is refused.

    PRD 3.9: "Filing increments the invoice's `version` by 1."

    PRD 2.7: "Filing a measurement dispute requires `expected_invoice_version` to equal
    the target invoice's current `version`."

    Design: Corner/cross_cutting_complexity_layers/a_second_dispute_on_the_invoice_version_read_before_the_first_returns_412
    """
    world = build_baseline_billing_world()
    build_baseline_draft_invoice(world)
    validate_success(
        api_client.issue_invoice(
            world["invoice"]["id"], {"issue_note": "period closed"}, BILLING_OPS
        )
    )
    version_read_before_the_first_filing = reread_invoice(world)["version"]

    first_dispute = get_success_data(
        api_client.create_measurement_dispute(
            f.measurement_dispute_payload(
                world["invoice"]["id"],
                version_read_before_the_first_filing,
                dispute_category="IMPRESSION_DISCREPANCY",
                claimed_amount_cents=FIRST_DISPUTE_CLAIM_CENTS,
            ),
            ACCOUNT_MANAGER,
        )
    )

    response = api_client.create_measurement_dispute(
        f.measurement_dispute_payload(
            world["invoice"]["id"],
            version_read_before_the_first_filing,
            dispute_category="ATTRIBUTION_WINDOW",
            claimed_amount_cents=SECOND_DISPUTE_CLAIM_CENTS,
            line_item_id=world["line_item"]["id"],
            evidence_note="Second filing on a stale read",
        ),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ERR_STALE_INVOICE_VERSION)

    invoice = reread_invoice(world)
    assert invoice["invoice_status"] == "DISPUTED"
    assert invoice["net_cash_due_cents"] == 227
    held = get_success_data(
        api_client.get_measurement_dispute(first_dispute["id"], ACCOUNT_MANAGER)
    )
    assert held["dispute_status"] == "SUBMITTED"
    assert held["claimed_amount_cents"] == 50
    assert reread_campaign(world)["billing_status"] == "DISPUTED"


# --- The second study on a superseded campaign read -----------------------

FIRST_STUDY = {
    "design_method": "GEO_HOLDOUT",
    "holdout_pct": 0.1,
    "window_start_at": "2026-08-01T00:00:00Z",
    "window_end_at": "2026-08-08T00:00:00Z",
}
SECOND_STUDY = {
    "design_method": "USER_HOLDOUT",
    "holdout_pct": 0.1,
    "window_start_at": "2026-08-10T00:00:00Z",
    "window_end_at": "2026-08-17T00:00:00Z",
}


def test_a_study_design_quoting_a_superseded_campaign_version_is_refused():
    """A second design quoting the campaign version the first design moved is refused.

    PRD 3.7: "design increments the campaign's `version` by 1."

    PRD 2.7: "Designing an incrementality study requires `expected_campaign_version` to
    equal the parent campaign's current `version`."

    PRD 2.4: "A stale parent version is detected *after* existence but *before* any
    state or business check, so a client that both holds a stale version and requests an
    undeclared transition sees the stale-version code, not the transition code."

    Design: Corner/cross_cutting_complexity_layers/a_second_study_on_the_campaign_version_read_before_the_first_returns_412
    """
    world = build_baseline_delivering_world()
    version_read_before_the_first_design = reread_campaign(world)["version"]

    first_study = get_success_data(
        api_client.create_incrementality_study(
            f.incrementality_study_payload(
                world["campaign"]["id"],
                version_read_before_the_first_design,
                **FIRST_STUDY,
            ),
            MEASUREMENT_ANALYST,
        )
    )
    world["study"] = first_study

    response = api_client.create_incrementality_study(
        f.incrementality_study_payload(
            world["campaign"]["id"],
            version_read_before_the_first_design,
            **SECOND_STUDY,
        ),
        MEASUREMENT_ANALYST,
    )
    validate_error(response, ERR_STALE_CAMPAIGN_VERSION)

    study = reread_study(world)
    assert study["study_status"] == "DESIGNED"
    assert study["design_method"] == "GEO_HOLDOUT"
    campaign = reread_campaign(world)
    assert campaign["delivery_status"] == "DELIVERING"
    assert campaign["incremental_revenue_cents"] == 0


# --- One hundred cents of off-site spend, three levels of consequence ------

EXHAUSTION_PLAN = {"committed_total_cents": 1000100}
EXHAUSTION_SLOT = {
    "slot_code": "OFF-D1",
    "channel": "OFFSITE",
    "page_type": "OFFSITE_DISPLAY",
    "buffer_minutes": 0,
}
EXHAUSTION_CAMPAIGN = {"name": "Offsite Boundary", "channel_mix": "OFFSITE_ONLY"}
EXHAUSTION_LINE_ITEM = {"daily_budget_cents": 100}
OFFSITE_REPORTED_SPEND_CENTS = 100


def test_one_hundred_cents_of_offsite_spend_exhausts_the_plan_and_cascades():
    """The posting that drives headroom to exactly zero pauses two levels below it.

    PRD 3.2: "`consumed_cents` is the sum of `settled_spend_cents` over settled auctions
    whose winning line item belongs to a campaign on this plan, plus the sum of
    `offsite_reported_spend_cents` over the plan's campaigns whose `delivery_status` is
    not `REJECTED`."

    PRD 3.2: "When a recomputation following an auction settlement or an off-site spend
    posting yields `available_cents` of 0 or less, the plan moves to `EXHAUSTED` and
    `exhausted_at` is stamped with the current logical time. That transition cascades
    two levels: every campaign on the plan whose `delivery_status` is `DELIVERING` moves
    to `PAUSED`, and each of those campaigns moves every one of its own `SERVING` line
    items to `MANUAL_PAUSED` with `pause_reason` set to `BUDGET_EXHAUSTED`."

    PRD 3.8: "`offsite_variance_pct` is ... exactly 100.00 when the logged figure is 0
    but the reported figure is positive".

    The plan commits 1,000,100 cents against a 1,000,000-cent reservation, so exactly
    100 cents of reported off-site spend lands headroom on the boundary itself.

    Design: Corner/cross_cutting_complexity_layers/an_offsite_spend_posting_of_one_hundred_cents_exhausts_the_plan_and_cascades_three_levels
    """
    world = build_baseline_delivering_world(
        offsite=True,
        plan=EXHAUSTION_PLAN,
        slot=EXHAUSTION_SLOT,
        campaign=EXHAUSTION_CAMPAIGN,
        line_item=EXHAUSTION_LINE_ITEM,
    )

    response = api_client.post_campaign_offsite_reconciliation(
        world["campaign"]["id"],
        f.offsite_reconciliation_payload(
            OFFSITE_REPORTED_SPEND_CENTS, reporting_partner_code="PARTNER-A"
        ),
        BILLING_OPS,
    )
    validate_success(response)

    campaign = reread_campaign(world)
    assert campaign["offsite_reported_spend_cents"] == 100
    assert campaign["offsite_variance_pct"] == 100.00
    assert campaign["delivery_status"] == "PAUSED"
    assert campaign["billing_status"] == "ACCRUING"
    assert campaign["delivered_spend_cents"] == 0

    plan = reread_plan(world)
    assert plan["consumed_cents"] == 100
    assert plan["reserved_cents"] == 1000000
    assert plan["available_cents"] == 0
    assert plan["plan_status"] == "EXHAUSTED"
    assert parse_utc(plan["exhausted_at"]) == parse_utc("2026-08-01T00:00:00Z")
    assert_budget_plan_identity(plan)

    assert_line_item_paused(reread_line_item(world), "MANUAL_PAUSED", "BUDGET_EXHAUSTED")
    assert_occupancy_count(reread_slot(world), 1)
