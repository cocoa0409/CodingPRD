"""
State machines: the rotation's four-state walk, declared initial states, three
preconditions that refuse a transition, and the offer's capacity cycle.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACCOUNT_HAS_IN_FLIGHT_POINTS,
    ERR_AGREEMENT_HAS_IN_FLIGHT_TRANSFERS,
    ERR_OFFER_HAS_COMMITTED_SEATS,
)
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_ledger_entry_types,
    assert_sweep_counters,
    assert_timestamp_equals,
    read_ledger,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    ACCOUNT_ACTIVE,
    AGREEMENT_DRAFT,
    AGREEMENT_SUSPENDED,
    CATEGORY_GROCERY,
    ENTRY_EARN_BASE,
    FULFILLMENT_CANCELLED,
    FULFILLMENT_QUOTED,
    NOTICE_DRAFT,
    OFFER_OPEN,
    OFFER_SOLD_OUT,
    ROTATION_ACTIVE,
    ROTATION_DRAFT,
    ROTATION_EXPIRED,
    ROTATION_SCHEDULED,
    SETTLEMENT_UNSETTLED,
    TRANSFER_HELD,
)

GROCERY_MCC = "5411"


def _cheap_offer(api, portal_seats=2, agency_public_seats=2, itinerary_code="PDX-YVR-08"):
    """A zero-markup, zero-tax offer whose portal price is exactly 10,000 cents."""
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
        agency_public_seats=agency_public_seats,
        portal_seats=portal_seats,
        tax_cents=0,
    )


def test_the_rotation_walks_draft_to_scheduled_to_active_to_expired(api):
    """
    "`SCHEDULED` → `ACTIVE` fires once the clock instant reaches or passes
    `window_start`, setting `activated_at` and incrementing `version`, and from that
    moment the rotation participates in points awards for matching purchases.
    `ACTIVE` → `EXPIRED` fires once the clock instant reaches or passes `window_end`,
    setting `expired_at` and incrementing `version`"

    Design: Corner/state_machines/rotation_publishes_then_ops_run_activates_and_expires_it
    """
    category = fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    rotation = validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="AUTUMN-GROCERY",
                bonus_multiplier=2.0,
                capped_spend_cents=100000,
                window_start="2026-09-01T00:00:00.000Z",
                window_end="2026-10-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    published = validate_success(api.publish_rotation(rotation["id"], {}, ADMIN_HEADERS))
    assert published["status"] == ROTATION_SCHEDULED
    assert_timestamp_equals(published["published_at"], "2026-08-01T00:00:00.000Z")

    fx.set_clock(api, "2026-09-01T00:00:00.000Z")
    first_sweep = fx.ops_run(api)
    assert_sweep_counters(first_sweep, rotations_activated=1, rotations_expired=0)
    assert_timestamp_equals(first_sweep["clock_utc"], "2026-09-01T00:00:00.000Z")
    activated = validate_success(api.get_rotation(rotation["id"], ADMIN_HEADERS))
    assert activated["status"] == ROTATION_ACTIVE
    assert_timestamp_equals(activated["activated_at"], "2026-09-01T00:00:00.000Z")

    fx.set_clock(api, "2026-10-01T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), rotations_activated=0, rotations_expired=1)
    expired = validate_success(api.get_rotation(rotation["id"], ADMIN_HEADERS))
    assert expired["status"] == ROTATION_EXPIRED
    assert_timestamp_equals(expired["expired_at"], "2026-10-01T00:00:00.000Z")


def test_every_configuration_entity_is_born_in_its_declared_initial_state(api):
    """
    "A newly created rotation is `DRAFT`." ... "A fresh agreement is `DRAFT`, with
    `submitted_by_user_id`, `approved_by_user_id`, `activated_at`, and
    `suspension_reason` all null."

    Design: Corner/state_machines/configuration_entities_start_in_their_declared_initial_states
    """
    category = fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )

    rotation = validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"], rotation_code="INIT-ROT"
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    agreement = fx.draft_agreement(api, ADMIN_HEADERS)
    notice = validate_success(
        api.create_notice(f.notice_payload(notice_code="INIT-NOTICE"), ADMIN_HEADERS),
        201,
    )
    _, offer, _ = _cheap_offer(api, itinerary_code="INIT-OFFER-01")

    assert rotation["status"] == ROTATION_DRAFT
    assert rotation["published_at"] is None
    assert agreement["status"] == AGREEMENT_DRAFT
    assert agreement["submitted_by_user_id"] is None
    assert agreement["approved_by_user_id"] is None
    assert agreement["activated_at"] is None
    assert notice["status"] == NOTICE_DRAFT
    assert offer["status"] == OFFER_OPEN
    assert offer["seats_committed"] == 0


def test_an_offer_with_one_committed_seat_cannot_be_withdrawn(api):
    """
    "An offer with even one committed seat cannot be withdrawn and is rejected with
    `ERR_OFFER_HAS_COMMITTED_SEATS`."

    Design: Corner/state_machines/offer_withdraw_with_a_committed_seat_rejected
    """
    account, cardholder = fx.funded_account(
        api, 40000, cardholder_name="Tomas Ruiz", email="tomas@example.com"
    )
    _, offer, supplier = _cheap_offer(api)
    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Tomas Ruiz")

    validate_error(
        api.withdraw_offer(offer["id"], {}, supplier),
        ERR_OFFER_HAS_COMMITTED_SEATS,
        409,
    )

    after = fx.read_offer(api, offer["id"], supplier)
    assert after["status"] == OFFER_OPEN
    assert after["seats_committed"] == 1
    assert (
        validate_success(api.get_order(order["id"], ADMIN_HEADERS))["fulfillment_status"]
        == FULFILLMENT_QUOTED
    )


def test_an_account_with_a_quoted_order_cannot_be_closed(api):
    """
    "The account must currently be `ACTIVE`; no transfer request belonging to it may
    be in `SUBMITTED`, `QUEUED`, or `HELD`; and no redemption order belonging to it
    may be in `QUOTED` or `CONFIRMED` fulfilment. A violation of either in-flight
    condition is rejected with `ERR_ACCOUNT_HAS_IN_FLIGHT_POINTS`."

    Design: Corner/state_machines/account_close_with_quoted_order_rejected
    """
    account, cardholder = fx.funded_account(
        api, 40000, cardholder_name="Neve Larsen", email="neve@example.com"
    )
    _, offer, _ = _cheap_offer(api, itinerary_code="AUS-MEX-12")
    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Neve Larsen")

    validate_error(
        api.close_account(account["id"], {}, ADMIN_HEADERS),
        ERR_ACCOUNT_HAS_IN_FLIGHT_POINTS,
        409,
    )

    after = fx.read_account(api, account["id"])
    assert after["status"] == ACCOUNT_ACTIVE
    assert after["closed_at"] is None
    assert_account_aggregates(after, points_pending_redemption=10000)
    assert (
        validate_success(api.get_order(order["id"], ADMIN_HEADERS))["fulfillment_status"]
        == FULFILLMENT_QUOTED
    )


def test_a_suspended_agreement_still_holding_a_transfer_cannot_be_terminated(api):
    """
    "the agreement being terminated has no transfers in flight
    (`ERR_AGREEMENT_HAS_IN_FLIGHT_TRANSFERS`, 409)."

    Design: Corner/state_machines/agreement_terminate_with_held_transfer_rejected
    """
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Emil Torres", email="emil@example.com"
    )
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
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
    fx.hold_transfer(api, transfer["id"], ANALYST_HEADERS)
    validate_success(
        api.suspend_agreement(
            agreement["id"], f.offer_suspend_payload("WIND_DOWN"), ADMIN_HEADERS
        )
    )

    validate_error(
        api.terminate_agreement(agreement["id"], {}, APPROVER_HEADERS),
        ERR_AGREEMENT_HAS_IN_FLIGHT_TRANSFERS,
        409,
    )

    after = validate_success(api.get_agreement(agreement["id"], ADMIN_HEADERS))
    assert after["status"] == AGREEMENT_SUSPENDED
    assert after["suspension_reason"] == "WIND_DOWN"
    assert fx.read_transfer(api, transfer["id"])["status"] == TRANSFER_HELD


def test_the_last_seat_sells_the_offer_out_and_a_cancel_reopens_it(api):
    """
    "When a new booking consumes the last seat — that is, when `seats_committed`
    before the booking plus one equals `portal_seats` — the offer moves `OPEN` →
    `SOLD_OUT` after `seats_committed` is recomputed, and `version` increments by 1."

    Design: Corner/state_machines/offer_sells_out_on_last_seat_and_reopens_when_order_cancelled
    """
    account, cardholder = fx.funded_account(
        api, 40000, cardholder_name="Alba Reyes", email="alba@example.com"
    )
    _, offer, supplier = _cheap_offer(
        api, portal_seats=1, agency_public_seats=1, itinerary_code="SLC-HNL-04"
    )

    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Alba Reyes")
    sold_out = fx.read_offer(api, offer["id"], supplier)
    assert sold_out["status"] == OFFER_SOLD_OUT
    assert sold_out["seats_committed"] == 1
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=40000,
        points_pending_redemption=10000,
    )

    cancelled = validate_success(
        api.cancel_order(order["id"], f.cancel_payload("CHANGED_MIND"), cardholder)
    )

    assert cancelled["fulfillment_status"] == FULFILLMENT_CANCELLED
    assert cancelled["settlement_status"] == SETTLEMENT_UNSETTLED
    assert cancelled["closed_reason"] == "CHANGED_MIND"
    reopened = fx.read_offer(api, offer["id"], supplier)
    assert reopened["status"] == OFFER_OPEN
    assert reopened["seats_committed"] == 0
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=40000,
        points_pending_redemption=0,
    )
    assert_ledger_entry_types(read_ledger(api, ADMIN_HEADERS, account["id"]), [ENTRY_EARN_BASE])
