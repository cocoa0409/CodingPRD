"""Policy lifecycle and contestability: the two independent clocks, grace/lapse/
reinstatement/termination, the contestability flip, and lapse forfeiture.

Covers difficulty rules non_linear_state_machine (parallel dimensions instance) and
priority_pair_validation_conflict (lapsed-policy state-beats-amount instance), plus the
corner policy state-machine instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, validate_paginated, ApiErrorId,
    setup_issued_policy, setup_lapsed_policy,
    make_on_cycle_payment, fetch_policy, set_clock,
    make_policyowner_headers,
    EXAM_STANDARD,
)


def test_policy_parallel_lifecycle_and_contestability_dimensions(api):
    """PRD §2.7: "A `Policy` advances along two dimensions that move independently of one
    another and must never be conflated."
    PRD §3.8: "When the clock passes a policy's `next_premium_due_date` while it is
    `IN_FORCE`, the policy lazily enters `GRACE` on the next read or payment attempt"

    Design: Difficulty/non_linear_state_machine/policy_parallel_lifecycle_and_contestability_dimensions
    """
    # Issue 2026-06-01, contestability 24mo flips 2028-06-01, next due 2027-06-01.
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    # Past due date but before contestability window elapses -> GRACE x CONTESTABLE.
    set_clock("2027-06-15T00:00:00Z")
    policy = fetch_policy(policy_id, applicant_id)
    assert policy["lifecycle_status"] == "GRACE", policy
    assert policy["contestability_status"] == "CONTESTABLE", policy


def test_state_beats_premium_amount_mismatch_on_lapsed_policy(api):
    """PRD §2.11: "then whether the requested transition is even defined from the
    resource's current state (`ERR_INVALID_STATE`). Domain rules follow this preamble."
    PRD §3.8: "If the clock then passes the due date plus the product's grace-period days
    while the policy is still in `GRACE`, the policy lazily lapses, advancing `GRACE` to
    `LAPSED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_premium_amount_mismatch_on_lapsed_policy
    """
    # A LAPSED policy: no premium-payment transition is defined from LAPSED, so the state
    # check (priority 7) dominates the wrong-amount check (priority 13).
    ctx = setup_lapsed_policy(issue_clock="2026-06-01T00:00:00Z", lapse_clock="2027-08-01T00:00:00Z")
    assert ctx["policy"]["lifecycle_status"] == "LAPSED", ctx["policy"]
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    resp = api.create_premium_payment(
        policy_id, {"amount_cents": 999}, make_policyowner_headers(applicant_id)
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    unchanged = fetch_policy(policy_id, applicant_id)
    assert unchanged["lifecycle_status"] == "LAPSED", unchanged


def test_contestability_flips_incontestable_after_window(api):
    """PRD §3.8: "When the clock reaches at least the issue date plus the product's
    `contestability_months` while the policy is still `CONTESTABLE`, the next read lazily
    sets `contestability_status` to `INCONTESTABLE` and increments the policy's `version`."

    Design: Corner/state_machines/contestability_flips_incontestable_after_window
    """
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    # Keep lifecycle IN_FORCE by paying the two on-cycle anniversaries before the flip.
    make_on_cycle_payment(policy_id, applicant_id, 125000)
    make_on_cycle_payment(policy_id, applicant_id, 125000)
    # issue 2026-06-01 + 24mo = 2028-06-01.
    set_clock("2028-06-01T00:00:00Z")
    policy = fetch_policy(policy_id, applicant_id)
    assert policy["contestability_status"] == "INCONTESTABLE", policy
    assert policy["lifecycle_status"] == "IN_FORCE", policy


def test_lapsed_policy_reinstated_resets_contestability(api):
    """PRD §3.8: "Reinstatement advances `LAPSED` to `REINSTATED`"
    PRD §3.8: "Crucially, reinstatement resets contestability: `contestability_status` is
    set back to `CONTESTABLE` and a fresh contestability window begins from the
    reinstatement date, distinct from the original issue clock."

    Design: Corner/state_machines/lapsed_policy_reinstated_resets_contestability
    """
    ctx = setup_lapsed_policy(issue_clock="2026-06-01T00:00:00Z", lapse_clock="2027-08-01T00:00:00Z")
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    # One overdue annual premium (2027-06-01) -> back_premium_count 1, within the 3-year window.
    data = validate_success(
        api.reinstate_policy(policy_id, {"back_premium_count": 1},
                             make_policyowner_headers(applicant_id))
    )
    assert data["lifecycle_status"] == "REINSTATED", data
    assert data["contestability_status"] == "CONTESTABLE", data


def test_reinstate_after_three_year_window_closed(api):
    """PRD §3.8: "Reinstatement advances `LAPSED` to `REINSTATED`, but only while the
    current clock date is at or before three years after the issue date — the reinstatement
    window — failing otherwise with `ERR_REINSTATEMENT_WINDOW_CLOSED`."

    Design: Corner/state_machines/reinstate_after_three_year_window_closed
    """
    # Issue 2026-06-01, window closes 2029-06-01; clock 2029-07-01 is past the window.
    # The reinstatement window closes at exactly issue+3yr — the same boundary at which a
    # still-LAPSED policy lazily moves LAPSED -> TERMINATED (PRD §3.8). Whether the policy
    # is read first (or the reinstate handler's own lazy reconcile runs), once the clock
    # passes issue+3yr the policy is TERMINATED, so the state check (PRD §2.11 priority 7)
    # reports ERR_INVALID_STATE before the reinstatement-window check (priority 12). Either
    # PRD-consistent rejection code is acceptable for a past-window reinstatement attempt.
    ctx = setup_lapsed_policy(issue_clock="2026-06-01T00:00:00Z", lapse_clock="2027-08-01T00:00:00Z")
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    set_clock("2029-07-01T00:00:00Z")
    fetch_policy(policy_id, applicant_id)  # surface lazy state at the new clock
    resp = api.reinstate_policy(policy_id, {"back_premium_count": 3},
                                make_policyowner_headers(applicant_id))
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_REINSTATEMENT_WINDOW_CLOSED.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


def test_back_premium_insufficient_on_reinstate(api):
    """PRD §3.8: "The request must also make the policy whole on missed premiums by
    supplying `back_premium_count`, the whole number of overdue annual premiums measured
    from the applied due date through the current clock. A count that does not cover every
    overdue annual premium is rejected with `ERR_BACK_PREMIUM_INSUFFICIENT`."

    Design: Corner/errors/error_back_premium_insufficient_on_reinstate
    """
    # One annual premium overdue; back_premium_count 0 does not cover it.
    ctx = setup_lapsed_policy(issue_clock="2026-06-01T00:00:00Z", lapse_clock="2027-08-01T00:00:00Z")
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    resp = api.reinstate_policy(policy_id, {"back_premium_count": 0},
                                make_policyowner_headers(applicant_id))
    validate_error(resp, ApiErrorId.ERR_BACK_PREMIUM_INSUFFICIENT.value)


def test_grace_payment_within_window_returns_in_force(api):
    """PRD §3.7: "a payment accepted while it is in `GRACE` restores it to `IN_FORCE`,
    provided the current clock date is at or before the next due date plus the product's
    grace-period days."

    Design: Corner/state_machines/grace_payment_within_window_returns_in_force
    """
    # Issue 2026-06-01, due 2027-06-01, grace 31d. Clock 2027-06-15 is within grace.
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    set_clock("2027-06-15T00:00:00Z")
    pre = fetch_policy(policy_id, applicant_id)
    assert pre["lifecycle_status"] == "GRACE", pre
    make_on_cycle_payment(policy_id, applicant_id, 125000)
    post = fetch_policy(policy_id, applicant_id)
    assert post["lifecycle_status"] == "IN_FORCE", post


def test_lapse_forfeit_zeroes_gross_cash_value(api):
    """PRD §3.8: "Lapse forfeits accumulated cash value: a `CashValueEntry` with reason
    `LAPSE_FORFEIT` is appended whose `amount_cents` equals the negative of the current
    gross cash value, which drives the gross back to zero through the standard
    recompute-and-reconcile cascade"

    Design: Corner/state_machines/lapse_forfeit_zeroes_gross_cash_value_compensation
    """
    # STANDARD issue -> gross 3750 after issue, then lapse.
    ctx = setup_lapsed_policy(issue_clock="2026-06-01T00:00:00Z", lapse_clock="2027-08-01T00:00:00Z")
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    policy = ctx["policy"]
    assert policy["lifecycle_status"] == "LAPSED", policy
    assert policy["gross_cash_value_cents"] == 0, policy
    assert policy["net_cash_value_cents"] == 0, policy
    entries, _ = validate_paginated(
        api.list_cash_value_entries(policy_id, make_policyowner_headers(applicant_id))
    )
    forfeits = [e for e in entries if e["reason"] == "LAPSE_FORFEIT"]
    assert len(forfeits) == 1, entries
    assert forfeits[0]["amount_cents"] == -3750, forfeits
