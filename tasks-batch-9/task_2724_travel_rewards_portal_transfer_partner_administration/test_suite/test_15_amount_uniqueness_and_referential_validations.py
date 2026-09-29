"""
Validation refusals on amounts, uniqueness scopes, and the referential checks that
guard a redemption channel and a benefit consumption.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BELOW_MIN_TRANSFER,
    ERR_BENEFIT_REQUIRES_TICKETED_BOOKING,
    ERR_CHANNEL_REQUIRES_OFFER,
    ERR_DUPLICATE_CATEGORY_MAPPING,
    ERR_DUPLICATE_PROGRAM_CODE,
    ERR_NOTICE_TARGET_REQUIRED,
    ERR_ORDER_ACCOUNT_MISMATCH,
    ERR_STATEMENT_CREDIT_BELOW_MINIMUM,
    ERR_TRANSFER_INCREMENT_INVALID,
)
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_page,
)
from test_helpers.test_users import ADMIN_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    AGREEMENT_DRAFT,
    AGREEMENT_PENDING_APPROVAL,
    BENEFIT_LOUNGE_ACCESS,
    BENEFIT_TRAVEL_INSURANCE,
    CATEGORY_DINING,
    CATEGORY_GROCERY,
    CHANNEL_PORTAL_BOOKING,
    CHANGE_TRANSFER_RATIO_CHANGE,
    FULFILLMENT_CONFIRMED,
    NOTICE_DRAFT,
    TRANSFER_SUBMITTED,
)

GROCERY_MCC = "5411"


def _grocery(api):
    """The 1.0x grocery mapping every funding purchase in this file rides on."""
    return fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )


def _ten_thousand_point_account(api, name, email):
    """One `CORE` account funded to exactly 10,000 points."""
    _grocery(api)
    account, cardholder = fx.funded_account(api, 0, cardholder_name=name, email=email)
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
    return fx.read_account(api, account["id"]), cardholder


def _bare_fare_offer(api, itinerary_code="DEN-YYC-22"):
    """A zero-markup, zero-tax offer priced at exactly 10,000 cents."""
    return fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Bare Fare Consolidators",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code=itinerary_code,
        net_rate_cents=10000,
        agency_public_price_cents=10000,
        agency_public_seats=2,
        portal_seats=2,
        tax_cents=0,
    )


def test_a_statement_credit_one_point_below_the_floor_writes_no_order(api):
    """
    "A statement credit must be for at least 2,500 points; anything smaller is
    rejected with `ERR_STATEMENT_CREDIT_BELOW_MINIMUM` (HTTP 422)."

    Design: Corner/validations/statement_credit_below_the_minimum_rejected
    """
    account, cardholder = _ten_thousand_point_account(
        api, "Ilya Sorokin", "ilya@example.com"
    )

    validate_error(
        api.create_order(
            f.statement_credit_payload(account["id"], points_requested=2499), cardholder
        ),
        ERR_STATEMENT_CREDIT_BELOW_MINIMUM,
        422,
    )

    assert_page(
        api.list_orders(ADMIN_HEADERS, {"account_id": account["id"]}),
        total_count=0,
        length=0,
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=10000,
        points_pending_redemption=0,
    )


def test_the_transfer_minimum_is_checked_before_the_increment(api):
    """
    "**Transfer and seat constraints.** Below the agreement minimum
    (`ERR_BELOW_MIN_TRANSFER`, 422), then not an exact increment multiple
    (`ERR_TRANSFER_INCREMENT_INVALID`, 422), then no seat available
    (`ERR_SEAT_UNAVAILABLE`, 409), then statement credit below the floor
    (`ERR_STATEMENT_CREDIT_BELOW_MINIMUM`, 422), then a ratio-change notice missing
    its target (`ERR_NOTICE_TARGET_REQUIRED`, 422), in that order."

    Design: Corner/validations/transfer_amount_checks_are_ordered_minimum_before_increment
    """
    account, cardholder = _ten_thousand_point_account(
        api, "Hana Ito", "hana@example.com"
    )
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        min_transfer_points=5000,
        transfer_increment_points=1000,
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    pinned_version = account["version"]

    validate_error(
        api.create_transfer(
            f.transfer_payload(
                account["id"], agreement["id"], 4500, pinned_version
            ),
            cardholder,
        ),
        ERR_BELOW_MIN_TRANSFER,
        422,
    )
    validate_error(
        api.create_transfer(
            f.transfer_payload(
                account["id"], agreement["id"], 5500, pinned_version
            ),
            cardholder,
        ),
        ERR_TRANSFER_INCREMENT_INVALID,
        422,
    )
    admitted = validate_success(
        api.create_transfer(
            f.transfer_payload(
                account["id"], agreement["id"], 5000, pinned_version
            ),
            cardholder,
        ),
        201,
    )

    assert admitted["points_out"] == 5000
    assert admitted["status"] == TRANSFER_SUBMITTED
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=5000,
        points_pending_redemption=5000,
    )
    assert_page(
        api.list_transfers(ADMIN_HEADERS, {"account_id": account["id"]}),
        total_count=1,
        length=1,
    )


def test_neither_a_second_fallback_nor_a_reused_mcc_code_is_admitted(api):
    """
    "An `mcc_code` must be globally unique across the mapping table, and a second row
    claiming an already-mapped code — or a second row claiming `is_fallback` — is
    rejected with `ERR_DUPLICATE_CATEGORY_MAPPING`."

    Design: Corner/validations/second_fallback_category_and_duplicate_mcc_rejected
    """
    incumbent = validate_success(
        api.create_merchant_category(
            f.merchant_category_payload(
                mcc_code=GROCERY_MCC,
                display_name="Grocery Stores",
                base_category=CATEGORY_GROCERY,
                base_multiplier=1.0,
                is_fallback=True,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    validate_error(
        api.create_merchant_category(
            f.merchant_category_payload(
                mcc_code="5812",
                display_name="Restaurants",
                base_category=CATEGORY_DINING,
                base_multiplier=3.0,
                is_fallback=True,
            ),
            ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_CATEGORY_MAPPING,
        409,
    )
    validate_error(
        api.create_merchant_category(
            f.merchant_category_payload(
                mcc_code=GROCERY_MCC,
                display_name="Supermarkets",
                base_category=CATEGORY_GROCERY,
                base_multiplier=2.0,
                is_fallback=False,
            ),
            ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_CATEGORY_MAPPING,
        409,
    )

    assert_page(api.list_merchant_categories(ADMIN_HEADERS), total_count=1, length=1)
    surviving = validate_success(
        api.get_merchant_category(incumbent["id"], ADMIN_HEADERS)
    )
    assert surviving["base_multiplier"] == 1.0
    assert surviving["is_fallback"] is True


def test_the_programme_code_is_reserved_at_submission_not_at_drafting(api):
    """
    "Submitting a `DRAFT` agreement for approval requires that no *other* agreement
    carrying the same `partner_program_code` is currently `PENDING_APPROVAL`,
    `ACTIVE`, or `SUSPENDED`; a collision is rejected with
    `ERR_DUPLICATE_PROGRAM_CODE`."

    Design: Corner/validations/duplicate_program_code_on_the_second_submit_rejected
    """
    first = fx.draft_agreement(
        api,
        ADMIN_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    second = fx.draft_agreement(
        api,
        ADMIN_HEADERS,
        partner_name="Skyward Miles Renewal",
        partner_program_code="SKYW",
        ratio_points_out=2000,
        transfer_latency_hours=24,
        reversal_window_hours=48,
        settlement_cost_cents_per_1k=800,
    )

    submitted = validate_success(api.submit_agreement(first["id"], {}, ADMIN_HEADERS))
    validate_error(
        api.submit_agreement(second["id"], {}, ADMIN_HEADERS),
        ERR_DUPLICATE_PROGRAM_CODE,
        409,
    )

    assert submitted["status"] == AGREEMENT_PENDING_APPROVAL
    blocked = validate_success(api.get_agreement(second["id"], ADMIN_HEADERS))
    assert blocked["status"] == AGREEMENT_DRAFT
    assert blocked["submitted_by_user_id"] is None


def test_the_flat_order_collection_refuses_a_portal_booking_channel(api):
    """
    "Attempting to create a `PORTAL_BOOKING` on the flat collection is rejected with
    `ERR_CHANNEL_REQUIRES_OFFER` (HTTP 422)."

    Design: Corner/validations/portal_booking_channel_on_the_flat_create_endpoint_rejected
    """
    account, cardholder = _ten_thousand_point_account(
        api, "Yara Haddad", "yara@example.com"
    )

    validate_error(
        api.create_order(
            f.statement_credit_payload(
                account["id"], points_requested=3000, channel=CHANNEL_PORTAL_BOOKING
            ),
            cardholder,
        ),
        ERR_CHANNEL_REQUIRES_OFFER,
        422,
    )

    assert_page(
        api.list_orders(ADMIN_HEADERS, {"account_id": account["id"]}),
        total_count=0,
        length=0,
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]), points_pending_redemption=0
    )


def test_a_cited_order_belonging_to_another_account_is_refused(api):
    """
    "And whenever an order is cited, its `account_id` must equal the entitlement's
    `account_id`, or the call is refused with `ERR_ORDER_ACCOUNT_MISMATCH`."

    Design: Corner/validations/benefit_consume_citing_another_accounts_order_rejected
    """
    _grocery(api)
    holder, holder_headers = fx.funded_account(
        api, 0, cardholder_name="Aki Mori", email="aki@example.com"
    )
    stranger, stranger_headers = fx.funded_account(
        api, 0, cardholder_name="Bram Vos", email="bram@example.com"
    )
    fx.fund_account(api, stranger["id"], 10000, mcc_code=GROCERY_MCC)
    foreign_order = fx.statement_credit(
        api, stranger["id"], stranger_headers, points_requested=3000
    )
    entitlement = fx.grant_entitlement(
        api,
        holder["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_LOUNGE_ACCESS,
        annual_allowance=4,
        expires_at="2027-01-01T00:00:00.000Z",
        requires_portal_booking=False,
    )

    validate_error(
        api.consume_entitlement(
            entitlement["id"],
            f.consume_payload(redemption_order_id=foreign_order["id"]),
            holder_headers,
        ),
        ERR_ORDER_ACCOUNT_MISMATCH,
        422,
    )

    after = fx.read_entitlement(api, entitlement["id"])
    assert after["used_count"] == 0
    assert after["remaining_allowance"] == 4
    assert after["last_consumed_at"] is None


def test_a_portal_gated_benefit_wants_a_ticketed_order_not_a_confirmed_one(api):
    """
    "When `requires_portal_booking` is true the cited `redemption_order_id` must name
    an order whose `channel` is `PORTAL_BOOKING` and whose `fulfillment_status` is
    `TICKETED`, or the call is refused with `ERR_BENEFIT_REQUIRES_TICKETED_BOOKING`"

    Design: Corner/validations/benefit_requiring_portal_booking_citing_a_confirmed_order_rejected
    """
    account, cardholder = _ten_thousand_point_account(
        api, "Cleo Marchetti", "cleo@example.com"
    )
    _, offer, _ = _bare_fare_offer(api)
    order = fx.book(
        api, offer, account["id"], cardholder, traveler_name="Cleo Marchetti"
    )
    fx.confirm(api, order["id"], cardholder)
    entitlement = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_TRAVEL_INSURANCE,
        annual_allowance=2,
        expires_at="2027-01-01T00:00:00.000Z",
        requires_portal_booking=True,
    )

    validate_error(
        api.consume_entitlement(
            entitlement["id"],
            f.consume_payload(redemption_order_id=order["id"]),
            cardholder,
        ),
        ERR_BENEFIT_REQUIRES_TICKETED_BOOKING,
        409,
    )

    assert (
        validate_success(api.get_order(order["id"], ADMIN_HEADERS))["fulfillment_status"]
        == FULFILLMENT_CONFIRMED
    )
    after = fx.read_entitlement(api, entitlement["id"])
    assert after["used_count"] == 0
    assert after["remaining_allowance"] == 2


def test_a_ratio_change_notice_needs_its_three_terms_only_at_submission(api):
    """
    "and for a `TRANSFER_RATIO_CHANGE` it enforces two conditions:
    `target_agreement_id`, `new_ratio_points_out`, and `new_ratio_partner_units_in`
    must all be present, or the request is rejected with `ERR_NOTICE_TARGET_REQUIRED`
    (HTTP 422)"

    Design: Corner/validations/ratio_change_notice_submitted_without_its_ratio_terms_rejected
    """
    notice = fx.draft_notice(
        api,
        ADMIN_HEADERS,
        notice_code="RATIO-NO-TARGET",
        change_type=CHANGE_TRANSFER_RATIO_CHANGE,
        effective_at="2026-12-01T00:00:00.000Z",
        grandfather_window_days=30,
        cohort_enrolled_before="2025-01-01T00:00:00.000Z",
    )
    assert notice["target_agreement_id"] is None

    validate_error(
        api.submit_notice(notice["id"], {}, ADMIN_HEADERS),
        ERR_NOTICE_TARGET_REQUIRED,
        422,
    )

    assert fx.read_notice(api, notice["id"])["status"] == NOTICE_DRAFT
