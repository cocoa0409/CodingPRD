"""Wash-sale detection: cross-account sweep, window boundaries, deferral
cascade onto replacement lots, and loss-conservation invariants.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_paginated, TEST_USERS,
    setup_wash_sale_scenario, settle,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]


def _settle_and_fetch(s):
    settled = settle(s["firm"]["id"], s["disposition"]["id"])
    lot2 = validate_success(api_client.get_tax_lot(s["firm"]["id"], s["lot2"]["id"], TAX_OPS))
    return settled, lot2


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc /
# wash_sale_preview_same_account_vs_settled_cross_account
# ---------------------------------------------------------------------------

def test_preview_wash_sale_scans_own_account_only(api):
    """PRD §3.3: "The wash-sale preview is a deliberately narrower triage
    signal: it scans only the disposition's own account for replacement lots
    and answers with `would_trigger` plus the `candidate_lot_ids`, whereas
    settlement-time detection sweeps every account sharing the customer's
    `wash_sale_scope_key`."

    Design: Difficulty/dual_variant_calc/wash_sale_preview_same_account_vs_settled_cross_account
    """
    s = setup_wash_sale_scenario(tin="TIN-WS-1", cusip="123456789")
    preview = validate_success(api.preview_wash_sale(s["firm"]["id"], s["disposition"]["id"], TAX_OPS))
    assert preview["would_trigger"] is False, (
        "same-account-only preview must find no replacement inside the selling account A1"
    )


def test_settled_wash_sale_sweeps_across_accounts(api):
    """PRD §3.4: "The sweep spans the taxpayer's entire relationship with the
    firm: candidate replacement lots are every lot whose account belongs to a
    customer with the same `wash_sale_scope_key`."
    PRD §3.4: "The deferred loss is then tacked onto the triggering lot: the
    disallowed amount is added to both its `wash_sale_taint_basis_cents` and
    its `adjusted_cost_basis_cents`."

    Design: Difficulty/dual_variant_calc/wash_sale_preview_same_account_vs_settled_cross_account
    """
    s = setup_wash_sale_scenario(tin="TIN-WS-1", cusip="123456789")
    settled, lot2 = _settle_and_fetch(s)
    assert settled["is_wash_sale_flag"] is True
    assert settled["wash_sale_disallowed_loss_cents"] == 100000
    assert settled["realized_gain_cents"] == 0, "raw -100000 + disallowed 100000"
    assert lot2["wash_sale_taint_basis_cents"] == 100000
    assert lot2["adjusted_cost_basis_cents"] == 510000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / wash_sale_partial_prorata_multi_input
# ---------------------------------------------------------------------------

def _partial_prorata_scenario(tin="TIN-PP-1", cusip="333333333"):
    return setup_wash_sale_scenario(repl_qty=60, repl_basis=246000, tin=tin, cusip=cusip)


def test_partial_prorata_event_rule_and_amount(api):
    """PRD §3.4: "When the candidate can cover every remaining loss share, the
    match is recorded with `matching_rule` `SHARE_FOR_SHARE`; otherwise it is
    `PARTIAL_PRORATA`. The candidate's disallowed share is the absolute value of
    the disposition's realized loss, multiplied by the replacement shares the
    candidate absorbs and divided by the total shares sold at a loss, rounded
    half up to the nearest whole cent."

    Design: Difficulty/combinatorial_formula/wash_sale_partial_prorata_multi_input
    """
    s = _partial_prorata_scenario()
    settled = settle(s["firm"]["id"], s["disposition"]["id"])
    events, _meta = validate_paginated(
        api.list_wash_sale_events(s["firm"]["id"], s["disposition"]["id"], TAX_OPS)
    )
    assert len(events) == 1
    assert events[0]["matching_rule"] == "PARTIAL_PRORATA", "60 replacement shares < 100 loss shares"
    assert events[0]["disallowed_loss_cents"] == 60000, "round_half_up(100000 * 60/100)"
    assert settled["wash_sale_disallowed_loss_cents"] == 60000


def test_partial_prorata_recognized_loss_and_taint(api):
    """PRD §3.4: "The recognized loss shrinks by the disallowed portion — the
    disallowed total is added back to `realized_gain_cents`, though never past
    zero: a wash sale cannot turn a loss into a gain."
    PRD §3.4: "The deferred loss is then tacked onto the triggering lot: the
    disallowed amount is added to both its `wash_sale_taint_basis_cents` and
    its `adjusted_cost_basis_cents`."

    Design: Difficulty/combinatorial_formula/wash_sale_partial_prorata_multi_input
    """
    s = _partial_prorata_scenario()
    settled, lot2 = _settle_and_fetch(s)
    assert settled["realized_gain_cents"] == -40000, "raw -100000 + 60000 deferred"
    assert lot2["wash_sale_taint_basis_cents"] == 60000
    assert lot2["adjusted_cost_basis_cents"] == 306000, "246000 + 60000"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / wash_sale_evaluation_order_pinned
# ---------------------------------------------------------------------------

def test_disallowed_computed_from_raw_loss(api):
    """PRD §3.4: "Wash-sale review runs at settlement whenever the realized
    gain is negative" and "The candidate's disallowed share is the absolute
    value of the disposition's realized loss, multiplied by the replacement
    shares the candidate absorbs and divided by the total shares sold at a
    loss" — detection reads the raw realized loss before the recognized figure
    is adjusted.

    Design: Difficulty/combinatorial_formula/wash_sale_evaluation_order_pinned
    """
    s = setup_wash_sale_scenario(tin="TIN-EO-1", cusip="666666666")
    settled = settle(s["firm"]["id"], s["disposition"]["id"])
    assert settled["wash_sale_disallowed_loss_cents"] == 100000, (
        "computed from the raw -100000 loss, not from the post-adjustment 0"
    )
    assert settled["is_wash_sale_flag"] is True


def test_recognized_gain_adjusted_exactly_once(api):
    """PRD §3.4: "The recognized loss shrinks by the disallowed portion — the
    disallowed total is added back to `realized_gain_cents`, though never past
    zero: a wash sale cannot turn a loss into a gain."

    Design: Difficulty/combinatorial_formula/wash_sale_evaluation_order_pinned
    """
    s = setup_wash_sale_scenario(tin="TIN-EO-1", cusip="666666666")
    settled, lot2 = _settle_and_fetch(s)
    assert settled["realized_gain_cents"] == 0, "adjusted exactly once, after detection"
    assert lot2["adjusted_cost_basis_cents"] == 510000, "410000 + 100000 taint"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / settle_wash_sale_cascade_depth3
# ---------------------------------------------------------------------------

def test_settle_creates_event_naming_triggering_lot(api):
    """PRD §3.4: "For each match the system records a wash-sale event naming
    the `disposition_id`, the `sold_lot_id`, and the `triggering_lot_id`,
    carrying the `disallowed_loss_cents`, the `matching_rule`, and the computed
    `wash_sale_window_start` and `wash_sale_window_end` bounding the window."

    Design: Difficulty/transitive_cascade/settle_wash_sale_cascade_depth3
    """
    s = setup_wash_sale_scenario(tin="TIN-CASC-1", cusip="111111112")
    settle(s["firm"]["id"], s["disposition"]["id"])
    events, _meta = validate_paginated(
        api.list_wash_sale_events(s["firm"]["id"], s["disposition"]["id"], TAX_OPS)
    )
    assert len(events) == 1
    assert events[0]["triggering_lot_id"] == s["lot2"]["id"]
    assert events[0]["sold_lot_id"] == s["lot1"]["id"]
    assert events[0]["disallowed_loss_cents"] == 100000


def test_event_cascades_taint_basis_and_holding_period(api):
    """PRD §3.4: "The deferred loss is then tacked onto the triggering lot: the
    disallowed amount is added to both its `wash_sale_taint_basis_cents` and
    its `adjusted_cost_basis_cents`, and its `holding_period_start` is replaced
    by the earlier of its own and the sold lot's, so the replacement lot
    inherits the sold lot's holding period."

    Design: Difficulty/transitive_cascade/settle_wash_sale_cascade_depth3
    """
    s = setup_wash_sale_scenario(tin="TIN-CASC-1", cusip="111111112")
    settle(s["firm"]["id"], s["disposition"]["id"])
    lot2 = validate_success(api.get_tax_lot(s["firm"]["id"], s["lot2"]["id"], TAX_OPS))
    assert lot2["wash_sale_taint_basis_cents"] == 100000
    assert lot2["adjusted_cost_basis_cents"] == 510000
    assert lot2["holding_period_start"].startswith("2025-01-05"), (
        "sold lot's holding period tacks onto the replacement lot"
    )


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / wash_sale_window_inclusive_day30
# ---------------------------------------------------------------------------

def test_replacement_exactly_30_days_after_is_inside_window(api):
    """PRD §3.4: "The window reaches from thirty days before the `trade_date`
    through thirty days after it — both endpoints inclusive, so an acquisition
    exactly thirty days before or exactly thirty days after the sale falls
    inside the sixty-one-day window."

    Design: Difficulty/boundary_precision_check/wash_sale_window_inclusive_day30
    """
    s = setup_wash_sale_scenario(repl_date="2025-07-10T00:00:00Z", tin="TIN-BD-1", cusip="111111116")
    settled = settle(s["firm"]["id"], s["disposition"]["id"])
    assert settled["is_wash_sale_flag"] is True, "day +30 is inside the inclusive window"
    assert settled["wash_sale_disallowed_loss_cents"] == 100000


def test_day30_replacement_receives_full_taint(api):
    """PRD §3.4: "The deferred loss is then tacked onto the triggering lot: the
    disallowed amount is added to both its `wash_sale_taint_basis_cents` and
    its `adjusted_cost_basis_cents`."

    Design: Difficulty/boundary_precision_check/wash_sale_window_inclusive_day30
    """
    s = setup_wash_sale_scenario(repl_date="2025-07-10T00:00:00Z", tin="TIN-BD-1", cusip="111111116")
    settle(s["firm"]["id"], s["disposition"]["id"])
    lot2 = validate_success(api.get_tax_lot(s["firm"]["id"], s["lot2"]["id"], TAX_OPS))
    assert lot2["wash_sale_taint_basis_cents"] == 100000
    assert lot2["adjusted_cost_basis_cents"] == 510000


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap /
# wash_sale_window_symmetric_inclusive_interval (back edge)
# ---------------------------------------------------------------------------

def _back_edge_scenario():
    """Replacement lot acquired 2025-05-11 — exactly trade_date - 30 days."""
    s = setup_wash_sale_scenario(repl_date="2025-05-11T00:00:00Z", tin="TIN-OV-1", cusip="111111122")
    return s


def test_replacement_exactly_30_days_before_is_inside_window(api):
    """PRD §3.4: "both endpoints inclusive, so an acquisition exactly thirty
    days before or exactly thirty days after the sale falls inside the
    sixty-one-day window".

    Design: Difficulty/resource_temporal_overlap/wash_sale_window_symmetric_inclusive_interval
    """
    s = _back_edge_scenario()
    settled = settle(s["firm"]["id"], s["disposition"]["id"])
    assert settled["is_wash_sale_flag"] is True, "day -30 is inside the inclusive window"
    assert settled["wash_sale_disallowed_loss_cents"] == 100000


def test_back_edge_replacement_receives_taint(api):
    """PRD §3.4: "The deferred loss is then tacked onto the triggering lot: the
    disallowed amount is added to both its `wash_sale_taint_basis_cents` and
    its `adjusted_cost_basis_cents`."

    Design: Difficulty/resource_temporal_overlap/wash_sale_window_symmetric_inclusive_interval
    """
    s = _back_edge_scenario()
    settle(s["firm"]["id"], s["disposition"]["id"])
    lot2 = validate_success(api.get_tax_lot(s["firm"]["id"], s["lot2"]["id"], TAX_OPS))
    assert lot2["wash_sale_taint_basis_cents"] == 100000


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / wash_sale_deferral_conservation
# ---------------------------------------------------------------------------

def test_deferral_debit_equals_taint_credit(api):
    """PRD §3.4: "The disposition's `wash_sale_disallowed_loss_cents`, which
    begins at zero, totals the deferred amounts" and "The deferred loss is then
    tacked onto the triggering lot: the disallowed amount is added to both its
    `wash_sale_taint_basis_cents` and its `adjusted_cost_basis_cents`."

    Design: Difficulty/compensating_invariant/wash_sale_deferral_conservation
    """
    s = _partial_prorata_scenario(tin="TIN-INV-2", cusip="111111125")
    settled, lot2 = _settle_and_fetch(s)
    assert settled["wash_sale_disallowed_loss_cents"] == 60000, "debit side"
    assert lot2["wash_sale_taint_basis_cents"] == 60000, "credit side — equal and opposite"
    assert lot2["adjusted_cost_basis_cents"] - 246000 == 60000


def test_recognized_loss_reduced_by_exactly_deferred_amount(api):
    """PRD §3.4: "The recognized loss shrinks by the disallowed portion — the
    disallowed total is added back to `realized_gain_cents`, though never past
    zero: a wash sale cannot turn a loss into a gain."

    Design: Difficulty/compensating_invariant/wash_sale_deferral_conservation
    """
    s = _partial_prorata_scenario(tin="TIN-INV-2", cusip="111111125")
    settled, _lot2 = _settle_and_fetch(s)
    assert settled["realized_gain_cents"] == -40000, (
        "total economic loss -100000 = -40000 recognized - 60000 deferred, conserved"
    )


# ---------------------------------------------------------------------------
# Corner: calculations / gain exempt and day-31 outside
# ---------------------------------------------------------------------------

def test_wash_sale_skipped_when_gain_nonnegative(api):
    """PRD §3.4: "Wash-sale review runs at settlement whenever the realized
    gain is negative; a disposition that breaks even or gains is exempt."

    Design: Corner/calculations/wash_sale_skipped_when_gain_nonnegative
    """
    s = setup_wash_sale_scenario(loss_basis=400000, proceeds=450000, tin="TIN-CALC-15", cusip="444444445")
    settled, lot2 = _settle_and_fetch(s)
    assert settled["is_wash_sale_flag"] is False
    assert settled["wash_sale_disallowed_loss_cents"] == 0
    assert settled["realized_gain_cents"] == 50000
    assert lot2["wash_sale_taint_basis_cents"] == 0


def test_wash_sale_window_day31_outside(api):
    """PRD §3.4: "The window reaches from thirty days before the `trade_date`
    through thirty days after it — both endpoints inclusive, so an acquisition
    exactly thirty days before or exactly thirty days after the sale falls
    inside the sixty-one-day window." (Day +31 is therefore outside.)

    Design: Corner/calculations/wash_sale_window_day31_outside
    """
    s = setup_wash_sale_scenario(repl_date="2025-07-11T00:00:00Z", tin="TIN-CALC-16", cusip="454545454")
    settled, lot2 = _settle_and_fetch(s)
    assert settled["is_wash_sale_flag"] is False, "day +31 is outside the window"
    assert settled["realized_gain_cents"] == -100000, "full loss recognized"
    assert lot2["wash_sale_taint_basis_cents"] == 0
