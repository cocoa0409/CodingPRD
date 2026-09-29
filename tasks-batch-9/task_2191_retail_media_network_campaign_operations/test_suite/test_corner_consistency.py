"""Everything a write recomputes is visible in that write's own answer.

Both requests here touch several rows at once — a line item and the plan, campaign and
slot around it; an invoice, the fund pool it draws on and the campaigns it covers. The
figures the request derives are asserted from the response body itself, and the sibling
rows are read straight afterwards, so a build that defers a recomputation to a later
sweep or serves a lagging stored balance fails.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    BILLING_OPS,
    CATALOG_OPS,
    NETWORK_ADMIN,
    api_client,
    assert_trade_fund_identity,
    factories as f,
    validate_success,
)
from test_helpers.fixtures import (
    build_pending_eligibility_line_item,
    build_pending_review_campaign,
)
from test_helpers.fixtures_corner_rbac import (
    BASELINE_LINE_ITEM_A,
    build_baseline_billing_world,
    build_baseline_campaign_world,
    build_baseline_draft_invoice,
)

# --- Line item activation --------------------------------------------------


def test_line_item_activation_returns_every_recomputed_field_in_its_own_response():
    """The activation answer already carries the status, tier and reservation.

    PRD 3.5: "Activation moves an `ELIGIBLE` line item to `SERVING` and is available to
    `NetworkAdmin`, `AccountManager` and the owning `AdvertiserUser`; the system performs
    the same transition for every eligible line item when the owning campaign reaches
    `DELIVERING`. It requires the campaign to be `DELIVERING`, the advertiser to be
    `ACTIVE`, the plan to be `ACTIVE` with `available_cents` at least
    `daily_budget_cents`, the current logical time to be at or after `flight_start_at`
    and strictly before `flight_end_at`, and `eligible_product_count` of at least 1.
    Activation sets `pause_reason` to `NONE` and recomputes `priority_tier`."

    PRD 3.5: "It lands the line item in `ELIGIBLE`, raises the slot's `occupancy_count`
    by 1, and computes `reserved_cents` as `daily_budget_cents` multiplied by the number
    of whole twenty-four-hour periods in the line item's flight, with that day count
    floored at 1 — a flight shorter than a day reserves exactly one day of budget."

    PRD 3.5: "Otherwise, when the advertiser is `MANAGED` **or** the remaining ratio is
    at least 0.20, the tier is `TIER_2`."

    The line item waits in `PENDING_ELIGIBILITY` while the campaign is taken to
    `DELIVERING`, so nothing is promoted on its behalf and the activation under test is
    the operator's own call.

    Design: Corner/consistency_model/line_item_activation_returns_every_recomputed_field_in_its_own_response_with_no_reread_lag
    """
    world = build_baseline_campaign_world()
    build_pending_eligibility_line_item(world, **BASELINE_LINE_ITEM_A)
    build_pending_review_campaign(world, with_line_item=False)
    world["campaign"] = validate_success(
        api_client.decide_campaign_review(
            world["campaign"]["id"], f.decision_payload("APPROVE"), NETWORK_ADMIN
        )
    )
    world["campaign"] = validate_success(
        api_client.activate_campaign(world["campaign"]["id"], None, ACCOUNT_MANAGER)
    )
    world["line_item"] = validate_success(
        api_client.decide_line_item_eligibility(
            world["line_item"]["id"], f.decision_payload("APPROVE"), CATALOG_OPS
        )
    )

    activated = validate_success(
        api_client.activate_line_item(world["line_item"]["id"], None, ACCOUNT_MANAGER)
    )
    assert activated["line_item_status"] == "SERVING"
    assert activated["priority_tier"] == "TIER_2"
    assert activated["reserved_cents"] == 1000000

    plan = validate_success(
        api_client.get_budget_plan(world["plan"]["id"], ACCOUNT_MANAGER)
    )
    assert plan["plan_status"] == "ACTIVE"
    assert plan["reserved_cents"] == 1000000

    campaign = validate_success(
        api_client.get_campaign(world["campaign"]["id"], ACCOUNT_MANAGER)
    )
    assert campaign["delivery_status"] == "DELIVERING"
    assert campaign["billing_status"] == "ACCRUING"

    slot = validate_success(
        api_client.get_placement_slot(world["slot"]["id"], ACCOUNT_MANAGER)
    )
    assert slot["occupancy_count"] == 1


# --- Invoice issuance ------------------------------------------------------


def test_invoice_issuance_exposes_the_waterfall_and_the_fund_debit_at_once():
    """The issuance answer carries the whole waterfall and the pool is already debited.

    PRD 3.8: "The waterfall runs in ten pinned steps and the order is not negotiable,
    because each step consumes the previous step's output."

    PRD 3.8: "Step four computes `managed_service_fee_cents` as `gross_spend_cents`
    multiplied by the advertiser's `managed_service_fee_pct`, rounded half-up to whole
    cents; for a self-serve advertiser this is necessarily 0."

    PRD 3.8: "Step ten sets `net_cash_due_cents` to the billable-before-funds figure less
    `trade_fund_deduction_cents`, floored at 0."

    PRD 3.8: "`trade_fund_deduction_cents` moves out of the pool's `available_cents` and
    into its `deducted_cents`."

    PRD 3.8: "It stamps `issued_at` with the current logical time, `due_at` thirty days
    later, and `issued_by_user_id` with the acting `X-User-ID`, and it moves every
    campaign on the plan whose `billing_status` is `PENDING_INVOICE` to `INVOICED`."

    PRD 3.4: "`deducted_cents` is the sum of `trade_fund_deduction_cents` over invoices
    referencing this pool whose `invoice_status` is `ISSUED`, `DISPUTED`, `ADJUSTED` or
    `SETTLED`, plus the sum of every manual deduction posted to it; and
    `available_cents` is `accrued_cents` less `reserved_cents` less `deducted_cents`."

    Design: Corner/consistency_model/invoice_issuance_exposes_the_whole_waterfall_and_the_trade_fund_debit_within_the_same_request
    """
    world = build_baseline_billing_world()
    build_baseline_draft_invoice(world)

    issued = validate_success(
        api_client.issue_invoice(
            world["invoice"]["id"], {"issue_note": "August close"}, BILLING_OPS
        )
    )
    assert issued["gross_spend_cents"] == 284
    assert issued["managed_service_fee_cents"] == 0
    assert issued["trade_fund_deduction_cents"] == 57
    assert issued["net_cash_due_cents"] == 227
    assert issued["invoice_status"] == "ISSUED"

    pool = validate_success(
        api_client.get_trade_fund_account(world["pool"]["id"], BILLING_OPS)
    )
    assert pool["deducted_cents"] == 57
    assert pool["available_cents"] == 299943
    assert_trade_fund_identity(pool)

    campaign = validate_success(
        api_client.get_campaign(world["campaign"]["id"], BILLING_OPS)
    )
    assert campaign["billing_status"] == "INVOICED"
