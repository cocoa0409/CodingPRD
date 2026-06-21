"""Wash-sale disallowance, the depth-3 harvest cascade, the inclusive 30-day
window boundary, and the compensating-undo reversal invariants.

Queue A: combinatorial_formula/wash_sale_proration_min_and_basis_carryover,
transitive_cascade/harvest_close_to_washscan_to_ytd_ledger_depth3,
resource_temporal_overlap/wash_sale_window_inclusive_30day_boundary,
compensating_invariant/harvest_reverse_restores_total_value_cents,
compensating_invariant/harvest_reverse_restores_realized_gain_ytd.
"""
from test_helpers import (
    get_success_data,
    TEST_USERS,
    set_clock,
    create_model,
    create_security,
    create_active_account,
    open_tax_lot,
    get_account,
    get_tax_lot,
    propose_harvest,
    setup_active_account_with_washsale_loss_lot,
    setup_executed_harvest,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def _execute_washsale_harvest(api, clock_iso, email, **overrides):
    """Wash-sale scenario (2sh in-window lot + 5sh/60000 source in A, uncorrelated
    replacement B), harvest proposed then executed. Returns the scenario dict with
    the executed harvest under "harvest"."""
    s = setup_active_account_with_washsale_loss_lot(clock_iso, email, **overrides)
    harvest = propose_harvest(
        s["account"]["id"], s["source_lot"]["id"], s["repl_sec"]["id"], s["acct_version"]
    )
    s["harvest"] = get_success_data(api.execute_harvest_event(harvest["id"], ADVISOR))
    return s


# ─── wash_sale_proration_min_and_basis_carryover ────────────────────
def test_wash_sale_disallowed_amount_is_prorated_min(api):
    """PRD §3.5: "The disallowed amount is the smaller of the absolute realized
    loss and the value obtained by taking the in-window replacement shares
    divided by the closing lot's shares, multiplying by the absolute realized
    loss, and rounding half up to whole cents".

    Design: Difficulty/combinatorial_formula/wash_sale_proration_min_and_basis_carryover
    """
    s = _execute_washsale_harvest(api, "2026-04-01T00:00:00.000Z", "wash@x.com")
    # min(abs(-10000), round_half_up((2/5)*10000)) = min(10000, 4000) = 4000.
    closed = get_tax_lot(s["source_lot"]["id"])
    assert closed["wash_sale_disallowed_cents"] == 4000
    assert s["harvest"]["disallowed_loss_cents"] == 4000
    assert s["harvest"]["realized_loss_cents"] == 10000


def test_wash_sale_basis_carryover_onto_in_window_lot(api):
    """PRD §3.5: "the in-window replacement lot's `cost_basis_cents` is increased by that same amount as a basis carryover".

    Design: Difficulty/combinatorial_formula/wash_sale_proration_min_and_basis_carryover
    """
    s = _execute_washsale_harvest(api, "2026-04-02T00:00:00.000Z", "wash2@x.com")
    in_window = get_tax_lot(s["in_window_lot"]["id"])
    # Original basis 24000 + 4000 disallowed = 28000.
    assert in_window["cost_basis_cents"] == 28000


# ─── harvest_close_to_washscan_to_ytd_ledger_depth3 ─────────────────
def test_cascade_l1_source_lot_closed_with_realized_loss(api):
    """PRD §3.4: "First, the source lot is closed: its `disposed_at` is stamped with the current clock instant, its `proceeds_cents` is set to the lot's market value at the moment of sale, its `realized_gain_cents` is computed as proceeds minus cost basis (a negative number for a loss)".

    Design: Difficulty/transitive_cascade/harvest_close_to_washscan_to_ytd_ledger_depth3
    """
    s = _execute_washsale_harvest(
        api, "2026-06-01T00:00:00.000Z", "casc@x.com", src_ticker="EEE", repl_ticker="FFF"
    )
    closed = get_tax_lot(s["source_lot"]["id"])
    assert closed["status"] == "CLOSED"
    # proceeds 50000 - basis 60000 = -10000.
    assert closed["realized_gain_cents"] == -10000


def test_cascade_l3_ytd_ledgers_updated_with_disallowance(api):
    """PRD §3.4: "Third, the wash-sale recompute updates the account's `wash_sale_disallowed_cents_ytd` and its `realized_gain_cents_ytd` (the loss net of any disallowance)." PRD §3.5: "the net realized loss recognized in the
    current year is the realized loss plus the disallowed amount — since the loss
    is negative, adding the positive disallowance moves the recognized loss back
    toward zero."

    Design: Difficulty/transitive_cascade/harvest_close_to_washscan_to_ytd_ledger_depth3
    """
    s = _execute_washsale_harvest(
        api, "2026-06-02T00:00:00.000Z", "casc2@x.com", src_ticker="EE2", repl_ticker="FF2"
    )
    acct = get_account(s["account"]["id"])
    # L2 disallowance 4000 -> L3 ytd: wash 4000, realized -10000 + 4000 add-back = -6000.
    assert acct["wash_sale_disallowed_cents_ytd"] == 4000
    assert acct["realized_gain_cents_ytd"] == -6000


# ─── wash_sale_window_inclusive_30day_boundary ──────────────────────
def _setup_30day_boundary_harvest(api, email, src_ticker, repl_ticker):
    """In-window 5sh/50000 purchase of A on 2026-03-31, source 5sh/60000 in A
    disposed 2026-04-30 — exactly 30 days apart, inside the inclusive window."""
    set_clock("2026-03-31T00:00:00.000Z")
    model = create_model(
        name=f"BW-{email}", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}]
    )
    a = create_security(
        src_ticker, "US_EQUITY", 10000, correlated_with=[{"ticker": repl_ticker, "correlation": 0.05}]
    )
    b = create_security(
        repl_ticker, "US_EQUITY", 4000, correlated_with=[{"ticker": src_ticker, "correlation": 0.05}]
    )
    acct = create_active_account(email, model_id=model["id"])
    in_window = open_tax_lot(acct["id"], a["id"], 5, 50000)
    set_clock("2026-04-30T00:00:00.000Z")
    source = open_tax_lot(acct["id"], a["id"], 5, 60000)
    acct_v = get_account(acct["id"])["version"]
    harvest = propose_harvest(acct["id"], source["id"], b["id"], acct_v)
    executed = get_success_data(api.execute_harvest_event(harvest["id"], ADVISOR))
    return source, executed


def test_wash_sale_window_inclusive_at_exactly_30_days(api):
    """PRD §3.5: "The window spans from the disposal instant minus the wash-sale
    day count to the disposal instant plus the wash-sale day count, inclusive of
    both ends, where the wash-sale day count is 30 days."

    Design: Difficulty/resource_temporal_overlap/wash_sale_window_inclusive_30day_boundary
    """
    source, _ = _setup_30day_boundary_harvest(api, "tov1@x.com", "MMM", "NNN")
    closed = get_tax_lot(source["id"])
    # In-window 5 shares / 5 closing shares * 10000 loss = 10000; full disallowance.
    assert closed["wash_sale_disallowed_cents"] == 10000


def test_wash_sale_window_inclusive_harvest_disallowed_loss(api):
    """PRD §3.5: "A triggering replacement purchase is any other `OPEN` tax lot in the same security as the closing lot whose `acquired_at` falls inside that window." PRD §3.4: "the event's `disallowed_loss_cents` records the disallowed magnitude".

    Design: Difficulty/resource_temporal_overlap/wash_sale_window_inclusive_30day_boundary
    """
    _, executed = _setup_30day_boundary_harvest(api, "tov1b@x.com", "MM2", "NN2")
    assert executed["disallowed_loss_cents"] == 10000


# ─── harvest_reverse_restores_total_value_cents ─────────────────────
def test_reverse_restores_total_value_cents(api):
    """PRD §3.7: "The reversal is exact: the account's `total_value_cents` returns to precisely its pre-harvest value."

    Design: Difficulty/compensating_invariant/harvest_reverse_restores_total_value_cents
    """
    s = setup_executed_harvest(
        "2026-05-20T00:00:00.000Z", "inv1@x.com", src_ticker="OOO", repl_ticker="PPP"
    )
    # Pre-harvest total value: 5sh @ 10000 = 50000 invested, cash 0.
    get_success_data(api.reverse_harvest_event(s["harvest"]["id"], COMPLIANCE))
    acct = get_account(s["account"]["id"])
    assert acct["total_value_cents"] == 50000


def test_reverse_reopens_source_lot_and_marks_reversed(api):
    """PRD §3.7: "Reversal is a compensating undo that moves the event from `EXECUTED` to `REVERSED`: the replacement lot is closed with proceeds equal to its market value and the cash for its shares returned, the source lot is reopened to `OPEN` with its `disposed_at`, `proceeds_cents`, and `realized_gain_cents` cleared".

    Design: Difficulty/compensating_invariant/harvest_reverse_restores_total_value_cents
    """
    s = setup_executed_harvest(
        "2026-05-21T00:00:00.000Z", "inv1b@x.com", src_ticker="OO2", repl_ticker="PP2"
    )
    reversed_event = get_success_data(api.reverse_harvest_event(s["harvest"]["id"], COMPLIANCE))
    assert reversed_event["status"] == "REVERSED"
    assert get_tax_lot(s["source_lot"]["id"])["status"] == "OPEN"


# ─── harvest_reverse_restores_realized_gain_ytd ─────────────────────
def test_reverse_restores_ytd_realized_gain_and_wash_disallowed(api):
    """PRD §3.7: "the wash-sale disallowance applied at execution is unwound so that the account's `wash_sale_disallowed_cents_ytd` and `realized_gain_cents_ytd` are restored to their pre-harvest values and any cost-basis carryover bumped onto a survivor lot is undone".

    Design: Difficulty/compensating_invariant/harvest_reverse_restores_realized_gain_ytd
    """
    s = _execute_washsale_harvest(
        api, "2026-06-10T00:00:00.000Z", "inv2@x.com", src_ticker="QQQ", repl_ticker="RRR"
    )
    # After execute: realized_gain_cents_ytd == -6000, wash_sale_disallowed_cents_ytd == 4000.
    get_success_data(api.reverse_harvest_event(s["harvest"]["id"], COMPLIANCE))
    acct = get_account(s["account"]["id"])
    assert acct["realized_gain_cents_ytd"] == 0
    assert acct["wash_sale_disallowed_cents_ytd"] == 0


def test_reverse_clears_source_lot_wash_sale_disallowed(api):
    """PRD §3.7: "the wash-sale disallowance applied at execution is unwound so that the account's `wash_sale_disallowed_cents_ytd` and `realized_gain_cents_ytd` are restored to their pre-harvest values and any cost-basis carryover bumped onto a survivor lot is undone". PRD §3.7: "the source lot is reopened to `OPEN` with its `disposed_at`, `proceeds_cents`, and `realized_gain_cents` cleared".

    Design: Difficulty/compensating_invariant/harvest_reverse_restores_realized_gain_ytd
    """
    s = _execute_washsale_harvest(
        api, "2026-06-11T00:00:00.000Z", "inv2b@x.com", src_ticker="QQ2", repl_ticker="RR2"
    )
    get_success_data(api.reverse_harvest_event(s["harvest"]["id"], COMPLIANCE))
    source = get_tax_lot(s["source_lot"]["id"])
    assert source["wash_sale_disallowed_cents"] == 0
    assert source["status"] == "OPEN"
