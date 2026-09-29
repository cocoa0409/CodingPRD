"""One call each on the surfaces the rest of the suite only passes through.

Two computed reads that must project figures they never store, an amendment that may
rewrite a draft campaign's commercial settings without disturbing either status
dimension or the plan behind it, the exact-amount settlement gate, the write-off that
compensates an issuance down to the last cent of the fund identity, and the sale
ingestion that derives its own line-item link from the engagement it credits.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    BILLING_OPS,
    CREDIT_ANALYST,
    ERR_SETTLEMENT_AMOUNT_MISMATCH,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    api_client,
    assert_trade_fund_identity,
    factories as f,
    get_success_data,
    reread_campaign,
    reread_invoice,
    reread_plan,
    reread_pool,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import build_child_advertiser
from test_helpers.fixtures_corner_rbac import (
    BASELINE_PLAN,
    build_baseline_advertiser,
    build_baseline_billing_world,
    build_baseline_campaign_world,
    build_baseline_delivering_world,
    build_baseline_draft_invoice,
    build_baseline_second_line_item,
    build_baseline_settled_auction,
)

SALE_CENTS = 50000
SALE_OCCURRED_AT = "2026-08-02T00:00:00Z"

# --- The campaign performance read -----------------------------------------


def test_campaign_performance_summary_returns_settled_spend_and_attributed_revenue():
    """The summary projects both the auction spend and the closed-loop revenue.

    PRD 4: "| GET | /rmn/campaigns/{id}/performance-summary | Computed read returning
    delivered spend, attributed revenue, incremental revenue, roas, iroas and
    pacing_index for the campaign. | NetworkAdmin, AccountManager, MeasurementAnalyst,
    BillingOps, AdvertiserUser |"

    PRD 3.6: "Level one adds `settled_spend_cents` to the winning line item's
    `spend_cents` and to its campaign's `delivered_spend_cents`."

    PRD 3.6: "A campaign's `attributed_revenue_cents` is the sum of the already-rounded
    `attributed_credit_cents` across its attributed sales whose `restated` is false."

    PRD 3.6: "`roas` is `attributed_revenue_cents` divided by the sum of
    `delivered_spend_cents` and `offsite_reported_spend_cents`, rounded half-up to four
    decimal places, and is 0.0 when that denominator is 0."

    Design: Corner/endpoints/campaign_performance_summary_read_returns_settled_spend_and_attributed_revenue
    """
    world = build_baseline_delivering_world()
    build_baseline_second_line_item(world)
    build_baseline_settled_auction(world)
    credited_click = world["engagements"][1]
    sale = get_success_data(
        api_client.create_attributed_sale(
            f.attributed_sale_payload(
                credited_click["id"],
                world["product"]["id"],
                sale_cents=SALE_CENTS,
                occurred_at=SALE_OCCURRED_AT,
                retail_order_ref="RO-2001",
                match_type="CLICK_THROUGH",
            ),
            MEASUREMENT_ANALYST,
        )
    )

    summary = validate_success(
        api_client.get_campaign_performance_summary(
            world["campaign"]["id"], MEASUREMENT_ANALYST
        )
    )
    assert summary["delivered_spend_cents"] == 284
    assert summary["attributed_revenue_cents"] == 50000
    assert summary["incremental_revenue_cents"] == 0
    assert summary["roas"] == 176.0563
    assert summary["iroas"] == 0.0

    campaign = reread_campaign(world)
    assert campaign["offsite_reported_spend_cents"] == 0
    assert campaign["oos_paused_line_item_count"] == 0
    assert campaign["delivery_status"] == "DELIVERING"
    assert campaign["billing_status"] == "ACCRUING"

    held = validate_success(
        api_client.get_attributed_sale(sale["id"], MEASUREMENT_ANALYST)
    )
    assert held["attributed_credit_cents"] == 50000


# --- The credit summary of an umbrella child -------------------------------

CHILD_ADVERTISER = {
    "legal_name": "Nordvale Kids LLC",
    "service_model": "SELF_SERVE",
    "credit_limit_cents": 100000,
    "self_serve_daily_spend_cap_cents": 5000000,
}


def test_child_advertiser_credit_summary_shows_own_exposure_without_rolling_up():
    """A child borrows the parent's limit but keeps its exposure to itself.

    PRD 3.1: "A child does not roll up into the parent's exposure, but a child evaluates
    its own exposure against the **parent's** `credit_limit_cents` rather than its own."

    PRD 3.1: "It is the sum of `committed_total_cents` over the advertiser's own budget
    plans whose `plan_status` is `APPROVED`, `ACTIVE` or `EXHAUSTED`, plus the sum of
    `net_cash_due_cents` over the advertiser's own invoices whose `invoice_status` is
    `ISSUED`, `DISPUTED` or `ADJUSTED`."

    PRD 2.12: "On plan approval: the advertiser's `credit_exposure_cents` plus the plan's
    `cash_share_cents` does not exceed the effective credit limit, which is the parent
    advertiser's `credit_limit_cents` when `parent_advertiser_id` is non-null and the
    advertiser's own `credit_limit_cents` otherwise — otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED`, 402."

    PRD 3.2: "The approved plan lands in `APPROVED`; when the current logical time is
    already at or after `window_start_at` and the advertiser is `ACTIVE`, it is promoted
    to `ACTIVE` in the same request."

    A 2,000,000-cent commitment is twenty times the child's own 100,000-cent limit and
    approves anyway, which is only possible if the parent's limit is the one being read.

    Design: Corner/endpoints/child_advertiser_credit_summary_shows_own_exposure_without_rolling_up_to_the_parent
    """
    world = build_baseline_advertiser()
    build_child_advertiser(world, **CHILD_ADVERTISER)
    child = world["child_advertiser"]

    plan = get_success_data(
        api_client.create_budget_plan(
            f.budget_plan_payload(child["id"], child["version"], **BASELINE_PLAN),
            ACCOUNT_MANAGER,
        )
    )
    get_success_data(
        api_client.submit_budget_plan(
            plan["id"], {"submission_note": "quarterly commitment"}, ACCOUNT_MANAGER
        )
    )
    approved = get_success_data(
        api_client.approve_budget_plan(
            plan["id"], {"approval_note": "backed by the parent limit"}, CREDIT_ANALYST
        )
    )
    assert approved["plan_status"] == "ACTIVE"

    summary = validate_success(
        api_client.get_advertiser_credit_summary(child["id"], CREDIT_ANALYST)
    )
    assert summary["credit_exposure_cents"] == 2000000
    assert summary["dispute_credit_balance_cents"] == 0

    held_child = validate_success(api_client.get_advertiser(child["id"], NETWORK_ADMIN))
    assert held_child["credit_limit_cents"] == 100000
    assert held_child["onboarding_status"] == "ACTIVE"
    assert held_child["credit_exposure_cents"] == 2000000

    parent = validate_success(
        api_client.get_advertiser(world["advertiser"]["id"], NETWORK_ADMIN)
    )
    assert parent["credit_exposure_cents"] == 0


# --- Amending a draft campaign ---------------------------------------------

CAMPAIGN_AMENDMENT = {
    "name": "Back to School v2",
    "daily_cap_cents": 150000,
    "attribution_window_days": 7,
    "pacing_mode": "ACCELERATED",
}


def test_patching_a_draft_campaign_amends_cap_and_window_without_touching_delivery():
    """The amendment rewrites the commercial settings and nothing else moves.

    PRD 3.3: "Amendment, available to the same three roles, optionally accepts `name`,
    `flight_start_at`, `flight_end_at`, `allocated_budget_cents`, `pacing_mode`,
    `daily_cap_cents`, `attribution_model`, `attribution_window_days` and `channel_mix`;
    omitted fields are left untouched and the containment, cap and channel rules are
    re-applied to the resulting combination."

    PRD 2.2: "`version`, an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row — including mutations the row
    suffers as a bystander in somebody else's cascade."

    PRD 3.3: "`APPROVE` additionally requires the advertiser to be `ACTIVE` and the
    current logical time to be strictly before `flight_end_at`; it lands the campaign in
    `SCHEDULED`, at which point `allocated_budget_cents` becomes reserved, so the plan's
    `reserved_cents` and `available_cents` are recomputed and the advertiser's exposure
    is recomputed with it."

    The campaign has never been reviewed, so no reservation exists yet and the plan's
    headroom must still be the full commitment.

    Design: Corner/endpoints/patching_a_draft_campaign_amends_cap_and_attribution_window_without_touching_delivery
    """
    world = build_baseline_campaign_world()
    version_before_the_amendment = world["campaign"]["version"]

    amended = validate_success(
        api_client.update_campaign(
            world["campaign"]["id"], CAMPAIGN_AMENDMENT, ACCOUNT_MANAGER
        )
    )
    assert amended["name"] == "Back to School v2"
    assert amended["daily_cap_cents"] == 150000
    assert amended["attribution_window_days"] == 7
    assert amended["pacing_mode"] == "ACCELERATED"
    assert amended["delivery_status"] == "DRAFT"
    assert amended["billing_status"] == "UNBILLED"
    assert amended["allocated_budget_cents"] == 1000000
    assert amended["version"] == version_before_the_amendment + 1

    assert reread_plan(world)["available_cents"] == 2000000


# --- Settlement is exact-amount only --------------------------------------

SHORT_PAYMENT_CENTS = 226


def test_settling_an_invoice_one_cent_short_of_net_cash_due_is_rejected():
    """A cent short is a refusal, not a partial payment.

    PRD 3.8: "It requires that no dispute on the invoice be in `SUBMITTED`,
    `UNDER_REVIEW`, `INFO_REQUESTED` or `ESCALATED`, and that `paid_amount_cents` equal
    `net_cash_due_cents` exactly — partial payment and overpayment are both refused."

    PRD 2.12: "On invoice settlement: `paid_amount_cents` equals the invoice's
    `net_cash_due_cents` exactly — otherwise `ERR_SETTLEMENT_AMOUNT_MISMATCH`, 422."

    PRD 3.8: "It stamps `settled_at`, moves every campaign on the plan whose
    `billing_status` is `INVOICED` or `DISPUTED` to `RECONCILED` with `roas` and `iroas`
    recomputed, and recomputes the advertiser's `credit_exposure_cents` and
    `dispute_credit_balance_cents`."

    Design: Corner/endpoints/settling_an_invoice_with_one_cent_short_of_net_cash_due_is_rejected
    """
    world = build_baseline_billing_world()
    build_baseline_draft_invoice(world)
    issued = validate_success(
        api_client.issue_invoice(
            world["invoice"]["id"], {"issue_note": "August close"}, BILLING_OPS
        )
    )
    assert issued["net_cash_due_cents"] == 227

    response = api_client.settle_invoice(
        world["invoice"]["id"],
        {"paid_amount_cents": SHORT_PAYMENT_CENTS, "payment_reference": "WIRE-0001"},
        BILLING_OPS,
    )
    validate_error(response, ERR_SETTLEMENT_AMOUNT_MISMATCH)

    invoice = reread_invoice(world)
    assert invoice["invoice_status"] == "ISSUED"
    assert invoice["net_cash_due_cents"] == 227
    assert invoice["settled_at"] is None
    assert reread_campaign(world)["billing_status"] == "INVOICED"
    advertiser = validate_success(
        api_client.get_advertiser(world["advertiser"]["id"], NETWORK_ADMIN)
    )
    assert advertiser["credit_exposure_cents"] == 2000227


# --- Write-off is the compensating transaction ----------------------------

WRITE_OFF_INSTANT = "2026-10-30T00:00:00Z"


def test_writing_off_an_overdue_invoice_restores_the_trade_fund_identity():
    """Sixty days past due, the write-off returns the deduction cent for cent.

    PRD 3.8: "It requires the current logical time to be at or after `due_at` plus sixty
    days and requires the acting `X-User-ID` to differ from `issued_by_user_id`."

    PRD 3.8: "It is the compensating transaction for issuance and conserves the pool
    identity: the full `trade_fund_deduction_cents` — the post-adjustment figure when the
    invoice passed through `ADJUSTED` — moves back from the pool's `deducted_cents` to
    its `available_cents`, restoring the invariant that `accrued_cents` equals
    `available_cents` plus `reserved_cents` plus `deducted_cents`."

    PRD 3.8: "Every campaign on the plan whose `billing_status` is `INVOICED` or
    `DISPUTED` moves to `RECONCILED`, the advertiser's `credit_exposure_cents` is
    recomputed, and an advertiser whose `onboarding_status` is `ACTIVE` is suspended with
    `suspension_reason` `CREDIT_BREACH`, because a written-off invoice is by definition a
    credit failure."

    PRD 3.8: "It stamps `issued_at` with the current logical time, `due_at` thirty days
    later, and `issued_by_user_id` with the acting `X-User-ID`, and it moves every
    campaign on the plan whose `billing_status` is `PENDING_INVOICE` to `INVOICED`."

    Issuance happens at 2026-08-01, so the due date is 2026-08-31 and the write-off
    window opens exactly at 2026-10-30.

    Design: Corner/endpoints/writing_off_an_overdue_invoice_restores_the_trade_fund_identity_and_reconciles_campaigns
    """
    world = build_baseline_billing_world()
    build_baseline_draft_invoice(world)
    validate_success(
        api_client.issue_invoice(
            world["invoice"]["id"], {"issue_note": "August close"}, BILLING_OPS
        )
    )
    set_clock(world, WRITE_OFF_INSTANT)

    written_off = validate_success(
        api_client.write_off_invoice(
            world["invoice"]["id"],
            {"write_off_reason": "Uncollectible after 60 days"},
            NETWORK_ADMIN,
        )
    )
    assert written_off["invoice_status"] == "WRITTEN_OFF"
    assert written_off["trade_fund_deduction_cents"] == 57
    assert written_off["net_cash_due_cents"] == 227

    pool = reread_pool(world)
    assert pool["accrued_cents"] == 500000
    assert pool["reserved_cents"] == 200000
    assert pool["deducted_cents"] == 0
    assert pool["available_cents"] == 300000
    assert pool["account_status"] == "OPEN"
    assert_trade_fund_identity(pool)

    assert reread_campaign(world)["billing_status"] == "RECONCILED"
    advertiser = validate_success(
        api_client.get_advertiser(world["advertiser"]["id"], NETWORK_ADMIN)
    )
    assert advertiser["credit_exposure_cents"] == 2000000
    assert advertiser["onboarding_status"] == "SUSPENDED"
    assert advertiser["suspension_reason"] == "CREDIT_BREACH"


# --- The sale derives its own line-item link ------------------------------


def test_attributed_sale_creation_copies_the_line_item_link_from_the_engagement():
    """The request names an engagement and a product; the link and the model are derived.

    PRD 3.6: "`line_item_id` is not supplied; it is copied from the referenced engagement
    event."

    PRD 3.6: "`match_type` must be supplied but the persisted value is always derived: it
    is `CLICK_THROUGH` when the credited engagement's `event_type` is `CLICK` and
    `VIEW_THROUGH` for an `IMPRESSION` or `OFFSITE_VIEW`."

    PRD 3.6: "`attribution_model_applied` records which of the campaign's two models was
    in force when the credit was computed, and it is never taken from the request."

    PRD 3.6: "`within_window` is true when the sale's `occurred_at` is at or after the
    engagement's `occurred_at` **and** the elapsed interval between them is strictly less
    than the window length; a sale landing exactly at the window boundary is therefore
    outside the window, while a sale landing at the same instant as the engagement is
    inside it."

    PRD 3.6: "Under `LAST_TOUCH` the credit goes entirely to one engagement: the
    candidate with the greatest `occurred_at`, with ties broken by `event_type` in the
    fixed precedence `CLICK` first, then `OFFSITE_VIEW`, then `IMPRESSION`, and any
    remaining tie broken by ascending `created_at`."

    The two candidates sharing this shopper are the 12:05 impression and the 12:10 click,
    so last touch credits the click the request already names.

    Design: Corner/endpoints/attributed_sale_creation_copies_the_line_item_link_from_the_credited_engagement
    """
    world = build_baseline_delivering_world()
    build_baseline_second_line_item(world)
    build_baseline_settled_auction(world)
    credited_click = world["engagements"][1]

    sale = validate_success(
        api_client.create_attributed_sale(
            f.attributed_sale_payload(
                credited_click["id"],
                world["product"]["id"],
                sale_cents=SALE_CENTS,
                occurred_at=SALE_OCCURRED_AT,
                retail_order_ref="RO-2001",
                match_type="CLICK_THROUGH",
            ),
            MEASUREMENT_ANALYST,
        ),
        201,
    )
    assert sale["line_item_id"] == world["line_item"]["id"]
    assert sale["match_type"] == "CLICK_THROUGH"
    assert sale["attribution_model_applied"] == "LAST_TOUCH"
    assert sale["within_window"] is True
    assert sale["restated"] is False
    assert sale["attribution_weight"] == 1.0
    assert sale["attributed_credit_cents"] == 50000

    assert reread_campaign(world)["attributed_revenue_cents"] == 50000
