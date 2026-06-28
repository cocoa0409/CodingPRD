"""Binding the policy, premium reconciliation, and the bind-time ledger.

Queue A: combinatorial_formula / premium_reconciliation_sum_of_rounded_rider_lines.
Queue B: bind preconditions, immediate-consistency, ledger-on-bind, idempotent bind.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    make_policyholder_headers, TEST_USERS, assert_policy,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX

_admin = TEST_USERS["admin_headers"]
_uw = TEST_USERS["underwriter_headers"]
_ph = make_policyholder_headers("ph-1")


def _quoted_with_two_clamped_riders():
    """Quoted SINGLE_EVENT policy: CANC coverage @150 + ATTIRE(100000) + GIFTS(5000000)."""
    product = FX.create_cancellation_product()
    venue = FX.create_venue()
    policy = FX.create_quoted_policy()
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    FX.add_coverage(policy["id"], product["id"])
    FX.add_rider(policy["id"], "ATTIRE", 100000)   # raw 1500 -> clamp up to 2500
    FX.add_rider(policy["id"], "GIFTS", 5000000)    # raw 75000 -> clamp down to 50000
    return policy


def test_premium_reconciliation_sum_of_rounded_rider_lines(api):
    """PRD §3.4: "The policy's `base_premium_cents` is the sum of `rated_premium_cents`
    over coverage lines whose status is `SELECTED` or `ACTIVE`".
    PRD §3.4: "Because each rider line is already a clamped whole-cent figure and each
    coverage line is already a whole-cent figure, the reconciliation is strictly a sum of
    already-rounded line subtotals, performed in that pinned order — sum-of-rounded-lines,
    never round-of-sum."

    Design: Difficulty/combinatorial_formula/premium_reconciliation_sum_of_rounded_rider_lines
    """
    policy = _quoted_with_two_clamped_riders()
    bound = validate_success(api.bind_policy(policy["id"], _uw), 200)
    assert bound["base_premium_cents"] == 65000
    assert bound["rider_premium_cents"] == 52500   # 2500 + 50000
    assert bound["total_premium_cents"] == 117500  # 65000 + 52500
    assert bound["lifecycle_status"] == "BOUND"


def test_premium_reconciliation_total_is_base_plus_rider(api):
    """PRD §3.4: "The policy's `total_premium_cents` is the sum of those two aggregates."
    PRD §3.3: "this rounded-up figure is then clamped so that it is never below a floor of
    2,500 cents and never above a ceiling of 50,000 cents."

    Design: Difficulty/combinatorial_formula/premium_reconciliation_sum_of_rounded_rider_lines
    """
    policy = _quoted_with_two_clamped_riders()
    bound = validate_success(api.bind_policy(policy["id"], _uw), 200)
    assert_policy(bound)
    assert bound["total_premium_cents"] == bound["base_premium_cents"] + bound["rider_premium_cents"]
    assert bound["total_premium_cents"] == 117500


def test_bind_policy_with_no_coverage_selected_rejected(api):
    """PRD §3.4: "There must be at least one coverage line in `SELECTED` status, or
    `ERR_NO_COVERAGE_SELECTED` is returned."

    Design: Corner/state_machines/bind_policy_with_no_coverage_selected_rejected
    """
    venue = FX.create_venue()
    policy = FX.create_quoted_policy()
    FX.add_event_profile(policy["id"], venue["id"])
    res = api.bind_policy(policy["id"], _uw)
    validate_error(res, "ERR_NO_COVERAGE_SELECTED", 422)
    refreshed = validate_success(api.get_policy(policy["id"], _uw), 200)
    assert refreshed["lifecycle_status"] == "QUOTED"


def test_bind_policy_with_no_event_profile_rejected(api):
    """PRD §3.4: "There must be at least one event profile, or `ERR_NO_EVENT_PROFILE` is
    returned."

    Design: Corner/state_machines/bind_policy_with_no_event_profile_rejected
    """
    product = FX.create_cancellation_product()
    policy = FX.create_quoted_policy()
    FX.add_coverage(policy["id"], product["id"])
    res = api.bind_policy(policy["id"], _uw)
    validate_error(res, "ERR_NO_EVENT_PROFILE", 422)


def test_bind_already_bound_policy_returns_invalid_state(api):
    """PRD §3.4: "The policy must currently be `QUOTED`, or the request is rejected with
    `ERR_POLICY_NOT_QUOTED`."

    Design: Corner/state_machines/bind_already_bound_policy_returns_invalid_state
    """
    ctx = FX.setup_bound_policy_canc_only()
    res = api.bind_policy(ctx["policy"]["id"], _uw)
    validate_error(res, "ERR_POLICY_NOT_QUOTED", 409)


def test_immediate_premium_visible_in_bind_response(api):
    """PRD §3.4: "Binding is the moment premium is computed and charged".
    PRD §3.4: "A coverage line's `rated_premium_cents` is the product's
    `base_premium_cents` plus its `per_guest_premium_cents` multiplied by that total
    attendance."

    Design: Corner/consistency_model/immediate_premium_visible_in_bind_response
    """
    ctx = FX.setup_quoted_single_event(attendance=150)
    bound = validate_success(api.bind_policy(ctx["policy"]["id"], _uw), 200)
    assert bound["total_premium_cents"] == 65000
    assert bound["lifecycle_status"] == "BOUND"


def test_ledger_records_premium_charge_on_bind(api):
    """PRD §3.4: "The premium charge written to the ledger at bind is a `PREMIUM_CHARGE`
    entry whose `amount_cents` equals the positive `total_premium_cents`."

    Design: Corner/cross_cutting_complexity_layers/ledger_records_premium_charge_on_bind
    """
    ctx = FX.setup_quoted_single_event(attendance=150)
    FX.bind_policy(ctx["policy"]["id"])
    data, meta = validate_paginated(api.list_ledger(ctx["policy"]["id"], _uw))
    assert meta["total_count"] == 1
    charges = [e for e in data if e["entry_kind"] == "PREMIUM_CHARGE"]
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 65000
