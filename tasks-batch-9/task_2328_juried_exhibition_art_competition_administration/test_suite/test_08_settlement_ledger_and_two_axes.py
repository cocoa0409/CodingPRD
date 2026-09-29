"""Reconciliation arithmetic and the independence of the two exhibition axes."""

from test_helpers import (
    FINANCE_A,
    FINANCE_B,
    ApiErrorId,
    assert_same_instant,
    fixtures,
    validate_error,
)

TWO_SALEABLE_WORKS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
        "declared_value_cents": 400000, "for_sale": True,
        "list_price_cents": 250000,
    },
    {
        "title": "Salt Flat", "medium_category": "PHOTOGRAPHY",
        "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
        "declared_value_cents": 300000, "for_sale": True,
        "list_price_cents": 180000,
    },
]

INSURED_TOTAL_CENTS = 700000
PREMIUM_FLOOR_CENTS = 25000

SALE_PRICE_CENTS = 250000
TWO_SALES_GROSS = 500000
TWO_SALES_COMMISSION = 160920
TWO_SALES_TAX = 40230
TWO_SALES_PAYABLE = 298850
# 160,920 minus 25,000 recovered at the 0.75 rate.
RETENTION_AT_HIGH_RATE = 142170
# What the middle 0.50 rate would have produced instead.
RETENTION_AT_MID_RATE = 148420
# No commission at all: 0 minus 25,000 recovered at the 0.25 rate.
RETENTION_WITHOUT_SALES = -6250

CLAIM_DEADLINE_AT = "2027-01-12T00:00:00Z"


def _on_view_show():
    return fixtures.setup_on_view_show(
        works=TWO_SALEABLE_WORKS,
        artist_overrides={"member_status": "MEMBER"},
    )


# ─── The premium-recovery tier keyed on commission ────

def _reconciled_show_with_two_sales():
    ctx = _on_view_show()
    first, second = ctx["accepted_artwork_ids"]
    fixtures.setup_paid_sale(
        first, recorder=FINANCE_A, buyer_name="Collector One",
        sale_price_cents=SALE_PRICE_CENTS,
    )
    fixtures.setup_paid_sale(
        second, recorder=FINANCE_A, buyer_name="Collector Two",
        sale_price_cents=SALE_PRICE_CENTS,
    )
    reconciled = fixtures.advance_settlement(ctx["exhibition"]["id"], "RECONCILING")
    return ctx, reconciled


def test_premium_recovery_rate_is_keyed_on_the_commission_total(api):
    """PRD §3.10: "Step four selects a premium-recovery rate **keyed on the
    commission total from step two, never on the retention figure being
    computed**: the rate is 0.75 when `commission_total_cents` is at least 150,000
    cents, otherwise 0.50 when it is at least 50,000 cents, otherwise 0.25."

    Design: Difficulty/combinatorial_formula/settlement_retention_recovery_tier_keyed_on_commission
    """
    _, reconciled = _reconciled_show_with_two_sales()

    assert reconciled["settlement_status"] == "RECONCILING"
    assert reconciled["commission_total_cents"] == TWO_SALES_COMMISSION
    assert reconciled["insurance_premium_cents"] == PREMIUM_FLOOR_CENTS
    assert reconciled["council_retention_cents"] == RETENTION_AT_HIGH_RATE
    assert reconciled["council_retention_cents"] != RETENTION_AT_MID_RATE, (
        "keying the tier on the retention figure instead of the commission total "
        "would select the 0.50 rate"
    )


def test_reconciliation_recomputes_every_money_aggregate(api):
    """PRD §3.10: "Step five sets `council_retention_cents` to
    `commission_total_cents` minus the premium multiplied by that recovery rate,
    with only that recovered-premium product rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/settlement_retention_recovery_tier_keyed_on_commission
    """
    ctx, reconciled = _reconciled_show_with_two_sales()

    assert reconciled["sales_gross_cents"] == TWO_SALES_GROSS
    assert reconciled["sales_tax_total_cents"] == TWO_SALES_TAX
    assert reconciled["artist_payable_total_cents"] == TWO_SALES_PAYABLE
    assert reconciled["insured_value_total_cents"] == INSURED_TOTAL_CENTS

    read_back = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert read_back["council_retention_cents"] == RETENTION_AT_HIGH_RATE


# ─── The two axes advance independently ───────────────

def test_settlement_axis_advances_while_the_show_is_still_on_view(api):
    """PRD §3.10: "Reconciliation may begin only once the show is `ON_VIEW` or
    `CLOSED`, else `ERR_EXHIBITION_PHASE_INVALID`, and it recomputes
    `sales_gross_cents`, `commission_total_cents`, `sales_tax_total_cents`,
    `artist_payable_total_cents` and `council_retention_cents`."

    Design: Difficulty/non_linear_state_machine/exhibition_status_and_settlement_axes_advance_independently
    """
    ctx = _on_view_show()

    reconciled = fixtures.advance_settlement(ctx["exhibition"]["id"], "RECONCILING")

    assert reconciled["status"] == "ON_VIEW"
    assert reconciled["settlement_status"] == "RECONCILING"
    assert reconciled["insured_value_total_cents"] == INSURED_TOTAL_CENTS
    assert reconciled["insurance_premium_cents"] == PREMIUM_FLOOR_CENTS
    assert reconciled["commission_total_cents"] == 0
    assert reconciled["council_retention_cents"] == RETENTION_WITHOUT_SALES, (
        "council_retention_cents may legitimately be negative"
    )


def test_closing_the_show_leaves_the_settlement_axis_untouched(api):
    """PRD §3.1: "The two axes then advance independently of one another, and the
    `status` axis is driven by the `CallManager` naming a `target_status`."

    Design: Difficulty/non_linear_state_machine/exhibition_status_and_settlement_axes_advance_independently
    """
    ctx = _on_view_show()
    fixtures.advance_settlement(ctx["exhibition"]["id"], "RECONCILING")

    closed = fixtures.close_show(ctx["exhibition"]["id"])
    assert closed["status"] == "CLOSED"
    assert closed["settlement_status"] == "RECONCILING"
    assert closed["insured_value_total_cents"] == 0
    assert closed["insurance_premium_cents"] == 0

    first_id = ctx["accepted_artwork_ids"][0]
    returned = fixtures.read_artwork(first_id)
    assert returned["status"] == "RETURN_PENDING"
    assert returned["placement_status"] == "DEINSTALLED"
    assert_same_instant(returned["claim_deadline_at"], CLAIM_DEADLINE_AT)

    wall = fixtures.read_wall(ctx["wall"]["id"])
    assert wall["occupied_cm"] == 0.0
    assert wall["available_cm"] == 600.0
    assert wall["loaded_weight_kg"] == 0.0


def test_settlement_may_not_skip_a_rung_to_books_closed(api):
    """PRD §3.10: "Settlement is the exhibition's second, independent axis, driven
    by a `FinanceOfficer` naming a `target_settlement_status`, and it advances
    `NOT_STARTED → RECONCILING → PAYOUTS_RELEASED → BOOKS_CLOSED`."

    Design: Difficulty/non_linear_state_machine/exhibition_status_and_settlement_axes_advance_independently
    """
    ctx = _on_view_show()
    fixtures.advance_settlement(ctx["exhibition"]["id"], "RECONCILING")
    fixtures.close_show(ctx["exhibition"]["id"])

    response = api.advance_settlement(
        ctx["exhibition"]["id"], {"target_settlement_status": "BOOKS_CLOSED"},
        FINANCE_B,
    )
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_PHASE_INVALID.value)

    after = fixtures.read_exhibition(ctx["exhibition"]["id"])
    assert after["settlement_status"] == "RECONCILING"
    assert after["status"] == "CLOSED"
