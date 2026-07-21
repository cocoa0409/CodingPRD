"""Estimate valuation: RCV vs ACV net-payable variants and per-line rounding order."""
from test_helpers import validate_success, make_field_adjuster_headers
from test_helpers import fixtures as fx
from test_helpers import create_estimate_payload

# Two lines, each rcv 10001 at 50% depreciation.
# rcv_total = 20002; acv per line = round_half_up(5000.5) = 5001, summed = 10002.
LINE_ITEMS = [
    {"description": "L1", "rcv_cents": 10001, "depreciation_pct": 50},
    {"description": "L2", "rcv_cents": 10001, "depreciation_pct": 50},
]


def _estimate_on_completed_inspection(api, policy_type):
    ctx = fx.setup_completed_inspection(api, loss_state="FL", peril_type="HAIL",
                                        policy_type=policy_type)
    payload = create_estimate_payload(ctx["insp_id"], ctx["claim_id"], line_items=LINE_ITEMS)
    data = validate_success(api.create_estimate(payload, make_field_adjuster_headers(ctx["adj_id"])), 201)
    return data


def test_rcv_policy_net_payable_is_rcv_total(api):
    """PRD 3.4: "Finally the net_payable_cents is variant by the parent claim's
    policy_type: for an ACV policy it equals acv_total_cents (the depreciated value
    only), and for an RCV policy it equals rcv_total_cents (full replacement cost,
    with the recoverable depreciation held for later release)."

    Design: Difficulty/dual_variant_calc/estimate_rcv_vs_acv_net_payable
    """
    data = _estimate_on_completed_inspection(api, "RCV")
    assert data["net_payable_cents"] == 20002
    # Both variants are computed regardless of policy.
    assert data["rcv_total_cents"] == 20002
    assert data["acv_total_cents"] == 10002


def test_acv_policy_net_payable_is_acv_total(api):
    """PRD 3.4: "Finally the net_payable_cents is variant by the parent claim's
    policy_type: for an ACV policy it equals acv_total_cents (the depreciated value
    only), and for an RCV policy it equals rcv_total_cents (full replacement cost,
    with the recoverable depreciation held for later release)."

    Design: Difficulty/dual_variant_calc/estimate_rcv_vs_acv_net_payable
    """
    data = _estimate_on_completed_inspection(api, "ACV")
    assert data["net_payable_cents"] == 10002


def test_acv_total_uses_per_line_round_half_up(api):
    """PRD 2.7: "When depreciating a line item to its actual cash value, the result is
    rounded half-up to whole cents per line item, before the lines are summed — never
    sum-then-round."

    Design: Difficulty/combinatorial_formula/estimate_perline_rounding_order
    """
    data = _estimate_on_completed_inspection(api, "ACV")
    # Per-line: round_half_up(5000.5) = 5001 twice -> 10002 (not sum-then-round 10001).
    assert data["acv_total_cents"] == 10002


def test_recoverable_depreciation_is_rcv_minus_acv(api):
    """PRD 3.4: "The recoverable_depreciation_cents is the rcv_total_cents minus the
    acv_total_cents."

    Design: Difficulty/combinatorial_formula/estimate_perline_rounding_order
    """
    data = _estimate_on_completed_inspection(api, "ACV")
    assert data["recoverable_depreciation_cents"] == 10000
