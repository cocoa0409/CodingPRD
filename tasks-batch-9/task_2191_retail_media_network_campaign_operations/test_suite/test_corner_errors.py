"""One refusal per rule, each with the state it was supposed to leave untouched.

Every request below is well formed, correctly addressed and made by a role the endpoint
table lists. What refuses each one is a single stated rule — a document threshold, a
global code uniqueness, a hero product the line item may not be left without, an
advertiser that is no longer active, a significance floor, a minimum accrual, a drawable
balance — and each test also asserts that the refused write left nothing half-applied.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    BILLING_OPS,
    CATALOG_OPS,
    CREDIT_ANALYST,
    ERR_ADVERTISER_NOT_ACTIVE,
    ERR_AMOUNT_BELOW_MINIMUM,
    ERR_DUPLICATE_RESOURCE_CODE,
    ERR_HERO_ASSIGNMENT_REQUIRED,
    ERR_KYC_DOCUMENTS_INSUFFICIENT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STUDY_NOT_SIGNIFICANT,
    ERR_TRADE_FUND_INSUFFICIENT,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    OPERATOR_USER_IDS,
    ROLE_ACCOUNT_MANAGER,
    api_client,
    assert_trade_fund_identity,
    factories as f,
    reread_campaign,
    reread_line_item,
    reread_plan,
    reread_pool,
    reread_study,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    build_eligible_line_item,
    build_pending_review_campaign,
    build_trade_fund_pool,
)
from test_helpers.fixtures_corner_rbac import (
    BASELINE_LINE_ITEM_A,
    BASELINE_PRODUCT_A,
    build_baseline_advertiser,
    build_baseline_campaign_world,
    build_baseline_delivering_world,
    build_baseline_plan,
)

# --- The two sides of the campaign review chain ----------------------------


def test_the_submitter_of_a_campaign_review_cannot_render_its_own_decision():
    """The operator recorded as the submitter is refused its own review decision.

    PRD 3.3: "Both branches stamp `review_decided_by_user_id` and both refuse a caller
    whose `X-User-ID` equals `submitted_for_review_by_user_id`."

    PRD 2.12: "On KYC decision, plan approval, campaign review decision, invoice
    write-off and dispute resolution: the segregation-of-duties rule of §2.11 holds —
    otherwise `ERR_SEGREGATION_OF_DUTIES`, 403."

    Design: Corner/errors/the_submitter_of_a_campaign_review_cannot_render_its_own_review_decision_forbidden
    """
    world = build_baseline_campaign_world()
    build_pending_review_campaign(world, **BASELINE_LINE_ITEM_A)

    response = api_client.decide_campaign_review(
        world["campaign"]["id"],
        f.decision_payload("APPROVE", decision_note="Self approval attempt"),
        ACCOUNT_MANAGER,
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES)

    campaign = reread_campaign(world)
    assert campaign["delivery_status"] == "PENDING_REVIEW"
    assert (
        campaign["submitted_for_review_by_user_id"]
        == OPERATOR_USER_IDS[ROLE_ACCOUNT_MANAGER]
    )
    assert campaign["review_decided_by_user_id"] is None


# --- The first-submission document threshold ------------------------------


def test_onboarding_submission_with_a_single_kyc_document_is_rejected():
    """One document is below the first-submission floor of two.

    PRD 3.1: "A first submission out of `DRAFT` requires at least 2 documents; a
    remediation submission out of `CREDIT_HOLD` requires at least 3, because remediation
    costs one extra document."

    PRD 3.1: "The advertiser is born with `onboarding_status` `DRAFT`,
    `suspension_reason` `NONE`, `kyc_document_count` 0, and `credit_exposure_cents` and
    `dispute_credit_balance_cents` both 0."

    PRD 2.12: "On onboarding submission: `kyc_document_count` is at least 2 on a first
    submission and at least 3 on a re-submission out of `CREDIT_HOLD` — otherwise
    `ERR_KYC_DOCUMENTS_INSUFFICIENT`, 422."

    Design: Corner/errors/onboarding_submission_with_a_single_kyc_document_is_rejected
    """
    advertiser = validate_success(
        api_client.create_advertiser(f.advertiser_payload(), NETWORK_ADMIN), 201
    )

    response = api_client.submit_advertiser_onboarding(
        advertiser["id"], f.submit_onboarding_payload(kyc_document_count=1), ACCOUNT_MANAGER
    )
    validate_error(response, ERR_KYC_DOCUMENTS_INSUFFICIENT)

    held = validate_success(api_client.get_advertiser(advertiser["id"], NETWORK_ADMIN))
    assert held["onboarding_status"] == "DRAFT"
    assert held["kyc_document_count"] == 0
    assert held["onboarding_submitted_by_user_id"] is None


# --- Global SKU uniqueness ------------------------------------------------

DUPLICATE_SKU_PRODUCT = {
    "sku": "SKU-RED-1",
    "category_code": "APPAREL",
    "title": "red jacket",
    "price_cents": 9000,
    "in_stock_units": 20,
    "margin_pct": 0.3,
}


def test_reusing_an_existing_catalog_sku_is_rejected():
    """A different category does not buy a second product the same SKU.

    PRD 2.12: "On catalog product creation and placement slot creation: `sku` is unique
    across all catalog products and `slot_code` is unique across all placement slots —
    otherwise `ERR_DUPLICATE_RESOURCE_CODE`, 409."

    Design: Corner/errors/reusing_an_existing_catalog_sku_is_rejected_with_a_duplicate_resource_code
    """
    first = validate_success(
        api_client.create_catalog_product(
            f.catalog_product_payload(**BASELINE_PRODUCT_A), CATALOG_OPS
        ),
        201,
    )

    response = api_client.create_catalog_product(
        f.catalog_product_payload(**DUPLICATE_SKU_PRODUCT), CATALOG_OPS
    )
    validate_error(response, ERR_DUPLICATE_RESOURCE_CODE)

    held = validate_success(
        api_client.get_catalog_product(first["id"], CATALOG_OPS)
    )
    assert held["sku"] == "SKU-RED-1"
    assert held["category_code"] == "FOOTWEAR"
    assert held["in_stock_units"] == 50


# --- The hero product an eligible line item may not lose ------------------


def test_deleting_the_last_hero_assignment_of_an_eligible_line_item_is_rejected():
    """The only active hero assignment of a non-draft line item cannot be removed.

    PRD 3.4: "Removal is available to the same four roles; it is accepted while the
    assignment is `ACTIVE`, `PAUSED_OOS` or `PAUSED_RESTRICTED`, requires the owning line
    item not to be `ENDED`, and — when the actor is an operator rather than the system —
    requires the line item to retain at least one other assignment that is `ACTIVE` with
    `is_hero` true, unless the line item is still in `DRAFT`."

    PRD 2.12: "On line item eligibility submission the line item has at least one
    assignment whose `assignment_status` is `ACTIVE` and whose `is_hero` is true, and on
    assignment removal the last such hero assignment of a line item that is not in
    `DRAFT` may not be removed — otherwise `ERR_HERO_ASSIGNMENT_REQUIRED`, 422."

    Design: Corner/errors/deleting_the_last_hero_assignment_of_an_eligible_line_item_is_rejected
    """
    world = build_baseline_campaign_world()
    build_eligible_line_item(world, **BASELINE_LINE_ITEM_A)
    assignment_id = world["assignment"]["id"]

    response = api_client.delete_product_assignment(assignment_id, ACCOUNT_MANAGER)
    validate_error(response, ERR_HERO_ASSIGNMENT_REQUIRED)

    held = validate_success(
        api_client.get_product_assignment(assignment_id, ACCOUNT_MANAGER)
    )
    assert held["assignment_status"] == "ACTIVE"
    assert held["is_hero"] is True
    assert held["removed_at"] is None
    line_item = reread_line_item(world)
    assert line_item["line_item_status"] == "ELIGIBLE"
    assert line_item["eligible_product_count"] == 1


# --- A campaign review approval for an advertiser no longer active --------


def test_approving_a_campaign_review_for_a_suspended_advertiser_is_a_conflict():
    """The suspended advertiser, not the campaign, is what refuses the approval.

    PRD 3.3: "`APPROVE` additionally requires the advertiser to be `ACTIVE` and the
    current logical time to be strictly before `flight_end_at`; it lands the campaign in
    `SCHEDULED`, at which point `allocated_budget_cents` becomes reserved, so the plan's
    `reserved_cents` and `available_cents` are recomputed and the advertiser's exposure
    is recomputed with it."

    PRD 2.12: "On budget plan approval, campaign review decision, campaign resume, line
    item activation and study start: the advertiser's `onboarding_status` is `ACTIVE` —
    otherwise `ERR_ADVERTISER_NOT_ACTIVE`, 409."

    Design: Corner/errors/approving_a_campaign_review_for_a_suspended_advertiser_returns_409
    """
    world = build_baseline_campaign_world()
    build_pending_review_campaign(world, **BASELINE_LINE_ITEM_A)
    validate_success(
        api_client.suspend_advertiser(
            world["advertiser"]["id"], {"suspension_reason": "CREDIT_BREACH"},
            CREDIT_ANALYST,
        )
    )

    response = api_client.decide_campaign_review(
        world["campaign"]["id"], f.decision_payload("APPROVE"), NETWORK_ADMIN
    )
    validate_error(response, ERR_ADVERTISER_NOT_ACTIVE)

    advertiser = validate_success(
        api_client.get_advertiser(world["advertiser"]["id"], NETWORK_ADMIN)
    )
    assert advertiser["onboarding_status"] == "SUSPENDED"
    assert advertiser["suspension_reason"] == "CREDIT_BREACH"
    assert reread_campaign(world)["delivery_status"] == "PENDING_REVIEW"
    assert reread_plan(world)["available_cents"] == 2000000


# --- The significance floor on publication --------------------------------

STUDY_DESIGN = {
    "design_method": "GEO_HOLDOUT",
    "holdout_pct": 0.1,
    "window_start_at": "2026-08-01T00:00:00Z",
    "window_end_at": "2026-08-08T00:00:00Z",
}
COHORT_SIZE = 10000
EXPOSED_CONVERSIONS = 1001
CONTROL_CONVERSIONS = 1000
EXPOSED_SALES_CENTS = 2000000
CONTROL_SALES_CENTS = 1990000


def test_publishing_a_study_below_the_significance_minimum_is_rejected():
    """A positive lift is not a publishable one when the score sits under 1.96.

    PRD 3.7: "`significance_score` is the absolute difference between the exposed rate
    and the control rate, multiplied by the square root of the smaller of the two group
    sizes, rounded half-up to four decimal places."

    PRD 3.7: "`significance_flag` is true when `significance_score` is at or above 1.96
    and false below it, so a score of exactly 1.9600 is significant."

    PRD 2.12: "On study publication: the study's `significance_flag` is true — otherwise
    `ERR_STUDY_NOT_SIGNIFICANT`, 422."

    Design: Corner/errors/publishing_a_study_whose_significance_score_is_below_the_minimum_is_rejected
    """
    world = build_baseline_delivering_world()
    world["study"] = validate_success(
        api_client.create_incrementality_study(
            f.incrementality_study_payload(
                world["campaign"]["id"], world["campaign"]["version"], **STUDY_DESIGN
            ),
            MEASUREMENT_ANALYST,
        ),
        201,
    )
    validate_success(
        api_client.start_incrementality_study(
            world["study"]["id"],
            f.study_start_payload(
                exposed_group_size=COHORT_SIZE, control_group_size=COHORT_SIZE
            ),
            MEASUREMENT_ANALYST,
        )
    )
    set_clock(world, STUDY_DESIGN["window_end_at"])
    world["study"] = validate_success(
        api_client.measure_incrementality_study(
            world["study"]["id"],
            f.study_measure_payload(
                EXPOSED_CONVERSIONS,
                CONTROL_CONVERSIONS,
                EXPOSED_SALES_CENTS,
                CONTROL_SALES_CENTS,
            ),
            MEASUREMENT_ANALYST,
        )
    )

    response = api_client.publish_incrementality_study(
        world["study"]["id"],
        {"publication_note": "Attempted publication"},
        MEASUREMENT_ANALYST,
    )
    validate_error(response, ERR_STUDY_NOT_SIGNIFICANT)

    study = reread_study(world)
    assert study["study_status"] == "MEASURING"
    assert study["significance_score"] == 0.0100
    assert study["significance_flag"] is False
    assert study["lift_pct"] == 0.0010
    assert study["incremental_sales_cents"] == 1998
    assert reread_campaign(world)["incremental_revenue_cents"] == 0


# --- The accrual minimum --------------------------------------------------

BELOW_MINIMUM_ACCRUAL_CENTS = 500


def test_a_trade_fund_accrual_below_the_minimum_amount_is_rejected():
    """A 500-cent accrual is under the 1,000-cent floor and credits nothing.

    PRD 3.4: "An accrual, posted by `BillingOps` or `NetworkAdmin` with
    `accrual_amount_cents` of at least 1,000 cents and a mandatory `accrual_reference`,
    raises `accrued_cents` and `available_cents` together and requires the pool to be
    `OPEN`."

    PRD 2.12: "On plan top-up `top_up_amount_cents` is at least 50,000 cents, and on a
    fund accrual `accrual_amount_cents` is at least 1,000 cents — otherwise
    `ERR_AMOUNT_BELOW_MINIMUM`, 422."

    Design: Corner/errors/a_trade_fund_accrual_below_the_minimum_amount_is_rejected
    """
    world = build_baseline_advertiser()
    build_trade_fund_pool(world, accrual_cents=0)

    response = api_client.post_trade_fund_accrual(
        world["pool"]["id"],
        f.accrual_payload(
            BELOW_MINIMUM_ACCRUAL_CENTS, accrual_reference="ACC-2026-Q3-TINY"
        ),
        BILLING_OPS,
    )
    validate_error(response, ERR_AMOUNT_BELOW_MINIMUM)

    pool = reread_pool(world)
    assert pool["accrued_cents"] == 0
    assert pool["available_cents"] == 0
    assert pool["account_status"] == "OPEN"
    assert_trade_fund_identity(pool)


# --- The drawable balance, not the accrual ------------------------------

POOL_ACCRUAL_CENTS = 500000
PLAN_TRADE_FUND_SHARE_CENTS = 200000
OVERSIZED_DEDUCTION_CENTS = 400000


def test_a_manual_deduction_above_the_unreserved_pool_balance_is_rejected():
    """The draw is tested against what is drawable, not against what was accrued.

    PRD 3.4: "Its four money figures are derived: `accrued_cents` is the cumulative sum
    of every accrual posted to it; `reserved_cents` is the sum of `trade_fund_share_cents`
    over budget plans of the same advertiser and period whose `plan_status` is `APPROVED`
    or `ACTIVE`; `deducted_cents` is the sum of `trade_fund_deduction_cents` over invoices
    referencing this pool whose `invoice_status` is `ISSUED`, `DISPUTED`, `ADJUSTED` or
    `SETTLED`, plus the sum of every manual deduction posted to it; and `available_cents`
    is `accrued_cents` less `reserved_cents` less `deducted_cents`."

    PRD 2.12: "On manual deduction the pool's `available_cents` is at least the requested
    amount, and on plan submission it is at least the plan's `trade_fund_share_cents` —
    otherwise `ERR_TRADE_FUND_INSUFFICIENT`, 402."

    Design: Corner/errors/a_manual_deduction_above_the_unreserved_pool_balance_is_rejected
    """
    world = build_baseline_advertiser()
    build_trade_fund_pool(world, accrual_cents=POOL_ACCRUAL_CENTS, deduction_cap_pct=0.6)
    build_baseline_plan(world, trade_fund_share_cents=PLAN_TRADE_FUND_SHARE_CENTS)
    current_version = reread_pool(world)["version"]

    response = api_client.post_trade_fund_deduction(
        world["pool"]["id"],
        f.deduction_payload(
            OVERSIZED_DEDUCTION_CENTS,
            current_version,
            deduction_reference="MAN-DED-OVER",
        ),
        BILLING_OPS,
    )
    validate_error(response, ERR_TRADE_FUND_INSUFFICIENT)

    pool = reread_pool(world)
    assert pool["accrued_cents"] == 500000
    assert pool["reserved_cents"] == 200000
    assert pool["deducted_cents"] == 0
    assert pool["available_cents"] == 300000
    assert_trade_fund_identity(pool)
