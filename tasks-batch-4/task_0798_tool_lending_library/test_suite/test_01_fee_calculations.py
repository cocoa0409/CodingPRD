"""Late-fee and damage/replacement fee calculations.

Difficulty queue A: dual_variant_calc, combinatorial_formula, boundary_precision.
Corner queue B: rate_threshold_triggers.
"""
from test_helpers import (
    setup_overdue_loan, setup_checked_out_loan, set_clock, ops_run,
    return_loan, first_fee_for_loan, get_fee, checkout, add_copy, create_item,
    create_member, item_version, get_loan,
    create_loan_payload,
)
from test_helpers import api_client, TEST_USERS, validate_success

COORD = TEST_USERS["coordinator_headers"]


# =========================================================================== #
# Difficulty/dual_variant_calc/late_fee_accruing_vs_finalized_on_loan
# =========================================================================== #
def test_accruing_late_fee_grows_to_100_at_three_days_overdue(api):
    """The ACCRUING variant observed mid-overdue on the same loan.

    PRD §3.6: "While a loan is `OVERDUE` and not yet returned, its `LATE` fee
    stays in `ACCRUING` status and is recomputed on every housekeeping run
    against the current clock, so the amount grows as time passes."
    PRD §3.6: "Billable days are the days overdue reduced by a grace period of
    2 days, but never less than zero."

    A loan due 2026-03-08 observed at 2026-03-11 is 3 days overdue, 1 billable
    day, so daily_late_fee_cents(100) * 1 = 100.

    Design: Difficulty/dual_variant_calc/late_fee_accruing_vs_finalized_on_loan
    """
    _m, _i, _c, _loan, fee = setup_overdue_loan(
        clock_checkout="2026-03-01T00:00:00Z",
        clock_overdue="2026-03-11T00:00:00Z",
        item_overrides={"daily_late_fee_cents": 100, "replacement_value_cents": 12000,
                        "loan_period_days": 7})
    assert fee["amount_cents"] == 100, f"accruing fee should be 100, got {fee['amount_cents']}"
    assert fee["status"] == "ACCRUING"
    assert fee["fee_type"] == "LATE"


def test_finalized_late_fee_frozen_at_300_on_return(api):
    """The FINALIZED variant frozen at return on the same loan domain.

    PRD §3.6: "When the loan is returned or declared lost, the same computation
    is evaluated one last time — against `returned_at`, or the housekeeping
    instant for a loss — and the amount is frozen as the fee moves to `PENDING`."
    PRD §3.6: "The raw fee is the item's `daily_late_fee_cents` multiplied by the
    billable days."

    Returning at 2026-03-13 (5 days overdue, 3 billable) freezes 100 * 3 = 300.

    Design: Difficulty/dual_variant_calc/late_fee_accruing_vs_finalized_on_loan
    """
    _m, _i, _c, loan, fee = setup_overdue_loan(
        clock_checkout="2026-03-01T00:00:00Z",
        clock_overdue="2026-03-11T00:00:00Z",
        item_overrides={"daily_late_fee_cents": 100, "replacement_value_cents": 12000,
                        "loan_period_days": 7})
    set_clock("2026-03-13T00:00:00Z")
    returned = return_loan(loan["id"], "GOOD")
    frozen = get_fee(fee["id"])
    assert frozen["amount_cents"] == 300, f"finalized fee should be 300, got {frozen['amount_cents']}"
    assert frozen["status"] == "PENDING"
    assert returned["status"] == "RETURNED"


# =========================================================================== #
# Difficulty/dual_variant_calc/damage_repair_vs_replace_on_damage_fee
# =========================================================================== #
def _two_copy_item_checked_out(replacement_value_cents=12345, acquired_on="2024-03-01T00:00:00Z"):
    member = create_member()
    item = create_item(name="Saw", category="TOOL",
                       replacement_value_cents=replacement_value_cents,
                       loan_period_days=7, daily_late_fee_cents=100, max_renewals=2)
    copy1 = add_copy(item["id"], asset_tag="S-1", acquired_on=acquired_on)
    copy2 = add_copy(item["id"], asset_tag="S-2", acquired_on=acquired_on)
    set_clock("2026-03-13T00:00:00Z")
    loan1 = checkout(member["id"], copy1["id"], item["id"])
    loan2 = checkout(member["id"], copy2["id"], item["id"])
    return member, item, loan1, loan2


def test_minor_damage_billed_as_flat_repair_1500(api):
    """MINOR_DAMAGE return -> REPAIR DAMAGE fee capped at the flat repair charge.

    PRD §3.5: "A `MINOR_DAMAGE` return is billed as a repair: its `amount_cents`
    is the smaller of the flat repair charge of 1500 cents and the full
    replacement figure, and the resulting fee's `fee_type` is `DAMAGE`."

    Design: Difficulty/dual_variant_calc/damage_repair_vs_replace_on_damage_fee
    """
    _m, _i, loan1, _loan2 = _two_copy_item_checked_out()
    return_loan(loan1["id"], "MINOR_DAMAGE")
    fee = first_fee_for_loan(loan1["id"])
    assert fee["amount_cents"] == 1500, f"repair should be 1500, got {fee['amount_cents']}"
    assert fee["fee_type"] == "DAMAGE"


def test_major_damage_billed_at_full_replacement_9875(api):
    """MAJOR_DAMAGE return -> REPLACE REPLACEMENT fee at the full replacement figure.

    PRD §3.5: "A `MAJOR_DAMAGE` return, a `LOST` return, and a housekeeping loss
    declaration are all billed at the full replacement figure itself, and the
    resulting fee's `fee_type` is `REPLACEMENT`."
    PRD §3.5: "The depreciated value is then the `replacement_value_cents` minus
    that rounded per-year depreciation multiplied by the age in years — the
    rounding of the per-year amount happens first, then the multiplication by
    age, then the subtraction, in that pinned order."

    replacement 12345, age 2y: round(12345*0.10)=1235; 12345-1235*2=9875.

    Design: Difficulty/dual_variant_calc/damage_repair_vs_replace_on_damage_fee
    """
    _m, _i, _loan1, loan2 = _two_copy_item_checked_out()
    return_loan(loan2["id"], "MAJOR_DAMAGE")
    fee = first_fee_for_loan(loan2["id"])
    assert fee["amount_cents"] == 9875, f"replacement should be 9875, got {fee['amount_cents']}"
    assert fee["fee_type"] == "REPLACEMENT"


# =========================================================================== #
# Difficulty/combinatorial_formula/late_fee_min_cap_binds_mode_a
# =========================================================================== #
def test_late_fee_capped_at_replacement_value_when_raw_exceeds(api):
    """Nested max/min: the replacement-value cap binds so raw 1700 becomes 250.

    PRD §3.6: "The final `amount_cents` is capped at the item's
    `replacement_value_cents` — that is, the smaller of the raw fee and the
    replacement value — so a late fee can never exceed the cost of simply
    replacing the item."

    daily 100, 19 days overdue -> 17 billable -> raw 1700; cap 250 binds.

    Design: Difficulty/combinatorial_formula/late_fee_min_cap_binds_mode_a
    """
    _m, _i, _c, loan, _fee = setup_overdue_loan(
        clock_checkout="2026-03-01T00:00:00Z",
        clock_overdue="2026-03-27T00:00:00Z",
        item_overrides={"name": "Trowel", "category": "OUTDOOR",
                        "replacement_value_cents": 250, "daily_late_fee_cents": 100,
                        "loan_period_days": 7})
    return_loan(loan["id"], "GOOD")
    fee = first_fee_for_loan(loan["id"])
    assert fee["amount_cents"] == 250, f"cap should bind at 250, got {fee['amount_cents']}"


def test_late_fee_capped_charge_is_typed_late(api):
    """The capped charge is still a LATE fee (fee_type discrimination).

    PRD §3.6: "A fee's `fee_type` for this charge is `LATE`, and its `status` is
    one of `ACCRUING`, `PENDING`, `PAID`, or `WAIVED`; `LATE` fees begin
    `ACCRUING` while damage and replacement fees are created directly in
    `PENDING`."

    Design: Difficulty/combinatorial_formula/late_fee_min_cap_binds_mode_a
    """
    _m, _i, _c, loan, _fee = setup_overdue_loan(
        clock_checkout="2026-03-01T00:00:00Z",
        clock_overdue="2026-03-27T00:00:00Z",
        item_overrides={"name": "Trowel", "category": "OUTDOOR",
                        "replacement_value_cents": 250, "daily_late_fee_cents": 100,
                        "loan_period_days": 7})
    return_loan(loan["id"], "GOOD")
    fee = first_fee_for_loan(loan["id"])
    assert fee["fee_type"] == "LATE"
    assert fee["status"] == "PENDING"


# =========================================================================== #
# Difficulty/combinatorial_formula/damage_nested_rounding_order_mode_b
# =========================================================================== #
def test_replacement_charge_uses_pinned_rounding_order_9875(api):
    """Pinned rounding order yields 9875 (unpinned would give 9876).

    PRD §3.5: "The per-year depreciation is the item's `replacement_value_cents`
    multiplied by the annual depreciation rate of 10 percent, rounded half up to
    whole cents."
    PRD §3.5: "The depreciated value is then the `replacement_value_cents` minus
    that rounded per-year depreciation multiplied by the age in years — the
    rounding of the per-year amount happens first, then the multiplication by
    age, then the subtraction, in that pinned order."

    Design: Difficulty/combinatorial_formula/damage_nested_rounding_order_mode_b
    """
    member = create_member()
    item = create_item(name="Ladder", category="TOOL", replacement_value_cents=12345,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="L-1", acquired_on="2024-03-01T00:00:00Z")
    set_clock("2026-03-13T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    return_loan(loan["id"], "MAJOR_DAMAGE")
    fee = first_fee_for_loan(loan["id"])
    assert fee["amount_cents"] == 9875, f"pinned-order replacement should be 9875, got {fee['amount_cents']}"


def test_replacement_charge_fee_type_is_replacement(api):
    """The full-replacement charge carries fee_type REPLACEMENT.

    PRD §3.5: "A `MAJOR_DAMAGE` return, a `LOST` return, and a housekeeping loss
    declaration are all billed at the full replacement figure itself, and the
    resulting fee's `fee_type` is `REPLACEMENT`."

    Design: Difficulty/combinatorial_formula/damage_nested_rounding_order_mode_b
    """
    member = create_member()
    item = create_item(name="Ladder", category="TOOL", replacement_value_cents=12345,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="L-1", acquired_on="2024-03-01T00:00:00Z")
    set_clock("2026-03-13T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    return_loan(loan["id"], "MAJOR_DAMAGE")
    fee = first_fee_for_loan(loan["id"])
    assert fee["fee_type"] == "REPLACEMENT"
    assert fee["status"] == "PENDING"


# =========================================================================== #
# Difficulty/boundary_precision_check/late_fee_grace_exact_boundary_no_fee
# =========================================================================== #
def test_late_fee_zero_at_exact_grace_boundary(api):
    """At exactly days_overdue == GRACE_DAYS (2), billable days = 0 so fee = 0.

    PRD §3.6: "Billable days are the days overdue reduced by a grace period of 2
    days, but never less than zero. The raw fee is the item's
    `daily_late_fee_cents` multiplied by the billable days."

    due 2026-03-08, returned 2026-03-10 -> 2 days overdue -> 0 billable -> 0.

    Design: Difficulty/boundary_precision_check/late_fee_grace_exact_boundary_no_fee
    """
    _m, _i, _c, loan, fee = setup_overdue_loan(
        clock_checkout="2026-03-01T00:00:00Z",
        clock_overdue="2026-03-10T00:00:00Z",
        item_overrides={"name": "Drill2", "category": "TOOL",
                        "replacement_value_cents": 12000, "daily_late_fee_cents": 100,
                        "loan_period_days": 7})
    return_loan(loan["id"], "GOOD")
    frozen = get_fee(fee["id"])
    assert frozen["amount_cents"] == 0, f"grace-boundary fee should be 0, got {frozen['amount_cents']}"


def test_late_fee_grace_boundary_finalizes_pending(api):
    """The zero-amount late fee is still finalized to PENDING on return.

    PRD §3.6: "When the loan is returned or declared lost, the same computation
    is evaluated one last time — against `returned_at`, or the housekeeping
    instant for a loss — and the amount is frozen as the fee moves to `PENDING`."

    Design: Difficulty/boundary_precision_check/late_fee_grace_exact_boundary_no_fee
    """
    _m, _i, _c, loan, fee = setup_overdue_loan(
        clock_checkout="2026-03-01T00:00:00Z",
        clock_overdue="2026-03-10T00:00:00Z",
        item_overrides={"name": "Drill2", "category": "TOOL",
                        "replacement_value_cents": 12000, "daily_late_fee_cents": 100,
                        "loan_period_days": 7})
    return_loan(loan["id"], "GOOD")
    frozen = get_fee(fee["id"])
    assert frozen["status"] == "PENDING"


# =========================================================================== #
# Corner/cross_cutting_complexity_layers/rate_threshold_late_fee_first_billable_day
# =========================================================================== #
def test_first_billable_day_yields_one_day_late_fee(api):
    """At days_overdue == GRACE_DAYS + 1 (3) the first billable day yields one
    day of late fee = 100.

    PRD §3.6: "The raw fee is the item's `daily_late_fee_cents` multiplied by the
    billable days."
    PRD §3.6: "Billable days are the days overdue reduced by a grace period of 2
    days, but never less than zero."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_late_fee_first_billable_day
    """
    _m, _i, _c, loan, fee = setup_overdue_loan(
        clock_checkout="2026-03-01T00:00:00Z",
        clock_overdue="2026-03-11T00:00:00Z",
        item_overrides={"name": "Drill3", "category": "TOOL",
                        "replacement_value_cents": 12000, "daily_late_fee_cents": 100,
                        "loan_period_days": 7})
    return_loan(loan["id"], "GOOD")
    frozen = get_fee(fee["id"])
    assert frozen["amount_cents"] == 100, f"first billable day should be 100, got {frozen['amount_cents']}"
    assert frozen["status"] == "PENDING"
