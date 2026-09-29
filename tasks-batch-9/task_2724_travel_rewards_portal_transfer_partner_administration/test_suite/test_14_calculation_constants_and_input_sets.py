"""
Calculation surfaces: the grandfathering chain that resolves a transfer's ratio, the
`LEGACY_GOLD` constant pair, the available-points input set, and the two ATO legs.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INSUFFICIENT_POINTS
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_page,
    assert_sweep_counters,
    assert_timestamp_equals,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    APPROVER_HEADERS,
)
from test_helpers.types import (
    CASE_OPEN,
    CASE_UNDER_REVIEW,
    CATEGORY_DINING,
    CATEGORY_GROCERY,
    CHANNEL_STATEMENT_CREDIT,
    FULFILLMENT_QUOTED,
    NOTICE_EFFECTIVE,
    PARITY_IN,
    POSTURE_LOCKED,
    POSTURE_WATCH,
    PRODUCT_LEGACY_GOLD,
    SIGNAL_DEVICE_CHANGE,
    SIGNAL_EMAIL_CHANGE,
    SIGNAL_GEO_ANOMALY,
    SIGNAL_NEW_PAYEE,
    SIGNAL_PASSWORD_RESET,
    TRANSFER_COMPLETED,
    TRANSFER_REJECTED,
)

GROCERY_MCC = "5411"
DINING_MCC = "5812"


def _grocery(api):
    """The 1.0x grocery mapping the funding purchases of this file ride on."""
    return fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )


def _two_cohorts_under_one_ratio_notice(api):
    """
    One in-cohort account, one out-of-cohort account, and an `ANNOUNCED`
    `TRANSFER_RATIO_CHANGE` notice on the agreement both of them will transfer into.
    """
    _grocery(api)
    old, old_holder = fx.funded_account(
        api,
        0,
        cardholder_name="Odile Fournier",
        email="odile@example.com",
        enrolled_at="2024-06-01T00:00:00.000Z",
    )
    new, new_holder = fx.funded_account(
        api,
        0,
        cardholder_name="Nils Aaberg",
        email="nils@example.com",
        enrolled_at="2026-01-01T00:00:00.000Z",
    )
    fx.fund_account(api, old["id"], 10000, mcc_code=GROCERY_MCC)
    fx.fund_account(api, new["id"], 10000, mcc_code=GROCERY_MCC)
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        ratio_points_out=1000,
        ratio_partner_units_in=1000,
        transfer_latency_hours=48,
        reversal_window_hours=72,
        settlement_cost_cents_per_1k=900,
    )
    notice = fx.announced_notice(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        notice_code="RATIO-2026-10",
        target_agreement_id=agreement["id"],
        new_ratio_points_out=2000,
        new_ratio_partner_units_in=1000,
        effective_at="2026-10-01T00:00:00.000Z",
        grandfather_window_days=30,
        cohort_enrolled_before="2025-01-01T00:00:00.000Z",
    )
    return {
        "old": old,
        "old_holder": old_holder,
        "new": new,
        "new_holder": new_holder,
        "agreement": agreement,
        "notice": notice,
    }


def test_the_effective_notice_protects_the_cohort_and_repoints_everyone_else(api):
    """
    "An account whose `enrolled_at` is strictly before the notice's
    `cohort_enrolled_before` is protected: it keeps whatever `terms_notice_id` it
    already had, records the new notice as its `pending_notice_id`, and receives a
    `grandfather_expires_at` equal to the notice's `effective_at` plus
    `grandfather_window_days` days."

    Design: Corner/calculations/grandfathered_cohort_keeps_old_ratio_until_its_window_matures
    """
    world = _two_cohorts_under_one_ratio_notice(api)

    fx.set_clock(api, "2026-10-01T00:00:00.000Z")
    sweep = fx.ops_run(api)

    assert_sweep_counters(
        sweep, notices_made_effective=1, grandfather_windows_matured=0
    )
    assert fx.read_notice(api, world["notice"]["id"])["status"] == NOTICE_EFFECTIVE
    protected = fx.read_account(api, world["old"]["id"])
    assert protected["pending_notice_id"] == world["notice"]["id"]
    assert protected["terms_notice_id"] is None
    assert_timestamp_equals(
        protected["grandfather_expires_at"], "2026-10-31T00:00:00.000Z"
    )
    repointed = fx.read_account(api, world["new"]["id"])
    assert repointed["terms_notice_id"] == world["notice"]["id"]
    assert repointed["pending_notice_id"] is None
    assert repointed["grandfather_expires_at"] is None


def test_the_applied_ratio_follows_each_accounts_governing_notice(api):
    """
    "If there is such a notice, and its `status` is `EFFECTIVE`, and its `change_type`
    is `TRANSFER_RATIO_CHANGE`, and its `target_agreement_id` equals the agreement
    being transferred into, then the applied ratio is that notice's
    `new_ratio_points_out` and `new_ratio_partner_units_in`."

    Design: Corner/calculations/grandfathered_cohort_keeps_old_ratio_until_its_window_matures
    """
    world = _two_cohorts_under_one_ratio_notice(api)
    fx.set_clock(api, "2026-10-01T00:00:00.000Z")
    fx.ops_run(api)
    old_transfer = fx.submit_transfer(
        api, world["old"]["id"], world["agreement"]["id"], 4000, world["old_holder"]
    )
    new_transfer = fx.submit_transfer(
        api, world["new"]["id"], world["agreement"]["id"], 4000, world["new_holder"]
    )
    fx.clear_screening(api, old_transfer["id"], ANALYST_HEADERS)
    fx.clear_screening(api, new_transfer["id"], ANALYST_HEADERS)

    fx.set_clock(api, "2026-10-03T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), transfers_completed=2)

    grandfathered = fx.read_transfer(api, old_transfer["id"])
    assert grandfathered["status"] == TRANSFER_COMPLETED
    assert grandfathered["ratio_points_out_applied"] == 1000
    assert grandfathered["ratio_partner_units_in_applied"] == 1000
    assert grandfathered["base_units"] == 4000
    assert grandfathered["bonus_units"] == 0
    assert grandfathered["partner_units_credited"] == 4000
    cut = fx.read_transfer(api, new_transfer["id"])
    assert cut["ratio_points_out_applied"] == 2000
    assert cut["ratio_partner_units_in_applied"] == 1000
    assert cut["base_units"] == 2000
    assert cut["bonus_units"] == 0
    assert cut["partner_units_credited"] == 2000


def test_a_matured_grandfather_window_promotes_the_pending_notice(api):
    """
    "Any account carrying a non-null `pending_notice_id` whose
    `grandfather_expires_at` the clock has reached or passed has that pending notice
    promoted into `terms_notice_id`, with `pending_notice_id` cleared to null;
    `grandfather_expires_at` is retained as an audit fact rather than cleared."

    Design: Corner/calculations/grandfathered_cohort_keeps_old_ratio_until_its_window_matures
    """
    world = _two_cohorts_under_one_ratio_notice(api)
    fx.set_clock(api, "2026-10-01T00:00:00.000Z")
    fx.ops_run(api)

    fx.set_clock(api, "2026-10-31T00:00:00.000Z")
    assert_sweep_counters(
        fx.ops_run(api), grandfather_windows_matured=1, transfers_completed=0
    )

    matured = fx.read_account(api, world["old"]["id"])
    assert matured["terms_notice_id"] == world["notice"]["id"]
    assert matured["pending_notice_id"] is None
    assert_timestamp_equals(
        matured["grandfather_expires_at"], "2026-10-31T00:00:00.000Z"
    )


def _legacy_gold_with_an_offer(api):
    """A `LEGACY_GOLD` account, a 3.0x dining mapping, and one 48,000-cent offer."""
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
        cardholder_name="Greta Halvorsen",
        email="greta@example.com",
        card_product_code=PRODUCT_LEGACY_GOLD,
        enrolled_at="2019-04-11T00:00:00.000Z",
    )
    _, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Northwind Travel",
            "contracted_markup_bps": 2000,
            "parity_tolerance_bps": 1000,
        },
        itinerary_code="OSL-BKK-21",
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=4000,
    )
    return account, fx.account_holder(account), offer, supplier


def test_the_legacy_gold_earn_multiplier_doubles_the_category_leg(api):
    """
    "Billable dollars are multiplied by the effective base multiplier and then by the
    card product's earn multiplier — 1.5 for `PREMIER`, 1.0 for `CORE`, and 2.0 for
    `LEGACY_GOLD` — and the result is floored to a whole number of `base_points`."

    Design: Corner/calculations/legacy_gold_product_constants_drive_earn_and_redemption_pricing
    """
    account, _, offer, _ = _legacy_gold_with_an_offer(api)

    purchase = fx.post_purchase(
        api, account["id"], 1600000, headers=ADMIN_HEADERS, mcc_code=DINING_MCC
    )

    assert purchase["base_points"] == 96000
    assert purchase["bonus_points"] == 0
    assert purchase["total_points_earned"] == 96000
    assert offer["portal_price_cents"] == 48000
    assert offer["cash_copay_cents"] == 4000
    assert offer["parity_status"] == PARITY_IN
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=96000,
        lifetime_points_earned=96000,
    )


def test_the_legacy_gold_redemption_rate_rounds_the_points_price_up(api):
    """
    "The redemption rate is pinned from the account's `card_product_code` at quote
    time and stored on the order as `cents_per_point_applied`: 1.25 cents per point
    for `PREMIER`, 1.0 for `CORE`, and 1.5 for `LEGACY_GOLD`."

    Design: Corner/calculations/legacy_gold_product_constants_drive_earn_and_redemption_pricing
    """
    account, cardholder, offer, _ = _legacy_gold_with_an_offer(api)
    fx.post_purchase(
        api, account["id"], 1600000, headers=ADMIN_HEADERS, mcc_code=DINING_MCC
    )

    order = fx.book(
        api, offer, account["id"], cardholder, traveler_name="Greta Halvorsen"
    )

    assert order["cents_per_point_applied"] == 1.5
    assert order["points_debited"] == 29334
    assert order["cash_copay_cents"] == 4000
    assert order["statement_credit_cents"] == 0
    assert order["issuer_cost_provisional_cents"] == 36000
    assert order["cost_per_1k_provisional_cents"] == 1227
    assert order["issuer_cost_final_cents"] is None
    assert order["cost_per_1k_final_cents"] is None

    fx.confirm(api, order["id"], cardholder)

    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=66666,
        points_pending_redemption=0,
        lifetime_points_earned=96000,
        lifetime_points_redeemed=29334,
    )


def _all_ten_thousand_points_reserved_by_a_quote(api):
    """A 10,000-point account whose whole balance sits behind one `QUOTED` booking."""
    _grocery(api)
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Rune Dahl", email="rune@example.com"
    )
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
    _, offer, _ = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Bare Fare Consolidators",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code="BOS-YUL-17",
        net_rate_cents=10000,
        agency_public_price_cents=10000,
        agency_public_seats=2,
        portal_seats=2,
        tax_cents=0,
    )
    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Rune Dahl")
    assert order["points_debited"] == 10000
    return account, cardholder, order


def test_a_quoted_reservation_is_subtracted_from_available_points(api):
    """
    "Available points are `points_balance` less the sum of `points_debited` over the
    account's `QUOTED` redemption orders — and nothing else."

    Design: Corner/calculations/available_points_subtracts_quoted_orders_only_not_confirmed_ones
    """
    account, cardholder, quote = _all_ten_thousand_points_reserved_by_a_quote(api)

    validate_error(
        api.create_order(
            f.statement_credit_payload(account["id"], points_requested=3000), cardholder
        ),
        ERR_INSUFFICIENT_POINTS,
        402,
    )

    assert_page(
        api.list_orders(ADMIN_HEADERS, {"channel": CHANNEL_STATEMENT_CREDIT}),
        total_count=0,
        length=0,
    )
    validate_success(
        api.cancel_order(quote["id"], f.cancel_payload("FREEING_POINTS"), cardholder)
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=10000,
        points_pending_redemption=0,
    )


def test_a_confirmed_burn_is_never_subtracted_twice_and_equality_is_admitted(api):
    """
    "A requested burn is admitted when it is less than or equal to available points;
    equality is admitted, and a burn strictly greater than available points is
    rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 402)."

    Design: Corner/calculations/available_points_subtracts_quoted_orders_only_not_confirmed_ones
    """
    account, cardholder, quote = _all_ten_thousand_points_reserved_by_a_quote(api)
    validate_success(
        api.cancel_order(quote["id"], f.cancel_payload("FREEING_POINTS"), cardholder)
    )

    credit = validate_success(
        api.create_order(
            f.statement_credit_payload(account["id"], points_requested=3000), cardholder
        ),
        201,
    )
    assert credit["points_debited"] == 3000
    assert credit["statement_credit_cents"] == 3000
    assert credit["cash_copay_cents"] == 0
    assert credit["inventory_offer_id"] is None
    assert credit["issuer_cost_provisional_cents"] == 0
    fx.confirm(api, credit["id"], cardholder)
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=7000,
        points_pending_redemption=0,
    )

    exact = validate_success(
        api.create_order(
            f.statement_credit_payload(account["id"], points_requested=7000), cardholder
        ),
        201,
    )

    assert exact["fulfillment_status"] == FULFILLMENT_QUOTED
    assert exact["points_debited"] == 7000
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=7000,
        points_pending_redemption=7000,
    )


def test_the_instant_leg_is_the_plain_sum_of_the_signal_weights(api):
    """
    "At case opening the `instant_score` is the sum of the weights of the case's
    distinct signals, capped at 100: a device change contributes 30, a new payee 25,
    an email change 20, a password reset 15, and a geographic anomaly 10."

    Design: Corner/calculations/ato_signal_weights_sum_and_full_signal_set_scores_exactly_one_hundred
    """
    two_signal_account, _ = fx.funded_account(
        api, 0, cardholder_name="Ines Cabral", email="ines@example.com"
    )
    every_signal_account, _ = fx.funded_account(
        api, 0, cardholder_name="Otto Brandt", email="otto@example.com"
    )

    watched = fx.open_case(
        api,
        two_signal_account["id"],
        ANALYST_HEADERS,
        signals=[SIGNAL_DEVICE_CHANGE, SIGNAL_EMAIL_CHANGE],
        device_fingerprint_changed=True,
    )
    locked = fx.open_case(
        api,
        every_signal_account["id"],
        ANALYST_HEADERS,
        signals=[
            SIGNAL_DEVICE_CHANGE,
            SIGNAL_EMAIL_CHANGE,
            SIGNAL_PASSWORD_RESET,
            SIGNAL_NEW_PAYEE,
            SIGNAL_GEO_ANOMALY,
        ],
        device_fingerprint_changed=True,
    )

    assert watched["risk_score"] == 50
    assert watched["review_score"] is None
    assert watched["status"] == CASE_OPEN
    assert watched["opened_by_user_id"] == ANALYST_USER_ID
    assert_account_aggregates(
        fx.read_account(api, two_signal_account["id"]), fraud_posture=POSTURE_WATCH
    )
    assert locked["risk_score"] == 100
    assert_account_aggregates(
        fx.read_account(api, every_signal_account["id"]), fraud_posture=POSTURE_LOCKED
    )


def _four_fifty_thousand_point_transfers_then_a_case(api):
    """200,000 points fully committed to four `SUBMITTED` transfers, then one case."""
    _grocery(api)
    account, cardholder = fx.funded_account(
        api, 0, cardholder_name="Mira Solberg", email="mira@example.com"
    )
    fx.fund_account(api, account["id"], 200000, mcc_code=GROCERY_MCC)
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
    transfers = [
        fx.submit_transfer(api, account["id"], agreement["id"], 50000, cardholder)
        for _ in range(4)
    ]
    fx.set_clock(api, "2026-08-02T00:00:00.000Z")
    case = fx.open_case(
        api,
        account["id"],
        ANALYST_HEADERS,
        signals=[SIGNAL_DEVICE_CHANGE],
        device_fingerprint_changed=True,
    )
    return account, transfers, case


def test_the_velocity_term_stops_at_forty_however_many_steps_it_earned(api):
    """
    "that window total is divided by 50,000 using integer floor division, multiplied
    by 10, and capped at 40."

    Design: Corner/calculations/velocity_term_caps_at_forty_and_review_leg_locks_and_rejects_transfers
    """
    account, _, case = _four_fifty_thousand_point_transfers_then_a_case(api)
    assert case["risk_score"] == 30
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=0,
        points_pending_redemption=200000,
        fraud_posture=POSTURE_WATCH,
    )

    reviewed = fx.review_case(api, case["id"], ANALYST_HEADERS)

    assert reviewed["review_score"] == 70
    assert reviewed["risk_score"] == 70
    assert reviewed["status"] == CASE_UNDER_REVIEW
    assert_timestamp_equals(reviewed["reviewed_at"], "2026-08-02T00:00:00.000Z")


def test_crossing_the_lock_threshold_rejects_every_transfer_still_in_flight(api):
    """
    "Moving to `LOCKED` — whether from `WATCH` or directly from `CLEAR` when a freshly
    opened case already scores at least 60 — is far heavier: every transfer request of
    the account whose `status` is `SUBMITTED`, `QUEUED`, or `HELD` is moved to
    `REJECTED`"

    Design: Corner/calculations/velocity_term_caps_at_forty_and_review_leg_locks_and_rejects_transfers
    """
    account, transfers, case = _four_fifty_thousand_point_transfers_then_a_case(api)

    fx.review_case(api, case["id"], ANALYST_HEADERS)

    rows = [fx.read_transfer(api, transfer["id"]) for transfer in transfers]
    assert [row["status"] for row in rows] == [TRANSFER_REJECTED] * 4
    assert rows[0]["resolution_reason"] == "POSTURE_LOCKED"
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=200000,
        points_pending_redemption=0,
        fraud_posture=POSTURE_LOCKED,
        transfer_hold_count=0,
    )
