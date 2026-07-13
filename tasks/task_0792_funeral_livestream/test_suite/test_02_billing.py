"""Service billing: the estimated vs final variants, the tiered/combinatorial
formula, and the included-minutes overage boundary.

All queue-A difficulty instances under dual_variant_calc, combinatorial_formula
(billing side), and boundary_precision_check (duration side).
"""
from test_helpers import (
    TEST_USERS,
    setup_scheduled_order, setup_invoiced_order, run_broadcast, transition_order,
)

ADMIN = TEST_USERS["admin_headers"]


# --- dual_variant_calc: estimated (scheduled) vs final (actual) --------------
def test_estimated_cost_computed_from_scheduled_duration(api):
    """PRD §3.6: "for the forward estimate it is the scheduled window from
    `scheduled_start` to `scheduled_end` in seconds divided by sixty and
    rounded up to a whole minute".
    PRD §3.6: "To this the system adds a base fee of 15,000 cents plus 5,000
    cents for each camera in `camera_count`".

    Design: Difficulty/dual_variant_calc/service_cost_estimated_vs_final_diverges
    """
    base = setup_scheduled_order(
        initial_credits=1, camera_count=2, priority_support=False,
        scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T12:00:00Z",
    )
    # 120 scheduled minutes => zero overage; 15000 + 5000*2 = 25000.
    assert base["order"]["estimated_cost_cents"] == 25000


def test_final_invoice_from_actual_duration_diverges_from_estimate(api):
    """PRD §3.6: "The estimate is computed at scheduling and stored in
    `estimated_cost_cents`; the final figure is computed at invoicing and stored
    in `final_invoice_cents`, and it diverges from the estimate whenever the
    broadcast ran longer or shorter than planned."

    Design: Difficulty/dual_variant_calc/service_cost_estimated_vs_final_diverges
    """
    base = setup_scheduled_order(
        initial_credits=1, camera_count=2, priority_support=False,
        scheduled_start="2026-06-01T10:00:00Z", scheduled_end="2026-06-01T12:00:00Z",
    )
    run_broadcast(base["order"]["id"], "2026-06-01T10:05:00Z", "2026-06-01T12:35:00Z")
    order = transition_order(base["order"]["id"], "INVOICE")
    # Actual 150 minutes => 30 overage @100 = 3000; 15000 + 10000 + 3000 = 28000.
    assert order["final_invoice_cents"] == 28000
    assert order["estimated_cost_cents"] == 25000
    assert order["final_invoice_cents"] != order["estimated_cost_cents"]


# --- combinatorial_formula: two-tier overage + priority surcharge ------------
def test_recording_duration_from_actual_clock_instants(api):
    """PRD §3.6: "once both instants exist, it is the elapsed time from
    `actual_start` to `actual_end` in seconds, divided by sixty and rounded up
    to the next whole minute."

    Design: Difficulty/combinatorial_formula/final_invoice_tiered_overage_with_priority_surcharge
    """
    base = setup_invoiced_order(
        initial_credits=1, camera_count=2, priority_support=True,
        scheduled_start="2026-06-03T10:00:00Z", scheduled_end="2026-06-03T13:15:00Z",
        go_live_at="2026-06-03T10:00:00Z", end_at="2026-06-03T13:15:00Z",
    )
    assert base["order"]["recording_duration_minutes"] == 195


def test_final_invoice_two_tier_overage_with_priority_surcharge(api):
    """PRD §3.6: "The first 60 overage minutes are billed at 100 cents per
    minute; every overage minute beyond that first 60 is billed at 150 cents
    per minute. To this the system adds a base fee of 15,000 cents plus 5,000
    cents for each camera in `camera_count`, and, when `priority_support` is
    true, a flat priority-support surcharge of 10,000 cents (omitted when it
    is false)."

    Design: Difficulty/combinatorial_formula/final_invoice_tiered_overage_with_priority_surcharge
    """
    base = setup_invoiced_order(
        initial_credits=1, camera_count=2, priority_support=True,
        scheduled_start="2026-06-03T10:00:00Z", scheduled_end="2026-06-03T13:15:00Z",
        go_live_at="2026-06-03T10:00:00Z", end_at="2026-06-03T13:15:00Z",
    )
    # 195 min => overage 75 => tier1 60*100=6000, tier2 15*150=2250.
    # 15000 + 5000*2 + 6000 + 2250 + 10000 = 43250.
    assert base["order"]["final_invoice_cents"] == 43250


# --- boundary_precision_check: exactly INCLUDED_MINUTES, no overage ----------
def test_invoice_exactly_included_minutes_has_no_overage(api):
    """PRD §3.6: "The included allowance is 120 minutes (two hours): the overage
    is the duration minus 120, floored at zero, so a duration of exactly 120
    minutes yields no overage and billable overage begins only at 121 minutes."

    Design: Difficulty/boundary_precision_check/invoice_no_overage_at_exactly_included_minutes
    """
    base = setup_invoiced_order(
        initial_credits=1, camera_count=2, priority_support=False,
        scheduled_start="2026-06-11T10:00:00Z", scheduled_end="2026-06-11T12:00:00Z",
        go_live_at="2026-06-11T10:00:00Z", end_at="2026-06-11T12:00:00Z",
    )
    # Exactly 120 actual minutes => no overage => 15000 + 5000*2 = 25000.
    assert base["order"]["final_invoice_cents"] == 25000


def test_recording_duration_exactly_120_minutes(api):
    """PRD §3.6: "for the final invoice it is `recording_duration_minutes`, the
    actual aired duration."

    Design: Difficulty/boundary_precision_check/invoice_no_overage_at_exactly_included_minutes
    """
    base = setup_invoiced_order(
        initial_credits=1, camera_count=2, priority_support=False,
        scheduled_start="2026-06-11T10:00:00Z", scheduled_end="2026-06-11T12:00:00Z",
        go_live_at="2026-06-11T10:00:00Z", end_at="2026-06-11T12:00:00Z",
    )
    assert base["order"]["recording_duration_minutes"] == 120
