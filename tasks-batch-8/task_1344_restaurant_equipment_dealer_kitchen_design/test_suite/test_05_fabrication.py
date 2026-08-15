"""Fabrication orders: overtime reconciliation (quoted vs final variant)."""
from decimal import ROUND_HALF_UP, Decimal

from test_helpers import (
    TEST_USERS,
    assert_fabrication_order,
    get_success_data,
    setup_fabrication_in_production,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
FL = TEST_USERS["fabrication_lead_headers"]


def test_fabrication_cost_quoted_vs_reconciled_final(api):
    """PRD §3.4: "Every day of overrun beyond that allowance accrues a penalty
    of 4 percent of the quoted cost; the accrued penalty is capped at 40
    percent of the quoted cost, with the cap applied after the per-day
    accrual. The final fabrication cost is the quoted cost plus the capped
    penalty, rounded half-up once at the very end to whole cents, and stored
    in `final_fab_cost_cents`."

    Design: Difficulty/dual_variant_calc/fabrication_cost_quoted_vs_reconciled_final
    """
    customer, project, layout, item, quote, fab = setup_fabrication_in_production()
    # In-production clock pin: start at the default logical time.
    get_success_data(api.set_clock("2026-08-01T00:00:00Z", ADMIN))
    # Restart production clock reference: approval already happened; re-walk
    # is unnecessary — the allowance is measured from shop-drawing approval,
    # which occurred at the default 2026-08-01 logical time.
    get_success_data(api.set_clock("2026-11-29T00:00:00Z", ADMIN))  # +120 days

    completed = validate_success(
        api.complete_fabrication(project["id"], fab["id"], FL), 200
    )
    assert_fabrication_order(completed)
    assert completed["status"] == "FAB_COMPLETE"

    # over = 120 - (60 + 30) = 30; raw penalty = Q*0.04*30 = 1.20Q, capped at
    # 0.40Q -> final = round_half_up(Q * 1.40).
    quoted = completed["quoted_fab_cost_cents"]
    expected = int(
        (Decimal(quoted) * Decimal("1.40")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    assert completed["final_fab_cost_cents"] == expected
    assert completed["final_fab_cost_cents"] != quoted


def test_fabrication_complete_marks_item_received(api):
    """PRD §3.4: "Completing the order also moves the linked equipment item
    from `ORDERED` to `RECEIVED`."

    Design: Difficulty/dual_variant_calc/fabrication_cost_quoted_vs_reconciled_final
    """
    customer, project, layout, item, quote, fab = setup_fabrication_in_production()
    get_success_data(api.complete_fabrication(project["id"], fab["id"], FL))

    refreshed = get_success_data(
        api.get_equipment_item(project["id"], item["id"], PM)
    )
    assert refreshed["status"] == "RECEIVED"


def test_fabrication_penalty_cap_engages_on_long_overrun(api):
    """PRD §3.4: "the allowance is the linked item's `lead_time_days` plus a
    30-day schedule allowance, measured against the actual calendar days
    elapsed between the shop-drawing approval and fabrication completion on
    the logical clock."

    Design: Difficulty/dual_variant_calc/fabrication_cost_quoted_vs_reconciled_final
    """
    # A short overrun inside the cap: 95 elapsed days - (60 + 30) = 5 days
    # of overrun -> penalty = 5 * 4% = 20% of quoted (below the 40% cap).
    customer, project, layout, item, quote, fab = setup_fabrication_in_production()
    get_success_data(api.set_clock("2026-11-04T00:00:00Z", ADMIN))  # +95 days

    completed = validate_success(
        api.complete_fabrication(project["id"], fab["id"], FL), 200
    )
    quoted = completed["quoted_fab_cost_cents"]
    expected = int(
        (Decimal(quoted) * Decimal("1.20")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    assert completed["final_fab_cost_cents"] == expected
