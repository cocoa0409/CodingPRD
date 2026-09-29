"""
Guards that live on a different aggregate than the row being transitioned: an
agreement behind a transfer, an agency behind an order, an order behind a benefit.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AGENCY_SUSPENDED,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_BENEFIT_REQUIRES_TICKETED_BOOKING,
)
from test_helpers.assertions import assert_account_aggregates, assert_timestamp_equals
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    AGENCY_SUSPENDED as AGENCY_STATUS_SUSPENDED,
)
from test_helpers.types import (
    AGREEMENT_SUSPENDED,
    BENEFIT_LOUNGE_ACCESS,
    CATEGORY_DINING,
    CATEGORY_GROCERY,
    FULFILLMENT_CONFIRMED,
    FULFILLMENT_TICKETED,
    OFFER_SUSPENDED,
    PRODUCT_PREMIER,
    SETTLEMENT_AGENCY_INVOICED,
    SETTLEMENT_UNSETTLED,
    SUSPENSION_AGENCY_SUSPENDED,
    TRANSFER_SUBMITTED,
)

DINING_MCC = "5812"
GROCERY_MCC = "5411"


def _submitted_transfer_then_agreement_suspended(api):
    """A 4,000-point transfer accepted while the agreement was still `ACTIVE`."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    account, cardholder = fx.funded_account(api, 10000, mcc_code=GROCERY_MCC)
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    transfer = fx.submit_transfer(api, account["id"], agreement["id"], 4000, cardholder)
    suspended = validate_success(
        api.suspend_agreement(
            agreement["id"],
            f.offer_suspend_payload("PARTNER_API_OUTAGE"),
            ADMIN_HEADERS,
        )
    )
    assert suspended["status"] == AGREEMENT_SUSPENDED
    return account, transfer


def test_screening_clearance_fails_on_the_agreement_state_not_the_transfer_state(api):
    """
    "The agreement gate applies to exactly four operations, each rejecting with
    `ERR_AGREEMENT_NOT_ACTIVE` when the referenced agreement is in any state other
    than `ACTIVE`: creating a transfer request, clearing screening on one, scheduling
    a promotional bonus event, and submitting a `TRANSFER_RATIO_CHANGE` notice for
    approval."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_transfer_screening_requires_active_partner_agreement
    """
    _, transfer = _submitted_transfer_then_agreement_suspended(api)

    validate_error(
        api.clear_screening(transfer["id"], {}, ANALYST_HEADERS),
        ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )

    after = fx.read_transfer(api, transfer["id"])
    assert after["status"] == TRANSFER_SUBMITTED
    assert after["screening_cleared_at"] is None
    assert after["scheduled_post_at"] is None


def test_the_refused_clearance_leaves_the_submitted_reservation_exactly_as_it_was(api):
    """
    "the sum of `points_out` over the account's transfer requests whose `status` is
    `SUBMITTED`, `HELD`, or `QUEUED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_transfer_screening_requires_active_partner_agreement
    """
    account, transfer = _submitted_transfer_then_agreement_suspended(api)

    validate_error(
        api.clear_screening(transfer["id"], {}, ANALYST_HEADERS),
        ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )

    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=6000,
        points_pending_redemption=4000,
    )


def _confirmed_order_then_agency_suspended(api):
    """A confirmed portal booking whose agency is pulled out from under it."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=DINING_MCC,
        display_name="Restaurants",
        base_category=CATEGORY_DINING,
        base_multiplier=3.0,
    )
    account = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Yusuf Brandt",
        email="yusuf@example.com",
        card_product_code=PRODUCT_PREMIER,
    )
    cardholder = fx.account_holder(account)
    fx.post_purchase(api, account["id"], 1600000, ADMIN_HEADERS, mcc_code=DINING_MCC)

    agency, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Northwind Travel",
            "contracted_markup_bps": 2000,
            "parity_tolerance_bps": 1000,
        },
        itinerary_code="ORD-FCO-03",
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=4000,
    )
    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Yusuf Brandt")
    assert order["points_debited"] == 35200
    assert order["issuer_cost_provisional_cents"] == 36000
    fx.confirm(api, order["id"], cardholder)
    validate_success(
        api.suspend_agency_partner(
            agency["id"], f.suspend_payload("IATA_LICENCE_LAPSED"), ADMIN_HEADERS
        )
    )
    return account, agency, offer, order, supplier


def test_ticketing_is_blocked_by_the_agency_behind_the_offer(api):
    """
    "the order's `fulfillment_status` must be `CONFIRMED`, its `channel` must be
    `PORTAL_BOOKING`, the offer's agency must be `ACTIVE` (`ERR_AGENCY_SUSPENDED`)"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_ticketing_requires_active_travel_agency
    """
    _, agency, offer, order, supplier = _confirmed_order_then_agency_suspended(api)

    validate_error(
        api.ticket_order(order["id"], f.ticket_payload("TKT-80014"), supplier),
        ERR_AGENCY_SUSPENDED,
        409,
    )

    assert (
        validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))["status"]
        == AGENCY_STATUS_SUSPENDED
    )
    suspended_offer = fx.read_offer(api, offer["id"], ADMIN_HEADERS)
    assert suspended_offer["status"] == OFFER_SUSPENDED
    assert suspended_offer["suspension_reason"] == SUSPENSION_AGENCY_SUSPENDED


def test_the_confirmed_order_and_the_agency_payable_are_both_left_alone(api):
    """
    "Redemption orders already `QUOTED` or `CONFIRMED` against the offer are untouched
    by the suspension."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_ticketing_requires_active_travel_agency
    """
    account, agency, _, order, supplier = _confirmed_order_then_agency_suspended(api)

    validate_error(
        api.ticket_order(order["id"], f.ticket_payload("TKT-80014"), supplier),
        ERR_AGENCY_SUSPENDED,
        409,
    )

    after = validate_success(api.get_order(order["id"], ADMIN_HEADERS))
    assert after["fulfillment_status"] == FULFILLMENT_CONFIRMED
    assert after["settlement_status"] == SETTLEMENT_UNSETTLED
    assert after["ticket_number"] is None
    assert (
        validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))[
            "payable_cents"
        ]
        == 0
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]), points_balance=36800
    )


def _lounge_entitlement_and_a_confirmed_booking(api):
    """A lounge benefit that insists on a ticketed booking, plus a confirmed one."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=DINING_MCC,
        display_name="Restaurants",
        base_category=CATEGORY_DINING,
        base_multiplier=3.0,
    )
    account = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Lila Mensah",
        email="lila@example.com",
        card_product_code=PRODUCT_PREMIER,
    )
    cardholder = fx.account_holder(account)
    fx.post_purchase(api, account["id"], 1600000, ADMIN_HEADERS, mcc_code=DINING_MCC)
    entitlement = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_LOUNGE_ACCESS,
        annual_allowance=2,
        requires_portal_booking=True,
    )
    agency, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Northwind Travel",
            "contracted_markup_bps": 2000,
            "parity_tolerance_bps": 1000,
        },
        itinerary_code="BOS-DUB-09",
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=4000,
    )
    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Lila Mensah")
    fx.confirm(api, order["id"], cardholder)
    return agency, order, entitlement, cardholder, supplier


def test_consuming_against_a_merely_confirmed_booking_is_refused(api):
    """
    "When `requires_portal_booking` is true the cited `redemption_order_id` must name
    an order whose `channel` is `PORTAL_BOOKING` and whose `fulfillment_status` is
    `TICKETED`, or the call is refused with `ERR_BENEFIT_REQUIRES_TICKETED_BOOKING`"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_benefit_consumption_requires_ticketed_order
    """
    _, order, entitlement, cardholder, _ = _lounge_entitlement_and_a_confirmed_booking(
        api
    )

    validate_error(
        api.consume_entitlement(
            entitlement["id"], f.consume_payload(order["id"]), cardholder
        ),
        ERR_BENEFIT_REQUIRES_TICKETED_BOOKING,
        409,
    )

    after = fx.read_entitlement(api, entitlement["id"])
    assert after["used_count"] == 0
    assert after["remaining_allowance"] == 2
    assert after["last_consumed_at"] is None


def test_the_identical_consume_call_is_admitted_once_that_order_is_ticketed(api):
    """
    "and `used_count` counts only consumptions that succeeded — a rejected consume
    call never increments it."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_benefit_consumption_requires_ticketed_order
    """
    _, order, entitlement, cardholder, supplier = (
        _lounge_entitlement_and_a_confirmed_booking(api)
    )
    validate_error(
        api.consume_entitlement(
            entitlement["id"], f.consume_payload(order["id"]), cardholder
        ),
        ERR_BENEFIT_REQUIRES_TICKETED_BOOKING,
        409,
    )
    fx.ticket(api, order["id"], supplier, "TKT-80015")

    consumed = validate_success(
        api.consume_entitlement(
            entitlement["id"], f.consume_payload(order["id"]), cardholder
        )
    )

    assert consumed["used_count"] == 1
    assert consumed["remaining_allowance"] == 1
    assert_timestamp_equals(consumed["last_consumed_at"], "2026-08-01T00:00:00.000Z")


def test_ticketing_the_cited_order_also_moves_the_cash_dimension(api):
    """
    "moves `settlement_status` from `UNSETTLED` to `AGENCY_INVOICED` while adding the
    order's `issuer_cost_provisional_cents` to the agency's `payable_cents`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_benefit_consumption_requires_ticketed_order
    """
    agency, order, _, _, supplier = _lounge_entitlement_and_a_confirmed_booking(api)

    ticketed = fx.ticket(api, order["id"], supplier, "TKT-80015")

    assert ticketed["fulfillment_status"] == FULFILLMENT_TICKETED
    assert ticketed["settlement_status"] == SETTLEMENT_AGENCY_INVOICED
    assert (
        validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))[
            "payable_cents"
        ]
        == 36000
    )
