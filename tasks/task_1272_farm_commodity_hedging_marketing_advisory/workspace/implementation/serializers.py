"""Entity -> JSON dict serializers (convert Decimals to floats)."""

from helpers import to_float


def _decimalize_out(entity, decimal_fields):
    out = dict(entity)
    for f in decimal_fields:
        if f in out and out[f] is not None:
            out[f] = to_float(out[f])
    return out


OPERATION_FIELDS = []
def ser_operation(o):
    return dict(o)


BASELINE_DECIMALS = ["aph_yield_bushels", "trend_yield_bushels"]
def ser_baseline(b):
    return _decimalize_out(b, BASELINE_DECIMALS)


POLICY_DECIMALS = ["coverage_level_pct", "projected_price", "harvest_price", "indemnity_dollars"]
def ser_policy(p):
    return _decimalize_out(p, POLICY_DECIMALS)


PLAN_DECIMALS = ["max_priced_pct"]
def ser_plan(p):
    return _decimalize_out(p, PLAN_DECIMALS)


TARGET_DECIMALS = ["target_price"]
def ser_target(t):
    return _decimalize_out(t, TARGET_DECIMALS)


REC_DECIMALS = ["strike_price", "premium_per_bushel"]
def ser_recommendation(r):
    return _decimalize_out(r, REC_DECIMALS)


POSITION_DECIMALS = [
    "entry_price", "exit_price", "initial_margin_dollars",
    "maintenance_margin_dollars", "unrealized_pnl", "realized_pnl",
    "strike_price", "premium_per_bushel",
]
def ser_position(p):
    return _decimalize_out(p, POSITION_DECIMALS)


ACCOUNT_DECIMALS = [
    "cash_balance", "initial_margin_required", "maintenance_margin_required",
    "margin_equity", "margin_call_amount",
]
def ser_account(a):
    return _decimalize_out(a, ACCOUNT_DECIMALS)


def ser_buyer(b):
    return dict(b)


CONTRACT_DECIMALS = [
    "fixed_price", "basis_level", "fixation_price", "effective_price",
    "settled_value_dollars", "default_penalty_dollars", "delivered_bushels",
]
def ser_contract(c):
    return _decimalize_out(c, CONTRACT_DECIMALS)


TICKET_DECIMALS = ["moisture_pct", "shrink_pct", "net_bushels", "ticket_value_dollars"]
def ser_ticket(t):
    return _decimalize_out(t, TICKET_DECIMALS)


LOT_DECIMALS = ["cost_per_bushel_month", "annual_interest_rate"]
def ser_lot(l):
    return _decimalize_out(l, LOT_DECIMALS)


AGREEMENT_DECIMALS = ["rate_per_bushel", "flat_annual_fee", "annual_cap_dollars", "billable_bushels_accrued"]
def ser_agreement(a):
    return _decimalize_out(a, AGREEMENT_DECIMALS)


TICK_DECIMALS = ["price"]
def ser_tick(t):
    return _decimalize_out(t, TICK_DECIMALS)
