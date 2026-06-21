"""Computed reads: the per-line-rounded group load score and the empty-set
CSAT index boundary.

Difficulty queue A: combinatorial_formula (group load), boundary_precision_check
(empty CSAT set).
"""
from test_helpers import (
    api_client,
    validate_success,
    fixtures as fx,
    test_users as U,
)


# ===========================================================================
# combinatorial_formula / group_load_score_per_line_round_then_sum
# ===========================================================================
def test_group_load_score_rounds_each_term_before_summing():
    """PRD §3.9: "For each such ticket, take its priority weight — eight for P1,
    four for P2, two for P3, one for P4 — multiply by a breach factor of
    one-and-a-half when the ticket's sla_state is RESPONSE_BREACHED or
    RESOLVE_BREACHED and one otherwise, divide by three, and round that per-ticket
    term half-up to two decimals. Sum the rounded per-ticket terms, then round the
    grand total half-up to one decimal place to produce the load_score."

    Design: Difficulty/combinatorial_formula/group_load_score_per_line_round_then_sum
    """
    _, group, category = fx.setup_catalog(default_priority="P1")
    for i in range(5):
        fx.open_ticket(category["id"], requester_id="req-load")

    data = validate_success(api_client.get_group_load(group["id"], U.agent("agent-1")))

    # Per line round(8/3, 2) = 2.67; 5*2.67 = 13.35 -> round 1dp = 13.4.
    # (Sum-raw-then-round would give 13.3.)
    assert data["load_score"] == 13.4, \
        f"per-line-then-sum must yield 13.4 (not 13.3), got {data['load_score']}"
    assert data["ticket_count"] == 5


def test_group_load_score_per_line_authoritative_not_sum_raw():
    """PRD §3.9: "The per-line rounding before summation is authoritative: summing
    the raw terms and rounding once would yield a different figure."

    Design: Difficulty/combinatorial_formula/group_load_score_per_line_round_then_sum
    """
    _, group, category = fx.setup_catalog(default_priority="P1")
    for i in range(5):
        fx.open_ticket(category["id"], requester_id="req-load2")

    data = validate_success(api_client.get_group_load(group["id"], U.agent("agent-1")))
    assert data["load_score"] == 13.4
    assert data["load_score"] != 13.3


# ===========================================================================
# boundary_precision_check / group_csat_empty_eligible_set_index_zero
# ===========================================================================
def test_group_csat_index_is_zero_for_empty_eligible_set():
    """PRD §3.7: "If the third step's denominator is zero, the csat_index is
    exactly 0.0."

    Design: Difficulty/boundary_precision_check/group_csat_empty_eligible_set_index_zero
    """
    group = fx.create_group(name="EmptyGrp")
    data = validate_success(api_client.get_group_csat(group["id"], U.agent("agent-1")))

    assert data["csat_index"] == 0.0, \
        f"empty eligible set must give csat_index 0.0, got {data['csat_index']}"
    assert data["eligible_count"] == 0


def test_group_csat_eligible_count_zero_when_no_surveys():
    """PRD §3.7: "The computed read reports csat_index, avg_score, response_rate,
    and the eligible_count of surveys that counted."

    Design: Difficulty/boundary_precision_check/group_csat_empty_eligible_set_index_zero
    """
    group = fx.create_group(name="EmptyGrp2")
    data = validate_success(api_client.get_group_csat(group["id"], U.agent("agent-1")))

    assert data["eligible_count"] == 0
    assert data["csat_index"] == 0.0
