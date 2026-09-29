"""
Validation refusals on the temporal guards, the two state gates a closed account and
a suspended offer raise, and the two shape checks on bodies and pagination windows.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACCOUNT_CLOSED,
    ERR_AVAILABILITY_PARITY_BREACH,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_NOTICE_PERIOD_TOO_SHORT,
    ERR_OFFER_NOT_BOOKABLE,
    ERR_SETTLEMENT_AMOUNT_INVALID,
    ERR_SNAPSHOT_AS_OF_IN_FUTURE,
)
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_page,
    assert_timestamp_equals,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, APPROVER_HEADERS, APPROVER_USER_ID
from test_helpers.types import (
    ACCOUNT_CLOSED,
    CATEGORY_GROCERY,
    CHANGE_BENEFIT_REMOVAL,
    METHOD_COST_BASIS,
    NOTICE_ANNOUNCED,
    NOTICE_PENDING_APPROVAL,
    OFFER_SUSPENDED,
    PARITY_IN,
    POSTURE_CLEAR,
    SETTLEMENT_AGENCY_INVOICED,
    SIGNAL_DEVICE_CHANGE,
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


def _bare_fare_offer(api, itinerary_code="SEA-KOA-25"):
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


def _pending_notice(api, notice_code, effective_at):
    """One `BENEFIT_REMOVAL` notice walked `DRAFT` → `PENDING_APPROVAL`."""
    notice = fx.draft_notice(
        api,
        ADMIN_HEADERS,
        notice_code=notice_code,
        change_type=CHANGE_BENEFIT_REMOVAL,
        effective_at=effective_at,
        grandfather_window_days=0,
        cohort_enrolled_before="2025-01-01T00:00:00.000Z",
    )
    return validate_success(api.submit_notice(notice["id"], {}, ADMIN_HEADERS))


def test_forty_four_days_of_runway_is_short_and_forty_five_is_exact(api):
    """
    "and that the notice's `effective_at` is at least 45 days after the clock instant
    at the moment of announcement — a shorter runway is rejected with
    `ERR_NOTICE_PERIOD_TOO_SHORT` (HTTP 422)."

    Design: Corner/validations/notice_announced_inside_the_forty_five_day_period_rejected
    """
    short = _pending_notice(api, "SHORT-44", "2026-09-14T00:00:00.000Z")
    exact = _pending_notice(api, "EXACT-45", "2026-09-15T00:00:00.000Z")

    validate_error(
        api.announce_notice(short["id"], {}, APPROVER_HEADERS),
        ERR_NOTICE_PERIOD_TOO_SHORT,
        422,
    )
    announced = validate_success(api.announce_notice(exact["id"], {}, APPROVER_HEADERS))

    refused = fx.read_notice(api, short["id"])
    assert refused["status"] == NOTICE_PENDING_APPROVAL
    assert refused["announced_at"] is None
    assert announced["status"] == NOTICE_ANNOUNCED
    assert_timestamp_equals(announced["announced_at"], "2026-08-01T00:00:00.000Z")
    assert announced["approved_by_user_id"] == APPROVER_USER_ID


def test_a_snapshot_dated_past_the_clock_is_refused_and_the_clock_itself_is_not(api):
    """
    "The cut-off may not be in the future: an `as_of` strictly after the clock instant
    is rejected with `ERR_SNAPSHOT_AS_OF_IN_FUTURE` (HTTP 422)." ... "Should the
    chosen input set be empty, the blended cost falls back to 1000 cents per 1,000
    points."

    Design: Corner/validations/liability_snapshot_dated_after_the_clock_rejected
    """
    validate_error(
        api.create_snapshot(
            f.snapshot_payload("2026-08-02T00:00:00.000Z", method=METHOD_COST_BASIS),
            ADMIN_HEADERS,
        ),
        ERR_SNAPSHOT_AS_OF_IN_FUTURE,
        422,
    )

    snapshot = fx.new_snapshot(
        api, "2026-08-01T00:00:00.000Z", ADMIN_HEADERS, method=METHOD_COST_BASIS
    )

    assert snapshot["gross_outstanding_points"] == 0
    assert snapshot["blended_cost_per_1k_cents"] == 1000
    assert snapshot["gross_liability_cents"] == 0
    assert snapshot["net_liability_cents"] == 0
    assert snapshot["effective_breakage_rate_bps"] == 0
    assert_page(api.list_snapshots(ADMIN_HEADERS), total_count=1, length=1)


def test_a_resync_may_not_expose_more_portal_seats_than_the_agency_advertises(api):
    """
    "Separately from the derived verdict, a hard safety rule guards both offer
    publication and resync: the `portal_seats` in the payload may not exceed the
    `agency_public_seats` declared in that same payload, because the portal would then
    be advertising inventory the agency cannot honour. A violation is rejected with
    `ERR_AVAILABILITY_PARITY_BREACH` (HTTP 422)."

    Design: Corner/validations/resync_raising_portal_seats_above_public_seats_rejected
    """
    _, offer, supplier = _bare_fare_offer(api)

    validate_error(
        api.resync_offer(
            offer["id"],
            f.resync_payload(
                net_rate_cents=10000,
                agency_public_price_cents=10000,
                agency_public_seats=4,
                portal_seats=5,
            ),
            supplier,
        ),
        ERR_AVAILABILITY_PARITY_BREACH,
        422,
    )

    after = fx.read_offer(api, offer["id"], supplier)
    assert after["portal_seats"] == 2
    assert after["agency_public_seats"] == 2
    assert after["portal_price_cents"] == 10000
    assert after["parity_status"] == PARITY_IN
    assert after["version"] == 1
    assert after["last_resynced_at"] is None


def test_an_adjustment_driving_the_final_cost_negative_leaves_the_invoice_open(api):
    """
    "A negative `invoice_amount_cents`, or an adjustment that drives
    `issuer_cost_final_cents` below zero, is rejected with
    `ERR_SETTLEMENT_AMOUNT_INVALID` (HTTP 422)."

    Design: Corner/validations/settlement_driving_issuer_cost_below_zero_rejected
    """
    account, cardholder = _ten_thousand_point_account(api, "Dov Katz", "dov@example.com")
    agency, offer, supplier = _bare_fare_offer(api, itinerary_code="MIA-SJU-28")
    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Dov Katz")
    fx.confirm(api, order["id"], cardholder)
    fx.ticket(api, order["id"], supplier, ticket_number="TKT-556677")

    validate_error(
        api.settle_order(
            order["id"],
            f.settle_payload(
                invoice_amount_cents=1000, settlement_adjustment_cents=-2000
            ),
            ADMIN_HEADERS,
        ),
        ERR_SETTLEMENT_AMOUNT_INVALID,
        422,
    )

    after = validate_success(api.get_order(order["id"], ADMIN_HEADERS))
    assert after["settlement_status"] == SETTLEMENT_AGENCY_INVOICED
    assert after["settled_at"] is None
    assert after["issuer_cost_final_cents"] is None
    assert after["cost_per_1k_final_cents"] is None
    assert after["issuer_cost_provisional_cents"] == 10000
    assert (
        validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))[
            "payable_cents"
        ]
        == 10000
    )


def test_a_closed_account_refuses_a_fresh_purchase_and_earns_nothing_more(api):
    """
    "A closed account is inert for spending. Posting a purchase to it, booking an
    offer for it, creating a redemption order or a transfer request on its behalf,
    granting it a new benefit entitlement, or consuming one of its existing
    entitlements are all rejected with `ERR_ACCOUNT_CLOSED` — those six operations,
    and no others, consult the lifecycle dimension."

    Design: Corner/validations/posting_a_transaction_to_a_closed_account_rejected
    """
    account, _ = _ten_thousand_point_account(api, "Esme Roche", "esme@example.com")
    closed = validate_success(api.close_account(account["id"], {}, ADMIN_HEADERS))
    assert closed["status"] == ACCOUNT_CLOSED

    validate_error(
        api.create_transaction(
            f.transaction_payload(
                account["id"],
                mcc_code=GROCERY_MCC,
                amount_cents=500000,
                posted_at="2026-08-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        ERR_ACCOUNT_CLOSED,
        409,
    )

    assert_page(api.list_transactions(ADMIN_HEADERS), total_count=1, length=1)
    assert_page(
        api.list_ledger_entries(ADMIN_HEADERS, {"account_id": account["id"]}),
        total_count=1,
        length=1,
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        status=ACCOUNT_CLOSED,
        points_balance=10000,
    )


def test_a_suspended_offer_is_not_bookable_even_at_its_current_version(api):
    """
    "The offer's `status` must be `OPEN`, so a suspended, sold-out, or withdrawn offer
    is refused with `ERR_OFFER_NOT_BOOKABLE`."

    Design: Corner/validations/booking_a_suspended_offer_rejected
    """
    account, cardholder = _ten_thousand_point_account(
        api, "Faye Osei", "faye@example.com"
    )
    _, offer, _ = _bare_fare_offer(api, itinerary_code="ORD-DUB-30")

    suspended = validate_success(
        api.suspend_offer(
            offer["id"], f.offer_suspend_payload("PRICING_AUDIT"), ADMIN_HEADERS
        )
    )
    assert suspended["status"] == OFFER_SUSPENDED

    validate_error(
        api.book_offer(
            offer["id"],
            f.book_payload(
                account["id"],
                expected_offer_version=suspended["version"],
                traveler_name="Faye Osei",
            ),
            cardholder,
        ),
        ERR_OFFER_NOT_BOOKABLE,
        409,
    )

    after = fx.read_offer(api, offer["id"])
    assert after["status"] == OFFER_SUSPENDED
    assert after["seats_committed"] == 0
    assert_page(api.list_orders(ADMIN_HEADERS), total_count=0, length=0)
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=10000,
        points_pending_redemption=0,
    )


def test_a_signals_array_must_be_a_non_empty_set_of_distinct_members(api):
    """
    "Duplicate members in `signals` are rejected as a malformed body with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/fraud_case_with_duplicate_signal_members_invalid_request
    """
    account, _ = _ten_thousand_point_account(api, "Gil Navarro", "gil@example.com")

    validate_error(
        api.create_fraud_case(
            f.fraud_case_payload(
                account["id"], signals=[SIGNAL_DEVICE_CHANGE, SIGNAL_DEVICE_CHANGE]
            ),
            ANALYST_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_fraud_case(
            f.fraud_case_payload(account["id"], signals=[]), ANALYST_HEADERS
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    assert_page(api.list_fraud_cases(ANALYST_HEADERS), total_count=0, length=0)
    assert_account_aggregates(
        fx.read_account(api, account["id"]), fraud_posture=POSTURE_CLEAR
    )


def test_pagination_windows_outside_the_declared_bounds_are_refused(api):
    """
    "A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is
    rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/list_endpoint_pagination_bounds_rejected
    """
    fx.new_account(api, ADMIN_HEADERS)

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_accounts(ADMIN_HEADERS, params), ERR_INVALID_PAGINATION, 400
        )

    assert_page(
        api.list_accounts(ADMIN_HEADERS, {"limit": 100, "offset": 0}),
        total_count=1,
        has_more=False,
        limit=100,
        offset=0,
        length=1,
    )
