"""
Combinatorial arithmetic: two earning legs floored independently, partner units
floored per thousand-point block, and a liability tier pinned to step one's gross.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_account_aggregates,
    assert_ledger_entry,
    assert_ledger_entry_types,
    assert_sweep_counters,
    read_ledger,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    CATEGORY_DINING,
    CATEGORY_GROCERY,
    CLASSIFICATION_MAPPED,
    ENTRY_EARN_BASE,
    ENTRY_EARN_BONUS,
    EVENT_RUNNING,
    METHOD_COST_BASIS,
    METHOD_FAIR_VALUE,
    PRODUCT_PREMIER,
    ROTATION_ACTIVE,
    TRANSFER_COMPLETED,
)

DINING_MCC = "5812"
GROCERY_MCC = "5411"


def _active_dining_rotation(api):
    """A 2.25x dining rotation walked to `ACTIVE` with the clock inside its window."""
    category = fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=DINING_MCC,
        display_name="Restaurants",
        base_category=CATEGORY_DINING,
        base_multiplier=1.5,
    )
    created = validate_success(
        api.create_rotation(
            f.rotation_payload(
                merchant_category_id=category["id"],
                rotation_code="Q4-DINING",
                bonus_multiplier=2.25,
                capped_spend_cents=100000,
                window_start="2026-09-01T00:00:00.000Z",
                window_end="2026-10-01T00:00:00.000Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(api.publish_rotation(created["id"], {}, ADMIN_HEADERS))
    fx.set_clock(api, "2026-09-05T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), rotations_activated=1)
    rotation = validate_success(api.get_rotation(created["id"], ADMIN_HEADERS))
    assert rotation["status"] == ROTATION_ACTIVE
    return category, rotation


def test_base_and_bonus_legs_are_floored_apart_so_the_total_is_not_the_floored_sum(api):
    """
    "The base earn leg and the rotation bonus leg are each floored on their own, and
    only then added together. Flooring the sum instead of the two legs produces a
    different point total whenever both legs have fractional parts."

    Design: Difficulty/combinatorial_formula/combinatorial_earning_two_legs_floored_independently_then_summed
    """
    category, rotation = _active_dining_rotation(api)
    account = fx.new_account(api, ADMIN_HEADERS, card_product_code=PRODUCT_PREMIER)

    purchase = fx.post_purchase(
        api,
        account["id"],
        12345,
        headers=ADMIN_HEADERS,
        mcc_code=DINING_MCC,
        posted_at="2026-09-10T00:00:00.000Z",
    )

    assert purchase["classification_source"] == CLASSIFICATION_MAPPED
    assert purchase["merchant_category_id"] == category["id"]
    assert purchase["rotation_id"] == rotation["id"]
    assert purchase["rotation_eligible_cents"] == 12345
    assert purchase["base_points"] == 276
    assert purchase["bonus_points"] == 230
    assert purchase["total_points_earned"] == 506
    assert purchase["total_points_earned"] != 507


def test_each_earning_leg_appends_its_own_ledger_entry_base_before_bonus(api):
    """
    "an `EARN_BASE` entry carrying `base_points` as a positive `points_delta` is
    always appended first, and a second `EARN_BONUS` entry carrying `bonus_points` is
    appended only when `bonus_points` is strictly greater than zero."

    Design: Difficulty/combinatorial_formula/combinatorial_earning_two_legs_floored_independently_then_summed
    """
    _active_dining_rotation(api)
    account = fx.new_account(api, ADMIN_HEADERS, card_product_code=PRODUCT_PREMIER)
    purchase = fx.post_purchase(
        api,
        account["id"],
        12345,
        headers=ADMIN_HEADERS,
        mcc_code=DINING_MCC,
        posted_at="2026-09-10T00:00:00.000Z",
    )

    entries = read_ledger(api, ADMIN_HEADERS, account["id"])
    assert_ledger_entry_types(entries, [ENTRY_EARN_BASE, ENTRY_EARN_BONUS])
    assert_ledger_entry(
        entries[0],
        entry_type=ENTRY_EARN_BASE,
        points_delta=276,
        balance_after=276,
        source_entity_id=purchase["id"],
    )
    assert_ledger_entry(
        entries[1],
        entry_type=ENTRY_EARN_BONUS,
        points_delta=230,
        balance_after=506,
        source_entity_id=purchase["id"],
    )
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=506,
        lifetime_points_earned=506,
    )


def _completed_block_transfer(api):
    """A 9,000-point transfer completed under a 3,000:2,000 ratio with a promotion."""
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code=GROCERY_MCC,
        display_name="Supermarkets",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    account, cardholder = fx.funded_account(api, 0)
    fx.fund_account(api, account["id"], 10000, mcc_code=GROCERY_MCC)
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Borealis Rewards",
        partner_program_code="BOREALIS",
        ratio_points_out=3000,
        ratio_partner_units_in=2000,
        min_transfer_points=1000,
        transfer_increment_points=1000,
        transfer_latency_hours=24,
    )
    event = fx.new_bonus_event(
        api,
        agreement["id"],
        ADMIN_HEADERS,
        event_code="BOREALIS-30",
        bonus_bps=3000,
        window_start="2026-08-05T00:00:00.000Z",
        window_end="2026-08-20T00:00:00.000Z",
        cap_points_per_account=6000,
    )
    fx.set_clock(api, "2026-08-10T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), bonus_events_opened=1)
    assert (
        validate_success(api.get_bonus_event(event["id"], ADMIN_HEADERS))["status"]
        == EVENT_RUNNING
    )

    transfer = fx.submit_transfer(
        api, account["id"], agreement["id"], 9000, cardholder
    )
    assert transfer["bonus_event_id"] == event["id"]
    queued = fx.clear_screening(api, transfer["id"], ANALYST_HEADERS)
    assert queued["scheduled_post_at"].startswith("2026-08-11T00:00:00")

    fx.set_clock(api, "2026-08-12T00:00:00.000Z")
    assert_sweep_counters(fx.ops_run(api), transfers_completed=1)
    return account, fx.read_transfer(api, transfer["id"])


def test_base_units_are_floored_per_thousand_point_block_then_summed(api):
    """
    "9,000 points at an applied ratio of 3,000 points to 2,000 units yields 666 units
    per block and therefore 5,994 `base_units`, where a single division would have
    yielded 6,000."

    Design: Difficulty/combinatorial_formula/combinatorial_transfer_units_floored_per_1000_point_block
    """
    _, transfer = _completed_block_transfer(api)

    assert transfer["status"] == TRANSFER_COMPLETED
    assert transfer["ratio_points_out_applied"] == 3000
    assert transfer["ratio_partner_units_in_applied"] == 2000
    assert transfer["base_units"] == 5994
    assert transfer["base_units"] != 6000


def test_bonus_units_ride_the_floored_per_block_figure_within_the_capped_blocks(api):
    """
    "the bonus units earned by one eligible block are the per-block base figure
    multiplied by the event's `bonus_bps` and divided by 10,000, floored; and
    `bonus_units` is that per-block bonus added once for each eligible block."

    Design: Difficulty/combinatorial_formula/combinatorial_transfer_units_floored_per_1000_point_block
    """
    account, transfer = _completed_block_transfer(api)

    assert transfer["bonus_units"] == 1194
    assert transfer["partner_units_credited"] == 7188
    assert_account_aggregates(
        fx.read_account(api, account["id"]),
        points_balance=1000,
        points_pending_redemption=0,
        lifetime_points_redeemed=9000,
    )


def _dormant_and_active_book(api):
    """One dormant account, one active account, and one settled portal booking."""
    fx.set_clock(api, "2024-01-01T00:00:00.000Z")
    dormant = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Dormant Dana",
        email="dormant@example.com",
        enrolled_at="2023-06-01T00:00:00.000Z",
    )
    fx.fund_account(
        api, dormant["id"], 400000, posted_at="2024-01-01T00:00:00.000Z"
    )

    fx.set_clock(api, "2026-07-01T00:00:00.000Z")
    active = fx.new_account(
        api,
        ADMIN_HEADERS,
        cardholder_name="Active Ana",
        email="active@example.com",
        enrolled_at="2026-01-15T00:00:00.000Z",
    )
    cardholder = fx.account_holder(active)
    fx.fund_account(
        api, active["id"], 800000, posted_at="2026-07-01T00:00:00.000Z"
    )

    _, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={"contracted_markup_bps": 2000, "parity_tolerance_bps": 1000},
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=4000,
    )

    fx.set_clock(api, "2026-07-10T00:00:00.000Z")
    order = fx.book(api, offer, active["id"], cardholder)
    assert order["points_debited"] == 44000
    fx.confirm(api, order["id"], cardholder)
    fx.ticket(api, order["id"], supplier)
    fx.settle(api, order["id"], 41000, settlement_adjustment_cents=-500)

    fx.set_clock(api, "2026-08-01T00:00:00.000Z")
    return dormant, active


def test_cost_basis_snapshot_pins_the_tier_on_gross_and_uplifts_the_dormant_bucket(api):
    """
    "**Step three** selects the breakage tier, keyed on step one's gross figure only
    — never on the net liability the tier itself helps produce ... The dormant bucket
    breaks at a higher rate: the base rate plus 1000 basis points, capped at 5000
    basis points."

    Design: Difficulty/combinatorial_formula/combinatorial_liability_tier_pinned_to_step_one_gross
    """
    _dormant_and_active_book(api)

    snapshot = fx.new_snapshot(
        api, "2026-08-01T00:00:00.000Z", ADMIN_HEADERS, method=METHOD_COST_BASIS
    )

    assert snapshot["gross_outstanding_points"] == 1156000
    assert snapshot["dormant_outstanding_points"] == 400000
    assert snapshot["blended_cost_per_1k_cents"] == 830
    assert snapshot["gross_liability_cents"] == 959480
    assert snapshot["breakage_credit_cents"] == 205906
    assert snapshot["net_liability_cents"] == 753574
    assert snapshot["effective_breakage_rate_bps"] == 2146


def test_fair_value_snapshot_reuses_the_same_tier_with_the_provisional_blended_cost(api):
    """
    "Under `FAIR_VALUE` the input set is the redemption orders whose
    `fulfillment_status` is `CONFIRMED`, `TICKETED`, or `REFUNDED` and whose
    `created_at` is at or before `as_of`; the blended cost is the sum of their
    `issuer_cost_provisional_cents` multiplied by 1,000, divided by the sum of their
    `points_debited`, rounded half up ..."

    Design: Difficulty/combinatorial_formula/combinatorial_liability_tier_pinned_to_step_one_gross
    """
    _dormant_and_active_book(api)

    snapshot = fx.new_snapshot(
        api, "2026-08-01T00:00:00.000Z", ADMIN_HEADERS, method=METHOD_FAIR_VALUE
    )

    assert snapshot["gross_outstanding_points"] == 1156000
    assert snapshot["dormant_outstanding_points"] == 400000
    assert snapshot["blended_cost_per_1k_cents"] == 818
    assert snapshot["gross_liability_cents"] == 945608
    assert snapshot["breakage_credit_cents"] == 202929
    assert snapshot["net_liability_cents"] == 742679
