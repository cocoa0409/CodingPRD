"""Monthly invoicing: tiered demand charge, round-then-sum energy subtotal, and
invoice-lifecycle guards.

Difficulty (queue A): combinatorial demand-charge min/max, round-then-sum order.
Corner (queue B): duplicate invoice per (depot, month), paying a DRAFT invoice.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, fm_headers,
)
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Difficulty: tiered demand charge with nested min/max over concurrent peak
# ---------------------------------------------------------------------------

def test_invoice_peak_demand_is_max_concurrent_load(api):
    """PRD §3.8: "over the set of qualifying sessions, evaluate at each session's
    `actual_start` instant the concurrent load, defined as the sum of `power_kw`
    over all qualifying sessions whose half-open active interval
    `[actual_start, actual_end)` contains that instant (a session counts at an
    instant at or after its own `actual_start` and strictly before its
    `actual_end`); the peak demand is the largest such concurrent load found at
    any session's start instant, or 0 if there are no qualifying sessions."

    Design: Difficulty/combinatorial_formula/invoice_demand_charge_tiered_minmax
    """
    inv = fx.setup_demand_charge_invoice(api)
    assert inv["peak_demand_kw"] == 250, f"S1 150 + S2 100 concurrent at 11:00, got {inv['peak_demand_kw']}"


def test_invoice_demand_charge_tiers_peak_against_contracted(api):
    """PRD §3.8: "it is the depot's `demand_rate_cents_per_kw` multiplied by the
    smaller of `peak_demand_kw` and `contracted_capacity_kw`, plus the depot's
    `overage_rate_cents_per_kw` multiplied by the amount of `peak_demand_kw`
    above `contracted_capacity_kw` (or zero if the peak does not exceed the
    contracted capacity), the whole rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/invoice_demand_charge_tiered_minmax
    """
    inv = fx.setup_demand_charge_invoice(api)
    # 1000*min(250,200) + 2500*max(0,250-200) = 200000 + 125000 = 325000.
    assert inv["demand_charge_cents"] == 325000, f"got {inv['demand_charge_cents']}"


# ---------------------------------------------------------------------------
# Difficulty: round-then-sum energy subtotal
# ---------------------------------------------------------------------------

def test_each_session_final_cost_rounds_to_whole_cent(api):
    """PRD §3.4: "sum these contributions across all overlapped windows and round
    the total half up to whole cents."

    Design: Difficulty/combinatorial_formula/invoice_energy_subtotal_round_then_sum
    """
    _, s1_id, s2_id = fx.setup_energy_subtotal_invoice(api)
    s1 = get_success_data(api.get_session(s1_id, fm_headers()))
    s2 = get_success_data(api.get_session(s2_id, fm_headers()))
    # 5.02 kWh * 20 c/kWh = 100.4c -> 100c each.
    assert s1["final_cost_cents"] == 100, f"got {s1['final_cost_cents']}"
    assert s2["final_cost_cents"] == 100, f"got {s2['final_cost_cents']}"


def test_invoice_energy_subtotal_is_round_then_sum(api):
    """PRD §3.8: "The **energy subtotal**, `energy_subtotal_cents`, is a
    round-then-sum aggregate: each qualifying session already carries a whole-cent
    `final_cost_cents` stamped at completion, and the subtotal is the direct
    integer sum of those stamped values — the system does not recompute a
    fractional per-session cost and round the total."

    Design: Difficulty/combinatorial_formula/invoice_energy_subtotal_round_then_sum
    """
    inv, _, _ = fx.setup_energy_subtotal_invoice(api)
    # 100 + 100 = 200 (round-then-sum); sum-then-round of 100.4+100.4 would give 201.
    assert inv["energy_subtotal_cents"] == 200, f"got {inv['energy_subtotal_cents']}"


# ---------------------------------------------------------------------------
# Corner: uniqueness and invalid transition
# ---------------------------------------------------------------------------

def test_duplicate_invoice_same_period_returns_error(api):
    """PRD §3.8: "Only one invoice may exist per depot and month: a second
    generation for the same pair is rejected with `ERR_DUPLICATE_INVOICE`
    (HTTP 409)."

    Design: Corner/validations/duplicate_invoice_same_period_returns_error
    """
    depot = fx.new_depot(api)
    fx.generate_invoice(api, depot["id"], "2026-05")
    from test_helpers import factories as fac
    resp = api.create_invoice(fac.create_invoice_payload(depot["id"], "2026-05"), fm_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE.value)


def test_pay_draft_invoice_returns_not_issued(api):
    """PRD §3.8: "A `FinanceManager` then marks an issued invoice paid, moving it
    `ISSUED → PAID`; paying an invoice not in `ISSUED` is rejected with
    `ERR_INVOICE_NOT_ISSUED` (HTTP 409)."

    Design: Corner/state_machines/pay_draft_invoice_returns_not_issued
    """
    depot = fx.new_depot(api)
    inv = fx.generate_invoice(api, depot["id"], "2026-05")
    assert inv["status"] == "DRAFT"
    resp = api.pay_invoice(inv["id"], fx.finance_headers())
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED.value)
