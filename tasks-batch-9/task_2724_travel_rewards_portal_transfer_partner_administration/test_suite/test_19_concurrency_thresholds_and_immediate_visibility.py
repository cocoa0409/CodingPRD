"""
The cross-cutting layers: the two optimistic-concurrency compares, the inclusive
posture thresholds at 30 and 60, and the immediate visibility of derived fields.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_ACCOUNT_VERSION,
    ERR_STALE_OFFER_VERSION,
)
from test_helpers.assertions import assert_account_aggregates, assert_page
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    CASE_OPEN,
    CATEGORY_GROCERY,
    FULFILLMENT_CONFIRMED,
    FULFILLMENT_QUOTED,
    OFFER_OPEN,
    OFFER_SOLD_OUT,
    POSTURE_CLEAR,
    POSTURE_LOCKED,
    POSTURE_WATCH,
    SIGNAL_DEVICE_CHANGE,
    SIGNAL_EMAIL_CHANGE,
    SIGNAL_NEW_PAYEE,
    SIGNAL_PASSWORD_RESET,
    TRANSFER_SUBMITTED,
)

GROCERY_MCC = "5411"


def _grocery(api):
    """The 1.0x grocery mapping every funding purchase rides on."""
    return fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
        is_fallback=False,
    )


def _ten_thousand_point_account(api, name, email, enrolled_at):
    """One `CORE` account funded to exactly 10,000 points."""
    _grocery(api)
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name=name, email=email, enrolled_at=enrolled_at
    )
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
    return fx.read_account(api, account["id"]), cardholder


def test_a_booking_quoting_a_pre_resync_offer_version_is_refused_then_admitted(api):
    """
    "If that number does not equal the offer's current `version`, the booking is
    rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412). An offer with more than one
    portal seat legitimately accepts several bookings, so a second booking is not
    blocked by any state precondition; the stale version instead signals that the
    client is quoting a price the agency has already resynced away, and resync is
    precisely the operation that advances the offer's `version`."

    Design: Corner/cross_cutting_complexity_layers/offer_book_rejects_a_version_the_agency_has_already_resynced_away
    """
    account, cardholder = _ten_thousand_point_account(
        api, "Tomas Weber", "tomas@example.com", "2025-01-25T00:00:00.000Z"
    )
    _, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Parity Travel",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code="BOS-LIS-51",
        depart_at="2026-11-04T21:00:00.000Z",
        return_at="2026-11-12T08:00:00.000Z",
        net_rate_cents=10000,
        agency_public_price_cents=10000,
        agency_public_seats=2,
        portal_seats=2,
        tax_cents=0,
    )
    stale_version = offer["version"]
    resynced = validate_success(
        api.resync_offer(
            offer["id"],
            f.resync_payload(
                net_rate_cents=10000,
                agency_public_price_cents=10000,
                agency_public_seats=2,
                portal_seats=2,
            ),
            supplier,
        )
    )
    assert resynced["version"] == stale_version + 1

    validate_error(
        api.book_offer(
            offer["id"],
            f.book_payload(
                account["id"],
                expected_offer_version=stale_version,
                traveler_name="Tomas Weber",
            ),
            cardholder,
        ),
        ERR_STALE_OFFER_VERSION,
        412,
    )

    refused = fx.read_offer(api, offer["id"])
    assert refused["seats_committed"] == 0
    assert refused["status"] == OFFER_OPEN
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=10000,
        points_pending_redemption=0,
    )

    order = validate_success(
        api.book_offer(
            offer["id"],
            f.book_payload(
                account["id"],
                expected_offer_version=resynced["version"],
                traveler_name="Tomas Weber",
            ),
            cardholder,
        ),
        201,
    )
    assert order["fulfillment_status"] == FULFILLMENT_QUOTED
    assert order["points_debited"] == 10000

    booked = fx.read_offer(api, offer["id"])
    assert booked["seats_committed"] == 1
    assert booked["version"] == 3
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=10000,
        points_pending_redemption=10000,
    )


def test_a_transfer_replaying_a_pre_debit_account_version_is_refused_then_admitted(api):
    """
    "If that number does not equal the account's current `version`, the create is
    rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). An account may legitimately
    hold several in-flight transfers at once, so a second create is not blocked by any
    state precondition; the stale version instead signals that the client's view of
    the available points balance predates an earlier debit, clawback, or posture
    cascade."

    Design: Corner/cross_cutting_complexity_layers/transfer_create_rejects_an_account_version_that_predates_the_first_debit
    """
    account, cardholder = _ten_thousand_point_account(
        api, "Uma Lindqvist", "uma@example.com", "2025-01-26T00:00:00.000Z"
    )
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Cloudline Miles",
        partner_program_code="CLDL",
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    first_version = account["version"]
    first = fx.submit_transfer(
        api,
        account["id"],
        agreement["id"],
        1000,
        cardholder,
        expected_account_version=first_version,
    )

    validate_error(
        api.create_transfer(
            f.transfer_payload(
                account["id"],
                agreement["id"],
                points_out=1000,
                expected_account_version=first_version,
            ),
            cardholder,
        ),
        ERR_STALE_ACCOUNT_VERSION,
        412,
    )

    assert_page(
        api.list_transfers(cardholder, {"account_id": account["id"]}),
        total_count=1,
        length=1,
    )
    after_refusal = fx.read_account(api, account["id"])
    assert_account_aggregates(
        after_refusal, points_balance=9000, points_pending_redemption=1000
    )
    assert after_refusal["version"] != first_version

    retry = validate_success(
        api.create_transfer(
            f.transfer_payload(
                account["id"],
                agreement["id"],
                points_out=1000,
                expected_account_version=after_refusal["version"],
            ),
            cardholder,
        ),
        201,
    )
    assert retry["status"] == TRANSFER_SUBMITTED
    assert retry["points_out"] == 1000
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=8000,
        points_pending_redemption=2000,
    )
    assert fx.read_transfer(api, first["id"])["status"] == TRANSFER_SUBMITTED


def test_a_twenty_five_point_case_stays_clear_while_exactly_thirty_watches(api):
    """
    "At case opening the `instant_score` is the sum of the weights of the case's
    distinct signals, capped at 100: a device change contributes 30, a new payee 25, an
    email change 20, a password reset 15, and a geographic anomaly 10." ... "All three
    thresholds are inclusive: a score of exactly 60 locks, a score of exactly 30
    watches, and exactly two holds watch."

    Design: Corner/cross_cutting_complexity_layers/posture_thresholds_fire_exactly_at_thirty_and_sixty
    """
    below = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Vera Costa",
        email="vera@example.com",
        enrolled_at="2025-01-27T00:00:00.000Z",
    )
    at_watch = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Wes Aoki",
        email="wes@example.com",
        enrolled_at="2025-01-28T00:00:00.000Z",
    )

    quiet_case = fx.open_case(
        api,
        below["id"],
        ANALYST_HEADERS,
        signals=[SIGNAL_NEW_PAYEE],
        device_fingerprint_changed=False,
    )
    watch_case = fx.open_case(
        api,
        at_watch["id"],
        ANALYST_HEADERS,
        signals=[SIGNAL_DEVICE_CHANGE],
        device_fingerprint_changed=True,
    )

    assert quiet_case["risk_score"] == 25
    assert quiet_case["status"] == CASE_OPEN
    assert quiet_case["review_score"] is None
    assert watch_case["risk_score"] == 30
    assert watch_case["review_score"] is None
    assert_account_aggregates(
        fx.read_account(api, below["id"]), fraud_posture=POSTURE_CLEAR
    )
    assert_account_aggregates(
        fx.read_account(api, at_watch["id"]), fraud_posture=POSTURE_WATCH
    )


def test_three_signals_summing_to_exactly_sixty_lock_the_account(api):
    """
    "Otherwise, if any case that is `OPEN` or `UNDER_REVIEW` has a `risk_score` of at
    least 60, the posture is `LOCKED`." ... "All three thresholds are inclusive: a score
    of exactly 60 locks, a score of exactly 30 watches, and exactly two holds watch."

    Design: Corner/cross_cutting_complexity_layers/posture_thresholds_fire_exactly_at_thirty_and_sixty
    """
    account = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Yuki Mori",
        email="yuki@example.com",
        enrolled_at="2025-01-29T00:00:00.000Z",
    )

    case = fx.open_case(
        api,
        account["id"],
        ANALYST_HEADERS,
        signals=[SIGNAL_PASSWORD_RESET, SIGNAL_NEW_PAYEE, SIGNAL_EMAIL_CHANGE],
        device_fingerprint_changed=False,
    )

    assert case["risk_score"] == 60
    assert case["status"] == CASE_OPEN
    assert case["review_score"] is None
    assert_account_aggregates(
        fx.read_account(api, account["id"]), fraud_posture=POSTURE_LOCKED
    )


def test_a_bookings_derived_legs_and_its_cascades_are_readable_at_once(api):
    """
    "The order's `cash_copay_cents` is copied from the offer's `cash_copay_cents`, and
    `points_debited` is the offer's `portal_price_cents` less that copay, divided by
    `cents_per_point_applied` and rounded **up** to the next whole point." ... "On
    success the offer's `seats_committed` is recomputed, the offer flips to `SOLD_OUT`
    if the last seat has gone, the account's `points_pending_redemption` rises by
    `points_debited` **with no ledger entry whatsoever**"

    Design: Corner/consistency_model/computed_fields_and_cascades_are_visible_in_the_same_response
    """
    account, cardholder = _ten_thousand_point_account(
        api, "Zane Okafor", "zane@example.com", "2025-01-30T00:00:00.000Z"
    )
    _, offer, _ = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Immediate Travel",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code="SEA-AKL-77",
        depart_at="2026-12-02T23:00:00.000Z",
        return_at="2026-12-14T06:00:00.000Z",
        net_rate_cents=8000,
        agency_public_price_cents=8000,
        agency_public_seats=1,
        portal_seats=1,
        tax_cents=500,
    )
    assert offer["portal_price_cents"] == 8000
    assert offer["cash_copay_cents"] == 500

    order = validate_success(
        api.book_offer(
            offer["id"],
            f.book_payload(
                account["id"],
                expected_offer_version=offer["version"],
                traveler_name="Zane Okafor",
            ),
            cardholder,
        ),
        201,
    )
    assert order["points_debited"] == 7500
    assert order["cash_copay_cents"] == 500
    assert order["issuer_cost_provisional_cents"] == 7500
    assert order["fulfillment_status"] == FULFILLMENT_QUOTED
    assert order["inventory_offer_id"] == offer["id"]

    sold_out = fx.read_offer(api, offer["id"], cardholder)
    assert sold_out["status"] == OFFER_SOLD_OUT
    assert sold_out["seats_committed"] == 1
    assert_account_aggregates(
        fx.read_account(api, account["id"], cardholder),
        points_balance=10000,
        points_pending_redemption=7500,
    )

    confirmed = validate_success(api.confirm_order(order["id"], {}, cardholder))
    assert confirmed["fulfillment_status"] == FULFILLMENT_CONFIRMED
    assert_account_aggregates(
        fx.read_account(api, account["id"], cardholder),
        points_balance=2500,
        points_pending_redemption=0,
        lifetime_points_redeemed=7500,
    )
