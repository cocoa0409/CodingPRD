"""Valid / invalid state transitions, terminal lockdown, initial state, preconditions.

Translates corner-design instances under section: state_machines (queue B).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    set_clock, create_fund, create_share_class, create_project, create_approved_investor,
    create_subscription, settle_subscription, declare_distribution,
    make_fund_manager_headers, make_operator_headers, make_investor_headers,
)

FM = make_fund_manager_headers()
OP = make_operator_headers()


def test_cancel_subscription_from_settled_returns_invalid_state(api):
    """PRD §3.4: "An `Investor` who has not yet funded may cancel an unsettled subscription,
    transitioning `PENDING_ACH → CANCELLED`; this is allowed only while the subscription is
    `PENDING_ACH`".
    PRD §3.1: "Any of these transitions attempted from a state in which they are not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cancel_subscription_from_settled_returns_invalid_state
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    inv_headers = make_investor_headers(inv["id"])
    res = api.cancel_subscription(sub["id"], inv_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_project_dispose_then_stabilize_terminal_lockdown(api):
    """PRD §3.2: "and may dispose of a project, transitioning it to `DISPOSED` from either
    `STABILIZED` or directly from `ACQUIRED`. Disposal is terminal ... An out-of-state transition
    yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/project_dispose_then_stabilize_terminal_lockdown
    """
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    proj = create_project(fund["id"], name="Proj 1",
                          acquisition_cost_cents=1_000_000, appraised_value_cents=1_000_000)
    get_success_data(api.dispose_project(proj["id"], FM))
    res = api.stabilize_project(proj["id"], FM)
    validate_error(res, "ERR_INVALID_STATE")


def test_subscription_initial_state_pending_ach(api):
    """PRD §3.4: "A subscription is created in `PENDING_ACH`."
    PRD §3.4: "At create time the system captures a **provisional** price quote, recording the
    fund's current `nav_per_share_cents` into the subscription's `provisional_nav_cents`".

    Design: Corner/state_machines/subscription_initial_state_pending_ach
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    assert sub["status"] == "PENDING_ACH"
    assert sub["provisional_nav_cents"] == 1000


def test_settle_already_settled_subscription_rejected(api):
    """PRD §3.4: "Settlement is where capital actually enters the fund, and it is an `Operator`
    action that transitions `PENDING_ACH → SETTLED`. Settlement runs a battery of preconditions.
    The subscription must be `PENDING_ACH`."
    PRD §3.1: "Any of these transitions attempted from a state in which they are not defined is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/settle_already_settled_subscription_idempotency_rejected
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    res = api.settle_subscription(sub["id"], OP)
    validate_error(res, "ERR_INVALID_STATE")


def test_distribution_pay_before_valuation_returns_no_valuation(api):
    """PRD §3.6: "It is permitted only when the distribution is `DECLARED` and only when the fund
    has at least one posted valuation — that is, the fund's `current_valuation_seq` is at least 1 —
    because a NAV must exist to price any reinvestment; otherwise it is rejected with
    `ERR_NO_VALUATION` (HTTP 409)."

    Design: Corner/state_machines/distribution_pay_before_valuation_returns_no_valuation
    """
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    dist = declare_distribution(fund["id"], period_label="2026-Q1", dividend_per_share_cents=1.5)
    res = api.pay_distribution(dist["id"], OP)
    validate_error(res, "ERR_NO_VALUATION")


def test_share_class_resume_cycle_back_to_offering(api):
    """PRD §3.2: "A `FundManager` may suspend an offering, transitioning `OFFERING → SUSPENDED`".
    PRD §3.2: "The manager may resume a suspended class, transitioning `SUSPENDED → OFFERING`; this
    is allowed only when the class is `SUSPENDED` and its parent fund is `OPEN`".

    Design: Corner/state_machines/share_class_resume_cycle_back_to_offering
    """
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    get_success_data(api.suspend_share_class(sc["id"], FM))
    resumed = get_success_data(api.resume_share_class(sc["id"], FM))
    assert resumed["status"] == "OFFERING"
