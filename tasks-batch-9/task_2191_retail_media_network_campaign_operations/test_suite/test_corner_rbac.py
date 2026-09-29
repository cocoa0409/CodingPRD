"""Who may call what, and who may not — including the calls that must succeed.

The endpoint table in §4 names the authorised roles for every path, and the rejection
order in §2.12 decides which refusal a caller sees. These tests take both sides: two
roles that are heavy legitimate users of the surrounding resources but absent from one
endpoint's list, an advertiser seat that clears the role check and fails the ownership
check that follows it, an operator barred from deciding a step it submitted itself, and
two roles exercising authority the table does grant them.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUCTION_SERVICE,
    BILLING_OPS,
    CREDIT_ANALYST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    NETWORK_ADMIN,
    OPERATOR_USER_IDS,
    ROLE_NETWORK_ADMIN,
    api_client,
    assert_occupancy_count,
    factories as f,
    make_advertiser_user_headers,
    reread_campaign,
    reread_line_item,
    reread_plan,
    reread_slot,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    build_draft_budget_plan,
    build_pending_eligibility_line_item,
    build_second_active_advertiser,
)
from test_helpers.fixtures_corner_rbac import (
    BASELINE_LINE_ITEM_A,
    BASELINE_PLAN,
    build_baseline_advertiser,
    build_baseline_awarded_auction,
    build_baseline_campaign_world,
    build_baseline_delivering_world,
    build_baseline_plan,
    build_baseline_second_line_item,
    build_baseline_settled_auction,
)

# --- The catalog eligibility fork ------------------------------------------


def test_billing_ops_calling_the_catalog_eligibility_fork_is_forbidden():
    """The money role cannot render the catalog's eligibility decision.

    PRD 3.5: "The eligibility fork is rendered by `CatalogOps` or `NetworkAdmin` with a
    `decision` of `APPROVE` or `REJECT` and an optional `decision_note`."

    PRD 2.12: "The acting role appears in the target endpoint's authorised-role list, on
    every request — otherwise `ERR_ROLE_NOT_PERMITTED`, 403."

    Design: Corner/rbac/billing_ops_calling_the_catalog_eligibility_fork_is_forbidden
    """
    world = build_baseline_campaign_world()
    build_pending_eligibility_line_item(world, **BASELINE_LINE_ITEM_A)

    response = api_client.decide_line_item_eligibility(
        world["line_item"]["id"], f.decision_payload("APPROVE"), BILLING_OPS
    )
    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "PENDING_ELIGIBILITY"
    assert line_item["reserved_cents"] == 0
    assert_occupancy_count(reread_slot(world), 0)


# --- Closed-loop revenue ---------------------------------------------------

SALE_CENTS = 50000
SALE_OCCURRED_AT = "2026-08-02T00:00:00Z"


def test_the_auction_service_cannot_post_attributed_sales():
    """The ad server may settle the auction but may not write the retail sale.

    PRD 4: "| POST | /rmn/attributed-sales | Closes the loop by matching a retail order
    line back to an engagement event and crediting it under the campaign's attribution
    model. | NetworkAdmin, MeasurementAnalyst |"

    PRD 2.12: "The acting role appears in the target endpoint's authorised-role list, on
    every request — otherwise `ERR_ROLE_NOT_PERMITTED`, 403."

    Design: Corner/rbac/the_auction_service_cannot_post_attributed_sales_and_is_forbidden
    """
    world = build_baseline_delivering_world()
    build_baseline_second_line_item(world)
    build_baseline_settled_auction(world)
    first_click = world["engagements"][1]

    response = api_client.create_attributed_sale(
        f.attributed_sale_payload(
            first_click["id"],
            world["product"]["id"],
            sale_cents=SALE_CENTS,
            occurred_at=SALE_OCCURRED_AT,
            retail_order_ref="RO-3001",
            match_type="CLICK_THROUGH",
        ),
        AUCTION_SERVICE,
    )
    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    campaign = reread_campaign(world)
    assert campaign["attributed_revenue_cents"] == 0
    assert campaign["delivered_spend_cents"] == 284
    assert world["auction"]["status"] == "SETTLED"


# --- Suspension is the credit analyst's own authority ----------------------

FUTURE_PLAN = {
    "fiscal_period_code": "2026-Q4",
    "window_start_at": "2026-10-01T00:00:00Z",
    "window_end_at": "2027-01-01T00:00:00Z",
}


def test_the_credit_analyst_exercises_its_exclusive_suspension_authority():
    """A credit analyst suspends an active advertiser and the plan is left alone.

    PRD 4: "| POST | /rmn/advertisers/{id}/suspend | Suspends an ACTIVE advertiser and
    runs the depth-3 suspension cascade. | NetworkAdmin, CreditAnalyst |"

    PRD 3.1: "A `CreditAnalyst` or `NetworkAdmin` suspends an `ACTIVE` advertiser,
    supplying `suspension_reason` as one of `CREDIT_BREACH`, `COMPLIANCE` or `MANUAL`; the
    system itself suspends with `CREDIT_BREACH` when invoice issuance drives exposure past
    the limit."

    PRD 3.1: "It is the sum of `committed_total_cents` over the advertiser's own budget
    plans whose `plan_status` is `APPROVED`, `ACTIVE` or `EXHAUSTED`, plus the sum of
    `net_cash_due_cents` over the advertiser's own invoices whose `invoice_status` is
    `ISSUED`, `DISPUTED` or `ADJUSTED`."

    The plan's window opens after the current logical time, so approval leaves it in
    `APPROVED` and the suspension has no campaign to cascade into.

    Design: Corner/rbac/credit_analyst_exercises_its_exclusive_suspension_authority
    """
    world = build_baseline_advertiser()
    build_baseline_plan(world, **FUTURE_PLAN)

    suspended = validate_success(
        api_client.suspend_advertiser(
            world["advertiser"]["id"], {"suspension_reason": "CREDIT_BREACH"},
            CREDIT_ANALYST,
        )
    )
    assert suspended["onboarding_status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "CREDIT_BREACH"
    assert suspended["credit_exposure_cents"] == 2000000

    plan = reread_plan(world)
    assert plan["plan_status"] == "APPROVED"
    assert plan["available_cents"] == 2000000


# --- Segregation of duties binds the superuser too ------------------------


def test_a_network_admin_that_submitted_a_budget_plan_cannot_also_approve_it():
    """The one operator on both sides of the plan chain is refused, superuser or not.

    PRD 2.11: "The acting `X-User-ID` must differ from the operator recorded for the
    preceding step: the advertiser's `onboarding_submitted_by_user_id` when a KYC
    decision is rendered; the plan's `submitted_by_user_id` when a budget plan is
    approved; the campaign's `submitted_for_review_by_user_id` when a campaign review
    decision is rendered; the invoice's `issued_by_user_id` when an invoice is written
    off; and the `published_by_user_id` of the campaign's most recent published
    incrementality study when a dispute whose category is `INCREMENTALITY_RESTATEMENT`
    is resolved."

    PRD 2.11: "The rule binds every role including `NetworkAdmin`."

    PRD 2.12: "On KYC decision, plan approval, campaign review decision, invoice
    write-off and dispute resolution: the segregation-of-duties rule of §2.11 holds —
    otherwise `ERR_SEGREGATION_OF_DUTIES`, 403."

    Design: Corner/rbac/a_network_admin_that_submitted_a_budget_plan_cannot_also_approve_it
    """
    world = build_baseline_advertiser()
    build_draft_budget_plan(world, **BASELINE_PLAN)
    world["plan"] = validate_success(
        api_client.submit_budget_plan(
            world["plan"]["id"], {"submission_note": "quarterly commitment"},
            NETWORK_ADMIN,
        )
    )

    response = api_client.approve_budget_plan(
        world["plan"]["id"], {"approval_note": "Self approval attempt"}, NETWORK_ADMIN
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES)

    plan = reread_plan(world)
    assert plan["plan_status"] == "PENDING_APPROVAL"
    assert plan["submitted_by_user_id"] == OPERATOR_USER_IDS[ROLE_NETWORK_ADMIN]
    assert plan["approved_by_user_id"] is None
    assert validate_success(
        api_client.get_advertiser(world["advertiser"]["id"], NETWORK_ADMIN)
    )["credit_exposure_cents"] == 0


# --- Settlement is a shared operation -------------------------------------


def test_billing_ops_may_settle_an_awarded_auction():
    """The money role closes the auction the ad server opened, ranked and awarded.

    PRD 4: "| POST | /rmn/auction-events/{id}/settle | Settles an AWARDED or NO_FILL
    auction, charging the winner and running the depth-3 budget-exhaustion cascade when
    the plan drains. | NetworkAdmin, AuctionService, BillingOps |"

    PRD 3.6: "Under `CPC`, only `CLICK` events are billable: `settled_spend_cents` is
    `clearing_price_cents` multiplied by the count of `CLICK` events on the auction, each
    `CLICK` event's `billable_cents` is set to the full `clearing_price_cents`, and every
    `IMPRESSION` and `OFFSITE_VIEW` event's `billable_cents` is set to 0."

    PRD 3.6: "Level one adds `settled_spend_cents` to the winning line item's
    `spend_cents` and to its campaign's `delivered_spend_cents`."

    Design: Corner/rbac/billing_ops_may_settle_an_awarded_auction_as_a_shared_operation
    """
    world = build_baseline_delivering_world()
    build_baseline_second_line_item(world)
    build_baseline_awarded_auction(world)

    settled = validate_success(
        api_client.settle_auction_event(world["auction"]["id"], None, BILLING_OPS)
    )
    assert settled["status"] == "SETTLED"
    assert settled["clearing_price_cents"] == 142
    assert settled["settled_spend_cents"] == 284

    assert reread_line_item(world)["spend_cents"] == 284
    assert reread_campaign(world)["delivered_spend_cents"] == 284
    assert reread_plan(world)["available_cents"] == 999716


# --- The advertiser seat is scoped to its own advertiser -------------------


PEER_ADVERTISER = {"legal_name": "Thinmargin Grocers LLC", "credit_limit_cents": 3000000}


def test_an_advertiser_seat_reading_another_advertisers_campaign_is_not_the_owner():
    """A seat listed on the endpoint is still stopped by the ownership check.

    PRD 2.12: "On every endpoint whose authorised roles include `AdvertiserUser`: when
    the acting role is `AdvertiserUser`, `X-User-ID` equals the advertiser that owns the
    targeted resource, resolved through a campaign reference to that campaign's
    advertiser, through a line-item reference to its campaign's advertiser, through an
    invoice reference to that invoice's advertiser, and through a budget-plan reference
    to that plan's advertiser — otherwise `ERR_NOT_RESOURCE_OWNER`, 403."

    PRD 4: "| GET | /rmn/campaigns/{id} | Reads one campaign including both parallel
    status dimensions and its closed-loop measurement fields. | NetworkAdmin,
    AccountManager, MeasurementAnalyst, BillingOps, AdvertiserUser |"

    Design: Corner/rbac/an_advertiser_seat_reading_another_advertisers_campaign_is_not_the_resource_owner
    """
    world = build_baseline_campaign_world()
    build_second_active_advertiser(world, **PEER_ADVERTISER)
    peer_seat = make_advertiser_user_headers(world["other_advertiser"]["id"])

    response = api_client.get_campaign(world["campaign"]["id"], peer_seat)
    validate_error(response, ERR_NOT_RESOURCE_OWNER)

    campaign = validate_success(
        api_client.get_campaign(world["campaign"]["id"], ACCOUNT_MANAGER)
    )
    assert campaign["advertiser_id"] == world["advertiser"]["id"]
    assert campaign["delivery_status"] == "DRAFT"
