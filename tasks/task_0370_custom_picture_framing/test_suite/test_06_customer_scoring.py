"""Customer reliability scoring: forward no-show risk vs settled reputation, and
the pickup cascade into open-order count / no-show risk.

Translates queue A (Difficulty) dual_variant_calc (customer-scoring instance) and
transitive_cascade (pickup instance).
"""
from test_helpers import (
    get_success_data, TEST_USERS,
    create_customer, create_order, add_line, measure_line, quote, pay,
    create_workbench, setup_picked_up_order,
)

DESIGNER = TEST_USERS["frame_designer_headers"]
TECH = TEST_USERS["frame_production_tech_headers"]
CLERK = TEST_USERS["front_desk_clerk_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc / customer_forward_risk_vs_settled_reputation_diverge
# ===========================================================================
def test_forward_risk_vs_settled_reputation_diverge_after_abandon(api):
    """PRD §3.1: "the score is the count of open orders multiplied by 5, plus the
    count of ready-but-unpaid open orders multiplied by 15, with the smaller of that
    sum and 100 taken as the final value."
    PRD §3.1: "an on-time outcome subtracts 10 from the running score and an abandon
    outcome adds 20 to it; after each individual step the running score is clamped to
    the range from 0 to 100."

    One open order -> forward risk 5; one ABANDON -> settled 50+20=70. The two scores
    diverge.

    Design: Difficulty/dual_variant_calc/customer_forward_risk_vs_settled_reputation_diverge
    """
    cust = create_customer(loyalty_tier="STANDARD", email="bo@x.com", full_name="Bo Risk")
    order_a = create_order(cust["id"])  # open
    order_b = create_order(cust["id"])  # will be cancelled
    get_success_data(api.cancel_order(order_b["id"], CLERK))
    refreshed = get_success_data(api.get_customer(cust["id"], CLERK))
    assert refreshed["open_order_count"] == 1
    assert refreshed["no_show_risk_score"] == 5
    assert refreshed["settled_reputation_score"] == 70
    assert refreshed["no_show_risk_score"] != refreshed["settled_reputation_score"]


def test_seeded_scores_diverge_from_open_risk(api):
    """PRD §3.1: "At creation the customer's reliability fields are seeded —
    `no_show_risk_score` starts at 0 and `settled_reputation_score` starts at 50".
    PRD §3.1: "it weights every open order by 5 points".

    Second test for the risk-vs-reputation divergence: a fresh customer reads
    (no_show 0, settled 50); after opening one order the forward risk moves to 5 while
    settled reputation stays at its seed 50 (no terminal outcome yet), so the two
    diverge from a different starting configuration.

    Design: Difficulty/dual_variant_calc/customer_forward_risk_vs_settled_reputation_diverge
    """
    cust = create_customer(loyalty_tier="STANDARD", email="bo2@x.com")
    assert cust["no_show_risk_score"] == 0
    assert cust["settled_reputation_score"] == 50
    create_order(cust["id"])  # one open order
    refreshed = get_success_data(api.get_customer(cust["id"], CLERK))
    assert refreshed["no_show_risk_score"] == 5
    assert refreshed["settled_reputation_score"] == 50
    assert refreshed["no_show_risk_score"] != refreshed["settled_reputation_score"]


# ===========================================================================
# Difficulty: transitive_cascade / pickup_triggers_open_count_then_no_show_risk_recompute
# ===========================================================================
def test_pickup_triggers_open_count_then_no_show_risk_recompute(api):
    """PRD §3.7: "the owning customer's `open_order_count` is recomputed because this
    order has left the open set, the customer's `no_show_risk_score` is recomputed
    because the projected open set has shrunk".
    PRD §3.1: "the score is the count of open orders multiplied by 5, plus the count
    of ready-but-unpaid open orders multiplied by 15".

    With two other open orders remaining after pickup, open_order_count is 2 and
    no_show_risk_score falls to 10.

    Design: Difficulty/transitive_cascade/pickup_triggers_open_count_then_no_show_risk_recompute
    """
    cust = create_customer(email="hal@x.com", full_name="Hal Pick")
    bench = create_workbench(bench_type="ASSEMBLY", bench_name="Asm P")
    create_order(cust["id"])  # o1 open
    create_order(cust["id"])  # o2 open
    ox = create_order(cust["id"], deposit_pct=0.30)
    lx = add_line(ox["id"], ox["version"], artwork_label="X",
                  nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    measure_line(lx["id"], 8, 10)
    quoted = quote(ox["id"])
    pay(quoted["id"], "DEPOSIT", 25.00)
    get_success_data(api.start_production(quoted["id"], TECH))
    tx = get_success_data(api.create_task(
        {"order_id": quoted["id"], "workbench_id": bench["id"], "start_minute": 0, "end_minute": 30}, TECH))
    get_success_data(api.complete_task(tx["id"], TECH))
    get_success_data(api.mark_ready(quoted["id"], TECH))
    pay(quoted["id"], "BALANCE", 39.47)
    get_success_data(api.pickup_order(quoted["id"], CLERK))
    refreshed = get_success_data(api.get_customer(cust["id"], CLERK))
    assert refreshed["open_order_count"] == 2
    assert refreshed["no_show_risk_score"] == 10


def test_pickup_shrinks_open_set_to_zero_risk(api):
    """PRD §3.7: "the owning customer's `open_order_count` is recomputed because this
    order has left the open set, the customer's `no_show_risk_score` is recomputed
    because the projected open set has shrunk".
    PRD §3.1: "The **open order count**, `open_order_count`, is the number of this
    customer's framing orders whose `production_status` is neither `PICKED_UP` nor
    `CANCELLED`."

    Second test for the pickup cascade: with no other open orders, pickup drops
    open_order_count to 0 and no_show_risk_score to 0.

    Design: Difficulty/transitive_cascade/pickup_triggers_open_count_then_no_show_risk_recompute
    """
    cust, picked, line, bench, task = setup_picked_up_order()
    refreshed = get_success_data(api.get_customer(cust["id"], CLERK))
    assert refreshed["open_order_count"] == 0
    assert refreshed["no_show_risk_score"] == 0
