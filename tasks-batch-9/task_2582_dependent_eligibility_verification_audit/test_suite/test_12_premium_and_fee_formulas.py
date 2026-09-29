"""The two pinned money formulas: continuation pricing and the demand arithmetic.

Both are specified as an order of operations rather than as a closed expression,
and in both the arithmetically tempting alternative order lands on a different
figure, so each test pins the order the specification names.
"""
from __future__ import annotations

from test_helpers.assertions import (
    assert_demand_pricing,
    assert_instant_equals,
    assert_pct,
    expected_continuation_premium,
    naive_continuation_premium,
)
from test_helpers.fixtures import (
    APPEAL_INSTANT,
    finalized_wave,
)

ELECTION_INSTANT = APPEAL_INSTANT


def test_electing_continuation_rounds_each_component_before_summing(b):
    """A spouse premium is 50708, one cent above the single-rounding alternative.

    PRD: "**The order of rounding is pinned and is not negotiable:** each of the
    three components is multiplied by the load factor of 1.02 and rounded half up
    to a whole cent *individually*, and only then are the three rounded results
    added together to give `continuation_monthly_premium_cents`."

    Design: Difficulty/combinatorial_formula/continuation_premium_rounds_each_component_before_summing
    """
    ctx = finalized_wave(b, relationships=("SPOUSE",))
    notice = b.notice_for(ctx.dep["id"])
    assert notice["continuation_election_status"] == "NOT_ELECTED"

    b.set_clock(ELECTION_INSTANT)
    elected = b.continuation_election(
        notice["id"], "ELECT", employee_id=ctx.employee["id"]
    )

    assert elected["continuation_monthly_premium_cents"] == 50708
    assert elected["continuation_monthly_premium_cents"] != 50707
    assert elected["continuation_monthly_premium_cents"] == (
        expected_continuation_premium("SPOUSE")
    )
    assert elected["continuation_monthly_premium_cents"] != (
        naive_continuation_premium("SPOUSE")
    )
    assert elected["continuation_election_status"] == "ELECTED"
    assert_instant_equals(elected["continuation_elected_at"], ELECTION_INSTANT)


def test_a_domestic_partner_premium_uses_the_same_three_component_schedule(b):
    """The domestic-partner class shares the spouse component costs exactly.

    PRD: "A `SPOUSE` and a `DOMESTIC_PARTNER` each carry a medical component of
    45,125 cents, a dental component of 3,313 cents, and a vision component of
    1,275 cents."

    Design: Difficulty/combinatorial_formula/continuation_premium_rounds_each_component_before_summing
    """
    ctx = finalized_wave(b, relationships=("DOMESTIC_PARTNER",))
    notice = b.notice_for(ctx.dep["id"])

    b.set_clock(ELECTION_INSTANT)
    elected = b.continuation_election(
        notice["id"], "ELECT", employee_id=ctx.employee["id"]
    )

    assert elected["continuation_monthly_premium_cents"] == 50708
    assert elected["continuation_monthly_premium_cents"] != 50707


def test_the_continuation_interval_starts_the_day_after_coverage_ends(b):
    """Coverage ends 2026-10-31, so continuation runs 2026-11-01 to 2028-05-01.

    PRD: "The notice's `continuation_start_date` is its `effective_date` advanced
    by one day and is the inclusive first day of the continuation interval."

    Design: Difficulty/combinatorial_formula/continuation_premium_rounds_each_component_before_summing
    """
    ctx = finalized_wave(b, relationships=("SPOUSE",))
    notice = b.notice_for(ctx.dep["id"])
    assert notice["effective_date"] == "2026-10-31"
    assert notice["continuation_start_date"] is None
    assert notice["continuation_end_date"] is None

    b.set_clock(ELECTION_INSTANT)
    elected = b.continuation_election(
        notice["id"], "ELECT", employee_id=ctx.employee["id"]
    )

    assert elected["continuation_start_date"] == "2026-11-01"
    assert elected["continuation_end_date"] == "2028-05-01"


# Two lines inside the strict window, deliberately one cent-tier short of the
# eight-percent floor.
MID_TIER_CLAIMS = (
    {"service_date": "2026-09-20", "paid_cents": 240000},
    {"service_date": "2026-09-25", "paid_cents": 250000},
)
HIGH_TIER_CLAIMS = (
    {"service_date": "2026-09-20", "paid_cents": 250000},
    {"service_date": "2026-09-25", "paid_cents": 250000},
)


def _open_recovery_over(b, claims):
    ctx = finalized_wave(b, claims=list(claims))
    ctx.notice = b.notice_for(ctx.dep["id"])
    ctx.recovery = b.open_recovery(
        ctx.dep["id"], ctx.notice["id"], "STRICT", "2026-09-01"
    )
    return ctx


def test_the_admin_fee_tier_is_keyed_on_the_subtotal_not_the_finished_demand(b):
    """A 490000 subtotal attracts five percent even though the demand clears 500000.

    PRD: "Step two selects the fee rate **from that subtotal**, never from any
    fee-inclusive figure: a subtotal below 100,000 cents attracts a rate of zero,
    a subtotal from 100,000 cents up to but not including 500,000 cents attracts
    five percent, and a subtotal of 500,000 cents or more attracts eight
    percent."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keys_on_subtotal_not_fee_inclusive_total
    """
    ctx = _open_recovery_over(b, MID_TIER_CLAIMS)
    assert ctx.recovery["recoverable_subtotal_cents"] == 490000

    issued = b.issue_demand(ctx.recovery["id"])

    assert_pct(issued["admin_fee_pct"], 0.05)
    assert issued["admin_fee_cents"] == 24500
    assert issued["net_demand_cents"] == 514500
    # Tiering on the fee-inclusive 514500 would have charged eight percent.
    assert issued["net_demand_cents"] != 529200
    assert issued["status"] == "DEMAND_ISSUED"
    assert b.read_program(ctx.program["id"])["recovery_ledger_cents"] == 514500


def test_the_single_rounding_step_precedes_the_waiver_credit_subtraction(b):
    """A goodwill credit reduces the demand without disturbing the fee.

    PRD: "Step four subtracts last: `net_demand_cents` is the subtotal plus
    `admin_fee_cents` minus `waiver_credit_cents`."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keys_on_subtotal_not_fee_inclusive_total
    """
    ctx = _open_recovery_over(b, MID_TIER_CLAIMS)

    issued = b.issue_demand(ctx.recovery["id"], waiver_credit_cents=10000)

    assert_demand_pricing(
        issued, subtotal_cents=490000, waiver_credit_cents=10000
    )
    assert issued["admin_fee_cents"] == 24500
    assert issued["net_demand_cents"] == 504500


def test_a_subtotal_exactly_at_the_high_tier_floor_attracts_eight_percent(b):
    """500000 is inside the top band, so the fee is 40000 and the demand 540000.

    PRD: "Step two selects the fee rate **from that subtotal**, never from any
    fee-inclusive figure: a subtotal below 100,000 cents attracts a rate of zero,
    a subtotal from 100,000 cents up to but not including 500,000 cents attracts
    five percent, and a subtotal of 500,000 cents or more attracts eight
    percent."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keys_on_subtotal_not_fee_inclusive_total
    """
    ctx = _open_recovery_over(b, HIGH_TIER_CLAIMS)
    assert ctx.recovery["recoverable_subtotal_cents"] == 500000

    issued = b.issue_demand(ctx.recovery["id"])

    assert_pct(issued["admin_fee_pct"], 0.08)
    assert issued["admin_fee_cents"] == 40000
    assert issued["net_demand_cents"] == 540000
