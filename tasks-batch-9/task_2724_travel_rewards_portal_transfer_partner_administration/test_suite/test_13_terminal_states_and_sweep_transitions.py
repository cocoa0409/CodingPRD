"""
Terminal states that refuse a repeat action, the notice supersession cascade, and
the two sweep-driven transitions that end a transfer and an entitlement.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BENEFIT_NOT_CONSUMABLE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_TRANSFER_REVERSAL_WINDOW_EXPIRED,
)
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_page,
    assert_sweep_counters,
    assert_timestamp_equals,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    APPROVER_2_HEADERS,
    APPROVER_2_USER_ID,
    APPROVER_HEADERS,
)
from test_helpers.types import (
    ACCOUNT_CLOSED,
    AGENCY_SUSPENDED,
    BENEFIT_LOUNGE_ACCESS,
    BENEFIT_TRAVEL_INSURANCE,
    CATEGORY_GROCERY,
    CHANGE_BENEFIT_REMOVAL,
    CHANGE_EARN_MULTIPLIER_CUT,
    ENTITLEMENT_EXPIRED,
    FULFILLMENT_CANCELLED,
    NOTICE_ANNOUNCED,
    NOTICE_DRAFT,
    NOTICE_WITHDRAWN,
    OFFER_SUSPENDED,
    SUSPENSION_AGENCY_SUSPENDED,
    TRANSFER_COMPLETED,
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


def test_a_second_cancel_on_a_cancelled_order_is_refused_and_releases_nothing(api):
    """
    "**State.** The addressed row's current state is a declared origin state for the
    requested transition (`ERR_INVALID_STATE_TRANSITION`, 409, every action endpoint)."

    Design: Corner/state_machines/cancelling_an_already_cancelled_order_returns_409
    """
    _grocery(api)
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Petra Nowak", email="petra@example.com"
    )
    fx.fund_account(api, account["id"], 40000, mcc_code=GROCERY_MCC)
    _, offer, _ = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Bare Fare Consolidators",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code="CLT-BGI-10",
        net_rate_cents=10000,
        agency_public_price_cents=10000,
        agency_public_seats=2,
        portal_seats=2,
        tax_cents=0,
    )
    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Petra Nowak")
    validate_success(
        api.cancel_order(order["id"], f.cancel_payload("CHANGED_MIND"), cardholder)
    )

    validate_error(
        api.cancel_order(
            order["id"], f.cancel_payload("CHANGED_MIND_AGAIN"), cardholder
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    after = validate_success(api.get_order(order["id"], ADMIN_HEADERS))
    assert after["fulfillment_status"] == FULFILLMENT_CANCELLED
    assert after["closed_reason"] == "CHANGED_MIND"
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=40000,
        points_pending_redemption=0,
    )


def test_a_second_suspension_of_an_agency_is_refused_and_keeps_the_first_reason(api):
    """
    "Suspending an agency is a `ProgramAdmin` action that takes a `suspended_reason`
    and requires that the agency is currently `ACTIVE`."

    Design: Corner/state_machines/suspending_an_already_suspended_agency_returns_409
    """
    agency, offer, _ = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Northwind Travel",
            "contracted_markup_bps": 2000,
            "parity_tolerance_bps": 1000,
        },
        itinerary_code="EWR-LIS-13",
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=4000,
    )
    validate_success(
        api.suspend_agency_partner(
            agency["id"], f.suspend_payload("FIRST_SUSPENSION"), ADMIN_HEADERS
        )
    )

    validate_error(
        api.suspend_agency_partner(
            agency["id"], f.suspend_payload("SECOND_SUSPENSION"), ADMIN_HEADERS
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    after = validate_success(api.get_agency_partner(agency["id"], ADMIN_HEADERS))
    assert after["status"] == AGENCY_SUSPENDED
    assert after["suspended_reason"] == "FIRST_SUSPENSION"
    pulled = fx.read_offer(api, offer["id"])
    assert pulled["status"] == OFFER_SUSPENDED
    assert pulled["suspension_reason"] == SUSPENSION_AGENCY_SUSPENDED


def test_revising_a_notice_that_was_never_submitted_is_refused(api):
    """
    "An approver may bounce a pending notice back with a `PENDING_APPROVAL` → `DRAFT`
    revision that increments `version` by 1, and the draft/submit loop may repeat
    indefinitely."

    Design: Corner/state_machines/revising_a_draft_notice_returns_409
    """
    notice = fx.draft_notice(
        api,
        ADMIN_HEADERS,
        notice_code="NB-2026-02",
        change_type=CHANGE_BENEFIT_REMOVAL,
        effective_at="2026-12-01T00:00:00.000Z",
        grandfather_window_days=30,
        cohort_enrolled_before="2025-01-01T00:00:00.000Z",
    )

    validate_error(
        api.revise_notice(notice["id"], {}, APPROVER_HEADERS),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    after = fx.read_notice(api, notice["id"])
    assert after["status"] == NOTICE_DRAFT
    assert after["version"] == 1


def test_announcing_a_superseding_notice_withdraws_the_notice_it_replaces(api):
    """
    "It also cascades through the self-reference: when `supersedes_notice_id` is set
    and the notice it names is currently `ANNOUNCED`, that earlier notice moves to
    `WITHDRAWN` with `withdrawn_reason` `SUPERSEDED`."

    Design: Corner/state_machines/announcing_a_superseding_notice_withdraws_the_prior_notice
    """
    prior = fx.announced_notice(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        notice_code="NB-2026-10",
        change_type=CHANGE_EARN_MULTIPLIER_CUT,
        effective_at="2026-10-01T00:00:00.000Z",
        grandfather_window_days=30,
        cohort_enrolled_before="2025-01-01T00:00:00.000Z",
    )
    assert prior["status"] == NOTICE_ANNOUNCED
    successor = fx.draft_notice(
        api,
        ADMIN_HEADERS,
        notice_code="NB-2026-11",
        change_type=CHANGE_EARN_MULTIPLIER_CUT,
        effective_at="2026-11-01T00:00:00.000Z",
        grandfather_window_days=30,
        cohort_enrolled_before="2025-01-01T00:00:00.000Z",
        supersedes_notice_id=prior["id"],
    )
    validate_success(api.submit_notice(successor["id"], {}, ADMIN_HEADERS))

    announced = validate_success(
        api.announce_notice(successor["id"], {}, APPROVER_2_HEADERS)
    )

    assert announced["status"] == NOTICE_ANNOUNCED
    assert_timestamp_equals(announced["announced_at"], "2026-08-01T00:00:00.000Z")
    assert announced["approved_by_user_id"] == APPROVER_2_USER_ID
    assert announced["supersedes_notice_id"] == prior["id"]
    replaced = fx.read_notice(api, prior["id"])
    assert replaced["status"] == NOTICE_WITHDRAWN
    assert replaced["withdrawn_reason"] == "SUPERSEDED"


def test_the_sweep_posts_a_queued_transfer_at_its_scheduled_instant(api):
    """
    "Clearance sets `screening_cleared_at` to the clock instant and computes
    `scheduled_post_at` as that instant plus the agreement's
    `transfer_latency_hours`, then increments `version` by 1."

    Design: Corner/state_machines/queued_transfer_completes_on_ops_run_then_reversal_after_window_rejected
    """
    _grocery(api)
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Juno Marek", email="juno@example.com"
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
    queued = fx.clear_screening(api, transfer["id"], ANALYST_HEADERS)
    assert_timestamp_equals(queued["screening_cleared_at"], "2026-08-01T00:00:00.000Z")
    assert_timestamp_equals(queued["scheduled_post_at"], "2026-08-03T00:00:00.000Z")

    fx.set_clock(api, "2026-08-03T00:00:00.000Z")
    sweep = fx.ops_run(api)

    assert_sweep_counters(sweep, transfers_completed=1)
    assert_timestamp_equals(sweep["clock_utc"], "2026-08-03T00:00:00.000Z")
    posted = fx.read_transfer(api, transfer["id"])
    assert posted["status"] == TRANSFER_COMPLETED
    assert_timestamp_equals(posted["completed_at"], "2026-08-03T00:00:00.000Z")
    assert posted["base_units"] == 4000
    assert posted["bonus_units"] == 0
    assert posted["partner_units_credited"] == 4000
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=6000,
        points_pending_redemption=0,
    )


def test_a_reversal_past_the_agreement_window_leaves_the_credited_units_standing(api):
    """
    "A programme administrator may reverse a `COMPLETED` transfer with a
    `resolution_reason`, but only while the clock instant is at or before
    `completed_at` plus the agreement's `reversal_window_hours`; once past that
    deadline the request is rejected with `ERR_TRANSFER_REVERSAL_WINDOW_EXPIRED`."

    Design: Corner/state_machines/queued_transfer_completes_on_ops_run_then_reversal_after_window_rejected
    """
    _grocery(api)
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Juno Marek", email="juno@example.com"
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
    fx.clear_screening(api, transfer["id"], ANALYST_HEADERS)
    fx.set_clock(api, "2026-08-03T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), transfers_completed=1)

    fx.set_clock(api, "2026-08-07T00:00:00.000Z")
    validate_error(
        api.reverse_transfer(
            transfer["id"], f.resolution_payload("PARTNER_DISPUTE"), ADMIN_HEADERS
        ),
        ERR_TRANSFER_REVERSAL_WINDOW_EXPIRED,
        409,
    )

    after = fx.read_transfer(api, transfer["id"])
    assert after["status"] == TRANSFER_COMPLETED
    assert after["reversed_at"] is None
    assert after["partner_units_credited"] == 4000


def test_the_sweep_expires_an_entitlement_and_a_later_consume_is_refused(api):
    """
    "the sweep expires an entitlement that is `ACTIVE` or `SUSPENDED` once the clock
    instant reaches or passes its `expires_at` ... Either way `version` increments by
    1 and every subsequent consume attempt is refused with
    `ERR_BENEFIT_NOT_CONSUMABLE`."

    Design: Corner/state_machines/entitlement_expires_on_ops_run_and_then_consume_rejected
    """
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Sol Vega", email="sol@example.com"
    )
    entitlement = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_TRAVEL_INSURANCE,
        annual_allowance=2,
        expires_at="2026-08-15T00:00:00.000Z",
        requires_portal_booking=False,
    )

    fx.set_clock(api, "2026-08-15T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), entitlements_expired=1)
    assert fx.read_entitlement(api, entitlement["id"])["status"] == ENTITLEMENT_EXPIRED

    validate_error(
        api.consume_entitlement(entitlement["id"], {}, cardholder),
        ERR_BENEFIT_NOT_CONSUMABLE,
        409,
    )

    after = fx.read_entitlement(api, entitlement["id"])
    assert after["used_count"] == 0
    assert after["remaining_allowance"] == 2
    assert after["last_consumed_at"] is None


def test_closing_an_account_expires_every_active_entitlement_it_holds(api):
    """
    "On success the transition `ACTIVE` → `CLOSED` sets `closed_at` to the clock
    instant, moves every benefit entitlement of the account that is currently
    `ACTIVE` to `EXPIRED`, and increments the account's `version` by 1."

    Design: Corner/state_machines/closing_an_account_expires_its_active_entitlements
    """
    _grocery(api)
    account, _ = fx.funded_account(
        api, 0, cardholder_name="Bo Iversen", email="bo@example.com"
    )
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
    lounge = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_LOUNGE_ACCESS,
        annual_allowance=4,
        expires_at="2027-01-01T00:00:00.000Z",
        requires_portal_booking=False,
    )
    insurance = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_TRAVEL_INSURANCE,
        annual_allowance=2,
        expires_at="2027-01-01T00:00:00.000Z",
        requires_portal_booking=False,
    )

    closed = validate_success(api.close_account(account["id"], {}, ADMIN_HEADERS))

    assert closed["status"] == ACCOUNT_CLOSED
    assert_timestamp_equals(closed["closed_at"], "2026-08-01T00:00:00.000Z")
    assert fx.read_entitlement(api, lounge["id"])["status"] == ENTITLEMENT_EXPIRED
    assert fx.read_entitlement(api, insurance["id"])["status"] == ENTITLEMENT_EXPIRED
    assert_account_aggregates(closed, points_balance=10000)
    assert_page(
        api.list_ledger_entries(ADMIN_HEADERS, {"account_id": account["id"]}),
        total_count=1,
        length=1,
    )
